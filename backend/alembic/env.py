"""
Alembic 迁移环境配置

支持异步 PostgreSQL + pgvector。
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

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
import modules.memory.models  # noqa: F401
import modules.timeline.models  # noqa: F401
import modules.outline.models  # noqa: F401
import modules.rag.models  # noqa: F401
import modules.review.models  # noqa: F401
import modules.writing.models  # noqa: F401
import infrastructure.tasks.models  # noqa: F401

target_metadata = Base.metadata


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


async def run_async_migrations() -> None:
    """异步在线迁移"""
    from sqlalchemy import create_engine

    # Alembic 需要同步连接来执行迁移
    # 使用 psycopg2 作为同步 driver
    config_section = config.get_section(config.config_ini_section)
    sync_url = config_section["sqlalchemy.url"].replace(
        "postgresql+asyncpg://",
        "postgresql+psycopg2://",
    )
    config_section["sqlalchemy.url"] = sync_url

    connectable = async_engine_from_config(
        config_section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """运行在线迁移"""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
