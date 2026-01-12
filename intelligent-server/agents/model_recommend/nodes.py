from . import tools
from typing import TypedDict, List, Dict, Any, Literal, Annotated
from langchain.messages import ToolMessage, HumanMessage, SystemMessage, AnyMessage
from langgraph.graph import StateGraph, START, END
import operator
import json
from pymongo import MongoClient
from langgraph.checkpoint.mongodb import MongoDBSaver

# 连接配置
MONGO_URI = "mongodb://localhost:27017/"
DB_NAME = "huanghe-demo"

class AgentState(TypedDict):
    messages: Annotated[list[AnyMessage], operator.add]
    llm_calls: int

def llm_node(state: AgentState) -> Dict[str, Any]:
    """
    负责根据当前消息历史决定下一步
    调用已绑定工具的模型，返回模型产生的新消息
    如果需要调用工具，则返回工具调用指令
    
    Args:
        state (AgentState): 当前代理状态，包含消息历史等信息
    Returns:
        Dict[str, Any]: 更新后的状态，包含新消息
    """
    # 可在此加入 SystemMessage 以约束模型行为（可选）
    system = SystemMessage(content=(
        "你是一个专业的地理模型推荐专家。请按以下逻辑操作：\n"
        "1. 使用 `search_relevant_indices` 寻找与用户需求（如：降水预测）相关的指标。\n"
        "2. 从指标结果中提取指标关联的模型 `models_Id` (MD5列表)，并使用 `search_relevant_models` 进行模型精选。\n"
        "3. 调用 `get_model_details` 确定最适合的模型并获取最终模型的详细工作流。\n"
        "不要凭空想象模型，必须基于工具返回的数据。"
    ))
    messages = [system] + state["messages"]

    response = tools.model_with_tools.invoke(messages)

    return {
        "messages": [response],
        "llm_calls": state.get("llm_calls", 0) + 1
    }

def tool_node(state: AgentState) -> Dict[str, Any]:
    """
    读取最后一条消息的 tool_calls，按顺序执行对应工具并返回 ToolMessage 列表
    
    Agrs:
        state (AgentState): 当前代理状态，包含消息历史等信息
    Returns:
        Dict[str, Any]: 更新后的状态，包含工具调用结果消息列表
    """
    last_message = state["messages"][-1]
    # 防御性判断：如果没有 tool_calls，直接返回空消息
    tool_calls = getattr(last_message, "tool_calls", []) or []

    tool_messages = []

    for tool_call in tool_calls:
        tool = tools.TOOLS_BY_NAME[tool_call["name"]]
        observation = tool.invoke(tool_call["args"])

        # Graph 内部只保留 ToolMessage
        tool_messages.append(ToolMessage(
            content=json.dumps(observation, ensure_ascii=False),
            tool_call_id=tool_call["id"],
            tool_name=tool_call["name"]
        ))

    return {
        "messages": tool_messages
    }

def should_continue(state: AgentState) -> Any:
    """
    判断是否需要继续迭代（即 LLM 是否还需要调用工具）
    
    Args:
        state (AgentState): 当前代理状态，包含消息历史等信息
    Returns:
        Literal["tool_node", END]: 如果需要调用工具则返回 "tool_node"，否则返回 END
    """
    last_message = state["messages"][-1]
    if last_message.tool_calls:
        return "tool_node"
    
    return END

agent_builder = StateGraph(AgentState)
agent_builder.add_node("llm_node", llm_node)
agent_builder.add_node("tool_node", tool_node)
agent_builder.add_edge(START, "llm_node")
agent_builder.add_conditional_edges(
    "llm_node",
    should_continue,
    ["tool_node", END]
)
agent_builder.add_edge("tool_node", "llm_node")

mongo_client = MongoClient(MONGO_URI)
checkpointer = MongoDBSaver(mongo_client)

agent = agent_builder.compile(checkpointer=checkpointer)
