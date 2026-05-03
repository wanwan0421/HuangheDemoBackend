"""
RAG 检索策略实现
- No-RAG: 直接问大模型，不检索
- Vector-only: 仅向量检索
- Hybrid: 关键词+语义混合（Milvus）
"""

import time
import logging
import math
import os
from typing import List, Dict, Any, Tuple, Optional
from abc import ABC, abstractmethod
from pymongo import MongoClient
from pymilvus import RRFRanker, connections, Collection, AnnSearchRequest, WeightedRanker
from openai import OpenAI

logger = logging.getLogger(__name__)


class RAGStrategy(ABC):
    """RAG 策略基类"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.db_client = None
        self.llm_client = None
        self.milvus_collection = None
    
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

    def build_context(self, retrieved_docs: List[Dict[str, Any]]) -> str:
        """默认上下文构建，供无检索或空检索策略复用。"""
        if not retrieved_docs:
            return ""

        context_parts = []
        for idx, doc in enumerate(retrieved_docs, 1):
            description = doc.get("description") or doc.get("modelDescription") or ""
            text = f"""
                模型 {idx}:
                模型名称: {doc.get('modelName', '')}
                模型描述: {description}
                相似度: {doc.get('score', 0):.4f}
                """
            context_parts.append(text)

        return "\n".join(context_parts)

    def get_milvus_collection(self) -> Collection:
        """获取 Milvus collection 连接。"""
        if self.milvus_collection is None:
            connections.connect(
                alias="default",
                host=self.config.get("milvus_host", "localhost"),
                port=int(self.config.get("milvus_port", 19530)),
            )
            self.milvus_collection = Collection(self.config.get("milvus_collection", "modelembeddings"))
            self.milvus_collection.load()
        return self.milvus_collection
    
    def cleanup(self):
        """清理资源"""
        if self.db_client:
            self.db_client.close()
        if self.milvus_collection:
            try:
                self.milvus_collection.release()
            except Exception:
                logger.debug("release Milvus collection failed", exc_info=True)


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
        """使用 Milvus Dense-only 检索，不再扫描 MongoDB。"""
        llm_client = self.get_llm_client()
        
        start_time = time.time()
        
        try:
            # 1. 生成查询向量
            query_embedding = llm_client.embeddings.create(
                model=self.config["embedding_model"],
                input=query
            ).data[0].embedding
            
            embedding_time = time.time() - start_time
            
            retrieval_start = time.time()
            
            collection = self.get_milvus_collection()
            search_result = collection.search(
                data=[query_embedding],
                anns_field="embedding",
                param={"metric_type": "COSINE", "params": {"ef": 128}},
                limit=top_k,
                output_fields=["modelId", "modelMd5", "modelName", "modelDescription", "embeddingSource"],
            )

            hits = HybridStrategy._extract_hits(search_result)
            result = []
            for rank, hit in enumerate(hits, start=1):
                description = HybridStrategy._safe_hit_value(hit, "modelDescription")
                result.append({
                    "modelId": HybridStrategy._safe_hit_value(hit, "modelId"),
                    "modelMd5": HybridStrategy._safe_hit_value(hit, "modelMd5"),
                    "modelName": HybridStrategy._safe_hit_value(hit, "modelName"),
                    "description": description,
                    "modelDescription": description,
                    "embeddingSource": HybridStrategy._safe_hit_value(hit, "embeddingSource"),
                    "score": float(getattr(hit, "score", 0.0) or 0.0),
                    "rank": rank,
                })

            retrieved_ids = [m.get("modelMd5") for m in result if m.get("modelMd5")]
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


class HybridStrategy(VectorOnlyStrategy):
    """使用 Milvus 语义 + 关键词（BM25）混合检索。"""

    @staticmethod
    def _collection_has_sparse_field(collection: Collection) -> bool:
        try:
            schema = getattr(collection, "schema", None)
            fields = getattr(schema, "fields", None) or []
            for field in fields:
                if getattr(field, "name", "") == "sparse":
                    return True
            return False
        except Exception:
            return False

    @staticmethod
    def _safe_hit_value(hit: Any, field_name: str) -> Any:
        if isinstance(hit, dict):
            return hit.get(field_name)

        if hasattr(hit, "get"):
            try:
                return hit.get(field_name)
            except Exception:
                pass

        entity = getattr(hit, "entity", None)
        if entity is not None:
            try:
                return entity.get(field_name)
            except Exception:
                pass

        return getattr(hit, field_name, None)

    @staticmethod
    def _extract_hits(search_result: Any) -> List[Any]:
        candidates: List[Any] = []

        if isinstance(search_result, dict):
            candidates.extend([search_result.get("results"), search_result.get("data")])
        else:
            candidates.append(getattr(search_result, "results", None))
            candidates.append(getattr(search_result, "data", None))
            candidates.append(search_result)

        for candidate in candidates:
            if candidate is None:
                continue

            if isinstance(candidate, list):
                if len(candidate) > 0 and isinstance(candidate[0], list):
                    return candidate[0]
                return candidate

            if hasattr(candidate, "__iter__") and not isinstance(candidate, (str, bytes, dict)):
                try:
                    items = list(candidate)
                    if len(items) > 0 and isinstance(items[0], list):
                        return items[0]
                    if items:
                        return items
                except Exception:
                    continue

        return []

    def _make_weighted_ranker(self):
        semantic_weight = float(self.config.get("hybrid_semantic_weight", 0.8))
        keyword_weight = float(self.config.get("hybrid_keyword_weight", 0.2))
        try:
            return WeightedRanker(semantic_weight, keyword_weight)
        except TypeError:
            return WeightedRanker([semantic_weight, keyword_weight])

    def _format_hits(self, hits: List[Any]) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        for rank, hit in enumerate(hits, start=1):
            description = self._safe_hit_value(hit, "modelDescription")
            results.append({
                "modelId": self._safe_hit_value(hit, "modelId"),
                "modelMd5": self._safe_hit_value(hit, "modelMd5"),
                "modelName": self._safe_hit_value(hit, "modelName"),
                "description": description,
                "modelDescription": description,
                "embeddingSource": self._safe_hit_value(hit, "embeddingSource"),
                "score": float(getattr(hit, "score", 0.0) or 0.0),
                "rank": rank,
            })
        return results

    def _milvus_vector_search(self, query_vector: List[float], top_k: int) -> List[Dict[str, Any]]:
        try:
            collection = self.get_milvus_collection()
            search_result = collection.search(
                data=[query_vector],
                anns_field="embedding",
                param={"metric_type": "COSINE", "params": {"ef": 128}},
                limit=top_k,
                output_fields=["modelId", "modelMd5", "modelName", "modelDescription", "embeddingSource"],
            )
            hits = self._extract_hits(search_result)
            return self._format_hits(hits)
        except Exception:
            logger.exception("Milvus vector fallback search failed")
            return []

    def _milvus_hybrid_search(self, query_text: str, query_vector: List[float], top_k: int) -> Tuple[List[Dict[str, Any]], str]:
        collection = self.get_milvus_collection()
        if not self._collection_has_sparse_field(collection):
            logger.info("Milvus collection does not have sparse field; using vector-only search")
            return self._milvus_vector_search(query_vector, top_k), "vector_fallback_no_sparse"

        search_limit = max(top_k * 5, 50)
        semantic_request = AnnSearchRequest(
            data=[query_vector],
            anns_field="embedding",
            param={"metric_type": "COSINE", "params": {"ef": 128}},
            limit=search_limit,
        )
        keyword_request = AnnSearchRequest(
            data=[query_text],
            anns_field="sparse",
            param={"metric_type": "BM25", "params": {}},
            limit=search_limit,
        )

        results = collection.hybrid_search(
            [semantic_request, keyword_request],
            rerank=RRFRanker(k=60),
            limit=top_k,
            output_fields=["modelId", "modelMd5", "modelName", "modelDescription", "embeddingSource"],
        )

        hits = self._extract_hits(results)
        formatted = self._format_hits(hits)
        if not formatted:
            logger.warning("Milvus hybrid search returned no hits; falling back to vector-only search")
            return self._milvus_vector_search(query_vector, top_k), "vector_fallback_empty_hybrid"
        return formatted, "hybrid"

    def retrieve(self, query: str, top_k: int = 10) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        llm_client = self.get_llm_client()
        start_time = time.time()

        try:
            query_vector = llm_client.embeddings.create(
                model=self.config["embedding_model"],
                input=query,
            ).data[0].embedding
            embedding_time = time.time() - start_time

            retrieval_start = time.time()
            try:
                result, retrieval_mode = self._milvus_hybrid_search(query, query_vector, top_k)
            except Exception:
                logger.exception("Milvus hybrid search failed; falling back to vector-only search")
                result = self._milvus_vector_search(query_vector, top_k)
                retrieval_mode = "vector_fallback_error"

            retrieval_time = time.time() - retrieval_start

            return result, {
                "strategy": "hybrid",
                "retrieval_mode": retrieval_mode,
                "embedding_time": embedding_time,
                "retrieval_time": retrieval_time,
                "retrieved_count": len(result),
                "scores": [doc.get("score", 0.0) for doc in result],
            }
        except Exception as e:
            logger.exception("Hybrid 检索失败")
            return [], {"strategy": "hybrid", "error": str(e)}

    def generate(self, query: str, context: Optional[str] = None) -> Tuple[str, Dict[str, Any]]:
        answer, meta = super().generate(query, context)
        if meta.get("strategy") == "vector_only":
            meta["strategy"] = "hybrid"
        return answer, meta


def create_strategy(strategy_name: str, config: Dict[str, Any]) -> RAGStrategy:
    """工厂函数：创建策略实例"""
    strategy_map = {
        "no_rag": NoRAGStrategy,
        "vector_only": VectorOnlyStrategy,
        "hybrid": HybridStrategy,
    }
    
    if strategy_name not in strategy_map:
        raise ValueError(f"Unknown strategy: {strategy_name}")
    
    return strategy_map[strategy_name](config)
