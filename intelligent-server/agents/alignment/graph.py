import json
import os
import re
import operator
from typing import TypedDict, Dict, Any, List, Annotated
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

    return {
        "messages": [response],
        "Alignment_result": alignment.get("Alignment_result", alignment),
        "status": "completed"
    }


def build_alignment_graph():
    graph_builder = StateGraph(AlignmentState)
    graph_builder.add_node("alignment_node", alignment_node)
    graph_builder.add_edge(START, "alignment_node")
    graph_builder.add_edge("alignment_node", END)
    return graph_builder.compile()


alignment_agent = build_alignment_graph()
