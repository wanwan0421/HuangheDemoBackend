"""
Task Agent Graph: 任务规范解析和标准化
负责从用户自然语言输入中提取结构化的任务规范
"""

import json
import re
import operator
from typing import TypedDict, Dict, Any, List, Annotated
from langchain.messages import HumanMessage, SystemMessage, AnyMessage, AIMessage
from langgraph.graph import StateGraph, START, END
from langchain_google_genai import ChatGoogleGenerativeAI
from dotenv import load_dotenv
import os

load_dotenv()
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

task_model = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    temperature=0.1,
    max_retries=2,
    streaming=False,
    google_api_key=GOOGLE_API_KEY,
)


class TaskState(TypedDict):
    """Task Agent 状态"""
    messages: Annotated[List[AnyMessage], operator.add]
    user_input: str
    Task_spec: Annotated[Dict[str, Any], operator.or_]
    status: str


def extract_text_content(content: Any) -> str:
    """提取文本内容，兼容不同格式"""
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
    """从文本中提取JSON"""
    raw_text = raw_text.strip()
    if not raw_text:
        return {}

    # 尝试提取代码块中的JSON
    json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw_text, re.DOTALL)
    if json_match:
        raw_text = json_match.group(1)

    # 尝试直接解析
    if raw_text.startswith("{") and raw_text.endswith("}"):
        try:
            return json.loads(raw_text)
        except json.JSONDecodeError:
            pass

    # 尝试提取第一个完整的JSON对象
    fallback_match = re.search(r"(\{.*\})", raw_text, re.DOTALL)
    if fallback_match:
        try:
            return json.loads(fallback_match.group(1))
        except json.JSONDecodeError:
            pass

    return {}


def parse_task_spec_node(state: TaskState) -> Dict[str, Any]:
    """
    解析用户输入，生成任务规范
    
    任务规范包含：
    - Domain: 应用领域（如水文模拟、气候预测、生态评估等）
    - Target_object: 目标对象（如河流流量、降水量、植被指数等）
    - Spatial_scope: 空间范围和坐标系要求
    - Temporal_scope: 时间范围和时间分辨率要求
    - Resolution_requirements: 精度要求（空间分辨率、时间分辨率、数值精度等）
    - Additional_constraints: 其他约束条件
    """
    
    user_input = state.get("user_input", "")
    current_task_spec = state.get("Task_spec", {}) or {}
    
    system_prompt = """你是地理建模任务规范解析专家。请从用户输入中提取并标准化任务规范。

**任务规范结构** (必须严格遵循以下JSON结构):
{
  "Domain": "应用领域（如：水文模拟、气候预测、生态评估、灾害评估等）",
  "Target_object": "目标对象或变量（如：河流径流量、降水量、地表温度、植被覆盖度等）",
  "Spatial_scope": {
    "description": "空间范围描述（如：黄河流域、长江中下游、全国范围等）",
    "bbox": [minX, minY, maxX, maxY],  // 如果有具体坐标
    "crs_requirement": "坐标系要求（如：EPSG:4326, EPSG:3857）或'不限'",
    "spatial_resolution": "空间分辨率要求（如：30m, 1km, 0.1度）或'不限'"
  },
  "Temporal_scope": {
    "description": "时间范围描述",
    "start_time": "开始时间（ISO格式或描述性，如'2020-01-01'或'近十年'）",
    "end_time": "结束时间",
    "temporal_resolution": "时间分辨率（如：日、月、年、小时）",
    "is_realtime": false  // 是否需要实时数据
  },
  "Resolution_requirements": {
    "spatial": "空间精度要求的详细说明",
    "temporal": "时间精度要求的详细说明",
    "numerical": "数值精度要求（如：小数点后几位、有效数字等）",
    "priority": "精度优先级（spatial > temporal，或反之）"
  },
  "Additional_constraints": {
    "data_quality": "数据质量要求",
    "computation_constraints": "计算约束（如：内存、时间限制）",
    "output_format": "期望的输出格式",
    "other": "其他特殊要求"
  }
}

**解析原则**:
1. 如果用户输入不明确，标注为"待确认"或"用户未指定"
2. 对于空间范围，尽量推断具体区域名称
3. 对于时间范围，理解相对时间（如"最近5年"、"历史数据"）
4. 对于精度要求，从任务类型推断合理的默认值
5. 必须输出完整的JSON结构，不要遗漏任何字段

**重要**: 只输出JSON，不要有其他文字解释。
"""

    user_message = f"""用户输入: {user_input}

当前已有任务规范: {json.dumps(current_task_spec, ensure_ascii=False, indent=2) if current_task_spec else '无'}

请解析或更新任务规范。"""

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_message)
    ]
    
    response = task_model.invoke(messages)
    raw_content = extract_text_content(response.content)
    
    # 解析JSON
    task_spec = parse_json_from_text(raw_content)
    
    if not task_spec:
        # 如果解析失败，保留原有的或返回最小结构
        task_spec = current_task_spec if current_task_spec else {
            "Domain": "待确认",
            "Target_object": "待确认",
            "Spatial_scope": {},
            "Temporal_scope": {},
            "Resolution_requirements": {},
            "Additional_constraints": {}
        }
        status = "parse_failed"
    else:
        status = "completed"
    
    return {
        "messages": [AIMessage(content=f"任务规范已生成:\n{json.dumps(task_spec, ensure_ascii=False, indent=2)}")],
        "Task_spec": task_spec,
        "status": status
    }


def validate_task_spec_node(state: TaskState) -> Dict[str, Any]:
    """
    验证任务规范的完整性和合理性
    """
    task_spec = state.get("Task_spec", {})
    
    validation_results = {
        "is_valid": True,
        "missing_fields": [],
        "warnings": [],
        "recommendations": []
    }
    
    # 检查必要字段
    required_fields = ["Domain", "Target_object", "Spatial_scope", "Temporal_scope"]
    for field in required_fields:
        if field not in task_spec or not task_spec[field]:
            validation_results["missing_fields"].append(field)
            validation_results["is_valid"] = False
    
    # 检查空间范围
    spatial_scope = task_spec.get("Spatial_scope", {})
    if not spatial_scope.get("description") and not spatial_scope.get("bbox"):
        validation_results["warnings"].append("空间范围描述不够具体")
    
    # 检查时间范围
    temporal_scope = task_spec.get("Temporal_scope", {})
    if not temporal_scope.get("description") and not temporal_scope.get("start_time"):
        validation_results["warnings"].append("时间范围描述不够具体")
    
    # 检查坐标系要求
    if not spatial_scope.get("crs_requirement"):
        validation_results["recommendations"].append("建议明确坐标系要求，以便数据对齐")
    
    status = "validated" if validation_results["is_valid"] else "validation_failed"
    
    return {
        "messages": [AIMessage(content=f"验证结果: {json.dumps(validation_results, ensure_ascii=False, indent=2)}")],
        "status": status
    }


# 构建Task Agent图
def build_task_agent():
    """构建Task Agent工作流"""
    workflow = StateGraph(TaskState)
    
    # 添加节点
    workflow.add_node("parse_task_spec", parse_task_spec_node)
    workflow.add_node("validate_task_spec", validate_task_spec_node)
    
    # 添加边
    workflow.add_edge(START, "parse_task_spec")
    workflow.add_edge("parse_task_spec", "validate_task_spec")
    workflow.add_edge("validate_task_spec", END)
    
    return workflow.compile()


# 导出agent实例
task_agent = build_task_agent()


def run_task_agent(user_input: str, existing_task_spec: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    运行Task Agent
    
    Args:
        user_input: 用户输入
        existing_task_spec: 已有的任务规范（用于更新）
    
    Returns:
        包含Task_spec的结果字典
    """
    initial_state = {
        "messages": [],
        "user_input": user_input,
        "Task_spec": existing_task_spec or {},
        "status": "started"
    }
    
    result = task_agent.invoke(initial_state)
    return result
