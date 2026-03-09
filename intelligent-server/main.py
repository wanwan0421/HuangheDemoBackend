from fastapi import FastAPI, WebSocket, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from agents.model_recommend.graph import agent, ModelState
from agents.alignment.graph import alignment_agent, AlignmentState
from agents.data_scan.graph import DataScanState, data_scan_agent
from agents.triangle_coordinator import get_coordinator, TriangleMatchingCoordinator
from agents.data_monitor import get_data_scanner
from langchain.messages import HumanMessage, AIMessageChunk, AnyMessage, ToolMessage
from typing import Any, Dict, List, Optional
import uuid
import json
import asyncio
from pydantic import BaseModel
import operator
from pathlib import Path
import logging

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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
    coordinator = get_coordinator()

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

                    # 屏蔽 parse_task_spec_node 的文本输出
                    # 如果当前是解析节点，不仅不显示 JSON，什么都不发给前端文本流
                    if node_name == "parse_task_spec_node" or node_name == "model_contract_node":
                        continue 

                    # 正常的LLM节点才发送 Token
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
                            # 处理parse_task_spec_node节点
                            if node_name == "parse_task_spec_node":
                                # 提取 Task_spec
                                if "Task_spec" in node_output:
                                    specific_spec = node_output["Task_spec"]
                                    coordinator.update_task_and_model_from_stream(
                                        session_id=thread_id,
                                        task_spec=specific_spec
                                    )
                                    
                                    yield f"data: {json.dumps({
                                        'type': 'task_spec_generated', 
                                        'data': specific_spec
                                    }, ensure_ascii=False)}\n\n"

                            # 处理recommend_model_node节点
                            elif node_name == "recommend_model_node":
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

                            # 处理tool_node节点
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

                            # 处理model_contract_node节点
                            elif node_name == "model_contract_node":
                                # 提取 Model_contract
                                if "Model_contract" in node_output:
                                    model_contract = node_output["Model_contract"]
                                    coordinator.update_task_and_model_from_stream(
                                        session_id=thread_id,
                                        model_contract=model_contract
                                    )
                                    
                                    yield f"data: {json.dumps({
                                        'type': 'model_contract_generated',
                                        'data': model_contract
                                    }, ensure_ascii=False)}\n\n"

                        continue

                    await asyncio.sleep(0)

                elif mode == "custom":
                    # 工具内部通过 StreamWriter 发出的数据
                    yield f"data: {json.dumps({
                        'type': 'custom',
                        'data': chunk
                    }, ensure_ascii=False)}\n\n"
            
            session = coordinator.get_session(thread_id)
            yield f"data: {json.dumps({
                'type': 'final',
                'session_id': thread_id,
                'phase': 'task_model_completed',
                'has_task_spec': bool(session and session.task_spec),
                'has_model_contract': bool(session and session.model_contract)
            }, ensure_ascii=False)}\n\n"
                
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream"
    )

# ============= 数据分析辅助路由 =============

@app.get("/api/agent/data-scan/stream")
async def data_scan_stream_endpoint(file_path: str, session_id: Optional[str] = None, sessionId: Optional[str] = None):
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
    session_id = session_id or sessionId or str(uuid.uuid4())
    coordinator = get_coordinator()
    
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
                        if "```json" not in full_response:
                            yield f"data: {json.dumps({'type': 'token', 'message': content}, ensure_ascii=False)}\n\n"
                        else:
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

            final_profile = final_state.get("profile", {})
            session = coordinator.add_data_profile_from_stream(
                session_id=session_id,
                file_path=file_path,
                profile=final_profile
            )

            yield f"data: {json.dumps({
                'type': 'final',
                'profile': final_profile,
                'session_id': session_id,
                'saved_to_session': True,
                'data_profile_count': len(session.data_profiles)
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

# ============= 数据驱动三角检验API（流式闭环） =============

@app.post("/api/agent/align-session")
async def align_session(session_id: str):
    """
    一键对齐：基于已保存的task_spec + data_profiles执行三角检验
    
    前端流程闭环：
    1. GET /api/agent/stream?query=xxx → 获取session_id + task_spec/model_contract
    2. GET /api/agent/data-scan/stream?file_path=xxx&sessionId=xxx → 保存data_profiles
    3. POST /api/agent/align-session?session_id=xxx → 执行对齐，返回Go/No-Go决策
    
    Args:
        session_id: 会话ID（由流式接口返回）
    
    Returns:
        对齐结果、Go/No-Go决策、建议操作列表
    """
    try:
        coordinator = get_coordinator()
        session = coordinator.get_session(session_id)
        
        if not session:
            raise HTTPException(status_code=404, detail=f"会话 {session_id} 不存在")
        
        # 执行对齐
        session = await coordinator.execute_alignment(session_id)
        alignment_result = session.alignment_result or {}
        
        return {
            "status": "success",
            "session_id": session_id,
            "alignment_result": alignment_result,
            "alignment_status": session.status.value,
            "go_no_go": alignment_result.get("go_no_go", "no-go"),
            "can_run_now": alignment_result.get("can_run_now", False),
            "recommended_actions": alignment_result.get("recommended_actions", []),
            "minimal_runnable_inputs": alignment_result.get("minimal_runnable_inputs", []),
            "mapping_plan": alignment_result.get("mapping_plan_draft", [])
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"对齐失败: {e}")
        raise HTTPException(status_code=500, detail=f"对齐执行失败: {str(e)}")