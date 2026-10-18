"""Goal ledger checkpoints must not wait on the request's own PostgreSQL row lock."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import replace
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.container import container_scope
from core.errors import ConflictError
from modules.account.models import Account
from modules.assistant.goal_runs import service
from modules.assistant.goal_runs.contracts import (
    GoalAction,
    GoalPlanApproval,
    GoalReplanRequest,
    GoalResume,
)
from modules.assistant.models import AssistantRun
from modules.assistant.tests.test_goal_runs import (
    _install_offline_goal_planner,
    _plan,
    _read_operation,
    _start_request,
)
from modules.project.models import Project
from tests.e2e.config import DATABASE_URL

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]


@pytest.mark.parametrize(
    "action",
    [
        "approve",
        "restart",
        "cancel",
        "concurrent",
        "advance_concurrent",
        "cancel_during",
        "pause_during",
    ],
)
async def test_goal_author_action_does_not_self_lock_checkpoint(monkeypatch, action):
    def new_engine():
        return create_async_engine(
            DATABASE_URL,
            connect_args={"server_settings": {"statement_timeout": "1500"}},
            pool_size=2 if action in {"cancel_during", "pause_during"} else 1,
            max_overflow=0,
            pool_timeout=1,
        )

    engine = new_engine()
    maker = async_sessionmaker(engine, expire_on_commit=False)
    owner_id = uuid.uuid4()
    project_id = uuid.uuid4()
    async with maker() as db:
        db.add(Account(id=owner_id, support_code=owner_id.hex[:16]))
        db.add(Project(id=project_id, owner_id=owner_id, title="离线目标事务测试"))
        await db.commit()

    async def require_owned_project(*_args, **_kwargs):
        return None

    async def project_context(*_args, **_kwargs):
        return Project(
            id=project_id,
            owner_id=owner_id,
            title="离线目标事务测试",
            genre="奇幻",
            tone="简洁",
            language="zh",
            current_stage="writing",
        )

    plan = _plan()
    operation = _read_operation()
    entered = asyncio.Event()
    release = asyncio.Event()
    prepare_calls = 0
    if action in {"concurrent", "advance_concurrent", "cancel_during", "pause_during"}:

        async def blocked_prepare(_db, _novel_id, args, *, context=None):
            nonlocal prepare_calls
            prepare_calls += 1
            entered.set()
            await release.wait()
            return {"query": args.query, "result": "read receipt"}

        operation = replace(operation, prepare=blocked_prepare)
    monkeypatch.setattr(service, "_require_goal_project", require_owned_project)
    monkeypatch.setattr(service, "get_any_project_context", project_context)
    monkeypatch.setattr(
        service, "_operation_registry", lambda: {"project.goal_test.read": operation}
    )
    _install_offline_goal_planner(monkeypatch, plan)
    request = _start_request(project_id)
    checkpoint_errors: list[str] = []
    write_checkpoint = service._write_envelope_checkpoint

    async def observed_checkpoint(*args):
        try:
            await write_checkpoint(*args)
        except BaseException as error:
            checkpoint_errors.append(type(error).__name__)
            raise

    monkeypatch.setattr(service, "_write_envelope_checkpoint", observed_checkpoint)
    try:
        with container_scope(
            {"assistant.operations": {"project.goal_test.read": operation}}
        ):
            async with maker() as db:
                prepared = await service.start_goal(db, request, str(owner_id))
                assert prepared["status"] == "waiting_approval"
                created = await db.get(AssistantRun, uuid.UUID(prepared["run_id"]))
                assert created is not None
                original_started_at = created.checkpoint_json["goal"]["envelope"][
                    "started_at"
                ]
            if action == "restart":
                # The next action has no process-local connection or ORM state.
                await engine.dispose()
                engine = new_engine()
                maker = async_sessionmaker(engine, expire_on_commit=False)
            # Reopen on a different session: the approved action must use the
            # persisted ledger and the same original started_at.
            approval = GoalPlanApproval(
                expected_revision=prepared["revision"],
                plan=plan,
                budget=request.budget,
                auto_r2=False,
            )
            if action in {
                "concurrent",
                "advance_concurrent",
                "cancel_during",
                "pause_during",
            }:

                async def approve_once():
                    async with maker() as action_db:
                        return await service.approve_goal_plan(
                            action_db,
                            str(project_id),
                            prepared["run_id"],
                            approval,
                            str(owner_id),
                        )

                first = asyncio.create_task(approve_once())
                try:
                    await asyncio.wait_for(entered.wait(), timeout=3)
                    if action == "concurrent":
                        with pytest.raises(ConflictError, match="正在处理"):
                            await approve_once()
                    elif action == "advance_concurrent":
                        async with maker() as advance_db:
                            with pytest.raises(ConflictError, match="正在处理"):
                                await service.advance_goal(
                                    advance_db,
                                    str(project_id),
                                    prepared["run_id"],
                                    str(owner_id),
                                    GoalAction(expected_revision=prepared["revision"]),
                                )
                    else:
                        async with maker() as cancel_db:
                            current = await service.get_goal(
                                cancel_db,
                                str(project_id),
                                prepared["run_id"],
                                str(owner_id),
                            )
                            stop = (
                                service.pause_goal
                                if action == "pause_during"
                                else service.cancel_goal
                            )
                            stopped = await stop(
                                cancel_db,
                                str(project_id),
                                prepared["run_id"],
                                GoalAction(expected_revision=current["revision"]),
                                str(owner_id),
                            )
                        assert stopped["stop_code"] == (
                            "pause_requested"
                            if action == "pause_during"
                            else "cancel_requested"
                        )
                finally:
                    release.set()
                result = await first
                if action == "pause_during":
                    assert result["stop_code"] == "paused"
                    async with maker() as resume_db:
                        result = await service.resume_goal(
                            resume_db,
                            str(project_id),
                            prepared["run_id"],
                            GoalResume(
                                expected_revision=result["revision"],
                                budget=request.budget,
                            ),
                            str(owner_id),
                        )
                assert result["status"] == (
                    "cancelled" if action == "cancel_during" else "completed"
                )
                assert prepare_calls == 1
            else:
                async with maker() as db:
                    if action in {"approve", "restart"}:
                        result = await asyncio.wait_for(
                            service.approve_goal_plan(
                                db,
                                str(project_id),
                                prepared["run_id"],
                                approval,
                                str(owner_id),
                            ),
                            timeout=5,
                        )
                        assert result["status"] == "completed"
                    else:
                        result = await asyncio.wait_for(
                            service.cancel_goal(
                                db,
                                str(project_id),
                                prepared["run_id"],
                                GoalAction(expected_revision=prepared["revision"]),
                                str(owner_id),
                            ),
                            timeout=5,
                        )
                        assert result["status"] == "cancelled"
            assert checkpoint_errors == []
            async with maker() as verify:
                stored = await verify.get(AssistantRun, uuid.UUID(prepared["run_id"]))
                assert stored is not None
                ledger = stored.checkpoint_json["goal"]["envelope"]
                assert ledger["started_at"] == original_started_at
                assert ledger["requests_started"] == 2
                assert ledger["status"] == (
                    "cancelled" if action in {"cancel", "cancel_during"} else "succeeded"
                )
    finally:
        await engine.dispose()


async def test_crashed_planner_recovers_in_flight_charge_without_reissuing(monkeypatch):
    class ProcessExited(BaseException):
        pass

    engine = create_async_engine(DATABASE_URL, pool_size=1, max_overflow=0)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    owner_id, project_id = uuid.uuid4(), uuid.uuid4()
    async with maker.begin() as db:
        db.add(Account(id=owner_id, support_code=owner_id.hex[:16]))
        db.add(Project(id=project_id, owner_id=owner_id, title="Goal crash"))

    operation = _read_operation()

    async def owned(*_args, **_kwargs):
        return None

    async def project(*_args, **_kwargs):
        return Project(id=project_id, owner_id=owner_id, title="Goal crash")

    async def snapshot(*_args, **_kwargs):
        return {"provider_id": "test", "model": "offline", "verified": True}

    async def no_trace(*_args, **_kwargs):
        return False

    calls = 0

    async def crash_after_reservation(
        _db, _run, _goal, _catalog, _reads, *, envelope, budget
    ):
        from infrastructure.llm.workflow_budget import current_workflow_budget

        nonlocal calls
        calls += 1
        client = SimpleNamespace(
            runtime_scope={}, profile_summary={"provider_id": "test", "model": "offline"}
        )
        meter = service.GoalWorkflowCounter(envelope, budget)
        with (
            service.workflow_budget(meter, service._noop_checkpoint),
            service.managed_step_scope(
                service._managed_context(
                    client, step=service.GOAL_PLAN_STEP, fingerprint="a" * 64
                )
            ),
        ):
            reservation = await envelope.reserve()
            try:
                assert current_workflow_budget() is not None
                await current_workflow_budget().before_request()
            except BaseException:
                await envelope.discard(reservation)
                raise
        raise ProcessExited

    monkeypatch.setattr(service, "_require_goal_project", owned)
    monkeypatch.setattr(service, "get_any_project_context", project)
    monkeypatch.setattr(service, "build_project_llm_execution_snapshot", snapshot)
    monkeypatch.setattr(service, "_trace_enabled", no_trace)
    monkeypatch.setattr(service, "_select_plan", crash_after_reservation)
    monkeypatch.setattr(
        service, "_operation_registry", lambda: {"project.goal_test.read": operation}
    )
    monkeypatch.setattr(service, "_feature_enabled", lambda _novel_id: True)
    request = _start_request(project_id)
    try:
        with container_scope(
            {"assistant.operations": {"project.goal_test.read": operation}}
        ):
            async with maker() as db:
                with pytest.raises(ProcessExited):
                    await service.start_goal(db, request, str(owner_id))
            # New engine and session represent a process restart. The saved
            # reservation is unresolved and must never turn into a free retry.
            await engine.dispose()
            engine = create_async_engine(DATABASE_URL, pool_size=1, max_overflow=0)
            maker = async_sessionmaker(engine, expire_on_commit=False)
            async with maker() as db:
                active = await service.get_active_goal(db, str(project_id), str(owner_id))
                assert active is not None and active["status"] == "running"
                recovered = await service.replan_goal(
                    db,
                    str(project_id),
                    active["run_id"],
                    GoalReplanRequest(
                        expected_revision=active["revision"], reason="恢复规划"
                    ),
                    str(owner_id),
                )
                assert recovered["stop_code"] == "unknown_charge"
                assert recovered["can_replan"] is False
                stored = await db.get(AssistantRun, uuid.UUID(active["run_id"]))
                assert stored is not None
                ledger = stored.checkpoint_json["goal"]["envelope"]
                assert ledger["requests_started"] == 1
                assert ledger["requests_unknown"] == 1
                assert calls == 2  # recovery checked the ledger, never sent a request
    finally:
        await engine.dispose()
