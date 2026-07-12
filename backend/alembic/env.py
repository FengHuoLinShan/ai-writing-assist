"""
Alembic 迁移环境配置

支持异步 PostgreSQL + pgvector。
"""

import os
from logging.config import fileConfig

from sqlalchemy import inspect, pool, text

from alembic import context

# Alembic Config 对象
config = context.config

# 日志配置
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 导入所有 ORM 模型以注册到 Base.metadata
import infrastructure.tasks.models  # noqa: E402, F401

# character 模块已删除，模型在 modules.world.models
import modules.context.models  # noqa: E402, F401
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
from core.config import load_env_file  # noqa: E402

target_metadata = Base.metadata

load_env_file()


def _ensure_version_table_capacity(connection) -> None:
    """Allow descriptive revision IDs longer than Alembic's varchar(32) default."""
    if connection.dialect.name != "postgresql":
        return

    inspector = inspect(connection)
    if "alembic_version" not in inspector.get_table_names():
        connection.execute(
            text(
                "CREATE TABLE alembic_version ("
                "version_num VARCHAR(255) NOT NULL, "
                "CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)"
                ")"
            )
        )
        connection.commit()
        return

    columns = {
        column["name"]: column for column in inspector.get_columns("alembic_version")
    }
    version_column = columns.get("version_num")
    column_type = version_column["type"] if version_column else None
    if getattr(column_type, "length", None) and column_type.length < 255:
        connection.execute(
            text("ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(255)")
        )

    if connection.in_transaction():
        connection.commit()


def _database_url() -> str:
    """Return the runtime database URL, falling back to alembic.ini."""
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
    _ensure_version_table_capacity(connection)

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
