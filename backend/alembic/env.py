"""
Alembic 迁移环境配置

支持异步 PostgreSQL + pgvector。
"""
# ruff: noqa: E402, I001

from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool

# Alembic Config 对象
config = context.config

# 日志配置
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 导入所有 ORM 模型以注册到 Base.metadata
from core.base import Base

# 显式导入所有模块的模型，确保 alembic autogenerate 能检测到所有表
import modules.project.models  # noqa: F401
import modules.world.models  # noqa: F401
import modules.character.models  # noqa: F401
import modules.geo.models  # noqa: F401
import modules.imports.models  # noqa: F401
import modules.memory.models  # noqa: F401
import modules.timeline.models  # noqa: F401
import modules.outline.models  # noqa: F401
import modules.rag.models  # noqa: F401
import modules.review.models  # noqa: F401
import modules.writing.models  # noqa: F401
import infrastructure.tasks.models  # noqa: F401

target_metadata = Base.metadata


def get_database_url() -> str:
    """Return migration database URL from runtime settings."""
    from core.config import get_settings

    return get_settings().database_url


config.set_main_option("sqlalchemy.url", get_database_url())


def run_migrations_offline() -> None:
    """离线迁移：输出 SQL 脚本，不连接数据库"""
    url = config.get_main_option("sqlalchemy.url")
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

    config_section = config.get_section(config.config_ini_section)
    sync_url = config_section["sqlalchemy.url"].replace(
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
