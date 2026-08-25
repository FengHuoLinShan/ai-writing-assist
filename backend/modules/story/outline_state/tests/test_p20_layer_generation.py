from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest import mock

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.llm.prompt_loader import load_prompt
from modules.story.outline_state.models import (
    ForeshadowingPlan,
    PlotThread,
    RevealPlan,
    Scene,
)
from modules.story.outline_state.p20_context import P20GenerationPlan
from modules.story.outline_state.p20_schemas import (
    OutlineLayerGenerateRequest,
    P20InformationMovement,
    P20PlannedSceneOutput,
    P20PlotThreadOutput,
    P20SemanticAudit,
)
from modules.story.outline_state.p20_service import (
    P20ApplyService,
    P20GenerationService,
    P20SemanticAuditError,
    _information_movement_chronology_violations,
)
from modules.world.models.core import CoreEntity


def _request(novel_id: str, *, target: str, mode: str = "create", **extra):
    return OutlineLayerGenerateRequest.model_validate(
        {
            "novel_id": novel_id,
            "context_confirmation_id": str(uuid.uuid4()),
            "target": target,
            "mode": mode,
            "instruction": "按当前总纲深化这一层。",
            **extra,
        }
    )


async def test_p20_initial_request_contains_exact_output_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modules.story.outline_state import p20_service

    output = P20PlotThreadOutput(result="no_change")

    async def managed_call(_client, _request, schema, **_kwargs):
        if schema is P20SemanticAudit:
            return P20SemanticAudit(verdict="pass")
        return output

    managed = mock.AsyncMock(side_effect=managed_call)
    monkeypatch.setattr(p20_service, "run_managed_structured", managed)
    request = _request(
        "11111111-1111-1111-1111-111111111111",
        target="plot_thread",
    )
    plan = P20GenerationPlan(
        request=request,
        context={"author_instruction": "创建主线"},
        reference_map={},
        context_provenance={},
        source_fingerprint="frozen",
    )

    actual = await P20GenerationService().execute(
        SimpleNamespace(model_name="test-model"),
        plan,
    )

    assert actual is output
    llm_request = managed.await_args_list[0].args[1]
    system_prompt = llm_request.messages[0].content
    assert "<P20_OUTPUT_CONTRACT_JSON_SCHEMA>" in system_prompt
    assert '"reuse_judgments"' in system_prompt
    assert '"information_movements"' in system_prompt
    assert '"additionalProperties":false' in system_prompt
    audit_prompts = [
        call.args[1].messages[0].content for call in managed.await_args_list[1:]
    ]
    assert len(audit_prompts) == 3
    assert all('"verdict"' in prompt for prompt in audit_prompts)


def test_p20_prompts_forbid_author_decision_escape_hatch() -> None:
    plot_prompt = load_prompt("p20_plot_thread")
    scope_prompt = load_prompt("p20_scope_rule_audit")
    author_prompt = load_prompt("p20_author_instruction_audit")

    assert "author_decisions" in plot_prompt
    assert "作者已经禁止" in plot_prompt
    assert "所有文本叶子" in scope_prompt
    assert "author_decisions" in scope_prompt
    assert "不是逃避作者指令的出口" in author_prompt
    assert "未来提案" in author_prompt
    assert "避免提前泄露后续真相" in plot_prompt
    assert "具体地点" in author_prompt
    assert "author_decisions.options" in load_prompt("p20_evidence_audit")


def test_p20_plot_thread_prompt_requires_chronological_information_nodes() -> None:
    plot_prompt = load_prompt("p20_plot_thread")
    evidence_prompt = load_prompt("p20_evidence_audit")

    assert "从早到晚" in plot_prompt
    assert "从早到晚" in evidence_prompt


def test_p20_audit_distinguishes_reveal_from_general_progression() -> None:
    plot_prompt = load_prompt("p20_plot_thread")
    evidence_prompt = load_prompt("p20_evidence_audit")

    assert "不是接收信息的人" in plot_prompt
    assert "虚假的 RevealPlan" in plot_prompt
    assert "新知道了" in evidence_prompt
    assert "降为 `reinforce`" in evidence_prompt


def test_p20_prompts_keep_short_references_out_of_free_text() -> None:
    for prompt_name in (
        "p20_plot_thread",
        "p20_outline_arc",
        "p20_planned_scene",
        "p20_evidence_audit",
    ):
        prompt = load_prompt(prompt_name)
        assert "`*_ref` / `*_refs`" in prompt
        assert "S029" in prompt
        assert "短引用" in prompt


async def test_p20_apply_compiles_before_exclusive_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Independent RAG trace persistence must not wait on our project lock."""

    class _Nested:
        async def __aenter__(self):
            return None

        async def __aexit__(self, *_args):
            return False

    novel_id = "11111111-1111-1111-1111-111111111111"
    request = _request(novel_id, target="plot_thread")
    output = P20PlotThreadOutput(result="no_change")
    confirmed_context = SimpleNamespace()
    events: list[str] = []

    async def prepare(_db, _request, *, confirmed_context=None):
        events.append("prepare_locked" if confirmed_context is not None else "prepare")
        return P20GenerationPlan(
            request=request,
            context={},
            reference_map={
                "threads": {},
                "arcs": {},
                "scenes": {},
                "characters": {},
                "entities": {},
            },
            context_provenance={"story_outline_revision_id": str(uuid.uuid4())},
            source_fingerprint="frozen",
            confirmed_context=confirmed_context or confirmed_context_value,
        )

    confirmed_context_value = confirmed_context
    generation = SimpleNamespace(prepare=mock.AsyncMock(side_effect=prepare))
    service = P20ApplyService(generation=generation)
    monkeypatch.setattr(service, "_apply_threads", mock.AsyncMock(return_value=[]))

    async def exclusive(_db, _novel_id):
        events.append("exclusive")

    async def require_fresh(*_args, **_kwargs):
        events.append("fresh_confirmation")

    monkeypatch.setattr(
        "modules.project.facade.require_active_project_exclusive",
        exclusive,
    )
    monkeypatch.setattr(
        "modules.story.outline_state.p20_service.context_facade.require_fresh_confirmation",
        require_fresh,
    )
    monkeypatch.setattr(
        "modules.story.outline_state.p20_service.context_facade.attach_result_refs",
        mock.AsyncMock(),
    )
    monkeypatch.setattr(
        "infrastructure.tasks.facade.replace_completed_task_result",
        mock.AsyncMock(return_value=True),
    )

    task = SimpleNamespace(
        task_id=str(uuid.uuid4()),
        revision_token="revision",
        result={
            "_request": request.model_dump(mode="json"),
            "_reference_map": {
                "threads": {},
                "arcs": {},
                "scenes": {},
                "characters": {},
                "entities": {},
            },
            "draft_structure": output.model_dump(mode="json"),
            "context_fingerprint": "frozen",
        },
    )
    db = SimpleNamespace(begin_nested=lambda: _Nested())

    result = await service.apply(
        db,
        task=task,
        novel_id=novel_id,
        confirmation_id=request.context_confirmation_id,
        draft_structure=output.model_dump(mode="json"),
    )

    assert result["status"] == "applied"
    assert events == [
        "prepare",
        "exclusive",
        "fresh_confirmation",
        "prepare_locked",
    ]
    assert generation.prepare.await_args_list[-1].kwargs == {
        "confirmed_context": confirmed_context,
    }


async def test_p20_semantic_audit_revises_once_then_rechecks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modules.story.outline_state import p20_service

    first = P20PlotThreadOutput(result="no_change")
    revised = P20PlotThreadOutput(result="needs_author_decision")
    candidate_count = 0

    async def managed_call(_client, _request, schema, **kwargs):
        nonlocal candidate_count
        if schema is P20PlotThreadOutput:
            candidate_count += 1
            return first if candidate_count == 1 else revised
        if candidate_count == 1 and "evidence_canon_audit" in kwargs["step_name"]:
            return P20SemanticAudit(
                verdict="revise",
                violations=["hidden_truth 使用了项目外部正史"],
            )
        return P20SemanticAudit(verdict="pass")

    managed = mock.AsyncMock(side_effect=managed_call)
    monkeypatch.setattr(p20_service, "run_managed_structured", managed)
    plan = P20GenerationPlan(
        request=_request(
            "11111111-1111-1111-1111-111111111111",
            target="plot_thread",
        ),
        context={"structure_coverage": {"materialized_chapter_range": None}},
        reference_map={},
        context_provenance={},
        source_fingerprint="frozen",
    )

    actual = await P20GenerationService().execute(
        SimpleNamespace(model_name="test-model"),
        plan,
    )

    assert actual is revised
    assert candidate_count == 2
    assert managed.await_count == 8
    revision_request = [
        call.args[1]
        for call in managed.await_args_list
        if call.kwargs["step_name"].endswith("semantic_revision")
    ][0]
    assert "hidden_truth 使用了项目外部正史" in revision_request.messages[-1].content


async def test_p20_semantic_audit_allows_second_revision_within_same_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modules.story.outline_state import p20_service

    first = P20PlotThreadOutput(result="no_change")
    revised_once = P20PlotThreadOutput(result="needs_author_decision")
    revised_twice = P20PlotThreadOutput(result="proposed")
    candidates = [first, revised_once, revised_twice]
    candidate_count = 0
    progress: list[float] = []

    async def managed_call(_client, _request, schema, **kwargs):
        nonlocal candidate_count
        if schema is P20PlotThreadOutput:
            candidate = candidates[candidate_count]
            candidate_count += 1
            return candidate
        if candidate_count < 3 and "evidence_canon_audit" in kwargs["step_name"]:
            return P20SemanticAudit(
                verdict="revise",
                violations=[
                    "信息推进节点引用了错误 Scene；改用审计指出的正确短引用，"
                    "无法确认时清空引用并标记不确定"
                ],
            )
        return P20SemanticAudit(verdict="pass")

    managed = mock.AsyncMock(side_effect=managed_call)
    monkeypatch.setattr(p20_service, "run_managed_structured", managed)
    plan = P20GenerationPlan(
        request=_request(
            "11111111-1111-1111-1111-111111111111",
            target="plot_thread",
        ),
        context={"structure_coverage": {"materialized_chapter_range": [1, 60]}},
        reference_map={},
        context_provenance={},
        source_fingerprint="frozen",
    )

    actual = await P20GenerationService().execute(
        SimpleNamespace(model_name="test-model"),
        plan,
        progress_callback=progress.append,
    )

    assert actual is revised_twice
    assert candidate_count == 3
    assert progress == [0.4, 0.55, 0.65, 0.72, 0.78, 0.82]
    assert managed.await_count == 12
    second_revision = [
        call.args[1]
        for call in managed.await_args_list
        if call.kwargs["step_name"].endswith("semantic_revision_2")
    ][0]
    assert "正确的短引用" in second_revision.messages[-1].content
    assert "清空该引用" in second_revision.messages[-1].content


async def test_p20_deterministic_guard_revises_embedded_scene_citation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modules.story.outline_state import p20_service

    first = P20PlannedSceneOutput.model_validate(
        {
            "result": "proposed",
            "scenes": [
                {
                    "proposal_ref": "P1",
                    "title": "下一步",
                    "core_conflict": None,
                    "core_conflict_status": "not_applicable",
                    "basis": "服药与扮演已经由 S029-S030 证明。",
                    "confidence": 0.8,
                }
            ],
        }
    )
    revised = P20PlannedSceneOutput.model_validate(
        {
            "result": "proposed",
            "scenes": [
                {
                    "proposal_ref": "P1",
                    "title": "下一步",
                    "core_conflict": None,
                    "core_conflict_status": "not_applicable",
                    "basis": "已确认的服药与扮演进展支持这一计划。",
                    "confidence": 0.8,
                }
            ],
        }
    )
    candidate_count = 0

    async def managed_call(_client, _request, schema, **_kwargs):
        nonlocal candidate_count
        if schema is P20PlannedSceneOutput:
            candidate_count += 1
            return first if candidate_count == 1 else revised
        return P20SemanticAudit(verdict="pass")

    managed = mock.AsyncMock(side_effect=managed_call)
    monkeypatch.setattr(p20_service, "run_managed_structured", managed)
    plan = P20GenerationPlan(
        request=_request(
            "11111111-1111-1111-1111-111111111111",
            target="planned_scene",
        ),
        context={"structure_coverage": {"materialized_chapter_range": [1, 60]}},
        reference_map={"scenes": {"S029": str(uuid.uuid4())}},
        context_provenance={},
        source_fingerprint="frozen",
    )

    actual = await P20GenerationService().execute(
        SimpleNamespace(model_name="test-model"),
        plan,
    )

    assert actual is revised
    assert candidate_count == 2
    revision_request = [
        call.args[1]
        for call in managed.await_args_list
        if call.kwargs["step_name"].endswith("semantic_revision")
    ][0]
    assert "reference_integrity" in revision_request.messages[-1].content
    assert "S029, S030" in revision_request.messages[-1].content


def test_p20_apply_rejects_short_reference_embedded_in_basis() -> None:
    request = _request(str(uuid.uuid4()), target="planned_scene")
    output = P20PlannedSceneOutput.model_validate(
        {
            "result": "proposed",
            "scenes": [
                {
                    "proposal_ref": "P1",
                    "title": "下一步",
                    "core_conflict": None,
                    "core_conflict_status": "not_applicable",
                    "basis": "错误地把 S029 当成可核验引文。",
                    "confidence": 0.8,
                }
            ],
        }
    )

    with pytest.raises(ValueError, match="自由文本中嵌入短引用 S029"):
        P20ApplyService._validate_references(
            request,
            output,
            {
                "threads": {},
                "arcs": {},
                "scenes": {"S029": str(uuid.uuid4())},
                "characters": {},
                "entities": {},
            },
        )


async def test_p20_final_audit_failure_exposes_bounded_actionable_violations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modules.story.outline_state import p20_service

    output = P20PlotThreadOutput(result="no_change")

    async def managed_call(_client, _request, schema, **_kwargs):
        if schema is P20SemanticAudit:
            return P20SemanticAudit(
                verdict="revise",
                violations=["已物化章节中的节点没有项目证据"],
            )
        return output

    managed = mock.AsyncMock(side_effect=managed_call)
    monkeypatch.setattr(p20_service, "run_managed_structured", managed)
    plan = P20GenerationPlan(
        request=_request(
            "11111111-1111-1111-1111-111111111111",
            target="plot_thread",
        ),
        context={"structure_coverage": {"materialized_chapter_range": None}},
        reference_map={},
        context_provenance={},
        source_fingerprint="frozen",
    )

    with pytest.raises(P20SemanticAuditError, match="已物化章节中的节点没有项目证据"):
        await P20GenerationService().execute(
            SimpleNamespace(model_name="test-model"),
            plan,
        )

    step_names = [call.kwargs["step_name"] for call in managed.await_args_list]
    assert any(name.endswith("semantic_revision_2") for name in step_names)
    assert any(name.endswith("evidence_canon_audit.final") for name in step_names)
    assert any(name.endswith("scope_rule_audit.final") for name in step_names)
    assert any(name.endswith("author_instruction_audit.final") for name in step_names)


def test_revise_requires_explicit_current_layer_selection() -> None:
    with pytest.raises(ValidationError, match="explicit current-layer selection"):
        _request(str(uuid.uuid4()), target="outline_arc", mode="revise")


def test_planned_scene_accepts_real_not_applicable_conflict() -> None:
    output = P20PlannedSceneOutput.model_validate(
        {
            "result": "proposed",
            "scenes": [
                {
                    "proposal_ref": "P1",
                    "title": "无声交接",
                    "core_conflict": None,
                    "core_conflict_status": "not_applicable",
                    "basis": "这一单元的作用是完成信息交接，并不存在真实对抗。",
                    "uncertain_fields": [],
                    "confidence": 0.9,
                }
            ],
        }
    )

    assert output.scenes[0].semantic_field_statuses()["core_conflict"] == (
        "not_applicable"
    )


def test_information_movement_routes_chronology_to_semantic_revision() -> None:
    output = P20PlotThreadOutput.model_validate(
        {
            "result": "proposed",
            "threads": [
                {
                    "proposal_ref": "P1",
                    "name": "主线",
                    "thread_type": "main",
                    "information_movements": [
                        {
                            "movement_ref": "IM-ORDER",
                            "information_subject": "信息推进",
                            "nodes": [
                                {
                                    "kind": "seed",
                                    "content": "较晚节点",
                                    "chapter_hint": 58,
                                },
                                {
                                    "kind": "reinforce",
                                    "content": "较早节点",
                                    "chapter_hint": 35,
                                },
                            ],
                            "basis": "已物化章节必须按发生顺序排列。",
                            "confidence": 0.8,
                        }
                    ],
                    "basis": "沿既有方向推进。",
                    "confidence": 0.8,
                }
            ],
        }
    )

    assert _information_movement_chronology_violations(output) == [
        "threads[0].information_movements[0].nodes 的已知章号顺序为 [58, 35]，"
        "不是从早到晚；请保持节点内容不变并按叙事发生顺序重排。若章号证据不足，"
        "清空不可靠的 chapter_hint 并把 nodes 标记为不确定"
    ]


async def test_p20_chronology_guard_uses_semantic_revision_not_format_repair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modules.story.outline_state import p20_service

    def output_with_chapters(chapters: list[int]) -> P20PlotThreadOutput:
        return P20PlotThreadOutput.model_validate(
            {
                "result": "proposed",
                "threads": [
                    {
                        "proposal_ref": "P1",
                        "name": "主线",
                        "thread_type": "main",
                        "information_movements": [
                            {
                                "movement_ref": "IM-ORDER",
                                "information_subject": "信息推进",
                                "nodes": [
                                    {
                                        "kind": "seed",
                                        "content": "第一节点",
                                        "chapter_hint": chapters[0],
                                    },
                                    {
                                        "kind": "reinforce",
                                        "content": "第二节点",
                                        "chapter_hint": chapters[1],
                                    },
                                ],
                                "basis": "按正文发生顺序组织。",
                                "confidence": 0.8,
                            }
                        ],
                        "basis": "沿既有方向推进。",
                        "confidence": 0.8,
                    }
                ],
            }
        )

    candidates = iter((output_with_chapters([58, 35]), output_with_chapters([35, 58])))

    async def managed_call(_client, _request, schema, **_kwargs):
        if schema is P20PlotThreadOutput:
            return next(candidates)
        return P20SemanticAudit(verdict="pass")

    managed = mock.AsyncMock(side_effect=managed_call)
    monkeypatch.setattr(p20_service, "run_managed_structured", managed)
    plan = P20GenerationPlan(
        request=_request(
            "11111111-1111-1111-1111-111111111111",
            target="plot_thread",
        ),
        context={"structure_coverage": {"materialized_chapter_range": [1, 60]}},
        reference_map={},
        context_provenance={},
        source_fingerprint="frozen",
    )

    actual = await P20GenerationService().execute(
        SimpleNamespace(model_name="test-model"),
        plan,
    )

    movement = actual.threads[0].information_movements[0]
    assert [node.chapter_hint for node in movement.nodes] == [35, 58]
    revision_calls = [
        call
        for call in managed.await_args_list
        if call.kwargs["step_name"].endswith("semantic_revision")
    ]
    assert len(revision_calls) == 1
    revision_prompt = revision_calls[0].args[1].messages[-1].content
    assert "[information_chronology]" in revision_prompt
    assert "[58, 35]" in revision_prompt


def test_information_movement_allows_unknown_chapters_between_ordered_nodes() -> None:
    movement = P20InformationMovement.model_validate(
        {
            "movement_ref": "IM-ORDER",
            "information_subject": "信息推进",
            "nodes": [
                {"kind": "seed", "content": "已知起点", "chapter_hint": 5},
                {"kind": "reinforce", "content": "时间未定的未来提案"},
                {"kind": "payoff", "content": "已知后续", "chapter_hint": 35},
            ],
            "basis": "仅约束已知章号的相对顺序。",
            "confidence": 0.8,
        }
    )

    assert [node.chapter_hint for node in movement.nodes] == [5, None, 35]


@pytest.mark.parametrize(
    "patch",
    [
        {"core_conflict": None, "core_conflict_status": "present"},
        {"core_conflict": "虚构冲突", "core_conflict_status": "not_applicable"},
        {"core_conflict": None, "core_conflict_status": "uncertain"},
    ],
)
def test_planned_scene_rejects_conflict_status_contradictions(patch: dict) -> None:
    item = {
        "proposal_ref": "P1",
        "title": "矛盾契约",
        "basis": "测试",
        "uncertain_fields": [],
        "confidence": 0.5,
        **patch,
    }
    with pytest.raises(ValidationError):
        P20PlannedSceneOutput.model_validate({"result": "proposed", "scenes": [item]})


@pytest.mark.parametrize("uncertain_fields", [[], ["target_ref"]])
def test_unresolved_reveal_target_is_normalized_as_uncertain(
    uncertain_fields: list[str],
) -> None:
    movement = P20InformationMovement.model_validate(
        {
            "movement_ref": "M1",
            "information_subject": "潮门的用途",
            "hidden_content": "潮门在筛选继承者。",
            "nodes": [
                {
                    "kind": "partial_reveal",
                    "content": "主角发现潮门会记录来访者。",
                }
            ],
            "basis": "现有资料不能把秘密可靠绑定到一个对象。",
            "uncertain_fields": uncertain_fields,
            "confidence": 0.6,
        }
    )
    assert movement.target_ref is None
    assert movement.uncertain_fields == ["target_ref"]


def test_information_movement_allows_unknown_hidden_content_without_invention() -> None:
    movement = P20InformationMovement.model_validate(
        {
            "movement_ref": "M2",
            "information_subject": "灰门为何回应主角",
            "surface_understanding": "灰门会在仪式后出现。",
            "hidden_content": None,
            "nodes": [],
            "basis": "项目只提供了现象，没有提供答案。",
            "uncertain_fields": [],
            "confidence": 0.4,
        }
    )

    assert movement.hidden_content is None
    assert movement.uncertain_fields == ["hidden_content"]


@pytest.mark.asyncio
async def test_planned_scene_materializes_without_prose_mapping(
    db_session: AsyncSession,
    sample_novel_id: str,
) -> None:
    request = _request(sample_novel_id, target="planned_scene")
    output = P20PlannedSceneOutput.model_validate(
        {
            "result": "proposed",
            "scenes": [
                {
                    "proposal_ref": "P1",
                    "title": "跨章共同签署",
                    "planned_start_chapter": 8,
                    "planned_end_chapter": 9,
                    "goal": "完成共同签署。",
                    "core_conflict": None,
                    "core_conflict_status": "not_applicable",
                    "narrative_tag": "transition",
                    "basis": "这是一个可独立规划和续写的因果单元。",
                    "uncertain_fields": [],
                    "confidence": 0.88,
                }
            ],
        }
    )

    refs = await P20ApplyService()._apply_scenes(
        db_session,
        request=request,
        output=output,
        reference_map={"arcs": {}, "threads": {}, "characters": {}, "entities": {}},
        task_id=str(uuid.uuid4()),
        context_fingerprint="fingerprint",
        story_outline_revision_id=str(uuid.uuid4()),
        adopted_at="2026-07-17T00:00:00+00:00",
    )

    scene = await db_session.scalar(
        select(Scene).where(Scene.id == uuid.UUID(refs[0]["id"]))
    )
    assert scene is not None
    assert scene.scene_chunks == []
    assert scene.chapter_ids == []
    assert scene.structure_meta["planning_state"] == "planned"
    assert scene.structure_meta["semantic_origin"] == "p20_planned_scene"
    assert scene.structure_meta["planned_chapter_range"] == {"start": 8, "end": 9}
    assert scene.structure_meta["core_conflict_status"] == "not_applicable"


@pytest.mark.asyncio
async def test_revising_materialized_scene_preserves_mapping_and_history(
    db_session: AsyncSession,
    sample_novel_id: str,
) -> None:
    scene = Scene(
        novel_id=uuid.UUID(sample_novel_id),
        scene_index=0,
        title="旧标题",
        scene_chunks=[{"chapter_index": 4, "start_pos": 10, "end_pos": 20}],
        chapter_ids=[4],
        source="deep_import",
        status="canonical",
        structure_meta={"planning_state": "materialized"},
    )
    db_session.add(scene)
    await db_session.flush()
    request = _request(
        sample_novel_id,
        target="planned_scene",
        mode="revise",
        selected_scene_ids=[str(scene.id)],
    )
    output = P20PlannedSceneOutput.model_validate(
        {
            "result": "proposed",
            "scenes": [
                {
                    "proposal_ref": "P1",
                    "target_scene_ref": "S1",
                    "title": "新标题",
                    "core_conflict": "必须选择是否公开真相。",
                    "core_conflict_status": "present",
                    "basis": "修订语义但不改变正文定位。",
                    "uncertain_fields": [],
                    "confidence": 0.91,
                }
            ],
        }
    )

    await P20ApplyService()._apply_scenes(
        db_session,
        request=request,
        output=output,
        reference_map={
            "scenes": {"S1": str(scene.id)},
            "arcs": {},
            "threads": {},
            "characters": {},
            "entities": {},
        },
        task_id=str(uuid.uuid4()),
        context_fingerprint="fingerprint",
        story_outline_revision_id=str(uuid.uuid4()),
        adopted_at="2026-07-17T00:00:00+00:00",
    )

    assert scene.title == "新标题"
    assert scene.source == "deep_import"
    assert scene.scene_chunks == [{"chapter_index": 4, "start_pos": 10, "end_pos": 20}]
    assert scene.chapter_ids == [4]
    assert scene.structure_meta["planning_state"] == "materialized"
    history = scene.structure_meta["ai_revision_history"]
    assert history[-1]["before"]["title"] == "旧标题"
    assert history[-1]["before"]["scene_chunks"] == scene.scene_chunks


@pytest.mark.asyncio
async def test_information_movement_projects_linked_foreshadow_and_reveal(
    db_session: AsyncSession,
    sample_novel_id: str,
) -> None:
    entity = CoreEntity(
        novel_id=uuid.UUID(sample_novel_id),
        entity_type="artifact",
        name="潮门",
        status="canonical",
        importance=0.8,
        importance_level="important",
        reveal_level="author_only",
    )
    db_session.add(entity)
    await db_session.flush()
    request = _request(sample_novel_id, target="plot_thread")
    output = P20PlotThreadOutput.model_validate(
        {
            "result": "proposed",
            "threads": [
                {
                    "proposal_ref": "P1",
                    "name": "群岛联盟",
                    "thread_type": "main",
                    "information_movements": [
                        {
                            "movement_ref": "M1",
                            "information_subject": "潮门的判断机制",
                            "surface_understanding": "潮门只是机关。",
                            "hidden_content": "潮门在评估共同决策。",
                            "target_ref": "E1",
                            "nodes": [
                                {
                                    "kind": "seed",
                                    "content": "签署后门纹发光",
                                    "chapter_hint": 8,
                                },
                                {
                                    "kind": "partial_reveal",
                                    "content": "纹路记录每次表决",
                                    "chapter_hint": 20,
                                },
                                {
                                    "kind": "full_reveal",
                                    "content": "最终兑现位置留待作者决定。",
                                },
                            ],
                            "basis": "总纲要求资源与真相同步推进。",
                            "uncertain_fields": [],
                            "confidence": 0.9,
                        }
                    ],
                    "basis": "已有总纲方向需要物化为长期剧情线。",
                    "uncertain_fields": [],
                    "confidence": 0.9,
                }
            ],
        }
    )

    refs = await P20ApplyService()._apply_threads(
        db_session,
        request=request,
        output=output,
        reference_map={
            "characters": {},
            "entities": {"E1": str(entity.id)},
            "scenes": {},
        },
        task_id=str(uuid.uuid4()),
        context_fingerprint="fingerprint",
        story_outline_revision_id=str(uuid.uuid4()),
        adopted_at="2026-07-17T00:00:00+00:00",
    )

    novel_uuid = uuid.UUID(sample_novel_id)
    thread = await db_session.scalar(
        select(PlotThread).where(PlotThread.id == uuid.UUID(refs[0]["id"]))
    )
    foreshadow = await db_session.scalar(
        select(ForeshadowingPlan).where(ForeshadowingPlan.novel_id == novel_uuid)
    )
    reveal = await db_session.scalar(
        select(RevealPlan).where(RevealPlan.novel_id == novel_uuid)
    )
    assert thread is not None and foreshadow is not None and reveal is not None
    movement_id = foreshadow.provenance_meta["information_movement_id"]
    assert reveal.provenance_meta["information_movement_id"] == movement_id
    assert foreshadow.related_thread_ids == [str(thread.id)]
    assert reveal.related_thread_ids == [str(thread.id)]
    assert reveal.target_id == entity.id
    assert len(reveal.reveal_stages) == 1
    assert reveal.provenance_meta["needs_review"] is True
    assert reveal.provenance_meta["projection_warning"] == (
        "reveal_node_missing_chapter_hint"
    )


@pytest.mark.asyncio
async def test_unresolved_reveal_target_keeps_movement_without_fake_projection(
    db_session: AsyncSession,
    sample_novel_id: str,
) -> None:
    request = _request(sample_novel_id, target="plot_thread")
    output = P20PlotThreadOutput.model_validate(
        {
            "result": "proposed",
            "threads": [
                {
                    "proposal_ref": "P1",
                    "name": "灰雾认知",
                    "thread_type": "main",
                    "information_movements": [
                        {
                            "movement_ref": "M1",
                            "information_subject": "灰雾的真实作用",
                            "hidden_content": "现阶段没有可可靠绑定的揭示对象。",
                            "nodes": [
                                {
                                    "kind": "partial_reveal",
                                    "content": "主角获得一条仍需验证的线索。",
                                }
                            ],
                            "basis": "保留信息推进，但不伪造对象引用。",
                            "uncertain_fields": ["target_ref"],
                            "confidence": 0.55,
                        }
                    ],
                    "basis": "总纲需要长期认知推进。",
                    "uncertain_fields": [],
                    "confidence": 0.8,
                }
            ],
        }
    )

    refs = await P20ApplyService()._apply_threads(
        db_session,
        request=request,
        output=output,
        reference_map={"characters": {}, "entities": {}, "scenes": {}},
        task_id=str(uuid.uuid4()),
        context_fingerprint="fingerprint",
        story_outline_revision_id=str(uuid.uuid4()),
        adopted_at="2026-07-17T00:00:00+00:00",
    )

    assert [item["type"] for item in refs] == ["plot_thread"]
    thread = await db_session.get(PlotThread, uuid.UUID(refs[0]["id"]))
    reveal = await db_session.scalar(
        select(RevealPlan).where(RevealPlan.novel_id == uuid.UUID(sample_novel_id))
    )
    assert thread is not None
    assert reveal is None
    assert thread.provenance_meta["needs_review"] is True
    assert thread.provenance_meta["information_movements"][0]["target_ref"] is None


@pytest.mark.asyncio
async def test_revising_thread_retires_projections_for_removed_movements(
    db_session: AsyncSession,
    sample_novel_id: str,
) -> None:
    create_request = _request(sample_novel_id, target="plot_thread")
    create_output = P20PlotThreadOutput.model_validate(
        {
            "result": "proposed",
            "threads": [
                {
                    "proposal_ref": "P1",
                    "name": "潮门真相",
                    "thread_type": "main",
                    "information_movements": [
                        {
                            "movement_ref": "M1",
                            "information_subject": "潮门秘密",
                            "surface_understanding": "潮门只是机关。",
                            "nodes": [
                                {
                                    "kind": "seed",
                                    "content": "门纹第一次发光。",
                                    "chapter_hint": 8,
                                }
                            ],
                            "basis": "总纲要求铺设潮门线索。",
                            "uncertain_fields": [],
                            "confidence": 0.9,
                        }
                    ],
                    "basis": "创建长期剧情线。",
                    "uncertain_fields": [],
                    "confidence": 0.9,
                }
            ],
        }
    )
    service = P20ApplyService()
    refs = await service._apply_threads(
        db_session,
        request=create_request,
        output=create_output,
        reference_map={"characters": {}, "entities": {}, "scenes": {}},
        task_id=str(uuid.uuid4()),
        context_fingerprint="create-fingerprint",
        story_outline_revision_id=str(uuid.uuid4()),
        adopted_at="2026-07-17T00:00:00+00:00",
    )
    thread_id = refs[0]["id"]
    plan = await db_session.scalar(
        select(ForeshadowingPlan).where(
            ForeshadowingPlan.novel_id == uuid.UUID(sample_novel_id)
        )
    )
    assert plan is not None
    plan_id = plan.id

    revise_request = _request(
        sample_novel_id,
        target="plot_thread",
        mode="revise",
        selected_thread_ids=[thread_id],
    )
    revise_output = P20PlotThreadOutput.model_validate(
        {
            "result": "proposed",
            "threads": [
                {
                    "proposal_ref": "P2",
                    "target_thread_ref": "T1",
                    "name": "潮门真相",
                    "thread_type": "main",
                    "information_movements": [],
                    "basis": "作者决定删除尚未成立的信息推进。",
                    "uncertain_fields": [],
                    "confidence": 0.95,
                }
            ],
        }
    )
    await service._apply_threads(
        db_session,
        request=revise_request,
        output=revise_output,
        reference_map={
            "threads": {"T1": thread_id},
            "characters": {},
            "entities": {},
            "scenes": {},
        },
        task_id="revision-task",
        context_fingerprint="revise-fingerprint",
        story_outline_revision_id=str(uuid.uuid4()),
        adopted_at="2026-07-17T01:00:00+00:00",
    )

    retired = await db_session.get(ForeshadowingPlan, plan_id)
    assert retired is not None
    assert retired.status == "deprecated"
    assert retired.related_thread_ids == []
    assert retired.provenance_meta["projection_retired"] == {
        "task_id": "revision-task",
        "adopted_at": "2026-07-17T01:00:00+00:00",
        "reason": "information_movement_removed_or_projection_no_longer_valid",
        "previous_status": "draft",
    }
