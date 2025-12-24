from langchain_core.messages import AnyMessage
from typing_extensions import TypedDict, Annotated, List, Dict, Optional
from pydantic import BaseModel, Field
import operator

# 用于存储消息
class MessageState(TypedDict):
    messages: Annotated[list[AnyMessage], operator.add]

# LangGraph状态定义
class AgentState(TypedDict):
    prompt: str # 用户的需求
    relevantIndices: List[Dict] # 向量检索的指标
    recommendedIndices: List[Dict] # 推荐的指标
    recommendedModels: List[Dict] # 推荐的模型
    finalResult: str # 最终结果