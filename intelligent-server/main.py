from fastapi import FastAPI, WebSocket, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from agents.nodes import agent
from langchain.messages import HumanMessage
from typing import Any, Dict, List, Optional
import uuid
import json
import asyncio

app = FastAPI()
# 允许任何来源的跨域请求
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

def serialize_message(msg: Any) -> Dict[str, Any]:
    """
    把langchain/message-like对象序列化为前端可使用的简单的dict
    Args:
        msg (Any): langchain消息对象
    Returns:
        Dict[str, Any]: 序列化后的消息字典
    """

    out: Dict[str, Any] = {}
    out["content"] = getattr(msg, "content", None)

    # 推断角色
    cls_name = msg.__class__.__name__ if hasattr(msg, "__class__") else None
    if cls_name:
        if "Human" in cls_name or "User" in cls_name:
            out["role"] = "user"
        elif "System" in cls_name:
            out["role"] = "system"
        elif "Tool" in cls_name:
            out["role"] = "tool"
        else:
            out["role"] = "assistant"
    
    # tool_calls如果存在
    if hasattr(msg, "tool_calls"):
        try:
            out["tool_calls"] = list(getattr(msg, "tool_calls") or [])
        except Exception:
            out["tool_calls"] = getattr(msg, "tool_calls")
    
    # tool_call_id（ToolMessage）
    if hasattr(msg, "tool_call_id"):
        out["tool_call_id"] = getattr(msg, "tool_call_id")
    return out

def serialize_messages(msgs: List[Any]) -> List[Dict[str, Any]]:
    return [serialize_message(m) for m in msgs]

def map_agent_event(event: Dict[str, Any], root_started_ref, root_finished_ref) -> Optional[Dict[str, Any]]:
    """
    将LangGraph原始事件映射为“可解释事件”
    """
    etype = event.get("event")
    parent_run_id = event.get("parent_run_id")
    is_root = parent_run_id is None

    # Agent开始分析问题，只在整个Graph的根节点开始时触发一次
    if etype == "on_chain_start" and is_root and not root_started_ref:
        root_started_ref = True
        return {
            "type": "status",
            "message": "Agent正在分析问题"
        }

    # LLM token流
    if etype == "on_chat_model_stream":
        chunk = event.get("data", {}).get("chunk")
        content = getattr(chunk, "content", "")
        if content:
            return {
                "type": "token",
                "message": content
            }

    # Tool开始调用工具
    if etype == "on_tool_start":
        print("Tool开始调用工具")
        name = event.get('name')
        friendly_names = {
            "search_relevant_indices": "正在检索地理指标库...",
            "search_relevant_models": "正在匹配最优地理模型...",
            "get_model_details": "正在读取模型工作流详情..."
        }
        msg = friendly_names.get(name, f"正在执行工具: {name}")
        return {
            "type": "tool",
            "message": f"{msg}",
            "data": event.get("data")
        }

    # Tool结束调用工具
    if etype == "on_tool_end":
        name = event.get('name')
        data = event.get("data", {})
        output = data.get("output", {})

        # 指标库返回结果
        if name == "search_relevant_indices":
            return {
                "type": "search_index",
                "message": "工具已返回相关地理指标",
                "data": output
            }
        # 模型库返回结果
        if name == "search_relevant_models":
            return {
                "type": "search_model",
                "message": "工具已返回相关地理模型",
                "data": output
            }
        # 模型详情返回结果
        if name == "get_model_details":
            return {
                "type": "model_details",
                "message": "工具已返回模型工作流详情",
                "data": output
            }

    # Agent完成分析
    if etype == "on_chain_end" and is_root and not root_finished_ref:
        root_finished_ref = True
        return {
            "type": "final",
            "message": "Agent已得出结论"
        }

    return None

@app.get("/api/agent/stream")
async def stream_agent(query: str):
    print("Received stream query:", query)
    if not query:
        raise HTTPException(status_code=400, detail="query is required")

    async def event_generator():
        init_input = {
            "messages": [HumanMessage(content=query)]
        }

        root_started = {"value": False}
        root_finished = {"value": False}

        try:
            async for event in agent.astream_events(
                init_input,
                version="v1"
            ):
                print("Agent event:", event)
                mapped = map_agent_event(
                    event,
                    root_started_ref = root_started,
                    root_finished_ref = root_finished
                )
                if mapped:
                    yield f"data: {json.dumps(mapped, ensure_ascii=False)}\n\n"
                await asyncio.sleep(0)
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream"
    )

@app.post("/api/agent/run")
async def run_agent(body: Dict[str, Any]):
    query = body.get("query", "")
    if not query:
        raise HTTPException(status_code=400, detail="query is required")

    session_id = body.get("sessionId") or str(uuid.uuid4())
    
    # 构造初始状态
    init_input = {"messages": [HumanMessage(content=query)]}

    try:
        # 直接运行 Graph，它会自动处理 llm_node -> tool_node -> should_continue 的循环
        # 如果你的 llm_node 定义了 llm_calls，它也会在结果中返回
        final_state = await agent.ainvoke(init_input)
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Graph 运行失败: {str(e)}")

    return {
        "status": "ok", 
        "sessionId": session_id, 
        "messages": serialize_messages(final_state.get("messages", [])), 
        "llm_calls": final_state.get("llm_calls", 0)
    }