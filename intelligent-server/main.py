from fastapi import FastAPI, WebSocket, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from agents.nodes import agent
from langchain.messages import HumanMessage, AIMessageChunk
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
    print("event:", event)
    etype = event.get("event")
    parent_run_id = event.get("parent_run_id")
    is_root = parent_run_id is None

    # Agent开始分析问题，只在整个Graph的根节点开始时触发一次
    if etype == "on_chain_start" and is_root and not root_started_ref["value"]:
        root_started_ref["value"] = True
        return {
            "type": "status",
            "message": "Agent正在分析问题"
        }

    # LLM token流
    if etype == "on_chat_model_stream":
        chunk = event.get("data", {}).get("chunk")
        content = getattr(chunk, "content", "")

        if isinstance(content, list):
            texts = []
            for c in content:
                if isinstance(c, dict) and 'text' in c:
                    texts.append(c['text'])
                elif isinstance(c, str):
                    texts.append(c)
            content = "".join(texts)
            print("content:", content)

        if content:
            return {
                "type": "token",
                "message": content
            }

    # Tool开始调用工具
    if etype == "on_tool_start":
        print("Tool开始调用工具")
        name = event.get('name')
        # 开始检索指标库
        if name == "search_relevant_indices":
            return {
                "type": "search_index",
                "message": "正在检索地理指标库...",
                "data": event.get("data")
            }
        # 开始检索模型库
        if name == "search_relevant_models":
            return {
                "type": "search_model",
                "message": "正在检索地理模型库...",
                "data": event.get("data")
            }
        # 开始获取模型详情
        if name == "get_model_details":
            return {
                "type": "model_details",
                "message": "正在读取模型工作流详情...",
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
                "type": "search_index_end",
                "message": "工具已返回相关地理指标",
                "data": output
            }
        # 模型库返回结果
        if name == "search_relevant_models":
            return {
                "type": "search_model_end",
                "message": "工具已返回相关地理模型",
                "data": output
            }
        # 模型详情返回结果
        if name == "get_model_details":
            return {
                "type": "model_details_end",
                "message": "工具已返回模型工作流详情",
                "data": output
            }

    # Agent完成分析
    if etype == "on_chain_end" and is_root and not root_finished_ref["value"]:
        root_finished_ref["value"] = True
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

        try:
            def extract_text(content):
                if isinstance(content, str):
                    return content
                elif isinstance(content, dict) and "text" in content:
                    return content["text"]
                elif isinstance(content, list):
                    return "".join(extract_text(c) for c in content)
                else:
                    return ""

            async for mode, chunk in agent.astream(
                init_input,
                stream_mode=["messages", "updates", "custom"]
            ):
                if mode == "messages":
                    if isinstance(chunk, tuple):
                        message_chunk = chunk[0]
                    else:
                        message_chunk = chunk
                    
                    if isinstance(message_chunk, AIMessageChunk):
                        content = message_chunk.content
                        content = extract_text(content)

                        if content and content.strip(): 
                            print("content:", content) # 调试用
                            # 发送命名事件 + data
                            yield f"data: {json.dumps({'type': 'token', 'message': content}, ensure_ascii=False)}\n\n"

                elif mode == "updates":
                    # 一般是节点名+小更新内容
                    if isinstance(chunk, dict):
                        for node_name, node_output in chunk.items():
                            if node_name == "llm_node":
                                # 获取messages列表
                                llm_messages = node_output.get("messages", [])

                                # 处理LLM调用工具
                                last_msg = llm_messages[-1] if llm_messages else None
                                tool_calls = getattr(last_msg, "tool_calls", []) or []

                                if tool_calls:
                                    for tool_call in tool_calls:
                                        event_name = tool_call.get('name') if isinstance(tool_call, dict) else str(tool_call)
                                        yield f"data: {json.dumps({'type': event_name, 'message': event_name}, ensure_ascii=False)}\n\n"
                                continue

                            if node_name == "tool_node":
                                # node_output is like {"messages": [ToolMessage,...]}
                                tool_msgs = node_output.get("messages", [])

                                for tmsg in tool_msgs:
                                    try:
                                        tool_result = json.loads(tmsg.content)
                                    except Exception:
                                        tool_result = tmsg.content
                                    # get tool_name from tmsg if exists (fallback to id if not)

                                    tool_name = getattr(tmsg, "tool_name", None)
                                    event_type = {
                                        "search_relevant_indices":"search_index_end",
                                        "search_relevant_models":"search_model_end",
                                        "get_model_details":"model_details_end"
                                    }.get(tool_name, "tool_complete")

                                    yield f"data: {json.dumps({"type": event_type, "tool": tool_name, "data": tool_result}, ensure_ascii=False)}\n\n"

                                continue

                            # fallback
                            yield f"data: {json.dumps({"type": "update", "node": node_name, "data": node_output}, ensure_ascii=False)}\n\n"

                elif mode == "custom":
                    # 工具内部通过 StreamWriter 发出的数据
                    yield f"data: {json.dumps({'type': 'custom', 'data': chunk}, ensure_ascii=False)}\n\n"

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