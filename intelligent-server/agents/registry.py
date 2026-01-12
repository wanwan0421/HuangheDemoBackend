"""
Agent Registry and Manifest
Maintains information about all available agents in the system.
"""

AGENTS = {
    "data_scan": {
        "name": "DataScanAgent",
        "description": "分析和分类地理空间数据文件，提取元数据",
        "endpoint": "POST /api/agents/data-scan",
        "capabilities": [
            "file_format_detection",
            "data_type_classification",
            "metadata_extraction",
            "llm_refinement"
        ],
        "input": {
            "file_path": "str",
            "extension": "str",
            "headers": "Optional[List[str]]",
            "sample_rows": "Optional[List[Dict]]",
            "coords_detected": "Optional[bool]",
            "time_detected": "Optional[bool]",
            "dimensions": "Optional[Dict]",
            "file_size": "Optional[int]"
        },
        "output": {
            "form": "str",
            "confidence": "float",
            "details": "Dict",
            "source": "str",
            "node_analysis": "Dict"
        }
    },
    
    "model_recommend": {
        "name": "ModelRecommendationAgent",
        "description": "根据数据特征推荐适配的地理模型",
        "endpoint": "POST /api/agent/stream",  # 现有端点
        "capabilities": [
            "index_search",
            "model_ranking",
            "workflow_extraction"
        ],
        "input": {
            "query": "str"
        },
        "output": {
            "messages": "List[Dict]",
            "models": "List[Dict]"
        }
    },
    
    "data_visualize": {
        "name": "DataVisualizationAgent",
        "description": "生成数据的可视化方案和代码",
        "status": "planned",
        "capabilities": [
            "visualization_planning",
            "code_generation"
        ]
    },
    
    "parameter_optimize": {
        "name": "ParameterOptimizationAgent",
        "description": "根据数据特征优化模型参数",
        "status": "planned",
        "capabilities": [
            "parameter_analysis",
            "optimization_recommendation"
        ]
    }
}


def get_agent_info(agent_name: str) -> dict:
    """Get information about a specific agent"""
    return AGENTS.get(agent_name, {})


def list_agents() -> dict:
    """List all available agents"""
    return AGENTS


def agent_exists(agent_name: str) -> bool:
    """Check if an agent exists"""
    return agent_name in AGENTS
