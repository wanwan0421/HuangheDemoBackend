import json
from typing import Dict, Any, List
from langchain.messages import HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import StateGraph, START, END
from pydantic import BaseModel, Field
from . import tools
from .tools import DataScanState, data_scan_model


class SemanticPayload(BaseModel):
    Abstract: str = Field(default="基于规则扫描生成的数据画像")
    Applications: List[str] = Field(default_factory=lambda: ["数据入模前质检"])
    Tags: List[str] = Field(default_factory=lambda: ["gis", "data-scan", "validation"])


class SemanticEnvelope(BaseModel):
    Semantic: SemanticPayload = Field(default_factory=SemanticPayload)


def to_dict(model_obj: Any) -> Dict[str, Any]:
    if hasattr(model_obj, "model_dump"):
        return model_obj.model_dump()
    if hasattr(model_obj, "dict"):
        return model_obj.dict()
    if isinstance(model_obj, dict):
        return model_obj
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

    system_prompt = """你是GIS数据解释专家，负责把结构化扫描结果转成可读语义信息。

    任务目标：
    1) 只基于输入画像生成 Semantic，不得虚构任何未出现的信息。
    2) 语义需可追溯到已有字段，例如：Form、Source_forms、Spatial、Temporal、Quality、Validation、data_sources。
    3) 若关键信息缺失，使用保守表述（如“未明确提供时间分辨率”），不要猜测。

    输出要求（你将被结构化输出约束）：
    - Semantic.Abstract: 1-2句中文摘要，优先覆盖数据形态、时空特征、质量状态。
    - Semantic.Applications: 2-5个应用场景短语，必须由已有事实支持；避免空泛词和重复项。
    - Semantic.Tags: 3-5个主题标签，优先使用领域词、数据形态词、时空词（例如 hydrology, raster, timeseries, validation）。

    质量约束：
    - 不要输出与输入冲突的描述。
    - 若 Validation 中存在 issues/warnings，Abstract 中应简要体现风险。
    - 若 Temporal.Has_time 为 false，不要写“长期序列”“多年变化”等时间序列结论。
    - 若 Source_count > 1，可体现“多源数据”特征；否则避免“多源融合”措辞。
    """

    user_prompt = f"""请基于以下结构化数据画像补全Semantic：
        {json.dumps(profile, ensure_ascii=False)}
    """

    structured_llm = data_scan_model.with_structured_output(SemanticEnvelope)
    try:
        response = structured_llm.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ])
        payload = to_dict(response)
        semantic_candidate = payload.get("Semantic", payload)
        if isinstance(semantic_candidate, dict):
            semantic_data = {
                "Abstract": semantic_candidate.get("Abstract"),
                "Applications": semantic_candidate.get("Applications"),
                "Tags": semantic_candidate.get("Tags"),
            }
    except Exception:
        pass

    merged_profile = {**profile, "Semantic": semantic_data}
    return {
        "messages": [],
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
