"""
FastAPI 应用入口

AI 长篇小说结构化创作引擎 v2.0

注册所有模块的 API 路由，配置生命周期事件、中间件、异常处理器。
"""

from __future__ import annotations  # noqa: I001

from infrastructure.llm.model_limits import get_model_limits
import asyncio
import hmac
import logging
import re
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import wraps
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from app.bootstrap import register_container_services
from app.http_rate_limit import HttpRateLimitMiddleware
from app.task_runtime import register_task_handlers
from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from starlette.middleware.errors import ServerErrorMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send

from core import container
from core.config import (
    get_settings,
    validate_app_access_token_config,
    validate_auth_config,
    validate_cors_origins,
    validate_http_rate_limit_config,
)
from core.database import get_manager
from core.errors import DomainError
from core.logging_context import (
    bind_validated_novel_id,
    current_novel_id_for_log,
    novel_log_scope,
)
from infrastructure.embedding.client import (
    BgeEmbeddingClient,
    prewarm_embedding_worker,
)
from infrastructure.llm.redaction import redact_diagnostic


register_container_services()
register_task_handlers()

logger = logging.getLogger(__name__)


def _configure_application_logging(log_level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    # The OpenAI SDK logs the complete request JSON at DEBUG, including prompt
    # context and manuscript excerpts. Application DEBUG must never imply that
    # author content is copied into transport logs.
    logging.getLogger("openai").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.INFO)


_REQUEST_PATH_LOG_MAX_LENGTH = 160
_UUID_PATH_SEGMENT_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_LONG_HEX_PATH_SEGMENT_RE = re.compile(r"^[0-9a-fA-F]{16,}$")
_LONG_HASH_PATH_SEGMENT_RE = re.compile(r"^(?=.*\d)[A-Za-z0-9_-]{24,}$")
_HTTP_METHOD_LOG_RE = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Z]{1,32}$")
_EXCEPTION_TYPE_LOG_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,79}$")
_TRACE_FRAME_LOG_RE = re.compile(r"^[A-Za-z0-9_.<>-]{1,80}$")
_STATE_CHANGING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_API_SECURITY_EXEMPT_PATHS = {"/api/health", "/api/health/llm"}
_DATABASE_HEALTH_TIMEOUT_SECONDS = 2.0
_OUTER_RESPONSE_HEADERS = {
    b"strict-transport-security",
    b"x-content-type-options",
    b"x-frame-options",
    b"x-request-time-ms",
}


def _redact_request_path(path: str) -> str:
    """Redact dynamic identifiers from request paths before logging."""
    path_only, separator, _query = path.partition("?")
    redacted_segments = [
        "<id>" if _should_redact_path_segment(segment) else segment
        for segment in path_only.split("/")
    ]
    redacted_path = "/".join(redacted_segments)
    if separator:
        redacted_path = f"{redacted_path}?<redacted>"
    if len(redacted_path) <= _REQUEST_PATH_LOG_MAX_LENGTH:
        return redacted_path
    return f"{redacted_path[: _REQUEST_PATH_LOG_MAX_LENGTH - 3]}..."


def _should_redact_path_segment(segment: str) -> bool:
    if not segment:
        return False
    return (
        segment.isdigit()
        or _UUID_PATH_SEGMENT_RE.fullmatch(segment) is not None
        or _LONG_HEX_PATH_SEGMENT_RE.fullmatch(segment) is not None
        or _LONG_HASH_PATH_SEGMENT_RE.fullmatch(segment) is not None
    )


def _domain_error_log_fields(
    request: Request | None,
    exc: DomainError,
) -> tuple[str, str]:
    """Return bounded, non-user-content fields for DomainError logs."""
    del exc
    scope = getattr(request, "scope", None)
    method, route_template = _request_log_fields(scope)
    return method, route_template


def _request_log_fields(scope: object) -> tuple[str, str]:
    """Return bounded method and route-template fields for request logs."""
    if not isinstance(scope, dict) or scope.get("type") != "http":
        scope = {}
    raw_method = scope.get("method")
    method = raw_method.upper() if isinstance(raw_method, str) else "UNKNOWN"
    if _HTTP_METHOD_LOG_RE.fullmatch(method) is None:
        method = "UNKNOWN"
    route = scope.get("route")
    try:
        route_template = getattr(route, "path", "")
    except Exception:
        route_template = ""
    if (
        not isinstance(route_template, str)
        or not route_template
        or len(route_template) > _REQUEST_PATH_LOG_MAX_LENGTH
        or not route_template.isprintable()
    ):
        route_template = "<unresolved>"
    return method, route_template


def _bind_successful_route_novel_id(scope: Scope, status_code: int | None) -> None:
    """Bind a path project ID only after the routed operation succeeded."""
    if status_code is None or not 200 <= status_code < 400:
        return
    path_params = scope.get("path_params")
    if not isinstance(path_params, dict):
        return
    value = path_params.get("novel_id") or path_params.get("project_id")
    if value is not None:
        bind_validated_novel_id(value)


def _safe_exception_stack(exc: Exception) -> str:
    """Return bounded frame locations without exception values or source lines."""
    frames: list[str] = []
    traceback = exc.__traceback__
    while traceback is not None:
        code = traceback.tb_frame.f_code
        raw_filename = code.co_filename.replace("\\", "/").rsplit("/", 1)[-1]
        filename = (
            raw_filename if _TRACE_FRAME_LOG_RE.fullmatch(raw_filename) else "<unknown>"
        )
        raw_function = code.co_name
        function = (
            raw_function if _TRACE_FRAME_LOG_RE.fullmatch(raw_function) else "<unknown>"
        )
        frames.append(f"{filename}:{traceback.tb_lineno}:{function}")
        traceback = traceback.tb_next
    return " > ".join(frames[-32:]) or "<unavailable>"


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
    _install_operation_trace_route_adapters(app)

    # --- 配置日志 ---
    _configure_application_logging(settings.log_level)

    logger.info(
        "Starting %s v%s",
        settings.app_name,
        settings.app_version,
    )

    # --- 初始化数据库 ---
    manager = get_manager()
    manager.init()
    if getattr(settings, "auth_mode", "local") == "public":
        from modules.account.contracts import BOOTSTRAP_ACCOUNT_ID
        from modules.account.models import Account

        async with manager.session() as session:
            bootstrap = await session.get(Account, BOOTSTRAP_ACCOUNT_ID)
            if bootstrap is None or bootstrap.legacy_claimed_at is None:
                raise RuntimeError(
                    "Public auth requires claim-legacy before application startup"
                )

    # --- 检查 pgvector ---
    # 生产判断用 APP_ENV（不是 auth_mode=="public" 的引导开关）：
    # production 下向量扩展缺失或探测失败即拒绝启动，其余环境只告警。
    production_runtime = settings.app_env.strip().lower() == "production"
    try:
        vector_ok = await manager.check_vector_extension()
    except Exception as exc:
        if production_runtime:
            logger.error(
                "Could not check pgvector extension: %s. "
                "Production requires vector operations; refusing to start.",
                redact_diagnostic(exc, limit=500),
            )
            raise RuntimeError(
                "pgvector extension check failed; production startup aborted"
            ) from exc
        logger.warning(
            "Could not check pgvector extension: %s. "
            "Proceeding without vector verification.",
            redact_diagnostic(exc, limit=500),
        )
    else:
        if vector_ok:
            logger.info("pgvector extension detected — vector ops enabled.")
        elif production_runtime:
            logger.error(
                "pgvector extension NOT detected. "
                "Production requires vector operations. "
                "Install it via: CREATE EXTENSION vector; refusing to start."
            )
            raise RuntimeError("pgvector extension is required when APP_ENV=production")
        else:
            logger.warning(
                "pgvector extension NOT detected. "
                "Install it via: CREATE EXTENSION vector;"
            )

    # --- 启动完成 ---
    prewarm_task: asyncio.Task[None] | None = None
    if settings.rag_prewarm_on_startup:

        async def _background_prewarm() -> None:
            try:
                await prewarm_embedding_worker()
            except Exception as exc:
                logger.error(
                    "RAG embedding prewarm failed: %s",
                    redact_diagnostic(exc, limit=500),
                )

        prewarm_task = asyncio.create_task(_background_prewarm())

    logger.info("Application startup complete.")

    try:
        yield  # <-- 应用运行期间
    finally:
        # --- 关闭清理 ---
        # Lifespan body exceptions and one failing closer must not skip the
        # remaining resource owners. In particular, a container close error
        # must not leave the embedding worker or DB pool alive.
        logger.info("Shutting down — closing database connections...")
        await _shutdown_application_resources(manager, prewarm_task)
        logger.info("Application shutdown complete.")


async def _shutdown_application_resources(
    manager: object,
    prewarm_task: asyncio.Task[None] | None,
) -> None:
    """Attempt every application closer and report all cleanup failures."""
    errors: list[Exception] = []

    if prewarm_task is not None:
        if not prewarm_task.done():
            prewarm_task.cancel()
        try:
            await prewarm_task
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            exc.add_note("while awaiting RAG embedding prewarm shutdown")
            errors.append(exc)

    closers = (
        ("application container", container.shutdown),
        ("embedding client", BgeEmbeddingClient.close_instance),
        ("database manager", manager.close),
    )
    for label, closer in closers:
        try:
            await closer()
        except Exception as exc:
            exc.add_note(f"while closing {label}")
            errors.append(exc)

    if errors:
        raise ExceptionGroup("Errors during application shutdown", errors)


# ---------------------------------------------------------------------------
# 应用实例
# ---------------------------------------------------------------------------

_initial_settings = get_settings()
_public_mode = _initial_settings.auth_mode.strip().lower() == "public"
app = FastAPI(
    title="AI 长篇小说结构化创作引擎",
    description=(
        "面向中文长篇小说的结构化创作系统。"
        "管理世界对象、人物档案、地理历史、长期记忆、时间线、剧情结构，"
        "并支持 RAG 检索、上下文编译和结构复查。"
    ),
    version=get_settings().app_version,
    debug=get_settings().debug,
    lifespan=lifespan,
    docs_url=None if _public_mode else "/api/docs",
    redoc_url=None if _public_mode else "/api/redoc",
    openapi_url=None if _public_mode else "/api/openapi.json",
)


# ---------------------------------------------------------------------------
# 中间件
# ---------------------------------------------------------------------------

# 纯 ASGI 耗时记录 middleware：不依赖 BaseHTTPMiddleware，
# 避免与 CORSMiddleware 的 ASGI 层级不兼容问题。
# 该 middleware 在所有短路响应 middleware 注册完成后最后添加，以保持最外层。


class _TimingMiddleware:
    """注入统一响应头，并记录不含用户内容的结构化 access log。"""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        with novel_log_scope():
            await self._handle_http(scope, receive, send)

    async def _handle_http(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        start = time.perf_counter()
        status_code: int | None = None

        async def send_with_headers(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                raw_status = message.get("status")
                status_code = (
                    raw_status
                    if type(raw_status) is int and 100 <= raw_status <= 599
                    else None
                )
                elapsed = time.perf_counter() - start
                headers = [
                    (name, value)
                    for name, value in message.get("headers", [])
                    if name.lower() not in _OUTER_RESPONSE_HEADERS
                ]
                headers.extend(
                    [
                        (b"x-content-type-options", b"nosniff"),
                        (b"x-frame-options", b"DENY"),
                        (
                            b"x-request-time-ms",
                            str(round(elapsed * 1000, 1)).encode(),
                        ),
                    ]
                )
                if scope.get("scheme") == "https":
                    headers.append((b"strict-transport-security", b"max-age=31536000"))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_headers)
        except Exception:
            elapsed = time.perf_counter() - start
            method, route_template = _request_log_fields(scope)
            logger.error(
                "Request failed method=%s route=%s status=%d duration_ms=%.1f "
                "novel_id=%s",
                method,
                route_template,
                status_code or 500,
                round(elapsed * 1000, 1),
                current_novel_id_for_log(),
            )
            raise

        if status_code is None:
            elapsed = time.perf_counter() - start
            method, route_template = _request_log_fields(scope)
            logger.error(
                "Request failed method=%s route=%s status=500 duration_ms=%.1f "
                "novel_id=%s",
                method,
                route_template,
                round(elapsed * 1000, 1),
                current_novel_id_for_log(),
            )
            return
        _bind_successful_route_novel_id(scope, status_code)
        elapsed = time.perf_counter() - start
        method, route_template = _request_log_fields(scope)
        level = logging.ERROR if status_code >= 500 else logging.INFO
        logger.log(
            level,
            "Request completed method=%s route=%s status=%d duration_ms=%.1f novel_id=%s",
            method,
            route_template,
            status_code,
            round(elapsed * 1000, 1),
            current_novel_id_for_log(),
        )


class _ApiSecurityMiddleware:
    """App-wide lightweight guard for same-origin console writes and closed tests."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        path = str(scope.get("path") or "")
        method = str(scope.get("method") or "").upper()
        if not path.startswith("/api/") or method == "OPTIONS":
            await self.app(scope, receive, send)
            return

        headers = {
            key.decode("latin1").lower(): value.decode("latin1")
            for key, value in scope.get("headers", [])
        }
        settings = get_settings()

        if (
            settings.auth_mode == "closed_test"
            and settings.app_access_token
            and path not in _API_SECURITY_EXEMPT_PATHS
        ):
            expected = f"Bearer {settings.app_access_token}"
            supplied = headers.get("authorization", "")
            if not hmac.compare_digest(supplied, expected):
                response = JSONResponse(
                    status_code=401,
                    content={"detail": "Missing or invalid access token"},
                )
                await response(scope, receive, send)
                return

        if (
            method in _STATE_CHANGING_METHODS
            and headers.get("x-requested-with") != "XMLHttpRequest"
        ):
            response = JSONResponse(
                status_code=403,
                content={"detail": "Missing X-Requested-With header"},
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)


app.add_middleware(_ApiSecurityMiddleware)

from modules.account.middleware import AccountAuthMiddleware  # noqa: E402

app.add_middleware(AccountAuthMiddleware)


# CORS 配置：开发环境允许前端本地文件 + localhost
# 生产环境请通过 ALLOWED_ORIGINS 环境变量设置具体域名
_settings = get_settings()
_origins = _settings.allowed_origins
validate_cors_origins(_settings.app_env, _origins)
validate_auth_config(_settings)
if _settings.auth_mode == "closed_test":
    validate_app_access_token_config(_settings.app_env, _settings.app_access_token)
validate_http_rate_limit_config(
    _settings.app_env,
    _settings.http_rate_limit_per_minute,
    _settings.http_rate_limit_burst,
    _settings.http_rate_limit_max_clients,
)
get_model_limits("legacy", "legacy", settings=_settings)
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


def _omit_validation_error_input(value: object) -> object:
    """Remove request values from validation diagnostics before serialization."""
    if isinstance(value, dict):
        return {
            key: _omit_validation_error_input(item)
            for key, item in value.items()
            if key != "input"
        }
    if isinstance(value, list | tuple):
        return [_omit_validation_error_input(item) for item in value]
    return value


@app.exception_handler(RequestValidationError)
async def request_validation_error_handler(
    _request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    """Return useful validation metadata without echoing submitted values."""
    return JSONResponse(
        status_code=422,
        content={"detail": jsonable_encoder(_omit_validation_error_input(exc.errors()))},
    )


@app.exception_handler(DomainError)
async def domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
    """领域异常 → HTTP JSON 响应。"""
    method, route_template = _domain_error_log_fields(request, exc)
    level = logging.ERROR if exc.status_code >= 500 else logging.INFO
    logger.log(
        level,
        "Domain request rejected method=%s route=%s status=%d novel_id=%s",
        method,
        route_template,
        exc.status_code,
        current_novel_id_for_log(),
    )
    content = {
        "error": exc.code,
        "detail": exc.message,
        "message": exc.message,
        "status_code": exc.status_code,
    }
    if exc.context:
        content["context"] = exc.context
    return JSONResponse(
        status_code=exc.status_code,
        content=content,
    )


async def _internal_server_error_response(
    _request: Request,
    _exc: Exception,
) -> JSONResponse:
    """Build the stable internal-error wire response without duplicate logging."""
    return JSONResponse(
        status_code=500,
        content={
            "error": "InternalServerError",
            "message": "服务器内部错误，请稍后重试。",
            "status_code": 500,
        },
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """全局兜底异常处理器"""
    raw_exception_type = type(exc).__name__
    exception_type = (
        raw_exception_type
        if _EXCEPTION_TYPE_LOG_RE.fullmatch(raw_exception_type)
        else "Exception"
    )
    logger.error(
        "Unhandled exception novel_id=%s type=%s stack=%s",
        current_novel_id_for_log(),
        exception_type,
        _safe_exception_stack(exc),
    )
    return await _internal_server_error_response(request, exc)


# FastAPI 自带的 ServerErrorMiddleware 固定在所有 user middleware 之外；若内层
# 应用抛出未处理异常，它生成的 500 响应不会再经过 user middleware。这里在耗时
# middleware 内侧复用同一错误响应层，使全局 500 JSON 响应也获得统一安全头；异常
# 仍会继续抛给外层错误层/ASGI server，保持现有错误日志与测试行为。
app.add_middleware(
    ServerErrorMiddleware,
    handler=_internal_server_error_response,
    debug=get_settings().debug,
)

# 位于认证/CORS/错误层之外，使无效令牌与未匹配路由同样受限；Timing 仍保持
# 最外层，以便 429 获得统一安全头和一条 access log。
app.add_middleware(
    HttpRateLimitMiddleware,
    requests_per_minute=_settings.http_rate_limit_per_minute,
    burst=_settings.http_rate_limit_burst,
    max_clients=_settings.http_rate_limit_max_clients,
)

# 最后注册即位于 Starlette user middleware 栈最外层，因此 CORS 预检、
# access-token/XHR 短路响应与已匹配路由均会有且仅有一条 access log。
app.add_middleware(_TimingMiddleware)


# ---------------------------------------------------------------------------
# 健康检查 & 根路由
# ---------------------------------------------------------------------------


@app.get("/api/health", tags=["system"])
async def health_check():
    """健康检查端点"""
    manager = get_manager()
    db_ok = False
    try:
        async with asyncio.timeout(_DATABASE_HEALTH_TIMEOUT_SECONDS):
            async with manager.session() as sess:
                from sqlalchemy import text

                result = await sess.execute(text("SELECT 1"))
                db_ok = result.scalar() == 1
    except Exception as exc:
        logger.warning(
            "Health check — DB unreachable: %s",
            redact_diagnostic(exc, limit=500),
        )

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


@app.get("/api/health/llm", tags=["system"])
async def llm_health_check():
    """LLM 服务能力检查；不读取账户凭据或访问 provider。"""
    from fastapi.responses import JSONResponse

    from infrastructure.llm.health import check_llm_service_health

    result = await check_llm_service_health()
    content = result.model_dump()
    if not result.ok:
        return JSONResponse(status_code=503, content=content)
    return content


@app.get("/", tags=["system"])
async def root():
    """API 根路由 — 返回系统概览信息"""
    settings = get_settings()
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "description": "AI 长篇小说结构化创作引擎",
        "docs": None if _public_mode else "/api/docs",
        "openapi": None if _public_mode else "/api/openapi.json",
        "modules": [
            "account",
            "projects",
            "world",
            "evidence",
            "story",
            "writing",
            "imports",
            "interaction",
            "tasks",
        ],
    }


# ---------------------------------------------------------------------------
# 路由注册
# ---------------------------------------------------------------------------

# 注意：各模块 router 已自带 prefix（如 /api/projects），
# 此处 include 时不额外加前缀。
# 如需版本控制，未来可统一改为 prefix="/api/v1" + 移除模块内 prefix。

from app import debug_api  # noqa: E402
from infrastructure.tasks import api as tasks_api  # noqa: E402
from modules.account.api import account_router  # noqa: E402
from modules.account.api import router as account_auth_router  # noqa: E402
from modules.account.legal import router as legal_router  # noqa: E402
from modules.account.oidc import (  # noqa: E402
    reauth_router as account_oidc_reauth_router,
)
from modules.account.oidc import router as account_oidc_router  # noqa: E402
from modules.assistant import api as assistant_api  # noqa: E402
from modules.assistant.notices_api import router as assistant_notices_router  # noqa: E402
from modules.assistant.operation_api import router as assistant_operation_http_router  # noqa: E402
from modules.collaboration import api as collaboration_api  # noqa: E402
from modules.collaboration import author_operations_api as collaboration_author_api  # noqa: E402
from modules.evidence import api as evidence_api  # noqa: E402
from modules.evolution import api as evolution_api  # noqa: E402

# geo/review — 已从 minimal-core 移除
# character API 已迁入 modules.world.api；模块已删除
from modules.imports import api as imports_api  # noqa: E402
from modules.imports.spreadsheet_migration import (  # noqa: E402
    api as spreadsheet_migration_api,  # noqa: E402
)
from modules.interaction import api as interaction_api  # noqa: E402
from modules.interaction import author_api as interaction_author_api  # noqa: E402
from modules.interaction.forecast_api import (  # noqa: E402
    router as interaction_forecast_router,  # noqa: E402
)
from modules.local_agent.api import router as local_agent_router  # noqa: E402
from modules.project.api import router as project_router  # noqa: E402
from modules.project.settings_api import (  # noqa: E402
    defaults_handler_router as project_defaults_handler_router,
)
from modules.story import api as story_api  # noqa: E402
from modules.story.character_arcs.api import router as story_character_arcs_router  # noqa: E402
from modules.story.continuity import api as memory_api  # noqa: E402
from modules.story.director_api import router as story_director_router  # noqa: E402
from modules.story.outline_state import api as outline_api  # noqa: E402
from modules.story.world_progression_api import router as story_world_progression_router  # noqa: E402
from modules.world import api as world_api  # noqa: E402
from modules.world import map_atlas_api as world_map_atlas_api  # noqa: E402
from modules.world import project_vocabulary_api as world_vocabulary_api  # noqa: E402
from modules.writing import api as writing_api  # noqa: E402

app.include_router(assistant_api.router)
app.include_router(assistant_operation_http_router)
app.include_router(assistant_notices_router)
app.include_router(collaboration_api.router)
app.include_router(collaboration_author_api.router)
app.include_router(project_router)
app.include_router(local_agent_router)
app.include_router(account_auth_router)
app.include_router(account_router)
app.include_router(account_oidc_router)
app.include_router(account_oidc_reauth_router)
app.include_router(legal_router)
app.include_router(interaction_api.demo_router)
app.include_router(spreadsheet_migration_api.router)
app.include_router(imports_api.router)
app.include_router(interaction_api.router)
app.include_router(interaction_author_api.router)

app.include_router(interaction_forecast_router)
app.include_router(world_api.router)
app.include_router(world_map_atlas_api.router)
app.include_router(world_vocabulary_api.router)
app.include_router(memory_api.router)
app.include_router(outline_api.router)
app.include_router(evidence_api.router)
app.include_router(evolution_api.router)
app.include_router(writing_api.router)
app.include_router(story_api.router)
app.include_router(story_director_router)
app.include_router(story_character_arcs_router)
app.include_router(story_world_progression_router)
app.include_router(tasks_api.router)
if not _public_mode:
    app.include_router(debug_api.router)
app.include_router(
    project_defaults_handler_router,
    prefix="/api/account/settings",
)


def _trace_route_arguments(
    values: dict,
    argument_map: dict | None = None,
    trace_fields: dict[str, str] | None = None,
) -> dict:
    if trace_fields is not None:
        arguments = {}
        missing = object()
        for field, source in trace_fields.items():
            value = values
            for part in source.split("."):
                value = (
                    value.get(part, missing)
                    if isinstance(value, dict)
                    else getattr(value, part, missing)
                )
                if value is missing:
                    break
            if value is not missing:
                arguments[field] = (
                    value.model_dump(mode="json")
                    if hasattr(value, "model_dump")
                    else value
                )
        return arguments
    arguments = {}
    for name, value in values.items():
        if name in {"db", "response"} or (
            name == "request" and isinstance(value, Request)
        ):
            continue
        if hasattr(value, "model_dump"):
            rendered = value.model_dump(mode="json")
            if isinstance(rendered, dict):
                target = (argument_map or {}).get(name)
                if target:
                    arguments[target] = rendered
                else:
                    arguments.update(rendered)
        else:
            arguments[name] = value
    return arguments


def _trace_result(value):
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return value
    return None


def _install_operation_trace_route_adapters(application: FastAPI) -> None:
    """Bind operation-marked HTTP writes to the same trace port/transaction."""
    from core.container import get
    from core.service_keys import ASSISTANT_OPERATIONS
    from modules.assistant.evidence_tools import fingerprint
    from modules.assistant.operation_trace_service import (
        bind_operation_trace_context,
        current_operation_trace_context,
        operation_trace_enabled,
        record_operation_trace,
        reset_operation_trace_context,
    )

    def concrete_routes(routes):
        for item in routes:
            if isinstance(item, APIRoute):
                yield item
                continue
            # Included routers use a separate effective route context (and
            # ASGI app) for each inclusion. Wrapping the source APIRoute has
            # no effect on requests dispatched through that context.
            effective_routes = getattr(item, "effective_route_contexts", None)
            if effective_routes is not None:
                for effective in effective_routes():
                    if isinstance(getattr(effective, "original_route", None), APIRoute):
                        yield effective

    operations = get(ASSISTANT_OPERATIONS)

    async def record_reversal(db, *, trace_context, reference, original_op_ids) -> None:
        """Match a completed domain receipt to its original traced execution."""
        from sqlalchemy import String, cast, select

        from modules.assistant.operation_trace_models import AssistantOperationTrace

        if not isinstance(reference, dict):
            trace_context["incomplete_count"] = (
                trace_context.get("incomplete_count", 0) + 1
            )
            return
        kind, ref_id = reference.get("type"), reference.get("id")
        try:
            ref_id = str(UUID(str(ref_id)))
        except (TypeError, ValueError, AttributeError):
            trace_context["incomplete_count"] = (
                trace_context.get("incomplete_count", 0) + 1
            )
            return
        if not isinstance(kind, str) or not kind or len(kind) > 80:
            trace_context["incomplete_count"] = (
                trace_context.get("incomplete_count", 0) + 1
            )
            return
        rows = (
            await db.scalars(
                select(AssistantOperationTrace)
                .where(
                    AssistantOperationTrace.novel_id == UUID(trace_context["novel_id"]),
                    AssistantOperationTrace.owner_id == UUID(trace_context["owner_id"]),
                    AssistantOperationTrace.op_id.in_(original_op_ids),
                    AssistantOperationTrace.event_type == "executed",
                    cast(AssistantOperationTrace.result_refs, String).like(f"%{ref_id}%"),
                )
                .order_by(AssistantOperationTrace.id.desc())
            )
        ).all()
        original = next(
            (
                row
                for row in rows
                if {"type": kind, "id": ref_id} in (row.result_refs or [])
                and row.call_id is not None
            ),
            None,
        )
        if original is None:
            trace_context["incomplete_count"] = (
                trace_context.get("incomplete_count", 0) + 1
            )
            return
        prior_restored = await db.scalar(
            select(AssistantOperationTrace.id)
            .where(
                AssistantOperationTrace.novel_id == original.novel_id,
                AssistantOperationTrace.owner_id == original.owner_id,
                AssistantOperationTrace.op_id == original.op_id,
                AssistantOperationTrace.call_id == original.call_id,
                AssistantOperationTrace.event_type == "restored",
            )
            .limit(1)
        )
        if prior_restored is not None:
            return
        saved = await record_operation_trace(
            db,
            enabled=True,
            novel_id=trace_context["novel_id"],
            owner_id=trace_context["owner_id"],
            operation=operations[original.op_id],
            event_type="restored",
            arguments=trace_context.get("arguments"),
            result={"result_ref": {"type": kind, "id": ref_id}},
            actor_type="ui",
            entrypoint="assistant.http",
            call_id=str(original.call_id),
            parent_call_id=trace_context["call_id"],
        )
        if saved is False:
            trace_context["incomplete_count"] = (
                trace_context.get("incomplete_count", 0) + 1
            )

    for route in concrete_routes(application.routes):
        if getattr(route, "_trace_adapter_installed", False):
            continue
        operation_id = (route.openapi_extra or {}).get("x-novelcraft-operation-id")
        if not operation_id:
            continue
        operation = operations.get(operation_id)
        if operation is None:
            raise RuntimeError(
                f"HTTP route references unknown assistant operation: {operation_id}"
            )
        original_endpoint = route.endpoint
        original_app = route.app
        argument_map = (route.openapi_extra or {}).get(
            "x-novelcraft-operation-argument-map", {}
        )
        trace_fields = (route.openapi_extra or {}).get(
            "x-novelcraft-operation-trace-fields"
        )
        operation_phase = (route.openapi_extra or {}).get(
            "x-novelcraft-operation-phase", "execute"
        )
        if operation_phase not in {"execute", "prepare"}:
            raise RuntimeError(f"Invalid HTTP operation phase: {operation_id}")
        confirmation_field = (route.openapi_extra or {}).get(
            "x-novelcraft-operation-confirmation-field"
        )
        call_id_field = (route.openapi_extra or {}).get(
            "x-novelcraft-operation-call-id-field"
        )
        terminal_event = (route.openapi_extra or {}).get(
            "x-novelcraft-operation-terminal-event"
        )
        reversal_op_ids = (route.openapi_extra or {}).get(
            "x-novelcraft-operation-reversal-op-ids", ()
        )
        reversal_ref_field = (route.openapi_extra or {}).get(
            "x-novelcraft-operation-reversal-ref-field", "result_ref"
        )
        if terminal_event is not None and (
            terminal_event != "restored"
            or operation_phase != "execute"
            or not reversal_op_ids
            or any(op_id not in operations for op_id in reversal_op_ids)
            or not isinstance(reversal_ref_field, str)
        ):
            raise RuntimeError(f"Invalid HTTP reversal declaration: {operation_id}")
        if trace_fields is not None and set(trace_fields) != set(
            operation.schema.model_fields
        ):
            raise RuntimeError(
                f"HTTP route trace fields differ from operation schema: {operation_id}"
            )

        @wraps(original_endpoint)
        async def traced_endpoint(
            *args,
            __endpoint=original_endpoint,
            __operation=operation,
            __argument_map=argument_map,
            __trace_fields=trace_fields,
            __operation_phase=operation_phase,
            __confirmation_field=confirmation_field,
            __call_id_field=call_id_field,
            __terminal_event=terminal_event,
            __reversal_op_ids=tuple(reversal_op_ids),
            __reversal_ref_field=reversal_ref_field,
            **kwargs,
        ):
            trace_context = current_operation_trace_context()
            db = kwargs.get("db")
            if trace_context is None or db is None:
                return await __endpoint(*args, **kwargs)
            from modules.account.facade import current_account_id

            try:
                owner_id = str(current_account_id())
            except Exception:
                return await __endpoint(*args, **kwargs)
            arguments = _trace_route_arguments(kwargs, __argument_map, __trace_fields)
            body_novel_id = next(
                (
                    getattr(value, "novel_id", None)
                    for value in kwargs.values()
                    if hasattr(value, "novel_id")
                ),
                None,
            )
            body_author_project_id = next(
                (
                    getattr(value, "author_project_id", None)
                    for value in kwargs.values()
                    if hasattr(value, "author_project_id")
                ),
                None,
            )
            novel_id = str(
                kwargs.get("novel_id")
                or kwargs.get("project_id")
                or body_novel_id
                or body_author_project_id
                or arguments.get("novel_id")
                or arguments.get("author_project_id")
                or arguments.get("project_id")
                or ""
            )
            if novel_id:
                from modules.project.facade import require_active_project

                # This wrapper runs before the endpoint's own guard. Trace
                # preference/salt/events must never touch another owner's or
                # a recycled project, even when tracing is disabled.
                await require_active_project(db, novel_id)
            if __call_id_field:
                stable_value = _trace_route_arguments(
                    kwargs, trace_fields={"stable": __call_id_field}
                ).get("stable")
                try:
                    stable_uuid = str(UUID(str(stable_value)))
                except (TypeError, ValueError, AttributeError) as exc:
                    raise RuntimeError(
                        f"HTTP operation stable call field missing: {__operation.op_id}"
                    ) from exc
                normalized = {
                    key: value
                    for key, value in arguments.items()
                    if key != "preview_fingerprint"
                }
                trace_context["call_id"] = str(
                    uuid5(
                        NAMESPACE_URL,
                        f"{novel_id}:{__operation.op_id}:{stable_uuid}:{fingerprint(normalized)}",
                    )
                )
            business_bind = db.get_bind()
            trace_context.update(
                owner_id=owner_id,
                novel_id=novel_id,
                arguments=arguments,
                operation=__operation,
                business_engine=getattr(business_bind, "engine", business_bind),
            )
            if not novel_id or not await operation_trace_enabled(db, owner_id):
                return await __endpoint(*args, **kwargs)
            trace_context["enabled"] = True
            already_terminal = None
            if __call_id_field:
                from sqlalchemy import select

                from modules.assistant.operation_trace_models import (
                    AssistantOperationTrace,
                )

                already_terminal = await db.scalar(
                    select(AssistantOperationTrace.id)
                    .where(
                        AssistantOperationTrace.novel_id == UUID(novel_id),
                        AssistantOperationTrace.owner_id == UUID(owner_id),
                        AssistantOperationTrace.op_id == __operation.op_id,
                        AssistantOperationTrace.call_id == UUID(trace_context["call_id"]),
                        AssistantOperationTrace.event_type == "executed",
                    )
                    .limit(1)
                )
            trace_context["replayed_trace"] = already_terminal is not None
            explicitly_confirmed = (
                _trace_route_arguments(
                    kwargs, trace_fields={"confirmed": __confirmation_field}
                ).get("confirmed")
                is True
                if __confirmation_field
                else True
            )
            if (
                __operation.permission == "confirm"
                and __operation_phase == "execute"
                and explicitly_confirmed
                and already_terminal is None
            ):
                await record_operation_trace(
                    db,
                    enabled=True,
                    novel_id=novel_id,
                    owner_id=owner_id,
                    operation=__operation,
                    event_type="confirmed",
                    arguments=arguments,
                    actor_type="ui",
                    entrypoint="assistant.http",
                    call_id=trace_context["call_id"],
                    parent_call_id=trace_context.get("parent_call_id"),
                )
            try:
                result = await __endpoint(*args, **kwargs)
            except Exception as error:
                trace_context["failure_event"] = (
                    "outcome_unknown"
                    if __operation.transaction_mode == "multi_stage"
                    else "failed"
                )
                trace_context["error_code"] = getattr(
                    error, "code", "operation_http_failed"
                )
                raise
            trace_context["result"] = _trace_result(result)
            if __terminal_event == "restored" and already_terminal is None:
                reference = trace_context["result"]
                for part in __reversal_ref_field.split("."):
                    reference = (
                        reference.get(part) if isinstance(reference, dict) else None
                    )
                try:
                    async with db.begin_nested():
                        await record_reversal(
                            db,
                            trace_context=trace_context,
                            reference=reference,
                            original_op_ids=__reversal_op_ids,
                        )
                except Exception as trace_error:
                    trace_context["incomplete_count"] = (
                        trace_context.get("incomplete_count", 0) + 1
                    )
                    logger.warning(
                        "HTTP reversal trace unavailable op_id=%s error_type=%s",
                        __operation.op_id,
                        type(trace_error).__name__,
                    )
            if __operation.transaction_mode == "single_transaction":
                from sqlalchemy import select

                from modules.assistant.operation_trace_models import (
                    AssistantOperationTrace,
                )

                already_recorded = await db.scalar(
                    select(AssistantOperationTrace.id)
                    .where(
                        AssistantOperationTrace.novel_id == UUID(novel_id),
                        AssistantOperationTrace.owner_id == UUID(owner_id),
                        AssistantOperationTrace.op_id == __operation.op_id,
                        AssistantOperationTrace.call_id == UUID(trace_context["call_id"]),
                        AssistantOperationTrace.event_type.in_(
                            ("previewed", "executed", "outcome_unknown")
                            if __operation_phase == "prepare"
                            else ("executed", "outcome_unknown")
                        ),
                    )
                    .limit(1)
                )
                if already_recorded is None and not trace_context.get("replayed_trace"):
                    await record_operation_trace(
                        db,
                        enabled=True,
                        novel_id=novel_id,
                        owner_id=owner_id,
                        operation=__operation,
                        event_type=(
                            "previewed" if __operation_phase == "prepare" else "executed"
                        ),
                        arguments=arguments,
                        result=trace_context["result"],
                        actor_type="ui",
                        entrypoint="assistant.http",
                        call_id=trace_context["call_id"],
                        parent_call_id=trace_context.get("parent_call_id"),
                    )
            return result

        async def traced_route_app(
            scope, receive, send, *, __app=original_app, __operation=operation
        ):
            if scope.get("type") != "http":
                await __app(scope, receive, send)
                return
            trace_context = {
                "operation_id": __operation.op_id,
                "call_id": str(uuid4()),
                "parent_call_id": None,
            }
            token = bind_operation_trace_context(trace_context)
            status_code = None

            async def capture_status(message):
                nonlocal status_code
                if message.get("type") == "http.response.start":
                    status_code = message.get("status")
                    if trace_context.get("enabled") and status_code >= 400:
                        from core.database import get_manager

                        try:
                            manager = get_manager()
                            if manager.engine.sync_engine is not trace_context.get(
                                "business_engine"
                            ):
                                trace_context["terminal_trace_unavailable"] = True
                                trace_context["incomplete_count"] = (
                                    trace_context.get("incomplete_count", 0) + 1
                                )
                        except Exception as trace_error:
                            trace_context["terminal_trace_unavailable"] = True
                            trace_context["incomplete_count"] = (
                                trace_context.get("incomplete_count", 0) + 1
                            )
                            logger.warning(
                                "HTTP operation terminal trace manager unavailable "
                                "op_id=%s error_type=%s",
                                __operation.op_id,
                                type(trace_error).__name__,
                            )
                    if trace_context.get("incomplete_count"):
                        message = {
                            **message,
                            "headers": [
                                *(message.get("headers") or []),
                                (b"x-novelcraft-operation-trace-incomplete", b"true"),
                            ],
                        }
                await send(message)

            try:
                await __app(scope, receive, capture_status)
            except Exception as error:
                if trace_context.get("enabled"):
                    await _record_http_terminal(
                        trace_context,
                        __operation,
                        "failed"
                        if __operation.transaction_mode == "single_transaction"
                        else "outcome_unknown",
                        getattr(error, "code", "request_commit_failed"),
                    )
                raise
            else:
                if (
                    trace_context.get("enabled")
                    and status_code is not None
                    and status_code >= 400
                ):
                    await _record_http_terminal(
                        trace_context,
                        __operation,
                        trace_context.get("failure_event")
                        or (
                            "outcome_unknown"
                            if __operation.transaction_mode == "multi_stage"
                            else "failed"
                        ),
                        trace_context.get("error_code") or f"http_{status_code}",
                    )
                elif (
                    trace_context.get("enabled")
                    and __operation.transaction_mode == "multi_stage"
                    and not trace_context.get("replayed_trace")
                ):
                    await _record_http_terminal(
                        trace_context,
                        __operation,
                        "executed",
                        None,
                    )
            finally:
                reset_operation_trace_context(token)

        async def _record_http_terminal(trace_context, operation, event_type, error_code):
            if not trace_context.get("novel_id") or not trace_context.get("owner_id"):
                return
            from core.database import get_manager

            try:
                if trace_context.get("terminal_trace_unavailable"):
                    logger.warning(
                        "HTTP operation terminal trace skipped because the request "
                        "database differs from the background trace database op_id=%s",
                        operation.op_id,
                    )
                    return
                manager = get_manager()
                if manager.engine.sync_engine is not trace_context.get("business_engine"):
                    trace_context["incomplete_count"] = (
                        trace_context.get("incomplete_count", 0) + 1
                    )
                    logger.warning(
                        "HTTP operation terminal trace skipped because the request "
                        "database differs from the background trace database op_id=%s",
                        operation.op_id,
                    )
                    return
                async with manager.session_factory() as trace_db:
                    await record_operation_trace(
                        trace_db,
                        enabled=True,
                        novel_id=trace_context["novel_id"],
                        owner_id=trace_context["owner_id"],
                        operation=operation,
                        event_type=event_type,
                        arguments=trace_context.get("arguments"),
                        result=trace_context.get("result"),
                        error_code=error_code,
                        actor_type="ui",
                        entrypoint="assistant.http",
                        call_id=trace_context["call_id"],
                        parent_call_id=trace_context.get("parent_call_id"),
                    )
                    await trace_db.commit()
            except Exception as trace_error:
                trace_context["incomplete_count"] = (
                    trace_context.get("incomplete_count", 0) + 1
                )
                logger.warning(
                    "HTTP operation trace failed op_id=%s error_type=%s",
                    operation.op_id,
                    type(trace_error).__name__,
                )

        route.endpoint = traced_endpoint
        route.dependant.call = traced_endpoint
        route.app = traced_route_app
        route._trace_adapter_installed = True


_install_operation_trace_route_adapters(app)


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
