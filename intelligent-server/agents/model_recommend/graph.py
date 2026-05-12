from . import tools
from typing import TypedDict, Dict, Any, Annotated, Optional, get_type_hints, get_origin, get_args
from langchain.messages import ToolMessage, HumanMessage, SystemMessage, AnyMessage
from ..context_manager import ContextManager
from ..store import Store
from langgraph.graph import StateGraph, START, END
import operator
import json
import inspect
import hashlib
import os
from pathlib import Path
from pymongo import MongoClient
from langgraph.checkpoint.mongodb import MongoDBSaver
from pydantic import BaseModel, Field
from langgraph.prebuilt import InjectedState
from langchain_core.messages import AIMessage
from dotenv import load_dotenv

# 连接配置
load_dotenv(Path(__file__).resolve().parents[2] / ".env")
MONGO_URI = os.getenv("MONGO_URI")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME")
MAX_TOOL_CALL_ITERATIONS = int(os.getenv("MAX_TOOL_CALL_ITERATIONS"))
MESSAGE_SUMMARY_TRIGGER = int(os.getenv("MESSAGE_SUMMARY_TRIGGER"))
MESSAGE_KEEP_RECENT = int(os.getenv("MESSAGE_KEEP_RECENT"))


def replace_state_value(current: Any, incoming: Any) -> Any:
    return current if incoming is None else incoming


def messages_reducer(current: list[AnyMessage], incoming: Any) -> list[AnyMessage]:
    current = current or []
    if incoming is None:
        return current
    if isinstance(incoming, dict) and incoming.get("__replace_messages__"):
        return incoming.get("items", [])
    return current + (incoming or [])

class ModelState(TypedDict):
    messages: Annotated[list[AnyMessage], messages_reducer]
    llm_calls: Annotated[int, replace_state_value]
    tool_call_count: Annotated[int, replace_state_value]
    request_id: Annotated[str, replace_state_value]
    task_hash: Annotated[str, replace_state_value]
    tool_scope_id: Annotated[str, replace_state_value]
    conversation_summary: Annotated[str, replace_state_value]
    user_id: Annotated[str, replace_state_value]
    latest_user_query: Annotated[str, replace_state_value]
    # 任务规范，由Task Agent生成
    Task_spec: Annotated[Dict[str, Any], operator.or_]
    # 模型契约：由Model Agent生成
    Model_contract: Annotated[Dict[str, Any], replace_state_value]
    # 模型推荐详情
    recommended_model: Annotated[Dict[str, Any], replace_state_value]
    # 各工具最近一次结果
    tool_results: Annotated[Dict[str, Any], replace_state_value]
    # 候选最优模型md5
    selected_model_md5: Annotated[str, replace_state_value]

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
            return extract_text_content(getattr(msg, "content", ""))
    return ""

# 构建任务哈希值
def build_task_hash(task_spec: Dict[str, Any], latest_query: str) -> str:
    payload = {
        "task_spec": task_spec or {},
        "latest_query": latest_query or "",
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

# 构建工具调用范围ID，优先级：request_id > task_hash > 任务规范+最新用户查询的哈希值
def get_tool_scope_id(state: ModelState) -> str:
    request_id = str(state.get("request_id") or "").strip()
    if request_id:
        return request_id
    task_hash = str(state.get("task_hash") or "").strip()
    if task_hash:
        return task_hash
    return build_task_hash(state.get("Task_spec", {}) or {}, state.get("latest_user_query", "") or "")


def get_scoped_tool_results(state: ModelState) -> Dict[str, Any]:
    tool_results = dict(state.get("tool_results", {}) or {})
    scope_id = get_tool_scope_id(state)
    if tool_results.get("_scope_id") and tool_results.get("_scope_id") != scope_id:
        return {}
    return {k: v for k, v in tool_results.items() if not str(k).startswith("_")}


def get_scoped_recommended_model(state: ModelState) -> Dict[str, Any]:
    recommended_model = dict(state.get("recommended_model", {}) or {})
    if not recommended_model:
        return {}
    scope_id = get_tool_scope_id(state)
    model_scope = recommended_model.get("_scope_id")
    if model_scope and model_scope != scope_id:
        return {}
    if model_scope is None and state.get("request_id"):
        return {}
    return {k: v for k, v in recommended_model.items() if not str(k).startswith("_")}


def scoped_tool_results_envelope(state: ModelState, base_results: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    scope_id = get_tool_scope_id(state)
    return {
        "_scope_id": scope_id,
        "_request_id": state.get("request_id", ""),
        "_task_hash": state.get("task_hash", ""),
        **(base_results or {}),
    }


def compact_tool_results(tool_results: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    compact: Dict[str, Any] = {}
    for name, result in (tool_results or {}).items():
        if str(name).startswith("_"):
            continue
        if not isinstance(result, dict):
            compact[name] = result
            continue
        entry = {
            "status": result.get("status"),
            "count": result.get("count"),
            "message": result.get("message"),
        }
        models = result.get("models")
        if isinstance(models, list):
            entry["models"] = [
                {
                    "modelMd5": model.get("modelMd5"),
                    "modelName": model.get("modelName"),
                    "score": model.get("score"),
                    "rank": model.get("rank"),
                }
                for model in models[:5]
                if isinstance(model, dict)
            ]
        if result.get("md5"):
            entry["md5"] = result.get("md5")
            entry["name"] = result.get("name")
            entry["description"] = result.get("description")
        compact[name] = {k: v for k, v in entry.items() if v is not None}
    return compact


def build_structured_history_digest(messages: list[AnyMessage], ctx_mgr: ContextManager, max_tokens: int = 1400) -> str:
    rows = []
    used = 0
    for msg in messages:
        compressed = ctx_mgr._compress_message_for_context(msg, max_tokens=140)
        text = extract_text_content(getattr(compressed, "content", ""))
        tokens = ctx_mgr._count_tokens(text)
        if used + tokens > max_tokens:
            break
        rows.append(text)
        used += tokens
    return "\n\n".join(rows)


def memory_maintenance_node(state: ModelState) -> Dict[str, Any]:
    """负责对消息历史进行总结和压缩，生成对话摘要，并更新状态中的 messages 和 conversation_summary 字段"""
    messages = state.get("messages", []) or []
    if len(messages) <= MESSAGE_SUMMARY_TRIGGER:
        return {}

    keep_recent = max(MESSAGE_KEEP_RECENT, 4)
    old_messages = messages[:-keep_recent]
    recent_messages = messages[-keep_recent:]
    if not old_messages:
        return {}

    ctx_mgr = ContextManager(max_tokens=4000)
    previous_summary = state.get("conversation_summary") or ""
    digest = build_structured_history_digest(old_messages, ctx_mgr)
    latest_query = state.get("latest_user_query") or get_latest_user_query(messages)

    summary_prompt = (
        "请更新对话滚动摘要，用于后续地理建模智能体恢复上下文。"
        "摘要必须保留：用户目标、任务规范、关键约束、已调用工具、候选/已选模型、待确认问题。"
        "不要保留无关寒暄，不要编造。\n\n"
        f"已有摘要:\n{previous_summary or '无'}\n\n"
        f"本次需要吸收的旧消息结构化摘要:\n{digest}\n\n"
        f"最新用户问题:\n{latest_query}\n\n"
        "输出 6 条以内要点："
    )

    try:
        response = tools.recommendation_model.invoke([HumanMessage(content=summary_prompt)])
        summary_text = extract_text_content(getattr(response, "content", "")).strip()
    except Exception:
        summary_text = ""

    summary_text = ctx_mgr._truncate_text(summary_text, 700)
    summary_msg = HumanMessage(content=f"[Conversation Summary]\n{summary_text}")
    return {
        "messages": {
            "__replace_messages__": True,
            "items": [summary_msg] + recent_messages,
        },
        "conversation_summary": summary_text,
    }


def _persist_task_memory(user_id: Optional[str], task_spec: Dict[str, Any], latest_query: str) -> None:
    if not user_id or not task_spec or not any(str(v or "").strip() for v in task_spec.values()):
        return
    try:
        store = Store()
        summary_parts = []
        if latest_query:
            summary_parts.append(f"query={latest_query}")
        domain = task_spec.get("Domain")
        target = task_spec.get("Target_object")
        if domain:
            summary_parts.append(f"domain={domain}")
        if target:
            summary_parts.append(f"target={target}")
        summary = " | ".join(summary_parts) if summary_parts else "task_memory"
        store.add_task_memory(user_id, summary, task_spec)
    except Exception:
        pass

def parse_task_spec_node(state: ModelState) -> Dict[str, Any]:
    """
    负责从用户最新输入中提取或更新地理建模任务规范
    """
    # 获取上一轮的 Task_spec 作为基础 (实现记忆继承)
    current_task_spec = state.get("Task_spec", {}) or {}

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

    ctx_mgr = ContextManager(max_tokens=4000)
    latest_user_query = state.get("latest_user_query") or get_latest_user_query(state.get("messages", []))
    fitted_history = ctx_mgr.fit_context_window(
        messages=state.get("messages", []),
        system_prompt=system.content,
        task_spec=current_task_spec,
        tool_results=compact_tool_results(get_scoped_tool_results(state)),
        latest_query=latest_user_query,
        conversation_summary=state.get("conversation_summary", ""),
    )
    messages = [system, context] + fitted_history

    try:
        structured_llm = tools.recommendation_model.with_structured_output(TaskSpecEnvelope)
        response = structured_llm.invoke(messages)
        contract = to_dict(response).get("Task_spec", {}) or {}
            
    except Exception as e:
        contract = {}

    _persist_task_memory(
        state.get("user_id"),
        contract,
        latest_user_query,
    )

    task_hash = build_task_hash(contract, latest_user_query)

    return {
        "messages": [], 
        "Task_spec": contract,
        "latest_user_query": latest_user_query,
        "task_hash": task_hash,
        "tool_scope_id": get_tool_scope_id({**state, "task_hash": task_hash}),
    }

def recommend_model_node(state: ModelState) -> Dict[str, Any]:
    """
    负责根据当前消息历史决定下一步
    调用已绑定工具的模型，返回模型产生的新消息
    如果需要调用工具，则返回工具调用指令
    """
    # 加入SystemMessage以约束模型行为（同时生成 Task Spec 与模型推荐）

    tool_results = get_scoped_tool_results(state)
    relevant_models = (tool_results.get("search_relevant_models", {}) or {}).get("models", []) or []
    search_status = (tool_results.get("search_relevant_models", {}) or {}).get("status")

    if search_status == "error" or (search_status == "success" and len(relevant_models) == 0):
        return {
            "messages": [AIMessage(content="未检索到可用的候选模型，请检查 Milvus 里的模型向量数据、collection schema 或输入查询。")],
        }

    if int(state.get("tool_call_count") or 0) >= MAX_TOOL_CALL_ITERATIONS and not get_scoped_recommended_model(state):
        return {
            "messages": [AIMessage(content=f"工具调用已达到上限（{MAX_TOOL_CALL_ITERATIONS} 次），暂时无法稳定完成模型推荐。请补充更明确的领域、目标对象或空间范围后重试。")],
        }

    # 如果存在 user_id（由调用端注入），则检索用户长期记忆并构建 Context Bundle
    user_id = state.get("user_id")
    context_msgs = []
    ctx_mgr = ContextManager(max_tokens=4000)
    try:
        if user_id:
            context_msgs = ctx_mgr.build_context_bundle(
                user_id,
                state.get("latest_user_query") or get_latest_user_query(state.get("messages", [])),
            )
    except Exception:
        context_msgs = []

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

        # Hard Constraint
        - 只有在工具返回了真实候选模型后，才允许输出最终推荐。
        - 如果候选池为空，必须直接结束，不得自行猜测或编造模型。
        """)
    # 动态裁剪历史消息，避免超过 token 预算
    fitted_history = ctx_mgr.fit_context_window(
        messages=state.get("messages", []),
        system_prompt=system.content,
        task_spec=state.get("Task_spec"),
        tool_results=compact_tool_results(tool_results),
        latest_query=state.get("latest_user_query") or get_latest_user_query(state.get("messages", [])),
        conversation_summary=state.get("conversation_summary", ""),
    )

    # SystemMessage 必须放在第一位；历史记忆作为参考上下文放在其后。
    messages = [system] + context_msgs + fitted_history

    response = tools.model_with_tools.invoke(messages)

    # 推荐后，若命中了具体模型则把推荐记入 user model memory
    try:
        store = Store()
        user_id = state.get("user_id")
        if user_id and isinstance(response, dict):
            # 如果响应包含推荐模型信息，尝试写入
            rec = response.get("recommended_model") or {}
            if rec and rec.get("md5"):
                store.add_model_memory(user_id, rec.get("md5"), rec.get("name", ""), reason="auto-recommend")
    except Exception:
        pass

    return {"messages": [response]}

def model_contract_node(state: ModelState) -> Dict[str, Any]:
    """
    负责根据推荐模型详情数据，生成模型契约
    """
    
    # 优先使用state里已缓存的推荐模型
    target_model_data = get_scoped_recommended_model(state) or None
    messages = state.get("messages", [])
    
    if not target_model_data and not state.get("request_id"):
        # 兼容旧 checkpoint：旧状态没有 request_id 时，才允许从历史 ToolMessage 回捞。
        for msg in reversed(messages):
            tool_id = getattr(msg, "tool_name", None) or getattr(msg, "name", None)
            if isinstance(msg, ToolMessage) and tool_id == "get_model_details":
                try:
                    data = json.loads(msg.content)
                    if data.get("status") == "success":
                        target_model_data = data
                        break
                except Exception:
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

    ctx_mgr = ContextManager(max_tokens=4000)
    fitted_history = ctx_mgr.fit_context_window(
        messages=state.get("messages", []),
        system_prompt=prompt_content,
        task_spec=task_spec,
        tool_results=compact_tool_results(get_scoped_tool_results(state)),
        latest_query=state.get("latest_user_query") or get_latest_user_query(state.get("messages", [])),
        conversation_summary=state.get("conversation_summary", ""),
    )

    # 发送任务相关 Prompt，并附带裁剪后的历史消息（如有）
    response = None
    try:
        structured_llm = tools.recommendation_model.with_structured_output(ModelContractEnvelope)
        response = structured_llm.invoke([SystemMessage(content=prompt_content)] + fitted_history)
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
    tool_results = get_scoped_tool_results(state)
    selected_model_md5 = state.get("selected_model_md5", "")
    recommended_model = get_scoped_recommended_model(state)
    scope_id = get_tool_scope_id(state)

    for tool_call in tool_calls:
        tool_name = tool_call.get("name")
        tool = tools.TOOLS_BY_NAME.get(tool_name)
        if tool is None:
            observation = {
                "status": "error",
                "message": f"未知工具: {tool_name}",
            }
            tool_messages.append(ToolMessage(
                content=json.dumps(observation, ensure_ascii=False),
                tool_call_id=tool_call.get("id", f"unknown_tool_{len(tool_messages)}"),
                tool_name=tool_name or "unknown"
            ))
            continue

        args_with_injected_state = inject_state_for_tool(tool, tool_call.get("args", {}), state)
        observation = tool.invoke(args_with_injected_state)
        tool_results[tool_name] = observation

        if isinstance(observation, dict):
            if observation.get("md5"):
                selected_model_md5 = observation.get("md5")
            else:
                models = observation.get("models", []) or []
                if models and isinstance(models[0], dict) and models[0].get("modelMd5"):
                    selected_model_md5 = models[0]["modelMd5"]

            if tool_name == "get_model_details" and observation.get("status") == "success":
                recommended_model = {
                    **observation,
                    "_scope_id": scope_id,
                    "_request_id": state.get("request_id", ""),
                    "_task_hash": state.get("task_hash", ""),
                }
                try:
                    user_id = state.get("user_id")
                    if user_id:
                        model_md5 = observation.get("md5", "")
                        model_name = observation.get("name", "")
                        reason = f"selected for task: {(state.get('Task_spec') or {}).get('Target_object', '')}"
                        if model_md5:
                            Store().add_model_memory(
                                user_id=user_id,
                                model_md5=model_md5,
                                model_name=model_name,
                                reason=reason,
                                success=True,
                            )
                except Exception:
                    pass

        # Graph 内部只保留 ToolMessage
        tool_messages.append(ToolMessage(
            content=json.dumps(observation, ensure_ascii=False),
            tool_call_id=tool_call["id"],
            tool_name=tool_name
        ))

    return {
        "messages": tool_messages,
        "Task_spec": state.get("Task_spec", {}),
        "tool_results": scoped_tool_results_envelope(state, tool_results),
        "selected_model_md5": selected_model_md5,
        "recommended_model": recommended_model,
        "tool_call_count": int(state.get("tool_call_count") or 0) + len(tool_calls),
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
    
    # 只认可本轮作用域内的 get_model_details 结果，避免旧 checkpoint 污染新请求。
    has_model_details = bool(get_scoped_recommended_model(state))
    
    # 如果工作流已完整，进入合约生成阶段
    if has_task_spec and has_model_details:
        return "model_contract_node"
    
    # 检查是否还需要调用工具（但防止重复调用）
    # 只有当最后一条消息是 AIMessage 且有 tool_calls 时，才调用工具
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        if int(state.get("tool_call_count") or 0) >= MAX_TOOL_CALL_ITERATIONS:
            return "memory_maintenance_node"
        return "tool_node"
    
    # 否则结束
    return "memory_maintenance_node"

agent_builder = StateGraph(ModelState)

agent_builder.add_node("parse_task_spec_node", parse_task_spec_node)
agent_builder.add_node("recommend_model_node", recommend_model_node)
agent_builder.add_node("model_contract_node", model_contract_node)
agent_builder.add_node("tool_node", tool_node)
agent_builder.add_node("memory_maintenance_node", memory_maintenance_node)

agent_builder.add_edge(START, "parse_task_spec_node")
agent_builder.add_edge("parse_task_spec_node", "recommend_model_node")

agent_builder.add_conditional_edges(
    "recommend_model_node",
    should_continue,
    {
        "recommend_model_node": "recommend_model_node",
        "tool_node": "tool_node",
        "model_contract_node": "model_contract_node",
        "memory_maintenance_node": "memory_maintenance_node",
        END: END
    }
)

agent_builder.add_edge("tool_node", "recommend_model_node")
agent_builder.add_edge("model_contract_node", "memory_maintenance_node")
agent_builder.add_edge("memory_maintenance_node", END)

if not MONGO_URI or not MONGO_DB_NAME:
    raise RuntimeError("MONGO_URI and MONGO_DB_NAME must be configured in intelligent-server/.env")

mongo_client = MongoClient(MONGO_URI)
checkpointer = MongoDBSaver(mongo_client)

agent = agent_builder.compile(checkpointer=checkpointer)
