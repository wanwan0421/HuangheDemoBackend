import os
import json
from typing import TypedDict, Dict, Any, List, Optional, Annotated
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.messages import HumanMessage, SystemMessage, AnyMessage
from langgraph.graph import StateGraph, START, END
from dotenv import load_dotenv
import operator
from google import genai

# 初始化模型
load_dotenv()
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
client = genai.Client(api_key=GOOGLE_API_KEY )

class DataRefineState(TypedDict):
    """
    数据分析LLM辅助请求体：包含NestJS的初步分析结果
    """
    # 输入
    file_path: str
    profile: Dict[str, Any]
    # LLM 对话
    messages: Annotated[List[AnyMessage], operator.add]

    # 输出
    final_profile: Dict[str, Any]
    corrections: List[str]
    completions: List[str]


def refine_node(state: DataRefineState) -> Dict[str, Any]:
    """
    检验、修正和补全节点：使用LLM分析初步结果
    """
    system_prompt = """你是地理空间数据分析专家。你的任务是：
1. **检验**：检查初步分析是否合理
2. **修正**：如果发现错误，修正数据形式和元数据
3. **补全**：补全缺失的关键信息

数据形式分类：
- Raster: 栅格/影像数据（网格结构，通常有lat/lon维度）
- Vector: 矢量地理数据（点、线、面几何，包含坐标）
- Table: 纯表格数据（无地理参考）
- Timeseries: 时间序列数据（强调时间维度）
- Parameter: 配置参数文件

请直接返回符合 DataSemanticProfile 结构的 JSON 对象。"""

    # 构建上下文：只给 LLM 看它需要的“证据”
    context = {
        "file_path": state['file_path'],
        "current_profile": state['profile']
    }

    user_input = f"""请对以下数据画像进行【语义精炼】和【逻辑校验】：
{json.dumps(context, ensure_ascii=False, indent=2)}

注意：请保留原有物理参数，仅修正 form 并补全 domain, semantic 以及相关的 profile 细节。"""
    
    # 调用LLM
    model = ChatGoogleGenerativeAI(
        model="gemini-2.0-flash-exp",
        temperature=0.1,
        google_api_key=GOOGLE_API_KEY,
    )
    
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_input)
    ]
    
    response = model.invoke(messages)
    
    # 解析LLM响应
    try:
        content = response.content
        # 清洗 Markdown 代码块
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        
        refined_data = json.loads(content)

        # 提取 LLM 的变更点作为记录
        corrections = []
        if refined_data.get('form') != state['profile'].get('form'):
            corrections.append(f"Form 从 {state['profile'].get('form')} 修正为 {refined_data.get('form')}")
        
        return {
            "messages": [response],
            "profile": refined_data, # 更新后的 profile
            "corrections": corrections,
            "completions": ["已补全 domain 和 semantic 摘要"]
        }

    except Exception as e:
        return {
            "messages": [response],
            "error": f"解析失败: {str(e)}"
        }

"""构建数据修正工作流图"""
agent_builder = StateGraph(DataRefineState)
agent_builder.add_node("refine", refine_node)
agent_builder.add_edge(START, "refine")
agent_builder.add_edge("refine", END)
    
data_scan_agent = agent_builder.compile()