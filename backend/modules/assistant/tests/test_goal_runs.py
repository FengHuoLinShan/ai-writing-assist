"""Goal runs use one durable plan/run ledger and preserve active uniqueness."""

import json
import uuid
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from pydantic import BaseModel, ValidationError
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


@pytest.mark.parametrize("tokens", [512, 500_001, 5_000_000])
def test_goal_budget_accepts_explicit_token_limits_up_to_five_million(tokens):
    budget = GoalBudget(
        requests=100,
        possible_charge_requests=100,
        tokens=tokens,
        time_limit_seconds=7200,
    )
    assert budget.tokens == tokens


@pytest.mark.parametrize(
    "override",
    [
        {"tokens": 511},
        {"tokens": 5_000_001},
        {"requests": 101},
        {"possible_charge_requests": 101},
        {"time_limit_seconds": 7201},
    ],
)
def test_goal_budget_keeps_other_authorization_bounds(override):
    with pytest.raises(ValidationError):
        GoalBudget.model_validate(
            {
                "requests": 100,
                "possible_charge_requests": 100,
                "tokens": 12000,
                "time_limit_seconds": 7200,
                **override,
            }
        )


async def test_goal_capabilities_reports_explicit_large_token_limit(monkeypatch):
    from modules.assistant import approval
    from modules.assistant.goal_runs import service

    async def owned(*_args):
        return None

    async def unavailable(*_args):
        return {"enabled": False}

    monkeypatch.setattr(service, "_feature_enabled", lambda _novel_id: True)
    monkeypatch.setattr(service, "is_demo_readonly_principal", lambda: False)
    monkeypatch.setattr(service, "_require_goal_project", owned)
    monkeypatch.setattr(service, "_operation_registry", lambda: {})
    monkeypatch.setattr(approval, "approval_availability", unavailable)

    capabilities = await service.goal_capabilities(None, "novel-a", "owner-a")
    assert capabilities["budget_limits"] == {
        "requests_max": 100,
        "possible_charge_requests_max": 100,
        "tokens_max": 5_000_000,
        "time_limit_seconds_max": 7200,
    }


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
@pytest.mark.parametrize(
    "project_summary",
    [
        {},
        {"title": "标题不能代替作品编号"},
        {"novel_id": "stale-title", "title": "旧运行"},
    ],
)
async def test_goal_both_planner_prompts_use_run_project_identity(
    monkeypatch, exploration_gate, project_summary
):
    import modules.story.exploration_tasks  # noqa: F401
    from app.assistant_operation_registry import story_exploration_operations
    from infrastructure.llm.workflow_budget import new_ai_run_envelope
    from modules.assistant.goal_runs import service

    novel_id = uuid.uuid4()
    plan = _exploration_goal_plan(str(novel_id))
    operation_ids = [
        "story.exploration." + name
        for name in (
            "preview",
            "start",
            "detail",
            "confirmation_preview",
            "confirm",
            "handoff",
        )
    ]
    operations = {key: story_exploration_operations[key] for key in operation_ids}
    requests = []

    class CapturingPlanner(_PlanningClient):
        async def generate_structured(self, request, response_schema, **kwargs):
            requests.append((request, response_schema))
            return await super().generate_structured(request, response_schema, **kwargs)

    @asynccontextmanager
    async def planner(*_args):
        yield CapturingPlanner(plan, selection_ids=operation_ids)

    monkeypatch.setattr(service, "open_project_snapshot_llm_client", planner)
    budget = GoalBudget(
        requests=20, possible_charge_requests=20, tokens=200000, time_limit_seconds=600
    )
    run = SimpleNamespace(
        id=uuid.uuid4(),
        novel_id=novel_id,
        request_hash="f" * 64,
        request_json={"goal": "解释禁水规则如何影响一家人晚餐，并给孩子一句回应"},
    )
    original_summary = dict(project_summary)
    goal = {
        "llm_snapshot": _offline_snapshot(),
        "project_summary": project_summary,
        "requested_budget": budget.model_dump(mode="json"),
    }
    envelope = new_ai_run_envelope(
        operation_id=str(uuid.uuid4()),
        run_id=str(run.id),
        root_capability_id=service.GOAL_PLAN_STEP,
        novel_id=str(novel_id),
        request_limit=budget.requests,
        token_limit=budget.tokens,
    )
    result = await service._select_plan(
        None, run, goal, operations, [], envelope=envelope, budget=budget
    )

    assert result == plan
    assert [schema for _, schema in requests] == [GoalOperationSelection, GoalPlan]
    for request, _ in requests:
        payload = json.loads(
            next(
                message.content for message in request.messages if message.role == "user"
            )
        )
        assert payload["project"]["novel_id"] == str(novel_id)
    assert project_summary == original_summary
    plan_payload = json.loads(requests[1][0].messages[1].content)
    descriptors = {item["operation_id"]: item for item in plan_payload["catalog"]}
    for operation_id, operation in operations.items():
        assert descriptors[operation_id]["description"] == operation.description
        assert (
            descriptors[operation_id]["parameter_schema"]
            == operation.schema.model_json_schema()
        )
    planning_system = requests[1][0].messages[0].content
    assert "$ref.step_id" in planning_system
    assert "targets[].target_id" in planning_system
    assert "必须显式列入当前步骤的 depends_on" in planning_system
    assert "传递依赖不能代替直接依赖" in planning_system
    planning_schema = requests[1][1].model_json_schema()["$defs"]
    for model, field in (("GoalReference", "step_id"), ("GoalStep", "depends_on")):
        description = planning_schema[model]["properties"][field]["description"]
        assert "参数" in description and "target_id" in description
        assert "显式" in description and "传递依赖不能代替" in description
    assert envelope.snapshot().requests_started == 2


@pytest.mark.parametrize("reference_location", ["parameters", "targets"])
def test_goal_reference_requires_explicit_dependency_even_when_transitively_reachable(
    reference_location,
):
    from core.errors import ValidationError as DomainValidationError
    from modules.assistant.goal_runs.planning import validate_plan

    operation = _read_operation()
    reference = {
        "step_id": "source",
        "path": ["result"],
        "value_type": "identifier",
    }
    consumer = {
        "step_id": "consumer",
        "operation_id": "project.read",
        "depends_on": ["middle"],
        "parameters": {"query": "读取最后一项"},
        "intent": "直接读取首步产物",
    }
    if reference_location == "parameters":
        consumer["parameters"]["query"] = {"$ref": reference}
    else:
        consumer["targets"] = [{"target_type": "project", "target_id": reference}]
    plan = GoalPlan.model_validate(
        {
            "title": "直接引用必须声明直接依赖",
            "steps": [
                {
                    "step_id": "source",
                    "operation_id": "project.read",
                    "parameters": {"query": "读取首项"},
                    "intent": "提供来源",
                },
                {
                    "step_id": "middle",
                    "operation_id": "project.read",
                    "depends_on": ["source"],
                    "parameters": {"query": "读取中间项"},
                    "intent": "建立传递依赖",
                },
                consumer,
            ],
        }
    )
    before = plan.model_dump(mode="json")
    with pytest.raises(DomainValidationError, match="参数引用必须同时声明为前置步骤"):
        validate_plan(plan, {"project.read": operation})
    assert plan.model_dump(mode="json") == before

    plan.steps[-1].depends_on.append("source")
    assert validate_plan(plan, {"project.read": operation}) == plan


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["start", "detail", "revise"])
async def test_exploration_planner_descriptions_match_read_result_projection(
    monkeypatch, name
):
    from app.assistant_operation_registry import story_exploration_operations
    from modules.story import exploration_operations

    novel_id, root_id, branch_id, result_id, task_id = (
        str(uuid.uuid4()) for _ in range(5)
    )
    receipt = {
        "status": "completed",
        "root_id": root_id,
        "branch_id": branch_id,
        "result_id": result_id,
        "output_kind": "story.exploration.sandbox",
        "payload": _SANDOX_RECEIPT_PAYLOAD,
    }
    reference = {
        "task_id": task_id,
        "task_type": "story_exploration_progression_task",
        "root_id": root_id,
    }

    async def completed_task(_db, **kwargs):
        assert kwargs["novel_id"] == novel_id
        assert kwargs["task_id"] == task_id
        assert kwargs["task_type"] == reference["task_type"]
        return SimpleNamespace(result=receipt)

    monkeypatch.setattr(
        exploration_operations, "get_completed_task_payload", completed_task
    )
    operation = story_exploration_operations["story.exploration." + name]
    result = await operation.read_result(None, novel_id, reference)
    assert result["status"] == "completed"
    for field in ("result_id", "root_id", "branch_id", "output_kind", "payload"):
        assert field in operation.description
        assert result[field] == receipt[field]


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


# ---------------------------------------------------------------------------
# M4-B 切片 1：探索操作接入目标运行（goal runs）
# ---------------------------------------------------------------------------


@pytest.fixture
def exploration_gate(monkeypatch):
    from core.config import get_settings

    monkeypatch.setenv("STORY_EXPLORATION_ENABLED", "true")
    get_settings.cache_clear()
    yield
    monkeypatch.setenv("STORY_EXPLORATION_ENABLED", "false")
    get_settings.cache_clear()


def _provisional_start():
    from modules.evidence.contracts import Assumption, ProvisionalStart

    return ProvisionalStart(
        kind="provisional",
        question="这个城镇每天只有一小时重力减半，面包师的一天会怎样？",
        assumptions=[Assumption(kind="world_rule", text="每天只有一小时重力减半")],
        time_basis="assumed_now",
    )


_SANDOX_RECEIPT_PAYLOAD = {
    "question": "重力减半后面包师的一天？",
    "influence_chain": [
        {
            "condition": "揉面时间不变",
            "mechanism": "重力降低让面团发酵更快",
            "effect": "面包更松软",
        }
    ],
    "preconditions": [],
    "unknowns": ["无精确生产参数，不编造产出变化"],
}


def _exploration_start_parameters(novel_id: str) -> dict:
    from modules.story.exploration_budget import preview_exploration_budget

    start = _provisional_start()
    budget = preview_exploration_budget(
        novel_id=novel_id,
        scale="sandbox",
        start=start,
        focus="",
    )
    return {
        "novel_id": novel_id,
        "scale": "sandbox",
        "start": start.model_dump(mode="json"),
        "focus": "",
        "action": "story.exploration.sandbox.generate",
        "context_confirmation_id": str(uuid.uuid4()),
        "budget_preview_hash": budget.preview_hash,
        "operation_id": str(uuid.uuid4()),
        "time_budget_seconds": 3600,
    }


def _exploration_goal_plan(novel_id: str) -> GoalPlan:
    return GoalPlan.model_validate(
        {
            "title": "沙盘看一条规则影响",
            "steps": [
                {
                    "step_id": "explore",
                    "operation_id": "story.exploration.start",
                    "parameters": _exploration_start_parameters(novel_id),
                    "intent": "看规则对日常的影响并停在结果",
                }
            ],
        }
    )


def _stub_exploration_worker(
    monkeypatch, *, usage: dict | None, fail: bool = False, fail_after_usage: bool = False
):
    """把两个探索任务类型的 handler 替换为离线桩：可产生账本用量或失败。"""
    from infrastructure.llm.schemas import LLMUsage
    from infrastructure.llm.workflow_budget import (
        AIManagedStepContext,
        AIStepCallKind,
        current_ai_run_envelope,
        managed_step_scope,
    )
    from infrastructure.tasks.registry import TaskRegistry

    async def stub_handler(db, task):  # noqa: ARG001 - 与任务处理器签名一致
        envelope = current_ai_run_envelope()
        assert envelope is not None
        assert envelope.run_id == str(task.meta["exploration_root_id"])
        assert envelope.root_capability_id == "story.exploration"
        if fail:
            raise RuntimeError("stub exploration worker failure")
        if usage is not None:
            with managed_step_scope(
                AIManagedStepContext(
                    step_name="story.exploration.sandbox.generate",
                    call_kind=AIStepCallKind.structured,
                    capability_id="story.exploration",
                )
            ):
                reservation = await envelope.reserve()
                if usage.get("unknown"):
                    await envelope.settle(reservation)
                else:
                    await envelope.settle(
                        reservation,
                        usage=LLMUsage(
                            prompt_tokens=usage["prompt_tokens"],
                            completion_tokens=usage["completion_tokens"],
                            total_tokens=usage["total_tokens"],
                        ),
                    )
        if fail_after_usage:
            raise RuntimeError("stub failure after provider response")
        return {
            "status": "completed",
            "root_id": str(task.meta["exploration_root_id"]),
            "branch_id": str(task.meta["exploration_branch_id"]),
            "result_id": str(uuid.uuid4()),
            "output_kind": "story.exploration.sandbox",
            "payload": _SANDOX_RECEIPT_PAYLOAD,
        }

    original = TaskRegistry.get_handler

    def patched(self, task_type):
        if task_type in {
            "story_exploration_progression_task",
            "story_exploration_scene_task",
        }:
            return stub_handler
        return original(self, task_type)

    monkeypatch.setattr(TaskRegistry, "get_handler", patched)


def _stub_exploration_domain_inputs(monkeypatch, *, calls: list | None = None):
    """替换 Evidence 确认与执行快照：确认重用同一 ID，不新建确认。"""
    from types import SimpleNamespace

    from modules.story import exploration_api

    async def fresh_confirmation(_db, *, novel_id, action, confirmation_id):
        if calls is not None:
            calls.append({"action": action, "confirmation_id": confirmation_id})
        return SimpleNamespace(
            compile_options={
                "exploration_start": _provisional_start().model_dump(mode="json"),
                "exploration_scale": "sandbox",
                "exploration_focus": "",
            }
        )

    async def snapshot(_db, novel_id):
        return {"novel_id": novel_id}

    async def attach_ref(
        _db, *, novel_id, confirmation_id, result_type, result_id, status
    ):  # noqa: E501
        return None

    monkeypatch.setattr(exploration_api, "require_fresh_confirmation", fresh_confirmation)
    # 操作目录 prepare 直接从 evidence facade 导入；与探索 API 共用同一桩。
    import modules.evidence.facade as evidence_facade

    monkeypatch.setattr(evidence_facade, "require_fresh_confirmation", fresh_confirmation)
    monkeypatch.setattr(exploration_api, "build_project_llm_execution_snapshot", snapshot)
    monkeypatch.setattr(exploration_api, "attach_result_ref", attach_ref)


def _exploration_goal_env(monkeypatch, db_session, test_project_id, owner_id, plan):
    from app.assistant_operation_registry import story_exploration_operations
    from modules.assistant.goal_runs import service

    async def no_project_gate(*_args, **_kwargs):
        return None

    async def project_context(*_args, **_kwargs):
        return SimpleNamespace(
            project_kind="author",
            owner_id=owner_id,
            title="测试小说",
            genre="奇幻",
            tone="沉静",
            language="zh",
            current_stage="世界构建",
        )

    async def trace_disabled(*_args, **_kwargs):
        return False

    async def project_snapshot(*_args, **_kwargs):
        return _offline_snapshot()

    @asynccontextmanager
    async def offline_client(*_args, **_kwargs):
        yield _PlanningClient(plan)

    monkeypatch.setattr(service, "_require_goal_project", no_project_gate)
    monkeypatch.setattr(service, "get_any_project_context", project_context)
    monkeypatch.setattr(service, "_trace_enabled", trace_disabled)
    monkeypatch.setattr(service, "build_project_llm_execution_snapshot", project_snapshot)
    monkeypatch.setattr(service, "open_project_snapshot_llm_client", offline_client)
    monkeypatch.setattr(
        service, "_operation_registry", lambda: story_exploration_operations
    )
    return service


@pytest.mark.asyncio
async def test_goal_exploration_start_step_approval_and_domain_ledger_import(
    db_session, test_project_id, monkeypatch, exploration_gate
):
    """探索 start：R2 步骤批准 → 领域独立账本执行 → 增量汇入目标总账。"""
    import modules.story.exploration_tasks  # noqa: F401
    from infrastructure.tasks.models import AsyncTask
    from modules.story.world_progression_models import StoryWorldProgressionRoot

    owner_id = str(current_account_id())
    plan = _exploration_goal_plan(test_project_id)
    service = _exploration_goal_env(
        monkeypatch, db_session, test_project_id, owner_id, plan
    )
    confirmation_calls: list[dict] = []
    _stub_exploration_domain_inputs(monkeypatch, calls=confirmation_calls)
    _stub_exploration_worker(
        monkeypatch,
        usage={"prompt_tokens": 90, "completion_tokens": 30, "total_tokens": 120},
    )

    request = _start_request(uuid.UUID(test_project_id))
    request.budget.requests = 10
    request.budget.possible_charge_requests = 10
    request.budget.tokens = 200000
    prepared = await service.start_goal(db_session, request, owner_id)
    assert prepared["phase"] == "plan_review"
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
    # 探索 start 是 confirm/R2：计划批准后仍需作者步骤批准（现有 step 流程）。
    assert approved["status"] == "waiting_approval"
    assert approved["phase"] == "step_review"
    assert approved["steps"][0]["status"] == "prepared"

    completed = await service.approve_goal_step(
        db_session,
        novel_id=test_project_id,
        run_id=prepared["run_id"],
        owner_id=owner_id,
        data=GoalStepApproval(
            expected_revision=approved["revision"],
            step_id="explore",
            approve=True,
        ),
    )
    assert completed["status"] == "completed", completed.get("stop_reason")
    assert completed["steps"][0]["status"] == "completed"
    # 目标总账 = 规划 2 次 + 探索任务增量 1 次；令牌含领域汇入的 120。
    assert completed["budget"]["used"]["requests"] == 3
    assert completed["budget"]["used"]["tokens"] == 40 + 120
    assert completed["budget"]["used"]["charge_state"] == "recorded"

    run = await service._load_goal_run(
        db_session, test_project_id, prepared["run_id"], owner_id
    )
    goal = run.checkpoint_json["goal"]
    record = service._step_records(goal)["explore"]
    assert record["reference"]["task_type"] == "story_exploration_progression_task"
    assert record["result"]["output_kind"] == "story.exploration.sandbox"
    assert record["result"]["result_id"]
    assert record["result"]["payload"]["influence_chain"]
    # 领域任务绑定目标父任务；领域根账本镜像保留真实消耗。
    task = await db_session.get(AsyncTask, uuid.UUID(record["reference"]["task_id"]))
    assert task.meta["_parent_task_id"] == str(run.task_id)
    root = await db_session.get(
        StoryWorldProgressionRoot, uuid.UUID(record["reference"]["root_id"])
    )
    mirrored = root.run_envelope_json
    assert mirrored["requests_started"] == 1
    assert mirrored["usage"]["total_tokens"] == 120
    # 同一确认被复用（prepare + apply），不逐层新建授权。
    assert {item["confirmation_id"] for item in confirmation_calls} == {
        plan.steps[0].parameters["context_confirmation_id"]
    }


@pytest.mark.asyncio
async def test_goal_exploration_unknown_domain_usage_stops_goal_for_review(
    db_session, test_project_id, monkeypatch, exploration_gate
):
    """领域未知计费汇入目标总账后按未知语义停止；不返还、不静默重发。"""
    import modules.story.exploration_tasks  # noqa: F401

    owner_id = str(current_account_id())
    plan = _exploration_goal_plan(test_project_id)
    service = _exploration_goal_env(
        monkeypatch, db_session, test_project_id, owner_id, plan
    )
    _stub_exploration_domain_inputs(monkeypatch)
    _stub_exploration_worker(monkeypatch, usage={"unknown": True})

    request = _start_request(uuid.UUID(test_project_id))
    request.budget.requests = 10
    request.budget.possible_charge_requests = 10
    request.budget.tokens = 200000
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
    resolved = await service.approve_goal_step(
        db_session,
        novel_id=test_project_id,
        run_id=prepared["run_id"],
        owner_id=owner_id,
        data=GoalStepApproval(
            expected_revision=approved["revision"], step_id="explore", approve=True
        ),
    )
    assert resolved["status"] == "waiting_approval"
    assert resolved["stop_code"] == "unknown_charge", resolved.get("stop_reason")
    assert resolved["budget"]["used"]["requests"] == 3
    assert resolved["budget"]["used"]["charge_state"] == "possible"
    envelope = service._envelope_from_run(
        await service._load_goal_run(
            db_session, test_project_id, prepared["run_id"], owner_id
        )
    ).snapshot()
    assert envelope.requests_unknown == 1
    # 步骤回执已完成，但目标在下一步骤前停止核对，不自动继续。
    assert resolved["steps"][0]["status"] == "completed"


def test_goal_domain_ledger_headroom_refuses_over_declared_allocation():
    """领域申报上限超过目标剩余额度时，先拒绝执行而不是超支后无法归集。"""
    from infrastructure.llm.workflow_budget import new_ai_run_envelope
    from modules.assistant.goal_runs import service

    budget = GoalBudget(
        requests=4, possible_charge_requests=4, tokens=4096, time_limit_seconds=600
    )
    envelope = new_ai_run_envelope(
        operation_id=str(uuid.uuid4()),
        run_id=str(uuid.uuid4()),
        root_capability_id="assistant.goal.run",
        novel_id=str(uuid.uuid4()),
        request_limit=budget.requests,
        token_limit=budget.tokens,
        budget_mode="goal",
        scope_fingerprint="a" * 64,
        authorized_step_capabilities=["assistant.goal.plan"],
    )

    class _Task:
        task_type = "story_exploration_progression_task"
        meta = {
            "exploration_authorized_requests": 3,
            "exploration_authorized_tokens": 5000,
        }

    reason = service._domain_ledger_headroom_reason(envelope, budget, _Task())
    assert reason and "申报 3 次请求" in reason and "剩余 4 次" in reason
    assert service._domain_ledger_declared_allocation(None) == (0, 0)

    class _SmallTask:
        task_type = "story_exploration_progression_task"
        meta = {
            "exploration_authorized_requests": 1,
            "exploration_authorized_tokens": 400,
        }

    assert service._domain_ledger_headroom_reason(envelope, budget, _SmallTask()) is None


@pytest.mark.parametrize(
    "requests,tokens,reason",
    [(9, 0, "80% 可能费用"), (11, 0, "可能产生费用"), (1, 800, "80% 令牌")],
)
def test_goal_counter_observes_live_detached_domain_ledger(requests, tokens, reason):
    from infrastructure.llm.schemas import LLMUsage
    from infrastructure.llm.workflow_budget import (
        AIRunBudgetExceededError,
        AIRunEnvelope,
        ai_run_scope,
        new_ai_run_envelope,
    )
    from modules.assistant.goal_runs import service

    budget = GoalBudget(
        requests=100, possible_charge_requests=10, tokens=1000, time_limit_seconds=600
    )
    parent = new_ai_run_envelope(
        operation_id=str(uuid.uuid4()),
        run_id=str(uuid.uuid4()),
        root_capability_id="assistant.goal.run",
        novel_id=str(uuid.uuid4()),
        request_limit=100,
        token_limit=1000,
        budget_mode="goal",
        scope_fingerprint="a" * 64,
    )
    snapshot = parent.snapshot().model_copy(deep=True)
    snapshot.run_id = str(uuid.uuid4())
    snapshot.requests_started = requests
    snapshot.usage = LLMUsage(
        prompt_tokens=tokens, completion_tokens=0, total_tokens=tokens
    )
    from infrastructure.llm.schemas import AIStepReceiptV1

    snapshot.steps = [
        AIStepReceiptV1(
            step_name="assistant.goal.plan",
            step_capability_id="assistant.goal.run",
            call_kind="structured",
            requests_started=requests,
            requests_settled=requests,
            usage=snapshot.usage,
        )
    ]
    domain = AIRunEnvelope(snapshot)
    meter = service.GoalWorkflowCounter(
        parent,
        budget,
        domain_baseline={
            "requests_started": 0,
            "requests_unknown": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
        },
    )
    with ai_run_scope(domain), pytest.raises(AIRunBudgetExceededError, match=reason):
        meter.reserve(requests=1)
    assert parent.snapshot().requests_started == 0


def test_goal_headroom_uses_possible_charge_limit_before_dispatch():
    from infrastructure.llm.workflow_budget import new_ai_run_envelope
    from modules.assistant.goal_runs import service

    budget = GoalBudget(
        requests=20, possible_charge_requests=2, tokens=10000, time_limit_seconds=600
    )
    envelope = new_ai_run_envelope(
        operation_id=str(uuid.uuid4()),
        run_id=str(uuid.uuid4()),
        root_capability_id="assistant.goal.run",
        novel_id=str(uuid.uuid4()),
        request_limit=20,
        token_limit=10000,
        budget_mode="goal",
        scope_fingerprint="a" * 64,
    )
    task = SimpleNamespace(
        task_type="story_exploration_scene_task",
        meta={
            "exploration_authorized_requests": 3,
            "exploration_authorized_tokens": 100,
        },
    )
    assert "剩余 2 次" in service._domain_ledger_headroom_reason(envelope, budget, task)


async def test_goal_handoff_binds_preview_confirmation_start_without_extra_approval(
    db_session,
    test_project_id,
    monkeypatch,
    exploration_gate,
):
    import modules.story.exploration_tasks  # noqa: F401
    from modules.story import exploration_api
    from modules.story.tests.test_exploration_handoff import (
        _sandbox_envelope,
        _sandbox_start,
        _seed_source,
    )

    _root, _branch, source = await _seed_source(
        db_session,
        uuid.UUID(test_project_id),
        scale="sandbox",
        start=_sandbox_start(),
        envelope=_sandbox_envelope(),
    )

    def reference(step, *path):
        return {
            "$ref": {
                "step_id": step,
                "path": list(path),
                "value_type": "object" if path == ("derived_start",) else "string",
            }
        }

    base = {
        "novel_id": test_project_id,
        "scale": "event",
        "start": reference("handoff", "derived_start"),
        "focus": "先看订单如何送达",
        "action": "story.exploration.event.diagnose",
    }
    plan = GoalPlan.model_validate(
        {
            "title": "从条件影响推到事件路径",
            "steps": [
                {
                    "step_id": "handoff",
                    "operation_id": "story.exploration.handoff",
                    "intent": "保留候选条件",
                    "parameters": {
                        "novel_id": test_project_id,
                        "result_id": str(source.id),
                        "target_scale": "event",
                        "item_path": "chain:0",
                        "reason": "考察影响如何形成具体事件",
                    },
                },
                {
                    "step_id": "preview",
                    "operation_id": "story.exploration.confirmation_preview",
                    "intent": "只读目标资料",
                    "depends_on": ["handoff"],
                    "parameters": base,
                },
                {
                    "step_id": "confirm",
                    "operation_id": "story.exploration.confirm",
                    "intent": "在已批准目标内绑定资料",
                    "depends_on": ["handoff", "preview"],
                    "parameters": {
                        **base,
                        "expected_context_fingerprint": reference(
                            "preview", "context_fingerprint"
                        ),
                    },
                },
                {
                    "step_id": "start",
                    "operation_id": "story.exploration.start",
                    "intent": "在已批准预算内探索",
                    "depends_on": ["handoff", "preview", "confirm"],
                    "parameters": {
                        **base,
                        "operation_id": "goal-start",
                        "context_confirmation_id": reference(
                            "confirm", "confirmation_id"
                        ),
                        "budget_preview_hash": reference(
                            "preview", "budget", "preview_hash"
                        ),
                    },
                },
            ],
        }
    )
    owner = str(current_account_id())
    service = _exploration_goal_env(monkeypatch, db_session, test_project_id, owner, plan)

    async def snapshot(_db, novel_id):
        return {"novel_id": novel_id}

    monkeypatch.setattr(exploration_api, "build_project_llm_execution_snapshot", snapshot)
    _stub_exploration_worker(
        monkeypatch,
        usage={"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
    )
    request = _start_request(uuid.UUID(test_project_id))
    request.budget = GoalBudget(
        requests=20, possible_charge_requests=20, tokens=200000, time_limit_seconds=600
    )
    errors = []
    original_error_code = service._error_code

    def capture_error(error):
        errors.append(str(error))
        return original_error_code(error)

    monkeypatch.setattr(service, "_error_code", capture_error)
    prepared = await service.start_goal(db_session, request, owner)
    assert prepared["phase"] == "plan_review", errors
    result = await service.approve_goal_plan(
        db_session,
        novel_id=test_project_id,
        run_id=prepared["run_id"],
        owner_id=owner,
        data=GoalPlanApproval(
            expected_revision=prepared["revision"],
            plan=plan,
            budget=request.budget,
            auto_r2=True,
        ),
    )
    assert result["status"] == "completed", result
    assert all(step["status"] == "completed" for step in result["steps"])
    run = await db_session.get(AssistantRun, uuid.UUID(result["run_id"]))
    records = service._step_records(run.checkpoint_json["goal"])
    task = await db_session.get(
        AsyncTask, uuid.UUID(records["start"]["reference"]["task_id"])
    )
    assert task.meta["_execution_mode"] == "inline_only"
    assert task.meta["request"]["start"] == records["handoff"]["result"]["derived_start"]
    assert (
        task.meta["context_confirmation_id"]
        == records["confirm"]["result"]["confirmation_id"]
    )

    from app.assistant_operation_registry import story_exploration_operations
    from modules.assistant.goal_runs.planning import resolve_reference, step_operation_id

    results = service.records_to_results(records)
    described_paths = {
        "handoff": (("derived_start",),),
        "preview": (("context_fingerprint",), ("budget", "preview_hash")),
        "confirm": (("confirmation_id",),),
        "start": (
            ("result_id",),
            ("root_id",),
            ("branch_id",),
            ("output_kind",),
            ("payload",),
        ),
    }
    for step_id, paths in described_paths.items():
        step = next(item for item in plan.steps if item.step_id == step_id)
        description = service._operation_prompt(
            story_exploration_operations[step.operation_id], step.operation_id
        )["description"]
        for path in paths:
            assert ".".join(path) in description
            value_type = (
                "object" if path in {("derived_start",), ("payload",)} else "string"
            )
            value = resolve_reference(
                {
                    "$ref": {
                        "step_id": step_id,
                        "path": list(path),
                        "value_type": value_type,
                    }
                },
                results,
            )
            assert value is not None
    assert str(task.id) == step_operation_id(
        str(run.id), "start", records["start"]["parameter_fingerprint"]
    )


@pytest.mark.asyncio
async def test_goal_exploration_receipt_preview_and_reconcile_use_result_location(
    db_session, test_project_id, monkeypatch, exploration_gate
):
    """未知步骤核对：回执预览定位 exploration_result，作者确认后步骤完成。"""
    from app.assistant_operation_registry import story_exploration_operations
    from infrastructure.tasks.models import AsyncTask

    owner_id = str(current_account_id())
    plan = _exploration_goal_plan(test_project_id)
    service = _exploration_goal_env(
        monkeypatch, db_session, test_project_id, owner_id, plan
    )
    _stub_exploration_domain_inputs(monkeypatch)
    _stub_exploration_worker(monkeypatch, usage=None)

    request = _start_request(uuid.UUID(test_project_id))
    request.budget.requests = 4
    request.budget.possible_charge_requests = 4
    request.budget.tokens = 8192
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
    goal = run.checkpoint_json["goal"]
    step = plan.steps[0]
    operation = story_exploration_operations[step.operation_id]
    parameter_hash = service.parameter_fingerprint(operation, step.parameters)
    stable_operation_id = service.step_operation_id(
        str(run.id), step.step_id, parameter_hash
    )
    task_type = "story_exploration_progression_task"
    root_id, branch_id, result_id = (
        str(uuid.uuid4()),
        str(uuid.uuid4()),
        str(uuid.uuid4()),
    )
    reference = {
        "type": task_type,
        "task_id": stable_operation_id,
        "task_type": task_type,
        "operation_id": stable_operation_id,
    }
    db_session.add(
        AsyncTask(
            id=uuid.UUID(stable_operation_id),
            novel_id=uuid.UUID(test_project_id),
            task_type=task_type,
            status="done",
            meta={"_parent_task_id": str(run.task_id)},
            result={
                "status": "completed",
                "root_id": root_id,
                "branch_id": branch_id,
                "result_id": result_id,
                "output_kind": "story.exploration.sandbox",
                "payload": _SANDOX_RECEIPT_PAYLOAD,
            },
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
    run = await service._save_goal(db_session, run, goal, status="waiting_approval")

    preview = await service.goal_step_receipt_preview(
        db_session,
        test_project_id,
        prepared["run_id"],
        step.step_id,
        int(goal["revision"]),
        owner_id,
    )
    assert preview.status == "verified_applied"
    assert "沙盘" in preview.summary
    destination = preview.destination
    assert destination.kind == "exploration_result"
    assert str(destination.root_id) == root_id
    assert str(destination.result_id) == result_id
    assert destination.scale == "sandbox"

    resolved = await service.reconcile_goal_step(
        db_session,
        test_project_id,
        prepared["run_id"],
        step.step_id,
        GoalOutcomeReconciliation(
            expected_revision=preview.expected_revision, decision="applied"
        ),
        owner_id,
    )
    assert resolved["steps"][0]["status"] == "completed"
    assert resolved["stop_code"] == "step_receipt_applied"


@pytest.mark.asyncio
async def test_exploration_read_result_proves_outcomes_from_domain_state(
    db_session, test_project_id, monkeypatch, exploration_gate
):
    """完成=applied；失败且根已失败/首次领取前取消=not_applied；暂停=未知。"""
    from datetime import UTC, datetime, timedelta

    from infrastructure.llm.workflow_budget import new_ai_run_envelope
    from infrastructure.tasks.models import AsyncTask
    from modules.story.exploration_operations import _read_exploration_task_result
    from modules.story.exploration_service import create_exploration_root

    novel_id = test_project_id
    root, branch = await create_exploration_root(
        db_session,
        novel_id=novel_id,
        owner_id=str(current_account_id()),
        scale="sandbox",
        start=_provisional_start(),
        context_confirmation_id=str(uuid.uuid4()),
    )
    started_at = datetime.now(UTC)
    root.run_envelope_json = (
        new_ai_run_envelope(
            operation_id=str(uuid.uuid4()),
            run_id=str(root.id),
            root_capability_id="story.exploration",
            novel_id=novel_id,
            request_limit=1,
            budget_mode="bounded",
            token_limit=400,
            started_at=started_at,
            deadline_at=started_at + timedelta(hours=1),
        )
        .snapshot()
        .model_dump(mode="json")
    )
    await db_session.flush()

    def _reference(task_id: str) -> dict:
        return {
            "task_id": task_id,
            "task_type": "story_exploration_progression_task",
            "operation_id": task_id,
            "root_id": str(root.id),
            "branch_id": str(branch.id),
        }

    # 1) done + completed 回执 → completed，含结果定位字段。
    completed_task_id = str(uuid.uuid4())
    db_session.add(
        AsyncTask(
            id=uuid.UUID(completed_task_id),
            novel_id=uuid.UUID(novel_id),
            task_type="story_exploration_progression_task",
            status="done",
            meta={"_parent_task_id": "parent"},
            result={
                "status": "completed",
                "root_id": str(root.id),
                "branch_id": str(branch.id),
                "result_id": str(uuid.uuid4()),
                "output_kind": "story.exploration.sandbox",
                "payload": _SANDOX_RECEIPT_PAYLOAD,
            },
        )
    )
    receipt = await _read_exploration_task_result(
        db_session, novel_id, _reference(completed_task_id)
    )
    assert receipt["status"] == "completed"
    assert receipt["output_kind"] == "story.exploration.sandbox"
    assert receipt["payload"]["influence_chain"]

    # 2) done + paused_budget → incomplete，需作者在原工作台恢复。
    paused_task_id = str(uuid.uuid4())
    db_session.add(
        AsyncTask(
            id=uuid.UUID(paused_task_id),
            novel_id=uuid.UUID(novel_id),
            task_type="story_exploration_progression_task",
            status="done",
            meta={"_parent_task_id": "parent"},
            result={
                "status": "paused_budget",
                "root_id": str(root.id),
                "branch_id": str(branch.id),
                "budget_stop": "paused_budget",
            },
        )
    )
    receipt = await _read_exploration_task_result(
        db_session, novel_id, _reference(paused_task_id)
    )
    assert receipt["status"] == "incomplete"
    assert receipt["needs_author_resume"] is True

    # 3) 失败且探索根按失败收尾 → 可证明 not_applied。
    root.status = "failed"
    await db_session.flush()
    failed_task_id = str(uuid.uuid4())
    db_session.add(
        AsyncTask(
            id=uuid.UUID(failed_task_id),
            novel_id=uuid.UUID(novel_id),
            task_type="story_exploration_progression_task",
            status="failed",
            meta={"_parent_task_id": "parent"},
            error_message="boom",
        )
    )
    receipt = await _read_exploration_task_result(
        db_session, novel_id, _reference(failed_task_id)
    )
    assert receipt["status"] == "not_applied"
    assert receipt["proof"]["kind"] == "exploration_root_failed_without_result"

    # 4) 首次领取前取消 → 可证明 not_applied（与目标核对语义一致）。
    cancelled_task_id = str(uuid.uuid4())
    db_session.add(
        AsyncTask(
            id=uuid.UUID(cancelled_task_id),
            novel_id=uuid.UUID(novel_id),
            task_type="story_exploration_progression_task",
            status="cancelled",
            attempt=0,
        )
    )
    receipt = await _read_exploration_task_result(
        db_session, novel_id, _reference(cancelled_task_id)
    )
    assert receipt["status"] == "not_applied"
    assert receipt["proof"]["kind"] == "task_cancelled_before_first_claim"


@pytest.mark.asyncio
async def test_exploration_goal_apply_binds_stable_operation_parent_and_chain(
    monkeypatch, exploration_gate
):
    """goal 模式 apply 用目标冻结 operation_id 入队并绑定父任务与链上任务类型。"""
    from types import SimpleNamespace

    from modules.story import exploration_api, exploration_operations

    novel_id = str(uuid.uuid4())

    async def no_active_project(*_args, **_kwargs):
        return None

    monkeypatch.setattr(
        exploration_operations, "require_active_project", no_active_project
    )

    captured: dict = {}

    async def fake_start(db, *, data, owner_id=None, internal_meta=None):
        assert internal_meta["_execution_mode"] == "inline_only"
        captured["operation_id"] = str(data.operation_id)
        captured["internal_meta"] = internal_meta
        return {
            "task_id": str(data.operation_id),
            "status": "pending",
            "root_id": str(uuid.uuid4()),
            "branch_id": str(uuid.uuid4()),
        }

    async def fake_follow_up(db, **kwargs):
        captured["follow_up_operation_id"] = str(kwargs["operation_id"])
        captured["follow_up_meta"] = kwargs["internal_meta"]
        return {
            "task_id": str(kwargs["operation_id"]),
            "status": "pending",
            "root_id": str(uuid.uuid4()),
            "branch_id": str(uuid.uuid4()),
        }

    async def fake_locate(db, *, novel_id, result_id, lock=False):
        return None, "scene", None

    monkeypatch.setattr(exploration_api, "start_exploration_task", fake_start)
    monkeypatch.setattr(exploration_api, "submit_exploration_follow_up", fake_follow_up)
    monkeypatch.setattr(exploration_api, "_locate_exploration_result", fake_locate)

    context = SimpleNamespace(
        operation_id=str(uuid.uuid4()),
        internal_meta={"_execution_mode": "inline_only", "_parent_task_id": "parent-1"},
    )
    args = exploration_operations.ExplorationStartOperationRequest.model_validate(
        {
            "novel_id": novel_id,
            "scale": "sandbox",
            "start": {"kind": "scene_anchor", "scene_id": str(uuid.uuid4())},
            "action": "story.exploration.sandbox.generate",
            "context_confirmation_id": "conf-1",
            "budget_preview_hash": "a" * 64,
            "operation_id": str(uuid.uuid4()),
        }
    )
    receipt = await exploration_operations._apply_start(
        None, novel_id, args, {}, context=context
    )
    assert captured["operation_id"] == context.operation_id
    assert receipt["task_type"] == "story_exploration_progression_task"
    assert receipt["operation_id"] == context.operation_id
    assert captured["internal_meta"] == context.internal_meta

    detail_args = exploration_operations.ExplorationDetailOperationRequest.model_validate(
        {
            "novel_id": novel_id,
            "result_id": "result-1",
            "operation_id": str(uuid.uuid4()),
        }
    )
    receipt = await exploration_operations._apply_detail(
        None, novel_id, detail_args, {}, context=context
    )
    assert captured["follow_up_operation_id"] == context.operation_id
    assert captured["follow_up_meta"] == context.internal_meta
    assert receipt["task_type"] == "story_exploration_scene_task"


@pytest.mark.asyncio
async def test_exploration_non_goal_apply_keeps_client_operation_id(
    monkeypatch, exploration_gate
):
    """非 goal 模式保持既有行为：operation_id 来自请求，返回原 API 回执。"""

    from modules.story import exploration_api, exploration_operations

    novel_id = str(uuid.uuid4())

    async def no_active_project(*_args, **_kwargs):
        return None

    monkeypatch.setattr(
        exploration_operations, "require_active_project", no_active_project
    )

    captured: dict = {}

    async def fake_start(db, *, data, owner_id=None):
        captured["operation_id"] = str(data.operation_id)
        return {
            "task_id": "t-1",
            "status": "pending",
            "root_id": "r-1",
            "branch_id": "b-1",
        }

    monkeypatch.setattr(exploration_api, "start_exploration_task", fake_start)

    client_operation_id = str(uuid.uuid4())
    args = exploration_operations.ExplorationStartOperationRequest.model_validate(
        {
            "novel_id": novel_id,
            "scale": "sandbox",
            "start": {"kind": "scene_anchor", "scene_id": str(uuid.uuid4())},
            "action": "story.exploration.sandbox.generate",
            "context_confirmation_id": "conf-1",
            "budget_preview_hash": "a" * 64,
            "operation_id": client_operation_id,
        }
    )
    receipt = await exploration_operations._apply_start(
        None, novel_id, args, {}, context=None
    )
    assert captured["operation_id"] == client_operation_id
    assert receipt == {
        "task_id": "t-1",
        "status": "pending",
        "root_id": "r-1",
        "branch_id": "b-1",
        "task_type": "story_exploration_progression_task",
        "target_type": "story_exploration",
        "scale": "sandbox",
    }


@pytest.mark.parametrize("unknown", [False, True])
async def test_goal_failed_exploration_keeps_imported_usage_and_baseline(
    db_session, test_project_id, monkeypatch, exploration_gate, unknown
):
    owner_id = str(current_account_id())
    plan = _exploration_goal_plan(test_project_id)
    service = _exploration_goal_env(
        monkeypatch, db_session, test_project_id, owner_id, plan
    )
    _stub_exploration_domain_inputs(monkeypatch)
    _stub_exploration_worker(
        monkeypatch,
        usage={"unknown": True}
        if unknown
        else {"prompt_tokens": 90, "completion_tokens": 30, "total_tokens": 120},
        fail_after_usage=True,
    )
    request = _start_request(uuid.UUID(test_project_id))
    request.budget.requests = request.budget.possible_charge_requests = 10
    request.budget.tokens = 200000
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
    result = await service.approve_goal_step(
        db_session,
        novel_id=test_project_id,
        run_id=prepared["run_id"],
        owner_id=owner_id,
        data=GoalStepApproval(
            expected_revision=approved["revision"], step_id="explore", approve=True
        ),
    )
    assert result["stop_code"] == ("task_outcome_unknown" if unknown else "task_failed")
    assert result["budget"]["used"]["requests"] == 3
    assert result["budget"]["used"]["tokens"] == (40 if unknown else 160)
    assert result["budget"]["used"]["charge_state"] == (
        "possible" if unknown else "recorded"
    )
    run = await service._load_goal_run(
        db_session, test_project_id, prepared["run_id"], owner_id
    )
    goal = service._goal_state(run)
    record = service._step_records(goal)["explore"]
    assert record["domain_ledger_baseline"]["requests_started"] == 1
    from infrastructure.tasks.models import AsyncTask

    task = await db_session.get(AsyncTask, uuid.UUID(record["reference"]["task_id"]))
    ledger = service._envelope_from_run(run)
    before = ledger.snapshot().model_dump(mode="json")
    await service._import_domain_ledger_delta(ledger, task, record)
    assert ledger.snapshot().model_dump(mode="json") == before


async def test_domain_usage_import_settles_after_goal_deadline():
    from datetime import UTC, datetime, timedelta
    from types import SimpleNamespace

    from infrastructure.llm.schemas import AI_RUN_ENVELOPE_KEY, LLMUsage
    from infrastructure.llm.workflow_budget import (
        AIManagedStepContext,
        AIStepCallKind,
        managed_step_scope,
        new_ai_run_envelope,
    )
    from modules.assistant.goal_runs.service import _import_domain_ledger_delta

    deadline = datetime.now(UTC) - timedelta(seconds=1)
    goal = new_ai_run_envelope(
        operation_id="goal-import",
        run_id="goal-import",
        novel_id=str(uuid.uuid4()),
        root_capability_id="assistant.goal.run",
        request_limit=5,
        budget_mode="goal",
        scope_fingerprint="a" * 64,
        authorized_step_capabilities=["story.exploration"],
        started_at=deadline - timedelta(seconds=10),
        deadline_at=deadline,
    )
    # These are terminal source counts, not a new provider request.
    domain = new_ai_run_envelope(
        operation_id="domain",
        run_id="domain",
        root_capability_id="story.exploration",
        novel_id=goal.snapshot().novel_id,
        request_limit=5,
    )
    with managed_step_scope(
        AIManagedStepContext(step_name="domain", call_kind=AIStepCallKind.structured)
    ):
        request = await domain.reserve()
        await domain.settle(
            request,
            usage=LLMUsage(prompt_tokens=90, completion_tokens=30, total_tokens=120),
        )
    task = SimpleNamespace(
        task_type="story_exploration_scene_task",
        meta={AI_RUN_ENVELOPE_KEY: domain.snapshot().model_dump(mode="json")},
    )
    record = {}
    await _import_domain_ledger_delta(goal, task, record)
    assert goal.snapshot().requests_started == 1
    assert goal.snapshot().usage.total_tokens == 120
    assert record["domain_ledger_baseline"]["requests_started"] == 1
    before = goal.snapshot().model_dump(mode="json")
    await _import_domain_ledger_delta(goal, task, record)
    assert goal.snapshot().model_dump(mode="json") == before
    assert goal.snapshot().deadline_at == deadline
