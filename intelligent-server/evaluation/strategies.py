"""
RAG 检索策略实现
- No-RAG: 直接问大模型，不检索
- Vector-only: 仅向量检索
- Hybrid: 关键词+语义混合（后续补）
"""

import time
import logging
import math
import os
from typing import List, Dict, Any, Tuple, Optional
from abc import ABC, abstractmethod
from pymongo import MongoClient
from openai import OpenAI

logger = logging.getLogger(__name__)


class RAGStrategy(ABC):
    """RAG 策略基类"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.db_client = None
        self.llm_client = None
    
    def get_db(self):
        """获取 MongoDB 连接"""
        if self.db_client is None:
            self.db_client = MongoClient(self.config["mongo_uri"])
        return self.db_client[self.config["db_name"]]
    
    def get_llm_client(self):
        """获取 LLM 客户端"""
        if self.llm_client is None:
            # Temporarily disable HTTP proxy environment variables
            # to avoid openai client initialization issues
            saved_proxies = {}
            proxy_env_vars = ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy']
            for var in proxy_env_vars:
                if var in os.environ:
                    saved_proxies[var] = os.environ.pop(var)
            
            try:
                self.llm_client = OpenAI(
                    api_key=self.config["aihubmix_api_key"],
                    base_url=self.config["aihubmix_base_url"]
                )
            finally:
                # Restore proxy environment variables
                for var, val in saved_proxies.items():
                    os.environ[var] = val
        
        return self.llm_client
    
    @abstractmethod
    def retrieve(self, query: str, top_k: int = 10) -> Tuple[List[str], Dict[str, Any]]:
        """
        执行检索
        Args:
            query: 查询文本
            top_k: 返回结果数
        Returns:
            (retrieved_ids, metadata)
        """
        pass
    
    @abstractmethod
    def generate(self, query: str, context: Optional[str] = None) -> Tuple[str, Dict[str, Any]]:
        """
        生成回答
        Args:
            query: 查询文本
            context: 可选的上下文（检索结果）
        Returns:
            (answer, metadata)
        """
        pass
    
    def cleanup(self):
        """清理资源"""
        if self.db_client:
            self.db_client.close()


class NoRAGStrategy(RAGStrategy):
    """不使用RAG，直接对大模型提问"""
    
    def retrieve(self, query: str, top_k: int = 10) -> Tuple[List[str], Dict[str, Any]]:
        """
        No-RAG 不检索
        """
        return [], {"strategy": "no_rag", "retrieval_time": 0.0}
    
    def generate(self, query: str, context: Optional[str] = None) -> Tuple[str, Dict[str, Any]]:
        """
        直接对 LLM 提问，不使用任何上下文
        """
        llm_client = self.get_llm_client()
        
        system_prompt = "你是一个有帮助的助手。尽可能详细和准确地回答用户的问题。"
        
        start_time = time.time()
        
        try:
            response = llm_client.chat.completions.create(
                model=self.config["llm_model"],
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": query}
                ],
                temperature=self.config["llm_temperature"],
                max_completion_tokens=self.config["llm_max_tokens"],
            )
            
            answer = response.choices[0].message.content
            elapsed = time.time() - start_time
            
            return answer, {
                "strategy": "no_rag",
                "generation_time": elapsed,
                "input_tokens": response.usage.prompt_tokens,
                "output_tokens": response.usage.completion_tokens,
            }
        
        except Exception as e:
            logger.exception("No-RAG 生成失败")
            return "", {"strategy": "no_rag", "error": str(e)}


class VectorOnlyStrategy(RAGStrategy):
    """仅使用向量检索"""
    
    def cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """计算向量余弦相似度"""
        if not vec1 or not vec2 or len(vec1) != len(vec2):
            return 0.0
        
        dot_product = sum(a * b for a, b in zip(vec1, vec2))
        magnitude1 = math.sqrt(sum(a ** 2 for a in vec1))
        magnitude2 = math.sqrt(sum(b ** 2 for b in vec2))
        
        if magnitude1 == 0 or magnitude2 == 0:
            return 0.0
        
        return dot_product / (magnitude1 * magnitude2)
    
    def retrieve(self, query: str, top_k: int = 10) -> Tuple[List[str], Dict[str, Any]]:
        """
        使用向量检索
        """
        llm_client = self.get_llm_client()
        db = self.get_db()
        
        start_time = time.time()
        
        try:
            # 1. 生成查询向量
            query_embedding = llm_client.embeddings.create(
                model=self.config["embedding_model"],
                input=query
            ).data[0].embedding
            
            embedding_time = time.time() - start_time
            
            # 2. 检索模型
            retrieval_start = time.time()
            
            model_collection = db["modelembeddings"]
            all_models = list(model_collection.find({}))
            
            scored_models = []
            for model in all_models:
                if model.get("embedding") and len(model.get("embedding", [])) > 0:
                    score = self.cosine_similarity(query_embedding, model["embedding"])
                    scored_models.append({
                        "modelMd5": model.get("modelMd5"),
                        "modelName": model.get("modelName"),
                        "description": model.get("modelDescription"),
                        "score": score
                    })
            
            # 排序并取 top-k
            scored_models.sort(key=lambda x: x["score"], reverse=True)
            result = scored_models[:top_k]
            
            retrieved_ids = [m["modelMd5"] for m in result]
            retrieval_time = time.time() - retrieval_start
            
            return result, {
                "strategy": "vector_only",
                "embedding_time": embedding_time,
                "retrieval_time": retrieval_time,
                "retrieved_count": len(retrieved_ids),
                "scores": [m["score"] for m in result],
            }
        
        except Exception as e:
            logger.exception("向量检索失败")
            return [], {"strategy": "vector_only", "error": str(e)}
        
    def build_context(self, retrieved_docs: List[Dict[str, Any]]) -> str:
        """构建生成上下文"""
        context_parts = []

        for idx, doc in enumerate(retrieved_docs, 1):
            text = f"""
                模型 {idx}:
                模型名称: {doc.get('modelName', '')}
                模型描述: {doc.get('description', '')}
                相似度: {doc.get('score', 0):.4f}
                """
            context_parts.append(text)

        return "\n".join(context_parts)
    
    def generate(self, query: str, context: Optional[str] = None) -> Tuple[str, Dict[str, Any]]:
        """
        基于检索结果和查询生成回答
        """
        llm_client = self.get_llm_client()
        
        system_prompt = "你是一个地理信息科学和水文模型领域的专家。根据提供的模型信息回答用户的问题。"
        
        if context:
            user_message = f"基于以下模型信息，回答问题:\n\n{context}\n\n问题: {query}"
        else:
            user_message = f"问题: {query}"
        
        start_time = time.time()
        
        try:
            response = llm_client.chat.completions.create(
                model=self.config["llm_model"],
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message}
                ],
                temperature=self.config["llm_temperature"],
                max_completion_tokens=self.config["llm_max_tokens"],
            )
            
            answer = response.choices[0].message.content
            elapsed = time.time() - start_time
            
            return answer, {
                "strategy": "vector_only",
                "generation_time": elapsed,
                "input_tokens": response.usage.prompt_tokens,
                "output_tokens": response.usage.completion_tokens,
            }
        
        except Exception as e:
            logger.exception("Vector-only 生成失败")
            return "", {"strategy": "vector_only", "error": str(e)}


def create_strategy(strategy_name: str, config: Dict[str, Any]) -> RAGStrategy:
    """工厂函数：创建策略实例"""
    strategy_map = {
        "no_rag": NoRAGStrategy,
        "vector_only": VectorOnlyStrategy,
    }
    
    if strategy_name not in strategy_map:
        raise ValueError(f"Unknown strategy: {strategy_name}")
    
    return strategy_map[strategy_name](config)
