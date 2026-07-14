from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from uuid import uuid4

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import URL, Engine, make_url

from alembic import command
from core.base import Base
from tests.e2e.config import DATABASE_URL


@contextmanager
def _disposable_database() -> Iterator[tuple[URL, Engine]]:
    sync_url = DATABASE_URL.replace(
        "postgresql+asyncpg://",
        "postgresql+psycopg2://",
    )
    admin_engine = create_engine(sync_url, isolation_level="AUTOCOMMIT")
    database_name = f"migration_regression_{uuid4().hex}"
    quoted_database = admin_engine.dialect.identifier_preparer.quote(
        database_name
    )
    migration_url = make_url(DATABASE_URL).set(database=database_name)
    target_engine = create_engine(
        migration_url.render_as_string(hide_password=False).replace(
            "postgresql+asyncpg://",
            "postgresql+psycopg2://",
        )
    )

    with admin_engine.connect() as connection:
        connection.exec_driver_sql(f"CREATE DATABASE {quoted_database}")

    try:
        yield migration_url, target_engine
    finally:
        target_engine.dispose()
        with admin_engine.connect() as connection:
            connection.exec_driver_sql(f"DROP DATABASE {quoted_database}")
        admin_engine.dispose()


def _migration_config(monkeypatch, migration_url: URL) -> tuple[Config, set[str]]:
    monkeypatch.setenv(
        "DATABASE_URL",
        migration_url.render_as_string(hide_password=False),
    )
    config = Config("alembic.ini")
    expected_heads = set(ScriptDirectory.from_config(config).get_heads())
    assert len(expected_heads) == 1
    return config, expected_heads


def _assert_current_schema(engine: Engine, expected_heads: set[str]) -> None:
    with engine.connect() as connection:
        inspector = inspect(connection)
        tables = set(inspector.get_table_names())
        missing_columns = {
            table.name: sorted(
                set(table.columns.keys())
                - {
                    column["name"]
                    for column in inspector.get_columns(table.name)
                }
            )
            for table in Base.metadata.sorted_tables
            if table.name in tables
        }
        missing_columns = {
            table_name: columns
            for table_name, columns in missing_columns.items()
            if columns
        }
        current_heads = set(
            connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalars()
        )

    assert current_heads == expected_heads
    assert set(Base.metadata.tables) <= tables
    assert missing_columns == {}
    assert "smart_dedup_workbench_decisions" in tables
    assert "map_layer_nodes" in tables


def test_empty_postgresql_database_upgrades_from_base_to_head(
    monkeypatch,
) -> None:
    """Exercise every revision in a disposable database."""
    with _disposable_database() as (migration_url, target_engine):
        config, expected_heads = _migration_config(monkeypatch, migration_url)

        command.upgrade(config, "head")

        _assert_current_schema(target_engine, expected_heads)


def test_old_dynamic_baseline_objects_do_not_break_upgrade(monkeypatch) -> None:
    """Keep databases initialized by the former live-ORM baseline upgradeable."""
    with _disposable_database() as (migration_url, target_engine):
        config, expected_heads = _migration_config(monkeypatch, migration_url)
        with target_engine.begin() as connection:
            connection.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS vector")
            connection.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS pg_trgm")
            Base.metadata.create_all(connection)

        command.stamp(config, "20260703_scene_chapter_links")
        command.upgrade(config, "head")

        _assert_current_schema(target_engine, expected_heads)
