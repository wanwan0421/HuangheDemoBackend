from state import AgentState
from . import tools
from pymongo import MongoClient
from typing_extensions import List

# 连接配置
MONGO_URI = "mongodb://localhost:27017/"
DB_NAME = "huanghe-demo"

# 初始化模型
# embedding_model = OpenAIEmbeddings(model="text-embedding-ada-002")

# 连接到 MongoDB 数据库
def get_db():
    client = MongoClient(MONGO_URI)
    db = client[DB_NAME]
    return db

def find_relevantIndices(user_query_vector: List[float]):
    """
    findRelevantIndices：根据用户需求，从向量数据库中检索相关指标

    :param user_query_vector: 用户查询向量
    :type user_query_vector: List[float]
    """
    db = get_db()
    indexCollection = db["indexSystem"]

    all_indicators = list(indexCollection.find({}, {"categories": 1, "_id": 0}))
    flattened_indicators = []

    # 展平嵌套的 categories 列表
    for sphere in all_indicators:
        for category in sphere.get("categories", []):
            for indicator in category.get("indicators", []):
                if (indicator.get("embedding") and len(indicator["embedding"]) > 0):
                    score = tools.cosine_similarity(user_query_vector, indicator["embedding"])
                    flattened_indicators.append({
                        "name_en": indicator.get("name_en", ""),
                        "name_cn": indicator.get("name_cn", ""),
                        "score": score
                    })

    flattened_indicators.sort(key=lambda x: x["score"], reverse=True)
    return flattened_indicators[:10]

def recommendIndex(state: AgentState):
    """
    recommendIndex：分析用户需求，从指标库中查找数据
    
    :param state: 说明
    :type state: AgentState
    """
    query = state["prompt"]
    
    # 将用户需求转化为向量
    queryEmbedding = tools.embedding_model.embed_query(query)
    print(f"\n[1. 向量检索] 正在根据用户需求检索相关指标：{query}")

    # 使用向量检索从指标库中查找相关指标
    relevantIndices = find_relevantIndices(queryEmbedding)

    # AI从相关指标中再进行筛选



# 如果LLM决定调用工具，响应会包含tool_calls属性
