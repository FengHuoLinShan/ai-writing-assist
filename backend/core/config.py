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
- LOG_LEVEL: 日志级别（默认 INFO）
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path


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
    return float(value)


_LOCAL_ENVS = {"development", "test", "local"}


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
    pool_size: int = int(_env("POOL_SIZE", "10"))
    max_overflow: int = int(_env("MAX_OVERFLOW", "20"))
    echo_sql: bool = _env("ECHO_SQL", "false").lower() == "true"

    # --- LLM ---
    # Business LLM profile fields are DB-backed (project/global settings), not env-backed.
    # These legacy attributes remain for old helpers and explicit test construction.
    llm_api_key: str = ""
    llm_base_url: str = "https://api.deepseek.com"
    llm_model: str = "deepseek-v4-flash"
    llm_max_tokens: int = 4096
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

    # --- Embedding ---
    embedding_dim: int = int(_env("EMBEDDING_DIM", "768"))
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
    inference_worker_timeout: float = float(_env("INFERENCE_WORKER_TIMEOUT", "30.0"))
    inference_worker_max_batch: int = int(_env("INFERENCE_WORKER_MAX_BATCH", "64"))
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
    llm_settings_encryption_key: str = field(
        default_factory=lambda: _env("LLM_SETTINGS_ENCRYPTION_KEY", "")
    )

    # --- 重排序 ---
    reranker_enabled: bool = _env("RERANKER_ENABLED", "false").lower() == "true"

    # --- 运行环境 ---
    app_env: str = field(default_factory=lambda: _env("APP_ENV", "development"))

    # --- 应用 ---
    app_name: str = "ai-novel-structural-engine"
    app_version: str = "2.0.0"
    debug: bool = _env("DEBUG", "false").lower() == "true"
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
