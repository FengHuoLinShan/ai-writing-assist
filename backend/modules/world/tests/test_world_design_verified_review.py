"""Verified counterexample review stays exact, bounded, and author-controlled."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from core.errors import ValidationError
from infrastructure.llm.schemas import LLMCallRequest, LLMMessage
from infrastructure.stable_hash import stable_hash
from modules.world.llm_schemas import (
    GeneratedWorldDesignFinalReview,
    GeneratedWorldDesignIssueBatch,
    GeneratedWorldDesignVerification,
    GeneratedWorldGenerationDecisionState,
)
from modules.world.schemas import (
    WorldDesignIterationOutput,
    WorldDesignIterationRequest,
    WorldDesignReviewSummary,
)
from modules.world.services.worldbuilding.adoption_package_service import (
    WorldAdoptionPackageService,
)
from modules.world.services.worldbuilding.world_design_iteration import (
    revise_world_design,
    world_design_revision_content_hash,
)
from modules.world.services.worldbuilding.world_generation_center_service import (
    WorldGenerationCenterService,
)
from modules.world.tests.test_world_design_iteration import _parent, _request


def _issue(counterexample: str, *, severity: str = "major") -> dict:
    return {
        "commitment": "维护体系必须可持续",
        "trigger": "连续七日断盐",
        "counterexample": counterexample,
        "expected": "潮门仍有降级运转路径",
        "current": "提案没有交代替代来源",
        "severity": severity,
    }


def test_issue_cards_dedupe_across_isolated_lenses_and_keep_higher_severity():
    repeated = _issue("储备耗尽后港口停摆", severity="minor")
    issues = WorldGenerationCenterService._normalize_world_design_issues(
        (
            (
                "intent_scope",
                GeneratedWorldDesignIssueBatch(issues=[repeated]),
            ),
            (
                "causal_operability",
                GeneratedWorldDesignIssueBatch(
                    issues=[{**repeated, "severity": "blocker"}, _issue("维修者退出")]
                ),
            ),
        )
    )
    assert len(issues) == 2
    assert issues[0]["lenses"] == ["intent_scope", "causal_operability"]
    assert issues[0]["severity"] == "blocker"
    assert issues[0]["issue_id"].startswith("world-design:")


@pytest.mark.parametrize(
    "verdicts",
    [
        [],
        [
            {"issue_id": "unknown", "verdict": "rejected", "reason": "不存在"},
        ],
        [
            {"issue_id": "same", "verdict": "confirmed", "reason": "成立"},
            {"issue_id": "same", "verdict": "rejected", "reason": "重复"},
        ],
    ],
)
def test_verifier_rejects_missing_unknown_and_duplicate_ids(verdicts):
    issues = [{"issue_id": "expected"}]
    verification = GeneratedWorldDesignVerification.model_validate({"verdicts": verdicts})
    with pytest.raises(ValidationError, match="核验回执"):
        WorldGenerationCenterService._validate_world_design_verdicts(issues, verification)


def test_insufficient_evidence_and_tradeoff_stay_open_instead_of_becoming_facts():
    issues = [
        {"issue_id": "i1", "counterexample": "盐矿产量没有来源"},
        {"issue_id": "i2", "counterexample": "效率与自治需要作者取舍"},
    ]
    verdicts = {
        "i1": {"issue_id": "i1", "verdict": "insufficient", "reason": "无证据"},
        "i2": {"issue_id": "i2", "verdict": "tradeoff", "reason": "价值选择"},
    }
    summary = WorldGenerationCenterService._world_design_review_summary(
        GeneratedWorldDesignFinalReview(status="passed", checked_aspects=["资源"]),
        issues=issues,
        verdicts=verdicts,
    )
    assert summary.status == "passed_with_open_questions"
    assert summary.insufficient_evidence == ["盐矿产量没有来源"]
    assert summary.author_decisions == ["效率与自治需要作者取舍"]
    assert set(summary.model_dump()) == {
        "status",
        "checked_aspects",
        "addressed_issues",
        "insufficient_evidence",
        "author_decisions",
    }


@pytest.mark.parametrize(
    "private_text",
    ["world-design:abc123", "intent_scope", "causal_operability", "hidden Prompt"],
)
def test_public_review_summary_rejects_internal_ids_roles_and_prompts(private_text):
    with pytest.raises(ValueError, match="internal review details"):
        WorldDesignReviewSummary(status="passed", checked_aspects=[private_text])


def _task_source(request, *, status: str = "passed") -> SimpleNamespace:
    response = {
        "mode": "design",
        "session_id": str(request.session_id),
        "parent_checkpoint_id": str(request.parent_checkpoint_id),
        "context_confirmation_id": str(request.context_confirmation_id),
        "source_manifest_hash": "a" * 64,
        "summary": request.summary,
        "changes": request.changes.model_dump(mode="json", by_alias=True),
        "task_brief": {
            "current_author_goal": "补足潮门维护闭环",
            "working_assumptions": ["盐由港务机构统一配给"],
            "checkable_commitments": ["说明资源来源与故障后果"],
            "confidence": 0.8,
        },
    }
    receipt = {
        "schema_version": "world_design_verified_review.v1",
        "parent_checkpoint_id": str(request.parent_checkpoint_id),
        "context_confirmation_id": str(request.context_confirmation_id),
        "source_manifest_hash": "a" * 64,
        "input_hash": "c" * 64,
        "final_output_hash": world_design_revision_content_hash(
            summary=request.summary, changes=request.changes, decisions=[]
        ),
        "task_brief": response["task_brief"],
        "issues": [],
        "verdicts": [],
        "final_review": {"status": status},
        "review_summary": {"status": status},
        "knowledge_review": {"status": "passed"},
    }
    receipt["receipt_hash"] = stable_hash(receipt)
    return SimpleNamespace(
        result={
            **response,
            "_cocreation_turn_response": response,
            "_world_design_review_receipt": receipt,
        }
    )


@pytest.mark.asyncio
async def test_save_binding_keeps_exact_review_and_invalidates_author_edits(monkeypatch):
    parent = _parent()
    request = _request(
        parent,
        context_confirmation_id=str(uuid.uuid4()),
        origin_task_id=str(uuid.uuid4()),
    )
    source = _task_source(request)

    async def completed(*_args, **_kwargs):
        return source

    monkeypatch.setattr(
        "infrastructure.tasks.facade.get_completed_task_payload", completed
    )
    decision_state, reference = await WorldAdoptionPackageService._design_review_binding(
        None, request=request, parent=parent
    )
    assert decision_state.current_author_goal == "补足潮门维护闭环"
    assert reference["status"] == "passed"
    assert len(reference["receipt_hash"]) == 64

    edited = request.model_copy(update={"summary": "作者改写后的说明"})
    _, edited_reference = await WorldAdoptionPackageService._design_review_binding(
        None, request=edited, parent=parent
    )
    assert edited_reference["status"] == "author_edited_unreviewed"
    assert "receipt_hash" not in edited_reference


@pytest.mark.asyncio
async def test_blocked_exact_result_cannot_be_saved_as_reviewed(monkeypatch):
    parent = _parent()
    request = _request(
        parent,
        context_confirmation_id=str(uuid.uuid4()),
        origin_task_id=str(uuid.uuid4()),
    )

    async def completed(*_args, **_kwargs):
        return _task_source(request, status="blocked")

    monkeypatch.setattr(
        "infrastructure.tasks.facade.get_completed_task_payload", completed
    )
    with pytest.raises(ValidationError, match="终审未通过"):
        await WorldAdoptionPackageService._design_review_binding(
            None, request=request, parent=parent
        )


class _ReviewClient:
    def __init__(
        self,
        *,
        final_status: str = "passed",
        causal_verdict: str = "confirmed",
        with_issues: bool = True,
    ) -> None:
        self.final_status = final_status
        self.causal_verdict = causal_verdict
        self.with_issues = with_issues
        self.requests = []
        self.repairs = 0

    async def generate_structured(self, request, schema, **_kwargs):
        self.requests.append((schema.__name__, request))
        if schema is GeneratedWorldDesignIssueBatch:
            if not self.with_issues:
                return schema.model_validate({"issues": []})
            system = request.messages[0].content
            if "目标与范围" in system:
                return schema.model_validate(
                    {"issues": [_issue("只是审查者偏好的扩展方向")]}
                )
            return schema.model_validate({"issues": [_issue("储备耗尽后港口停摆")]})
        if schema is GeneratedWorldDesignVerification:
            content = request.messages[-1].content
            cards = content.split("<ISSUE_CARDS>\n", 1)[1].split("\n</ISSUE_CARDS>", 1)[0]
            import json

            issues = json.loads(cards)
            return schema.model_validate(
                {
                    "verdicts": [
                        {
                            "issue_id": item["issue_id"],
                            "verdict": (
                                "rejected"
                                if "偏好" in item["counterexample"]
                                else self.causal_verdict
                            ),
                            "reason": "与冻结输入逐项核对",
                        }
                        for item in issues
                    ]
                }
            )
        if schema is WorldDesignIterationOutput:
            self.repairs += 1
            return schema(summary="补上七日储备与降级运转", changes={})
        if schema is GeneratedWorldDesignFinalReview:
            return schema(
                status=self.final_status,
                checked_aspects=["作者目标", "资源与维护"],
                addressed_issues=(
                    ["储备耗尽后港口停摆"] if self.final_status != "blocked" else []
                ),
                blockers=(
                    ["新变化仍会让维护职责悬空"] if self.final_status == "blocked" else []
                ),
            )
        raise AssertionError(f"unexpected schema: {schema}")


def _review_run_inputs():
    parent = _parent()
    parent_id = uuid.uuid4()
    confirmation_id = uuid.uuid4()
    data = WorldDesignIterationRequest.model_validate(
        {
            "novel_id": parent.world_state.project.id,
            "session_id": str(uuid.uuid4()),
            "expected_checkpoint_id": str(parent_id),
            "context_confirmation_id": str(confirmation_id),
            "target": {"kind": "core_entity", "template": "none"},
            "messages": [{"role": "user", "content": "补足潮门维护闭环"}],
            "quality_mode": "pro",
            "workflow_preset": "world_core",
            "action": "pressure",
            "parent_checkpoint_id": str(parent_id),
        }
    )
    output = WorldDesignIterationOutput(summary="潮门依赖每日盐料", changes={})
    candidate = revise_world_design(
        parent,
        _request(
            parent,
            novel_id=data.novel_id,
            session_id=data.session_id,
            parent_checkpoint_id=data.parent_checkpoint_id,
            expected_checkpoint_id=data.expected_checkpoint_id,
            context_confirmation_id=data.context_confirmation_id,
            summary=output.summary,
        ),
    )
    task_brief = GeneratedWorldGenerationDecisionState(
        current_author_goal="补足潮门维护闭环",
        working_assumptions=["盐料可储存七日"],
        checkable_commitments=["说明资源、维护和故障反馈"],
        confidence=0.9,
    )
    prepared = {
        "conversation_messages": data.messages,
        "session_context": {},
        "allowed_page_types": [],
        "page_catalog": [],
        "assets": {"items": [], "hash_to_key": {}, "by_key": {}},
        "chapters": [],
        "background": {"rendered_context": ""},
        "source_refs": [],
    }
    request = LLMCallRequest(
        model="fake",
        messages=[LLMMessage(role="user", content="生成本轮变化")],
    )
    return parent, data, prepared, candidate, request, output, task_brief


@pytest.mark.asyncio
async def test_confirmed_issue_repairs_once_while_rejected_critique_is_ignored(
    monkeypatch,
):
    client = _ReviewClient()
    service = WorldGenerationCenterService()
    parent, data, prepared, candidate, request, output, task_brief = _review_run_inputs()

    async def pass_knowledge(*_args, **_kwargs):
        return {"status": "passed", "review": {"status": "passed"}}

    async def checkpoint(_progress):
        return None

    monkeypatch.setattr(
        "modules.world.services.worldbuilding.world_generation_center_service.govern_world_output",
        pass_knowledge,
    )
    review_state = {}
    (
        final_output,
        _,
        _,
        summary,
        receipt,
    ) = await service._run_verified_world_design_review(
        client,
        model="fake",
        data=data,
        prepared=prepared,
        parent=parent,
        candidate=candidate,
        request=request,
        output=output,
        task_brief=task_brief,
        knowledge_review={"status": "passed"},
        revise_world_design=revise_world_design,
        review_state=review_state,
        checkpoint_review=checkpoint,
    )
    assert client.repairs == 1
    assert final_output.summary == "补上七日储备与降级运转"
    assert summary.status == "passed"
    assert receipt["receipt_hash"] == stable_hash(
        {key: value for key, value in receipt.items() if key != "receipt_hash"}
    )
    repair_prompt = (
        next(
            request
            for schema, request in client.requests
            if schema == "WorldDesignIterationOutput"
        )
        .messages[-1]
        .content
    )
    assert "储备耗尽后港口停摆" in repair_prompt
    assert "只是审查者偏好的扩展方向" not in repair_prompt
    review_prompts = [
        request.messages[-1].content
        for schema, request in client.requests
        if schema == "GeneratedWorldDesignIssueBatch"
    ]
    assert len(review_prompts) == 2
    assert all("储备耗尽后港口停摆" not in prompt for prompt in review_prompts)

    resumed = _ReviewClient()
    (
        _,
        _,
        _,
        resumed_summary,
        resumed_receipt,
    ) = await service._run_verified_world_design_review(
        resumed,
        model="fake",
        data=data,
        prepared=prepared,
        parent=parent,
        candidate=candidate,
        request=request,
        output=output,
        task_brief=task_brief,
        knowledge_review={"status": "passed"},
        revise_world_design=revise_world_design,
        review_state=review_state,
        checkpoint_review=checkpoint,
    )
    assert resumed.requests == []
    assert resumed_summary == summary
    assert resumed_receipt["receipt_hash"] == receipt["receipt_hash"]


@pytest.mark.asyncio
async def test_terminal_blocker_stops_without_a_second_repair(monkeypatch):
    client = _ReviewClient(final_status="blocked")
    service = WorldGenerationCenterService()
    parent, data, prepared, candidate, request, output, task_brief = _review_run_inputs()

    async def pass_knowledge(*_args, **_kwargs):
        return {"status": "passed", "review": {"status": "passed"}}

    async def checkpoint(_progress):
        return None

    monkeypatch.setattr(
        "modules.world.services.worldbuilding.world_generation_center_service.govern_world_output",
        pass_knowledge,
    )
    _, _, _, summary, _ = await service._run_verified_world_design_review(
        client,
        model="fake",
        data=data,
        prepared=prepared,
        parent=parent,
        candidate=candidate,
        request=request,
        output=output,
        task_brief=task_brief,
        knowledge_review={"status": "passed"},
        revise_world_design=revise_world_design,
        review_state={},
        checkpoint_review=checkpoint,
    )
    assert summary.status == "blocked"
    assert client.repairs == 1
    assert (
        len(
            [
                schema
                for schema, _ in client.requests
                if schema == "WorldDesignIterationOutput"
            ]
        )
        == 1
    )


@pytest.mark.asyncio
async def test_no_issue_passes_without_verification_or_repair():
    client = _ReviewClient(with_issues=False)
    service = WorldGenerationCenterService()
    parent, data, prepared, candidate, request, output, task_brief = (
        _review_run_inputs()
    )

    async def checkpoint(_progress):
        return None

    _, _, _, summary, _ = await service._run_verified_world_design_review(
        client,
        model="fake",
        data=data,
        prepared=prepared,
        parent=parent,
        candidate=candidate,
        request=request,
        output=output,
        task_brief=task_brief,
        knowledge_review={"status": "passed"},
        revise_world_design=revise_world_design,
        review_state={},
        checkpoint_review=checkpoint,
    )
    assert summary.status == "passed"
    assert client.repairs == 0
    assert "GeneratedWorldDesignVerification" not in {
        schema for schema, _ in client.requests
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("verdict", "field"),
    [("insufficient", "insufficient_evidence"), ("tradeoff", "author_decisions")],
)
async def test_unconfirmed_issue_stays_open_and_never_triggers_repair(
    verdict, field
):
    client = _ReviewClient(causal_verdict=verdict)
    service = WorldGenerationCenterService()
    parent, data, prepared, candidate, request, output, task_brief = (
        _review_run_inputs()
    )

    async def checkpoint(_progress):
        return None

    final_output, _, _, summary, _ = (
        await service._run_verified_world_design_review(
            client,
            model="fake",
            data=data,
            prepared=prepared,
            parent=parent,
            candidate=candidate,
            request=request,
            output=output,
            task_brief=task_brief,
            knowledge_review={"status": "passed"},
            revise_world_design=revise_world_design,
            review_state={},
            checkpoint_review=checkpoint,
        )
    )
    assert final_output == output
    assert summary.status == "passed_with_open_questions"
    assert getattr(summary, field) == ["储备耗尽后港口停摆"]
    assert client.repairs == 0
