from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from uuid import uuid4

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import MetaData, Table, create_engine, inspect, select, text
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
        interaction_journey_unique_constraints = {
            tuple(item["column_names"])
            for item in inspector.get_unique_constraints("interaction_journeys")
        }
        interaction_preference_unique_constraints = {
            tuple(item["column_names"])
            for item in inspector.get_unique_constraints(
                "interaction_account_preferences"
            )
        }
        interaction_journey_indexes = {
            item["name"]: item
            for item in inspector.get_indexes("interaction_journeys")
        }
        interaction_preference_indexes = {
            item["name"]: item
            for item in inspector.get_indexes("interaction_account_preferences")
        }

    assert current_heads == expected_heads
    assert set(Base.metadata.tables) <= tables
    assert missing_columns == {}
    assert "smart_dedup_workbench_decisions" in tables
    assert "map_layer_nodes" in tables
    assert ("novel_id",) not in interaction_journey_unique_constraints
    assert ("owner_id",) not in interaction_preference_unique_constraints
    assert interaction_journey_indexes["ix_interaction_journeys_novel_id"][
        "unique"
    ]
    assert interaction_preference_indexes[
        "ix_interaction_account_preferences_owner_id"
    ]["unique"]


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


def test_account_llm_migration_removes_project_keys_in_postgresql(
    monkeypatch,
) -> None:
    """Prove the JSON data migration against the real PostgreSQL type."""

    with _disposable_database() as (migration_url, target_engine):
        config, _expected_heads = _migration_config(monkeypatch, migration_url)
        command.upgrade(config, "20260724_task_owners")

        owner_id = uuid4()
        project_id = uuid4()
        now = datetime.now(UTC)
        legacy_settings = {
            "theme": "dark",
            "llm": {
                "provider_id": "deepseek",
                "model": "legacy-model",
                "api_key": {"ciphertext": "legacy-secret"},
                "api_keys_by_provider": {
                    "deepseek": {"ciphertext": "other-legacy-secret"}
                },
            },
            "deep_import": {"global": {"structured_max_fix_attempts": 3}},
        }
        with target_engine.begin() as connection:
            metadata = MetaData()
            accounts = Table("accounts", metadata, autoload_with=connection)
            projects = Table("projects", metadata, autoload_with=connection)
            connection.execute(
                accounts.insert().values(
                    id=owner_id,
                    status="active",
                    support_code=f"MIG-{owner_id.hex[:12]}",
                    created_at=now,
                    updated_at=now,
                )
            )
            project_values = {
                "id": project_id,
                "owner_id": owner_id,
                "title": "legacy-key-project",
                "language": "zh",
                "default_reveal_policy": "author_safe",
                "settings": legacy_settings,
                "created_at": now,
                "updated_at": now,
            }
            if "project_kind" in projects.c:
                project_values["project_kind"] = "author"
            connection.execute(projects.insert().values(**project_values))

        command.upgrade(config, "head")

        with target_engine.connect() as connection:
            projects = Table(
                "projects",
                MetaData(),
                autoload_with=connection,
            )
            stored = connection.execute(
                select(projects.c.settings).where(projects.c.id == project_id)
            ).scalar_one()

        assert stored["theme"] == "dark"
        assert stored["deep_import"] == legacy_settings["deep_import"]
        assert stored["llm"] == {
            "provider_id": "deepseek",
            "model": "legacy-model",
        }
