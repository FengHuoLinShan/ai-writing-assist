"""Add durable task coalescing and domain workflow owners.

Revision ID: 20260724_task_owners
Revises: 20260723_account_system
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260724_task_owners"
down_revision = "20260723_account_system"
branch_labels = None
depends_on = None

_IMPORT_TASK_TYPES = frozenset(
    {
        "deep_import",
        "scene_auto_extraction",
        "world_object_auto_extraction",
        "plot_structure_auto_extraction",
        "map_observation_enrichment",
    }
)
_MANUAL_RECOVERY_IMPORT_TASK_TYPES = _IMPORT_TASK_TYPES - {
    "map_observation_enrichment",
}
_KNOWN_COALESCED_TASK_TYPES = frozenset(
    {
        "rag_index_chapter",
        "rag_reannotate_entities",
        "world_bible_projection_refresh",
        *_IMPORT_TASK_TYPES,
    }
)
_ACTIVE_TASK_STATUSES = frozenset({"pending", "running"})


def _uuid_type():
    return sa.CHAR(36).with_variant(postgresql.UUID(as_uuid=True), "postgresql")


def _canonical_novel_id(value: Any) -> str | None:
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError, AttributeError):
        return None


def _coalescing_key(
    *,
    task_type: str,
    novel_id: str,
    scope: Sequence[str],
) -> str:
    """Mirror infrastructure.tasks.enqueuer.build_task_coalescing_key v1."""
    payload = json.dumps(
        {
            "novel_id": str(uuid.UUID(str(novel_id))),
            "scope": tuple(str(value).strip() for value in scope),
            "task_type": str(task_type),
            "version": 1,
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _known_task_scope(
    task_type: str,
    meta: dict[str, Any],
) -> tuple[str, ...] | None:
    if task_type in _IMPORT_TASK_TYPES:
        return ("imports_pipeline",)
    if task_type == "rag_reannotate_entities":
        return ("entity_activity",)
    if task_type == "rag_index_chapter":
        chapter_index = meta.get("chapter_index")
        content_mode = str(meta.get("content_mode") or "").strip()
        try:
            chapter = int(chapter_index)
        except (TypeError, ValueError):
            return None
        if chapter < 1 or not content_mode:
            return None
        return ("chapter_index", str(chapter), content_mode)
    if task_type == "world_bible_projection_refresh":
        page_id = _canonical_novel_id(meta.get("page_id"))
        projection_type = str(meta.get("projection_type") or "").strip()
        if page_id is None or not projection_type:
            return None
        return ("page_projection", page_id, projection_type)
    return None


def _task_rows(bind: sa.Connection) -> list[dict[str, Any]]:
    rows = bind.execute(
        sa.text(
            """
            SELECT id, task_type, status, meta, result, created_at, updated_at,
                   started_at, finished_at, attempt, lease_id
            FROM async_tasks
            WHERE task_type IN (
                'deep_import',
                'scene_auto_extraction',
                'world_object_auto_extraction',
                'plot_structure_auto_extraction',
                'map_observation_enrichment',
                'rag_index_chapter',
                'rag_reannotate_entities',
                'world_bible_projection_refresh'
            )
            """
        )
    )
    return [dict(row._mapping) for row in rows]


def _sort_timestamp(row: dict[str, Any]) -> datetime:
    value = row.get("created_at")
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
    return datetime.min.replace(tzinfo=UTC)


def _newest_first(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        rows,
        key=lambda row: (_sort_timestamp(row), str(row.get("id") or "")),
        reverse=True,
    )


def _backfill_coalescing_keys(
    bind: sa.Connection,
    rows: list[dict[str, Any]],
) -> None:
    update = sa.text("UPDATE async_tasks SET coalescing_key = :key WHERE id = :task_id")
    for row in rows:
        task_type = str(row.get("task_type") or "")
        if task_type not in _KNOWN_COALESCED_TASK_TYPES:
            continue
        meta = _mapping(row.get("meta"))
        novel_id = _canonical_novel_id(meta.get("novel_id"))
        scope = _known_task_scope(task_type, meta)
        if novel_id is None or scope is None:
            continue
        key = _coalescing_key(
            task_type=task_type,
            novel_id=novel_id,
            scope=scope,
        )
        row["coalescing_key"] = key
        bind.execute(update, {"key": key, "task_id": row["id"]})


def _cancel_task(
    bind: sa.Connection,
    *,
    task_id: Any,
    reason: str,
) -> None:
    bind.execute(
        sa.text(
            """
            UPDATE async_tasks
            SET status = 'cancelled',
                finished_at = CURRENT_TIMESTAMP,
                lease_id = NULL,
                transition_reason = :reason,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = :task_id
              AND status IN ('pending', 'running')
            """
        ),
        {"task_id": task_id, "reason": reason},
    )


def _converge_duplicate_coalesced_tasks(
    bind: sa.Connection,
    rows: list[dict[str, Any]],
) -> None:
    by_key_status: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = row.get("coalescing_key")
        status = str(row.get("status") or "")
        if isinstance(key, str) and status in _ACTIVE_TASK_STATUSES:
            by_key_status[(key, status)].append(row)
    for duplicates in by_key_status.values():
        for stale in _newest_first(duplicates)[1:]:
            _cancel_task(
                bind,
                task_id=stale["id"],
                reason="superseded_migration",
            )
            stale["status"] = "cancelled"


def _optional_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _update_import_recovery_state(
    bind: sa.Connection,
    row: dict[str, Any],
    *,
    recovery_required: bool,
) -> None:
    meta = _mapping(row.get("meta"))
    result = _mapping(row.get("result"))
    meta["recovery_required"] = recovery_required
    result["recovery_required"] = recovery_required
    tasks = sa.table(
        "async_tasks",
        sa.column("id", _uuid_type()),
        sa.column("status", sa.String(32)),
        sa.column("meta", sa.JSON()),
        sa.column("result", sa.JSON()),
        sa.column("finished_at", sa.DateTime(timezone=True)),
        sa.column("lease_id", sa.String(36)),
        sa.column("transition_reason", sa.String(64)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    values: dict[str, Any] = {
        "meta": meta,
        "result": result,
        "updated_at": datetime.now(UTC),
    }
    if recovery_required:
        values.update(
            {
                "status": "failed",
                "finished_at": datetime.now(UTC),
                "lease_id": None,
                "transition_reason": "migration_import_manual_recovery",
            }
        )
        row["status"] = "failed"
        row["lease_id"] = None
    bind.execute(tasks.update().where(tasks.c.id == row["id"]).values(**values))
    row["meta"] = meta
    row["result"] = result


def _requires_manual_recovery(row: dict[str, Any]) -> bool:
    if str(row.get("task_type") or "") not in _MANUAL_RECOVERY_IMPORT_TASK_TYPES:
        return False
    if str(row.get("status") or "") != "failed":
        return False
    meta = _mapping(row.get("meta"))
    result = _mapping(row.get("result"))
    return (
        meta.get("recovery_required") is True and result.get("recovery_required") is True
    )


def _requeue_restartable_import_task(
    bind: sa.Connection,
    row: dict[str, Any],
) -> None:
    """Return a deployment-interrupted restartable workflow to the queue."""
    bind.execute(
        sa.text(
            """
            UPDATE async_tasks
            SET status = 'pending',
                started_at = NULL,
                finished_at = NULL,
                heartbeat_at = NULL,
                lease_id = NULL,
                stale_detected_at = NULL,
                transition_reason = 'migration_restartable_requeue',
                updated_at = CURRENT_TIMESTAMP
            WHERE id = :task_id
              AND status = 'running'
            """
        ),
        {"task_id": row["id"]},
    )
    row["status"] = "pending"
    row["lease_id"] = None


def _neutralize_unbackfillable_import_task(
    bind: sa.Connection,
    row: dict[str, Any],
) -> None:
    """Prevent malformed legacy imports rows from becoming reusable or recoverable."""
    status = str(row.get("status") or "")
    if status in _ACTIVE_TASK_STATUSES:
        _cancel_task(
            bind,
            task_id=row["id"],
            reason="migration_invalid_import_scope",
        )
        row["status"] = "cancelled"
        row["lease_id"] = None
    elif status == "failed":
        _update_import_recovery_state(
            bind,
            row,
            recovery_required=False,
        )


def _backfill_import_workflow_runs(
    bind: sa.Connection,
    rows: list[dict[str, Any]],
) -> None:
    imports_rows: list[dict[str, Any]] = []
    for row in rows:
        task_type = str(row.get("task_type") or "")
        if task_type not in _IMPORT_TASK_TYPES:
            continue
        meta = _mapping(row.get("meta"))
        novel_id = _canonical_novel_id(meta.get("novel_id"))
        start_chapter = _optional_int(meta.get("start_chapter"))
        end_chapter = _optional_int(meta.get("end_chapter"))
        if (
            novel_id is None
            or start_chapter is None
            or end_chapter is None
            or start_chapter < 1
            or end_chapter < start_chapter
        ):
            _neutralize_unbackfillable_import_task(bind, row)
            continue
        row["novel_id"] = novel_id
        row["start_chapter"] = start_chapter
        row["end_chapter"] = end_chapter
        if str(row.get("status") or "") == "running":
            if task_type in _MANUAL_RECOVERY_IMPORT_TASK_TYPES:
                _update_import_recovery_state(
                    bind,
                    row,
                    recovery_required=True,
                )
            else:
                _requeue_restartable_import_task(bind, row)
        row["recovery_required"] = _requires_manual_recovery(row)
        imports_rows.append(row)

    active_by_novel: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in imports_rows:
        if (
            str(row.get("status") or "") in _ACTIVE_TASK_STATUSES
            or row["recovery_required"] is True
        ):
            active_by_novel[row["novel_id"]].append(row)
    for duplicate_rows in active_by_novel.values():
        for stale in _newest_first(duplicate_rows)[1:]:
            if str(stale.get("status") or "") in _ACTIVE_TASK_STATUSES:
                _cancel_task(
                    bind,
                    task_id=stale["id"],
                    reason="superseded_migration",
                )
                stale["status"] = "cancelled"
            elif stale["recovery_required"] is True:
                _update_import_recovery_state(
                    bind,
                    stale,
                    recovery_required=False,
                )
            stale["recovery_required"] = False

    guid = _uuid_type()
    workflow_runs = sa.table(
        "import_workflow_runs",
        sa.column("id", guid),
        sa.column("task_id", guid),
        sa.column("novel_id", guid),
        sa.column("workflow_type", sa.String(64)),
        sa.column("stage", sa.String(64)),
        sa.column("start_chapter", sa.Integer()),
        sa.column("end_chapter", sa.Integer()),
        sa.column("status", sa.String(32)),
        sa.column("generation", sa.Integer()),
        sa.column("owner_task_id", guid),
        sa.column("owner_attempt", sa.Integer()),
        sa.column("owner_lease_id", sa.String(36)),
        sa.column("recovery_required", sa.Boolean()),
        sa.column("authorization_snapshot", sa.JSON()),
        sa.column("llm_execution_snapshot", sa.JSON()),
        sa.column("prepare_checkpoint", sa.JSON()),
        sa.column("checkpoints", sa.JSON()),
        sa.column("progress", sa.JSON()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    for row in _newest_first(imports_rows):
        meta = _mapping(row.get("meta"))
        result = _mapping(row.get("result"))
        status = str(row.get("status") or "failed")
        running = status == "running"
        task_uuid = uuid.UUID(str(row["id"]))
        bind.execute(
            workflow_runs.insert().values(
                id=task_uuid,
                task_id=task_uuid,
                novel_id=uuid.UUID(row["novel_id"]),
                workflow_type=str(row.get("task_type") or "deep_import"),
                stage=(
                    str(meta["stage"]).strip() if meta.get("stage") is not None else None
                ),
                start_chapter=row["start_chapter"],
                end_chapter=row["end_chapter"],
                status=status,
                generation=1,
                owner_task_id=task_uuid if running else None,
                owner_attempt=(_optional_int(row.get("attempt")) if running else None),
                owner_lease_id=(
                    str(row["lease_id"]) if running and row.get("lease_id") else None
                ),
                recovery_required=row["recovery_required"],
                authorization_snapshot=_mapping(meta.get("authorization_snapshot")),
                llm_execution_snapshot=_mapping(meta.get("llm_execution_snapshot")),
                prepare_checkpoint=meta,
                checkpoints=_mapping(result.get("checkpoints")),
                progress=result,
                created_at=row.get("created_at") or datetime.now(UTC),
                updated_at=(
                    row.get("updated_at") or row.get("created_at") or datetime.now(UTC)
                ),
            )
        )


def _backfill_rag_owners(bind: sa.Connection) -> None:
    states = bind.execute(
        sa.text(
            """
            SELECT id, novel_id, chapter_index, content_mode
            FROM rag_index_state
            """
        )
    )
    active_tasks = bind.execute(
        sa.text(
            """
            SELECT id, coalescing_key, status, created_at
            FROM async_tasks
            WHERE task_type = 'rag_index_chapter'
              AND status IN ('pending', 'running')
              AND coalescing_key IS NOT NULL
            """
        )
    )
    tasks_by_key: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for task in active_tasks:
        row = dict(task._mapping)
        tasks_by_key[str(row["coalescing_key"])].append(row)

    update = sa.text(
        """
        UPDATE rag_index_state
        SET active_task_id = :task_id,
            generation = 1,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = :state_id
        """
    )
    for state in states:
        row = dict(state._mapping)
        novel_id = _canonical_novel_id(row.get("novel_id"))
        content_mode = str(row.get("content_mode") or "").strip()
        if novel_id is None or not content_mode:
            continue
        key = _coalescing_key(
            task_type="rag_index_chapter",
            novel_id=novel_id,
            scope=(
                "chapter_index",
                str(int(row["chapter_index"])),
                content_mode,
            ),
        )
        candidates = tasks_by_key.get(key, [])
        if not candidates:
            continue
        candidates = sorted(
            candidates,
            key=lambda task: (
                str(task.get("status") or "") == "pending",
                _sort_timestamp(task),
                str(task.get("id") or ""),
            ),
            reverse=True,
        )
        bind.execute(
            update,
            {"task_id": candidates[0]["id"], "state_id": row["id"]},
        )


def _already_matches_dynamic_baseline() -> bool:
    """Accept a complete live-ORM baseline and reject ambiguous partial shapes."""
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    async_task_columns = {
        column["name"] for column in inspector.get_columns("async_tasks")
    }
    rag_state_columns = {
        column["name"] for column in inspector.get_columns("rag_index_state")
    }
    markers = {
        "async_tasks.coalescing_key": "coalescing_key" in async_task_columns,
        "rag_index_state.active_task_id": "active_task_id" in rag_state_columns,
        "rag_index_state.generation": "generation" in rag_state_columns,
        "import_workflow_runs": "import_workflow_runs" in tables,
    }
    if not any(markers.values()):
        return False
    if not all(markers.values()):
        missing = ", ".join(name for name, present in markers.items() if not present)
        raise RuntimeError(
            "Partial task-owner schema exists; refusing ambiguous migration: "
            f"missing {missing}"
        )
    return True


def upgrade() -> None:
    if op.get_context().as_sql:
        raise RuntimeError(
            "20260724_task_owners requires an online transactional migration "
            "for deterministic task backfill and duplicate convergence"
        )
    if _already_matches_dynamic_baseline():
        return

    guid = _uuid_type()
    op.add_column(
        "async_tasks",
        sa.Column(
            "coalescing_key",
            sa.String(64),
            nullable=True,
            comment=("Internal SHA-256 keyed-coalescing identity; never expose publicly"),
        ),
    )
    op.add_column(
        "rag_index_state",
        sa.Column("active_task_id", guid, nullable=True),
    )
    op.add_column(
        "rag_index_state",
        sa.Column(
            "generation",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.create_foreign_key(
        "fk_rag_index_state_active_task",
        "rag_index_state",
        "async_tasks",
        ["active_task_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_rag_index_state_active_task_id",
        "rag_index_state",
        ["active_task_id"],
    )

    op.create_table(
        "import_workflow_runs",
        sa.Column("id", guid, nullable=False),
        sa.Column("task_id", guid, nullable=False),
        sa.Column("novel_id", guid, nullable=False),
        sa.Column("workflow_type", sa.String(64), nullable=False),
        sa.Column("stage", sa.String(64), nullable=True),
        sa.Column("start_chapter", sa.Integer(), nullable=False),
        sa.Column("end_chapter", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column(
            "generation",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
        sa.Column("owner_task_id", guid, nullable=True),
        sa.Column("owner_attempt", sa.Integer(), nullable=True),
        sa.Column("owner_lease_id", sa.String(36), nullable=True),
        sa.Column(
            "recovery_required",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "authorization_snapshot",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column(
            "llm_execution_snapshot",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column(
            "prepare_checkpoint",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column(
            "checkpoints",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column(
            "progress",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["async_tasks.id"],
            name="fk_import_workflow_runs_task_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["novel_id"],
            ["projects.id"],
            name="fk_import_workflow_runs_novel_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["owner_task_id"],
            ["async_tasks.id"],
            name="fk_import_workflow_runs_owner_task_id",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "task_id",
            name="uq_import_workflow_runs_task_id",
        ),
        comment="imports-owned deep-import/map enrichment workflow state",
    )
    op.create_index(
        "ix_import_workflow_runs_novel_id",
        "import_workflow_runs",
        ["novel_id"],
    )
    op.create_index(
        "ix_import_workflow_runs_status",
        "import_workflow_runs",
        ["status"],
    )
    op.create_index(
        "ix_import_workflow_runs_task_generation",
        "import_workflow_runs",
        ["task_id", "generation"],
    )

    bind = op.get_bind()
    rows = _task_rows(bind)
    _backfill_coalescing_keys(bind, rows)
    _converge_duplicate_coalesced_tasks(bind, rows)
    _backfill_import_workflow_runs(bind, rows)
    _backfill_rag_owners(bind)

    op.create_index(
        "uq_async_tasks_coalescing_pending",
        "async_tasks",
        ["coalescing_key"],
        unique=True,
        postgresql_where=sa.text("coalescing_key IS NOT NULL AND status = 'pending'"),
        sqlite_where=sa.text("coalescing_key IS NOT NULL AND status = 'pending'"),
    )
    op.create_index(
        "uq_async_tasks_coalescing_running",
        "async_tasks",
        ["coalescing_key"],
        unique=True,
        postgresql_where=sa.text("coalescing_key IS NOT NULL AND status = 'running'"),
        sqlite_where=sa.text("coalescing_key IS NOT NULL AND status = 'running'"),
    )
    op.create_index(
        "ix_async_tasks_coalescing_created",
        "async_tasks",
        ["coalescing_key", "created_at"],
    )
    op.create_index(
        "uq_import_workflow_runs_active_novel",
        "import_workflow_runs",
        ["novel_id"],
        unique=True,
        postgresql_where=sa.text(
            "status IN ('pending', 'running') OR recovery_required = true"
        ),
        sqlite_where=sa.text("status IN ('pending', 'running') OR recovery_required = 1"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_import_workflow_runs_active_novel",
        table_name="import_workflow_runs",
    )
    op.drop_table("import_workflow_runs")

    op.drop_index(
        "ix_rag_index_state_active_task_id",
        table_name="rag_index_state",
    )
    op.drop_constraint(
        "fk_rag_index_state_active_task",
        "rag_index_state",
        type_="foreignkey",
    )
    op.drop_column("rag_index_state", "generation")
    op.drop_column("rag_index_state", "active_task_id")

    op.drop_index(
        "ix_async_tasks_coalescing_created",
        table_name="async_tasks",
    )
    op.drop_index(
        "uq_async_tasks_coalescing_running",
        table_name="async_tasks",
    )
    op.drop_index(
        "uq_async_tasks_coalescing_pending",
        table_name="async_tasks",
    )
    op.drop_column("async_tasks", "coalescing_key")
