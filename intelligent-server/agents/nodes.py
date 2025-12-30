from . import tools
from typing import TypedDict, List, Dict, Any, Literal, Annotated
from langchain.messages import ToolMessage, HumanMessage, SystemMessage, AnyMessage, AIMessage
from langchain_core.messages import AIMessageChunk
from langgraph.graph import StateGraph, START, END
import operator
import json

class AgentState(TypedDict):
    messages: Annotated[list[AnyMessage], operator.add]
    llm_calls: int

async def llm_node(state: AgentState):
    """
    流式 LLM Node：
    - 逐 token 向外 yield（前端可实时显示）
    - 最后补一个完整 AIMessage（保证 tool_calls / Graph 正常）
    """

    system = SystemMessage(content=(
        "你是一个专业的地理模型推荐专家。请按以下逻辑操作：\n"
        "1. 使用 `search_relevant_indices` 寻找与用户需求（如：降水预测）相关的指标。\n"
        "2. 从指标结果中提取指标关联的模型 `models_Id` (MD5列表)，并使用 `search_relevant_models` 进行模型精选。\n"
        "3. 调用 `get_model_details` 确定最适合的模型并获取最终模型的详细工作流。\n"
        "不要凭空想象模型，必须基于工具返回的数据。"
    ))

    messages = [system] + state["messages"]

    full_content = ""
    last_chunk: AIMessageChunk | None = None
    llm_call_recorded = False

    async for chunk in tools.model_with_tools.astream(messages):
        last_chunk = chunk

        # 1️⃣ 累积完整文本
        if isinstance(chunk.content, str):
            full_content += chunk.content
        elif isinstance(chunk.content, list):
            for c in chunk.content:
                if isinstance(c, dict) and "text" in c:
                    full_content += c["text"]

        # 2️⃣ 向 Graph / SSE 流式吐 token
        update: Dict[str, Any] = {
            "messages": [chunk]
        }

        # llm_calls 只在第一次 chunk +1
        if not llm_call_recorded:
            update["llm_calls"] = state.get("llm_calls", 0) + 1
            llm_call_recorded = True

        yield update

    # 3️⃣ 🔴 关键：补一个“最终完整 AIMessage”
    #    否则 tool_calls / should_continue 会不稳定
    if last_chunk is not None:
        yield {
            "messages": [
                AIMessage(
                    content=full_content,
                    tool_calls=getattr(last_chunk, "tool_calls", None)
                )
            ]
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
            tool_call_id=tool_call["id"]
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
agent = agent_builder.compile()
