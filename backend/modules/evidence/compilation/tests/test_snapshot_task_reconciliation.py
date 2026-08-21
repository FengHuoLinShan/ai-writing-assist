from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.tasks.models import AsyncTask
from modules.evidence.compilation.contracts import ContextSnapshotRequest
from modules.evidence.compilation.facade import (
    build_snapshot_health_summary,
    mark_stale_running_snapshots,
    open_context_snapshot,
)
from modules.evidence.compilation.models import ContextSnapshot


def _request(*, novel_id: str, task_id: str) -> ContextSnapshotRequest:
    return ContextSnapshotRequest(
        novel_id=novel_id,
        task_id=task_id,
        phase="entity_extraction",
        operation="scene_entity_extraction",
        prompt_name="scene_entity_extraction",
        model="test-model",
        compile_options={},
        included_asset_ids={},
        context_summary={},
        section_metadata={},
        token_metadata={},
    )


@pytest.mark.asyncio
async def test_live_owner_heartbeat_prevents_snapshot_timeout(
    db_session: AsyncSession,
) -> None:
    novel_id = str(uuid.uuid4())
    task = AsyncTask(
        id=uuid.uuid4(),
        task_type="deep_import",
        status="running",
        meta={"novel_id": novel_id},
        lease_id=str(uuid.uuid4()),
        started_at=datetime.now(UTC),
        heartbeat_at=datetime.now(UTC),
    )
    db_session.add(task)
    snapshot = await open_context_snapshot(
        db_session,
        _request(novel_id=novel_id, task_id=str(task.id)),
    )
    row = (
        await db_session.execute(
            select(ContextSnapshot).where(ContextSnapshot.id == uuid.UUID(snapshot.id))
        )
    ).scalar_one()
    row.created_at = datetime.now(UTC) - timedelta(hours=3)
    await db_session.flush()

    summary = await build_snapshot_health_summary(
        db_session,
        novel_id=novel_id,
        running_timeout_minutes=120,
    )
    assert summary["stale_running_count"] == 0


@pytest.mark.asyncio
async def test_terminal_owner_orphan_is_reconciled_without_waiting_for_timeout(
    db_session: AsyncSession,
) -> None:
    novel_id = str(uuid.uuid4())
    task = AsyncTask(
        id=uuid.uuid4(),
        task_type="deep_import",
        status="failed",
        meta={"novel_id": novel_id},
        recovery_policy="manual_resume",
    )
    db_session.add(task)
    snapshot = await open_context_snapshot(
        db_session,
        _request(novel_id=novel_id, task_id=str(task.id)),
    )

    summary = await build_snapshot_health_summary(
        db_session,
        novel_id=novel_id,
    )
    assert summary["stale_running_count"] == 1
    assert summary["owner_terminal_orphan_count"] == 1

    changed = await mark_stale_running_snapshots(
        db_session,
        novel_id=novel_id,
        dry_run=False,
    )
    assert changed == 1
    row = (
        await db_session.execute(
            select(ContextSnapshot).where(ContextSnapshot.id == uuid.UUID(snapshot.id))
        )
    ).scalar_one()
    assert row.status == "failed"
    assert row.error_kind == "owner_task_terminal"


@pytest.mark.asyncio
async def test_auto_requeued_owner_marks_prior_attempt_snapshot_stale(
    db_session: AsyncSession,
) -> None:
    novel_id = str(uuid.uuid4())
    task = AsyncTask(
        id=uuid.uuid4(),
        task_type="rag_reindex",
        status="pending",
        meta={"novel_id": novel_id},
        recovery_policy="auto_requeue",
        transition_reason="heartbeat_timeout",
    )
    db_session.add(task)
    await open_context_snapshot(
        db_session,
        _request(novel_id=novel_id, task_id=str(task.id)),
    )

    summary = await build_snapshot_health_summary(db_session, novel_id=novel_id)
    assert summary["stale_running_count"] == 1
    assert summary["owner_stale_count"] == 1
