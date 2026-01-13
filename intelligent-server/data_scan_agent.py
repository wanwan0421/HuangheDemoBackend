"""
Data Scan Agent: Specialized agent for analyzing and classifying geospatial data files.
Responsible for:
1. File format detection
2. Data type classification (Raster/Vector/Table/Timeseries/Parameter)
3. Metadata extraction
4. LLM-based refinement for ambiguous cases

This agent operates independently and can be invoked by a supervisor or directly via API.
"""

from typing import TypedDict, List, Dict, Any, Annotated
from langchain.messages import HumanMessage, SystemMessage, AIMessage, AnyMessage
from langgraph.graph import StateGraph, START, END
from langchain_google_genai import ChatGoogleGenerativeAI
import operator
import os
import json
from dotenv import load_dotenv

load_dotenv()
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")


class DataScanState(TypedDict):
    """State for data scan agent"""
    messages: Annotated[List[AnyMessage], operator.add]
    
    # Input
    task: str  # "scan", "refine", etc.
    file_path: str
    extension: str
    
    # Optional input (for refinement)
    current_form: str
    current_confidence: float
    headers: List[str]
    sample_rows: List[Dict[str, Any]]
    coords_detected: bool
    time_detected: bool
    dimensions: Dict[str, Any]
    file_size: int
    
    # Analysis results
    detection_result: Dict[str, Any]
    extraction_result: Dict[str, Any]
    refinement_result: Dict[str, Any]
    
    # Final output
    final_form: str
    final_confidence: float
    final_details: Dict[str, Any]


def format_analyzer_node(state: DataScanState) -> Dict[str, Any]:
    """
    格式分析师：基于扩展名和初步启发式判断文件格式
    """
    system_prompt = """你是文件格式分析专家。根据文件扩展名和基本信息快速判断可能的数据类型。

数据类型：
- Raster: 栅格/影像数据 (.tif, .img, .nc, .hdf等)
- Vector: 矢量/地理数据 (.shp, .geojson, .kml, 带坐标csv等)
- Table: 纯表格数据 (.csv, .xlsx, .xls等)
- Timeseries: 时间序列数据 (.nc, .txt, .dat等)
- Parameter: 配置参数文件 (.xml等)

输出JSON：
{
  "primary_form": "推断的主要类型",
  "alternative_forms": ["备选类型1", "备选类型2"],
  "confidence": 0.0-1.0,
  "reasoning": "判断依据"
}"""

    context_prompt = f"""
文件路径: {state['file_path']}
扩展名: {state['extension']}
{f'表头: {state.get("headers", [])[:10]}' if state.get('headers') else ''}
{f'检测坐标: {state.get("coords_detected", False)}' if 'coords_detected' in state else ''}
{f'检测时间: {state.get("time_detected", False)}' if 'time_detected' in state else ''}
"""
    
    model = ChatGoogleGenerativeAI(
        model="gemini-2.0-flash-exp",
        temperature=0.2,
        google_api_key=GOOGLE_API_KEY,
    )
    
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=context_prompt)
    ]
    
    response = model.invoke(messages)
    
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
        
        result = json.loads(content)
    except Exception as e:
        result = {
            "primary_form": state.get("current_form", "Unknown"),
            "alternative_forms": [],
            "confidence": state.get("current_confidence", 0.5),
            "reasoning": f"解析失败: {str(e)}"
        }
    
    return {
        "messages": [AIMessage(content=f"格式分析师: {result['primary_form']} (置信度: {result['confidence']:.2f})")],
        "detection_result": result
    }


def metadata_extractor_node(state: DataScanState) -> Dict[str, Any]:
    """
    元数据提取师：从样本数据中提取关键信息
    """
    system_prompt = """你是地理空间数据元数据提取专家。从样本数据中提取关键信息。

输出JSON：
{
  "spatial_columns": ["lon/lat/x/y列名"],
  "temporal_columns": ["时间列名"],
  "geometry_type": "Point|LineString|Polygon|Raster|null",
  "estimated_crs": "EPSG:4326|EPSG:3857|unknown",
  "data_quality": "good|fair|poor",
  "notes": "其他信息"
}"""

    sample_text = ""
    if state.get("headers"):
        sample_text += f"表头: {state['headers']}\n"
    if state.get("sample_rows"):
        sample_text += f"样本数据:\n"
        for row in state["sample_rows"][:3]:
            sample_text += f"  {json.dumps(row, ensure_ascii=False)}\n"
    if state.get("dimensions"):
        sample_text += f"维度信息: {state['dimensions']}\n"
    
    model = ChatGoogleGenerativeAI(
        model="gemini-2.0-flash-exp",
        temperature=0.2,
        google_api_key=GOOGLE_API_KEY,
    )
    
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=sample_text or "无样本数据")
    ]
    
    response = model.invoke(messages)
    
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
        
        result = json.loads(content)
    except Exception:
        result = {
            "spatial_columns": [],
            "temporal_columns": [],
            "geometry_type": None,
            "estimated_crs": "unknown",
            "data_quality": "unknown",
            "notes": "元数据提取失败"
        }
    
    return {
        "messages": [AIMessage(content=f"元数据提取师: 识别到{len(result.get('spatial_columns', []))}个空间列")],
        "extraction_result": result
    }


def llm_refiner_node(state: DataScanState) -> Dict[str, Any]:
    """
    LLM修正师：当置信度不足时，使用LLM综合所有分析结果做最终判断
    """
    detection = state.get("detection_result", {})
    extraction = state.get("extraction_result", {})
    
    # 如果置信度已经很高，可以跳过LLM修正
    if detection.get("confidence", 0) >= 0.85:
        return {
            "messages": [AIMessage(content="LLM修正师: 置信度足够，跳过LLM修正")],
            "refinement_result": {
                "form": detection.get("primary_form", state.get("current_form", "Unknown")),
                "confidence": detection.get("confidence", 0.5),
                "details": extraction,
                "source": "rule-based"
            }
        }
    
    system_prompt = """你是数据类型修正专家。综合多个分析结果，做出最终判断。

请输出JSON：
{
  "final_form": "最终数据类型",
  "confidence": 0.0-1.0,
  "details": {
    "geometry_type": "...",
    "crs": "...",
    "spatial_columns": [...],
    "temporal_columns": [...],
    "notes": "..."
  },
  "reasoning": "综合判断依据"
}"""

    synthesis_prompt = f"""
格式分析结果:
{json.dumps(detection, ensure_ascii=False)}

元数据提取结果:
{json.dumps(extraction, ensure_ascii=False)}

请综合判断数据的最终类型。
"""
    
    model = ChatGoogleGenerativeAI(
        model="gemini-2.0-flash-exp",
        temperature=0.1,
        google_api_key=GOOGLE_API_KEY,
    )
    
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=synthesis_prompt)
    ]
    
    response = model.invoke(messages)
    
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
        
        result = json.loads(content)
    except Exception:
        result = {
            "final_form": detection.get("primary_form", "Unknown"),
            "confidence": detection.get("confidence", 0.5),
            "details": extraction,
            "source": "fallback"
        }
    
    return {
        "messages": [AIMessage(content=f"LLM修正师: {result['final_form']} (置信度: {result['confidence']:.2f})")],
        "refinement_result": result
    }


def decision_maker_node(state: DataScanState) -> Dict[str, Any]:
    """
    决策制定者：汇总所有分析，输出最终结果
    """
    refinement = state.get("refinement_result", {})
    
    final_form = refinement.get("final_form", refinement.get("form", state.get("current_form", "Unknown")))
    final_confidence = refinement.get("confidence", state.get("current_confidence", 0.5))
    final_details = refinement.get("details", state.get("extraction_result", {}))
    
    return {
        "messages": [AIMessage(content=f"决策制定者: 最终判断 {final_form} (置信度: {final_confidence:.2f})")],
        "final_form": final_form,
        "final_confidence": final_confidence,
        "final_details": final_details
    }


def build_data_scan_graph():
    """Build data scan agent workflow"""
    workflow = StateGraph(DataScanState)
    
    # Add nodes
    workflow.add_node("format_analyzer", format_analyzer_node)
    workflow.add_node("metadata_extractor", metadata_extractor_node)
    workflow.add_node("llm_refiner", llm_refiner_node)
    workflow.add_node("decision_maker", decision_maker_node)
    
    # Define edges
    workflow.add_edge(START, "format_analyzer")
    workflow.add_edge("format_analyzer", "metadata_extractor")
    workflow.add_edge("metadata_extractor", "llm_refiner")
    workflow.add_edge("llm_refiner", "decision_maker")
    workflow.add_edge("decision_maker", END)
    
    return workflow.compile()


# Create the compiled agent
data_scan_agent = build_data_scan_graph()
