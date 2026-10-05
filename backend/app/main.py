"""光伏电站运维管理平台 后端服务入口。

启动：uvicorn app.main:app --host 127.0.0.1 --port 8000
健康检查：GET /api/health
"""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.db import initialize_database
from app.errors import DomainError
from app.routers import ROUTERS
from app.store import store

app = FastAPI(title="光伏电站运维管理平台", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(DomainError)
def domain_error_handler(_: Request, exc: DomainError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})


initialize_database()

for module in ROUTERS:
    app.include_router(module.router)


@app.get("/api/health")
def health() -> dict[str, object]:
    """健康检查：确认服务已经监听、示例数据已经就绪。"""
    return {"ok": True, "app": settings.app_name, "modules": len(store.module_names()) + 2}


@app.get("/api/overview")
def overview() -> dict[str, object]:
    """运营概览：把各业务模块的待处理量汇总成看板卡片。"""
    return store.overview()
