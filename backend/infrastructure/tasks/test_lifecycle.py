from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.tasks.lifecycle import TaskLifecycleService, lifecycle_contract
from infrastructure.tasks.models import AsyncTask


@pytest.mark.asyncio
async def test_claim_freezes_lease_and_rejects_old_lease_completion(
    db_session: AsyncSession,
) -> None:
    service = TaskLifecycleService()
    task = AsyncTask(
        id=uuid.uuid4(),
        task_type="rag_reindex",
        status="pending",
        meta={"novel_id": str(uuid.uuid4())},
        recovery_policy="auto_requeue",
        max_attempts=2,
    )
    db_session.add(task)
    await db_session.commit()

    claimed = await service.claim_next(db_session)
    assert claimed is not None
    assert claimed.status == "running"
    assert claimed.attempt == 1
    first_lease = claimed.lease_id
    assert first_lease

    claimed.started_at = datetime.now(UTC) - timedelta(minutes=10)
    claimed.heartbeat_at = datetime.now(UTC) - timedelta(minutes=10)
    await db_session.commit()
    counts = await service.recover_stale(db_session, max_heartbeat_gap=60)
    assert counts == {"auto_requeued": 1, "failed": 0, "manual_resume": 0}

    reclaimed = await service.claim_next(db_session)
    assert reclaimed is not None
    assert reclaimed.attempt == 2
    assert reclaimed.lease_id != first_lease

    stale_side_effect = AsyncTask(
        id=uuid.uuid4(),
        task_type="stale-side-effect",
        status="pending",
        meta={"novel_id": str(uuid.uuid4())},
    )
    db_session.add(stale_side_effect)
    await db_session.flush()

    accepted = await service.finalize(
        db_session,
        task_id=reclaimed.id,
        lease_id=str(first_lease),
        status="done",
        result_data={"owner": "old-worker"},
    )
    assert accepted is False
    assert await db_session.get(AsyncTask, stale_side_effect.id) is None
    await db_session.refresh(reclaimed)
    assert reclaimed.status == "running"
    assert reclaimed.result != {"owner": "old-worker"}

    accepted = await service.finalize(
        db_session,
        task_id=reclaimed.id,
        lease_id=str(reclaimed.lease_id),
        status="done",
        result_data={"owner": "current-worker"},
    )
    assert accepted is True
    await db_session.refresh(reclaimed)
    assert reclaimed.status == "done"
    assert reclaimed.result == {"owner": "current-worker"}


@pytest.mark.asyncio
async def test_manual_resume_policy_becomes_failed_recoverable(
    db_session: AsyncSession,
) -> None:
    service = TaskLifecycleService()
    task = AsyncTask(
        id=uuid.uuid4(),
        task_type="deep_import",
        status="running",
        meta={"novel_id": str(uuid.uuid4())},
        result={},
        attempt=1,
        max_attempts=1,
        recovery_policy="manual_resume",
        lease_id=str(uuid.uuid4()),
        started_at=datetime.now(UTC) - timedelta(minutes=10),
        heartbeat_at=datetime.now(UTC) - timedelta(minutes=10),
    )
    db_session.add(task)
    await db_session.commit()

    counts = await service.recover_stale(db_session, max_heartbeat_gap=60)
    assert counts == {"auto_requeued": 0, "failed": 1, "manual_resume": 1}
    await db_session.refresh(task)
    contract = lifecycle_contract(task, max_heartbeat_gap=60)
    assert contract.status == "failed"
    assert contract.recovery_required is True
    assert contract.available_actions == ["resume", "abandon"]
    assert task.lease_id is None
    assert task.result["lifecycle"]["reason"] == "heartbeat_timeout"


@pytest.mark.asyncio
async def test_heartbeat_is_fenced_by_lease(db_session: AsyncSession) -> None:
    service = TaskLifecycleService()
    task = AsyncTask(
        id=uuid.uuid4(),
        task_type="rag_reindex",
        status="running",
        meta={"novel_id": str(uuid.uuid4())},
        lease_id=str(uuid.uuid4()),
        attempt=1,
    )
    db_session.add(task)
    await db_session.commit()

    assert (
        await service.heartbeat(
            db_session,
            task_id=task.id,
            lease_id=str(uuid.uuid4()),
        )
        is False
    )
    assert (
        await service.heartbeat(
            db_session,
            task_id=task.id,
            lease_id=str(task.lease_id),
        )
        is True
    )


@pytest.mark.asyncio
async def test_cancel_unfinished_for_novel_is_scoped_and_preserves_terminal_tasks(
    db_session: AsyncSession,
) -> None:
    service = TaskLifecycleService()
    target_novel_id = str(uuid.uuid4())
    other_novel_id = str(uuid.uuid4())
    target_tasks = [
        AsyncTask(
            task_type="pending-task",
            status="pending",
            meta={"novel_id": target_novel_id},
        ),
        AsyncTask(
            task_type="running-task",
            status="running",
            meta={"novel_id": target_novel_id},
            lease_id=str(uuid.uuid4()),
        ),
        AsyncTask(
            task_type="done-task",
            status="done",
            meta={"novel_id": target_novel_id},
        ),
    ]
    other_task = AsyncTask(
        task_type="other-task",
        status="running",
        meta={"novel_id": other_novel_id},
        lease_id=str(uuid.uuid4()),
    )
    db_session.add_all([*target_tasks, other_task])
    await db_session.flush()

    cancelled = await service.cancel_unfinished_for_novel(
        db_session,
        novel_id=target_novel_id,
        transition_reason="project_soft_deleted",
    )

    assert cancelled == 2
    db_session.expire_all()
    refreshed = {
        task.task_type: task
        for task in (await db_session.execute(select(AsyncTask))).scalars().all()
    }
    for task_type in ("pending-task", "running-task"):
        task = refreshed[task_type]
        assert task.status == "cancelled"
        assert task.finished_at is not None
        assert task.lease_id is None
        assert task.transition_reason == "project_soft_deleted"
    assert refreshed["done-task"].status == "done"
    assert refreshed["other-task"].status == "running"
    assert refreshed["other-task"].lease_id is not None
