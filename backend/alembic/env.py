"""
Alembic 迁移环境配置

支持异步 PostgreSQL + pgvector。
"""

import os
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import pool

from alembic import context

# Alembic Config 对象
config = context.config

# 日志配置
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 导入所有 ORM 模型以注册到 Base.metadata
import infrastructure.tasks.models  # noqa: E402, F401

# character 模块已删除，模型在 modules.world.models
import modules.imports.models  # noqa: E402, F401
import modules.memory.models  # noqa: E402, F401
import modules.outline.models  # noqa: E402, F401

# 显式导入所有模块的模型，确保 alembic autogenerate 能检测到所有表
import modules.project.models  # noqa: E402, F401
import modules.rag.models  # noqa: E402, F401
import modules.world.map_models  # noqa: E402, F401
import modules.world.models  # noqa: E402, F401
import modules.writing.models  # noqa: E402, F401
from core.base import Base  # noqa: E402

target_metadata = Base.metadata


def _database_url() -> str:
    """Return the runtime database URL, falling back to alembic.ini."""
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key.strip() == "DATABASE_URL" and "DATABASE_URL" not in os.environ:
                os.environ["DATABASE_URL"] = value.strip().strip("\"'")
                break
    return os.environ.get("DATABASE_URL", config.get_main_option("sqlalchemy.url"))


def run_migrations_offline() -> None:
    """离线迁移：输出 SQL 脚本，不连接数据库"""
    url = _database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    """在线迁移：连接数据库执行迁移"""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """在线迁移：使用同步 psycopg2 连接"""
    from sqlalchemy import create_engine

    sync_url = _database_url().replace(
        "postgresql+asyncpg://",
        "postgresql+psycopg2://",
    )

    connectable = create_engine(sync_url, poolclass=pool.NullPool)
    with connectable.connect() as connection:
        do_run_migrations(connection)
    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
