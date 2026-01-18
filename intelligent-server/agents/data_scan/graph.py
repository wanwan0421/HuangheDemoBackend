import os
import json
from typing import TypedDict, Dict, Any, List, Optional, Annotated
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.messages import HumanMessage, SystemMessage, AnyMessage, ToolMessage
from langgraph.graph import StateGraph, START, END
from dotenv import load_dotenv
import operator
from google import genai
from . import tools
from .tools import DataScanState, data_scan_model

def llm_node(state: DataScanState) -> Dict[str, Any]:
    """
    负责根据当前用户上传的文件路径和已有工具结果，生成数据画像
    通过调用绑定工具的模型，返回模型产生的新消息和数据画像
    Args:
        state (DataScanState): 当前代理状态，包含消息历史等信息
    Returns:
        Dict[str, Any]: 更新后的状态，包含新消息和数据画像
    """
    system_message = f"""你是一个专业的地理空间数据分析专家。请根据用户上传的文件路径，生成该数据的语义画像。\n"
        
        **工作流程**:
        1.首先调用`tool_prepare_file`工具，传入文件路径，准备数据。
        2.根据准备的数据，调用`tool_detect_format`工具，检测数据类型。
        3.根据数据类型的检测结果，调用专项分析工具，包括`tool_analyze_raster`, `tool_analyze_vector`, `tool_analyze_table`, `tool_analyze_timeseries`, `tool_analyze_parameter`，提取元数据。
        4.只有当所有信息完整，且你不再需要调用任何工具时，才进行最后的总结。

        **重要规则**：
        1.必须先调用`tool_prepare_file`
        2.其中有些难以根据后缀名判断的数据类型，需要调用其他工具来读取数据进行详细判断
        3.所有工具调用完成后，基于已有的工具结果生成最终完整的profile
        4.最终返回的profile必须整合所有工具的分析结果

        **关键元数据**
        第一层：最小通用语义内核
        1.form：数据形式（Raster, Vector, Table, Timeseries, Parameter）
        2.spatial：空间域信息，包括crs：空间参考系统（如EPSG:4326）和extent：空间范围（如 [minX, minY, maxX, maxY]）
        3.temporal：时间域信息，包括has_time：是否包含时间维度，time_range：时间范围（如[start, end]）
        4.semantic：语义摘要，描述数据内容和用途

        第二层：类型化语义描述
        详细数据画像，依据数据形式包含不同字段
        1.Raster：
            -resolution：分辨率
            -band_count：波段数量
            -value_range：数值范围（如[min, max]）
            -nodata：无效值
        2.Vector：
            -feature_count：要素数量
            -geometry_type：几何类型（Point, Line, Polygon）
            -attributes：属性列表，每属性包含name, type, semantic
        3.Table：
            -row_count：行数
            -columns：列名
            -column_types：列类型映射（如name, type, semantic等）
            -sample_rows：样本数据行
        4.Timeseries：
            -dimensions：维度信息
            -variables：变量列表（如name, type, semantic等）
        5.Parameter：
            -value_type：值类型（int, float, string, boolean）
            -unit：单位

    当所有工具执行完毕，请基于所有的结果，生成该数据的解释说明，内容包括但不限于：
    1.数据的基本属性和特征
    2.数据的潜在用途和应用场景
    3.有无明显的使用限制或注意事项
    """

    user_message = f"""请根据以下信息，生成数据画像：
    文件路径: {state['file_path']}"""

    messages = [
        SystemMessage(content=system_message),
        HumanMessage(content=user_message)
    ] + state["messages"]

    response = tools.model_with_tools.invoke(messages)

    if not response.tool_calls:
        return {"messages": [response], "status": "completed", "explanation": extract_text_content(response.content)}

    return {"messages": [response], "status": "processing"}

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

def tool_node(state: DataScanState) -> Dict[str, Any]:
    """
    工具调用节点：根据当前状态调用相应工具，并累积结果
    Args:
        state (DataScanState): 当前代理状态，包含消息历史等信息
    Returns:
        Dict[str, Any]: 更新后的状态，包含新消息和工具结果
    """
    last_message = state["messages"][-1]
    tool_calls = getattr(last_message, "tool_calls", []) or []

    tool_messages = []
    summary_profile = dict(state.get("profile", {}))

    for tool_call in tool_calls:
        tool_name = tool_call["name"]
        tool = tools.TOOLS_BY_NAME[tool_name]
        result = tool.invoke(tool_call["args"])

        if result.get("status") =="success":
            data = result.get("data", {})

            # 语义映射规则
            if tool_name == "tool_prepare_file":
                summary_profile["primary_file"] = result.get("primary_file")
                summary_profile["file_type"] = result.get("file_type")

            elif tool_name == "tool_detect_format":
                summary_profile["Form"] = result.get("Form")
                summary_profile["Confidence"] = result.get("Confidence")

            elif tool_name == "tool_analyze_raster":
                summary_profile["Spatial"] = data.get("Spatial", {})
                summary_profile["Resolution"] = data.get("Resolution", {})
                summary_profile["Value_range"] = data.get("Value_range", {})
                summary_profile["Band_count"] = data.get("Band_count", "Unknown")
                summary_profile["NoData"] = data.get("NoData", "Unknown")

            elif tool_name == "tool_analyze_vector":
                summary_profile["Spatial"] = data.get("Spatial", {})
                summary_profile["Feature_count"] = data.get("Feature_count", "Unknown")
                summary_profile["Geometry_type"] = data.get("Geometry_type", "Unknown")
                summary_profile["Attributes"] = data.get("Attributes", [])

            elif tool_name == "tool_analyze_table":
                summary_profile["Row_count"] = data.get("Row_count", "Unknown")
                summary_profile["Columns"] = data.get("Columns", [])
                summary_profile["Dtypes"] = data.get("Dtypes", {})
                summary_profile["Sample_rows"] = data.get("Sample_rows", [])

            elif tool_name == "tool_analyze_timeseries":
                summary_profile["Dimensions"] = data.get("Dimensions", {})
                summary_profile["Variables"] = data.get("Variables", [])
                summary_profile["Has_time"] = data.get("Has_time", False)

            elif tool_name == "tool_analyze_parameter":
                summary_profile["Value_type"] = data.get("Value_type", "Unknown")
                summary_profile["Unit"] = data.get("Unit", "Unknown")

        tool_messages.append(ToolMessage(
            content=json.dumps(result, ensure_ascii=False),
            tool_call_id=tool_call["id"],
            tool_name=tool_name
        ))

    return {
        "messages": tool_messages,
        "profile": summary_profile,
        "status": "processing"
    }

def should_continue(state: DataScanState) -> Any:
    """
    判断是否需要继续调用工具
    Args:
        state (DataScanState): 当前代理状态
    Returns:
        Literal["tool_node", END]: 如果需要调用工具则返回 "tool_node"，否则返回 END
    """
    last_message = state["messages"][-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tool_node"
    
    return END

agent_builder = StateGraph(DataScanState)
agent_builder.add_node("llm_node", llm_node)
agent_builder.add_node("tool_node", tool_node)
agent_builder.add_edge(START, "llm_node")
agent_builder.add_conditional_edges("llm_node", should_continue, ["tool_node", END])
agent_builder.add_edge("tool_node", "llm_node")

data_scan_agent = agent_builder.compile()