"""
Supervisor: High-level orchestrator for multi-agent workflow.
Routes tasks to appropriate agents and coordinates their execution.

Supported agents:
- DataScanAgent: Analyzes and classifies geospatial data files
- ModelRecommendationAgent: Recommends suitable models based on data characteristics
- (Future) DataVisualizationAgent, ParameterOptimizationAgent, etc.
"""

from typing import TypedDict, Literal, Annotated, Dict, Any, List
from langchain.messages import HumanMessage, SystemMessage, AIMessage, AnyMessage
from langgraph.graph import StateGraph, START, END
from langchain_google_genai import ChatGoogleGenerativeAI
import operator
import os
from dotenv import load_dotenv

load_dotenv()
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")


class SupervisorState(TypedDict):
    """State for supervisor coordination"""
    messages: Annotated[List[AnyMessage], operator.add]
    
    # Task information
    task_type: Literal["data_scan", "model_recommend", "data_visualize", "composite"]
    user_request: str
    
    # Agent routing
    next_agent: Literal["data_scan", "model_recommend", "end"]
    
    # Intermediate results
    data_scan_result: Dict[str, Any]
    model_recommendation_result: Dict[str, Any]
    
    # Final output
    final_result: Dict[str, Any]


def router_node(state: SupervisorState) -> Dict[str, Any]:
    """
    路由器：解析用户请求，确定应该调用哪个智能体
    """
    system_prompt = """你是任务路由专家。根据用户请求判断应该调用哪个智能体。

可用智能体：
- data_scan: 分析和分类上传的数据文件
- model_recommend: 根据数据特征推荐适配的模型

输出JSON：
{
  "agent": "data_scan|model_recommend|both",
  "reasoning": "路由决策理由"
}"""

    user_context = f"""
用户请求: {state['user_request']}
任务类型: {state['task_type']}
"""
    
    model = ChatGoogleGenerativeAI(
        model="gemini-2.0-flash-exp",
        temperature=0.1,
        google_api_key=GOOGLE_API_KEY,
    )
    
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_context)
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
        agent = decision.get("agent", "data_scan")
    except Exception:
        agent = "data_scan"
    
    next_agent = agent.split("|")[0] if "|" in agent else agent
    
    return {
        "messages": [AIMessage(content=f"路由器: 调用{next_agent}智能体")],
        "next_agent": next_agent
    }


def should_route(state: SupervisorState) -> str:
    """
    条件路由：根据next_agent决定流向
    """
    agent = state.get("next_agent", "data_scan")
    if agent == "data_scan":
        return "data_scan_wrapper"
    elif agent == "model_recommend":
        return "model_recommend_wrapper"
    else:
        return "end"


def build_supervisor_graph():
    """Build supervisor coordination workflow"""
    workflow = StateGraph(SupervisorState)
    
    # Add nodes
    workflow.add_node("router", router_node)
    
    # Placeholder nodes for actual agent execution
    # These will be implemented in main.py using subgraph composition
    workflow.add_node("data_scan_wrapper", lambda state: {
        "messages": [AIMessage(content="[DataScanAgent执行中]")],
        "data_scan_result": state.get("data_scan_result", {})
    })
    
    workflow.add_node("model_recommend_wrapper", lambda state: {
        "messages": [AIMessage(content="[ModelRecommendAgent执行中]")],
        "model_recommendation_result": state.get("model_recommendation_result", {})
    })
    
    # Define edges
    workflow.add_edge(START, "router")
    workflow.add_conditional_edges(
        "router",
        should_route,
        ["data_scan_wrapper", "model_recommend_wrapper", "end"]
    )
    workflow.add_edge("data_scan_wrapper", "end")
    workflow.add_edge("model_recommend_wrapper", "end")
    
    return workflow.compile()


# Create the compiled supervisor
supervisor = build_supervisor_graph()
