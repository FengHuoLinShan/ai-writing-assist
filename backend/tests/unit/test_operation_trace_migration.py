from __future__ import annotations

import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def _migration_module():
    migration_path = (
        Path(__file__).resolve().parents[2]
        / "alembic/versions/20261015_operation_trace_v2.py"
    )
    spec = importlib.util.spec_from_file_location(
        "test_operation_trace_migration", migration_path
    )
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def test_trace_migration_is_a_single_child_and_retention_is_the_only_delete_path():
    migration = _migration_module()
    assert migration.revision == "20261015_operation_trace_v2"
    assert migration.down_revision == "20261015_object_dossier_v2"

    engine = sa.create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            sa.Table(
                "accounts",
                sa.MetaData(),
                sa.Column("id", sa.UUID(), primary_key=True),
            ).create(connection)
            sa.Table(
                "projects",
                sa.MetaData(),
                sa.Column("id", sa.UUID(), primary_key=True),
            ).create(connection)
            migration.op = Operations(MigrationContext.configure(connection))
            migration.upgrade()
            project_id = uuid4()
            connection.execute(
                sa.text("INSERT INTO projects (id) VALUES (:id)"),
                {"id": str(project_id)},
            )
            insert = sa.text(
                """INSERT INTO assistant_operation_traces
                (novel_id, owner_id, occurred_at, actor_type, entrypoint, op_id,
                 op_version, risk_level, fee_category, event_type, target_type,
                 target_refs, parameter_summary, result_refs)
                VALUES (:novel_id, :owner_id, :occurred_at, 'assistant',
                        'assistant.test', 'world.dossier.read', '1', 'R0',
                        'free', 'executed', 'core_entity', '[]', '{}', '[]')"""
            )
            connection.execute(
                insert,
                {
                    "novel_id": str(project_id),
                    "owner_id": str(uuid4()),
                    "occurred_at": datetime.now(UTC),
                },
            )
            connection.execute(
                insert,
                {
                    "novel_id": str(project_id),
                    "owner_id": str(uuid4()),
                    "occurred_at": datetime.now(UTC) - timedelta(days=181),
                },
            )
            ids = (
                connection.execute(
                    sa.text(
                        "SELECT id FROM assistant_operation_traces ORDER BY occurred_at"
                    )
                )
                .scalars()
                .all()
            )
            assert len(ids) == 2
            with pytest.raises(sa.exc.IntegrityError):
                connection.execute(
                    sa.text("DELETE FROM assistant_operation_traces WHERE id=:id"),
                    {"id": ids[1]},
                )
            with pytest.raises(sa.exc.IntegrityError):
                connection.execute(
                    sa.text(
                        "UPDATE assistant_operation_traces "
                        "SET op_id='changed' WHERE id=:id"
                    ),
                    {"id": ids[1]},
                )
            connection.execute(
                sa.text("DELETE FROM assistant_operation_traces WHERE id=:id"),
                {"id": ids[0]},
            )
            assert (
                connection.execute(
                    sa.text("SELECT COUNT(*) FROM assistant_operation_traces")
                ).scalar_one()
                == 1
            )
            migration.downgrade()
            assert not {
                "assistant_operation_traces",
                "assistant_operation_trace_preferences",
                "assistant_operation_trace_project_salts",
                "assistant_operation_trace_aggregates",
                "assistant_operation_sequence_aggregates",
            } & set(sa.inspect(connection).get_table_names())
    finally:
        engine.dispose()
