"""
模型需求输入数据扫描智能体工具集
根据 MDL 文件分析模型的输入数据需求
"""

import json
import os
from typing import Annotated, Dict, Any, List, TypedDict
from pathlib import Path
from langchain.tools import tool
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.messages import AnyMessage
import operator

# 初始化模型
load_dotenv()
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

model = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    temperature=0,
    max_retries=2,
    google_api_key=GOOGLE_API_KEY,
)

class ModelRequirementState(TypedDict):
    """
    模型需求扫描状态体
    """
    # LLM 对话
    messages: Annotated[List[AnyMessage], operator.add]

    # 输入
    mdl_data: Dict[str, Any]  # MDL 文件内容

    # 分析结果
    mdl_requirements: Annotated[Dict[str, Any], operator.or_]  # 从 MDL 提取的需求

    # 状态
    status: str


# ============================================================================
# 工具: MDL 解析工具
# ============================================================================

@tool
def tool_parse_mdl(mdl_data: str) -> Dict[str, Any]:
    """
    解析 MDL 文件，提取模型的输入数据需求
    
    Args:
        mdl_data: MDL 文件的 JSON 字符串或对象
    
    Returns:
        {
            "status": "success" | "error",
            "model_name": "模型名称",
            "model_description": "模型描述",
            "input_requirements": [
                {
                    "name": "输入参数名",
                    "type": "输入类型",
                    "format": "数据格式",
                    "required": 是否必需,
                    "description": "描述"
                }
            ],
            "output_specifications": [...],
            "parameters": [...]
        }
    """
    try:
        # 解析 MDL 数据
        if isinstance(mdl_data, str):
            mdl_obj = json.loads(mdl_data)
        else:
            mdl_obj = mdl_data

        # 提取基本信息
        model_info = {
            "status": "success",
            "model_name": mdl_obj.get("modelName", "Unknown"),
            "model_description": mdl_obj.get("modelDescription", ""),
            "input_requirements": [],
            "output_specifications": [],
            "parameters": []
        }

        # 提取输入需求
        if "inputs" in mdl_obj:
            for input_item in mdl_obj["inputs"]:
                model_info["input_requirements"].append({
                    "name": input_item.get("name"),
                    "type": input_item.get("type"),
                    "format": input_item.get("format"),
                    "required": input_item.get("required", True),
                    "description": input_item.get("description", ""),
                    "spatial_requirement": input_item.get("spatial_requirement"),
                    "temporal_requirement": input_item.get("temporal_requirement")
                })

        # 提取输出规范
        if "outputs" in mdl_obj:
            for output_item in mdl_obj["outputs"]:
                model_info["output_specifications"].append({
                    "name": output_item.get("name"),
                    "type": output_item.get("type"),
                    "format": output_item.get("format"),
                    "description": output_item.get("description", "")
                })

        # 提取参数
        if "parameters" in mdl_obj:
            for param in mdl_obj["parameters"]:
                model_info["parameters"].append({
                    "name": param.get("name"),
                    "type": param.get("type"),
                    "default_value": param.get("default_value"),
                    "range": param.get("range"),
                    "description": param.get("description", "")
                })

        return model_info

    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }


# ============================================================================
# 工具注册
# ============================================================================

tools = [
    tool_parse_mdl
]

TOOLS_BY_NAME = {tool.name: tool for tool in tools}
model_with_tools = model.bind_tools(tools)
