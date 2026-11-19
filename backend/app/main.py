"""CULTScope 后端入口。"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.cult import router as cult_router
from app.api.imdb import router as imdb_router
from app.api.movies import router as movies_router
from app.core.config import settings

app = FastAPI(
    title="CULTScope API",
    version="0.2.0",
    description="邪典电影文化观察站 —— 阶段二：数据清洗与探索性可视化",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(movies_router)
app.include_router(cult_router)
app.include_router(imdb_router)


@app.get("/", tags=["system"])
def root() -> dict:
    """根路径：演示时快速确认 API 已启动。"""
    return {
        "name": "CULTScope API",
        "version": app.version,
        "status": "running",
        "docs": "/docs",
    }


@app.get("/api/health", tags=["system"])
def health() -> dict:
    """健康检查：确认服务可访问、TMDb Token 是否已配置（不回显 Token）。"""
    return {
        "status": "ok",
        "app": settings.app_name,
        "env": settings.app_env,
        "version": app.version,
        "tmdb_configured": bool(settings.tmdb_bearer_token),
    }
