"""
Multi-agent data refinement workflow using LangGraph.
Specialized agents collaborate to analyze and classify geospatial data.
"""

from typing import TypedDict, List, Dict, Any, Literal, Annotated
from langchain.messages import HumanMessage, SystemMessage, AIMessage, AnyMessage
from langgraph.graph import StateGraph, START, END
from langchain_google_genai import ChatGoogleGenerativeAI
import operator
import os
from dotenv import load_dotenv

load_dotenv()
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")


class DataAnalysisState(TypedDict):
    """State for multi-agent data refinement workflow"""
    messages: Annotated[List[AnyMessage], operator.add]
    
    # Input context
    file_path: str
    extension: str
    current_form: str
    current_confidence: float
    headers: List[str]
    sample_rows: List[Dict[str, Any]]
    coords_detected: bool
    time_detected: bool
    dimensions: Dict[str, Any]
    file_size: int
    
    # Agent analysis results
    type_expert_analysis: Dict[str, Any]
    geo_expert_analysis: Dict[str, Any]
    timeseries_expert_analysis: Dict[str, Any]
    coordinator_decision: Dict[str, Any]
    
    # Final output
    final_form: str
    final_confidence: float
    final_details: Dict[str, Any]


# Initialize specialized LLMs
def create_specialized_model(temperature: float = 0.3) -> ChatGoogleGenerativeAI:
    """Create a Gemini model instance"""
    return ChatGoogleGenerativeAI(
        model="gemini-2.0-flash-exp",
        temperature=temperature,
        google_api_key=GOOGLE_API_KEY,
    )


def data_type_expert_node(state: DataAnalysisState) -> Dict[str, Any]:
    """
    数据类型识别专家：基于扩展名、文件结构判断数据类型
    """
    system_prompt = """你是数据类型识别专家。你的任务是根据文件信息判断数据类型。

数据类型：
- Raster: 栅格数据（GeoTIFF、影像、格网等）
- Vector: 矢量数据（Shapefile、GeoJSON、带坐标表格等）
- Table: 纯表格数据（无地理信息）
- Timeseries: 时间序列数据（NetCDF时序、时序文本等）
- Parameter: 参数配置文件（XML等）

请只输出JSON：
{
  "form": "数据类型",
  "confidence": 0.0-1.0,
  "reasoning": "判断依据"
}"""

    context_prompt = f"""
文件: {state['file_path']}
扩展名: {state['extension']}
当前推断: {state['current_form']} ({state['current_confidence']:.2f})
表头: {state.get('headers', [])[:10] if state.get('headers') else '无'}
检测坐标: {state.get('coords_detected', False)}
检测时间: {state.get('time_detected', False)}
文件大小: {state.get('file_size', 0) / 1024 / 1024:.2f} MB
"""
    
    model = create_specialized_model(temperature=0.2)
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=context_prompt)
    ]
    
    response = model.invoke(messages)
    
    import json
    try:
        # Extract JSON from markdown code blocks if present
        content = response.content
        if "```json" in content:
            start = content.find("```json") + 7
            end = content.find("```", start)
            content = content[start:end].strip()
        elif "```" in content:
            start = content.find("```") + 3
            end = content.find("```", start)
            content = content[start:end].strip()
        
        analysis = json.loads(content)
    except Exception as e:
        analysis = {
            "form": state['current_form'],
            "confidence": state['current_confidence'],
            "reasoning": f"解析失败: {str(e)}"
        }
    
    return {
        "messages": [AIMessage(content=f"数据类型专家分析: {analysis['form']} (置信度: {analysis['confidence']})")],
        "type_expert_analysis": analysis
    }


def geo_expert_node(state: DataAnalysisState) -> Dict[str, Any]:
    """
    地理空间分析专家：判断坐标系统、几何类型、空间范围
    """
    system_prompt = """你是地理空间数据专家。分析数据的地理空间特征。

请输出JSON：
{
  "has_spatial_info": true/false,
  "geometry_type": "Point|LineString|Polygon|Raster|null",
  "crs_guess": "EPSG:4326|EPSG:3857|unknown",
  "spatial_extent": {"minx": ..., "miny": ..., "maxx": ..., "maxy": ...} or null,
  "reasoning": "判断依据"
}"""

    context_prompt = f"""
文件: {state['file_path']}
扩展名: {state['extension']}
表头: {state.get('headers', [])[:15] if state.get('headers') else '无'}
样本行: {state.get('sample_rows', [])[:3] if state.get('sample_rows') else '无'}
检测坐标: {state.get('coords_detected', False)}
"""
    
    model = create_specialized_model(temperature=0.2)
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=context_prompt)
    ]
    
    response = model.invoke(messages)
    
    import json
    try:
        content = response.content
        if "```json" in content:
            start = content.find("```json") + 7
            end = content.find("```", start)
            content = content[start:end].strip()
        elif "```" in content:
            start = content.find("```") + 3
            end = content.find("```", start)
            content = content[start:end].strip()
        
        analysis = json.loads(content)
    except Exception:
        analysis = {
            "has_spatial_info": state.get('coords_detected', False),
            "geometry_type": None,
            "crs_guess": "unknown",
            "spatial_extent": None,
            "reasoning": "解析失败"
        }
    
    return {
        "messages": [AIMessage(content=f"地理专家分析: 空间信息={analysis['has_spatial_info']}")],
        "geo_expert_analysis": analysis
    }


def timeseries_expert_node(state: DataAnalysisState) -> Dict[str, Any]:
    """
    时序数据分析专家：识别时间列、频率、时间范围
    """
    system_prompt = """你是时间序列数据专家。分析数据的时间特征。

请输出JSON：
{
  "has_time_info": true/false,
  "time_column": "列名 or null",
  "frequency": "daily|monthly|yearly|irregular|unknown",
  "time_range": {"start": "...", "end": "..."} or null,
  "reasoning": "判断依据"
}"""

    context_prompt = f"""
文件: {state['file_path']}
扩展名: {state['extension']}
表头: {state.get('headers', [])[:15] if state.get('headers') else '无'}
样本行: {state.get('sample_rows', [])[:3] if state.get('sample_rows') else '无'}
检测时间: {state.get('time_detected', False)}
维度信息: {state.get('dimensions', {})}
"""
    
    model = create_specialized_model(temperature=0.2)
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=context_prompt)
    ]
    
    response = model.invoke(messages)
    
    import json
    try:
        content = response.content
        if "```json" in content:
            start = content.find("```json") + 7
            end = content.find("```", start)
            content = content[start:end].strip()
        elif "```" in content:
            start = content.find("```") + 3
            end = content.find("```", start)
            content = content[start:end].strip()
        
        analysis = json.loads(content)
    except Exception:
        analysis = {
            "has_time_info": state.get('time_detected', False),
            "time_column": None,
            "frequency": "unknown",
            "time_range": None,
            "reasoning": "解析失败"
        }
    
    return {
        "messages": [AIMessage(content=f"时序专家分析: 时间信息={analysis['has_time_info']}")],
        "timeseries_expert_analysis": analysis
    }


def coordinator_node(state: DataAnalysisState) -> Dict[str, Any]:
    """
    协调者：综合三位专家意见，做出最终决策
    """
    system_prompt = """你是数据分析协调专家。综合三位专家的分析，做出最终判断。

数据类型：
- Raster: 栅格数据
- Vector: 矢量数据
- Table: 纯表格
- Timeseries: 时间序列
- Parameter: 参数文件

请输出JSON：
{
  "form": "最终数据类型",
  "confidence": 0.0-1.0,
  "details": {
    "geometry_type": "...",
    "crs": "...",
    "time_column": "...",
    "spatial_extent": {...},
    "notes": "..."
  },
  "reasoning": "综合判断依据"
}"""

    experts_summary = f"""
## 数据类型专家意见
{state.get('type_expert_analysis', {})}

## 地理空间专家意见
{state.get('geo_expert_analysis', {})}

## 时序数据专家意见
{state.get('timeseries_expert_analysis', {})}

## 原始推断
类型: {state['current_form']}
置信度: {state['current_confidence']}
"""
    
    model = create_specialized_model(temperature=0.1)
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=experts_summary)
    ]
    
    response = model.invoke(messages)
    
    import json
    try:
        content = response.content
        if "```json" in content:
            start = content.find("```json") + 7
            end = content.find("```", start)
            content = content[start:end].strip()
        elif "```" in content:
            start = content.find("```") + 3
            end = content.find("```", start)
            content = content[start:end].strip()
        
        decision = json.loads(content)
    except Exception:
        decision = {
            "form": state['current_form'],
            "confidence": state['current_confidence'],
            "details": {},
            "reasoning": "解析失败，使用原始推断"
        }
    
    return {
        "messages": [AIMessage(content=f"协调者决策: {decision['form']} (置信度: {decision['confidence']})")],
        "coordinator_decision": decision,
        "final_form": decision['form'],
        "final_confidence": decision['confidence'],
        "final_details": decision.get('details', {})
    }


# Build the multi-agent workflow
def build_data_refine_graph():
    """Build multi-agent data refinement graph"""
    workflow = StateGraph(DataAnalysisState)
    
    # Add nodes
    workflow.add_node("type_expert", data_type_expert_node)
    workflow.add_node("geo_expert", geo_expert_node)
    workflow.add_node("timeseries_expert", timeseries_expert_node)
    workflow.add_node("coordinator", coordinator_node)
    
    # Define edges - parallel expert analysis, then coordinator
    workflow.add_edge(START, "type_expert")
    workflow.add_edge(START, "geo_expert")
    workflow.add_edge(START, "timeseries_expert")
    
    workflow.add_edge("type_expert", "coordinator")
    workflow.add_edge("geo_expert", "coordinator")
    workflow.add_edge("timeseries_expert", "coordinator")
    
    workflow.add_edge("coordinator", END)
    
    return workflow.compile()


# Create the compiled graph
data_refine_agent = build_data_refine_graph()
