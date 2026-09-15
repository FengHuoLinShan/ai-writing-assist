"""W2-Task：task 身份、lease-fenced 私有 checkpoint 与恢复合并的回归测试。"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker

from infrastructure.llm.errors import LLMAuthError, LLMTimeoutError
from infrastructure.llm.schemas import (
    AI_RUN_ENVELOPE_KEY,
    AIChargeState,
    AIRunStatus,
    AIStepCallKind,
    AITaskIdentityV1,
    LLMUsage,
    read_ai_run_envelope,
)
from infrastructure.llm.workflow_budget import (
    AIManagedStepContext,
    ai_run_scope,
    current_ai_run_envelope,
    managed_step_scope,
    new_ai_run_envelope,
)
from infrastructure.tasks.api import _public_task_meta, _public_task_result
from infrastructure.tasks.enqueuer import enqueue_task
from infrastructure.tasks.lifecycle import TaskLifecycleService
from infrastructure.tasks.models import AsyncTask
from infrastructure.tasks.registry import TaskRegistry
from infrastructure.tasks.worker import TaskWorker

_USAGE = LLMUsage(prompt_tokens=3, completion_tokens=5, total_tokens=8)


class _TaskManager:
    """Minimal DatabaseManager seam for a real worker against the test engine."""

    def __init__(self, engine: Any, sessions: Any) -> None:
        self.engine = engine
        self.session_factory = sessions


def _step_context() -> AIManagedStepContext:
    return AIManagedStepContext(
        step_name="task.run_envelope.test",
        call_kind=AIStepCallKind.structured,
    )


async def _record_request(*, usage: LLMUsage | None = _USAGE) -> None:
    ledger = current_ai_run_envelope()
    assert ledger is not None
    with managed_step_scope(_step_context()):
        reservation = await ledger.reserve()
        await ledger.settle(reservation, usage=usage)


def _stored_envelope(task: AsyncTask):
    return read_ai_run_envelope((task.meta or {}).get(AI_RUN_ENVELOPE_KEY))


async def _enqueue(
    sessions: Any,
    task_type: str,
    *,
    meta: dict[str, Any],
    novel_id=None,
) -> uuid.UUID:
    async with sessions.begin() as db:
        task_id = uuid.UUID(enqueue_task(db, task_type, meta=meta, novel_id=novel_id))
    return task_id


async def _cleanup(sessions: Any, task_ids: list[uuid.UUID]) -> None:
    async with sessions.begin() as db:
        await db.execute(delete(AsyncTask).where(AsyncTask.id.in_(task_ids)))


@pytest.mark.asyncio
async def test_success_persists_private_envelope_and_finishes_the_run(
    test_engine,
) -> None:
    sessions = async_sessionmaker(test_engine, expire_on_commit=False, autoflush=False)
    task_type = f"w2-envelope-success-{uuid.uuid4().hex}"
    registry = TaskRegistry()

    async def handler(*, db, task):
        del db
        await _record_request()
        return {"ok": True, "task_id": str(task.id)}

    registry.register(
        task_type,
        handler,
        owner_scope="global",
        root_capability_id="writing.generate",
    )
    task_id = uuid.uuid4()
    try:
        task_id = await _enqueue(sessions, task_type, meta={})
        returned = await TaskWorker(
            db_manager=_TaskManager(test_engine, sessions),
            heartbeat_interval=60.0,
        ).run_once()

        assert returned is not None and returned.status == "done"
        async with sessions() as db:
            stored = await db.get(AsyncTask, task_id)
            assert stored is not None
            envelope = _stored_envelope(stored)
            assert envelope is not None
            assert envelope.run_id == str(task_id)
            assert envelope.operation_id == str(task_id)
            assert envelope.root_capability_id == "writing.generate"
            assert envelope.task == AITaskIdentityV1(
                task_id=str(task_id),
                attempt=1,
                lease_id=None,
            )
            assert envelope.status is AIRunStatus.succeeded
            assert envelope.requests_started == 1
            assert envelope.requests_settled == 1
            assert envelope.requests_unknown == 0
            assert envelope.usage.total_tokens == _USAGE.total_tokens
            assert envelope.charge_state is AIChargeState.recorded
            assert envelope.legacy_untracked is False
            assert envelope.usage_complete is True
            # 信封只在私有 meta 中，绝不进入 result 或公开投影。
            assert "_ai_run_envelope" not in (stored.result or {})
            assert AI_RUN_ENVELOPE_KEY not in _public_task_result(stored.result)
            assert AI_RUN_ENVELOPE_KEY not in _public_task_meta(stored.meta)
    finally:
        registry.unregister(task_type)
        await _cleanup(sessions, [task_id])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("policy", "attempt_before_claim"),
    [("restart_origin", 0), ("auto_requeue", 1), ("manual_resume", 2)],
)
async def test_legacy_in_flight_task_without_envelope_is_marked_untracked(
    test_engine,
    policy: str,
    attempt_before_claim: int,
) -> None:
    sessions = async_sessionmaker(test_engine, expire_on_commit=False, autoflush=False)
    task_type = f"w2-envelope-legacy-{uuid.uuid4().hex}"
    registry = TaskRegistry()

    async def handler(*, db, task):
        del db, task
        return {"ok": True}

    registry.register(task_type, handler, owner_scope="global", recovery_policy=policy)
    task_id = uuid.uuid4()
    try:
        async with sessions.begin() as db:
            db.add(
                AsyncTask(
                    id=task_id,
                    task_type=task_type,
                    status="pending",
                    meta={},
                    recovery_policy=policy,
                    max_attempts=3,
                    attempt=attempt_before_claim,
                )
            )
        await TaskWorker(
            db_manager=_TaskManager(test_engine, sessions),
            heartbeat_interval=60.0,
        ).run_once()

        async with sessions() as db:
            stored = await db.get(AsyncTask, task_id)
            assert stored is not None
            envelope = _stored_envelope(stored)
            assert envelope is not None
            if attempt_before_claim == 0:
                assert envelope.legacy_untracked is False
                assert envelope.usage_complete is True
            else:
                assert envelope.legacy_untracked is True
                assert envelope.usage_complete is False
    finally:
        registry.unregister(task_type)
        await _cleanup(sessions, [task_id])


@pytest.mark.asyncio
async def test_transient_requeue_persists_receipt_and_keeps_counting_same_run(
    test_engine,
) -> None:
    sessions = async_sessionmaker(test_engine, expire_on_commit=False, autoflush=False)
    task_type = f"w2-envelope-transient-{uuid.uuid4().hex}"
    registry = TaskRegistry()
    calls = 0

    async def handler(*, db, task):
        del db, task
        nonlocal calls
        calls += 1
        await _record_request()
        if calls == 1:
            raise LLMTimeoutError("temporary provider timeout")
        return {"ok": True}

    registry.register(
        task_type,
        handler,
        owner_scope="global",
        recovery_policy="auto_requeue",
        max_attempts=3,
        retry_transient_llm_errors=True,
        root_capability_id="writing.generate",
    )
    task_id = uuid.uuid4()
    try:
        task_id = await _enqueue(sessions, task_type, meta={})
        worker = TaskWorker(
            db_manager=_TaskManager(test_engine, sessions),
            heartbeat_interval=60.0,
        )

        first = await worker.run_once()
        assert first is not None and first.status == "pending"
        async with sessions() as db:
            stored = await db.get(AsyncTask, task_id)
            assert stored is not None
            # 缺陷一回归：特殊 transient requeue 必须先持久化本次 attempt 回执。
            lifecycle = (stored.result or {})["lifecycle"]
            assert lifecycle["reason"] == "handler_error"
            assert lifecycle["transitions"][-1]["to"] == "pending"
            assert lifecycle["transitions"][-1]["reason"] == "handler_error"
            requeued = _stored_envelope(stored)
            assert requeued is not None
            assert requeued.requests_started == 1
            assert requeued.requests_settled == 1
            assert requeued.status is AIRunStatus.running

        second = await worker.run_once()
        assert second is not None and second.status == "done"
        async with sessions() as db:
            stored = await db.get(AsyncTask, task_id)
            assert stored is not None
            envelope = _stored_envelope(stored)
            assert envelope is not None
            assert envelope.run_id == str(task_id)
            assert envelope.task is not None and envelope.task.attempt == 2
            # 自动 requeue 继续累计同一 run，不重置计数。
            assert envelope.requests_started == 2
            assert envelope.requests_settled == 2
            assert envelope.status is AIRunStatus.succeeded
            assert calls == 2
    finally:
        registry.unregister(task_type)
        await _cleanup(sessions, [task_id])


@pytest.mark.asyncio
async def test_non_transient_llm_error_is_not_auto_requeued_for_llm_tasks(
    test_engine,
) -> None:
    """缺陷二回归：真实 enqueuer 冻结 auto_requeue 后非 transient LLM 错误仍终态。"""
    sessions = async_sessionmaker(test_engine, expire_on_commit=False, autoflush=False)
    task_type = f"w2-envelope-terminal-{uuid.uuid4().hex}"
    registry = TaskRegistry()
    calls = 0

    async def handler(*, db, task):
        del db, task
        nonlocal calls
        calls += 1
        raise LLMAuthError("bad credentials")

    registry.register(
        task_type,
        handler,
        owner_scope="global",
        recovery_policy="auto_requeue",
        max_attempts=3,
        retry_transient_llm_errors=True,
    )
    task_id = uuid.uuid4()
    try:
        task_id = await _enqueue(sessions, task_type, meta={})
        worker = TaskWorker(
            db_manager=_TaskManager(test_engine, sessions),
            heartbeat_interval=60.0,
        )
        returned = await worker.run_once()

        assert returned is not None
        assert returned.status == "failed"
        assert returned.attempt == 1
        assert calls == 1
        async with sessions() as db:
            stored = await db.get(AsyncTask, task_id)
            assert stored is not None
            envelope = _stored_envelope(stored)
            assert envelope is not None
            assert envelope.status is AIRunStatus.failed
        # 不能落回 pending，否则会白白重放不可重试的 provider 错误。
        assert await worker.run_once() is None
    finally:
        registry.unregister(task_type)
        await _cleanup(sessions, [task_id])


@pytest.mark.asyncio
async def test_plain_non_llm_auto_requeue_semantics_are_unchanged(test_engine) -> None:
    sessions = async_sessionmaker(test_engine, expire_on_commit=False, autoflush=False)
    task_type = f"w2-envelope-plain-requeue-{uuid.uuid4().hex}"
    registry = TaskRegistry()

    async def handler(*, db, task):
        del db, task
        raise RuntimeError("transient cleanup failure")

    registry.register(
        task_type,
        handler,
        owner_scope="global",
        recovery_policy="auto_requeue",
        max_attempts=2,
    )
    task_id = uuid.uuid4()
    try:
        task_id = await _enqueue(sessions, task_type, meta={})
        returned = await TaskWorker(
            db_manager=_TaskManager(test_engine, sessions),
            heartbeat_interval=60.0,
        ).run_once()

        assert returned is not None
        assert returned.status == "pending"
        assert returned.attempt == 1
        assert returned.finished_at is None
        assert returned.lease_id is None
        assert (returned.result or {})["lifecycle"]["reason"] == "handler_error"
        async with sessions() as db:
            stored = await db.get(AsyncTask, task_id)
            assert stored is not None
            envelope = _stored_envelope(stored)
            assert envelope is not None
            # 任务回到 pending，run 保持 running 等待下一次领取。
            assert envelope.status is AIRunStatus.running
    finally:
        registry.unregister(task_type)
        await _cleanup(sessions, [task_id])


@pytest.mark.asyncio
async def test_failure_then_manual_resume_continues_the_same_run(test_engine) -> None:
    sessions = async_sessionmaker(test_engine, expire_on_commit=False, autoflush=False)
    task_type = f"w2-envelope-resume-{uuid.uuid4().hex}"
    registry = TaskRegistry()
    novel_id = str(uuid.uuid4())
    calls = 0

    async def handler(*, db, task):
        del db
        nonlocal calls
        calls += 1
        await _record_request()
        if calls == 1:
            task.result = {"recovery_required": True, "phase": "provider"}
            raise RuntimeError("provider phase failed")
        return {"ok": True}

    registry.register(
        task_type,
        handler,
        recovery_policy="manual_resume",
        max_attempts=1,
        root_capability_id="writing.generate",
    )
    task_id = uuid.uuid4()
    try:
        task_id = await _enqueue(
            sessions,
            task_type,
            meta={"recovery_required": True},
            novel_id=novel_id,
        )
        worker = TaskWorker(
            db_manager=_TaskManager(test_engine, sessions),
            heartbeat_interval=60.0,
        )
        failed = await worker.run_once()
        assert failed is not None and failed.status == "failed"
        async with sessions() as db:
            stored = await db.get(AsyncTask, task_id)
            assert stored is not None
            envelope = _stored_envelope(stored)
            assert envelope is not None
            assert envelope.status is AIRunStatus.failed
            assert envelope.requests_started == 1

        async with sessions.begin() as db:
            contract = await TaskLifecycleService().resume_manual(
                db,
                task_id=str(task_id),
                task_types={task_type},
                novel_id=novel_id,
            )
            assert contract.status == "pending"

        resumed = await worker.run_once(task_id=task_id, novel_id=novel_id)
        assert resumed is not None and resumed.status == "done"
        async with sessions() as db:
            stored = await db.get(AsyncTask, task_id)
            assert stored is not None
            envelope = _stored_envelope(stored)
            assert envelope is not None
            # manual resume 复用同一 run 与同一累计计数。
            assert envelope.run_id == str(task_id)
            assert envelope.task is not None and envelope.task.attempt == 2
            assert envelope.requests_started == 2
            assert envelope.requests_settled == 2
            assert envelope.status is AIRunStatus.succeeded
    finally:
        registry.unregister(task_type)
        await _cleanup(sessions, [task_id])


@pytest.mark.asyncio
async def test_cancel_finishes_the_run_without_resetting_counts(test_engine) -> None:
    sessions = async_sessionmaker(test_engine, expire_on_commit=False, autoflush=False)
    task_type = f"w2-envelope-cancel-{uuid.uuid4().hex}"
    registry = TaskRegistry()

    async def handler(*, db, task):
        del db, task
        await _record_request()
        raise asyncio.CancelledError

    registry.register(
        task_type,
        handler,
        owner_scope="global",
        recovery_policy="auto_requeue",
        max_attempts=3,
        retry_transient_llm_errors=True,
    )
    task_id = uuid.uuid4()
    try:
        task_id = await _enqueue(sessions, task_type, meta={})
        returned = await TaskWorker(
            db_manager=_TaskManager(test_engine, sessions),
            heartbeat_interval=60.0,
        ).run_once()

        assert returned is not None and returned.status == "cancelled"
        async with sessions() as db:
            stored = await db.get(AsyncTask, task_id)
            assert stored is not None
            envelope = _stored_envelope(stored)
            assert envelope is not None
            assert envelope.run_id == str(task_id)
            assert envelope.status is AIRunStatus.cancelled
            assert envelope.requests_started == 1
            assert envelope.requests_settled == 1
    finally:
        registry.unregister(task_type)
        await _cleanup(sessions, [task_id])


async def _seed_in_flight_run(*, run_id: uuid.UUID, novel_id: str) -> dict[str, Any]:
    ledger = new_ai_run_envelope(
        operation_id=str(run_id),
        run_id=str(run_id),
        root_capability_id="writing.generate",
        novel_id=novel_id,
        request_limit=10,
        task=AITaskIdentityV1(task_id=str(run_id), attempt=1, lease_id="old-lease"),
    )
    with managed_step_scope(_step_context()):
        await ledger.reserve()
    return ledger.snapshot().model_dump(mode="json")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("policy", "max_attempts", "expected_status", "expected_run_status"),
    [
        ("auto_requeue", 3, "pending", AIRunStatus.running),
        ("manual_resume", 1, "failed", AIRunStatus.failed),
    ],
)
async def test_stale_recovery_converges_in_flight_into_the_same_run(
    test_engine,
    policy: str,
    max_attempts: int,
    expected_status: str,
    expected_run_status: AIRunStatus,
) -> None:
    sessions = async_sessionmaker(test_engine, expire_on_commit=False, autoflush=False)
    task_id = uuid.uuid4()
    novel_id = str(uuid.uuid4())
    lease_id = str(uuid.uuid4())
    stale_at = datetime.now(UTC) - timedelta(hours=1)
    envelope = await _seed_in_flight_run(run_id=task_id, novel_id=novel_id)
    envelope["task"] = {
        "task_id": str(task_id),
        "attempt": 1,
        "lease_id": lease_id,
    }
    try:
        async with sessions.begin() as db:
            db.add(
                AsyncTask(
                    id=task_id,
                    novel_id=uuid.UUID(novel_id),
                    task_type="w2-envelope-stale",
                    status="running",
                    meta={"novel_id": novel_id, AI_RUN_ENVELOPE_KEY: envelope},
                    recovery_policy=policy,
                    max_attempts=max_attempts,
                    attempt=1,
                    lease_id=lease_id,
                    started_at=stale_at,
                    heartbeat_at=stale_at,
                )
            )

        async with sessions.begin() as db:
            counts = await TaskLifecycleService().recover_stale(
                db,
                max_heartbeat_gap=120,
            )
        assert counts["auto_requeued"] + counts["failed"] == 1

        async with sessions() as db:
            stored = await db.get(AsyncTask, task_id)
            assert stored is not None
            assert stored.status == expected_status
            assert stored.lease_id is None
            recovered = _stored_envelope(stored)
            assert recovered is not None
            assert recovered.run_id == str(task_id)
            assert recovered.status is expected_run_status
            assert recovered.requests_started == 1
            assert recovered.requests_settled == 0
            # 未 settle 的请求收敛为 unknown/possible，绝不写成零用量。
            assert recovered.requests_unknown == 1
            assert recovered.charge_state is AIChargeState.possible
            assert recovered.usage_complete is False
            assert all(
                attempt.outcome.value != "in_flight"
                for attempt in recovered.recent_attempts
            )
    finally:
        await _cleanup(sessions, [task_id])


@pytest.mark.asyncio
async def test_external_cancel_finishes_the_run_and_converges_in_flight(
    test_engine,
) -> None:
    """API/域外取消同样结束同一 run，未 settle 请求转 unknown/possible。"""
    sessions = async_sessionmaker(test_engine, expire_on_commit=False, autoflush=False)
    task_id = uuid.uuid4()
    novel_id = str(uuid.uuid4())
    lease_id = str(uuid.uuid4())
    envelope = await _seed_in_flight_run(run_id=task_id, novel_id=novel_id)
    envelope["task"] = {
        "task_id": str(task_id),
        "attempt": 1,
        "lease_id": lease_id,
    }
    try:
        async with sessions.begin() as db:
            db.add(
                AsyncTask(
                    id=task_id,
                    novel_id=uuid.UUID(novel_id),
                    task_type="writing_generate",
                    status="running",
                    meta={"novel_id": novel_id, AI_RUN_ENVELOPE_KEY: envelope},
                    recovery_policy="auto_requeue",
                    max_attempts=3,
                    attempt=1,
                    lease_id=lease_id,
                )
            )
        async with sessions.begin() as db:
            contract = await TaskLifecycleService().cancel_exact(
                db,
                task_id=str(task_id),
                task_types={"writing_generate"},
                novel_id=novel_id,
                transition_reason="user_cancelled",
            )
        assert contract.status == "cancelled"
        async with sessions() as db:
            stored = await db.get(AsyncTask, task_id)
            assert stored is not None
            finished = _stored_envelope(stored)
            assert finished is not None
            assert finished.run_id == str(task_id)
            assert finished.status is AIRunStatus.cancelled
            assert finished.requests_started == 1
            assert finished.requests_unknown == 1
            assert finished.charge_state is AIChargeState.possible
    finally:
        await _cleanup(sessions, [task_id])


@pytest.mark.asyncio
async def test_lost_lease_never_writes_the_run_envelope(test_engine) -> None:
    sessions = async_sessionmaker(test_engine, expire_on_commit=False, autoflush=False)
    task_id = uuid.uuid4()
    lease_id = str(uuid.uuid4())
    try:
        async with sessions.begin() as db:
            db.add(
                AsyncTask(
                    id=task_id,
                    task_type="w2-envelope-lease",
                    status="running",
                    meta={},
                    attempt=1,
                    lease_id=lease_id,
                )
            )

        payload = {"version": 1, "run_id": str(task_id)}
        async with sessions.begin() as db:
            rejected = await TaskLifecycleService().checkpoint_run_envelope(
                db,
                task_id=task_id,
                lease_id=str(uuid.uuid4()),
                envelope=payload,
            )
        assert rejected is False
        async with sessions() as db:
            stored = await db.get(AsyncTask, task_id)
            assert stored is not None
            assert AI_RUN_ENVELOPE_KEY not in (stored.meta or {})

        async with sessions.begin() as db:
            accepted = await TaskLifecycleService().checkpoint_run_envelope(
                db,
                task_id=task_id,
                lease_id=lease_id,
                envelope=payload,
            )
        assert accepted is True
        async with sessions() as db:
            stored = await db.get(AsyncTask, task_id)
            assert stored is not None
            assert (stored.meta or {})[AI_RUN_ENVELOPE_KEY] == payload
            # 窄 merge 只动私有信封，业务 meta 键保持原样。
            assert stored.meta.get("novel_id") is None
    finally:
        await _cleanup(sessions, [task_id])


@pytest.mark.asyncio
async def test_completed_payload_never_exposes_private_run_envelope(test_engine) -> None:
    """Story Outline 采用路径读 result 顶层键，私有信封只在 meta。"""
    sessions = async_sessionmaker(test_engine, expire_on_commit=False, autoflush=False)
    task_id = uuid.uuid4()
    novel_id = str(uuid.uuid4())
    result = {
        "managed_llm_steps": [{"step_name": "story.outline.candidate"}],
        "knowledge_review": {"status": "passed"},
    }
    try:
        async with sessions.begin() as db:
            db.add(
                AsyncTask(
                    id=task_id,
                    novel_id=uuid.UUID(novel_id),
                    task_type="story_outline_generate",
                    status="done",
                    meta={"novel_id": novel_id, AI_RUN_ENVELOPE_KEY: {"version": 1}},
                    result=result,
                )
            )
        async with sessions() as db:
            contract = await TaskLifecycleService().get_completed_payload(
                db,
                task_id=str(task_id),
                task_type="story_outline_generate",
                novel_id=novel_id,
            )
        assert contract is not None
        assert contract.result == result
        assert set(contract.result) == {"managed_llm_steps", "knowledge_review"}
    finally:
        await _cleanup(sessions, [task_id])


@pytest.mark.asyncio
async def test_inline_execution_injects_own_run_identity(test_engine) -> None:
    from infrastructure.tasks.inline import run_task_inline

    sessions = async_sessionmaker(test_engine, expire_on_commit=False, autoflush=False)
    task_type = f"w2-envelope-inline-{uuid.uuid4().hex}"
    registry = TaskRegistry()
    observed: dict[str, Any] = {}

    async def handler(*, db, task):
        del db
        ledger = current_ai_run_envelope()
        assert ledger is not None
        snapshot = ledger.snapshot()
        observed["run_id"] = snapshot.run_id
        observed["task"] = snapshot.task
        return {"ok": True}

    registry.register(task_type, handler, owner_scope="global")
    task_id = uuid.uuid4()
    try:
        task_id = await _enqueue(sessions, task_type, meta={})
        async with sessions() as db:
            result = await run_task_inline(
                db,
                task_id=str(task_id),
                expected_task_type=task_type,
            )
        assert result == {"ok": True}
        assert observed["run_id"] == str(task_id)
        identity = observed["task"]
        assert identity is not None
        assert identity.task_id == str(task_id)
        assert identity.attempt == 1
        assert identity.lease_id
        async with sessions() as db:
            stored = await db.get(AsyncTask, task_id)
            assert stored is not None
            envelope = _stored_envelope(stored)
            assert envelope is not None
            assert envelope.status is AIRunStatus.succeeded
            assert envelope.run_id == str(task_id)
    finally:
        registry.unregister(task_type)
        await _cleanup(sessions, [task_id])


@pytest.mark.asyncio
async def test_inline_child_reuses_the_active_parent_run(test_engine) -> None:
    """内联子任务注入父 run，不另开账本、不覆盖父级执行载体。"""
    from infrastructure.tasks.inline import run_task_inline

    sessions = async_sessionmaker(test_engine, expire_on_commit=False, autoflush=False)
    task_type = f"w2-envelope-inline-child-{uuid.uuid4().hex}"
    registry = TaskRegistry()
    novel_id = str(uuid.uuid4())
    parent_run_id = uuid.uuid4()
    observed: dict[str, Any] = {}

    async def handler(*, db, task):
        del db, task
        ledger = current_ai_run_envelope()
        assert ledger is not None
        observed["run_id"] = ledger.run_id
        return {"ok": True}

    registry.register(task_type, handler)
    task_id = uuid.uuid4()
    try:
        task_id = await _enqueue(
            sessions,
            task_type,
            meta={"novel_id": novel_id},
            novel_id=novel_id,
        )
        parent = new_ai_run_envelope(
            operation_id=str(parent_run_id),
            run_id=str(parent_run_id),
            root_capability_id="assistant.turn",
            novel_id=novel_id,
            request_limit=10,
        )
        async with sessions() as db:
            with ai_run_scope(parent):
                result = await run_task_inline(
                    db,
                    task_id=str(task_id),
                    expected_task_type=task_type,
                )
        assert result == {"ok": True}
        assert observed["run_id"] == str(parent_run_id)
        async with sessions() as db:
            stored = await db.get(AsyncTask, task_id)
            assert stored is not None
            # 子任务不建立自己的信封：run 属于父操作。
            assert AI_RUN_ENVELOPE_KEY not in (stored.meta or {})
    finally:
        registry.unregister(task_type)
        await _cleanup(sessions, [task_id])
