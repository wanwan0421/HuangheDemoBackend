import json
import os
import re
import operator
from typing import TypedDict, Dict, Any, List, Annotated, Optional, Set
from langchain.messages import HumanMessage, SystemMessage, AnyMessage
from langgraph.graph import StateGraph, START, END
from langchain_google_genai import ChatGoogleGenerativeAI
from dotenv import load_dotenv

load_dotenv()
AIHUBMIX_API_KEY = os.getenv("AIHUBMIX_API_KEY")
AIHUBMIX_BASE_URL = "https://aihubmix.com/v1"

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

alignment_model = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    temperature=0.2,
    max_retries=2,
    streaming=False,
    google_api_key=GOOGLE_API_KEY,
)

class AlignmentState(TypedDict):
    messages: Annotated[List[AnyMessage], operator.add]
    Task_spec: Annotated[Dict[str, Any], operator.or_]
    Model_contract: Annotated[Dict[str, Any], operator.or_]
    Data_profile: Annotated[Dict[str, Any], operator.or_]
    Alignment_result: Annotated[Dict[str, Any], operator.or_]
    status: str


def extract_text_content(content: Any) -> str:
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
    return str(value or "").strip().lower()


def _normalize_form(value: Any) -> str:
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
    spatial_req = slot.get("Spatial_requirement") or {}
    if isinstance(spatial_req, dict):
        crs = spatial_req.get("Crs") or spatial_req.get("CRS") or spatial_req.get("crs")
        text = str(crs).strip() if crs else ""
        return text or None
    return None


def _extract_data_sources(data_profile: Dict[str, Any]) -> List[Dict[str, Any]]:
    data_sources = data_profile.get("data_sources")
    if isinstance(data_sources, list) and data_sources:
        return data_sources

    return [{
        "file_path": data_profile.get("primary_file") or "single",
        "form": data_profile.get("Form"),
        "spatial": data_profile.get("Spatial"),
    }]


def _source_form_set(data_profile: Dict[str, Any]) -> Set[str]:
    forms: Set[str] = set()
    for source in _extract_data_sources(data_profile):
        form = _normalize_form(source.get("form"))
        if form:
            forms.add(form)
    return forms


def _source_crs_tokens(data_profile: Dict[str, Any]) -> Set[str]:
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

        if expected_crs:
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


def alignment_node(state: AlignmentState) -> Dict[str, Any]:
    task_spec = state.get("Task_spec", {}) or {}
    model_contract = state.get("Model_contract", {}) or {}
    data_profile = state.get("Data_profile", {}) or {}

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
    alignment_result = _apply_rule_validation(alignment_result, model_contract, data_profile)

    return {
        "messages": [response],
        "Alignment_result": alignment_result,
        "status": "completed"
    }


def build_alignment_graph():
    graph_builder = StateGraph(AlignmentState)
    graph_builder.add_node("alignment_node", alignment_node)
    graph_builder.add_edge(START, "alignment_node")
    graph_builder.add_edge("alignment_node", END)
    return graph_builder.compile()


alignment_agent = build_alignment_graph()
