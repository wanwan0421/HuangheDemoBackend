import json
import os
import re
import operator
from typing import TypedDict, Dict, Any, List, Annotated, Optional, Set
from langchain.messages import HumanMessage, SystemMessage, AnyMessage
from langgraph.graph import StateGraph, START, END
from langchain_google_genai import ChatGoogleGenerativeAI
from dotenv import load_dotenv

from agents.execute.graph import execute_agent

"""Alignment 图：负责对齐任务规范、模型契约与数据画像，并给出可执行决策包。

整体流程：
1) alignment_node：调用 LLM 生成初始对齐结果
2) decision_package_node：补充可运行性判断和行动建议
3) auto_transform_node：按需触发自动转换执行器
"""

load_dotenv()
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

alignment_model = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    temperature=0.2,
    max_retries=2,
    streaming=False,
    google_api_key=GOOGLE_API_KEY,
)

def _replace_state_value(current: Any, incoming: Any) -> Any:
    # LangGraph reducer：当新值为 None 时保留旧值，否则直接替换。
    # 这里用于 Data_profiles，避免列表执行错误的“合并”语义。
    return current if incoming is None else incoming

class AlignmentState(TypedDict, total=False):
    # messages 采用追加语义，保留链路上的消息轨迹。
    messages: Annotated[List[AnyMessage], operator.add]
    # 任务规范、模型契约与数据画像采用并集更新语义。
    Task_spec: Annotated[Dict[str, Any], operator.or_]
    Model_contract: Annotated[Dict[str, Any], operator.or_]
    Data_profile: Annotated[Dict[str, Any], operator.or_]
    # 多文件场景下由外部传入完整列表，使用替换reducer。
    Data_profiles: Annotated[List[Dict[str, Any]], _replace_state_value]
    # 对齐结果和状态，后续节点基于此进行决策和执行。
    Alignment_result: Annotated[Dict[str, Any], operator.or_]
    alignment_status: str
    auto_transform: bool
    status: str

def extract_text_content(content: Any) -> str:
    """兼容不同模型返回格式，提取可解析的纯文本。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                parts.append(part.get("text", ""))
            elif isinstance(part, str):
                parts.append(part)
        return "".join(parts)
    return ""

def parse_json_from_text(raw_text: str) -> Dict[str, Any]:
    """从 LLM 输出中提取 JSON。

    支持三种常见格式：
    - ```json ... ``` 代码块
    - 纯对象文本
    - 文本中夹带的对象片段
    """
    raw_text = raw_text.strip()
    if not raw_text:
        return {}

    json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw_text, re.DOTALL)
    if json_match:
        raw_text = json_match.group(1)

    if raw_text.startswith("{") and raw_text.endswith("}"):
        return json.loads(raw_text)

    fallback_match = re.search(r"(\{.*\})", raw_text, re.DOTALL)
    if fallback_match:
        return json.loads(fallback_match.group(1))

    return {}

def _normalize_text(value: Any) -> str:
    """统一做字符串化、去空白、小写，便于规则比较。"""
    return str(value or "").strip().lower()

def _normalize_form(value: Any) -> str:
    """将不同来源的数据形态别名归一到统一类别。"""
    raw = _normalize_text(value)
    if raw in ["raster", "grid"]:
        return "raster"
    if raw in ["vector", "shapefile", "geojson", "kml", "gml", "shp"]:
        return "vector"
    if raw in ["table", "csv", "xlsx", "xls"]:
        return "table"
    if raw in ["timeseries", "time series", "nc", "netcdf", "hdf", "h5"]:
        return "timeseries"
    if raw in ["parameter", "xml"]:
        return "parameter"
    return raw

def _expected_forms_from_requirement(slot: Dict[str, Any]) -> Set[str]:
    """根据模型输入数据槽位描述推断可接受的数据形态集合。"""
    combined = " ".join([
        _normalize_text(slot.get("Data_type")),
        _normalize_text(slot.get("Format_requirement")),
    ])

    expected: Set[str] = set()
    if any(k in combined for k in ["tif", "tiff", "geotiff", "raster", "img", "vrt", "asc"]):
        expected.add("raster")
    if any(k in combined for k in ["shp", "shapefile", "geojson", "kml", "gml", "vector"]):
        expected.add("vector")
    if any(k in combined for k in ["csv", "xlsx", "xls", "table"]):
        expected.add("table")
    if any(k in combined for k in ["nc", "netcdf", "hdf", "h5", "timeseries", "time series"]):
        expected.add("timeseries")
    if any(k in combined for k in ["parameter", "xml"]):
        expected.add("parameter")

    return expected

def _extract_expected_crs(slot: Dict[str, Any]) -> Optional[str]:
    """从模型输入数据契约中Spatial_requirement中提取CRS。"""
    spatial_req = slot.get("Spatial_requirement") or {}
    if isinstance(spatial_req, dict):
        crs = spatial_req.get("Crs") or spatial_req.get("CRS") or spatial_req.get("crs")
        text = str(crs).strip() if crs else ""
        return text or None
    return None


def _extract_data_sources(data_profile: Dict[str, Any]) -> List[Dict[str, Any]]:
    """统一取数源列表；单文件画像会被包装为一个虚拟 data_source。"""
    data_sources = data_profile.get("data_sources")
    if isinstance(data_sources, list) and data_sources:
        return data_sources

    return [{
        "file_path": data_profile.get("primary_file") or "single",
        "form": data_profile.get("Form"),
        "spatial": data_profile.get("Spatial"),
    }]


def _source_form_set(data_profile: Dict[str, Any]) -> Set[str]:
    """收集当前输入中实际可用的数据形态集合。"""
    forms: Set[str] = set()
    for source in _extract_data_sources(data_profile):
        form = _normalize_form(source.get("form"))
        if form:
            forms.add(form)
    return forms


def _source_crs_tokens(data_profile: Dict[str, Any]) -> Set[str]:
    """将数据源 CRS 信息拆分为可比对 token（EPSG/Name/WKT 等）。"""
    tokens: Set[str] = set()
    for source in _extract_data_sources(data_profile):
        spatial = source.get("spatial") or {}
        crs = (spatial.get("Crs") if isinstance(spatial, dict) else None) or {}

        if isinstance(crs, dict):
            for key in ["EPSG", "Name", "Wkt", "Projection", "Datum"]:
                value = crs.get(key)
                if value:
                    tokens.add(_normalize_text(value))
        elif isinstance(crs, str):
            tokens.add(_normalize_text(crs))
    return tokens


def _ensure_slot_item(alignment_result: Dict[str, Any], input_name: str) -> Dict[str, Any]:
    """确保 per_slot 中存在指定槽位，若不存在则创建默认结构。"""
    per_slot = alignment_result.setdefault("per_slot", [])
    for item in per_slot:
        if _normalize_text(item.get("input_name")) == _normalize_text(input_name):
            return item

    slot_item = {
        "input_name": input_name,
        "semantic_alignment": {"score": 0.5, "status": "partial", "evidence": [], "gaps": []},
        "spatiotemporal_alignment": {"score": 0.5, "status": "partial", "evidence": [], "gaps": []},
        "spec_alignment": {"score": 0.5, "status": "partial", "evidence": [], "gaps": []},
        "actions": [],
    }
    per_slot.append(slot_item)
    return slot_item


def _apply_rule_validation(
    alignment_result: Dict[str, Any],
    model_contract: Dict[str, Any],
    data_profile: Dict[str, Any],
) -> Dict[str, Any]:
    """在 LLM 结果上叠加确定性规则校验，降低幻觉风险。

    规则目前覆盖：
    - 格式/形态强校验（可阻塞）
    - CRS 软校验（默认非阻塞，参数类型跳过）
    """
    required_slots = model_contract.get("Required_slots", []) or []
    if not required_slots:
        return alignment_result

    forms_available = _source_form_set(data_profile)
    crs_tokens = _source_crs_tokens(data_profile)

    blocking_issues = alignment_result.setdefault("blocking_issues", [])
    non_blocking_issues = alignment_result.setdefault("non_blocking_issues", [])

    for slot in required_slots:
        input_name = slot.get("Input_name") or slot.get("input_name") or "unknown_input"
        expected_forms = _expected_forms_from_requirement(slot)
        expected_crs = _extract_expected_crs(slot)
        slot_item = _ensure_slot_item(alignment_result, input_name)

        if expected_forms and forms_available and forms_available.isdisjoint(expected_forms):
            expected_text = "/".join(sorted(expected_forms))
            actual_text = "/".join(sorted(forms_available))
            gap_text = f"格式不匹配：期望 {expected_text}，实际 {actual_text}"
            slot_item["spec_alignment"].setdefault("gaps", []).append(gap_text)
            slot_item["spec_alignment"]["status"] = "mismatch"
            slot_item["spec_alignment"]["score"] = 0.0
            slot_item.setdefault("actions", []).append("请上传符合格式要求的数据，或进行格式转换")
            blocking_issues.append(f"{input_name}: {gap_text}")

        # CRS 检查仅对非参数槽位进行，且跳过 N/A 类型。参数槽位无需空间参考系统检查。
        data_type = _normalize_text(slot.get("Data_type"))
        expected_crs_text = _normalize_text(expected_crs) if expected_crs else ""
        if expected_crs and data_type != "parameter" and expected_crs_text not in ["n/a", "na", "不适用"]:
            norm_expected = _normalize_text(expected_crs)
            crs_match = any(norm_expected in token or token in norm_expected for token in crs_tokens if token)
            if not crs_match:
                gap_text = f"CRS 可能不一致：期望 {expected_crs}"
                slot_item["spatiotemporal_alignment"].setdefault("gaps", []).append(gap_text)
                if slot_item["spatiotemporal_alignment"].get("status") != "mismatch":
                    slot_item["spatiotemporal_alignment"]["status"] = "partial"
                    slot_item["spatiotemporal_alignment"]["score"] = min(
                        0.4,
                        slot_item["spatiotemporal_alignment"].get("score", 0.5)
                    )
                slot_item.setdefault("actions", []).append("请检查并统一坐标参考系（CRS）")
                non_blocking_issues.append(f"{input_name}: {gap_text}")

    if blocking_issues:
        alignment_result["overall_score"] = min(alignment_result.get("overall_score", 0.0), 0.49)

    dedup_blocking = list(dict.fromkeys(blocking_issues))
    dedup_non_blocking = list(dict.fromkeys(non_blocking_issues))
    alignment_result["blocking_issues"] = dedup_blocking
    alignment_result["non_blocking_issues"] = dedup_non_blocking
    return alignment_result


def _alignment_status_from_score(overall_score: float) -> str:
    """把 overall_score 映射为离散状态。"""
    if overall_score >= 0.9:
        return "matched"
    if overall_score >= 0.5:
        return "partial"
    return "mismatch"


def _merge_data_profiles(data_profiles: List[Dict[str, Any]]) -> Dict[str, Any]:
    """将多文件 Data_profiles 合并为统一视图，便于一次性对齐。"""
    if not data_profiles:
        return {}

    if len(data_profiles) == 1:
        return data_profiles[0].get("profile", {})

    merged_profile: Dict[str, Any] = {
        "data_sources": [],
        "spatial_union": {},
        "temporal_union": {},
        "forms": [],
    }

    for data_profile in data_profiles:
        profile = data_profile.get("profile", {})
        merged_profile["data_sources"].append(
            {
                "file_id": data_profile.get("file_id"),
                "file_path": data_profile.get("file_path"),
                "form": profile.get("Form"),
                "spatial": profile.get("Spatial"),
                "temporal": profile.get("Temporal"),
            }
        )

        form = profile.get("Form")
        if form and form not in merged_profile["forms"]:
            merged_profile["forms"].append(form)

    return merged_profile


def _build_decision_package(
    alignment_result: Dict[str, Any],
    model_contract: Optional[Dict[str, Any]],
    status: str,
) -> Dict[str, Any]:
    """基于对齐结果生成执行决策包（go/no-go、风险、最小输入集等）。"""
    blocking_issues = alignment_result.get("blocking_issues", []) or []
    non_blocking_issues = alignment_result.get("non_blocking_issues", []) or []
    per_slot = alignment_result.get("per_slot", []) or []
    suggested_transformations = alignment_result.get("suggested_transformations", []) or []

    warnings = list(non_blocking_issues)
    minimal_runnable_inputs: List[str] = []
    mapping_plan_draft: List[Dict[str, Any]] = []

    for slot in per_slot:
        input_name = slot.get("input_name", "unknown")
        slot_status = slot.get("overall_status") or slot.get("spec_alignment", {}).get("status", "partial")

        if slot_status in ["match", "partial"]:
            minimal_runnable_inputs.append(input_name)

        if slot_status == "partial":
            warnings.append(f"{input_name}: 存在部分不匹配，建议先执行映射")

        actions = slot.get("actions", []) or []
        if actions:
            mapping_plan_draft.append(
                {
                    "input_name": input_name,
                    "priority": "high" if slot_status == "mismatch" else "medium",
                    "actions": actions,
                }
            )

    for transformation in suggested_transformations:
        mapping_plan_draft.append(
            {
                "input_name": "global",
                "priority": "medium",
                "actions": [transformation],
            }
        )

    required_slots = (model_contract or {}).get("Required_slots", []) or []
    file_estimate = len(minimal_runnable_inputs)
    required_count = len(required_slots)

    if blocking_issues:
        can_run_now = False
        go_no_go = "no-go"
        risk_level = "high"
    elif status in ["matched", "partial"]:
        can_run_now = True
        go_no_go = "go"
        risk_level = "medium" if warnings else "low"
    else:
        can_run_now = False
        go_no_go = "no-go"
        risk_level = "medium"

    recommended_actions: List[str] = []
    if blocking_issues:
        recommended_actions.append("存在阻塞问题，请先执行数据映射或补齐缺失输入后再运行模型")
    elif warnings:
        recommended_actions.append("可先用最小可运行输入集试跑，再迭代修复告警项")
    else:
        recommended_actions.append("可直接进入模型执行阶段")

    recommended_actions.append("修复后建议调用增量重扫接口，仅重扫变更文件并查看前后差异")

    estimated_minutes = max(2, required_count * 2)
    if required_count >= 8 or file_estimate >= 10:
        estimated_minutes = max(estimated_minutes, 20)

    return {
        "can_run_now": can_run_now,
        "go_no_go": go_no_go,
        "risk_level": risk_level,
        "warnings": warnings,
        "recommended_actions": recommended_actions,
        "minimal_runnable_inputs": list(dict.fromkeys(minimal_runnable_inputs)),
        "mapping_plan_draft": mapping_plan_draft,
        "execution_estimate": {
            "estimated_minutes": estimated_minutes,
            "required_slot_count": required_count,
            "available_input_count": file_estimate,
        },
    }


def _need_auto_transform(alignment_result: Dict[str, Any], alignment_status: str) -> bool:
    """判断是否需要进入自动转换阶段。"""
    if alignment_status in ["partial", "mismatch"]:
        return True

    per_slot = alignment_result.get("per_slot", []) or []
    for slot in per_slot:
        slot_status = _normalize_text(slot.get("overall_status") or slot.get("spec_alignment", {}).get("status"))
        if slot_status in ["partial", "mismatch", "missing"]:
            return True

    return False


def alignment_node(state: AlignmentState) -> Dict[str, Any]:
    """第一阶段：调用 LLM 生成 Alignment_result，并做解析兜底。"""
    task_spec = state.get("Task_spec", {}) or {}
    model_contract = state.get("Model_contract", {}) or {}
    data_profiles = state.get("Data_profiles", []) or []
    data_profile = state.get("Data_profile", {}) or {}
    if not data_profile and data_profiles:
        data_profile = _merge_data_profiles(data_profiles)

    system_prompt = """你是Alignment Agent。你的任务是对齐三方信息：
1) Task_spec（任务规范）
2) Model_contract（模型输入契约）
3) Data_profile（Scanner 产出的数据画像）

请基于三大维度生成对齐结果：
- 语义对齐（Semantic）：任务目标/模型语义 与 数据语义是否一致
- 时空对齐（Spatiotemporal）：空间范围、CRS、分辨率、时间范围/频率是否匹配
- 规格对齐（Spec）：数据形式、格式、字段/变量、数据类型是否满足模型契约

输出要求：
1) 仅输出 JSON
2) 给出每个输入槽位（Required_slots）的对齐结果
3) 给出全局总结、阻塞问题、可选修复建议
4) 评分区间为 0~1；status 仅允许: match | partial | mismatch
5) 当模型契约中的 CRS 描述为“推荐使用”而非“必须/严格要求”时，CRS 不一致默认判为 non_blocking_issues（警告）而非 blocking_issues；只有出现无法投影、空间参考缺失且无法推断、或会直接导致模型无法运行时，才可判为阻塞问题

JSON 结构示例（必须遵循）：
{
  "Alignment_result": {
    "overall_score": 0.0,
    "summary": "...",
    "dimensions": {
      "semantic": {"score": 0.0, "status": "partial", "evidence": [], "gaps": []},
      "spatiotemporal": {"score": 0.0, "status": "partial", "evidence": [], "gaps": []},
      "spec": {"score": 0.0, "status": "partial", "evidence": [], "gaps": []}
    },
    "per_slot": [
      {
        "input_name": "...",
        "semantic_alignment": {"score": 0.0, "status": "partial", "evidence": [], "gaps": []},
        "spatiotemporal_alignment": {"score": 0.0, "status": "partial", "evidence": [], "gaps": []},
        "spec_alignment": {"score": 0.0, "status": "partial", "evidence": [], "gaps": []},
        "actions": ["..."]
      }
    ],
    "blocking_issues": ["..."],
    "non_blocking_issues": ["..."],
    "suggested_transformations": ["..."]
  }
}
"""

    user_prompt = f"""请对齐以下三方信息：

Task_spec:
{json.dumps(task_spec, ensure_ascii=False)}

Model_contract:
{json.dumps(model_contract, ensure_ascii=False)}

Data_profile:
{json.dumps(data_profile, ensure_ascii=False)}
"""

    response = alignment_model.invoke([
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_prompt)
    ])

    raw_text = extract_text_content(response.content)
    try:
        alignment = parse_json_from_text(raw_text)
    except Exception:
        alignment = {}

    if "Alignment_result" not in alignment:
        alignment = {
            "Alignment_result": {
                "overall_score": 0.0,
                "summary": "对齐结果解析失败",
                "dimensions": {
                    "semantic": {"score": 0.0, "status": "mismatch", "evidence": [], "gaps": ["LLM输出无法解析"]},
                    "spatiotemporal": {"score": 0.0, "status": "mismatch", "evidence": [], "gaps": ["LLM输出无法解析"]},
                    "spec": {"score": 0.0, "status": "mismatch", "evidence": [], "gaps": ["LLM输出无法解析"]}
                },
                "per_slot": [],
                "blocking_issues": ["LLM输出无法解析"],
                "non_blocking_issues": [],
                "suggested_transformations": []
            },
            "raw": raw_text
        }

    alignment_result = alignment.get("Alignment_result", alignment)
    # LLM 结论后置规则校验：保证关键格式/CRS风险被稳定识别。
    alignment_result = _apply_rule_validation(alignment_result, model_contract, data_profile)
    alignment_status = _alignment_status_from_score(float(alignment_result.get("overall_score", 0.0)))

    return {
        "messages": [response],
        "Alignment_result": alignment_result,
        "alignment_status": alignment_status,
        "status": "aligned",
    }


def decision_package_node(state: AlignmentState) -> Dict[str, Any]:
    """第二阶段：补充决策信息，并与既有 recommended_actions 去重合并。"""
    alignment_result = state.get("Alignment_result", {}) or {}
    model_contract = state.get("Model_contract", {}) or {}
    alignment_status = state.get("alignment_status") or _alignment_status_from_score(
        float(alignment_result.get("overall_score", 0.0))
    )

    existing_actions = alignment_result.get("recommended_actions", []) or []
    decision = _build_decision_package(alignment_result, model_contract, alignment_status)
    decision_actions = decision.get("recommended_actions", []) or []
    decision["recommended_actions"] = list(dict.fromkeys([*existing_actions, *decision_actions]))
    alignment_result.update(decision)

    return {
        "Alignment_result": alignment_result,
        "alignment_status": alignment_status,
        "status": "decision_ready",
    }


async def auto_transform_node(state: AlignmentState) -> Dict[str, Any]:
    """第三阶段：按需触发 execute_agent 做自动转换，并回填结果摘要。"""
    # 自动转换阶段只在存在不匹配时触发，且执行逻辑委托给 execute 智能体。
    alignment_result = state.get("Alignment_result", {}) or {}
    alignment_status = state.get("alignment_status") or _alignment_status_from_score(
        float(alignment_result.get("overall_score", 0.0))
    )

    auto_transform = bool(state.get("auto_transform", False))
    if not auto_transform or not _need_auto_transform(alignment_result, alignment_status):
        return {
            "Alignment_result": alignment_result,
            "alignment_status": alignment_status,
            "status": "completed",
        }

    data_profiles = state.get("Data_profiles", []) or []
    if not data_profiles:
        recommended_actions = alignment_result.get("recommended_actions", []) or []
        recommended_actions.append("缺少 Data_profiles（含 file_path/data_id），已跳过自动转换")
        alignment_result["recommended_actions"] = list(dict.fromkeys(recommended_actions))
        return {
            "Alignment_result": alignment_result,
            "alignment_status": alignment_status,
            "status": "completed",
        }

    try:
        execute_state = {
            "messages": [],
            "alignment_result": alignment_result,
            "model_contract": state.get("Model_contract", {}) or {},
            "data_profiles": data_profiles,
            "status": "started",
        }
        execute_result = await execute_agent.ainvoke(execute_state)
        alignment_result = execute_result.get("alignment_result", alignment_result) or alignment_result
    except Exception as exc:
        recommended_actions = alignment_result.get("recommended_actions", []) or []
        alignment_result["recommended_actions"] = list(dict.fromkeys(recommended_actions))
        alignment_result["auto_transform_summary"] = {
            "attempted": 0,
            "success": 0,
            "failed": 0,
            "error": str(exc),
        }

    return {
        "Alignment_result": alignment_result,
        "alignment_status": alignment_status,
        "status": "completed", 
    }


def build_alignment_graph():
    """组装 LangGraph 拓扑：START -> 对齐 -> 决策 -> 自动转换 -> END。"""
    graph_builder = StateGraph(AlignmentState)
    graph_builder.add_node("alignment_node", alignment_node)
    graph_builder.add_node("decision_package_node", decision_package_node)
    graph_builder.add_node("auto_transform_node", auto_transform_node)
    graph_builder.add_edge(START, "alignment_node")
    graph_builder.add_edge("alignment_node", "decision_package_node")
    graph_builder.add_edge("decision_package_node", "auto_transform_node")
    graph_builder.add_edge("auto_transform_node", END)
    return graph_builder.compile()


alignment_agent = build_alignment_graph()
