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
    # 任务规范，由Task Agent生成
    Task_spec: Annotated[Dict[str, Any], operator.or_]
    # 模型契约：由Model Agent生成
    Model_contract: Annotated[Dict[str, Any], operator.or_]
    # 模型推荐详情
    recommended_model: Annotated[Dict[str, Any], operator.or_]

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

def extract_json_from_text(text: str) -> dict:
    """
    从文本中提取 JSON 对象，支持多种格式：
    1. ```json {...} ``` 代码块
    2. 直接的 {...} JSON 对象
    3. 文本中嵌入的 JSON（前后有其他文字）
    
    返回提取的 JSON 对象，如果失败返回 None
    """
    # 方法1：尝试提取 markdown 代码块
    json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except json.JSONDecodeError:
            pass
    
    # 方法2：尝试从 { 到 } 的最外层 JSON 对象
    # 找到第一个 { 和最后一个 }
    first_brace = text.find('{')
    last_brace = text.rfind('}')
    
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        json_candidate = text[first_brace:last_brace+1]
        try:
            return json.loads(json_candidate)
        except json.JSONDecodeError:
            # 方法3：尝试嵌套匹配，从 { 开始逐层匹配到对应的 }
            for i in range(first_brace, len(text)):
                if text[i] == '{':
                    # 尝试匹配这个开始位置
                    brace_count = 0
                    for j in range(i, len(text)):
                        if text[j] == '{':
                            brace_count += 1
                        elif text[j] == '}':
                            brace_count -= 1
                            if brace_count == 0:
                                try:
                                    return json.loads(text[i:j+1])
                                except json.JSONDecodeError:
                                    break
    
    return None

def parse_task_spec_node(state: ModelState) -> Dict[str, Any]:
    """
    负责从用户最新输入中提取或更新地理建模任务规范
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

        # 使用增强的 JSON 提取函数
        extracted_json = extract_json_from_text(raw_text)
        
        if extracted_json:
            task_spec = extracted_json.get("Task_spec", {})
            print(f"[parse_task_spec_node] ✅ JSON extracted successfully: {list(task_spec.keys())}")
        else:
            # 这种情况通常是 LLM 回复了 "好的，正在为您查找..." 这种废话
            # 我们选择忽略这次解析，直接返回旧状态
            print(f"[parse_task_spec_node] ❌ No JSON found, keeping previous state. Raw: {raw_text[:100]}...")
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

    except Exception as e:
        print(f"[parse_task_spec_node] ❌ Unexpected error: {type(e).__name__}: {e}")
        return {
            "messages": [],
            "Task_spec": current_task_spec
        }

def recommend_model_node(state: ModelState) -> Dict[str, Any]:
    """
    负责根据当前消息历史决定下一步
    调用已绑定工具的模型，返回模型产生的新消息
    如果需要调用工具，则返回工具调用指令
    """
    # 加入SystemMessage以约束模型行为（同时生成 Task Spec 与模型推荐）
    system = SystemMessage(content=(
        """你是用户任务需求解析+模型推荐一体化智能体.请根据用户需求，完成以下任务要求。

        **工作流程**:
        1.模型初选：更加用户查询文本，调用`search_relevant_models`方法检索相关模型列表。
        2.模型评估：根据初选模型的`modelMd5`，调用`search_most_model`方法获取模型详细信息，选择最优模型。
        3.详情确认：调用`get_model_details`获取最优模型的工作流。

        **输出与结束规则**
        1.仅当你不再需要调用任何工具时，才进行最终的模型推荐总结。
        2.最终推荐的模型必须基于用户需求与模型详情进行综合评估。
        """
    ))
    messages = [system] + state["messages"]

    response = tools.model_with_tools.invoke(messages)

    return {"messages": [response]}

def model_contract_node(state: ModelState) -> Dict[str, Any]:
    """
    负责根据推荐模型详情数据，生成模型契约
    """
    print("\n[model_contract_node] START")
    
    # 寻找最近使用的模型详情数据
    target_model_data = None
    messages = state.get("messages", [])
    
    print(f"[model_contract_node] Total messages: {len(messages)}")
    
    # 显示所有消息类型，便于诊断
    for i, msg in enumerate(reversed(messages)):
        msg_type = type(msg).__name__
        tool_id = getattr(msg, "tool_name", None) or getattr(msg, "name", None)
        print(f"[model_contract_node] Message {i}: {msg_type}, tool_id={tool_id}")
        
        if isinstance(msg, ToolMessage) and tool_id == "get_model_details":
            print(f"[model_contract_node] Found get_model_details at index {i}")
            try:
                data = json.loads(msg.content)
                if data.get("status") == "success":
                    target_model_data = data
                    print(f"[model_contract_node] ✅ Extracted model data: {data.get('name')}")
                    break
            except Exception as e:
                print(f"[model_contract_node] ❌ Failed to parse get_model_details: {e}")
                continue

    if not target_model_data:
        print("[model_contract_node] ❌ No get_model_details found in messages, returning empty contract")
        return {
            "messages": [],
            "Model_contract": {}
        }
    
    task_spec = state.get("Task_spec", {})
    print(f"[model_contract_node] Task_spec: {task_spec}")
    
    workflow_inputs = []
    workflow = target_model_data.get("workflow", [])
    print(f"[model_contract_node] Workflow steps: {len(workflow)}")
    
    for state_item in workflow:
        for event in state_item.get("events", []):
            for input in event.get("inputs", []):
                workflow_inputs.append(input)
    
    prompt_content = f"""你是一个地理建模专家。请为以下模型参数生成数据准入契约。

    **用户任务需求**
    {json.dumps(task_spec, ensure_ascii=False)}

    **模型输入定义**
    {json.dumps(workflow_inputs, ensure_ascii=False)}

    **关键元数据解释**
    1.Required_slots: 模型数据准入契约列表，包括以下字段：
        -Input_name: 输入参数名称
        -Semantic_requirement: 语义要求（如降水、温度、土地利用等）
        -Data_type: 数据类型（Raster, Vector, Table, Timeseries, Parameter）
        -Spatial_requirement: 空间要求（如某区域、某流域等，包含Region和Crs）
        -Temporal_requirement: 时间要求（如某年、某月、某日等）
        -Format_requirement: 格式要求（如TIFF、TIFF、Shapefile、NC、CSV等）

    **输出要求**
    请基于上述定义，将原始参数转化为具体的 "Required_slots"。
    必须返回标准的JSON格式，包含：Required_slots 列表。

    示例格式：
    {{
    "Required_slots": [
        {{
        "Input_name": "...",
        "Data_type": "...",
        "Semantic_requirement": "...",
        "Spatial_requirement": {{"Region": "...", "Crs": "..."}},
        "Temporal_requirement": "...",
        "Format_requirement": "..."
        }}
    ]
    }}
    """

    # 仅发送当前任务相关的 Prompt，不带state["messages"]里的历史聊天
    try:
        response = tools.recommendation_model.invoke([HumanMessage(content=prompt_content)])
        raw_content = extract_text_content(response.content).strip()
        
        # 使用增强的 JSON 提取函数
        contract = extract_json_from_text(raw_content) or {}
        
        if contract:
            print(f"[model_contract_node] ✅ Contract JSON extracted: {list(contract.keys())}")
        else:
            print(f"[model_contract_node] ⚠️  No JSON found in response, using empty contract")
            
    except Exception as e:
        print(f"[model_contract_node] ❌ LLM Generation/Parsing failed: {e}")
        contract = {}

    return {
        "messages": [response], 
        "recommended_model": target_model_data,
        "Model_contract": contract
    }
    
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
    判断是否需要继续迭代
    优先级：已完成工作流 > 还需工具 > 结束
    """
    messages = state.get("messages", [])
    last_message = messages[-1] if messages else None
    
    if not last_message:
        return END
    
    # 检查是否已有完整的推荐（Task_spec + model_details 都有）
    task_spec = state.get("Task_spec", {})
    has_task_spec = bool(task_spec and any(task_spec.values()))
    
    # 反向查找是否已有get_model_details的结果
    has_model_details = False
    for msg in reversed(messages):
        if isinstance(msg, ToolMessage) and msg.tool_name == "get_model_details":
            has_model_details = True
            break
    
    # 如果工作流已完整，进入合约生成阶段
    if has_task_spec and has_model_details:
        print(f"[should_continue] ✅ Routing to model_contract_node: has_task_spec={has_task_spec}, has_model_details={has_model_details}")
        return "model_contract_node"
    
    # 检查是否还需要调用工具（但防止重复调用）
    # 只有当最后一条消息是 AIMessage 且有 tool_calls 时，才调用工具
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        print(f"[should_continue] 🔧 Routing to tool_node: calling {[c.get('name') for c in last_message.tool_calls]}")
        return "tool_node"
    
    # 否则结束
    return END

agent_builder = StateGraph(ModelState)

agent_builder.add_node("parse_task_spec_node", parse_task_spec_node)
agent_builder.add_node("recommend_model_node", recommend_model_node)
agent_builder.add_node("model_contract_node", model_contract_node)
agent_builder.add_node("tool_node", tool_node)

agent_builder.add_edge(START, "parse_task_spec_node")
agent_builder.add_edge("parse_task_spec_node", "recommend_model_node")

agent_builder.add_conditional_edges(
    "recommend_model_node",
    should_continue,
    {
        "tool_node": "tool_node",
        "model_contract_node": "model_contract_node",
        END: END
    }
)

agent_builder.add_edge("tool_node", "recommend_model_node")
agent_builder.add_edge("model_contract_node", END)

mongo_client = MongoClient(MONGO_URI)
checkpointer = MongoDBSaver(mongo_client)

agent = agent_builder.compile(checkpointer=checkpointer)
