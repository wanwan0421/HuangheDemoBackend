import json
import re
from typing import Dict, Any
from langchain.messages import HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import StateGraph, START, END
from . import tools
from .tools import DataScanState, data_scan_model


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


def parse_json_from_text(raw_text: str) -> Dict[str, Any]:
    raw_text = (raw_text or "").strip()
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


def tool_node(state: DataScanState) -> Dict[str, Any]:
    """
    确定性扫描阶段（规则优先，避免LLM主导扫描过程）
    执行顺序：prepare -> detect -> analyze_dataset -> validate
    """
    file_path = state.get("file_path", "")
    tool_messages = []
    summary_profile = dict(state.get("profile", {}))

    step_results = []

    prepare_result = tools.tool_prepare_file.invoke({"file_path": file_path})
    step_results.append(("tool_prepare_file", prepare_result))

    detect_result = tools.tool_detect_format.invoke({"file_path": file_path})
    step_results.append(("tool_detect_format", detect_result))

    dataset_result = tools.analyze_dataset(file_path)
    step_results.append(("tool_analyze_dataset", dataset_result))

    if dataset_result.get("status") == "success":
        summary_profile.update(dataset_result.get("data", {}))
    else:
        summary_profile.update({
            "Form": detect_result.get("Form", "Unknown"),
            "Confidence": detect_result.get("Confidence", 0.3),
            "Source_type": detect_result.get("Source_type"),
            "Source_forms": detect_result.get("Source_forms", []),
            "data_sources": [],
            "Temporal": {
                "Has_time": False,
                "Years": [],
                "Time_range": None,
                "Frequency_hint": "unknown",
                "Confidence": 0.2,
            },
        })

    validation_data = tools.validate_profile_consistency(summary_profile)
    validation_result = {"status": "success", "data": validation_data}
    step_results.append(("tool_validate_profile", validation_result))

    summary_profile["Validation"] = validation_data

    for idx, (name, result) in enumerate(step_results):
        tool_messages.append(ToolMessage(
            content=json.dumps(result, ensure_ascii=False),
            tool_call_id=f"manual_step_{idx}",
            tool_name=name,
        ))

    return {
        "messages": tool_messages,
        "profile": summary_profile,
        "status": "processing",
    }


def llm_node(state: DataScanState) -> Dict[str, Any]:
    """
    LLM只做语义补全，不参与工具调度与事实抽取
    """
    profile = state.get("profile", {}) or {}

    system_prompt = """你是GIS数据解释专家。基于已给出的结构化扫描结果生成语义信息，不得臆造事实。\n
请输出JSON，且只包含以下结构：
{
  "Semantic": {
    "Abstract": "...",
    "Applications": ["..."],
    "Tags": ["...", "...", "..."]
  }
}

要求：
1) Abstract 1-2句，数据摘要，简要描述数据内容,必须引用已有字段（如Form、Source_forms、Temporal、Validation）
2) Applications 适用场景，列出数据可能的应用领域，必须基于已有字段推断，不得凭空想象
3) Tags 3-5个关键词标签，帮助快速理解数据主题
4) 仅输出JSON
"""

    user_prompt = f"""请基于以下结构化数据画像补全Semantic：
{json.dumps(profile, ensure_ascii=False)}
"""

    semantic_data = {
        "Abstract": "基于规则扫描生成的数据画像",
        "Applications": ["数据入模前质检"],
        "Tags": ["gis", "data-scan", "validation"],
    }

    response = data_scan_model.invoke([
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_prompt),
    ])

    raw_text = extract_text_content(response.content)
    try:
        payload = parse_json_from_text(raw_text)
        semantic_candidate = payload.get("Semantic", payload)
        if isinstance(semantic_candidate, dict):
            semantic_data = {
                "Abstract": semantic_candidate.get("Abstract") or semantic_data["Abstract"],
                "Applications": semantic_candidate.get("Applications") or semantic_data["Applications"],
                "Tags": semantic_candidate.get("Tags") or semantic_data["Tags"],
            }
    except Exception:
        pass

    merged_profile = {**profile, "Semantic": semantic_data}
    return {
        "messages": [response],
        "status": "completed",
        "profile": merged_profile,
    }


agent_builder = StateGraph(DataScanState)
agent_builder.add_node("tool_node", tool_node)
agent_builder.add_node("llm_node", llm_node)
agent_builder.add_edge(START, "tool_node")
agent_builder.add_edge("tool_node", "llm_node")
agent_builder.add_edge("llm_node", END)

data_scan_agent = agent_builder.compile()
