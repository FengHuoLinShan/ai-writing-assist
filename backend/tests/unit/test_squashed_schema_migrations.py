from __future__ import annotations

import hashlib
import importlib.util
import re
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

BACKEND_ROOT = Path(__file__).resolve().parents[2]
VERSIONS_ROOT = BACKEND_ROOT / "alembic" / "versions"


def _load_migration(filename: str):
    path = VERSIONS_ROOT / filename
    spec = importlib.util.spec_from_file_location(
        f"test_{path.stem}",
        path,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _create_frozen_sqlite_schema(connection: sa.Connection):
    baseline = _load_migration("20260703_squashed_current_schema.py")
    for statement in baseline._load_frozen_schema_statements("sqlite"):
        connection.exec_driver_sql(statement)
    return baseline


def _install_postgresql_compatibility_functions(connection: sa.Connection) -> None:
    raw_connection = connection.connection.driver_connection
    raw_connection.create_function(
        "md5",
        1,
        lambda value: hashlib.md5(str(value).encode()).hexdigest(),
    )
    raw_connection.create_function("now", 0, lambda: "2026-07-14 00:00:00")
    raw_connection.create_function("timezone", 2, lambda _zone, value: value)


def test_frozen_baseline_creates_only_revision_owned_schema() -> None:
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        baseline = _create_frozen_sqlite_schema(connection)
        inspector = sa.inspect(connection)

        assert inspector.get_table_names() == sorted(
            baseline._FROZEN_TABLES_IN_CREATE_ORDER
        )
        assert "smart_dedup_workbench_decisions" not in inspector.get_table_names()
        assert "map_layer_nodes" not in inspector.get_table_names()
        assert "global_llm_defaults" not in inspector.get_table_names()
        assert "world_bible_pages" in inspector.get_table_names()

        map_columns = {
            column["name"] for column in inspector.get_columns("map_configs")
        }
        assert "status" not in map_columns
        assert "archived_at" not in map_columns
        assert "editor_revision" not in map_columns


def test_frozen_snapshots_match_declared_tables_and_checksums() -> None:
    baseline = _load_migration("20260703_squashed_current_schema.py")
    expected_tables = list(baseline._FROZEN_TABLES_IN_CREATE_ORDER)

    for dialect_name in ("postgresql", "sqlite"):
        statements = baseline._load_frozen_schema_statements(dialect_name)
        actual_tables = [
            match.group(1)
            for statement in statements
            if (match := re.match(r"CREATE TABLE (\w+)", statement))
        ]
        assert actual_tables == expected_tables
        assert len(statements) == 234


def test_post_squash_migrations_tolerate_precreated_objects() -> None:
    smart_dedup = _load_migration("20260714_smart_dedup_workbench.py")
    map_editor = _load_migration("20260714_map_editor_layer_tree.py")
    map_floor = _load_migration("20260714_map_floor_paths.py")
    engine = sa.create_engine("sqlite://")

    with engine.begin() as connection:
        _install_postgresql_compatibility_functions(connection)
        _create_frozen_sqlite_schema(connection)
        operations = Operations(MigrationContext.configure(connection))
        smart_dedup.op = operations
        map_editor.op = operations
        map_floor.op = operations

        smart_dedup.upgrade()
        map_editor.upgrade()
        map_floor.upgrade()
        smart_dedup.upgrade()
        map_editor.upgrade()
        map_floor.upgrade()

        inspector = sa.inspect(connection)
        smart_indexes = {
            index["name"]
            for index in inspector.get_indexes(
                "smart_dedup_workbench_decisions"
            )
        }
        layer_indexes = {
            index["name"]
            for index in inspector.get_indexes("map_layer_nodes")
        }
        assert smart_indexes == {
            "ix_smart_dedup_decision_lookup",
            "ix_smart_dedup_workbench_decisions_novel_id",
            "uq_smart_dedup_active_disposition",
        }
        assert layer_indexes == {
            "ix_map_layer_node_map_parent",
            "ix_map_layer_nodes_map_id",
            "ix_map_layer_nodes_novel_id",
            "ix_map_layer_nodes_parent_id",
            "ix_map_layer_nodes_path_layer_id",
            "ix_map_layer_nodes_terrain_layer_id",
            "uq_map_layer_node_map_layer_key",
            "uq_map_layer_node_path_layer",
            "uq_map_layer_node_terrain_layer",
        }

        map_columns = {
            column["name"] for column in inspector.get_columns("map_configs")
        }
        assert {"status", "archived_at", "editor_revision"} <= map_columns
        layer_columns = {
            column["name"]
            for column in inspector.get_columns("map_layer_nodes")
        }
        assert {"selection_mode", "floor_level", "path_layer_id"} <= layer_columns
        assert {"map_path_layers", "map_paths", "map_path_nodes"} <= set(
            inspector.get_table_names()
        )
        assert any(
            foreign_key.get("constrained_columns") == ["path_layer_id"]
            for foreign_key in inspector.get_foreign_keys("map_layer_nodes")
        )


def test_baseline_source_does_not_import_live_orm_metadata() -> None:
    source = (
        VERSIONS_ROOT / "20260703_squashed_current_schema.py"
    ).read_text(encoding="utf-8")

    assert "Base.metadata" not in source
    assert "modules." not in source
    assert "infrastructure.tasks.models" not in source
