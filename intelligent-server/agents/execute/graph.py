import asyncio
import json
import operator
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Annotated, Any, Dict, List, Optional, TypedDict

from dotenv import load_dotenv
from langchain.messages import AnyMessage, HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import END, START, StateGraph

load_dotenv()

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
DATA_METHOD_BASE_URL = (os.getenv("DATA_METHOD_BASE_URL") or "http://172.21.252.222:8080").rstrip("/")
DATA_METHOD_TOKEN = os.getenv("DATA_METHOD_TOKEN") or ""

execute_model = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    temperature=0.2,
    max_retries=2,
    streaming=False,
    google_api_key=GOOGLE_API_KEY,
)


def _replace_state_value(current: Any, incoming: Any) -> Any:
    return current if incoming is None else incoming


class ExecuteState(TypedDict, total=False):
    messages: Annotated[List[AnyMessage], operator.add]
    alignment_result: Annotated[Dict[str, Any], operator.or_]
    model_contract: Annotated[Dict[str, Any], operator.or_]
    data_profiles: Annotated[List[Dict[str, Any]], _replace_state_value]
    available_methods: Annotated[List[Dict[str, Any]], _replace_state_value]
    execution_targets: Annotated[List[Dict[str, Any]], _replace_state_value]
    execution_plan: Annotated[List[Dict[str, Any]], _replace_state_value]
    status: str


def extract_text_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: List[str] = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                parts.append(str(part.get("text", "")))
            elif isinstance(part, str):
                parts.append(part)
        return "".join(parts)
    return ""


def parse_json_from_text(raw_text: str) -> Dict[str, Any]:
    text = str(raw_text or "").strip()
    if not text:
        return {}

    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)

    if text.startswith("{") and text.endswith("}"):
        return json.loads(text)

    fallback = re.search(r"(\{.*\})", text, re.DOTALL)
    if fallback:
        return json.loads(fallback.group(1))

    return {}


def _normalize_text(value: Any) -> str:
    return str(value or "").strip().lower()


def _container_get(endpoint: str, params: Optional[Dict[str, Any]] = None, timeout: int = 30) -> Dict[str, Any]:
    query = urllib.parse.urlencode(params or {})
    url = f"{DATA_METHOD_BASE_URL}/{endpoint.lstrip('/')}"
    if query:
        url = f"{url}?{query}"

    req = urllib.request.Request(url, headers={"token": DATA_METHOD_TOKEN}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            data = json.loads(raw)
            if data.get("code", 0) != 0:
                raise Exception(data.get("msg") or "数据处理服务返回错误")
            return data
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore") if hasattr(exc, "read") else str(exc)
        raise Exception(f"容器服务 GET 失败: HTTP {exc.code}: {detail}")


def _container_post(endpoint: str, payload: Dict[str, Any], timeout: int = 60) -> Dict[str, Any]:
    url = f"{DATA_METHOD_BASE_URL}/{endpoint.lstrip('/')}"
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"token": DATA_METHOD_TOKEN, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            data = json.loads(raw)
            if data.get("code", 0) != 0:
                raise Exception(data.get("msg") or "数据处理服务返回错误")
            return data
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore") if hasattr(exc, "read") else str(exc)
        raise Exception(f"容器服务 POST 失败: HTTP {exc.code}: {detail}")


def _resolve_data_id(profile_item: Dict[str, Any]) -> str:
    profile_data = profile_item.get("profile", {}) or {}
    file_path = str(profile_item.get("file_path") or "").strip()

    data_id = (
        profile_item.get("data_id")
        or profile_item.get("uploaded_data_id")
        or profile_item.get("remote_data_id")
        or profile_data.get("data_id")
        or profile_data.get("id")
    )
    if data_id:
        return str(data_id).strip()

    if not file_path:
        return ""

    match = re.search(r"/data/([^/?#]+)", file_path)
    if match:
        return match.group(1).strip()

    if file_path.startswith("http://") or file_path.startswith("https://"):
        return file_path.rstrip("/").split("/")[-1].strip()

    return ""


def _find_profile_for_slot(data_profiles: List[Dict[str, Any]], input_name: str) -> Optional[Dict[str, Any]]:
    normalized_name = _normalize_text(input_name)
    for item in data_profiles:
        slot_key = _normalize_text(item.get("slot_key"))
        if slot_key and slot_key == normalized_name:
            return item

    for item in data_profiles:
        if item.get("file_path"):
            return item

    return None


def _is_parameter_slot(input_name: str, profile_item: Optional[Dict[str, Any]], model_contract: Dict[str, Any]) -> bool:
    if profile_item:
        file_path = _normalize_text(profile_item.get("file_path"))
        profile = profile_item.get("profile", {}) or {}
        form = _normalize_text(profile.get("Form"))
        if file_path.startswith("manual://") or form == "parameter":
            return True

    required_slots = model_contract.get("Required_slots", []) or []
    for slot in required_slots:
        slot_name = _normalize_text(slot.get("Input_name") or slot.get("input_name"))
        if slot_name == _normalize_text(input_name):
            return _normalize_text(slot.get("Data_type")) == "parameter"

    return False


def _list_methods_by_keyword(keyword: str, limit: int = 100, max_pages: int = 2) -> List[Dict[str, Any]]:
    methods: List[Dict[str, Any]] = []
    for page in range(1, max_pages + 1):
        params = {"page": page, "limit": limit}
        if keyword:
            params["key"] = keyword
        data = _container_get("container/method/listWithTag", params=params)
        page_data = data.get("page", {}) or {}
        methods.extend(page_data.get("list", []) or [])
        total_count = int(page_data.get("totalCount") or 0)
        if page * limit >= total_count:
            break
    return methods


def collect_method_catalog_node(state: ExecuteState) -> Dict[str, Any]:
    """拉取候选方法库，供 LLM 在下一步选择。"""
    alignment_result = state.get("alignment_result", {}) or {}
    per_slot = alignment_result.get("per_slot", []) or []
    suggested = alignment_result.get("suggested_transformations", []) or []

    keywords: List[str] = []
    for slot in per_slot:
        input_name = str(slot.get("input_name") or "").strip()
        if input_name:
            keywords.append(input_name)
        for action in slot.get("actions", []) or []:
            keywords.extend(re.findall(r"[\u4e00-\u9fa5A-Za-z0-9_\-]+", str(action)))
    for text in suggested:
        keywords.extend(re.findall(r"[\u4e00-\u9fa5A-Za-z0-9_\-]+", str(text)))

    # 保留少量关键词，避免拉取过多数据影响性能。
    normalized = []
    for token in keywords + ["转换", "convert", "重投影", "裁剪", "重采样"]:
        t = _normalize_text(token)
        if t and len(t) >= 2 and t not in normalized:
            normalized.append(t)
    normalized = normalized[:8]

    candidate_map: Dict[str, Dict[str, Any]] = {}
    for token in normalized:
        try:
            items = _list_methods_by_keyword(token)
        except Exception:
            continue

        for item in items:
            method_name = str(item.get("name") or "").strip()
            method_id = str(item.get("id") or "").strip()
            if not method_name:
                continue

            key = method_id or method_name
            current = candidate_map.get(key)
            if not current:
                current = {
                    "id": item.get("id"),
                    "name": method_name,
                    "description": str(item.get("description") or ""),
                    "longDesc": str(item.get("longDesc") or ""),
                    "params": item.get("params") or [],
                    "score": 0.0,
                }
                candidate_map[key] = current

            searchable = " ".join(
                [
                    current.get("name", ""),
                    current.get("description", ""),
                    current.get("longDesc", ""),
                    json.dumps(current.get("params", []), ensure_ascii=False),
                ]
            ).lower()
            if token in searchable:
                current["score"] = float(current.get("score", 0.0)) + 1.0

    methods = sorted(candidate_map.values(), key=lambda x: float(x.get("score", 0.0)), reverse=True)[:60]
    return {"available_methods": methods, "status": "methods_ready"}


def plan_execution_node(state: ExecuteState) -> Dict[str, Any]:
    """把对齐问题和方法库喂给大模型，生成每个槽位的执行方法计划。"""
    alignment_result = state.get("alignment_result", {}) or {}
    model_contract = state.get("model_contract", {}) or {}
    data_profiles = state.get("data_profiles", []) or []
    available_methods = state.get("available_methods", []) or []

    per_slot = alignment_result.get("per_slot", []) or []
    targets: List[Dict[str, Any]] = []
    for slot in per_slot:
        input_name = str(slot.get("input_name") or "").strip()
        slot_status = _normalize_text(slot.get("overall_status") or slot.get("spec_alignment", {}).get("status"))
        if not input_name or slot_status not in ["partial", "mismatch", "missing"]:
            continue

        profile_item = _find_profile_for_slot(data_profiles, input_name)
        if _is_parameter_slot(input_name, profile_item, model_contract):
            continue

        targets.append(
            {
                "input_name": input_name,
                "slot_status": slot_status,
                "actions": slot.get("actions", []) or [],
                "profile_hint": {
                    "file_path": profile_item.get("file_path") if profile_item else "",
                    "form": (profile_item.get("profile", {}) or {}).get("Form") if profile_item else "",
                },
            }
        )

    if not targets:
        return {
            "execution_targets": [],
            "execution_plan": [],
            "status": "plan_ready",
        }

    method_index = [
        {
            "name": item.get("name", ""),
            "description": item.get("description", ""),
            "longDesc": item.get("longDesc", ""),
            "params": item.get("params", []),
        }
        for item in available_methods[:40]
    ]

    system_prompt = """你是数据转换方法规划智能体。\n
    你会根据待修复槽位和候选方法列表，给每个槽位选择一个最合适的方法名。\n\n
    输出必须是 JSON，结构如下：\n
    {\n  \"plans\": 
        [\n    
            {\n
                \"input_name\": \"...\",\n
                \"method_name\": \"...\",\n
                \"reason\": \"...\"\n
            }\n  
        ],\n
        \"notes\":
        [\"...\"]
        \n}\n\n
        约束：\n
        1) method_name 必须来自候选方法列表。\n
        2) 若找不到合适方法，不要编造，可不返回该槽位。\n
        3) 优先考虑语义匹配和参数数量可执行性。
        """

    user_prompt = f"""待修复槽位：\n{json.dumps(targets, ensure_ascii=False)}\n\n候选方法列表：\n{json.dumps(method_index, ensure_ascii=False)}"""

    response = execute_model.invoke([SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)])
    raw_text = extract_text_content(response.content)
    parsed = parse_json_from_text(raw_text)

    valid_names = {str(item.get("name") or "").strip() for item in available_methods}
    valid_slots = {item["input_name"] for item in targets}

    plans: List[Dict[str, Any]] = []
    for plan in parsed.get("plans", []) or []:
        input_name = str(plan.get("input_name") or "").strip()
        method_name = str(plan.get("method_name") or "").strip()
        if input_name in valid_slots and method_name in valid_names:
            plans.append(
                {
                    "input_name": input_name,
                    "method_name": method_name,
                    "reason": str(plan.get("reason") or ""),
                }
            )

    print(f"生成的执行计划: {json.dumps(plans, ensure_ascii=False, indent=2)}")

    return {
        "messages": [response],
        "execution_targets": targets,
        "execution_plan": plans,
        "status": "plan_ready",
    }


async def execute_plan_node(state: ExecuteState) -> Dict[str, Any]:
    """根据 LLM 输出的计划逐项调用远程方法，并把结果回写到 alignment_result。"""
    alignment_result = state.get("alignment_result", {}) or {}
    model_contract = state.get("model_contract", {}) or {}
    data_profiles = state.get("data_profiles", []) or []
    execution_targets = state.get("execution_targets", []) or []
    execution_plan = state.get("execution_plan", []) or []

    attempts: List[Dict[str, Any]] = []
    
    # 若无执行计划但有待修复目标，生成"需要人工选择"的记录，避免 attempted=0
    if not execution_plan and execution_targets:
        for target in execution_targets:
            attempts.append(
                {
                    "input_name": target.get("input_name"),
                    "status": "needs_manual_selection",
                    "reason": "未匹配到可执行方法或 LLM 未返回有效方案，请人工选择转换方法",
                }
            )
    
    for item in execution_plan:
        input_name = str(item.get("input_name") or "").strip()
        method_name = str(item.get("method_name") or "").strip()
        if not input_name or not method_name:
            continue

        profile_item = _find_profile_for_slot(data_profiles, input_name)
        if _is_parameter_slot(input_name, profile_item, model_contract):
            attempts.append({"input_name": input_name, "status": "skipped", "reason": "参数槽位不执行文件转换"})
            continue

        if not profile_item:
            attempts.append({"input_name": input_name, "status": "skipped", "reason": "未找到对应的数据文件"})
            continue

        file_path = str(profile_item.get("file_path") or "")
        file_extension = ""
        if file_path and "." in file_path:
            file_extension = "." + file_path.split(".")[-1]

        data_id = _resolve_data_id(profile_item)
        if not data_id:
            attempts.append(
                {
                    "input_name": input_name,
                    "status": "failed",
                    "method_name": method_name,
                    "error": "缺少可用的数据 ID，请先上传数据并提供 data_id",
                }
            )
            continue

        try:
            detail = await asyncio.to_thread(
                _container_get,
                f"container/method/infoByName/{urllib.parse.quote(method_name, safe='')}",
            )
            method = detail.get("method") or {}
            method_id = method.get("id")
            if method_id is None:
                raise Exception(f"方法 {method_name} 未返回 method id")

            result_file_name = f"result_{int(datetime.now().timestamp())}{file_extension}"
            invoke_payload = {"val0": data_id, "val1": result_file_name}
            invoke_resp = await asyncio.to_thread(
                _container_post,
                f"container/method/invoke/{method_id}",
                invoke_payload,
                120,
            )

            attempts.append(
                {
                    "input_name": input_name,
                    "status": "success",
                    "method_name": method_name,
                    "request": {"dataId": data_id, "resultFileName": result_file_name},
                    "response": {
                        "code": invoke_resp.get("code", 0),
                        "msg": invoke_resp.get("msg", ""),
                        "output": invoke_resp.get("output", {}),
                    },
                }
            )
        except Exception as exc:
            attempts.append(
                {
                    "input_name": input_name,
                    "status": "failed",
                    "method_name": method_name,
                    "error": str(exc),
                }
            )

    success_count = len([x for x in attempts if x.get("status") == "success"])
    failed_count = len([x for x in attempts if x.get("status") == "failed"])

    alignment_result["transformation_attempts"] = attempts
    alignment_result["auto_transform_summary"] = {
        "attempted": len(attempts),
        "success": success_count,
        "failed": failed_count,
        "invoke_url": f"{DATA_METHOD_BASE_URL}/container/method/invoke/{{methodId}}",
    }

    recommended_actions = alignment_result.get("recommended_actions", []) or []
    if success_count > 0:
        recommended_actions.append("已触发自动转换，请对转换结果重新执行数据扫描与对齐")
    elif attempts:
        recommended_actions.append("自动转换未成功，请检查 data_id、方法匹配和服务连通性")
    else:
        recommended_actions.append("当前未识别到可自动转换的文件型槽位")

    alignment_result["recommended_actions"] = list(dict.fromkeys(recommended_actions))

    return {"alignment_result": alignment_result, "status": "completed"}


def build_execute_graph():
    graph_builder = StateGraph(ExecuteState)
    graph_builder.add_node("collect_method_catalog_node", collect_method_catalog_node)
    graph_builder.add_node("plan_execution_node", plan_execution_node)
    graph_builder.add_node("execute_plan_node", execute_plan_node)
    graph_builder.add_edge(START, "collect_method_catalog_node")
    graph_builder.add_edge("collect_method_catalog_node", "plan_execution_node")
    graph_builder.add_edge("plan_execution_node", "execute_plan_node")
    graph_builder.add_edge("execute_plan_node", END)
    return graph_builder.compile()


execute_agent = build_execute_graph()
