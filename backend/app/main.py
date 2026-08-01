"""SpriteFrameService 应用入口。"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.router import api_router
from app.config import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    settings.ensure_dirs()
    yield
    # 优雅关闭：清理空闲会话
    from app.services.session import session_manager
    session_manager.cleanup_idle(max_idle_seconds=0)


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="SpriteFrameService",
        description="精灵帧工作室 - 后端服务 API",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router)

    @app.get("/api/health")
    def health():
        return {"status": "ok", "app": "SpriteFrameService"}

    # 托管前端构建产物（若存在）
    frontend_dir = settings.resolved_frontend_dir
    if frontend_dir.is_dir():
        app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")

    return app


app = create_app()
