from . import tools
from typing import TypedDict, List, Dict, Any, Literal, Annotated
from langchain.messages import ToolMessage, HumanMessage, SystemMessage, AnyMessage
from langgraph.graph import StateGraph, START, END
import operator
import json
from pymongo import MongoClient
from langgraph.checkpoint.mongodb import MongoDBSaver
import re

# 连接配置
MONGO_URI = "mongodb://localhost:27017/"
DB_NAME = "huanghe-demo"

class ModelState(TypedDict):
    messages: Annotated[list[AnyMessage], operator.add]
    llm_calls: int
    # 任务规范
    Task_spec: Annotated[Dict[str, Any], operator.or_]

def parse_task_spec_node(state: ModelState) -> Dict[str, Any]:
    """
    首轮节点：只负责从用户输入中解析 Task_spec
    ❗不允许 tool calls
    """
    # 1. 获取上一轮的 Task_spec 作为基础 (实现记忆继承)
    current_task_spec = state.get("Task_spec", {}) or {}

    # 如果 current_task_spec 是空或者不完整，初始化默认结构
    default_keys = ["Domain", "Target_object", "Spatial_scope", "Temporal_scope", "Resolution_requirements"]
    for key in default_keys:
        if key not in current_task_spec:
            current_task_spec[key] = ""

    system = SystemMessage(content=(
        f"""你是任务需求解析器。请从用户最新的输入中提取或更新地理建模任务规范。

            **关键元数据解释**
            1.Task_spec: 任务规范，包含以下字段：
                -Domain: 任务领域（如气象、水文、土地利用等）
                -Target_object: 具体研究对象（如径流量、土壤侵蚀度、降水、河流、植被等）
                -Spatial_scope: 空间范围（如某流域、某省份、上游、具体经纬度等）
                -Temporal_scope: 时间范围（如某年、某月、某日、某时间段等）
                -Resolution_requirements: 分辨率要求（如空间分辨率、时间分辨率等）

            **已有任务信息** (如果用户未提及修改，请保持原样):
            {current_task_spec}

            **输出要求：必须输出以下 JSON 格式（即使某些字段为空也必须包含）**：
            ```json
            {{
            "Task_spec": {{
                "Domain": "...",
                "Target_object": "...",
                "Spatial_scope": "...",
                "Temporal_scope": "...",
                "Resolution_requirements": "..."
                }}
            }}
            ```
            
            **提取规则**：
            1. 仅提取用户显式提及的变更或新增信息。
            2. 如果用户只是在指令切换模型或者其他询问而没有修改任务属性（如时间、地点），则输出空JSON或保持原值。
            3. 输出JSON格式，不要输出其他文字。
            4. 如果某个字段无法从用户输入中确定，使用空字符串 ""。
            """
    ))

    messages = [system] + state["messages"]

    try:
        response = tools.recommendation_model.invoke(messages)
        raw_text = extract_text_content(response.content).strip()
        task_spec = {}

        # 正则提取 JSON (增强鲁棒性)
        json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', raw_text, re.DOTALL)
        
        if json_match:
            json_str = json_match.group(1)
            data = json.loads(json_str)
            task_spec = data.get("Task_spec", {})
        else:
            # 尝试直接解析（防止 LLM 没写 markdown 代码块）
            # 如果 raw_text 看起来像 json (以 { 开头)
            if raw_text.startswith("{") and raw_text.endswith("}"):
                data = json.loads(raw_text)
                task_spec = data.get("Task_spec", {})
            else:
                # 这种情况通常是 LLM 回复了 "好的，正在为您查找..." 这种废话
                # 我们选择忽略这次解析，直接返回旧状态
                print(f"[parse_task_spec_node] No JSON found, keeping previous state. Raw: {raw_text[:50]}...")
                return {
                    "messages": [response], # 这里返回 response 是为了让 graph 记录 trace，但在 main.py 会被过滤
                    "Task_spec": current_task_spec
                }

        final_spec = current_task_spec.copy()
        for k, v in task_spec.items():
            if v and str(v).strip(): 
                final_spec[k] = v

        return {
            "messages": [response],
            "Task_spec": final_spec
        }

    except json.JSONDecodeError as e:
        print(f"[parse_task_spec_node] JSON parse error: {e}")
        print(f"[parse_task_spec_node] Failed JSON: {raw_text[:200]}")
        return {
            "messages": [],
            "Task_spec": current_task_spec
        }
    
    except Exception as e:
        print(f"[parse_task_spec_node] Unexpected error: {type(e).__name__}: {e}")
        return {
            "messages": [],
            "Task_spec": current_task_spec
        }

    
def llm_node(state: ModelState) -> Dict[str, Any]:
    """
    负责根据当前消息历史决定下一步
    调用已绑定工具的模型，返回模型产生的新消息
    如果需要调用工具，则返回工具调用指令
    
    Args:
        state (ModelState): 当前代理状态，包含消息历史等信息
    Returns:
        Dict[str, Any]: 更新后的状态，包含新消息
    """
    # 加入SystemMessage以约束模型行为（同时生成 Task Spec 与模型推荐）
    system = SystemMessage(content=(
        """你是用户任务需求解析+模型推荐一体化智能体.请根据用户需求，完成以下任务要求。

        **工作流程**:
        1.指标检索：调用`search_relevant_indices`查找与需求相关的指标。
        2.模型初选：从指标结果中提取的`models_Id`(MD5 列表)，调用`search_relevant_models`精选模型。
        3.详情确认：调用`get_model_details`获取最优模型的工作流。

        **输出与结束规则**
        1.仅当你不再需要调用任何工具时，才进行最终的模型推荐总结。
        2.最终推荐的模型必须基于用户需求与检索到的指标进行匹配与筛选。
        """
    ))
    messages = [system] + state["messages"]

    response = tools.model_with_tools.invoke(messages)

    return {
        "messages": [response]
    }

def extract_text_content(content: Any) -> str:
    """
    兼容处理字符串格式和列表格式的 AIMessage content
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text_parts = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                text_parts.append(part.get("text", ""))
            elif isinstance(part, str):
                text_parts.append(part)
        return "".join(text_parts)
    return ""


def tool_node(state: ModelState) -> Dict[str, Any]:
    """
    读取最后一条消息的 tool_calls，按顺序执行对应工具并返回 ToolMessage 列表
    
    Agrs:
        state (ModelState): 当前代理状态，包含消息历史等信息
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
        "messages": tool_messages,
        "Task_spec": state.get("Task_spec", {})
    }

def should_continue(state: ModelState) -> Any:
    """
    判断是否需要继续迭代（即 LLM 是否还需要调用工具）
    
    Args:
        state (ModelState): 当前代理状态，包含消息历史等信息
    Returns:
        Literal["tool_node", END]: 如果需要调用工具则返回 "tool_node"，否则返回 END
    """
    last_message = state["messages"][-1]
    if last_message.tool_calls:
        return "tool_node"
    
    return END

agent_builder = StateGraph(ModelState)

agent_builder.add_node("parse_task_spec", parse_task_spec_node)
agent_builder.add_node("llm_node", llm_node)
agent_builder.add_node("tool_node", tool_node)

agent_builder.add_edge(START, "parse_task_spec")
agent_builder.add_edge("parse_task_spec", "llm_node")

agent_builder.add_conditional_edges(
    "llm_node",
    should_continue,
    ["tool_node", END]
)

agent_builder.add_edge("tool_node", "llm_node")

mongo_client = MongoClient(MONGO_URI)
checkpointer = MongoDBSaver(mongo_client)

agent = agent_builder.compile(checkpointer=checkpointer)
