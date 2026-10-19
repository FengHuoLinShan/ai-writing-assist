import json
import uuid
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from core.errors import ConflictError, NotFoundError
from infrastructure.llm.agent_runtime import AgentRunBudget
from infrastructure.llm.schemas import LLMUsage
from infrastructure.llm.workflow_budget import current_workflow_budget, workflow_budget
from modules.account.facade import current_account_id
from modules.assistant import approval
from modules.assistant.approval_cases import SUITE_HASH
from modules.assistant.approval_contracts import (
    APPROVAL_CAPABILITY,
    APPROVAL_POLICY,
    ApprovalJudgment,
    ApprovalTarget,
    TaskApprovalRequest,
)
from modules.assistant.contracts import AssistantOperation
from modules.assistant.evidence_tools import fingerprint
from modules.assistant.models import AssistantApprovalCalibration, AssistantRun


@pytest.fixture
async def approval_case(db_session, test_project_id, monkeypatch):
    owner_id = str(current_account_id())
    run = AssistantRun(
        id=uuid.uuid4(),
        novel_id=uuid.UUID(test_project_id),
        owner_id=uuid.UUID(owner_id),
        mode="author",
        status="running",
        request_hash="a" * 64,
        request_json={"context": {"page": "world", "scope": "project"}},
    )
    db_session.add(run)
    await db_session.flush()
    snapshot = {
        "purpose": "approval_judgment",
        "profile": {
            "provider_id": "codex",
            "model": "gpt-6-luna",
            "reasoning_effort": "low",
        },
    }

    async def build_snapshot(_db, novel_id, *, purpose):
        assert novel_id == test_project_id and purpose == "approval_judgment"
        return snapshot

    monkeypatch.setattr(approval, "build_project_llm_execution_snapshot", build_snapshot)
    case = SimpleNamespace(
        db=db_session,
        novel_id=test_project_id,
        owner_id=owner_id,
        run=run,
        snapshot=snapshot,
        target=f"world_entity:{uuid.uuid4()}",
        calls=[],
        scope={"object_versions": ["saved-v1"], "excluded": ["other-object"]},
        decision="allow",
        cancel=False,
        fingerprint_drift=False,
        fault=None,
        during=None,
    )
    case.budget = AgentRunBudget()
    case.checkpoints = []

    async def checkpoint(values):
        case.checkpoints.append(values)

    case.checkpoint = checkpoint

    async def prepare(*_args, **_kwargs):
        return {}

    case.operation = AssistantOperation(
        "修改对象",
        BaseModel,
        prepare,
        prepare,
        op_id="world.edit_entity",
        risk_level="R2",
    )

    @asynccontextmanager
    async def open_client(_db, novel_id, model_snapshot):
        assert novel_id == case.novel_id and model_snapshot == snapshot

        async def generate(request, schema, **options):
            assert request.max_tokens == 1024
            assert options == {
                "max_fix_attempts": 0,
                "format_repair_attempts": 0,
                "transport_retries": False,
            }
            assert issubclass(schema, ApprovalJudgment) and not request.tools
            data = json.loads(request.messages[-1].content)
            if case.preview is not None:
                assert data["untrusted_evidence"]["binding"]["preview"] == case.preview
            case.calls.append(data)
            meter = current_workflow_budget()
            from infrastructure.llm.workflow_budget import current_ai_run_envelope

            root = current_ai_run_envelope()
            reservation = await root.reserve() if root is not None else None
            await meter.before_request()
            if case.cancel:
                await approval.revoke_grant(
                    _db,
                    case.novel_id,
                    data["untrusted_evidence"]["binding"]["run_id"],
                    owner_id,
                    1,
                )
            if case.during:
                await case.during()
            if case.fault:
                raise case.fault
            usage = LLMUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15)
            if root is not None:
                from infrastructure.llm.schemas import AIRequestOutcome

                await root.settle(
                    reservation, usage=usage, outcome=AIRequestOutcome.succeeded
                )
            await meter.completed(usage)
            return ApprovalJudgment(
                decision=case.decision,
                fingerprint="f" * 64 if case.fingerprint_drift else data["fingerprint"],
                reason="符合明确的保留要求"
                if case.decision == "allow"
                else "需要核对创作取舍",
            )

        yield SimpleNamespace(
            runtime_scope={"profile_source": "account"},
            profile_summary={},
            generate_structured=generate,
        )

    monkeypatch.setattr(approval, "open_project_snapshot_llm_client", open_client)
    monkeypatch.setattr(
        approval,
        "current_ai_run_envelope",
        lambda: SimpleNamespace(
            snapshot=lambda: SimpleNamespace(
                authorized_step_capabilities=[APPROVAL_CAPABILITY],
                requests_unknown=0,
                usage_complete=True,
            )
        ),
    )

    async def restore(_db, novel_id, model_snapshot):
        assert novel_id == case.novel_id and model_snapshot == snapshot
        return {}

    monkeypatch.setattr(approval, "restore_project_llm_execution_settings", restore)
    case.preview = {
        "target": case.target,
        "before": "旧简介",
        "after": "旅人",
        "source_version": "v1",
    }
    return case


async def _enable(case):
    await _calibrate(case)
    return await approval.create_grant(
        case.db,
        case.run,
        TaskApprovalRequest(preserve=["保留姓名"], max_judgments=2),
        intent="把简介改为旅人",
        targets=[ApprovalTarget(kind="world_entity", id=case.target.split(":")[1])],
        scope=case.scope,
        budget=case.budget.model_dump(mode="json"),
    )


async def _calibrate(case):
    case.db.add(
        AssistantApprovalCalibration(
            novel_id=case.run.novel_id,
            owner_id=case.run.owner_id,
            model_fingerprint=approval.calibration_fingerprint(case.snapshot),
            policy_version=APPROVAL_POLICY,
            suite_hash=SUITE_HASH,
            receipt_json={"passed": True},
        )
    )
    await case.db.flush()


async def _judge(case, **overrides):
    with workflow_budget(case.budget, case.checkpoint):
        return await approval.judge_preview(
            case.db,
            case.run,
            **{
                "preview": case.preview,
                "operations": [case.operation],
                "targets": [case.target],
                "scope_fingerprint": fingerprint(case.scope),
                **overrides,
            },
        )


@pytest.mark.asyncio
async def test_grant_requires_exact_calibrated_model_and_is_owner_scoped(approval_case):
    case = approval_case
    with pytest.raises(ConflictError, match="实测"):
        await approval.create_grant(
            case.db,
            case.run,
            TaskApprovalRequest(),
            intent="更新简介",
            targets=[ApprovalTarget(kind="world_entity", id="object")],
            scope=case.scope,
            budget={},
        )
    await _enable(case)
    view = await approval.grant_view(
        case.db, case.novel_id, str(case.run.id), case.owner_id
    )
    assert view["mode"] == "automatic" and view["task"]["preserve"] == ["保留姓名"]
    assert view["model"]["reasoning_effort"] == "low"
    with pytest.raises(NotFoundError):
        await approval.grant_view(
            case.db, case.novel_id, str(case.run.id), str(uuid.uuid4())
        )
    assert not case.calls


@pytest.mark.asyncio
@pytest.mark.parametrize("decision", ["allow", "ask", "deny"])
async def test_exact_judgment_replay_uses_parent_budget_once(approval_case, decision):
    case = approval_case
    await _enable(case)
    case.decision = decision
    receipt = await _judge(case)
    assert receipt["decision"] == decision
    assert (await _judge(case))["id"] == receipt["id"]
    assert len(case.calls) == case.budget.requests == 1
    assert case.budget.pending_usage == 0 and case.budget.prompt_tokens == 10
    if decision == "allow":
        grant, _attempt = await approval.require_execution_approval(
            case.db, case.run, receipt["id"], case.preview
        )
        approval.record_execution(
            grant, receipt["id"], {"status": "completed", "id": "domain-receipt"}
        )
        await case.db.commit()
        assert (await _judge(case))["execution"]["id"] == "domain-receipt"
    else:
        with pytest.raises(ConflictError):
            await approval.require_execution_approval(
                case.db, case.run, receipt["id"], case.preview
            )


@pytest.mark.asyncio
async def test_scope_reserved_operations_and_missing_parent_never_call_judge(
    approval_case, monkeypatch
):
    case = approval_case
    await _enable(case)
    for overrides in (
        {"targets": ["world_entity:outside"]},
        {"scope_fingerprint": "changed"},
        {
            "operations": [
                replace(case.operation, op_id="world.entity.merge", risk_level="R3")
            ]
        },
        {"operations": [replace(case.operation, reversibility="irreversible")]},
        {"operations": [replace(case.operation, transaction_mode="multi_stage")]},
    ):
        assert (await _judge(case, **overrides))["decision"] == "ask"
    monkeypatch.setattr(approval, "current_ai_run_envelope", lambda: None)
    assert (await _judge(case))["decision"] == "ask"
    assert not case.calls and case.budget.requests == 0


@pytest.mark.asyncio
async def test_relation_grant_is_exact_and_removal_stays_manual(approval_case):
    from modules.assistant.schemas import WorkContext

    case = approval_case
    entity_id, relation_id = str(uuid.uuid4()), str(uuid.uuid4())
    work = WorkContext.model_validate(
        {
            "page": "world",
            "target": {"target_type": "core_entity", "target_id": entity_id},
            "focus_ref": {
                "kind": "relation",
                "entity_id": entity_id,
                "relation_id": relation_id,
                "updated_at": "2026-10-18T12:00:00Z",
            },
        }
    )
    targets = approval.work_targets(work)
    assert [target.model_dump() for target in targets] == [
        {"kind": "world_relation", "id": relation_id}
    ]
    await _calibrate(case)
    await approval.create_grant(
        case.db,
        case.run,
        TaskApprovalRequest(),
        intent="结束已选关系的有效期，保留关系",
        targets=targets,
        scope=case.scope,
        budget=case.budget.model_dump(mode="json"),
    )
    operation = replace(case.operation, op_id="world.maintain_relation", risk_level="R3")
    target = f"world_relation:{relation_id}"
    assert approval.action_targets(
        [
            {
                "capability": operation.op_id,
                "arguments": {"relation_id": relation_id},
                "preview": {},
            }
        ]
    ) == [target]
    for op, current_target in (
        (operation, "world_relation:outside"),
        (replace(operation, op_id="world.remove_relation", risk_level="R4"), target),
    ):
        assert (await _judge(case, operations=[op], targets=[current_target]))[
            "decision"
        ] == "ask"
    assert not case.calls
    receipt = await _judge(case, operations=[operation], targets=[target])
    assert receipt["decision"] == "allow" and len(case.calls) == 1
    await approval.require_execution_approval(
        case.db, case.run, receipt["id"], case.preview
    )


@pytest.mark.asyncio
async def test_revocation_during_model_io_blocks_execution(approval_case):
    case = approval_case
    await _enable(case)
    case.cancel = True
    receipt = await _judge(case)
    assert receipt["decision"] == "ask" and "撤回" in receipt["reason"]
    with pytest.raises(ConflictError, match="撤回"):
        await approval.require_execution_approval(
            case.db, case.run, receipt["id"], case.preview
        )
    assert len(case.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["timeout", "invalid", "fingerprint"])
async def test_unknown_or_invalid_judgment_is_not_retried(approval_case, failure):
    case = approval_case
    await _enable(case)
    if failure == "fingerprint":
        case.fingerprint_drift = True
    else:
        case.fault = (
            TimeoutError() if failure == "timeout" else ValueError("invalid output")
        )
    receipt = await _judge(case)
    assert receipt["decision"] == "ask"
    await _judge(case)
    assert len(case.calls) == 1


@pytest.mark.asyncio
async def test_changed_preview_or_expired_version_cannot_execute(approval_case):
    case = approval_case
    await _enable(case)
    receipt = await _judge(case)
    with pytest.raises(ConflictError, match="预览"):
        await approval.require_execution_approval(
            case.db, case.run, receipt["id"], {**case.preview, "after": "另一个名字"}
        )
    await approval.revoke_grant(
        case.db, case.novel_id, str(case.run.id), case.owner_id, 1
    )
    with pytest.raises(ConflictError):
        await approval.require_execution_approval(
            case.db, case.run, receipt["id"], case.preview
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("changed", [False, True])
async def test_batch_uses_real_world_write_and_revalidates_after_judgment(
    approval_case, test_entity_id, changed
):
    from app.assistant_operation_registry import world_operations
    from core.container import container_scope
    from modules.assistant.contracts import AssistantOperationContext
    from modules.assistant.models import AssistantActionBatch
    from modules.assistant.operations import decide_batch, prepare_actions
    from modules.assistant.schemas import BatchDecision, ProposedAction, WorkContext
    from modules.world.models import CoreEntity

    case = approval_case
    case.target = f"world_entity:{test_entity_id}"
    case.scope = {"page": "world", "scope": "project"}
    case.run.request_json = {"context": case.scope}
    await _enable(case)
    with container_scope({"assistant.operations": world_operations}):
        actions = await prepare_actions(
            case.db,
            case.novel_id,
            [
                ProposedAction(
                    key="edit",
                    capability="world.edit_entity",
                    title="修改简介",
                    arguments={
                        "entity_id": test_entity_id,
                        "changes": {"summary": "旅人"},
                    },
                )
            ],
            context=AssistantOperationContext(
                str(case.run.id),
                case.owner_id,
                WorkContext(page="world", scope="project"),
            ),
        )
        batch = AssistantActionBatch(
            novel_id=case.run.novel_id,
            run_id=case.run.id,
            fingerprint=fingerprint(actions),
            actions_json=actions,
        )
        case.db.add(batch)
        await case.db.flush()
        case.preview = approval.batch_preview(batch)
        if changed:

            async def concurrent_edit():
                row = await case.db.get(CoreEntity, uuid.UUID(test_entity_id))
                row.summary = "作者后来修改的简介"
                await case.db.commit()

            case.during = concurrent_edit
        await case.db.commit()
        with workflow_budget(case.budget, case.checkpoint):
            await approval.automatically_decide_batch(
                case.db, case.run, batch, world_operations
            )
        await case.db.commit()
        await case.db.refresh(case.run)
        row = await case.db.get(CoreEntity, uuid.UUID(test_entity_id))
        await case.db.refresh(row)
        assert row.summary == ("作者后来修改的简介" if changed else "旅人")
        assert case.run.result_json["automatic_decision"]["decision"] == (
            "ask" if changed else "allow"
        )
        if not changed:
            await case.db.refresh(batch)
            assert batch.authorization_json["mode"] == "automatic"
            assert batch.status == "completed"
            receipt = await decide_batch(
                case.db,
                str(batch.id),
                BatchDecision(
                    novel_id=case.novel_id,
                    fingerprint=batch.fingerprint,
                    selected=["edit"],
                    confirmed=True,
                ),
                case.owner_id,
            )
            assert receipt["status"] == "completed" and len(case.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("decision", ["allow", "ask", "deny"])
async def test_goal_shares_exact_judge_and_root_budget(
    approval_case, test_entity_id, monkeypatch, decision
):
    from app.assistant_operation_registry import world_operations
    from infrastructure.llm.workflow_budget import current_ai_run_envelope
    from modules.assistant.goal_runs import service
    from modules.assistant.goal_runs.contracts import GoalPlan, GoalPlanApproval
    from modules.assistant.tests.test_goal_runs import (
        _install_offline_goal_planner,
        _start_request,
    )
    from modules.world.models import CoreEntity

    case = approval_case
    case.preview, case.decision = None, decision
    await _calibrate(case)
    monkeypatch.setattr(approval, "current_ai_run_envelope", current_ai_run_envelope)
    plan = GoalPlan(
        title="修改指定人物简介",
        steps=[
            {
                "step_id": "edit",
                "operation_id": "world.edit_entity",
                "targets": [{"target_type": "world_entity", "target_id": test_entity_id}],
                "parameters": {
                    "entity_id": test_entity_id,
                    "changes": {"summary": "旅人"},
                },
                "intent": "把简介改为旅人",
            }
        ],
    )
    _install_offline_goal_planner(monkeypatch, plan)
    monkeypatch.setattr(
        service,
        "_operation_registry",
        lambda: {"world.edit_entity": world_operations["world.edit_entity"]},
    )
    request = _start_request(uuid.UUID(case.novel_id))
    prepared = await service.start_goal(case.db, request, case.owner_id)
    result = await service.approve_goal_plan(
        case.db,
        case.novel_id,
        prepared["run_id"],
        GoalPlanApproval(
            expected_revision=prepared["revision"],
            plan=plan,
            budget=request.budget,
            approval=TaskApprovalRequest(preserve=["保留姓名"]),
        ),
        case.owner_id,
    )
    view = (
        result
        if isinstance(result, dict)
        else await service.goal_view(case.db, result, owner_id=case.owner_id)
    )
    row = await case.db.get(CoreEntity, uuid.UUID(test_entity_id))
    await case.db.refresh(row)
    assert (row.summary == "旅人") == (decision == "allow")
    assert view["status"] == (
        "completed" if decision == "allow" else "waiting_approval"
    ), view
    assert view["budget"]["used"]["requests"] == 3
    assert len(case.calls) == 1
    grant_view = await approval.grant_view(
        case.db, case.novel_id, prepared["run_id"], case.owner_id
    )
    assert grant_view["decisions"][0]["decision"] == decision
    if decision == "allow":
        assert grant_view["decisions"][0]["execution"]["step_id"] == "edit"


@pytest.mark.asyncio
@pytest.mark.parametrize("misclassify", [False, True])
async def test_fixed_calibration_is_metered_and_never_sends_expected_answers(
    approval_case, monkeypatch, misclassify
):
    from datetime import UTC, datetime, timedelta

    from infrastructure.llm.schemas import AIRequestOutcome
    from infrastructure.llm.workflow_budget import ai_run_scope, new_ai_run_envelope
    from modules.assistant import approval_calibration
    from modules.assistant.approval_cases import CASES

    case = approval_case
    monkeypatch.setattr(
        approval_calibration,
        "build_project_llm_execution_snapshot",
        approval.build_project_llm_execution_snapshot,
    )
    root = new_ai_run_envelope(
        operation_id=str(uuid.uuid4()),
        run_id=str(uuid.uuid4()),
        root_capability_id=APPROVAL_CAPABILITY,
        novel_id=case.novel_id,
        request_limit=len(CASES),
        token_limit=65536,
        deadline_at=datetime.now(UTC) + timedelta(minutes=10),
    )
    calls = []

    @asynccontextmanager
    async def open_client(*_args):
        async def generate(request, schema, **options):
            payload = json.loads(request.messages[-1].content)
            assert "expected" not in request.messages[-1].content
            assert (
                issubclass(schema, ApprovalJudgment) and options["max_fix_attempts"] == 0
            )
            assert (
                schema.model_json_schema()["properties"]["fingerprint"]["const"]
                == payload["fingerprint"]
            )
            evidence = payload["untrusted_evidence"]
            expected = next(
                item["expected"] for item in CASES if item["id"] == evidence["id"]
            )
            calls.append(evidence["id"])
            reservation = await root.reserve()
            meter = current_workflow_budget()
            await meter.before_request()
            usage = LLMUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15)
            await root.settle(
                reservation, usage=usage, outcome=AIRequestOutcome.succeeded
            )
            await meter.completed(usage)
            return ApprovalJudgment(
                decision="allow" if misclassify else expected,
                fingerprint=payload["fingerprint"],
                reason="合成测试",
            )

        yield SimpleNamespace(
            runtime_scope={"profile_source": "account"},
            profile_summary={},
            generate_structured=generate,
        )

    monkeypatch.setattr(
        approval_calibration, "open_project_snapshot_llm_client", open_client
    )
    budget = AgentRunBudget(policy_version="team_v1")
    with ai_run_scope(root), workflow_budget(budget, case.checkpoint):
        report = await approval_calibration.calibrate_approval_model(
            case.db, case.novel_id, case.owner_id
        )
    assert len(calls) == root.snapshot().requests_started == budget.requests == len(CASES)
    assert report["passed"] is not misclassify and report["status"] == "completed"
    assert (report["false_allow"] > 0) is misclassify
    assert (await approval.approval_availability(case.db, case.novel_id, case.owner_id))[
        "available"
    ] is not misclassify


def test_bound_judgment_constrains_native_output_and_rejects_another_preview():
    from pydantic import ValidationError

    expected = "a" * 64
    schema = ApprovalJudgment.for_fingerprint(expected)
    assert schema.model_json_schema()["properties"]["fingerprint"]["const"] == expected
    assert (
        schema.model_validate(
            {"decision": "deny", "fingerprint": expected, "reason": "越界"}
        ).decision
        == "deny"
    )
    with pytest.raises(ValidationError):
        schema.model_validate(
            {"decision": "allow", "fingerprint": "b" * 64, "reason": "另一份预览"}
        )


async def _approve_offline_goal(case, plan, operations, monkeypatch):
    from infrastructure.llm.workflow_budget import current_ai_run_envelope
    from modules.assistant.goal_runs import service
    from modules.assistant.goal_runs.contracts import GoalPlanApproval
    from modules.assistant.tests.test_goal_runs import (
        _install_offline_goal_planner,
        _start_request,
    )

    await _calibrate(case)
    case.preview = None
    monkeypatch.setattr(approval, "current_ai_run_envelope", current_ai_run_envelope)
    _install_offline_goal_planner(monkeypatch, plan)
    monkeypatch.setattr(service, "_operation_registry", lambda: operations)
    request = _start_request(uuid.UUID(case.novel_id))
    request.budget.requests = request.budget.possible_charge_requests = 10
    prepared = await service.start_goal(case.db, request, case.owner_id)
    result = await service.approve_goal_plan(
        case.db,
        case.novel_id,
        prepared["run_id"],
        GoalPlanApproval(
            expected_revision=prepared["revision"],
            plan=plan,
            budget=request.budget,
            approval=TaskApprovalRequest(max_judgments=3),
        ),
        case.owner_id,
    )
    return request, prepared, result


@pytest.mark.asyncio
@pytest.mark.parametrize("resume_mode", ["same", "larger_budget", "revoked"])
async def test_goal_pause_resume_preserves_scope_budget_and_revocation(
    approval_case, test_entity_id, monkeypatch, resume_mode
):
    from app.assistant_operation_registry import world_operations
    from modules.assistant.goal_runs import service
    from modules.assistant.goal_runs.contracts import GoalPlan, GoalResume
    from modules.world.models import CoreEntity

    case = approval_case
    plan = GoalPlan.model_validate(
        {
            "title": "更新选定对象",
            "steps": [
                {
                    "step_id": "edit",
                    "operation_id": "world.edit_entity",
                    "intent": "更新简介",
                    "parameters": {
                        "entity_id": test_entity_id,
                        "changes": {"summary": "旅人"},
                    },
                    "targets": [
                        {"target_type": "world_entity", "target_id": test_entity_id}
                    ],
                }
            ],
        }
    )

    async def pause_before_write():
        case.during = None
        run_id = case.calls[-1]["untrusted_evidence"]["binding"]["run_id"]
        run = await service._load_goal_run(case.db, case.novel_id, run_id, case.owner_id)
        goal = service._goal_state(run)
        goal["pause_requested"] = True
        await service._save_goal(case.db, run, goal, status="running")

    case.during = pause_before_write
    request, prepared, stopped = await _approve_offline_goal(
        case,
        plan,
        {"world.edit_entity": world_operations["world.edit_entity"]},
        monkeypatch,
    )
    assert stopped["stop_code"] == "paused" and len(case.calls) == 1
    grant = await approval._grant(case.db, prepared["run_id"])
    expires_at = grant.policy_json["expires_at"]
    original_attempt = dict(grant.attempts_json[0])
    budget = request.budget.model_copy()
    if resume_mode == "larger_budget":
        budget.requests = budget.possible_charge_requests = 12
    elif resume_mode == "revoked":
        await approval.revoke_grant(
            case.db, case.novel_id, prepared["run_id"], case.owner_id, grant.version
        )
    resumed = await service.resume_goal(
        case.db,
        case.novel_id,
        prepared["run_id"],
        GoalResume(expected_revision=stopped["revision"], budget=budget),
        case.owner_id,
    )
    grant = await approval._grant(case.db, prepared["run_id"])
    run = await service._load_goal_run(
        case.db, case.novel_id, prepared["run_id"], case.owner_id
    )
    assert grant.policy_json["expires_at"] == expires_at
    row = await case.db.get(CoreEntity, uuid.UUID(test_entity_id))
    await case.db.refresh(row)
    if resume_mode == "revoked":
        assert grant.status == "revoked" and resumed["status"] == "waiting_approval"
        assert not resumed["automatic_approval"] and row.summary != "旅人"
        assert len(case.calls) == 1
    else:
        assert resumed["status"] == "completed" and row.summary == "旅人", {
            "stop": (resumed.get("stop_code"), resumed.get("stop_reason")),
            "decisions": [
                (item.get("decision"), item.get("reason")) for item in grant.attempts_json
            ],
            "steps": [
                (item.get("status"), item.get("automatic_decision"))
                for item in service._step_records(service._goal_state(run)).values()
            ],
        }
        assert (
            grant.policy_json["scope_fingerprint"]
            == service._goal_state(run)["approved_scope_fingerprint"]
        )
        assert grant.version == (2 if resume_mode == "larger_budget" else 1)
        assert len(case.calls) == (2 if resume_mode == "larger_budget" else 1)
        assert grant.attempts_json[0]["fingerprint"] == original_attempt["fingerprint"]


@pytest.mark.asyncio
async def test_budget_continuation_invalidates_old_approval_without_resetting_judgments(
    approval_case,
):
    case = approval_case
    case.scope["budget"] = {"requests": 4}
    await _enable(case)
    first = await _judge(case)
    case.preview = {**case.preview, "after": "下一项明确修改"}
    await _judge(case)
    proposed = {**case.scope, "budget": {"requests": 6}}
    assert await approval.resume_goal_grant(case.db, case.run, case.scope, proposed)
    case.scope = proposed
    grant = await approval._grant(case.db, case.run.id)
    assert grant.version == 2 and len(grant.attempts_json) == 2
    assert "次数已用完" in (await _judge(case))["reason"]
    assert len(case.calls) == 2
    with pytest.raises(ConflictError, match="失效"):
        await approval.require_execution_approval(
            case.db, case.run, first["id"], case.preview
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["expired", "pending", "scope_changed"])
async def test_budget_continuation_cannot_revive_or_expand_a_grant(approval_case, state):
    case = approval_case
    await _enable(case)
    grant = await approval._grant(case.db, case.run.id)
    if state == "expired":
        grant.policy_json = {
            **grant.policy_json,
            "expires_at": (datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
        }
    elif state == "pending":
        grant.attempts_json = [{"id": "unknown", "decision": "pending"}]
    proposed = {**case.scope, "budget": {"requests": 8}}
    if state == "scope_changed":
        proposed["excluded"] = []
        with pytest.raises(ConflictError, match="范围已变化"):
            await approval.resume_goal_grant(case.db, case.run, case.scope, proposed)
    else:
        assert not await approval.resume_goal_grant(
            case.db, case.run, case.scope, proposed
        )
    assert grant.version == 1
    assert grant.policy_json["scope_fingerprint"] == fingerprint(case.scope)


@pytest.mark.asyncio
@pytest.mark.parametrize("new_stop", [None, "pause_requested", "cancel_requested"])
async def test_resume_acknowledges_only_the_reviewed_pause(approval_case, new_stop):
    from modules.assistant.goal_runs import service

    case = approval_case
    goal = {
        "protocol": service.PROTOCOL,
        "revision": 1,
        "phase": "paused",
        "pause_requested": True,
    }
    case.run.mode = "goal"
    case.run.checkpoint_json = {"goal": goal}
    await case.db.commit()
    resumed = {**goal, "phase": "executing", "pause_requested": False}
    if new_stop:
        case.run.checkpoint_json = {"goal": {**goal, "revision": 2, new_stop: True}}
        await case.db.commit()
    saved = await service._save_goal(
        case.db, case.run, resumed, status="running", clear_pause_requested=True
    )
    current = service._goal_state(saved)
    assert bool(current.get("pause_requested")) is bool(new_stop)
    assert bool(current.get("cancel_requested")) is (new_stop == "cancel_requested")


@pytest.mark.parametrize(
    "mismatch",
    [
        None,
        "dependency",
        "path",
        "value_type",
        "status",
        "plan",
        "type",
        "id",
        "operation",
    ],
)
def test_created_target_requires_exact_completed_dependency_receipt(mismatch):
    from modules.assistant.goal_runs.contracts import GoalPlan
    from modules.assistant.goal_runs.planning import digest

    identity = str(uuid.uuid4())
    plan = GoalPlan.model_validate(
        {
            "title": "建立后完善对象",
            "steps": [
                {
                    "step_id": "create",
                    "operation_id": "world.create_entity",
                    "intent": "创建对象",
                },
                {
                    "step_id": "edit",
                    "operation_id": "world.edit_entity",
                    "intent": "完善对象",
                    "depends_on": ["create"],
                    "targets": [
                        {
                            "target_type": "world_entity",
                            "target_id": {
                                "step_id": "create",
                                "path": ["id"],
                                "value_type": "identifier",
                            },
                        }
                    ],
                },
            ],
        }
    )
    source, step = plan.steps
    record = {
        "status": "completed",
        "plan_step_fingerprint": digest(source.model_dump(mode="json")),
        "result": {"type": "world_entity", "id": identity},
    }
    if mismatch == "dependency":
        step.depends_on = []
    elif mismatch == "path":
        step.targets[0].target_id.path = ["other_id"]
    elif mismatch == "value_type":
        step.targets[0].target_id.value_type = "string"
    elif mismatch == "status":
        record["status"] = "prepared"
    elif mismatch == "plan":
        record["plan_step_fingerprint"] = "stale"
    elif mismatch == "type":
        record["result"]["type"] = "world_page"
    elif mismatch == "id":
        record["result"]["id"] = str(uuid.uuid4())
    elif mismatch == "operation":
        source.operation_id = "world.edit_entity"
        record["plan_step_fingerprint"] = digest(source.model_dump(mode="json"))
    assert approval.goal_step_targets(
        step, {"entity_id": identity}, {}, plan=plan, records={"create": record}
    ) == [f"world_entity:{identity}" if mismatch else "creation_slot:create"]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["relation", "create_then_relate", "restore"])
async def test_goal_automatic_registered_targets_and_creation_receipts(
    approval_case, test_entity_id, monkeypatch, kind
):
    from app.assistant_operation_registry import (
        world_operations,
        writing_candidate_operations,
    )
    from modules.assistant.goal_runs.contracts import GoalPlan
    from modules.world.models import CoreEntity
    from modules.world.repositories import EntityRelationRepository
    from modules.writing.facade import create_draft_only, get_latest_draft_for_chapter

    case = approval_case
    if kind == "restore":
        source = await create_draft_only(case.db, case.novel_id, 1, content="历史正文")
        await create_draft_only(case.db, case.novel_id, 1, content="后续正文")
        operations = {
            "writing.restore_version": writing_candidate_operations[
                "writing.restore_version"
            ]
        }
        steps = [
            {
                "step_id": "restore",
                "operation_id": "writing.restore_version",
                "intent": "从已保存历史版本继续写",
                "parameters": {"draft_id": source.id},
                "targets": [{"target_type": "writing_chapter", "target_id": source.id}],
            }
        ]
    else:
        other = CoreEntity(
            novel_id=uuid.UUID(case.novel_id),
            entity_type="character",
            name="船医",
            status="canonical",
        )
        case.db.add(other)
        await case.db.flush()
        other_id = str(other.id)
        operations = {"world.add_relation": world_operations["world.add_relation"]}
        steps = []
        source_id = test_entity_id
        target_id = source_id
        if kind == "create_then_relate":
            operations["world.create_entity"] = world_operations["world.create_entity"]
            steps.append(
                {
                    "step_id": "create",
                    "operation_id": "world.create_entity",
                    "intent": "创建巡港人",
                    "parameters": {"name": "沈砚", "entity_type": "character"},
                }
            )
            target_id = {"step_id": "create", "path": ["id"], "value_type": "identifier"}
            source_id = {"$ref": target_id}
        steps.append(
            {
                "step_id": "connect",
                "operation_id": "world.add_relation",
                "depends_on": ["create"] if kind == "create_then_relate" else [],
                "intent": "连接已核对的两端",
                "parameters": {
                    "source_id": source_id,
                    "target_id": other_id,
                    "relation_type": "ally_of",
                    "relation_kind": "social",
                },
                "targets": [
                    {"target_type": "world_entity_pair", "target_id": target_id},
                    {"target_type": "world_entity_pair", "target_id": other_id},
                ],
            }
        )
    plan = GoalPlan.model_validate({"title": "执行作者选定步骤", "steps": steps})
    _, prepared, result = await _approve_offline_goal(case, plan, operations, monkeypatch)
    assert result["status"] == "completed", result
    expected_calls = 2 if kind == "create_then_relate" else 1
    assert len(case.calls) == expected_calls
    grant = await approval.grant_view(
        case.db, case.novel_id, prepared["run_id"], case.owner_id
    )
    assert len(grant["decisions"]) == expected_calls
    assert all(item["execution"]["status"] == "completed" for item in grant["decisions"])
    if kind == "restore":
        current = await get_latest_draft_for_chapter(case.db, case.novel_id, 1)
        assert current.content == "历史正文" and current.id != source.id
    else:
        if kind == "create_then_relate":
            source_id = grant["decisions"][0]["execution"]["result"]["id"]
            created = await case.db.get(CoreEntity, uuid.UUID(source_id))
            assert created.name == "沈砚"
        relations = await EntityRelationRepository().get_by_source(
            case.db, uuid.UUID(case.novel_id), uuid.UUID(source_id)
        )
        assert len(relations) == 1 and str(relations[0].target_id) == other_id
