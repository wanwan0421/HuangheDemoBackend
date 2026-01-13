from fastapi import FastAPI, WebSocket, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from agents.model_recommend.graph import agent
from agents.data_scan.graph import DataScanState, data_scan_agent
from agents.supervisor import supervisor, SupervisorState
from agents.registry import list_agents, get_agent_info
from langchain.messages import HumanMessage, AIMessageChunk, AnyMessage
from typing import Any, Dict, List, Optional,TypedDict, Annotated
import uuid
import json
import asyncio
from pydantic import BaseModel
import operator
from pathlib import Path

app = FastAPI()
# 允许任何来源的跨域请求
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ============= 模型推荐智能体路由 =============

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
async def stream_agent(query: str, sessionId: Optional[str] = None):
    print("Received stream query:", query, "sessionId:", sessionId)
    if not query:
        raise HTTPException(status_code=400, detail="query is required")

    # 使用 LangGraph checkpointer 的 thread_id
    thread_id = sessionId or str(uuid.uuid4())

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
                stream_mode=["messages", "updates", "custom"],
                config={
                    "configurable": {
                        "thread_id": thread_id
                    }
                }
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

# ============= 数据分析辅助路由 =============

class DataScanRequest(BaseModel):
    """数据扫描请求体"""
    file_path: str
    session_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class DataScanStreamRequest(BaseModel):
    """流式数据扫描请求体"""
    file_path: str
    session_id: Optional[str] = None
    include_samples: Optional[bool] = True  # 是否包含样本数据


@app.post("/api/agents/data-scan")
async def data_scan_endpoint(request: DataScanRequest):
    """
    数据扫描端点：同步调用 LangGraph Agent 分析数据
    用于 NestJS 后端直接调用，一次性获取完整结果
    
    Args:
        request: 包含文件路径和会话ID
        
    Returns:
        {
            "status": "ok" | "error",
            "profile": {...完整的 DataSemanticProfile...},
            "agent_logs": ["工作流日志1", "工作流日志2"],
            "session_id": "会话ID"
        }
    """
    try:
        session_id = request.session_id or str(uuid.uuid4())
        
        # 初始化 LangGraph 状态
        initial_state: DataScanState = {
            "messages": [],
            "file_path": request.file_path,
            "tool_results": {},
            "profile": {},
            "status": "processing"
        }
        
        # 同步调用 LangGraph Agent
        final_state = await asyncio.to_thread(
            lambda: data_scan_agent.invoke(initial_state)
        )
        
        profile = final_state.get("profile", {})
        
        # 添加基础字段
        if "id" not in profile:
            profile["id"] = f"data_{Path(request.file_path).stem}_{session_id[:8]}"
        
        if "format" not in profile:
            profile["format"] = Path(request.file_path).suffix.lower()
        
        return {
            "status": "ok",
            "profile": profile,
            "agent_logs": ["Agent 分析完成"],
            "session_id": session_id
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Data scan failed: {str(e)}")


@app.get("/api/agents/data-scan/stream")
async def data_scan_stream_endpoint(file_path: str, session_id: Optional[str] = None):
    """
    流式数据扫描端点：实时返回分析过程
    用于React前端实时展示分析进度
    
    特点：
    1. 服务器发送事件（SSE）流式响应
    2. 实时显示 Agent 工作流程
    3. 支持进度跟踪和日志展示
    
    Args:
        file_path: 待分析的文件路径
        session_id: 会话ID（可选）
        
    Returns:
        SSE 流，包含以下事件类型：
        - status: Agent 状态更新
        - tool_call: 工具调用开始
        - tool_result: 工具调用完成
        - progress: 进度更新
        - error: 错误信息
        - final: 最终结果
    """
    session_id = session_id or str(uuid.uuid4())
    
    async def event_generator():
        try:
            # 发送初始化事件
            yield f"data: {json.dumps({'type': 'status', 'message': '初始化数据扫描', 'session_id': session_id}, ensure_ascii=False)}\n\n"
            
            # 初始化 LangGraph 状态
            initial_state: DataScanState = {
                "messages": [],
                "file_path": file_path,
                "tool_results": {},
                "profile": {},
                "status": "processing"
            }
            
            # 流式调用 LangGraph Agent
            current_tool = None
            
            async for event in data_scan_agent.astream(initial_state):
                # 处理不同类型的事件
                if isinstance(event, dict):
                    for node_name, node_output in event.items():
                        
                        # LLM 节点事件
                        if node_name == "llm_node":
                            messages = node_output.get("messages", [])
                            if messages:
                                last_msg = messages[-1]
                                
                                # 检查是否有工具调用
                                if hasattr(last_msg, 'tool_calls') and last_msg.tool_calls:
                                    for tool_call in last_msg.tool_calls:
                                        current_tool = tool_call.get("name", "unknown")
                                        
                                        yield f"data: {json.dumps({
                                            'type': 'tool_call',
                                            'tool': current_tool,
                                            'message': f'工具开始执行: {current_tool}'
                                        }, ensure_ascii=False)}\n\n"
                                else:
                                    # LLM 生成了最终结果
                                    yield f"data: {json.dumps({
                                        'type': 'status',
                                        'message': 'LLM 生成分析结果'
                                    }, ensure_ascii=False)}\n\n"
                        
                        # 工具执行节点事件
                        elif node_name == "tool_node":
                            tool_results = node_output.get("messages", [])

                            for tmsg in tool_results:
                                try:
                                    tool_result = json.loads(tmsg.content)
                                except Exception:
                                    tool_result = tmsg.content
                                
                                tool_name = getattr(tmsg, "tool_name", "unknown")
                                
                                yield f"data: {json.dumps({
                                    'type': 'tool_result',
                                    'tool': tool_name,
                                    'data': tool_result,
                                    'message': f'工具执行完成: {tool_name}'
                                }, ensure_ascii=False)}\n\n"
                        
                        # 进度更新
                        yield f"data: {json.dumps({
                            'type': 'progress',
                            'node': node_name
                        }, ensure_ascii=False)}\n\n"
                
                await asyncio.sleep(0)
            
        except Exception as e:
            yield f"data: {json.dumps({
                'type': 'error',
                'message': f'分析失败: {str(e)}',
                'session_id': session_id
            }, ensure_ascii=False)}\n\n"
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive"
        }
    )

# ============= 智能体协调者路由（暂时保留框架） =============

class SupervisorRequest(BaseModel):
    """
    智能体协调者请求体格式
    """
    task_type: str  # "data_scan", "model_recommend", "composite"
    user_request: str
    data_context: Optional[Dict[str, Any]] = None


@app.post("/api/agents/supervisor")
async def supervisor_endpoint(request: SupervisorRequest):
    """
    通过智能体协调者路由用户请求到合适的智能体。
    Args:
        request: 智能体协调者请求体
    Returns:
        JSON包含路由决策和相关消息
    """
    try:
        initial_state: SupervisorState = {
            "messages": [],
            "task_type": request.task_type,
            "user_request": request.user_request,
            "next_agent": "data_scan",
            "data_scan_result": {},
            "model_recommendation_result": {},
            "final_result": {}
        }
        
        # Run the supervisor
        final_state = await asyncio.to_thread(
            lambda: supervisor.invoke(initial_state)
        )
        
        return {
            "status": "ok",
            "task_type": request.task_type,
            "routing_decision": final_state.get("next_agent", "data_scan"),
            "messages": [msg.content if hasattr(msg, 'content') else str(msg) for msg in final_state.get("messages", [])]
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Supervisor routing failed: {str(e)}")


# ============= 智能体清单路由 =============

@app.get("/api/agents")
async def list_agents_endpoint():
    """
    列表系统中所有可用的智能体。
    Returns:
        返回JSON，包含智能体清单和基本信息
    """
    return {
        "status": "ok",
        "agents": list_agents(),
        "total": len(list_agents())
    }


@app.get("/api/agents/{agent_name}")
async def get_agent_endpoint(agent_name: str):
    """
    获取特定智能体的详细信息。
    Args:
        agent_name: 智能体名称
    Returns:
        返回JSON，包含智能体详细信息、能力和API规范
    """
    agent_info = get_agent_info(agent_name)
    if not agent_info:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' not found")
    
    return {
        "status": "ok",
        "agent": agent_info
    }