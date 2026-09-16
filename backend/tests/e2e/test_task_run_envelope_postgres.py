"""PostgreSQL 层的 task 私有 AI 运行信封回归：lease fence 与 worker 合并。"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.database import get_manager
from infrastructure.llm.schemas import (
    AI_RUN_ENVELOPE_KEY,
    AIChargeState,
    AIRunStatus,
    AIStepCallKind,
    LLMUsage,
    read_ai_run_envelope,
)
from infrastructure.llm.workflow_budget import (
    AIManagedStepContext,
    current_ai_run_envelope,
    managed_step_scope,
    new_ai_run_envelope,
)
from infrastructure.tasks.enqueuer import enqueue_task
from infrastructure.tasks.lifecycle import TaskLifecycleService
from infrastructure.tasks.models import AsyncTask
from infrastructure.tasks.registry import TaskRegistry
from infrastructure.tasks.worker import TaskWorker
from modules.project.models import Project
from modules.world.map_atlas_models import MapAtlasRun
from modules.world.map_atlas_tasks import checkpoint_map_atlas_run_envelope
from tests.e2e.config import DATABASE_URL

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]

_USAGE = LLMUsage(prompt_tokens=2, completion_tokens=3, total_tokens=5)


async def _record_request() -> None:
    ledger = current_ai_run_envelope()
    assert ledger is not None
    with managed_step_scope(
        AIManagedStepContext(
            step_name="task.run_envelope.postgres",
            call_kind=AIStepCallKind.structured,
        )
    ):
        reservation = await ledger.reserve()
        await ledger.settle(reservation, usage=_USAGE)


async def test_checkpoint_run_envelope_requires_the_live_lease() -> None:
    """窄 merge 在真实 FOR UPDATE 行锁下只接受当前 attempt 的 lease。"""
    engine = create_async_engine(DATABASE_URL, pool_size=4, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    lifecycle = TaskLifecycleService()
    task_id = uuid.uuid4()
    novel_id = uuid.uuid4()
    live_lease = str(uuid.uuid4())
    try:
        async with sessions.begin() as db:
            db.add(Project(id=novel_id, title="run envelope lease fence"))
        async with sessions.begin() as db:
            db.add(
                AsyncTask(
                    id=task_id,
                    novel_id=novel_id,
                    task_type="run-envelope-lease-fence",
                    status="running",
                    meta={"novel_id": str(novel_id)},
                    attempt=1,
                    lease_id=live_lease,
                )
            )

        async with sessions.begin() as db:
            rejected = await lifecycle.checkpoint_run_envelope(
                db,
                task_id=task_id,
                lease_id=str(uuid.uuid4()),
                envelope={"version": 1, "run_id": "stale-attempt"},
            )
        assert rejected is False
        async with sessions() as db:
            stored = await db.get(AsyncTask, task_id)
            assert AI_RUN_ENVELOPE_KEY not in (stored.meta or {})

        async with sessions.begin() as db:
            accepted = await lifecycle.checkpoint_run_envelope(
                db,
                task_id=task_id,
                lease_id=live_lease,
                envelope={"version": 1, "run_id": "live-attempt"},
            )
        assert accepted is True

        # 新 attempt 接管 lease 后，旧 attempt 的窄 merge 不能再覆盖信封。
        async with sessions.begin() as db:
            await db.execute(
                update(AsyncTask)
                .where(AsyncTask.id == task_id)
                .values(lease_id=str(uuid.uuid4()))
            )
        async with sessions.begin() as db:
            stale = await lifecycle.checkpoint_run_envelope(
                db,
                task_id=task_id,
                lease_id=live_lease,
                envelope={"version": 1, "run_id": "stale-overwrite"},
            )
        assert stale is False
        async with sessions() as db:
            stored = await db.get(AsyncTask, task_id)
            assert (stored.meta or {})[AI_RUN_ENVELOPE_KEY]["run_id"] == "live-attempt"
    finally:
        async with sessions.begin() as cleanup_db:
            await cleanup_db.execute(delete(AsyncTask).where(AsyncTask.id == task_id))
            await cleanup_db.execute(delete(Project).where(Project.id == novel_id))
        await engine.dispose()


async def test_worker_merges_the_run_envelope_in_postgres() -> None:
    """真实 worker 在 PostgreSQL 上合并同一 run 并持久化终态快照。"""
    manager = get_manager()
    sessions = manager.session_factory
    registry = TaskRegistry()
    task_type = f"run-envelope-pg-{uuid.uuid4().hex}"
    task_id = uuid.uuid4()
    novel_id = uuid.uuid4()
    try:
        async def handler(*, db, task):
            del db, task
            await _record_request()
            return {"ok": True}

        registry.register(
            task_type,
            handler,
            root_capability_id="writing.generate",
            run_request_limit=1,
        )
        async with sessions.begin() as db:
            db.add(Project(id=novel_id, title="run envelope worker"))
            await db.flush()
            task_id = uuid.UUID(
                enqueue_task(
                    db,
                    task_type,
                    meta={"novel_id": str(novel_id)},
                    novel_id=novel_id,
                )
            )

        returned = await TaskWorker(heartbeat_interval=60.0).run_once(
            task_id=task_id,
            novel_id=novel_id,
        )
        assert returned is not None and returned.status == "done"

        async with sessions() as db:
            stored = await db.get(AsyncTask, task_id)
            assert stored is not None
            envelope = read_ai_run_envelope(
                (stored.meta or {}).get(AI_RUN_ENVELOPE_KEY)
            )
            assert envelope is not None
            assert envelope.run_id == str(task_id)
            assert envelope.root_capability_id == "writing.generate"
            assert envelope.status is AIRunStatus.succeeded
            assert envelope.requests_started == 1
            assert envelope.requests_settled == 1
            assert envelope.usage.total_tokens == _USAGE.total_tokens
            assert envelope.charge_state is AIChargeState.recorded
            # 信封只在 meta，result 保持 handler 返回的业务 shape。
            assert stored.result == {"ok": True}
    finally:
        registry.unregister(task_type)
        async with sessions.begin() as cleanup_db:
            await cleanup_db.execute(delete(AsyncTask).where(AsyncTask.id == task_id))
            await cleanup_db.execute(delete(Project).where(Project.id == novel_id))


async def test_map_atlas_envelope_mirrors_into_the_stable_run() -> None:
    manager = get_manager()
    sessions = manager.session_factory
    novel_id, task_id, run_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    try:
        async with sessions.begin() as db:
            db.add(Project(id=novel_id, title="map envelope mirror"))
            await db.flush()
            task = AsyncTask(
                id=task_id,
                novel_id=novel_id,
                task_type="map_atlas_generate",
                status="running",
                attempt=1,
                lease_id=str(uuid.uuid4()),
                meta={"novel_id": str(novel_id), "run_id": str(run_id)},
            )
            db.add(task)
            await db.flush()
            db.add(
                MapAtlasRun(
                    id=run_id,
                    novel_id=novel_id,
                    task_id=task_id,
                    run_kind="initial",
                    status="planning",
                    context_snapshot={},
                )
            )
            await db.flush()
            envelope = new_ai_run_envelope(
                operation_id=str(run_id),
                run_id=str(run_id),
                root_capability_id="world.map_atlas.generate",
                novel_id=str(novel_id),
                request_limit=51,
            ).snapshot().model_dump(mode="json")
            await checkpoint_map_atlas_run_envelope(db, task, envelope)

        async with sessions() as db:
            run = await db.get(MapAtlasRun, run_id)
            mirrored = read_ai_run_envelope(
                (run.context_snapshot or {}).get(AI_RUN_ENVELOPE_KEY)
            )
            assert mirrored is not None
            assert mirrored.run_id == str(run_id)
            assert mirrored.request_limit == 51
    finally:
        async with sessions.begin() as db:
            await db.execute(delete(MapAtlasRun).where(MapAtlasRun.id == run_id))
            await db.execute(delete(AsyncTask).where(AsyncTask.id == task_id))
            await db.execute(delete(Project).where(Project.id == novel_id))
