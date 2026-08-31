"""
全局配置管理

使用环境变量加载配置，支持 Pydantic BaseSettings。
通过 get_settings() 获取单例配置对象。

支持的配置项（环境变量名）：
- DATABASE_URL: PostgreSQL 连接字符串
- LLM_PROXY_URL / LLM_TRUST_ENV: LLM HTTP 代理配置
- LLM_HEALTH_REQUIRED / LLM_RETRY_*: LLM health 和重试运行参数
- EMBEDDING_DIM: embedding 向量维度（默认 768）
- IMPORT_MAX_CHAPTERS: 单次导入/深度导入最大章节数（默认 1000）
- POOL_SIZE: 数据库连接池大小（默认 10）
- MAX_OVERFLOW: 数据库连接池最大溢出（默认 20）
- DEBUG: 应用调试模式（默认 false）
- LOG_LEVEL: 日志级别（默认 INFO）
- HTTP_RATE_LIMIT_*: 进程级 HTTP direct-peer 限流配置
- LLM_RATE_LIMIT_PER_MINUTE: 进程级 LLM provider 限流配置
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from functools import lru_cache
from ipaddress import ip_address
from pathlib import Path
from urllib.parse import SplitResult, urlsplit

from shared.constants import DEFAULT_LLM_MAX_TOKENS


def load_env_file(env_path: Path | None = None) -> None:
    """Load backend .env values without overriding existing environment."""
    path = env_path or Path(__file__).resolve().parent.parent / ".env"
    if not path.exists():
        return

    with open(path, encoding="utf-8") as env_file:
        for raw_line in env_file:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key, value = key.strip(), value.strip().strip("\"'")
            if key not in os.environ:
                os.environ[key] = value


# 尝试加载 .env 文件（dev 环境）
load_env_file()


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def _env_bool(key: str, default: bool = False) -> bool:
    value = os.environ.get(key)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(key: str, default: int) -> int:
    value = os.environ.get(key)
    if value is None:
        return default
    return int(value)


def _env_float(key: str, default: float) -> float:
    value = os.environ.get(key)
    if value is None:
        return default
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError(f"{key} must be finite")
    return parsed


_LOCAL_ENVS = {"development", "test", "local"}


def _default_auth_mode() -> str:
    explicit = _env("AUTH_MODE", "").strip().lower()
    if explicit:
        return explicit
    return "closed_test" if _env("APP_ACCESS_TOKEN", "").strip() else "local"


def _parse_auth_url(name: str, value: str) -> SplitResult:
    try:
        parsed = urlsplit(value)
        _ = parsed.port
    except ValueError:
        raise RuntimeError(f"{name} must be a valid URL") from None
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise RuntimeError(f"{name} must be a valid HTTP(S) URL")
    return parsed


def _is_loopback_hostname(hostname: str) -> bool:
    normalized = hostname.strip().lower().rstrip(".")
    if normalized == "localhost" or normalized.endswith(".localhost"):
        return True
    try:
        return ip_address(normalized).is_loopback
    except ValueError:
        return False


def validate_map_atlas_s3_endpoint_url(value: str) -> str:
    """Allow AWS defaults, HTTPS, local HTTP, and the production MinIO service."""
    cleaned = value.strip()
    if not cleaned:
        return ""
    parsed = _parse_auth_url("MAP_ATLAS_S3_ENDPOINT_URL", cleaned)
    if (
        any(ord(character) <= 0x20 for character in cleaned)
        or parsed.username is not None
        or parsed.password is not None
        or "?" in cleaned
        or "#" in cleaned
    ):
        raise RuntimeError(
            "MAP_ATLAS_S3_ENDPOINT_URL must not include userinfo, query, or fragment"
        )
    app_env = _env("APP_ENV", "development").strip().lower()
    local_http = app_env != "production" and (parsed.hostname or "").lower() in {
        "localhost",
        "127.0.0.1",
        "::1",
    }
    production_minio = (
        app_env == "production"
        and cleaned == "http://minio:9000"
    )
    if parsed.scheme.lower() == "http" and not (local_http or production_minio):
        raise RuntimeError(
            "MAP_ATLAS_S3_ENDPOINT_URL must use https except for local development"
        )
    return cleaned


def _validate_auth_https_url(
    name: str,
    value: str,
    *,
    allow_local_loopback: bool,
) -> None:
    parsed = _parse_auth_url(name, value)
    if parsed.scheme.lower() == "https":
        return
    if (
        allow_local_loopback
        and parsed.scheme.lower() == "http"
        and _is_loopback_hostname(parsed.hostname or "")
    ):
        return
    raise RuntimeError(f"{name} must use https")


def validate_cors_origins(app_env: str, origins: list[str]) -> None:
    """Reject unsafe wildcard CORS configurations."""
    normalized_env = app_env.strip().lower()
    allows_wildcard = not origins or "*" in origins
    if "*" in origins and len(origins) > 1:
        raise RuntimeError("CORS wildcard origins cannot be mixed with explicit origins")
    if allows_wildcard and normalized_env not in _LOCAL_ENVS:
        raise RuntimeError(
            "CORS wildcard origins are only allowed in development, test, or local"
        )


def validate_app_access_token_config(app_env: str, app_access_token: str) -> None:
    """Require a deployment access token outside local runtimes."""
    normalized_env = app_env.strip().lower()
    if normalized_env not in _LOCAL_ENVS and not app_access_token.strip():
        raise RuntimeError(
            "APP_ACCESS_TOKEN must be configured outside development, test, or local"
        )


def validate_auth_config(settings: Settings) -> None:
    """Validate mutually exclusive local, closed-test, and public auth modes."""
    mode = settings.auth_mode.strip().lower()
    if mode not in {"local", "closed_test", "public"}:
        raise RuntimeError("AUTH_MODE must be local, closed_test, or public")
    is_local_env = settings.app_env.strip().lower() in _LOCAL_ENVS
    if mode == "local" and not is_local_env:
        raise RuntimeError("AUTH_MODE=local is only allowed in local runtimes")
    if mode == "closed_test" and not is_local_env and not settings.app_access_token:
        raise RuntimeError("APP_ACCESS_TOKEN is required for AUTH_MODE=closed_test")
    if mode != "public":
        return
    if settings.debug:
        raise RuntimeError("DEBUG must be false when AUTH_MODE=public")
    if len(settings.auth_secret_key) < 32:
        raise RuntimeError("AUTH_SECRET_KEY must contain at least 32 characters")
    _validate_auth_https_url(
        "PUBLIC_BASE_URL",
        settings.public_base_url,
        allow_local_loopback=is_local_env,
    )
    required_smtp = {
        "SMTP_HOST": settings.smtp_host,
        "SMTP_USERNAME": settings.smtp_username,
        "SMTP_PASSWORD": settings.smtp_password,
        "SMTP_FROM": settings.smtp_from,
        "SUPPORT_EMAIL": settings.support_email,
    }
    missing = [name for name, value in required_smtp.items() if not value.strip()]
    if missing:
        raise RuntimeError(
            "Public auth requires configuration: " + ", ".join(sorted(missing))
        )
    if settings.smtp_tls_mode not in {"starttls", "ssl"}:
        raise RuntimeError("SMTP_TLS_MODE must be starttls or ssl")
    if settings.authing_wechat_enabled:
        required_authing = {
            "AUTHING_ISSUER": settings.authing_issuer,
            "AUTHING_CLIENT_ID": settings.authing_client_id,
            "AUTHING_CLIENT_SECRET": settings.authing_client_secret,
            "AUTHING_REDIRECT_URI": settings.authing_redirect_uri,
        }
        missing = [name for name, value in required_authing.items() if not value.strip()]
        if missing:
            raise RuntimeError(
                "Enabled Authing WeChat requires: " + ", ".join(sorted(missing))
            )
        _validate_auth_https_url(
            "AUTHING_ISSUER",
            settings.authing_issuer,
            allow_local_loopback=is_local_env,
        )
        _validate_auth_https_url(
            "AUTHING_REDIRECT_URI",
            settings.authing_redirect_uri,
            allow_local_loopback=is_local_env,
        )


def validate_http_rate_limit_config(
    app_env: str,
    requests_per_minute: int,
    burst: int,
    max_clients: int,
) -> None:
    """Require a valid positive HTTP limiter outside local runtimes."""
    if requests_per_minute < 0:
        raise RuntimeError("HTTP_RATE_LIMIT_PER_MINUTE must be non-negative")
    if burst < 0:
        raise RuntimeError("HTTP_RATE_LIMIT_BURST must be non-negative")
    if max_clients <= 0:
        raise RuntimeError("HTTP_RATE_LIMIT_MAX_CLIENTS must be positive")
    if requests_per_minute > 0 and burst == 0:
        raise RuntimeError(
            "HTTP_RATE_LIMIT_BURST must be positive when HTTP rate limiting is enabled"
        )
    if app_env.strip().lower() not in _LOCAL_ENVS and requests_per_minute == 0:
        raise RuntimeError(
            "HTTP_RATE_LIMIT_PER_MINUTE must be positive outside "
            "development, test, or local"
        )


def validate_llm_rate_limit_config(app_env: str, requests_per_minute: int) -> None:
    """Validate the optional process-local LLM request limiter."""
    if requests_per_minute < 0:
        raise RuntimeError("LLM_RATE_LIMIT_PER_MINUTE must be non-negative")


@dataclass(frozen=True)
class Settings:
    """应用全局配置，不可变对象，通过 get_settings() 获取"""

    # --- 数据库 ---
    database_url: str = field(
        default_factory=lambda: _env(
            "DATABASE_URL",
            "postgresql+asyncpg://novelist:novel_dev_pass@localhost:5207/ai_novel_engine",
        )
    )
    pool_size: int = field(default_factory=lambda: _env_int("POOL_SIZE", 10))
    max_overflow: int = field(default_factory=lambda: _env_int("MAX_OVERFLOW", 20))
    echo_sql: bool = field(default_factory=lambda: _env_bool("ECHO_SQL", False))

    # --- LLM ---
    # Business LLM profile fields are DB-backed (project/global settings), not env-backed.
    # These legacy attributes remain for old helpers and explicit test construction.
    llm_api_key: str = ""
    llm_base_url: str = "https://api.deepseek.com"
    llm_model: str = "deepseek-v4-flash"
    llm_max_tokens: int = DEFAULT_LLM_MAX_TOKENS
    llm_timeout: int = 180
    llm_trust_env: bool = field(default_factory=lambda: _env_bool("LLM_TRUST_ENV", False))
    llm_proxy_url: str = field(default_factory=lambda: _env("LLM_PROXY_URL", ""))
    llm_health_required: bool = field(
        default_factory=lambda: _env_bool("LLM_HEALTH_REQUIRED", True)
    )
    rag_prewarm_on_startup: bool = field(
        default_factory=lambda: _env_bool("RAG_PREWARM_ON_STARTUP", False)
    )
    llm_retry_max_attempts: int = field(
        default_factory=lambda: _env_int("LLM_RETRY_MAX_ATTEMPTS", 3)
    )
    llm_retry_base_delay: float = field(
        default_factory=lambda: _env_float("LLM_RETRY_BASE_DELAY", 1.0)
    )
    llm_retry_max_delay: float = field(
        default_factory=lambda: _env_float("LLM_RETRY_MAX_DELAY", 60.0)
    )
    llm_max_concurrent_requests: int = field(
        default_factory=lambda: _env_int("LLM_MAX_CONCURRENT_REQUESTS", 8)
    )
    llm_rate_limit_per_minute: int = field(
        default_factory=lambda: _env_int("LLM_RATE_LIMIT_PER_MINUTE", 0)
    )
    llm_circuit_breaker_failure_threshold: int = field(
        default_factory=lambda: _env_int("LLM_CIRCUIT_BREAKER_FAILURE_THRESHOLD", 5)
    )
    llm_circuit_breaker_reset_seconds: float = field(
        default_factory=lambda: _env_float("LLM_CIRCUIT_BREAKER_RESET_SECONDS", 60.0)
    )

    # --- AI 地图册私有对象存储 ---
    map_atlas_s3_bucket: str = field(
        default_factory=lambda: _env("MAP_ATLAS_S3_BUCKET", "")
    )
    world_object_s3_bucket: str = field(
        default_factory=lambda: _env("WORLD_OBJECT_S3_BUCKET", "")
    )
    map_atlas_s3_region: str = field(
        default_factory=lambda: _env("MAP_ATLAS_S3_REGION", "us-east-1")
    )
    map_atlas_s3_endpoint_url: str = field(
        default_factory=lambda: _env("MAP_ATLAS_S3_ENDPOINT_URL", "")
    )
    map_atlas_s3_access_key_id: str = field(
        default_factory=lambda: _env("MAP_ATLAS_S3_ACCESS_KEY_ID", "")
    )
    map_atlas_s3_secret_access_key: str = field(
        default_factory=lambda: _env("MAP_ATLAS_S3_SECRET_ACCESS_KEY", "")
    )
    map_atlas_s3_force_path_style: bool = field(
        default_factory=lambda: _env_bool("MAP_ATLAS_S3_FORCE_PATH_STYLE", False)
    )

    # --- Embedding ---
    embedding_dim: int = field(default_factory=lambda: _env_int("EMBEDDING_DIM", 768))
    embedding_model: str = field(
        default_factory=lambda: _env(
            "EMBEDDING_MODEL",
            "bge-base-zh-v1.5",
        )
    )
    embedding_provider: str = field(
        default_factory=lambda: _env(
            "EMBEDDING_PROVIDER",
            "bge_onnx",
        )
    )
    embedding_base_url: str = field(
        default_factory=lambda: _env("EMBEDDING_BASE_URL", "")
    )
    embedding_api_key: str = field(default_factory=lambda: _env("EMBEDDING_API_KEY", ""))

    # --- BGE / ONNX Inference ---
    bge_onnx_model_path: str = field(
        default_factory=lambda: _env(
            "BGE_ONNX_MODEL_PATH",
            "BAAI/bge-base-zh-v1.5",
        )
    )
    bge_onnx_device: str = field(default_factory=lambda: _env("BGE_ONNX_DEVICE", "cpu"))
    bge_onnx_quantization: str = field(
        default_factory=lambda: _env(
            "BGE_ONNX_QUANTIZATION",
            "int8",
        )
    )
    inference_worker_timeout: float = field(
        default_factory=lambda: _env_float("INFERENCE_WORKER_TIMEOUT", 30.0)
    )
    inference_worker_startup_timeout: float = field(
        default_factory=lambda: _env_float(
            "INFERENCE_WORKER_STARTUP_TIMEOUT",
            300.0,
        )
    )
    inference_worker_max_batch: int = field(
        default_factory=lambda: _env_int("INFERENCE_WORKER_MAX_BATCH", 64)
    )
    inference_worker_queue_maxsize: int = field(
        default_factory=lambda: _env_int("INFERENCE_WORKER_QUEUE_MAXSIZE", 200)
    )
    embedding_batch_queue_delay_ms: int = field(
        default_factory=lambda: _env_int("EMBEDDING_BATCH_QUEUE_DELAY_MS", 5)
    )
    embedding_batch_queue_max_items: int = field(
        default_factory=lambda: _env_int(
            "EMBEDDING_BATCH_QUEUE_MAX_ITEMS",
            _env_int("INFERENCE_WORKER_MAX_BATCH", 64),
        )
    )
    embedding_batch_queue_timeout_seconds: float = field(
        default_factory=lambda: _env_float("EMBEDDING_BATCH_QUEUE_TIMEOUT_SECONDS", 30.0)
    )

    # --- Async task worker ---
    task_worker_max_concurrent_tasks: int = field(
        default_factory=lambda: _env_int("TASK_WORKER_MAX_CONCURRENT_TASKS", 2)
    )

    # --- Import ---
    import_max_chapters: int = field(
        default_factory=lambda: _env_int("IMPORT_MAX_CHAPTERS", 1000)
    )

    # --- CORS ---
    allowed_origins: list[str] = field(
        default_factory=lambda: [
            o.strip() for o in _env("ALLOWED_ORIGINS", "*").split(",") if o.strip()
        ]
    )

    # --- Deployment access / secrets ---
    app_access_token: str = field(default_factory=lambda: _env("APP_ACCESS_TOKEN", ""))
    auth_mode: str = field(default_factory=_default_auth_mode)
    auth_secret_key: str = field(default_factory=lambda: _env("AUTH_SECRET_KEY", ""))
    public_base_url: str = field(
        default_factory=lambda: _env("PUBLIC_BASE_URL", "http://localhost:8000")
    )
    session_idle_seconds: int = field(
        default_factory=lambda: _env_int("SESSION_IDLE_SECONDS", 7 * 24 * 3600)
    )
    session_absolute_seconds: int = field(
        default_factory=lambda: _env_int("SESSION_ABSOLUTE_SECONDS", 30 * 24 * 3600)
    )
    reauth_seconds: int = field(
        default_factory=lambda: _env_int("REAUTH_SECONDS", 10 * 60)
    )
    smtp_host: str = field(default_factory=lambda: _env("SMTP_HOST", ""))
    smtp_port: int = field(default_factory=lambda: _env_int("SMTP_PORT", 587))
    smtp_tls_mode: str = field(
        default_factory=lambda: _env("SMTP_TLS_MODE", "starttls").strip().lower()
    )
    smtp_username: str = field(default_factory=lambda: _env("SMTP_USERNAME", ""))
    smtp_password: str = field(default_factory=lambda: _env("SMTP_PASSWORD", ""))
    smtp_from: str = field(default_factory=lambda: _env("SMTP_FROM", ""))
    smtp_timeout_seconds: int = field(
        default_factory=lambda: _env_int("SMTP_TIMEOUT_SECONDS", 10)
    )
    support_email: str = field(default_factory=lambda: _env("SUPPORT_EMAIL", ""))
    terms_version: str = field(
        default_factory=lambda: _env("TERMS_VERSION", "2026-07-23")
    )
    privacy_version: str = field(
        default_factory=lambda: _env("PRIVACY_VERSION", "2026-07-23")
    )
    authing_wechat_enabled: bool = field(
        default_factory=lambda: _env_bool("AUTHING_WECHAT_ENABLED", False)
    )
    authing_issuer: str = field(default_factory=lambda: _env("AUTHING_ISSUER", ""))
    authing_client_id: str = field(default_factory=lambda: _env("AUTHING_CLIENT_ID", ""))
    authing_client_secret: str = field(
        default_factory=lambda: _env("AUTHING_CLIENT_SECRET", "")
    )
    authing_redirect_uri: str = field(
        default_factory=lambda: _env("AUTHING_REDIRECT_URI", "")
    )
    http_rate_limit_per_minute: int = field(
        default_factory=lambda: _env_int("HTTP_RATE_LIMIT_PER_MINUTE", 0)
    )
    http_rate_limit_burst: int = field(
        default_factory=lambda: _env_int("HTTP_RATE_LIMIT_BURST", 60)
    )
    http_rate_limit_max_clients: int = field(
        default_factory=lambda: _env_int("HTTP_RATE_LIMIT_MAX_CLIENTS", 10_000)
    )
    llm_settings_encryption_key: str = field(
        default_factory=lambda: _env("LLM_SETTINGS_ENCRYPTION_KEY", "")
    )

    # --- 重排序 ---
    reranker_enabled: bool = field(
        default_factory=lambda: _env_bool("RERANKER_ENABLED", False)
    )
    rag_query_planner_enabled: bool = field(
        default_factory=lambda: _env_bool("RAG_QUERY_PLANNER_ENABLED", False)
    )

    # --- 运行环境 ---
    app_env: str = field(default_factory=lambda: _env("APP_ENV", "development"))

    # --- 应用 ---
    app_name: str = "ai-novel-structural-engine"
    app_version: str = "2.0.0"
    debug: bool = field(default_factory=lambda: _env_bool("DEBUG", False))
    log_level: str = field(default_factory=lambda: _env("LOG_LEVEL", "INFO"))

    # --- pgvector ---
    vector_index_type: str = field(
        default_factory=lambda: _env(
            "VECTOR_INDEX_TYPE",
            "hnsw",
        )
    )
    vector_distance: str = field(
        default_factory=lambda: _env(
            "VECTOR_DISTANCE",
            "vector_cosine_ops",
        )
    )


@lru_cache
def get_settings() -> Settings:
    """获取全局配置单例（缓存避免重复创建）"""
    return Settings()  # noqa: F821


# 注意：不导出模块级配置常量。
# 模块级常量在 import 时立即求值，绕过 lru_cache，导致测试重置 Settings 时仍使用旧值。
# 调用方应使用 get_settings().database_url / get_settings().embedding_dim 获取。
# （Bug L2: 移除 import 时求值的模块级常量）
