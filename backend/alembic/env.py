"""
Alembic 迁移环境配置

支持异步 PostgreSQL + pgvector。
"""

import os
from logging.config import fileConfig
from typing import Any

from sqlalchemy import JSON, inspect, pool, text
from sqlalchemy.dialects.postgresql import JSONB

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


# These PostgreSQL-only indexes are intentionally owned by explicit migrations.
# Alembic cannot faithfully reconstruct expression, partial, trigram, or vector
# indexes from the portable ORM metadata, so comparison validates their presence
# separately and excludes only these known names from remove-index suggestions.
MIGRATION_MANAGED_INDEXES: dict[str, set[str]] = {
    "core_entities": {
        "ix_core_entities_auto_ingested_recent",
        "ix_core_entities_embedding_hnsw",
        "ix_core_entities_name",
        "ix_core_entities_search_trgm",
    },
    "delta_log": {"ix_delta_log_scene_index"},
    "entity_relations": {"uq_entity_relations_canonical_edge"},
    "events": {"ix_events_timeline_order"},
    "imported_chapters": {"ix_imported_chapters_novel"},
    "map_location_bindings": {"ix_map_binding_center"},
    "map_configs": {"uq_map_config_top_level_name"},
    "memory_events": {"ix_memory_events_novel_chapter"},
    "memory_snapshots": {"ix_memory_snapshots_novel_chapter"},
    "projects": {"ix_projects_deleted_at"},
    "rag_chunks": {
        "ix_rag_chunks_chapter_order",
        "ix_rag_chunks_embedding_hnsw",
        "ix_rag_chunks_source",
        "uq_rag_chunks_chapter_text_key",
        "uq_rag_chunks_object_source_key",
    },
    "reader_reveal_policies": {"ix_reader_reveal_null_chapter"},
    "text_archive": {"ix_text_archive_scene"},
    "writing_conflict_items": {"ix_writing_conflict_items_check"},
    "writing_drafts": {"ix_writing_drafts_chapter"},
}


def _is_schema_comparison() -> bool:
    cmd_opts = getattr(config, "cmd_opts", None)
    command = getattr(cmd_opts, "cmd", None)
    command_fn = command[0] if isinstance(command, tuple) and command else None
    return getattr(command_fn, "__name__", "") in {"check", "revision"}


def _include_schema_object(
    obj: Any,
    name: str | None,
    type_: str,
    reflected: bool,
    compare_to: Any,
) -> bool:
    del compare_to
    if type_ != "index" or not reflected or not name:
        return True
    table_name = getattr(getattr(obj, "table", None), "name", None)
    return name not in MIGRATION_MANAGED_INDEXES.get(str(table_name), set())


def _compare_schema_type(
    context: Any,
    inspected_column: Any,
    metadata_column: Any,
    inspected_type: Any,
    metadata_type: Any,
) -> bool | None:
    del context, inspected_column, metadata_column
    if isinstance(inspected_type, JSON | JSONB) and isinstance(
        metadata_type,
        JSON | JSONB,
    ):
        return False
    return None


def _validate_migration_managed_indexes(connection: Any) -> None:
    inspector = inspect(connection)
    tables = set(inspector.get_table_names())
    missing: list[str] = []
    for table_name, expected in MIGRATION_MANAGED_INDEXES.items():
        if table_name not in tables:
            continue
        actual = {index["name"] for index in inspector.get_indexes(table_name)}
        missing.extend(
            f"{table_name}.{index_name}"
            for index_name in sorted(expected - actual)
        )
    if missing:
        raise RuntimeError(
            "Missing migration-managed PostgreSQL indexes: " + ", ".join(missing)
        )


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

    schema_comparison = _is_schema_comparison()
    supports_comments = connection.dialect.supports_comments
    if schema_comparison:
        _validate_migration_managed_indexes(connection)
        # Column/table comments are documentation, not a runtime schema contract.
        # Disabling comment comparison avoids hundreds of false-positive changes
        # from the squashed demo baseline while explicit migrations still execute
        # comment DDL normally.
        connection.dialect.supports_comments = False
    try:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=_compare_schema_type,
            # ORM defaults are primarily application-side; PostgreSQL server
            # defaults remain migration-owned and are intentionally not compared.
            compare_server_default=False,
            include_object=_include_schema_object,
        )

        with context.begin_transaction():
            context.run_migrations()
    finally:
        connection.dialect.supports_comments = supports_comments


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
