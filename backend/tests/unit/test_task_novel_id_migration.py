"""Regression tests for the first-class async task project identity migration."""

from __future__ import annotations

import importlib.util
import json
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

BACKEND_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = BACKEND_ROOT / "alembic" / "versions" / "20260805_task_novel_id.py"


def _load_migration():
    spec = importlib.util.spec_from_file_location(
        "test_task_novel_id_migration_module",
        MIGRATION_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def _legacy_schema(connection: sa.Connection) -> tuple[sa.Table, sa.Table]:
    metadata = sa.MetaData()
    projects = sa.Table(
        "projects",
        metadata,
        sa.Column("id", sa.CHAR(36), primary_key=True),
    )
    tasks = sa.Table(
        "async_tasks",
        metadata,
        sa.Column("id", sa.CHAR(36), primary_key=True),
        sa.Column("meta", sa.JSON(), nullable=False),
    )
    metadata.create_all(connection)
    return projects, tasks


def _run_upgrade(connection: sa.Connection) -> None:
    migration = _load_migration()
    migration.op = Operations(MigrationContext.configure(connection))
    migration.upgrade()


def _run_downgrade(connection: sa.Connection) -> None:
    migration = _load_migration()
    migration.op = Operations(MigrationContext.configure(connection))
    migration.downgrade()


def test_migration_backfills_scoped_tasks_and_preserves_global_tasks() -> None:
    engine = sa.create_engine("sqlite://")
    project_id = uuid.uuid4()
    scoped_task_id = uuid.uuid4()
    global_task_id = uuid.uuid4()
    with engine.begin() as connection:
        projects, tasks = _legacy_schema(connection)
        connection.execute(projects.insert().values(id=str(project_id)))
        connection.execute(
            tasks.insert(),
            [
                {
                    "id": str(scoped_task_id),
                    "meta": {"novel_id": str(project_id).upper(), "stage": "queued"},
                },
                {"id": str(global_task_id), "meta": {"maintenance": True}},
            ],
        )

        _run_upgrade(connection)

        inspector = sa.inspect(connection)
        assert "novel_id" in {
            column["name"] for column in inspector.get_columns("async_tasks")
        }
        assert "ix_async_tasks_novel_id" in {
            index["name"] for index in inspector.get_indexes("async_tasks")
        }
        assert any(
            foreign_key.get("constrained_columns") == ["novel_id"]
            and foreign_key.get("referred_table") == "projects"
            and (foreign_key.get("options") or {}).get("ondelete", "").upper()
            == "CASCADE"
            for foreign_key in inspector.get_foreign_keys("async_tasks")
        )
        row_by_id = {
            row.id: (row.novel_id, json.loads(row.meta))
            for row in connection.execute(
                sa.text("SELECT id, novel_id, meta FROM async_tasks")
            )
        }
        assert row_by_id[str(scoped_task_id)] == (
            str(project_id),
            {"novel_id": str(project_id), "stage": "queued"},
        )
        assert row_by_id[str(global_task_id)] == (None, {"maintenance": True})
        with pytest.raises(sa.exc.IntegrityError, match="identity mismatch"):
            connection.execute(
                sa.text("UPDATE async_tasks SET novel_id = NULL WHERE id = :task_id"),
                {"task_id": str(scoped_task_id)},
            )
        with pytest.raises(sa.exc.IntegrityError, match="identity mismatch"):
            connection.execute(
                sa.text("UPDATE async_tasks SET meta = :meta WHERE id = :task_id"),
                {
                    "task_id": str(scoped_task_id),
                    "meta": '{"novel_id":"00000000-0000-0000-0000-000000000000"}',
                },
            )
        for noncanonical_identity in (
            "",
            str(project_id).upper(),
            project_id.hex,
        ):
            with pytest.raises(sa.exc.IntegrityError, match="identity mismatch"):
                connection.execute(
                    sa.text("UPDATE async_tasks SET meta = :meta WHERE id = :task_id"),
                    {
                        "task_id": str(scoped_task_id),
                        "meta": json.dumps({"novel_id": noncanonical_identity}),
                    },
                )
        connection.execute(
            sa.text(
                "INSERT INTO async_tasks (id, novel_id, meta) VALUES (:id, NULL, :meta)"
            ),
            {
                "id": str(uuid.uuid4()),
                "meta": json.dumps({"novel_id": None}),
            },
        )
        with pytest.raises(sa.exc.IntegrityError, match="identity mismatch"):
            connection.execute(
                sa.text(
                    "INSERT INTO async_tasks (id, novel_id, meta) "
                    "VALUES (:id, NULL, :meta)"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "meta": json.dumps({"novel_id": ""}),
                },
            )

        _run_downgrade(connection)
        assert "novel_id" not in {
            column["name"] for column in sa.inspect(connection).get_columns("async_tasks")
        }


@pytest.mark.parametrize(
    "meta",
    [
        {"novel_id": "not-a-uuid"},
        {"novel_id": str(uuid.uuid4())},
        ["not-an-object"],
    ],
)
def test_migration_rejects_invalid_or_orphan_task_identity(meta: object) -> None:
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        _projects, tasks = _legacy_schema(connection)
        connection.execute(tasks.insert().values(id=str(uuid.uuid4()), meta=meta))

        with pytest.raises(RuntimeError):
            _run_upgrade(connection)


def test_migration_rejects_preexisting_column_metadata_conflict() -> None:
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        metadata = sa.MetaData()
        projects = sa.Table(
            "projects",
            metadata,
            sa.Column("id", sa.CHAR(36), primary_key=True),
        )
        tasks = sa.Table(
            "async_tasks",
            metadata,
            sa.Column("id", sa.CHAR(36), primary_key=True),
            sa.Column("novel_id", sa.CHAR(36), nullable=True),
            sa.Column("meta", sa.JSON(), nullable=False),
        )
        metadata.create_all(connection)
        metadata_ids = (uuid.uuid4(), uuid.uuid4())
        connection.execute(
            projects.insert(),
            [{"id": str(project_id)} for project_id in metadata_ids],
        )
        connection.execute(
            tasks.insert().values(
                id=str(uuid.uuid4()),
                novel_id=str(metadata_ids[0]),
                meta={"novel_id": str(metadata_ids[1])},
            )
        )

        with pytest.raises(RuntimeError, match="disagrees"):
            _run_upgrade(connection)
