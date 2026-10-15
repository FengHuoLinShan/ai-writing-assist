"""Goal runs use one durable plan/run ledger and preserve active uniqueness."""

import uuid
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from core.container import container_scope
from core.errors import NotFoundError
from modules.account.facade import current_account_id
from modules.assistant.contracts import AssistantOperation
from modules.assistant.goal_runs.contracts import (
    GoalAction,
    GoalBudget,
    GoalPlan,
    GoalPlanApproval,
    GoalResume,
    GoalRunStart,
    GoalStepApproval,
)
from modules.assistant.models import AssistantRun


class ReadProject(BaseModel):
    query: str


class EditArtifact(BaseModel):
    target_id: str
    value: str


async def _read_project(_db, _novel_id, args, *, context=None):
    return {"query": args.query, "result": "read receipt"}


def _read_operation():
    return AssistantOperation(
        label="读取项目资料",
        schema=ReadProject,
        prepare=_read_project,
        permission="read",
        risk_level="R0",
        fee_category="free",
        target_type="project",
    )


async def _preview_artifact_edit(_db, _novel_id, args, *, context=None):
    return {"target_id": args.target_id, "before": "原值", "after": args.value}


async def _apply_artifact_edit(_db, _novel_id, args, _preview, *, context=None):
    return {"target_id": args.target_id, "value": args.value}


def _edit_operation():
    return AssistantOperation(
        label="修改对象",
        schema=EditArtifact,
        prepare=_preview_artifact_edit,
        apply=_apply_artifact_edit,
        permission="confirm",
        risk_level="R2",
        fee_category="free",
        target_type="artifact",
    )


class _PlanningClient:
    runtime_scope = {"profile_source": "test"}
    profile_summary = {
        "provider_id": "test",
        "model": "offline-goal-plan-stub",
    }

    def __init__(self, plan, *, unknown_charge=False):
        self.plan = plan
        self.unknown_charge = unknown_charge

    async def generate_structured(self, _request, _response_schema, **_kwargs):
        from infrastructure.llm.schemas import AIRequestOutcome, LLMUsage
        from infrastructure.llm.workflow_budget import (
            current_ai_run_envelope,
            current_workflow_budget,
        )

        budget = current_workflow_budget()
        envelope = current_ai_run_envelope()
        assert budget is not None and envelope is not None
        reservation = await envelope.reserve()
        try:
            await budget.before_request()
        except BaseException:
            await envelope.discard(reservation)
            raise
        if self.unknown_charge:
            raise TimeoutError("offline unknown result")
        usage = LLMUsage(prompt_tokens=12, completion_tokens=8)
        await envelope.settle(
            reservation,
            usage=usage,
            outcome=AIRequestOutcome.succeeded,
        )
        await budget.completed(usage)
        return self.plan


@pytest.mark.asyncio
async def test_goal_project_gate_requires_enabled_allowlisted_owned_author_project(
    monkeypatch,
):
    from core.config import get_settings
    from modules.assistant.goal_runs import service

    owner_id = str(current_account_id())
    settings = replace(
        get_settings(),
        assistant_enabled=True,
        assistant_goal_runs_enabled=True,
        assistant_goal_runs_project_allowlist=("novel-a",),
    )
    monkeypatch.setattr(service, "get_settings", lambda: settings)
    monkeypatch.setattr(service, "is_demo_readonly_principal", lambda: False)
    assert service._feature_enabled("novel-a") is True
    assert service._feature_enabled("novel-b") is False

    settings = replace(settings, assistant_goal_runs_enabled=False)
    assert service._feature_enabled("novel-a") is False
    settings = replace(
        settings,
        assistant_goal_runs_enabled=True,
        assistant_enabled=False,
    )
    assert service._feature_enabled("novel-a") is False
    settings = replace(settings, assistant_enabled=True)

    async def active_project(*_args, **_kwargs):
        return None

    project = SimpleNamespace(project_kind="author", owner_id=owner_id)

    async def project_context(*_args, **_kwargs):
        return project

    monkeypatch.setattr(service, "require_active_project", active_project)
    monkeypatch.setattr(service, "get_any_project_context", project_context)

    await service._require_goal_project(None, "novel-a", owner_id)
    with pytest.raises(NotFoundError):
        await service._require_goal_project(None, "novel-b", owner_id)
    with pytest.raises(NotFoundError):
        await service._require_goal_project(None, "novel-a", "another-owner")

    project.project_kind = "rp"
    with pytest.raises(NotFoundError):
        await service._require_goal_project(None, "novel-a", owner_id)

    project.project_kind = "author"
    monkeypatch.setattr(service, "is_demo_readonly_principal", lambda: True)
    with pytest.raises(NotFoundError):
        await service._require_goal_project(None, "novel-a", owner_id)


def _plan():
    return GoalPlan(
        title="核对项目资料",
        summary="读取一项資料并保存回执。",
        steps=[
            {
                "step_id": "read_project",
                "operation_id": "project.goal_test.read",
                "parameters": {"query": "目标工作资料"},
                "intent": "读取项目资料",
            }
        ],
    )


def _start_request(novel_id):
    return GoalRunStart(
        novel_id=novel_id,
        request_id=uuid.uuid4(),
        goal="核对当前项目资料",
        budget=GoalBudget(
            requests=4,
            possible_charge_requests=4,
            tokens=4096,
            time_limit_seconds=600,
        ),
    )


def _install_offline_goal_planner(monkeypatch, plan, *, unknown_charge=False):
    from modules.assistant.goal_runs import service

    async def project_snapshot(*_args, **_kwargs):
        return _offline_snapshot()

    async def trace_disabled(*_args, **_kwargs):
        return False

    @asynccontextmanager
    async def offline_client(*_args, **_kwargs):
        yield _PlanningClient(plan, unknown_charge=unknown_charge)

    monkeypatch.setattr(service, "_feature_enabled", lambda _novel_id: True)
    monkeypatch.setattr(service, "_trace_enabled", trace_disabled)
    monkeypatch.setattr(
        service,
        "build_project_llm_execution_snapshot",
        project_snapshot,
    )
    monkeypatch.setattr(service, "open_project_snapshot_llm_client", offline_client)


async def _approve_goal_plan(
    db, novel_id: str, owner_id: str, plan: GoalPlan, monkeypatch
):
    from modules.assistant.goal_runs import service

    _install_offline_goal_planner(monkeypatch, plan)
    request = _start_request(uuid.UUID(novel_id))
    prepared = await service.start_goal(db, request, owner_id)
    approved = await service.approve_goal_plan(
        db,
        novel_id=novel_id,
        run_id=prepared["run_id"],
        owner_id=owner_id,
        data=GoalPlanApproval(
            expected_revision=prepared["revision"],
            plan=plan,
            budget=request.budget,
            auto_r2=True,
        ),
    )
    return service, prepared, approved


@pytest.mark.asyncio
async def test_goal_start_plan_approval_and_read_step_share_one_checkpointed_budget(
    db_session, test_project_id, monkeypatch
):
    from modules.assistant.goal_runs import service

    owner_id = str(current_account_id())
    plan = _plan()
    operation = _read_operation()
    project = SimpleNamespace(
        project_kind="author",
        owner_id=owner_id,
        title="测试小说",
        genre="奇幻",
        tone="沉静",
        language="zh",
        current_stage="世界构建",
    )

    async def no_project_gate(*_args, **_kwargs):
        return None

    async def project_context(*_args, **_kwargs):
        return project

    async def trace_disabled(*_args, **_kwargs):
        return False

    async def project_snapshot(*_args, **_kwargs):
        return _offline_snapshot()

    @asynccontextmanager
    async def offline_client(*_args, **_kwargs):
        yield _PlanningClient(plan)

    monkeypatch.setattr(service, "_require_goal_project", no_project_gate)
    monkeypatch.setattr(
        service,
        "_operation_registry",
        lambda: {operation.op_id or "project.goal_test.read": operation},
    )
    monkeypatch.setattr(service, "get_any_project_context", project_context)
    monkeypatch.setattr(service, "_trace_enabled", trace_disabled)
    monkeypatch.setattr(
        service,
        "build_project_llm_execution_snapshot",
        project_snapshot,
    )
    monkeypatch.setattr(service, "open_project_snapshot_llm_client", offline_client)

    with container_scope({"assistant.operations": {"project.goal_test.read": operation}}):
        request = _start_request(uuid.UUID(test_project_id))
        prepared = await service.start_goal(db_session, request, owner_id)
        assert prepared["status"] == "waiting_approval"
        assert prepared["phase"] == "plan_review", prepared
        assert prepared["budget"]["used"]["requests"] == 1
        run_id = uuid.UUID(prepared["run_id"])

        stored = await db_session.scalar(
            select(AssistantRun).where(AssistantRun.id == run_id)
        )
        assert stored is not None
        assert stored.mode == "goal"
        assert stored.session_id is None
        assert stored.checkpoint_json["goal"]["envelope"]["version"] == 3
        assert stored.checkpoint_json["goal"]["envelope"]["requests_started"] == 1

        repeated = await service.start_goal(db_session, request, owner_id)
        assert repeated["run_id"] == prepared["run_id"]
        assert repeated["budget"]["used"]["requests"] == 1

        completed = await service.approve_goal_plan(
            db_session,
            novel_id=test_project_id,
            run_id=prepared["run_id"],
            owner_id=owner_id,
            data=GoalPlanApproval(
                expected_revision=prepared["revision"],
                plan=plan,
                budget=request.budget,
                auto_r2=False,
            ),
        )

    assert completed["status"] == "completed"
    assert completed["progress"] == {"completed": 1, "total": 1}
    assert completed["budget"]["used"]["requests"] == 1
    assert completed["steps"][0]["status"] == "completed"
    replayed = await service.advance_goal(
        db_session,
        test_project_id,
        prepared["run_id"],
        owner_id,
        GoalAction(expected_revision=completed["revision"]),
    )
    assert replayed["status"] == "completed"
    assert replayed["budget"]["used"]["requests"] == 1


@pytest.mark.asyncio
async def test_cancel_goal_keeps_usage_and_repeated_cancel_is_idempotent(
    db_session, test_project_id, monkeypatch
):
    from infrastructure.tasks.models import AsyncTask
    from modules.assistant.goal_runs import service

    owner_id = str(current_account_id())
    plan = _plan()
    operation = _read_operation()
    project = SimpleNamespace(
        project_kind="author",
        owner_id=owner_id,
        title="测试小说",
        genre="奇幻",
        tone="沉静",
        language="zh",
        current_stage="世界构建",
    )

    async def no_project_gate(*_args, **_kwargs):
        return None

    async def project_context(*_args, **_kwargs):
        return project

    _install_offline_goal_planner(monkeypatch, plan)
    monkeypatch.setattr(service, "_require_goal_project", no_project_gate)
    monkeypatch.setattr(
        service, "_operation_registry", lambda: {"project.goal_test.read": operation}
    )
    monkeypatch.setattr(service, "get_any_project_context", project_context)

    with container_scope({"assistant.operations": {"project.goal_test.read": operation}}):
        prepared = await service.start_goal(
            db_session,
            _start_request(uuid.UUID(test_project_id)),
            owner_id,
        )
        cancelled = await service.cancel_goal(
            db_session,
            test_project_id,
            prepared["run_id"],
            GoalAction(expected_revision=prepared["revision"]),
            owner_id,
        )
        repeated = await service.cancel_goal(
            db_session,
            test_project_id,
            prepared["run_id"],
            GoalAction(expected_revision=cancelled["revision"]),
            owner_id,
        )
        stored = await service._load_goal_run(
            db_session, test_project_id, prepared["run_id"], owner_id
        )
        parent = await db_session.get(AsyncTask, stored.task_id)

    assert cancelled["status"] == "cancelled"
    assert cancelled["stop_code"] == "cancelled"
    assert cancelled["budget"]["used"]["requests"] == 1
    assert repeated["status"] == "cancelled"
    assert repeated["budget"]["used"]["requests"] == 1
    assert parent is not None and parent.status == "cancelled"


def _offline_snapshot():
    return {
        "provider_id": "test",
        "model": "offline-goal-plan-stub",
        "verified": True,
    }


async def _settle_goal_requests(service, db, run, budget, count):
    from infrastructure.llm.schemas import AIRequestOutcome, LLMUsage
    from infrastructure.llm.workflow_budget import (
        ai_run_scope,
        managed_step_scope,
        workflow_budget,
    )

    envelope = service._live_envelope(db, run)
    meter = service.GoalWorkflowCounter(envelope, budget)
    client = _PlanningClient(_plan())
    context = service._managed_context(
        client, step=service.GOAL_PLAN_STEP, fingerprint="f" * 64
    )
    with (
        ai_run_scope(envelope),
        workflow_budget(meter, service._noop_checkpoint) as workflow,
    ):
        with managed_step_scope(context):
            for _ in range(count):
                reservation = await envelope.reserve()
                await workflow.before_request()
                usage = LLMUsage(prompt_tokens=1, completion_tokens=1)
                await envelope.settle(
                    reservation,
                    usage=usage,
                    outcome=AIRequestOutcome.succeeded,
                )
                await workflow.completed(usage)


@pytest.mark.asyncio
async def test_goal_mode_and_active_partial_unique_index_are_enforced_by_sqlite(
    db_session, test_project_id
):
    owner_id = uuid.UUID(str(current_account_id()))
    novel_id = uuid.UUID(test_project_id)

    first = AssistantRun(
        novel_id=novel_id,
        owner_id=owner_id,
        operation_id=uuid.uuid4(),
        session_id=None,
        mode="goal",
        status="waiting_approval",
        request_hash="a" * 64,
        request_json={},
    )
    db_session.add(first)
    await db_session.flush()

    second_active = AssistantRun(
        novel_id=novel_id,
        owner_id=owner_id,
        operation_id=uuid.uuid4(),
        session_id=None,
        mode="goal",
        status="running",
        request_hash="b" * 64,
        request_json={},
    )
    db_session.add(second_active)
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_goal_80_percent_stop_and_resume_keep_the_original_root_ledger(
    db_session, test_project_id, monkeypatch
):
    from modules.assistant.goal_runs import service

    owner_id = str(current_account_id())
    operation = _edit_operation()
    plan = GoalPlan(
        title="修改一个对象",
        steps=[
            {
                "step_id": "edit",
                "operation_id": "project.goal_test.edit",
                "targets": [{"target_type": "artifact", "target_id": "artifact-1"}],
                "parameters": {"target_id": "artifact-1", "value": "新值"},
                "intent": "修改选中的对象",
            }
        ],
    )
    project = SimpleNamespace(
        project_kind="author",
        owner_id=owner_id,
        title="测试小说",
        genre="奇幻",
        tone="沉静",
        language="zh",
        current_stage="世界构建",
    )

    async def no_project_gate(*_args, **_kwargs):
        return None

    async def project_context(*_args, **_kwargs):
        return project

    _install_offline_goal_planner(monkeypatch, plan)
    monkeypatch.setattr(service, "_require_goal_project", no_project_gate)
    monkeypatch.setattr(
        service,
        "_operation_registry",
        lambda: {"project.goal_test.edit": operation},
    )
    monkeypatch.setattr(service, "get_any_project_context", project_context)

    with container_scope({"assistant.operations": {"project.goal_test.edit": operation}}):
        request = _start_request(uuid.UUID(test_project_id))
        prepared = await service.start_goal(db_session, request, owner_id)
        approved = await service.approve_goal_plan(
            db_session,
            novel_id=test_project_id,
            run_id=prepared["run_id"],
            owner_id=owner_id,
            data=GoalPlanApproval(
                expected_revision=prepared["revision"],
                plan=plan,
                budget=request.budget,
                auto_r2=False,
            ),
        )
        assert approved["phase"] == "step_review"
        run = await service._load_goal_run(
            db_session, test_project_id, prepared["run_id"], owner_id
        )
        goal = service._goal_state(run)
        original_started_at = goal["envelope"]["started_at"]
        await _settle_goal_requests(service, db_session, run, request.budget, 3)
        run = await service._load_goal_run(
            db_session, test_project_id, prepared["run_id"], owner_id
        )
        current = await service.goal_view(db_session, run, owner_id=owner_id)

        stopped = await service.approve_goal_step(
            db_session,
            novel_id=test_project_id,
            run_id=prepared["run_id"],
            owner_id=owner_id,
            data=GoalStepApproval(
                expected_revision=current["revision"],
                step_id="edit",
                approve=True,
            ),
        )
        assert stopped["status"] == "waiting_approval"
        assert stopped["stop_code"] == "budget_80"
        assert stopped["can_resume"] is True
        assert stopped["budget"]["used"]["requests"] == 4

        resumed = await service.resume_goal(
            db_session,
            novel_id=test_project_id,
            run_id=prepared["run_id"],
            owner_id=owner_id,
            data=GoalResume(
                expected_revision=stopped["revision"],
                budget=GoalBudget(
                    requests=6,
                    possible_charge_requests=6,
                    tokens=request.budget.tokens,
                    time_limit_seconds=request.budget.time_limit_seconds,
                ),
            ),
        )

    assert resumed["status"] == "completed"
    assert resumed["budget"]["used"]["requests"] == 4
    stored = await service._load_goal_run(
        db_session, test_project_id, prepared["run_id"], owner_id
    )
    assert service._goal_state(stored)["envelope"]["started_at"] == original_started_at


@pytest.mark.asyncio
async def test_goal_planning_unknown_charge_stops_without_resume_or_replan(
    db_session, test_project_id, monkeypatch
):
    from modules.assistant.goal_runs import service

    owner_id = str(current_account_id())
    plan = _plan()
    operation = _read_operation()
    project = SimpleNamespace(
        project_kind="author",
        owner_id=owner_id,
        title="测试小说",
        genre="奇幻",
        tone="沉静",
        language="zh",
        current_stage="世界构建",
    )

    async def no_project_gate(*_args, **_kwargs):
        return None

    async def project_context(*_args, **_kwargs):
        return project

    _install_offline_goal_planner(monkeypatch, plan, unknown_charge=True)
    monkeypatch.setattr(service, "_require_goal_project", no_project_gate)
    monkeypatch.setattr(
        service,
        "_operation_registry",
        lambda: {"project.goal_test.read": operation},
    )
    monkeypatch.setattr(service, "get_any_project_context", project_context)

    with container_scope({"assistant.operations": {"project.goal_test.read": operation}}):
        result = await service.start_goal(
            db_session,
            _start_request(uuid.UUID(test_project_id)),
            owner_id,
        )

    assert result["status"] == "waiting_approval"
    assert result["budget"]["used"]["charge_state"] == "possible"
    assert result["stop_reason"] == "规划模型的计费结果未知，请先核对原回执"
    assert result["can_resume"] is False
    assert result["can_replan"] is False


@pytest.mark.asyncio
async def test_goal_r2_project_task_update_restores_through_real_domain_operation(
    db_session, test_project_id, monkeypatch
):
    from modules.assistant.goal_runs import service
    from modules.project.author_task_service import AuthorTaskService
    from modules.project.models import ProjectAuthorTask
    from modules.project.schemas import AuthorTaskCreateRequest

    owner_id = str(current_account_id())
    task = await AuthorTaskService().create_task(
        db_session,
        test_project_id,
        AuthorTaskCreateRequest(title="原始任务", note="基线说明"),
    )
    task_row = await db_session.get(ProjectAuthorTask, uuid.UUID(task.id))
    assert task_row is not None
    original_completed_at = datetime(2026, 10, 1, 12, 30, tzinfo=UTC)
    task_row.status = "completed"
    task_row.completed_at = original_completed_at
    await db_session.flush()
    plan = GoalPlan(
        title="更新项目待办",
        steps=[
            {
                "step_id": "update_task",
                "operation_id": "project.update_task",
                "targets": [{"target_type": "author_task", "target_id": task.id}],
                "parameters": {
                    "task_id": task.id,
                    "changes": {"title": "目标更新后的任务"},
                },
                "intent": "更新已选中的作者待办标题",
            }
        ],
    )
    _, _prepared, applied = await _approve_goal_plan(
        db_session, test_project_id, owner_id, plan, monkeypatch
    )
    prepared = _prepared
    assert prepared["phase"] == "plan_review"
    assert applied["status"] == "completed"
    assert applied["changes"][0]["state"] == "applied"
    task_row = await db_session.get(ProjectAuthorTask, uuid.UUID(task.id))
    assert task_row is not None and task_row.title == "目标更新后的任务"
    applied_updated_at = task_row.updated_at

    restored = await service.restore_goal_changes(
        db_session,
        test_project_id,
        applied["run_id"],
        GoalAction(expected_revision=applied["revision"]),
        owner_id,
    )
    await db_session.refresh(task_row)
    assert restored["changes"][0]["state"] == "restored"
    assert task_row.title == "原始任务"
    assert task_row.updated_at != applied_updated_at
    assert task_row.status == "completed"
    assert task_row.completed_at.replace(tzinfo=UTC) == original_completed_at
    restored_updated_at = task_row.updated_at

    repeated = await service.restore_goal_changes(
        db_session,
        test_project_id,
        applied["run_id"],
        GoalAction(expected_revision=restored["revision"]),
        owner_id,
    )
    await db_session.refresh(task_row)
    assert repeated["changes"][0]["state"] == "restored"
    assert task_row.updated_at == restored_updated_at


@pytest.mark.asyncio
async def test_goal_r2_dossier_edit_restores_through_real_domain_history(
    db_session, test_project_id, test_entity_id, monkeypatch
):
    from modules.assistant.goal_runs import service
    from modules.world.dossier_facade import create_world_object_dossier_entry
    from modules.world.schemas.dossier import DossierEntryCreate, DossierFacingRef

    owner_id = str(current_account_id())
    baseline = await create_world_object_dossier_entry(
        db_session,
        test_project_id,
        test_entity_id,
        DossierEntryCreate(
            facing=DossierFacingRef(kind="core", key="origin"),
            content="原始来源",
        ),
        source="author",
    )
    plan = GoalPlan(
        title="修订对象档案",
        steps=[
            {
                "step_id": "edit_dossier",
                "operation_id": "world.dossier.entry.edit",
                "targets": [{"target_type": "core_entity", "target_id": test_entity_id}],
                "parameters": {
                    "entity_id": test_entity_id,
                    "revision_id": str(baseline.id),
                    "update": {
                        "expected_revision_id": str(baseline.id),
                        "content": "目标修订后的来源",
                    },
                },
                "intent": "修订已选对象的来源档案",
            }
        ],
    )
    _, _prepared, applied = await _approve_goal_plan(
        db_session, test_project_id, owner_id, plan, monkeypatch
    )
    assert applied["status"] == "completed"
    assert applied["changes"][0]["state"] == "applied"

    restored = await service.restore_goal_changes(
        db_session,
        test_project_id,
        applied["run_id"],
        GoalAction(expected_revision=applied["revision"]),
        owner_id,
    )
    assert restored["changes"][0]["state"] == "restored"
    run = await db_session.get(
        AssistantRun,
        uuid.UUID(applied["run_id"]),
    )
    assert run is not None
    history = await service._active_dossier_revision(
        db_session,
        run,
        run.checkpoint_json["goal"],
        service._operation_registry(),
        entity_id=test_entity_id,
        entry_group_id=str(baseline.entry_group_id),
    )
    assert history is not None
    assert history["content"] == "原始来源"
    assert str(history["restored_from_id"]) == str(baseline.id)


@pytest.mark.asyncio
async def test_goal_r2_project_restore_uses_cas_after_author_edits(
    db_session, test_project_id, monkeypatch
):
    from modules.project.author_task_service import AuthorTaskService
    from modules.project.models import ProjectAuthorTask
    from modules.project.schemas import AuthorTaskCreateRequest, AuthorTaskPatchRequest

    owner_id = str(current_account_id())
    task = await AuthorTaskService().create_task(
        db_session,
        test_project_id,
        AuthorTaskCreateRequest(title="原始任务"),
    )
    plan = GoalPlan(
        title="更新项目待办",
        steps=[
            {
                "step_id": "update_task",
                "operation_id": "project.update_task",
                "targets": [{"target_type": "author_task", "target_id": task.id}],
                "parameters": {
                    "task_id": task.id,
                    "changes": {"title": "目标更新后的任务"},
                },
                "intent": "更新已选中的作者待办标题",
            }
        ],
    )
    service, _prepared, applied = await _approve_goal_plan(
        db_session, test_project_id, owner_id, plan, monkeypatch
    )
    task_row = await db_session.get(ProjectAuthorTask, uuid.UUID(task.id))
    assert task_row is not None
    await AuthorTaskService().patch_task(
        db_session,
        test_project_id,
        task.id,
        AuthorTaskPatchRequest(
            title="作者后来修改",
            expected_updated_at=task_row.updated_at,
        ),
    )

    result = await service.restore_goal_changes(
        db_session,
        test_project_id,
        applied["run_id"],
        GoalAction(expected_revision=applied["revision"]),
        owner_id,
    )
    await db_session.refresh(task_row)
    assert result["changes"][0]["state"] == "restore_blocked"
    assert result["changes"][0]["can_restore"] is False
    assert task_row.title == "作者后来修改"


@pytest.mark.asyncio
async def test_goal_r2_dossier_restore_uses_revision_cas_after_author_edits(
    db_session, test_project_id, test_entity_id, monkeypatch
):
    from modules.world.dossier_facade import (
        create_world_object_dossier_entry,
        edit_world_object_dossier_entry,
    )
    from modules.world.schemas.dossier import (
        DossierEntryCreate,
        DossierEntryUpdate,
        DossierFacingRef,
    )

    owner_id = str(current_account_id())
    baseline = await create_world_object_dossier_entry(
        db_session,
        test_project_id,
        test_entity_id,
        DossierEntryCreate(
            facing=DossierFacingRef(kind="core", key="origin"),
            content="原始来源",
        ),
    )
    plan = GoalPlan(
        title="修订对象档案",
        steps=[
            {
                "step_id": "edit_dossier",
                "operation_id": "world.dossier.entry.edit",
                "targets": [{"target_type": "core_entity", "target_id": test_entity_id}],
                "parameters": {
                    "entity_id": test_entity_id,
                    "revision_id": str(baseline.id),
                    "update": {
                        "expected_revision_id": str(baseline.id),
                        "content": "目标修订后的来源",
                    },
                },
                "intent": "修订已选对象的来源档案",
            }
        ],
    )
    service, _prepared, applied = await _approve_goal_plan(
        db_session, test_project_id, owner_id, plan, monkeypatch
    )
    run = await db_session.get(AssistantRun, uuid.UUID(applied["run_id"]))
    assert run is not None
    manifest = run.checkpoint_json["goal"]["changes"][0]
    await edit_world_object_dossier_entry(
        db_session,
        test_project_id,
        test_entity_id,
        manifest["applied_revision_id"],
        DossierEntryUpdate(
            expected_revision_id=uuid.UUID(manifest["applied_revision_id"]),
            content="作者后来修订",
        ),
    )

    result = await service.restore_goal_changes(
        db_session,
        test_project_id,
        applied["run_id"],
        GoalAction(expected_revision=applied["revision"]),
        owner_id,
    )
    assert result["changes"][0]["state"] == "restore_blocked"
    assert result["changes"][0]["can_restore"] is False
    active = await service._active_dossier_revision(
        db_session,
        run,
        run.checkpoint_json["goal"],
        service._operation_registry(),
        entity_id=test_entity_id,
        entry_group_id=str(baseline.entry_group_id),
    )
    assert active is not None and active["content"] == "作者后来修订"
