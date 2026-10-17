"""Goal runs use one durable plan/run ledger and preserve active uniqueness."""

import uuid
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from core.container import container_scope
from core.errors import ConflictError, NotFoundError
from infrastructure.tasks.models import AsyncTask
from modules.account.facade import current_account_id
from modules.assistant.contracts import AssistantOperation
from modules.assistant.goal_runs.contracts import (
    GoalAction,
    GoalBudget,
    GoalOperationSelection,
    GoalOutcomeReconciliation,
    GoalPlan,
    GoalPlanApproval,
    GoalReplanRequest,
    GoalResume,
    GoalRunStart,
    GoalStep,
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

    def __init__(self, plan, *, unknown_charge=False, selection_ids=None):
        self.plan = plan
        self.unknown_charge = unknown_charge
        self.selection_ids = selection_ids

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
        usage = LLMUsage(prompt_tokens=12, completion_tokens=8, total_tokens=20)
        await envelope.settle(
            reservation,
            usage=usage,
            outcome=AIRequestOutcome.succeeded,
        )
        await budget.completed(usage)
        if _response_schema is GoalOperationSelection:
            return GoalOperationSelection(
                operation_ids=self.selection_ids
                or list(dict.fromkeys(step.operation_id for step in self.plan.steps))
            )
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


async def _unknown_goal_step(
    db,
    novel_id: str,
    owner_id: str,
    monkeypatch,
    *,
    task_status="done",
    receipt_status="incomplete",
):
    from modules.assistant.goal_runs import service

    plan = GoalPlan(
        title="核对原扫描回执",
        steps=[
            {
                "step_id": "scan",
                "operation_id": "project.scan_duplicates",
                "parameters": {"query": "资料"},
                "intent": "扫描已选资料",
            }
        ],
    )
    calls = []
    applies = []
    receipt = {"value": {"status": receipt_status, "receipt_id": "domain-receipt"}}

    async def prepare(_db, _novel_id, _args, *, context=None):
        return {"effect": "扫描资料"}

    async def apply(*_args, **_kwargs):
        applies.append(True)
        return {"status": "unexpected_apply"}

    async def read_result(_db, _novel_id, reference):
        calls.append(dict(reference))
        return receipt["value"]

    operation = AssistantOperation(
        label="扫描资料",
        schema=ReadProject,
        prepare=prepare,
        apply=apply,
        permission="confirm",
        read_result=read_result,
        risk_level="R3",
        fee_category="free",
        target_type="project",
        transaction_mode="multi_stage",
    )
    _install_offline_goal_planner(monkeypatch, plan)
    monkeypatch.setattr(
        service,
        "_operation_registry",
        lambda: {"project.scan_duplicates": operation},
    )
    request = _start_request(uuid.UUID(novel_id))
    request.budget.requests = 10
    request.budget.possible_charge_requests = 10
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
    assert approved["phase"] == "step_review", (
        approved.get("stop_code"),
        approved.get("stop_reason"),
    )
    run = await service._load_goal_run(db, novel_id, prepared["run_id"], owner_id)
    goal = service._goal_state(run)
    step = plan.steps[0]
    parameter_hash = service.parameter_fingerprint(operation, step.parameters)
    stable_operation_id = service.step_operation_id(
        str(run.id), step.step_id, parameter_hash
    )
    task_type = service.TASK_OPERATION_TYPES[step.operation_id]
    reference = {
        "type": task_type,
        "task_id": stable_operation_id,
        "task_type": task_type,
        "operation_id": stable_operation_id,
    }
    db.add(
        AsyncTask(
            id=uuid.UUID(stable_operation_id),
            novel_id=uuid.UUID(novel_id),
            task_type=task_type,
            status=task_status,
            meta={"_parent_task_id": str(run.task_id)},
            result={"status": receipt_status},
        )
    )
    record = service._step_records(goal)[step.step_id]
    record.update(
        {
            "status": "outcome_unknown",
            "operation_id": stable_operation_id,
            "parameter_fingerprint": parameter_hash,
            "plan_step_fingerprint": service.digest(step.model_dump(mode="json")),
            "resolved_parameters": step.parameters,
            "reference": reference,
            "read_result": {"status": "incomplete"},
        }
    )
    goal["phase"] = "stopped"
    goal["stop_code"] = "task_outcome_unknown"
    goal["stop_reason"] = "原领域任务结果仍未落定。"
    run = await service._save_goal(db, run, goal, status="waiting_approval")
    return (
        service,
        approved,
        await service.goal_view(db, run, owner_id=owner_id),
        operation,
        calls,
        applies,
        receipt,
    )


@pytest.mark.asyncio
async def test_goal_receipt_preview_is_read_only_bounded_and_bound_to_the_unknown_step(
    db_session, test_project_id, monkeypatch
):
    owner_id = str(current_account_id())
    (
        service,
        _approved,
        unknown,
        _operation,
        calls,
        applies,
        receipt,
    ) = await _unknown_goal_step(db_session, test_project_id, owner_id, monkeypatch)
    receipt["value"] = {
        "status": "completed",
        "receipt_id": "private-receipt-id",
        "summary": "扫描完成 Bearer abcdefghijklmnop secret=private-value",
        "scanned_counts": {"plot_thread": 3, "outline_arc": 2},
        "group_count": 1,
    }
    tasks_before = await db_session.scalar(
        select(func.count())
        .select_from(AsyncTask)
        .where(AsyncTask.novel_id == uuid.UUID(test_project_id))
    )
    original_usage = unknown["budget"]["used"].copy()

    preview = await service.goal_step_receipt_preview(
        db_session,
        test_project_id,
        unknown["run_id"],
        "scan",
        unknown["revision"],
        owner_id,
    )

    assert preview.status == "verified_applied"
    assert preview.available_decisions == ["applied"]
    assert preview.summary == "扫描完成 Bearer [已隐藏凭据] secret=[已隐藏]"
    assert preview.details == ["本次扫描了 5 项资料。", "形成 1 组相似建议。"]
    assert preview.destination.kind == "smart_dedup_scan"
    run = await service._load_goal_run(
        db_session, test_project_id, unknown["run_id"], owner_id
    )
    record = service._step_records(service._goal_state(run))["scan"]
    assert preview.destination.task_id == uuid.UUID(record["reference"]["task_id"])
    assert len(calls) == 1
    assert calls[0] == record["reference"]
    assert applies == []
    tasks_after = await db_session.scalar(
        select(func.count())
        .select_from(AsyncTask)
        .where(AsyncTask.novel_id == uuid.UUID(test_project_id))
    )
    assert tasks_after == tasks_before

    after = await service.get_goal(
        db_session, test_project_id, unknown["run_id"], owner_id
    )
    assert after["revision"] == unknown["revision"]
    assert after["steps"][0]["status"] == "outcome_unknown"
    assert after["budget"]["used"] == original_usage
    assert after["can_replan"] is False


@pytest.mark.asyncio
async def test_goal_receipt_preview_http_route_exposes_safe_projection_and_revision(
    db_session, test_project_id, async_client, monkeypatch
):
    owner_id = str(current_account_id())
    (
        _service,
        _approved,
        unknown,
        _operation,
        calls,
        applies,
        receipt,
    ) = await _unknown_goal_step(db_session, test_project_id, owner_id, monkeypatch)
    receipt["value"] = {
        "status": "completed",
        "summary": "扫描完成",
        "scanned_counts": {"plot_thread": 2},
        "group_count": 0,
    }
    path = f"/api/assistant/goals/{unknown['run_id']}/steps/scan/receipt"
    response = await async_client.get(
        path,
        params={
            "novel_id": test_project_id,
            "expected_revision": unknown["revision"],
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["expected_revision"] == unknown["revision"]
    assert payload["status"] == "verified_applied"
    assert payload["available_decisions"] == ["applied"]
    assert payload["summary"] == "扫描完成"
    assert "task_id" in payload["destination"]
    assert "private-receipt-id" not in response.text
    stale = await async_client.get(
        path,
        params={
            "novel_id": test_project_id,
            "expected_revision": unknown["revision"] + 1,
        },
    )
    assert stale.status_code == 409
    assert len(calls) == 1
    assert applies == []


@pytest.mark.asyncio
async def test_goal_receipt_preview_does_not_read_a_still_running_task(
    db_session, test_project_id, monkeypatch
):
    owner_id = str(current_account_id())
    (
        service,
        _approved,
        unknown,
        _operation,
        calls,
        applies,
        _receipt,
    ) = await _unknown_goal_step(
        db_session,
        test_project_id,
        owner_id,
        monkeypatch,
        task_status="running",
    )

    preview = await service.goal_step_receipt_preview(
        db_session,
        test_project_id,
        unknown["run_id"],
        "scan",
        unknown["revision"],
        owner_id,
    )

    assert preview.status == "incomplete"
    assert preview.available_decisions == []
    assert preview.summary == "原任务仍在处理中；领域结果尚不能确认。"
    assert calls == []
    assert applies == []


@pytest.mark.asyncio
async def test_only_cancelled_before_first_claim_can_reconcile_as_not_applied(
    db_session, test_project_id, monkeypatch
):
    owner_id = str(current_account_id())
    (
        service,
        _approved,
        unknown,
        _operation,
        calls,
        applies,
        _receipt,
    ) = await _unknown_goal_step(
        db_session,
        test_project_id,
        owner_id,
        monkeypatch,
        task_status="cancelled",
    )
    run = await service._load_goal_run(
        db_session, test_project_id, unknown["run_id"], owner_id
    )
    task_id = service._step_records(service._goal_state(run))["scan"]["reference"][
        "task_id"
    ]
    task = await db_session.get(AsyncTask, uuid.UUID(task_id))
    task.result = {}
    task.attempt = 0
    task.started_at = None
    task.error_message = None
    await db_session.flush()

    preview = await service.goal_step_receipt_preview(
        db_session,
        test_project_id,
        unknown["run_id"],
        "scan",
        unknown["revision"],
        owner_id,
    )
    assert preview.status == "verified_not_applied"
    assert preview.available_decisions == ["not_applied"]
    assert preview.details == ["任务在首次领取前已取消，服务端确认没有执行领域操作。"]
    assert calls == []

    resolved = await service.reconcile_goal_step(
        db_session,
        test_project_id,
        unknown["run_id"],
        "scan",
        GoalOutcomeReconciliation(
            expected_revision=unknown["revision"], decision="not_applied"
        ),
        owner_id,
    )
    assert resolved["steps"][0]["status"] == "failed"
    assert resolved["stop_code"] == "step_receipt_not_applied"
    assert calls == []
    assert applies == []


@pytest.mark.asyncio
async def test_goal_unknown_step_reconciliation_requires_bound_domain_receipt(
    db_session, test_project_id, monkeypatch
):
    owner_id = str(current_account_id())
    (
        service,
        _approved,
        unknown,
        _operation,
        calls,
        applies,
        receipt,
    ) = await _unknown_goal_step(db_session, test_project_id, owner_id, monkeypatch)
    original_usage = unknown["budget"]["used"].copy()
    assert unknown["steps"][0]["can_reconcile"] is True
    assert unknown["can_replan"] is False

    with pytest.raises(ConflictError, match="没有证明该步骤已完成"):
        await service.reconcile_goal_step(
            db_session,
            test_project_id,
            unknown["run_id"],
            "scan",
            GoalOutcomeReconciliation(
                expected_revision=unknown["revision"], decision="applied"
            ),
            owner_id,
        )

    still_unknown = await service.get_goal(
        db_session, test_project_id, unknown["run_id"], owner_id
    )
    assert still_unknown["steps"][0]["status"] == "outcome_unknown"
    assert still_unknown["budget"]["used"] == original_usage

    with pytest.raises(ConflictError, match="没有证明该步骤未应用"):
        await service.reconcile_goal_step(
            db_session,
            test_project_id,
            unknown["run_id"],
            "scan",
            GoalOutcomeReconciliation(
                expected_revision=still_unknown["revision"],
                decision="not_applied",
            ),
            owner_id,
        )

    receipt["value"] = {
        "status": "completed",
        "receipt_id": "domain-receipt",
        "summary": "扫描完成",
    }
    resolved = await service.reconcile_goal_step(
        db_session,
        test_project_id,
        unknown["run_id"],
        "scan",
        GoalOutcomeReconciliation(
            expected_revision=still_unknown["revision"], decision="applied"
        ),
        owner_id,
    )
    assert resolved["steps"][0]["status"] == "completed"
    assert resolved["steps"][0]["can_reconcile"] is False
    assert resolved["stop_code"] == "step_receipt_applied"
    assert resolved["can_advance"] is True
    assert resolved["budget"]["used"] == original_usage
    assert len(calls) == 3
    assert calls[0] == calls[1] == calls[2]
    run = await service._load_goal_run(
        db_session, test_project_id, unknown["run_id"], owner_id
    )
    record = service._step_records(service._goal_state(run))["scan"]
    assert record["reconciliation"]["call_id"] == service._goal_trace_call_id(
        run, service._goal_state(run), "scan"
    )
    assert record["reconciliation"]["confirmed_by"] == owner_id
    assert applies == []

    completed = await service.advance_goal(
        db_session,
        test_project_id,
        unknown["run_id"],
        owner_id,
        GoalAction(expected_revision=resolved["revision"]),
    )
    assert completed["status"] == "completed"
    assert applies == []


@pytest.mark.asyncio
async def test_failed_task_status_alone_does_not_prove_not_applied(
    db_session, test_project_id, monkeypatch
):
    owner_id = str(current_account_id())
    (
        service,
        _approved,
        unknown,
        _operation,
        _calls,
        _applies,
        _receipt,
    ) = await _unknown_goal_step(
        db_session,
        test_project_id,
        owner_id,
        monkeypatch,
        task_status="failed",
        receipt_status="failed",
    )

    with pytest.raises(ConflictError, match="没有证明该步骤未应用"):
        await service.reconcile_goal_step(
            db_session,
            test_project_id,
            unknown["run_id"],
            "scan",
            GoalOutcomeReconciliation(
                expected_revision=unknown["revision"], decision="not_applied"
            ),
            owner_id,
        )


@pytest.mark.asyncio
async def test_goal_not_applied_requires_terminal_receipt_and_keeps_unknown_usage(
    db_session, test_project_id, monkeypatch
):
    from infrastructure.llm.schemas import AIRequestOutcome
    from infrastructure.llm.workflow_budget import ai_run_scope, managed_step_scope

    owner_id = str(current_account_id())
    (
        service,
        _approved,
        unknown,
        _operation,
        calls,
        applies,
        _receipt,
    ) = await _unknown_goal_step(
        db_session,
        test_project_id,
        owner_id,
        monkeypatch,
        task_status="failed",
        receipt_status="not_applied",
    )
    run = await service._load_goal_run(
        db_session, test_project_id, unknown["run_id"], owner_id
    )
    envelope = service._live_envelope(db_session, run)
    context = service._managed_context(
        _PlanningClient(_plan()),
        step=service.GOAL_PLAN_STEP,
        fingerprint="u" * 64,
    )
    with ai_run_scope(envelope), managed_step_scope(context):
        reservation = await envelope.reserve()
        await envelope.settle(reservation, outcome=AIRequestOutcome.unknown)

    run = await service._load_goal_run(
        db_session, test_project_id, unknown["run_id"], owner_id
    )
    before = await service.goal_view(db_session, run, owner_id=owner_id)
    resolved = await service.reconcile_goal_step(
        db_session,
        test_project_id,
        unknown["run_id"],
        "scan",
        GoalOutcomeReconciliation(
            expected_revision=before["revision"], decision="not_applied"
        ),
        owner_id,
    )
    assert resolved["steps"][0]["status"] == "failed"
    assert resolved["can_replan"] is False
    assert resolved["stop_code"] == "unknown_charge"
    assert resolved["budget"]["used"]["charge_state"] == "possible"
    assert resolved["budget"]["used"]["requests"] == before["budget"]["used"]["requests"]
    assert resolved["budget"]["used"]["requests"] == 3
    assert len(calls) == 1
    assert applies == []


@pytest.mark.asyncio
async def test_goal_verified_not_applied_allows_cumulative_replan_without_replay(
    db_session, test_project_id, monkeypatch
):
    owner_id = str(current_account_id())
    (
        service,
        _approved,
        unknown,
        _operation,
        calls,
        applies,
        _receipt,
    ) = await _unknown_goal_step(
        db_session,
        test_project_id,
        owner_id,
        monkeypatch,
        task_status="failed",
        receipt_status="not_applied",
    )
    before = unknown["budget"]["used"].copy()
    resolved = await service.reconcile_goal_step(
        db_session,
        test_project_id,
        unknown["run_id"],
        "scan",
        GoalOutcomeReconciliation(
            expected_revision=unknown["revision"], decision="not_applied"
        ),
        owner_id,
    )
    assert resolved["steps"][0]["status"] == "failed"
    assert resolved["can_replan"] is True
    assert resolved["budget"]["used"] == before

    replanned = await service.replan_goal(
        db_session,
        test_project_id,
        unknown["run_id"],
        GoalReplanRequest(
            expected_revision=resolved["revision"], reason="按原预算重新安排剩余工作"
        ),
        owner_id,
    )
    assert replanned["phase"] in {"plan_review", "scope_expanded"}
    assert replanned["budget"]["used"]["requests"] > before["requests"]
    assert len(calls) == 1
    assert applies == []


@pytest.mark.asyncio
async def test_goal_still_unknown_is_cas_protected_and_never_reads_or_replays(
    db_session, test_project_id, monkeypatch
):
    owner_id = str(current_account_id())
    (
        service,
        _approved,
        unknown,
        _operation,
        calls,
        applies,
        _receipt,
    ) = await _unknown_goal_step(
        db_session,
        test_project_id,
        owner_id,
        monkeypatch,
        task_status="running",
    )
    kept = await service.reconcile_goal_step(
        db_session,
        test_project_id,
        unknown["run_id"],
        "scan",
        GoalOutcomeReconciliation(
            expected_revision=unknown["revision"], decision="still_unknown"
        ),
        owner_id,
    )
    assert kept["steps"][0]["status"] == "outcome_unknown"
    assert kept["can_replan"] is False
    assert calls == []
    assert applies == []
    with pytest.raises(ConflictError, match="目标结果已更新"):
        await service.reconcile_goal_step(
            db_session,
            test_project_id,
            unknown["run_id"],
            "scan",
            GoalOutcomeReconciliation(
                expected_revision=unknown["revision"], decision="applied"
            ),
            owner_id,
        )


@pytest.mark.parametrize("risk_level", ["R2", "R3"])
@pytest.mark.asyncio
async def test_auto_r2_keeps_unrestorable_r2_and_r3_at_step_review(
    db_session, test_project_id, monkeypatch, risk_level
):
    from core.service_keys import ASSISTANT_REQUIRE_OPERATION_TARGETS
    from modules.assistant.goal_runs import service

    plan = GoalPlan(
        title="修改选定对象",
        steps=[
            {
                "step_id": "edit",
                "operation_id": "project.goal_test.edit",
                "targets": [{"target_type": "artifact", "target_id": "artifact-1"}],
                "parameters": {"target_id": "artifact-1", "value": "新值"},
                "intent": "修改选定对象",
            }
        ],
    )
    apply_calls = []

    async def apply(*_args, **_kwargs):
        apply_calls.append(True)
        return {"target_id": "artifact-1"}

    operation = replace(_edit_operation(), risk_level=risk_level, apply=apply)

    async def no_target_gate(*_args, **_kwargs):
        return None

    _install_offline_goal_planner(monkeypatch, plan)
    monkeypatch.setattr(
        service,
        "_operation_registry",
        lambda: {"project.goal_test.edit": operation},
    )
    owner_id = str(current_account_id())
    request = _start_request(uuid.UUID(test_project_id))
    with container_scope({ASSISTANT_REQUIRE_OPERATION_TARGETS: no_target_gate}):
        proposed = await service.start_goal(db_session, request, owner_id)
        tasks_before = await db_session.scalar(
            select(func.count()).select_from(AsyncTask)
        )
        approved_result = await service.approve_goal_plan(
            db_session,
            novel_id=test_project_id,
            run_id=proposed["run_id"],
            owner_id=owner_id,
            data=GoalPlanApproval(
                expected_revision=proposed["revision"],
                plan=plan,
                budget=request.budget,
                auto_r2=True,
            ),
        )
    approved = (
        approved_result
        if isinstance(approved_result, dict)
        else await service.goal_view(db_session, approved_result, owner_id=owner_id)
    )
    tasks_after = await db_session.scalar(select(func.count()).select_from(AsyncTask))

    assert approved["phase"] == "step_review", (
        approved.get("stop_code"),
        approved.get("stop_reason"),
    )
    assert approved["stop_code"] == "step_approval"
    assert approved["steps"][0]["status"] == "prepared"
    assert approved["steps"][0]["can_auto_restore"] is False
    assert approved["budget"]["used"] == proposed["budget"]["used"]
    assert apply_calls == []
    assert tasks_after == tasks_before


def test_r4_stays_unavailable_without_preparing_or_applying():
    from modules.assistant.goal_runs import service

    calls = []

    async def prepare(*_args, **_kwargs):
        calls.append("prepare")
        return {}

    async def apply(*_args, **_kwargs):
        calls.append("apply")
        return {}

    operation = AssistantOperation(
        label="需要独立授权的操作",
        schema=EditArtifact,
        prepare=prepare,
        apply=apply,
        risk_level="R4",
        fee_category="free",
    )
    plan = GoalPlan(
        title="需要独立授权",
        steps=[
            {
                "step_id": "r4",
                "operation_id": "project.goal_test.r4",
                "parameters": {"target_id": "artifact-1", "value": "新值"},
                "intent": "执行需要独立授权的操作",
            }
        ],
    )
    with pytest.raises(ConflictError, match="需在原工作台独立授权"):
        service._assert_plan_operations_supported(
            plan, {"project.goal_test.r4": operation}
        )
    assert calls == []
    assert service._step_is_manual(plan.steps[0], operation, {"auto_r2": True}, {})


def test_auto_r2_restore_catalog_requires_supported_fields_and_single_transaction():
    from modules.assistant.goal_runs import service

    operation = AssistantOperation(
        label="更新待办",
        schema=EditArtifact,
        prepare=_preview_artifact_edit,
        risk_level="R2",
        transaction_mode="single_transaction",
    )
    supported = GoalStep(
        step_id="task",
        operation_id="project.update_task",
        parameters={"changes": {"title": "新标题"}},
        intent="更新待办标题",
    )
    unsupported = supported.model_copy(
        update={"parameters": {"changes": {"status": "completed"}}}
    )
    assert service._r2_restore_is_supported(supported, operation, supported.parameters)
    assert not service._r2_restore_is_supported(
        unsupported, operation, unsupported.parameters
    )
    assert service._step_is_manual(
        unsupported, operation, {"auto_r2": True}, unsupported.parameters
    )

    dossier = GoalStep(
        step_id="dossier",
        operation_id="world.dossier.entry.edit",
        parameters={},
        intent="编辑对象档案",
    )
    assert service._r2_restore_is_supported(dossier, operation, {})
    multi_stage = replace(operation, transaction_mode="multi_stage")
    assert not service._r2_restore_is_supported(dossier, multi_stage, {})


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
        assert prepared["budget"]["used"]["requests"] == 2
        run_id = uuid.UUID(prepared["run_id"])

        stored = await db_session.scalar(
            select(AssistantRun).where(AssistantRun.id == run_id)
        )
        assert stored is not None
        assert stored.mode == "goal"
        assert stored.session_id is None
        assert stored.checkpoint_json["goal"]["envelope"]["version"] == 3
        assert stored.checkpoint_json["goal"]["envelope"]["requests_started"] == 2

        repeated = await service.start_goal(db_session, request, owner_id)
        assert repeated["run_id"] == prepared["run_id"]
        assert repeated["budget"]["used"]["requests"] == 2

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
    assert completed["budget"]["used"]["requests"] == 2
    assert completed["steps"][0]["status"] == "completed"
    replayed = await service.advance_goal(
        db_session,
        test_project_id,
        prepared["run_id"],
        owner_id,
        GoalAction(expected_revision=completed["revision"]),
    )
    assert replayed["status"] == "completed"
    assert replayed["budget"]["used"]["requests"] == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("token_budget", "expected_phase", "expected_requests"),
    [(12000, "plan_review", 2), (512, "planning_stopped", 0)],
)
async def test_goal_selection_allows_nine_small_operations_without_extra_cap(
    db_session,
    test_project_id,
    monkeypatch,
    token_budget,
    expected_phase,
    expected_requests,
):
    from modules.assistant.goal_runs import service

    owner_id = str(current_account_id())
    operation_ids = [f"project.goal_test.read_{index}" for index in range(9)]
    operations = {key: replace(_read_operation(), op_id=key) for key in operation_ids}
    plan = GoalPlan(
        title="合成目录选择",
        steps=[
            {
                "step_id": "read",
                "operation_id": operation_ids[0],
                "parameters": {"query": "合成资料"},
                "intent": "检查选中资料",
            }
        ],
    )

    async def owned(*_args, **_kwargs):
        return None

    async def project(*_args, **_kwargs):
        return SimpleNamespace(
            title="合成项目",
            genre="奇幻",
            tone="简洁",
            language="zh",
            current_stage="writing",
        )

    async def snapshot(*_args, **_kwargs):
        return _offline_snapshot()

    async def no_trace(*_args, **_kwargs):
        return False

    @asynccontextmanager
    async def planner(*_args, **_kwargs):
        yield _PlanningClient(plan, selection_ids=operation_ids)

    monkeypatch.setattr(service, "_require_goal_project", owned)
    monkeypatch.setattr(service, "get_any_project_context", project)
    monkeypatch.setattr(service, "build_project_llm_execution_snapshot", snapshot)
    monkeypatch.setattr(service, "_trace_enabled", no_trace)
    monkeypatch.setattr(service, "open_project_snapshot_llm_client", planner)
    monkeypatch.setattr(service, "_operation_registry", lambda: operations)
    request = _start_request(uuid.UUID(test_project_id))
    request.budget.tokens = token_budget
    with container_scope({"assistant.operations": operations}):
        prepared = await service.start_goal(db_session, request, owner_id)
    assert prepared["status"] == "waiting_approval"
    assert prepared["phase"] == expected_phase
    assert prepared["budget"]["used"]["requests"] == expected_requests
    if token_budget == 512:
        assert prepared["stop_code"] == "planning_scope_too_large"
        assert prepared["can_replan"] is False
        assert "增加预算" in prepared["stop_reason"]


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
    assert cancelled["budget"]["used"]["requests"] == 2
    assert repeated["status"] == "cancelled"
    assert repeated["budget"]["used"]["requests"] == 2
    assert parent is not None and parent.status == "cancelled"


def _offline_snapshot():
    return {
        "provider_id": "test",
        "model": "offline-goal-plan-stub",
        "profile": {"model": "offline-goal-plan-stub", "max_tokens": 8192},
        "verified": True,
    }


def test_goal_time_80_stops_before_provider_without_resetting_original_deadline():
    from infrastructure.llm.workflow_budget import (
        AIRunBudgetExceededError,
        AIRunEnvelope,
        new_ai_run_envelope,
    )
    from modules.assistant.goal_runs import service

    started_at = datetime(2026, 10, 16, tzinfo=UTC)
    now = started_at + timedelta(seconds=81)
    budget = GoalBudget(
        requests=10,
        possible_charge_requests=10,
        tokens=4096,
        time_limit_seconds=100,
    )
    frozen = new_ai_run_envelope(
        operation_id=str(uuid.uuid4()),
        run_id=str(uuid.uuid4()),
        root_capability_id="assistant.goal.run",
        novel_id=str(uuid.uuid4()),
        request_limit=budget.requests,
        token_limit=budget.tokens,
        deadline_at=started_at + timedelta(seconds=100),
        budget_mode="goal",
        scope_fingerprint="a" * 64,
        authorized_step_capabilities=["assistant.goal.plan"],
        started_at=started_at,
    ).snapshot()
    envelope = AIRunEnvelope(frozen, clock=lambda: now)
    meter = service.GoalWorkflowCounter(envelope, budget, clock=lambda: now)
    with pytest.raises(AIRunBudgetExceededError, match="80% 时间"):
        meter.reserve(requests=1)
    goal = {
        "protocol": service.PROTOCOL,
        "started_at": started_at.isoformat(),
        "requested_budget": budget.model_dump(mode="json"),
        "envelope": frozen.model_dump(mode="json"),
    }
    run = SimpleNamespace(checkpoint_json={"goal": goal})
    assert "80% 时间" in service._usage_stop_reason(run, goal, clock=lambda: now)

    goal["time_80_acknowledged"] = True
    resumed = service.GoalWorkflowCounter(
        envelope, budget, time_80_acknowledged=True, clock=lambda: now
    )
    resumed.reserve(requests=1)
    assert service._usage_stop_reason(run, goal, clock=lambda: now) is None
    assert envelope.snapshot().started_at == started_at
    assert envelope.snapshot().deadline_at == started_at + timedelta(seconds=100)

    now = started_at + timedelta(seconds=101)
    with pytest.raises(AIRunBudgetExceededError, match="时限"):
        resumed.reserve(requests=1)
    assert "时限已到" in service._usage_stop_reason(run, goal, clock=lambda: now)


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
        request.budget.requests = 3
        request.budget.possible_charge_requests = 3
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
        await _settle_goal_requests(service, db_session, run, request.budget, 1)
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
        assert stopped["budget"]["used"]["requests"] == 3

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
    assert resumed["budget"]["used"]["requests"] == 3
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
