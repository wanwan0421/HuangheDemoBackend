import os
from typing import List, Dict, Any, Optional
from langchain.tools import tool
from langchain_openai import OpenAIEmbeddings,ChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.chat_models import init_chat_model
from langchain_core.embeddings import Embeddings
from pymongo import MongoClient
import math
import requests
from dotenv import load_dotenv
from google import genai

# 自定义Embeddings
class CustomHTTPEmbeddings(Embeddings):
    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str
    ):
        self.api_key = api_key
        self.base_url = base_url
        self.model = model

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return [self.embed_query(t) for t in texts]

    def embed_query(self, text: str) -> List:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.model,
            "input": text,
        }

        resp = requests.post(
            self.base_url,
            json=payload,
            headers=headers,
            timeout=30
        )

        resp.raise_for_status()

        data = resp.json()

        return data["data"][0]["embedding"]     

# embedding_model = CustomHTTPEmbeddings(
#     model="gemini-embedding-001",
#     api_key="AIzaSyCxGIwvgtl1N6-Fd5ADkn4qOA48diGgfOo",
#     base_url="https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-001:embedContent"
#     )

# 初始化模型
load_dotenv()
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
client = genai.Client(api_key=GOOGLE_API_KEY )

recommendation_model = ChatGoogleGenerativeAI(
    model= "gemini-2.5-flash",
    temperature=1.0,
    max_retries=2,
    streaming=True,
    google_api_key=GOOGLE_API_KEY ,
)

# 连接配置
MONGO_URI = "mongodb://localhost:27017/"
DB_NAME = "huanghe-demo"

# MongoDB连接池
_db_client = None

def get_db():
    """获取 MongoDB 数据库连接"""
    global _db_client
    if _db_client is None:
        _db_client = MongoClient(MONGO_URI)
    return _db_client[DB_NAME]

def cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
    """计算两个向量的余弦相似度"""
    if not vec1 or not vec2 or len(vec1) != len(vec2):
        return 0.0
    
    dot_product = sum(a * b for a, b in zip(vec1, vec2))
    magnitude1 = math.sqrt(sum(a ** 2 for a in vec1))
    magnitude2 = math.sqrt(sum(b ** 2 for b in vec2))
    
    if magnitude1 == 0 or magnitude2 == 0:
        return 0.0
    
    return dot_product / (magnitude1 * magnitude2)

@tool
def search_relevant_indices(user_query_text: str, top_k: int = 5) -> Dict[str, Any]:
    """
    如果用户提出一个关于地理方面的问题，
    则可以根据用户输入文本，从指标数据库中检索相关指标，以辅助后续的模型推荐和决策。
    Args:
        user_query_text: 用户查询文本
        top_k: 返回的最相关指标数（默认5）
    Returns:
        包含相关指标列表的字典
    """
    try:
        # query_vector = embedding_model.embed_query(user_query_text)
        query_vector = client.models.embed_content(
            model="gemini-embedding-001",
            contents=user_query_text
        ).embeddings[0].values

        db = get_db()
        index_collection = db["indexSystem"]

        # 遍历所有指标
        all_data = list(index_collection.find({}, {"categories": 1, "_id": 0}))
        flattened_indicators = []

        for sphere in all_data:
            for category in sphere.get("categories", []):
                for indicator in category.get("indicators", []):
                    if indicator.get("embedding") and len(indicator.get("embedding", [])) > 0:
                        embedding = indicator.get("embedding")
                        if not embedding or not isinstance(embedding, list) or len(embedding) == 0:
                            print("指标嵌入无效，跳过该指标")
                            continue

                        score = cosine_similarity(query_vector, embedding)

                        model_ids = []
                        for model in indicator.get("models", []):
                            model_id = model.get("model_id")
                            if not model_id or not isinstance(model_id, str) or not model_id.strip():
                                print("模型ID无效，跳过该模型")
                                continue
                            model_ids.append(model_id)

                        flattened_indicators.append({
                            "name_en": indicator.get("name_en", ""),
                            "name_cn": indicator.get("name_cn", ""),
                            "models_Id": model_ids,
                            "score": score
                        })

        # 按相似度排序并取前 top_k
        flattened_indicators.sort(key=lambda x: x["score"], reverse=True)
        result = flattened_indicators[:top_k]
        
        return {
            "status": "success",
            "count": len(result),
            "indices": result
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"搜索指标失败: {str(e)}"
        }

@tool
def search_relevant_models(user_query_text: str, model_ids: List[str], top_k: int = 10) -> Dict[str, Any]:
    """
    在给定的候选模型范围内，根据用户需求进行语义筛选。
    当指标关联的模型太多时，使用此工具找出最符合用户具体意图的模型。
    Args:
        user_query_text: 用户查询文本
        model_ids: 候选模型MD5值列表
        top_k: 返回的最相关模型数（默认 10）
    Returns:
        包含相关模型列表的字典
    """
    try:
        if not model_ids:
            return {
                "status": "error",
                "message": "模型 ID 列表为空"
            }
        
        # query_vector = embedding_model.embed_query(user_query_text)
        query_vector = client.models.embed_content(
            model="gemini-embedding-001",
            contents=user_query_text
        ).embeddings[0].values

        db = get_db()
        model_embeddings_collection = db["modelembeddings"]

        # 查询指定MD5的所有模型
        all_models = list(
            model_embeddings_collection.find({"modelMd5": {"$in": model_ids}})
        )

        flattened_models = []
        
        for model in all_models:
            if model.get("embedding") and len(model.get("embedding", [])) > 0:
                score = cosine_similarity(query_vector, model["embedding"])
                flattened_models.append({
                    "modelMd5": model.get("modelMd5"),
                    "modelName": model.get("modelName"),
                    "modelDescription": model.get("modelDescription", ""),
                    "score": score
                })

        # 按相似度排序并取前top_k
        flattened_models.sort(key=lambda x: x["score"], reverse=True)
        result = flattened_models[:top_k]
        
        return {
            "status": "success",
            "count": len(result),
            "models": result
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"搜索模型失败: {str(e)}"
        }

@tool
def get_model_details(model_md5: str) -> Dict[str, Any]:
    """
    根据模型MD5值获取模型的详细信息和工作流
    Args:
        model_md5: 模型的MD5值
    Returns:
        模型详细信息和工作流
    """
    try:
        db = get_db()
        model_collection = db["modelResource"]

        # 查询模型
        model = model_collection.find_one({"md5": model_md5})
        
        if not model:
            return {
                "status": "error",
                "message": f"未找到 MD5 为 {model_md5} 的模型"
            }

        # 格式化工作流信息
        workflow_steps = []
        if model.get("data") and model["data"].get("input"):
            for state in model["data"]["input"]:
                events = []
                for event in state.get("events", []):
                    event_data = event.get("eventData", {})
                    inputs = []
                    
                    # 处理 internal 节点
                    if event_data.get("eventDataType") == "internal" and event_data.get("nodeList"):
                        for node in event_data.get("nodeList", []):
                            inputs.append({
                                "name": node.get("name", ""),
                                "type": node.get("dataType", ""),
                                "description": node.get("description", "")
                            })
                    
                    # 处理 external 节点
                    if event_data.get("eventDataType") == "external":
                        inputs.append({
                            "name": event_data.get("eventDataName") or event.get("eventName", ""),
                            "type": "FILE",
                            "description": event_data.get("exentDataDesc", "")
                        })
                    
                    events.append({
                        "eventName": event.get("eventName", ""),
                        "eventDescription": event.get("eventDescription", ""),
                        "inputs": inputs
                    })
                
                workflow_steps.append({
                    "stateName": state.get("stateName", ""),
                    "stateDescription": state.get("stateDescription", ""),
                    "events": events
                })

        return {
            "status": "success",
            "name": model.get("name", ""),
            "md5": model.get("md5", ""),
            "description": model.get("description", ""),
            "workflow": workflow_steps
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"获取模型详情失败: {str(e)}"
        }


# ============================================================================
# 工具集合 - 供 LangGraph 绑定
# ============================================================================

tools = [
    search_relevant_indices,
    search_relevant_models,
    get_model_details
]

TOOLS_BY_NAME = {tool.name: tool for tool in tools}
model_with_tools = recommendation_model.bind_tools(tools)