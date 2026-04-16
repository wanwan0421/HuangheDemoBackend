from . import tools
from typing import TypedDict, Dict, Any, Annotated, Optional, get_type_hints, get_origin, get_args
from langchain.messages import ToolMessage, HumanMessage, SystemMessage, AnyMessage
from langgraph.graph import StateGraph, START, END
import operator
import json
import inspect
from pymongo import MongoClient
from langgraph.checkpoint.mongodb import MongoDBSaver
from pydantic import BaseModel, Field
from langgraph.prebuilt import InjectedState

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
    # 各工具最近一次结果
    tool_results: Annotated[Dict[str, Any], operator.or_]
    # 候选最优模型md5
    selected_model_md5: str

# 任务规范结构
class TaskSpec(BaseModel):
    Domain: str = Field(default="",description="地理建模领域，如水文、气象、土地利用等")
    Target_object: str = Field(default="",description="具体研究对象，如径流量、土壤侵蚀度、降水、河流、植被等")
    Spatial_scope: str = Field(default="",description="空间范围，如某流域、某省份、上游、具体经纬度等")
    Temporal_scope: str = Field(default="",description="时间范围，如某年、某月、某日、某时间段等")
    Resolution_requirements: str = Field(default="",description="分辨率要求，如空间分辨率、时间分辨率等")

# 任务规范封装，用于绑定LLM输出结构
class TaskSpecEnvelope(BaseModel):
    Task_spec: TaskSpec = Field(default_factory=TaskSpec)

# 模型契约中的空间要求细化
class SpatialRequirement(BaseModel):
    Region: str = Field(default="",description="地理区域")
    Crs: str = Field(default="",description="坐标参考系统")

# 模型契约中每个输入槽位的定义
class RequiredSlot(BaseModel):
    Input_name: str = Field(default="",description="输入参数名称")
    Data_type: str = Field(default="",description="数据类型，如Raster, Vector, Table, Timeseries, Parameter")
    Semantic_requirement: str = Field(default="",description="语义要求，如降水、温度、土地利用等")
    Spatial_requirement: SpatialRequirement = Field(default_factory=SpatialRequirement)
    Temporal_requirement: str = Field(default="",description="时间要求，如某年、某月、某日等")
    Format_requirement: str = Field(default="",description="格式要求，如如TIFF、TIFF、Shapefile、NC、CSV等")

# 模型契约封装，用于绑定LLM输出结构
class ModelContractEnvelope(BaseModel):
    Required_slots: list[RequiredSlot] = Field(default_factory=list)

# 工具调用参数构建器，负责根据当前状态补全工具参数
def to_dict(model_obj: Any) -> Dict[str, Any]:
    if hasattr(model_obj, "model_dump"):
        return model_obj.model_dump()
    if hasattr(model_obj, "dict"):
        return model_obj.dict()
    if isinstance(model_obj, dict):
        return model_obj
    return {}

def extract_text_content(content: Any) -> str:
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

def get_model_md5_list_from_result(result: Dict[str, Any]) -> list[str]:
    models = (result or {}).get("models", []) or []
    return [m.get("modelMd5") for m in models if isinstance(m, dict) and m.get("modelMd5")]


def is_injected_state_annotation(annotation: Any) -> bool:
    if annotation is InjectedState:
        return True
    origin = get_origin(annotation)
    if origin is Annotated:
        metas = get_args(annotation)[1:]
        for meta in metas:
            if meta is InjectedState or meta.__class__.__name__ == "InjectedState":
                return True
    return False


def inject_state_for_tool(tool_obj: Any, raw_args: Dict[str, Any], state: ModelState) -> Dict[str, Any]:
    args = dict(raw_args or {})

    callable_fn = getattr(tool_obj, "func", None)
    if callable_fn is None:
        return args

    try:
        hints = get_type_hints(callable_fn, include_extras=True)
    except Exception:
        hints = getattr(callable_fn, "__annotations__", {}) or {}

    signature = inspect.signature(callable_fn)
    for param_name in signature.parameters:
        annotation = hints.get(param_name)
        if annotation is not None and is_injected_state_annotation(annotation):
            args[param_name] = state

    return args


def render_recent_context(messages: list[AnyMessage], limit: int = 6) -> str:
    rows = []
    for msg in messages[-limit:]:
        role = type(msg).__name__
        text = extract_text_content(getattr(msg, "content", "")).strip()
        if text:
            rows.append(f"[{role}] {text[:300]}")
    return "\n".join(rows)

def get_latest_user_query(messages):
    for msg in reversed(messages or []):
        if isinstance(msg, HumanMessage):
            return msg.content
    return ""

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


    system = SystemMessage(content=f"""
        # Role
        你是一位资深的地理建模专家，擅长理解用户的时空需求并提炼成规范化的任务描述。
        
        # Task
        请从用户的最新查询中提取或更新以下任务规范的字段：
        - **Domain**: 任务所属领域，如水文、气象、土地利用等
        - **Target_object**: 具体研究对象，如径流量、土壤侵蚀度、降水、河流、植被等
        - **Spatial_scope**: 空间范围，如某流域、某省份、上游、具体经纬度等
        - **Temporal_scope**: 时间范围，如某年、某月、某日、某时间段等
        - **Resolution_requirements**: 分辨率要求，如空间分辨率、时间分辨率等
                           
        # Constraints
        - 仅从最新用户查询中提取信息，避免重复或过时的内容。
        - 如果某个字段在当前规范中已有值，只有当用户明确提出修改时才更新。
        - 输出必须严格符合 `TaskSpecEnvelope` 定义的 JSON 结构，确保字段不缺失。
    """)

    context = HumanMessage(content=(
        f"已有任务规范: {json.dumps(current_task_spec, ensure_ascii=False)}\n"
        "请基于对话更新 Task_spec。"
    ))

    messages = [system, context] + state["messages"]
    latest_user_query = state.get("latest_user_query") or get_latest_user_query(state.get("messages", []))

    try:
        # 绑定结构化输出
        structured_llm = tools.recommendation_model.with_structured_output(TaskSpecEnvelope)
        # 直接获取Pydantic模型实例，避免手动解析
        parsed = structured_llm.invoke(messages)
        task_spec = to_dict(parsed).get("Task_spec", {}) or {}

        final_spec = current_task_spec.copy()
        for k, v in task_spec.items():
            if v and str(v).strip(): 
                final_spec[k] = v

        print(f"[parse_task_spec_node] ✅ Parsed Task_spec: {final_spec}")
        return {
            "messages": [],
            "Task_spec": final_spec,
            "latest_user_query": latest_user_query
        }

    except Exception as e:
        print(f"[parse_task_spec_node] ❌ Unexpected error: {type(e).__name__}: {e}")
        return {
            "messages": [],
            "Task_spec": current_task_spec,
            "latest_user_query": latest_user_query
        }

def recommend_model_node(state: ModelState) -> Dict[str, Any]:
    """
    负责根据当前消息历史决定下一步
    调用已绑定工具的模型，返回模型产生的新消息
    如果需要调用工具，则返回工具调用指令
    """
    # 加入SystemMessage以约束模型行为（同时生成 Task Spec 与模型推荐）
    system = SystemMessage(content=f"""
        # Role
        你是一位资深的地理建模专家，擅长根据复杂的时空需求匹配最合适的数值模型或机器学习模型。

        # Context
        - **任务规范**: {state['Task_spec']}
        - **最近对话状态**: {render_recent_context(state['messages'])}

        # Reasoning Process (Chain of Thought)
        在做出决定前，请按以下步骤思考：
        1. **领域校验**: 分析任务所属领域（如水文、气象），判断是否需要调用 `search_relevant_indices`。
        2. **初步筛选**: 使用 `search_relevant_models` 获取 MD5 候选池。
        3. **深度比对**: 根据初选模型的`modelMd5`，调用`search_most_model`方法获取模型详细信息，选择最优模型。
        4. **详情确认**: 根据选择的最优模型调用 `get_model_details` 获取候选模型的详细工作流和输入要求，确认其是否满足任务规范。
        5. **决策确认**: 如果模型满足任务需求，则停止调用工具并输出推荐结果。

        # Constraints
        - **Markdown 输出**: 你的非工具回复必须使用规范的 Markdown 格式。
        - **参数完整性**: 调用工具时，若状态中已有 `selected_model_md5`，请优先使用。
        - **最优模型唯一性**: 根据`search_most_model`方法获取模型详细信息后，选择最优模型。
        - **结果完整性**: 如果获取到最合适的模型，必须调用`get_model_details`工具获取模型详情，并根据模型要求进一步细化任务规范。
        - **禁止幻觉**: 严禁推荐数据库中不存在的 MD5。

        # Output Guide
        - 如果信息不足：请向用户提问或继续调用工具。
        - 如果找到匹配：请清晰说明推荐理由、模型的优势及局限性。
        """)
    messages = [system] + state["messages"]

    response = tools.model_with_tools.invoke(messages)

    return {"messages": [response]}

def model_contract_node(state: ModelState) -> Dict[str, Any]:
    """
    负责根据推荐模型详情数据，生成模型契约
    """
    
    # 优先使用state里已缓存的推荐模型
    target_model_data = state.get("recommended_model") or None
    messages = state.get("messages", [])
    
    # 显示所有消息类型，便于诊断
    for i, msg in enumerate(reversed(messages)):
        tool_id = getattr(msg, "tool_name", None) or getattr(msg, "name", None)
        
        if target_model_data:
            break

        if isinstance(msg, ToolMessage) and tool_id == "get_model_details":
            try:
                data = json.loads(msg.content)
                if data.get("status") == "success":
                    target_model_data = data
                    break
            except Exception as e:
                continue

    if not target_model_data:
        return {
            "messages": [],
            "Model_contract": {}
        }
    
    task_spec = state.get("Task_spec", {})
    
    workflow_inputs = []
    workflow = target_model_data.get("workflow", [])
    
    for state_item in workflow:
        for event in state_item.get("events", []):
            for input in event.get("inputs", []):
                workflow_inputs.append(input)
    
    prompt_content = f"""
    # Role
    你是一个地理建模数据契约审计员，负责定义模型运行的“数据准入标准”。

    # Task
    将用户的“业务语言”转化为“机器语言”。

    # Input Reference
    - 业务需求: {task_spec}
    - 模型原始输入流: {workflow_inputs}

    # Mapping Logic
    请为每一个输入槽位生成以下信息：
    1. **Semantic_requirement**: 不要只写名称，要描述该数据的地理学意义（如：年均径流量）。
    2. **Spatial_requirement**: 
        - 若用户未指定 CRS，默认推断为 `EPSG:4326` 或模型原定坐标系。
        - 明确 Region 是点、线还是面范围。
    3. **Temporal_requirement**: 明确数据的时间步长（如：日尺度、月尺度）。

    # Constraint
    输出必须严格符合 `ModelContractEnvelope` 定义的 JSON 结构，确保字段不缺失。
    """

    # 仅发送当前任务相关的 Prompt，不带state["messages"]里的历史聊天
    response = None
    try:
        structured_llm = tools.recommendation_model.with_structured_output(ModelContractEnvelope)
        response = structured_llm.invoke([HumanMessage(content=prompt_content)])
        contract = to_dict(response)
            
    except Exception as e:
        contract = {}

    return {
        "messages": [], 
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
    tool_results = state.get("tool_results", {}) or {}
    selected_model_md5 = state.get("selected_model_md5", "")
    recommended_model = state.get("recommended_model", {}) or {}

    for tool_call in tool_calls:
        tool = tools.TOOLS_BY_NAME[tool_call["name"]]
        args_with_injected_state = inject_state_for_tool(tool, tool_call.get("args", {}), state)
        observation = tool.invoke(args_with_injected_state)
        tool_results[tool_call["name"]] = observation

        if isinstance(observation, dict):
            if observation.get("md5"):
                selected_model_md5 = observation.get("md5")
            else:
                models = observation.get("models", []) or []
                if models and isinstance(models[0], dict) and models[0].get("modelMd5"):
                    selected_model_md5 = models[0]["modelMd5"]

            if tool_call["name"] == "get_model_details" and observation.get("status") == "success":
                recommended_model = observation

        # Graph 内部只保留 ToolMessage
        tool_messages.append(ToolMessage(
            content=json.dumps(observation, ensure_ascii=False),
            tool_call_id=tool_call["id"],
            tool_name=tool_call["name"]
        ))

    return {
        "messages": tool_messages,
        "Task_spec": state.get("Task_spec", {}),
        "tool_results": tool_results,
        "selected_model_md5": selected_model_md5,
        "recommended_model": recommended_model,
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

    task_spec = state.get("Task_spec", {})
    has_task_spec = bool(task_spec and any(task_spec.values()))
    
    # 反向查找是否已有get_model_details的结果
    has_model_details = bool(state.get("recommended_model"))
    for msg in reversed(messages):
        if isinstance(msg, ToolMessage) and msg.tool_name == "get_model_details":
            has_model_details = True
            break

    if has_task_spec and not has_model_details:
        print(f"[should_continue] 🔍 Task_spec is ready but model details are missing: {task_spec}")
        return "tool_node"
    
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

# agent_builder.add_node("parse_task_spec_node", parse_task_spec_node)
agent_builder.add_node("recommend_model_node", recommend_model_node)
agent_builder.add_node("model_contract_node", model_contract_node)
agent_builder.add_node("tool_node", tool_node)

# agent_builder.add_edge(START, "parse_task_spec_node")
# agent_builder.add_edge("parse_task_spec_node", "recommend_model_node")
agent_builder.add_edge(START, "recommend_model_node")

agent_builder.add_conditional_edges(
    "recommend_model_node",
    should_continue,
    {
        "recommend_model_node": "recommend_model_node",
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
