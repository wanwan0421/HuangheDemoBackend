# -*- coding: utf-8 -*-
"""
遥感监测 Python 服务主入口
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import PROJECT_NAME, API_PREFIX, ALLOWED_ORIGINS
from app.routers.landcover import router as landcover_router
from app.routers.hydrology import router as hydrology_router


app = FastAPI(
    title=PROJECT_NAME,
    description="黄河流域遥感监测动态瓦片服务",
    version="1.0.0",
)


# 允许前端开发环境跨域访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", summary="服务健康检查")
def root():
    return {
        "message": "Remote Sensing Tile Server is running."
    }


# 注册土地覆盖遥感路由
app.include_router(
    landcover_router,
    prefix=API_PREFIX,
)

# 注册水文遥感路由
app.include_router(
    hydrology_router,
    prefix=API_PREFIX,
)