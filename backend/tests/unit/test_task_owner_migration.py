"""Regression tests for durable task coalescing/owner migration."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

from infrastructure.tasks.enqueuer import build_task_coalescing_key

BACKEND_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = (
    BACKEND_ROOT / "alembic" / "versions" / "20260724_task_coalescing_owners.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location(
        "test_task_owner_migration_module",
        MIGRATION_PATH,
    )
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def test_migration_key_backfill_matches_runtime_contract() -> None:
    migration = _load_migration()
    novel_id = str(uuid4())
    scopes = (
        ("imports_pipeline",),
        ("chapter_index", "12", "working"),
        ("page_projection", str(uuid4()), "synopsis"),
        ("entity_activity",),
    )

    for scope in scopes:
        assert migration._coalescing_key(
            task_type="test_task",
            novel_id=novel_id,
            scope=scope,
        ) == build_task_coalescing_key(
            task_type="test_task",
            novel_id=novel_id,
            scope=scope,
        )


def test_migration_upgrade_and_downgrade_declare_owner_schema() -> None:
    migration = _load_migration()
    operations = MagicMock()
    context = MagicMock()
    context.as_sql = False
    operations.get_context.return_value = context
    operations.get_bind.return_value = MagicMock()
    migration.op = operations

    with (
        patch.object(
            migration,
            "_already_matches_dynamic_baseline",
            autospec=True,
            return_value=False,
        ),
        patch.object(migration, "_task_rows", autospec=True, return_value=[]),
        patch.object(migration, "_backfill_coalescing_keys", autospec=True),
        patch.object(
            migration,
            "_converge_duplicate_coalesced_tasks",
            autospec=True,
        ),
        patch.object(
            migration,
            "_backfill_import_workflow_runs",
            autospec=True,
        ),
        patch.object(migration, "_backfill_rag_owners", autospec=True),
    ):
        migration.upgrade()

    assert migration.revision == "20260724_task_owners"
    assert migration.down_revision == "20260723_account_system"
    assert any(
        call.args[0] == "async_tasks" and call.args[1].name == "coalescing_key"
        for call in operations.add_column.call_args_list
    )
    assert any(
        call.args[0] == "import_workflow_runs"
        for call in operations.create_table.call_args_list
    )
    created_indexes = {call.args[0] for call in operations.create_index.call_args_list}
    assert {
        "uq_async_tasks_coalescing_pending",
        "uq_async_tasks_coalescing_running",
        "ix_async_tasks_coalescing_created",
        "uq_import_workflow_runs_active_novel",
    } <= created_indexes

    operations.reset_mock()
    migration.downgrade()

    operations.drop_table.assert_called_once_with("import_workflow_runs")
    dropped_columns = {call.args for call in operations.drop_column.call_args_list}
    assert ("async_tasks", "coalescing_key") in dropped_columns
    assert ("rag_index_state", "active_task_id") in dropped_columns
    assert ("rag_index_state", "generation") in dropped_columns


def _import_task_row(task_type: str, status: str) -> dict:
    novel_id = str(uuid4())
    return {
        "id": uuid4(),
        "task_type": task_type,
        "status": status,
        "meta": {
            "novel_id": novel_id,
            "start_chapter": 1,
            "end_chapter": 3,
            "authorization_snapshot": {
                "authorization_confirmed": True,
                "adoption_policy": "user_authorized_pipeline",
            },
        },
        "result": {},
        "attempt": 1,
        "lease_id": str(uuid4()),
        "created_at": None,
        "updated_at": None,
    }


def test_migration_running_manual_workflow_remains_explicitly_recoverable() -> None:
    migration = _load_migration()
    bind = MagicMock()
    row = _import_task_row("scene_auto_extraction", "running")

    migration._backfill_import_workflow_runs(bind, [row])

    assert row["status"] == "failed"
    assert row["lease_id"] is None
    assert row["recovery_required"] is True
    assert row["meta"]["recovery_required"] is True
    assert row["result"]["recovery_required"] is True


def test_migration_duplicate_tasks_use_specified_superseded_reason() -> None:
    migration = _load_migration()
    bind = MagicMock()
    key = "a" * 64
    older = _import_task_row("deep_import", "pending")
    newer = _import_task_row("deep_import", "pending")
    older["coalescing_key"] = key
    newer["coalescing_key"] = key
    older["id"] = uuid4()
    newer["id"] = uuid4()

    migration._converge_duplicate_coalesced_tasks(bind, [older, newer])

    cancellation_params = [
        call.args[1]
        for call in bind.execute.call_args_list
        if len(call.args) > 1 and isinstance(call.args[1], dict)
    ]
    assert any(
        params.get("reason") == "superseded_migration"
        for params in cancellation_params
    )


def test_migration_cancels_active_import_task_without_backfillable_scope() -> None:
    migration = _load_migration()
    bind = MagicMock()
    row = _import_task_row("deep_import", "pending")
    row["meta"]["start_chapter"] = 0

    migration._backfill_import_workflow_runs(bind, [row])

    assert row["status"] == "cancelled"
    cancellation_params = [
        call.args[1]
        for call in bind.execute.call_args_list
        if len(call.args) > 1 and isinstance(call.args[1], dict)
    ]
    assert any(
        params.get("reason") == "migration_invalid_import_scope"
        for params in cancellation_params
    )


def test_migration_clears_recovery_flags_for_unbackfillable_failed_import() -> None:
    migration = _load_migration()
    bind = MagicMock()
    row = _import_task_row("deep_import", "failed")
    row["meta"]["end_chapter"] = 0
    row["meta"]["recovery_required"] = True
    row["result"]["recovery_required"] = True

    migration._backfill_import_workflow_runs(bind, [row])

    assert row["status"] == "failed"
    assert row["meta"]["recovery_required"] is False
    assert row["result"]["recovery_required"] is False
