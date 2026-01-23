from fastapi import FastAPI, WebSocket, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from agents.model_recommend.graph import agent, ModelState
from agents.model_requirement.tools import tool_parse_mdl
from agents.data_scan.graph import DataScanState, data_scan_agent
from agents.supervisor import supervisor, SupervisorState
from agents.registry import list_agents, get_agent_info
from langchain.messages import HumanMessage, AIMessageChunk, AnyMessage, ToolMessage
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

def extract_text(content):
    if isinstance(content, str):
        return content
    elif isinstance(content, dict) and "text" in content:
        return content["text"]
    elif isinstance(content, list):
        return "".join(extract_text(c) for c in content)
    else:
        return ""

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
            final_state: ModelState= {
                "messages": [],
                "session_id": thread_id,
                "status": "processing",
                "Task_spec": {}
            }
            final_state_task_spec = {}

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
                    # chunk 结构: (MessageChunk, metadata)
                    if isinstance(chunk, tuple):
                        message_chunk, metadata = chunk
                    else:
                        message_chunk = chunk
                        metadata = {}

                    # 获取当前产生消息的节点名称
                    node_name = metadata.get("langgraph_node", "")

                    # 屏蔽 parse_task_spec 的文本输出
                    # 如果当前是解析节点，不仅不显示 JSON，什么都不发给前端文本流
                    if node_name == "parse_task_spec":
                        continue 

                    # 正常的 LLM 节点 (llm_node) 才发送 Token
                    if isinstance(message_chunk, AIMessageChunk):
                        if message_chunk.tool_call_chunks:
                            continue
                        
                        content = extract_text(message_chunk.content)
                        if content:
                            yield f"data: {json.dumps({'type': 'token', 'message': content}, ensure_ascii=False)}\n\n"

                elif mode == "updates":
                    # 一般是节点名+小更新内容
                    if isinstance(chunk, dict):
                        final_state = merge_state(final_state, chunk)

                        for node_name, node_output in chunk.items():
                            if "parse_task_spec" in chunk:
                                node_output = chunk["parse_task_spec"]
                                
                                # 提取 Task_spec
                                if "Task_spec" in node_output:
                                    specific_spec = node_output["Task_spec"]
                                    
                                    # 立即发送 SSE 事件给前端！
                                    # 前端收到这个 type 后，立刻渲染 TaskSpecCard
                                    yield f"data: {json.dumps({
                                        'type': 'task_spec_generated', 
                                        'data': specific_spec
                                    }, ensure_ascii=False)}\n\n"

                            if node_name == "llm_node":
                                # 获取messages列表
                                messages = node_output.get("messages", [])
                                if messages and len(messages) > 0:
                                    last_msg = messages[-1]    

                                # 处理LLM调用工具
                                if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
                                    for tool_call in last_msg.tool_calls:
                                        current_tool = tool_call.get('name', 'unknown')

                                        yield f"data: {json.dumps({
                                            'type': 'tool_call',
                                            'tool': current_tool,
                                            'message': f'工具开始执行: {current_tool}'
                                        }, ensure_ascii=False)}\n\n"
                                else:
                                    # LLM 生成了最终结果
                                    yield f"data: {json.dumps({
                                        'type': 'status',
                                        'message': 'LLM 生成推荐结果'
                                    }, ensure_ascii=False)}\n\n"

                            elif node_name == "tool_node":
                                # node_output is like {"messages": [ToolMessage,...]}
                                tool_msgs = node_output.get("messages", [])

                                for tmsg in tool_msgs:
                                    try:
                                        tool_result = json.loads(tmsg.content)
                                    except Exception:
                                        tool_result = tmsg.content
                                    
                                    tool_name = getattr(tmsg, "tool_name", None)
                                    yield f"data: {json.dumps({
                                        "type": 'tool_result',
                                        "tool": tool_name,
                                        "data": tool_result
                                    }, ensure_ascii=False)}\n\n"

                        continue

                    await asyncio.sleep(0)

                elif mode == "custom":
                    # 工具内部通过 StreamWriter 发出的数据
                    yield f"data: {json.dumps({
                        'type': 'custom',
                        'data': chunk
                    }, ensure_ascii=False)}\n\n"
            
            yield f"data: {json.dumps({
                'type': 'final',
                'Task_spec': final_state.get('Task_spec', {})
            }, ensure_ascii=False)}\n\n"
                
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream"
    )

# ============= 数据分析辅助路由 =============

class ModelRequirementScanRequest(BaseModel):
    """模型需求扫描请求体（MDL解析）"""
    mdl: Any  # MDL JSON 对象或字符串
    session_id: Optional[str] = None

@app.post("/api/agent/model-requirement/scan")
async def model_requirement_scan_endpoint(request: ModelRequirementScanRequest):
    """
    模型需求扫描端点：解析 MDL，提取模型输入/输出/参数需求

    输入：MDL JSON（对象或字符串）
    输出：结构化的需求信息
    """
    try:
        # 直接调用工具以避免引入LLM，确保纯解析
        mdl_input = request.mdl
        if isinstance(mdl_input, (dict, list)):
            result = tool_parse_mdl.invoke({"mdl_data": mdl_input})
        elif isinstance(mdl_input, str):
            # 如果是字符串，可能是JSON文本
            result = tool_parse_mdl.invoke({"mdl_data": mdl_input})
        else:
            raise HTTPException(status_code=400, detail="Invalid MDL input type")

        return {
            "status": result.get("status", "success"),
            "requirements": result,
            "session_id": request.session_id
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Model requirement scan failed: {str(e)}")


@app.get("/api/agent/data-scan/stream")
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
                "facts": {},
                "profile": {},
                "status": "processing"
            }
            
            # 流式调用 LangGraph Agent
            current_tool = None
            final_state: DataScanState = {
                "messages": [],
                "file_path": file_path,
                "facts": {},
                "profile": {},
                "status": "processing",
            }
            full_response = ""
            is_json_started = False
            
            async for mode, chunk in data_scan_agent.astream(
                initial_state,
                stream_mode=["messages", "updates", "custom"],
            ):
                if mode == "messages":
                    message_chunk = chunk[0] if isinstance(chunk, tuple) else chunk
                    if isinstance(message_chunk, AIMessageChunk):
                        content = message_chunk.content

                        # 如果是字符串
                        if isinstance(content, str) and content.strip():
                            if content:
                                full_response += content
                                yield f"data: {json.dumps({
                                    'type': 'token',
                                    'message': content
                                }, ensure_ascii=False)}\n\n"

                        # 如果是 list（结构化 chunk）
                        elif isinstance(content, list):
                            for part in content:
                                if isinstance(part, dict) and part.get("type") == "text":
                                    text = part.get("text", "")
                                    if text:
                                        full_response += text
                                        yield f"data: {json.dumps({
                                            'type': 'token',
                                            'message': text
                                        }, ensure_ascii=False)}\n\n"

                        # 其他类型（忽略）
                        else:
                            pass

                        # 逻辑分流：
                        # 如果还没有遇到 ```json，则认为是给用户看的“口播”文字
                        if "```json" not in full_response:
                            yield f"data: {json.dumps({'type': 'token', 'message': content}, ensure_ascii=False)}\n\n"
                        else:
                            # 一旦检测到 JSON 开始，前端可以通过 status 事件显示“正在生成精美报告...”
                            if not is_json_started:
                                is_json_started = True
                                yield f"data: {json.dumps({'type': 'status', 'message': '正在构建数据可视化视图...'}, ensure_ascii=False)}\n\n"
                
                elif mode == "updates":
                # 处理不同类型的事件
                    if isinstance(chunk, dict):
                        final_state = merge_state(final_state, chunk)

                        for node_name, node_output in chunk.items():
                            # LLM 节点事件
                            if node_name == "llm_node":
                                messages = node_output.get("messages", [])
                                if messages and len(messages) > 0:
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
                                    tool_name = getattr(tmsg, "tool_name", "unknown")
                                    
                                    yield f"data: {json.dumps({
                                        'type': 'tool_result',
                                        'tool': tool_name,
                                        'message': f'工具执行完成: {tool_name}'
                                    }, ensure_ascii=False)}\n\n"

                        continue
                    
                    await asyncio.sleep(0)

            yield f"data: {json.dumps({
                'type': 'final',
                'profile': final_state.get("profile", {}),
                'session_id': session_id
            }, ensure_ascii=False)}\n\n"

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

def merge_state(old, update):
    if old is None:
        return update
    for _, v in update.items():
        old.update(v)
    return old

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