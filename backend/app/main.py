"""
FastAPI 应用入口

AI 长篇小说结构化创作引擎 v2.0

注册所有模块的 API 路由，配置生命周期事件、中间件、异常处理器。
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

import modules.character.models  # noqa: F401

# 注册所有 ORM 模型到 Base.metadata（FK 依赖解析需要）
import modules.project.models  # noqa: F401
import modules.world.models  # noqa: F401
import modules.world.tasks  # noqa: F401 — 注册任务处理器
from core.config import get_settings
from core.database import get_manager
from infrastructure.tasks import api as tasks_api
from modules.character import api as character_api
from modules.context import api as context_api
from modules.geo import api as geo_api
from modules.imports import api as imports_api
from modules.memory import api as memory_api
from modules.outline import api as outline_api
from modules.project import api as project_api
from modules.rag import api as rag_api
from modules.review import api as review_api
from modules.timeline import api as timeline_api
from modules.world import api as world_api
from modules.writing import api as writing_api

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 生命周期管理
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """
    应用生命周期：

    startup:
        - 初始化数据库连接池
        - 检查 pgvector 扩展
        - 配置日志级别

    shutdown:
        - 关闭所有数据库连接
    """
    settings = get_settings()

    # --- 配置日志 ---
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    logger.info(
        "Starting %s v%s",
        settings.app_name,
        settings.app_version,
    )

    # --- 初始化数据库 ---
    manager = get_manager()
    manager.init()

    # --- 检查 pgvector ---
    try:
        vector_ok = await manager.check_vector_extension()
        if vector_ok:
            logger.info("pgvector extension detected — vector ops enabled.")
        else:
            logger.warning(
                "pgvector extension NOT detected. "
                "Install it via: CREATE EXTENSION vector;"
            )
    except Exception as exc:
        logger.warning(
            "Could not check pgvector extension: %s. "
            "Proceeding without vector verification.",
            exc,
        )

    # --- 启动完成 ---
    logger.info("Application startup complete.")

    yield  # <-- 应用运行期间

    # --- 关闭清理 ---
    logger.info("Shutting down — closing database connections...")
    await manager.close()
    logger.info("Application shutdown complete.")


# ---------------------------------------------------------------------------
# 应用实例
# ---------------------------------------------------------------------------

app = FastAPI(
    title="AI 长篇小说结构化创作引擎",
    description=(
        "面向中文长篇小说的结构化创作系统。"
        "管理世界对象、人物档案、地理历史、长期记忆、时间线、剧情结构，"
        "并支持 RAG 检索、上下文编译和结构复查。"
    ),
    version=get_settings().app_version,
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)


# ---------------------------------------------------------------------------
# 中间件
# ---------------------------------------------------------------------------

# 纯 ASGI 耗时记录 middleware：不依赖 BaseHTTPMiddleware，
# 避免与 CORSMiddleware 的 ASGI 层级不兼容问题。
# CORS middleware 在下方通过 add_middleware 添加以保持最外层。


class _TimingMiddleware:
    """在响应头注入 X-Request-Time-Ms"""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        start = time.perf_counter()

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                elapsed = time.perf_counter() - start
                headers = list(message.get("headers", []))
                headers.append(
                    (b"X-Request-Time-Ms", str(round(elapsed * 1000, 1)).encode())
                )
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_headers)
        except Exception:
            elapsed = time.perf_counter() - start
            logger.error(
                "%s — unhandled exception after %.1fms",
                scope.get("path", ""),
                round(elapsed * 1000, 1),
            )
            raise


app.add_middleware(_TimingMiddleware)


# CORS 配置：开发环境允许前端本地文件 + localhost
# 生产环境请通过 ALLOWED_ORIGINS 环境变量设置具体域名
_origins = get_settings().allowed_origins
if not _origins or _origins == ["*"]:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
else:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


# ---------------------------------------------------------------------------
# 异常处理器
# ---------------------------------------------------------------------------


class AppError(Exception):
    """应用级业务异常基类"""

    def __init__(self, message: str, status_code: int = 400) -> None:
        self.message = message
        self.status_code = status_code
        super().__init__(message)


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    """业务异常 → JSON 错误响应"""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.__class__.__name__,
            "message": exc.message,
            "status_code": exc.status_code,
        },
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """全局兜底异常处理器"""
    logger.exception("Unhandled exception: %s", exc)
    return JSONResponse(
        status_code=500,
        content={
            "error": "InternalServerError",
            "message": "服务器内部错误，请稍后重试。",
            "status_code": 500,
        },
    )


# ---------------------------------------------------------------------------
# 健康检查 & 根路由
# ---------------------------------------------------------------------------


@app.get("/api/health", tags=["system"])
async def health_check():
    """健康检查端点"""
    manager = get_manager()
    db_ok = False
    try:
        async with manager.session() as sess:
            from sqlalchemy import text

            result = await sess.execute(text("SELECT 1"))
            db_ok = result.scalar() == 1
    except Exception as exc:
        logger.warning("Health check — DB unreachable: %s", exc)

    settings = get_settings()
    status = "healthy" if db_ok else "degraded"
    result = {
        "status": status,
        "database": "connected" if db_ok else "unreachable",
        "version": settings.app_version,
        "app_name": settings.app_name,
    }
    if status == "degraded":
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=503, content=result)
    return result


@app.get("/", tags=["system"])
async def root():
    """API 根路由 — 返回系统概览信息"""
    settings = get_settings()
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "description": "AI 长篇小说结构化创作引擎",
        "docs": "/api/docs",
        "openapi": "/api/openapi.json",
        "modules": [
            "projects",
            "world",
            "characters",
            "geo",
            "memory",
            "timeline",
            "outline",
            "rag",
            "context",
            "review",
            "writing",
            "tasks",
        ],
    }


# ---------------------------------------------------------------------------
# 路由注册
# ---------------------------------------------------------------------------

# 注意：各模块 router 已自带 prefix（如 /api/projects），此处 include 时不额外加前缀。
# 如需版本控制，未来可统一改为 prefix="/api/v1" + 移除模块内 prefix。

app.include_router(project_api.router)
app.include_router(imports_api.router)
app.include_router(world_api.router)
app.include_router(character_api.router)
app.include_router(geo_api.router)
app.include_router(memory_api.router)
app.include_router(timeline_api.router)
app.include_router(outline_api.router)
app.include_router(rag_api.router)
app.include_router(context_api.router)
app.include_router(review_api.router)
app.include_router(writing_api.router)
app.include_router(tasks_api.router)


# ---------------------------------------------------------------------------
# 列出所有注册路由（便于调试）
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    print("\n=== Registered Routes ===\n")
    for route in app.routes:
        if hasattr(route, "methods") and hasattr(route, "path"):
            methods = ",".join(sorted(route.methods - {"HEAD", "OPTIONS"}))
            print(f"  {methods:8s} {route.path}")
    print()

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )
