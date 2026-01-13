import os
import json
from typing import TypedDict, Dict, Any, List, Optional, Annotated
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.messages import HumanMessage, SystemMessage, AnyMessage
from langgraph.graph import StateGraph, START, END
from dotenv import load_dotenv
import operator
from google import genai
from . import tools

class DataScanState(TypedDict):
    """
    数据分析LLM辅助状态体
    """
    # LLM 对话
    messages: Annotated[List[AnyMessage], operator.add]
    tool_results: Dict[str, Any]

    # 输入
    file_path: str

    # 输出
    profile: Dict[str, Any]
    status: str

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
        1.首先调用`tool_prepare_profile`工具，传入文件路径，准备数据。
        2.根据准备的数据，调用`tool_detect_format`工具，检测数据类型。
        3.根据数据类型的检测结果，调用专项分析工具，包括`tool_analyze_raster`, `tool_analyze_vector`, `tool_analyze_table`, `tool_analyze_timeseries`, `tool_analyze_parameter`，提取元数据。
        4.综合所有工具的结果，生成最终的数据画像，包含数据形式、领域信息、语义摘要等。

        **重要规则**：
        1.必须先调用`tool_prepare_profile`
        2.其中有些难以根据后缀名判断的数据类型，需要调用其他工具来读取数据进行详细判断
        3.所有工具调用完成后，才生成最终profile

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

        第三层：领域语义扩展
        1.domain：领域信息（具体数据在某个学科中意味着什么）
        """

    user_message = f"""请根据以下信息，生成数据画像：
    文件路径: {state['file_path']}"""

    messages = [
        SystemMessage(content=system_message),
        HumanMessage(content=user_message)
    ] + state["messages"]

    response = tools.model_with_tools.invoke(messages)

    return {
        "messages": [response],
        # "profile": json.loads(response.content),
        "status": "success"
    }

def tool_node(state: DataScanState) -> Dict[str, Any]:
    """
    工具调用节点：根据当前状态调用相应工具
    Args:
        state (DataScanState): 当前代理状态，包含消息历史等信息
    Returns:
        Dict[str, Any]: 更新后的状态，包含新消息和工具结果
    """
    last_message = state["messages"][-1]
    tool_calls = getattr(last_message, "tool_calls", []) or []

    tool_messages = []

    for tool_call in tool_calls:
        tool = tools.TOOLS_BY_NAME[tool_call["name"]]
        observation = tool.invoke(tool_call["args"])

        tool_messages.append(tools.ToolMessage(
            content=json.dumps(observation, ensure_ascii=False),
            tool_call_id=tool_call["id"],
            tool_name=tool_call["name"]
        ))

    return {
        "messages": tool_messages
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
    if last_message.tool_calls:
        return "tool_node"
    
    return END

agent_builder = StateGraph(DataScanState)
agent_builder.add_node("llm_node", llm_node)
agent_builder.add_node("tool_node", tool_node)
agent_builder.add_edge(START, "llm_node")
agent_builder.add_conditional_edges("llm_node", should_continue, ["tool_node"], [END])
agent_builder.add_edge("tool_node", "llm_node")

agent = agent_builder.compile()