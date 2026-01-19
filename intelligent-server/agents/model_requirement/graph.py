"""
模型需求输入数据扫描 - LangGraph 工作流
执行流程：解析 MDL → 提取模型输入/输出/参数需求
"""

import json
from typing import List
from langgraph.graph import START, END, StateGraph, DEFAULT_CONDITIONAL
from langgraph.prebuilt import ToolNode
from langchain.messages import HumanMessage, ToolMessage, AIMessage
from tools import (
    ModelRequirementState,
    model_with_tools,
    TOOLS_BY_NAME,
    tool_parse_mdl,
)


# ============================================================================
# 节点定义
# ============================================================================

def llm_node(state: ModelRequirementState):
    """
    LLM 节点 - 决定下一步操作（仅进行 MDL 扫描与需求提取）
    """
    messages = state["messages"]

    # 如果是初始请求，添加系统提示
    if not messages or (len(messages) == 1 and isinstance(messages[0], HumanMessage)):
        system_prompt = """你是一个模型需求扫描专家。你的任务是：
    1. 解析模型的 MDL 文件，提取模型的输入需求、输出规范与参数设置
    2. 仅进行需求扫描，不进行任何用户数据的验证或比对

    执行步骤：
    1. 使用 tool_parse_mdl 解析 MDL 数据并返回结构化的模型需求 JSON

    请严格遵循仅扫描/解析的范围，不进行数据验证。"""

        messages = [HumanMessage(content=system_prompt)] + messages

    # 调用 LLM
    response = model_with_tools.invoke(messages)

    return {
        "messages": [response],
        "mdl_requirements": state.get("mdl_requirements", {}),
        "status": state.get("status", "processing")
    }


def tool_node(state: ModelRequirementState):
    """
    工具执行节点 - 执行 LLM 指定的工具（仅支持 MDL 解析）
    """
    messages = state["messages"]
    last_message = messages[-1]

    # 如果最后一条消息有工具调用，执行工具
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        tool_results = []

        for tool_call in last_message.tool_calls:
            tool_name = tool_call["name"]
            tool_input = tool_call["args"]

            print(f"\n🔧 执行工具: {tool_name}")
            print(f"   输入: {json.dumps(tool_input, ensure_ascii=False, indent=2)[:200]}...")

            # 执行工具
            if tool_name in TOOLS_BY_NAME:
                try:
                    tool = TOOLS_BY_NAME[tool_name]
                    result = tool.invoke(tool_input)

                    print(f"   结果: 成功")

                    tool_results.append(
                        ToolMessage(
                            content=json.dumps(result, ensure_ascii=False),
                            tool_use_id=tool_call["id"],
                            name=tool_name
                        )
                    )

                    # 更新状态
                    if tool_name == "tool_parse_mdl":
                        state["mdl_requirements"] = result

                except Exception as e:
                    tool_results.append(
                        ToolMessage(
                            content=f"Error: {str(e)}",
                            tool_use_id=tool_call["id"],
                            name=tool_name
                        )
                    )

        return {
            "messages": tool_results,
            "mdl_requirements": state.get("mdl_requirements", {}),
            "status": state.get("status", "processing")
        }

    # 如果没有工具调用，返回原状态
    return state


def should_continue(state: ModelRequirementState) -> str:
    """
    判断是否继续执行工具或结束流程
    """
    messages = state["messages"]

    # 获取最后一条消息
    last_message = messages[-1]

    # 如果是 ToolMessage，继续调用 LLM
    if isinstance(last_message, ToolMessage):
        return "llm"

    # 如果是 AIMessage 且有工具调用，继续执行工具
    if isinstance(last_message, AIMessage):
        if hasattr(last_message, "tool_calls") and last_message.tool_calls:
            return "tools"

    # 否则结束流程
    return "end"


# ============================================================================
# 构建 LangGraph
# ============================================================================

def build_model_requirement_graph():
    """
    构建模型需求扫描图（仅解析 MDL 并提取需求）
    """
    # 创建状态图
    graph_builder = StateGraph(ModelRequirementState)

    # 添加节点
    graph_builder.add_node("llm", llm_node)
    graph_builder.add_node("tools", tool_node)

    # 添加边
    graph_builder.add_edge(START, "llm")

    # 条件路由
    graph_builder.add_conditional_edges(
        "llm",
        should_continue,
        {
            "tools": "tools",
            "llm": "llm",
            "end": END
        }
    )

    graph_builder.add_conditional_edges(
        "tools",
        should_continue,
        {
            "llm": "llm",
            "tools": "tools",
            "end": END
        }
    )

    # 编译图
    return graph_builder.compile()


# 创建全局图实例
model_requirement_graph = build_model_requirement_graph()
