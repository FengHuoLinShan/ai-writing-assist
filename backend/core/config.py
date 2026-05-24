"""
全局配置管理

使用环境变量加载配置，支持 Pydantic BaseSettings。
通过 get_settings() 获取单例配置对象。

支持的配置项（环境变量名）：
- DATABASE_URL: PostgreSQL 连接字符串
- LLM_API_KEY: LLM 服务 API 密钥
- LLM_BASE_URL: LLM 服务基础地址
- LLM_MODEL: 默认模型名称
- EMBEDDING_DIM: embedding 向量维度（默认 1024）
- POOL_SIZE: 数据库连接池大小（默认 10）
- MAX_OVERFLOW: 数据库连接池最大溢出（默认 20）
- LOG_LEVEL: 日志级别（默认 INFO）
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Final

# 尝试加载 .env 文件（dev 环境）
_env_path = Path(__file__).resolve().parent.parent / ".env"
if _env_path.exists():
    with open(_env_path, encoding="utf-8") as _f:
        for _line in _f:
            _line = _line.strip()
            if not _line or _line.startswith("#") or "=" not in _line:
                continue
            _key, _value = _line.split("=", 1)
            _key, _value = _key.strip(), _value.strip().strip("\"'")
            if _key not in os.environ:
                os.environ[_key] = _value


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


@dataclass(frozen=True)
class Settings:
    """应用全局配置，不可变对象，通过 get_settings() 获取"""

    # --- 数据库 ---
    database_url: str = field(default_factory=lambda: _env(
        "DATABASE_URL",
        "postgresql+asyncpg://postgres:postgres@localhost:5432/novel_engine",
    ))
    pool_size: int = int(_env("POOL_SIZE", "10"))
    max_overflow: int = int(_env("MAX_OVERFLOW", "20"))
    echo_sql: bool = _env("ECHO_SQL", "false").lower() == "true"

    # --- LLM ---
    llm_api_key: str = field(default_factory=lambda: _env("LLM_API_KEY", ""))
    llm_base_url: str = field(default_factory=lambda: _env(
        "LLM_BASE_URL", "https://api.openai.com/v1",
    ))
    llm_model: str = field(default_factory=lambda: _env("LLM_MODEL", "gpt-4o"))
    llm_max_tokens: int = int(_env("LLM_MAX_TOKENS", "4096"))
    llm_timeout: int = int(_env("LLM_TIMEOUT", "60"))

    # --- Embedding ---
    embedding_dim: int = int(_env("EMBEDDING_DIM", "1024"))
    embedding_model: str = field(default_factory=lambda: _env(
        "EMBEDDING_MODEL", "text-embedding-3-large",
    ))

    # --- CORS ---
    allowed_origins: list[str] = field(default_factory=lambda: [
        o.strip() for o in _env("ALLOWED_ORIGINS", "*").split(",")
        if o.strip()
    ])

    # --- 应用 ---
    app_name: str = "ai-novel-structural-engine"
    app_version: str = "2.0.0"
    debug: bool = _env("DEBUG", "false").lower() == "true"
    log_level: str = field(default_factory=lambda: _env("LOG_LEVEL", "INFO"))

    # --- pgvector ---
    vector_index_type: str = field(default_factory=lambda: _env(
        "VECTOR_INDEX_TYPE", "hnsw",
    ))
    vector_distance: str = field(default_factory=lambda: _env(
        "VECTOR_DISTANCE", "vector_cosine_ops",
    ))


@lru_cache()
def get_settings() -> Settings:
    """获取全局配置单例（缓存避免重复创建）"""
    return Settings()  # noqa: F821


# 注意：不导出模块级配置常量。
# 模块级常量在 import 时立即求值，绕过 lru_cache，导致测试重置 Settings 时仍使用旧值。
# 调用方应使用 get_settings().database_url / get_settings().embedding_dim 获取。
# （Bug L2: 移除 import 时求值的模块级常量）
