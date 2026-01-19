"""
模型输入需求验证 - 主服务和 API
提供 REST API 和流式 SSE 接口
"""

import json
import asyncio
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Dict, Any, List
from pathlib import Path
import logging
from graph import model_requirement_graph
from tools import ModelRequirementState

# 日志配置
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============================================================================
# 数据模型
# ============================================================================

class ValidateRequest(BaseModel):
    """验证请求"""
    mdl_data: Dict[str, Any]
    data_file_path: str


class ValidateResponse(BaseModel):
    """验证响应"""
    status: str
    mdl_requirements: Dict[str, Any]
    data_profile: Dict[str, Any]
    validation_result: Dict[str, Any]


# ============================================================================
# FastAPI 应用
# ============================================================================

app = FastAPI(title="Model Requirement Validator")

# 临时文件存储目录
UPLOAD_DIR = Path("./model_uploads")
UPLOAD_DIR.mkdir(exist_ok=True)


@app.post("/api/validate", response_model=ValidateResponse)
async def validate_data(request: ValidateRequest) -> ValidateResponse:
    """
    验证数据是否符合模型需求
    
    请求:
    {
        "mdl_data": {
            "modelName": "模型名称",
            "inputs": [...]
        },
        "data_file_path": "/path/to/data"
    }
    
    返回:
    {
        "status": "success",
        "mdl_requirements": {...},
        "data_profile": {...},
        "validation_result": {...}
    }
    """
    try:
        # 初始化状态
        initial_state: ModelRequirementState = {
            "messages": [],
            "mdl_data": request.mdl_data,
            "data_file_path": request.data_file_path,
            "mdl_requirements": {},
            "data_profile": {},
            "validation_result": {},
            "status": "initializing"
        }

        # 执行图
        logger.info(f"开始验证: {request.data_file_path}")
        final_state = model_requirement_graph.invoke(initial_state)

        return ValidateResponse(
            status="success",
            mdl_requirements=final_state.get("mdl_requirements", {}),
            data_profile=final_state.get("data_profile", {}),
            validation_result=final_state.get("validation_result", {})
        )

    except Exception as e:
        logger.error(f"验证失败: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/validate/stream")
async def validate_data_stream(request: ValidateRequest):
    """
    验证数据 - 流式响应（SSE）
    """
    async def event_generator():
        try:
            # 初始化状态
            initial_state: ModelRequirementState = {
                "messages": [],
                "mdl_data": request.mdl_data,
                "data_file_path": request.data_file_path,
                "mdl_requirements": {},
                "data_profile": {},
                "validation_result": {},
                "status": "initializing"
            }

            # 发送开始事件
            yield f"data: {json.dumps({'event': 'start', 'message': '开始验证数据'})}\n\n"

            # 执行图
            logger.info(f"开始流式验证: {request.data_file_path}")

            # 使用 stream 获取中间状态
            async for event in model_requirement_graph.astream(initial_state):
                # 发送事件
                for key, value in event.items():
                    if key == "llm":
                        yield f"data: {json.dumps({'event': 'llm', 'message': '执行 LLM 分析'})}\n\n"
                    elif key == "tools":
                        yield f"data: {json.dumps({'event': 'tools', 'message': '执行工具分析'})}\n\n"

            # 发送最终状态
            yield f"data: {json.dumps({'event': 'complete', 'data': event})}\n\n"

        except Exception as e:
            logger.error(f"流式验证失败: {str(e)}")
            yield f"data: {json.dumps({'event': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream"
    )


@app.post("/api/validate/upload")
async def validate_with_upload(mdl_data: str = None, data_file: UploadFile = File(...)):
    """
    验证上传的数据文件
    
    form-data:
    - mdl_data: MDL 文件的 JSON 字符串或直接的 JSON
    - data_file: 上传的数据文件
    """
    try:
        # 保存上传的文件
        file_path = UPLOAD_DIR / data_file.filename
        with open(file_path, "wb") as f:
            content = await data_file.read()
            f.write(content)

        # 解析 MDL 数据
        if isinstance(mdl_data, str):
            mdl_obj = json.loads(mdl_data)
        else:
            mdl_obj = mdl_data

        # 创建验证请求
        request = ValidateRequest(
            mdl_data=mdl_obj,
            data_file_path=str(file_path)
        )

        # 执行验证
        return await validate_data(request)

    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid MDL JSON")
    except Exception as e:
        logger.error(f"验证失败: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/health")
async def health_check():
    """健康检查"""
    return {
        "status": "healthy",
        "service": "model-requirement-validator"
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8001,
        log_level="info"
    )
