import os
import logging
import re
from typing import List, Dict, Any, Optional, Annotated
from langchain.tools import tool
from langchain_openai import OpenAIEmbeddings,ChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.chat_models import init_chat_model
from langchain_core.embeddings import Embeddings
from langchain.messages import HumanMessage
from pymongo import MongoClient
from pymilvus import RRFRanker, connections, Collection, AnnSearchRequest, WeightedRanker
import math
from dotenv import load_dotenv
from google import genai
from langgraph.prebuilt import InjectedState
from openai import OpenAI
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

# 初始化模型
load_dotenv()
AIHUBMIX_API_KEY = os.getenv("AIHUBMIX_API_KEY")
AIHUBMIX_BASE_URL = os.getenv("AIHUBMIX_BASE_URL")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
client = OpenAI(
    api_key=AIHUBMIX_API_KEY,
    base_url=AIHUBMIX_BASE_URL
)

recommendation_model = ChatOpenAI(
    model= "gpt-5-mini",
    temperature=1.0,
    max_retries=2,
    streaming=True,
    openai_api_key=AIHUBMIX_API_KEY,
    openai_api_base=AIHUBMIX_BASE_URL,
)

# 连接配置
MONGO_URI = "mongodb://localhost:27017/"
DB_NAME = "huanghe-demo"
MILVUS_HOST = os.getenv("MILVUS_HOST", "localhost")
MILVUS_PORT = int(os.getenv("MILVUS_PORT", "19530"))
MILVUS_COLLECTION = os.getenv("MILVUS_COLLECTION", "modelembeddings")

# MongoDB连接池
_db_client = None
_milvus_collection = None
logger = logging.getLogger(__name__)

def _latest_user_query_from_state(state: Optional[Dict[str, Any]]) -> str:
    if not state:
        return ""

    direct = str(state.get("latest_user_query") or "").strip()
    if direct:
        return direct

    for msg in reversed(state.get("messages", []) or []):
        if not isinstance(msg, HumanMessage):
            continue
        content = getattr(msg, "content", "")
        if isinstance(content, str) and content.strip():
            return content.strip()
        if isinstance(content, list):
            text = "".join(
                p.get("text", "") if isinstance(p, dict) else p
                for p in content
                if isinstance(p, str) or (isinstance(p, dict) and p.get("type") == "text")
            ).strip()
            if text:
                return text

    return ""


def _model_md5s_from_state(state: Optional[Dict[str, Any]]) -> List[str]:
    tool_results = (state or {}).get("tool_results", {}) or {}
    models = (tool_results.get("search_relevant_models", {}) or {}).get("models", []) or []
    return [m.get("modelMd5") for m in models if isinstance(m, dict) and m.get("modelMd5")]


def _selected_model_md5_from_state(state: Optional[Dict[str, Any]]) -> str:
    if not state:
        return ""

    selected = str(state.get("selected_model_md5") or "").strip()
    if selected:
        return selected

    tool_results = state.get("tool_results", {}) or {}
    for key in ["search_most_model", "search_relevant_models"]:
        models = (tool_results.get(key, {}) or {}).get("models", []) or []
        if models and isinstance(models[0], dict):
            md5 = models[0].get("modelMd5")
            if md5:
                return md5

    return ""

def get_db():
    """获取 MongoDB 数据库连接"""
    global _db_client
    if _db_client is None:
        _db_client = MongoClient(MONGO_URI)
    return _db_client[DB_NAME]

def get_milvus_collection():
    """获取 Milvus collection 连接"""
    global _milvus_collection
    if _milvus_collection is None:
        connections.connect(alias="default", host=MILVUS_HOST, port=MILVUS_PORT)
        _milvus_collection = Collection(MILVUS_COLLECTION)
        _milvus_collection.load()
    return _milvus_collection

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

def _make_weighted_ranker(semantic_weight: float = 0.65, keyword_weight: float = 0.35):
    """创建一个 WeightedRanker，兼容不同版本的 pymilvus"""
    try:
        return WeightedRanker(semantic_weight, keyword_weight)
    except TypeError:
        return WeightedRanker([semantic_weight, keyword_weight])

def _infer_query_profile(query_text: str) -> Dict[str, Any]:
    text = (query_text or "").strip()
    lower = text.lower()
    ascii_tokens = re.findall(r"[A-Za-z][A-Za-z0-9_./-]*", text)
    has_identifier = any(
        "_" in token or "/" in token or "." in token or any(ch.isdigit() for ch in token)
        for token in ascii_tokens
    )
    has_acronym = any(
        len(token) >= 2 and sum(1 for ch in token if ch.isupper()) >= 2
        for token in ascii_tokens
    )
    parameter_terms = [
        "参数", "输入", "输出", "文件", "格式", "支持", "导入", "设置",
        "input", "output", "parameter", "param", "data", "file",
    ]
    intent_terms = [
        "我想", "有没有", "推荐", "哪个", "哪一个", "比较好", "适合",
        "怎么选", "用什么",
    ]

    keyword_signal = 0
    keyword_signal += 2 if has_identifier else 0
    keyword_signal += 2 if has_acronym else 0
    keyword_signal += sum(1 for term in parameter_terms if term in lower or term in text)

    is_colloquial = any(term in text for term in intent_terms)
    if is_colloquial and keyword_signal <= 1:
        return {"profile": "dense_heavy", "semantic_weight": 0.9, "keyword_weight": 0.1}
    if keyword_signal >= 3:
        return {"profile": "keyword_aware", "semantic_weight": 0.65, "keyword_weight": 0.35}
    return {"profile": "balanced", "semantic_weight": 0.8, "keyword_weight": 0.2}

def _extract_hybrid_hits(search_result: Any) -> List[Any]:
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

def _milvus_vector_search(query_vector: List[float], top_k: int) -> List[Dict[str, Any]]:
    try:
        collection = get_milvus_collection()
        search_result = collection.search(
            data=[query_vector],
            anns_field="embedding",
            param={"metric_type": "COSINE", "params": {"ef": 128}},
            limit=top_k,
            output_fields=["modelId", "modelMd5", "modelName", "modelDescription", "embeddingSource"],
        )

        rows = _extract_hybrid_hits(search_result)
        vector_results: List[Dict[str, Any]] = []
        for rank, hit in enumerate(rows, start=1):
            vector_results.append({
                "modelId": _safe_hit_value(hit, "modelId"),
                "modelMd5": _safe_hit_value(hit, "modelMd5"),
                "modelName": _safe_hit_value(hit, "modelName"),
                "modelDescription": _safe_hit_value(hit, "modelDescription"),
                "embeddingSource": _safe_hit_value(hit, "embeddingSource"),
                "score": float(getattr(hit, "score", 0.0) or 0.0),
                "rank": rank,
            })

        return vector_results
    except Exception:
        logger.exception("Milvus vector fallback search failed")
        return []

def _milvus_hybrid_search(query_text: str, query_vector: List[float], top_k: int) -> List[Dict[str, Any]]:
    """在 Milvus 中执行语义 + 关键词混合检索，并返回格式化结果"""
    try:
        collection = get_milvus_collection()
        if not _collection_has_sparse_field(collection):
            logger.info("Milvus collection does not have sparse field; using vector-only search")
            return _milvus_vector_search(query_vector, top_k)

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
        profile = _infer_query_profile(query_text)
        results = collection.hybrid_search(
            [semantic_request, keyword_request],
            rerank=_make_weighted_ranker(
                float(profile["semantic_weight"]),
                float(profile["keyword_weight"]),
            ),
            limit=top_k,
            output_fields=["modelId", "modelMd5", "modelName", "modelDescription", "embeddingSource"],
        )
        logger.info("Milvus adaptive hybrid search profile=%s", profile.get("profile"))

        hits = _extract_hybrid_hits(results)
        hybrid_results: List[Dict[str, Any]] = []
        for rank, hit in enumerate(hits, start=1):
            hybrid_results.append({
                "modelId": _safe_hit_value(hit, "modelId"),
                "modelMd5": _safe_hit_value(hit, "modelMd5"),
                "modelName": _safe_hit_value(hit, "modelName"),
                "modelDescription": _safe_hit_value(hit, "modelDescription"),
                "embeddingSource": _safe_hit_value(hit, "embeddingSource"),
                "score": float(getattr(hit, "score", 0.0) or 0.0),
                "rank": rank,
            })

        if not hybrid_results:
            logger.warning("Milvus hybrid search returned no hits; falling back to vector-only search")
            return _milvus_vector_search(query_vector, top_k)

        return hybrid_results
    except Exception:
        logger.exception("Milvus hybrid search failed; falling back to vector-only search")
        return _milvus_vector_search(query_vector, top_k)

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
def search_relevant_models(
    user_query_text: Optional[str] = None,
    top_k: int = 10,
    state: Annotated[Dict[str, Any], InjectedState] = None,
) -> Dict[str, Any]:
    """
    使用 Milvus 语义检索 + Milvus 关键词检索（BM25）混合检索。
    Args:
        user_query_text: 用户查询文本
        top_k: 返回的最相关模型数（默认 10）
    Returns:
        包含相关模型MD5和相似度分数的字典
    """
    try:
        if not user_query_text or not str(user_query_text).strip():
            user_query_text = _latest_user_query_from_state(state)

        if not user_query_text:
            return {
                "status": "error",
                "message": "缺少 user_query_text，且无法从状态注入中推断。"
            }

        # 生成用户查询向量
        query_vector = client.embeddings.create(
            model="gemini-embedding-001",
            input=user_query_text
        ).data[0].embedding

        result = _milvus_hybrid_search(user_query_text, query_vector, top_k)
        if not result:
            return {
                "status": "error",
                "message": "Milvus 混合检索未返回结果，请检查 collection、索引、embeddingSource 或 query 向量。",
                "models": [],
                "count": 0,
            }
        
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
def search_most_model(
    model_md5s: Optional[List[str]] = None,
    state: Annotated[Dict[str, Any], InjectedState] = None,
) -> Dict[str, Any]:
    """
    根据给定的模型MD5列表，从数据库获取这些模型的详细信息。
    供LLM使用，让LLM基于详细信息来选择最适合的一个模型。
    Args:
        model_md5s: 模型MD5值列表
    Returns:
        包含模型详细信息的字典
    """
    try:
        if not model_md5s:
            model_md5s = _model_md5s_from_state(state)

        if not model_md5s:
            return {
                "status": "error",
                "message": "模型 MD5 列表为空，且无法从状态注入中推断。"
            }

        db = get_db()
        model_resource_collection = db["modelResource"]

        # 根据MD5列表查询模型详细信息
        models = list(
            model_resource_collection.find({"md5": {"$in": model_md5s}})
        )
        
        # 构建结果
        result_models = []
        for model in models:
            result_models.append({
                "modelMd5": model.get("md5", ""),
                "modelName": model.get("name", ""),
                "mdl": model.get("mdl", "")
            })
        
        return {
            "status": "success",
            "count": len(result_models),
            "models": result_models
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"获取模型详情失败: {str(e)}"
        }

@tool
def get_model_details(
    model_md5: Optional[str] = None,
    state: Annotated[Dict[str, Any], InjectedState] = None,
) -> Dict[str, Any]:
    """
    根据模型MD5值获取模型的详细信息和工作流
    Args:
        model_md5: 模型的MD5值
    Returns:
        模型详细信息和工作流
    """
    try:
        if not model_md5:
            model_md5 = _selected_model_md5_from_state(state)

        if not model_md5:
            return {
                "status": "error",
                "message": "缺少 model_md5，且无法从状态注入中推断。"
            }

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
                            "description": event_data.get("exentDataDesc", ""),
                            "nodeList": event_data.get("nodeList", [])
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
    search_relevant_models,
    search_most_model,
    get_model_details
]

TOOLS_BY_NAME = {tool.name: tool for tool in tools}
model_with_tools = recommendation_model.bind_tools(tools)
