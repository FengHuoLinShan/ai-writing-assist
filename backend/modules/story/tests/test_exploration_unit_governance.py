"""Real Evidence workflow with scripted replies: unit contracts, not prose quality."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from core.errors import ConflictError
from infrastructure.llm.schemas import LLMCallRequest, LLMMessage
from modules.evidence.compilation.knowledge.llm_schemas import (
    AuditDimensionCheck,
    AuditFindingOutput,
    AuditVerdictOutput,
    DirectorShardDisposition,
    DirectorShardPlan,
)
from modules.evidence.contracts import ProvisionalStart
from modules.story import exploration_governance, exploration_tasks
from modules.story.exploration_schemas import (
    EventOutputV1,
    FullRehearsalPerformance,
    SceneLineOutputV1,
)

CANONICAL = "00000000-0000-0000-0000-000000000001"
PRIVATE = "AUTHOR_ONLY_SECRET"


class ScriptedClient:
    """Script verdicts to advance the real workflow; assertions inspect requests only."""

    def __init__(self, output, findings=()):
        self.output = output
        self.findings = list(findings)
        self.calls = []
        self.audit_count = 0

    async def generate_structured(self, request, schema, **kwargs):
        self.calls.append((schema, request.model_copy(deep=True)))
        if schema is DirectorShardPlan:
            return DirectorShardPlan(
                dispositions=[
                    DirectorShardDisposition(
                        source_key=line[2:].split("|")[0].strip(),
                        disposition="required_for_generation",
                    )
                    for message in request.messages
                    for line in message.content.splitlines()
                    if line.startswith("- packet:") and "|" in line
                ]
            )
        if schema is AuditVerdictOutput:
            self.audit_count += 1
            findings = self.findings if self.audit_count == 1 else []
            return AuditVerdictOutput(
                verdict="blocked" if findings else "pass",
                findings=findings,
                dimensions=[
                    AuditDimensionCheck(dimension=dimension)
                    for dimension in (
                        "character_knowledge",
                        "world_entities",
                        "scene_state",
                    )
                ],
            )
        assert schema is type(self.output)
        return self.output.model_copy(deep=True)


@pytest.fixture
def unit_context(monkeypatch):
    confirmed = SimpleNamespace(rendered_markdown="CONFIRMED_AUTHOR_MATERIAL")

    async def projected(_db, *, confirmed_context, character_id):
        assert confirmed_context is confirmed
        assert character_id == CANONICAL
        return SimpleNamespace(rendered_markdown="CANONICAL_VISIBLE_PROJECTION")

    async def hidden(_db, *, confirmed_context, viewpoint_character_id):
        assert confirmed_context is confirmed
        assert viewpoint_character_id == CANONICAL
        return [SimpleNamespace(phrase="CANONICAL_HIDDEN_SECRET")]

    monkeypatch.setattr(
        exploration_governance, "project_confirmed_character_context", projected
    )
    monkeypatch.setattr(exploration_governance, "build_hidden_guard_context", hidden)
    return confirmed


def _start():
    return ProvisionalStart(
        kind="provisional",
        question="WHOLE_AUTHOR_TASK_FOR_BOTH_CHARACTERS",
        assumptions=[{"kind": "state", "text": "AUTHOR_ASSUMPTION"}],
        candidates=[
            {"ref_id": ref, "label": ref, "role": "character"}
            for ref in ("c_one", "c_other")
        ],
        knowledge=[
            {"subject_ref": "c_one", "knows": ["OWN_KNOWN"], "observed": ["OWN_SEEN"]},
            {"subject_ref": "c_other", "knows": ["OTHER_CHARACTER_ONLY"]},
        ],
        canonical_refs=[CANONICAL],
        scene_stimuli=[
            {"subject_entity_id": CANONICAL, "stimulus": "CANONICAL_LOCAL_STIMULUS"}
        ],
        author_private=[PRIVATE],
        time_basis="assumed_now",
    )


def _line(target="c_one"):
    return SceneLineOutputV1(
        target_ref=target,
        line="LOCAL_CANDIDATE_LINE",
        rationale="LOCAL_CANDIDATE_BASIS",
    )


async def _run(start, confirmed, data, system, output, *, findings=(), audit_output=None):
    raw = ScriptedClient(output, findings)

    async def revalidate():
        return confirmed

    client = exploration_governance.ExplorationClient(
        raw,
        db=None,
        novel_id="synthetic-novel",
        confirmation_id="synthetic-confirmation",
        action=(
            exploration_tasks.EVENT_BRIDGE_ACTION
            if isinstance(output, EventOutputV1)
            else exploration_tasks.SCENE_LINE_ACTION
        ),
        start=start.model_dump(mode="json"),
        revalidate=revalidate,
    )
    client.audit_output = audit_output
    await client.generate_structured(
        LLMCallRequest(
            messages=[
                LLMMessage(role="system", content=system),
                LLMMessage(role="user", content=json.dumps(data, ensure_ascii=False)),
            ]
        ),
        type(output),
    )
    return raw.calls


def _section(request, heading):
    prompt = next(m.content for m in request.messages if m.role == "user")
    return prompt.split(f"【{heading}】\n", 1)[1].split("\n\n【", 1)[0]


@pytest.mark.parametrize(
    "kind", ["single", "multi_child", "spatial", "full_card", "goal", "bridge"]
)
async def test_audit_receives_current_unit_system_schema_and_visible_requirements(
    unit_context, kind
):
    start = _start()
    if kind in {"single", "multi_child"}:
        target = "c_one" if kind == "single" else "c_other"
        data = exploration_tasks._scene_line_user_data(
            start=start,
            focus="CURRENT_FOCUS",
            target_ref=target,
            confirmed=unit_context,
            mode="start",
            parent_payload=None,
            instruction="",
        )
        system = exploration_tasks._SYSTEM_PROMPTS[exploration_tasks.SCENE_LINE_ACTION]
        output = _line(target)
    elif kind == "spatial":
        data = exploration_tasks._scene_diagnostic_user_data(
            start=start,
            focus="CURRENT_FOCUS",
            confirmed=unit_context,
            question="CURRENT_SPATIAL_QUESTION",
            subject_ref=None,
            material=[],
        )
        system = exploration_tasks.SCENE_SPATIAL_DIAGNOSTIC_PROMPT
        output = SceneLineOutputV1(
            rationale="MISSING_SPATIAL_EVIDENCE",
            spatial_assessment={"supported": None, "unknowns": ["MISSING_DIMENSIONS"]},
        )
    elif kind == "full_card":
        data = exploration_tasks._rehearsal_performance_packet(
            start=start,
            focus="CURRENT_FOCUS",
            target_ref="c_one",
            confirmed=unit_context,
            round_number=1,
            previous_round=None,
        )
        system = exploration_tasks.FULL_REHEARSAL_CARD_PROMPT
        output = FullRehearsalPerformance(
            target_ref="c_one", line_or_beat="LOCAL_BEAT", rationale="OWN_SEEN"
        )
    else:
        data = exploration_tasks._sandbox_event_user_data(
            start=start,
            focus="CURRENT_FOCUS",
            confirmed=unit_context,
            mode="start",
            parent_payload=None,
            instruction="",
            bridge_target=None,
            single_item=False,
        )
        missing = {"reason": "NO_SUPPORTED_PATH", "missing": ["MISSING_CONTACT"]}
        if kind == "goal":
            system = exploration_tasks.EVENT_GOAL_PROMPT
            output = EventOutputV1(
                mode="goal",
                original_excerpt="SYNTHETIC_GOAL",
                goal_path={"goal": "GOAL", "steps": [], "unsolvable": missing},
            )
        else:
            system = exploration_tasks._SYSTEM_PROMPTS[
                exploration_tasks.EVENT_BRIDGE_ACTION
            ]
            output = EventOutputV1(
                mode="bridge", original_excerpt="SYNTHETIC_GAP", unsolvable=missing
            )
    calls = await _run(start, unit_context, data, system, output)
    generation = next(request for schema, request in calls if schema is type(output))
    audit = next(request for schema, request in calls if schema is AuditVerdictOutput)
    instruction = _section(audit, "任务指令")
    contract = json.loads(instruction.split("本单元合同：", 1)[1])
    assert contract["generation_instructions"] == [system]
    assert contract["output_schema"] == type(output).model_json_schema()
    visible = json.loads(next(m.content for m in generation.messages if m.role == "user"))
    requirements = json.loads(_section(audit, "作者要求（冻结投影）"))
    assert requirements == visible
    assert requirements != start.model_dump(mode="json")
    authority = json.loads(_section(audit, "权威资料（可能含隐藏真相，仅供审查）"))
    assert authority["author_task_background"] == start.model_dump(mode="json")
    assert PRIVATE in json.dumps(authority)
    if kind in {"single", "multi_child", "full_card"}:
        assert "WHOLE_AUTHOR_TASK_FOR_BOTH_CHARACTERS" not in json.dumps(requirements)
        assert "author_context" not in requirements
        assert PRIVATE not in json.dumps(requirements)
        assert requirements["target"]["ref"] == output.target_ref
        other = "c_one" if output.target_ref == "c_other" else "c_other"
        assert other not in json.dumps(requirements)
    if kind == "spatial":
        assert output.line == ""
        assert "不得生成对白" in contract["generation_instructions"][0]
    if kind == "full_card":
        assert "只输出这一张表演卡" in contract["generation_instructions"][0]


@pytest.mark.parametrize("target", ["c_one", CANONICAL])
async def test_character_audit_uses_actual_observations_and_local_stimuli(
    unit_context, target
):
    start = _start()
    data = exploration_tasks._rehearsal_performance_packet(
        start=start,
        focus="CURRENT_FOCUS",
        target_ref=target,
        confirmed=unit_context,
        round_number=2,
        previous_round=None,
    )
    data["accumulated_observations"] = ["OWN_PREVIOUSLY_OBSERVED"]
    output = FullRehearsalPerformance(
        target_ref=target, line_or_beat="LOCAL_BEAT", rationale="OWN_PREVIOUSLY_OBSERVED"
    )
    calls = await _run(
        start, unit_context, data, exploration_tasks.FULL_REHEARSAL_CARD_PROMPT, output
    )
    audit = next(request for schema, request in calls if schema is AuditVerdictOutput)
    context = json.loads(_section(audit, "生成者可见资料"))
    actual = context["per_character_knowledge"][target]
    assert actual["accumulated_observations"] == ["OWN_PREVIOUSLY_OBSERVED"]
    assert PRIVATE not in json.dumps(actual)
    assert "OTHER_CHARACTER_ONLY" not in json.dumps(actual)
    if target == CANONICAL:
        assert actual["confirmed_material"] == "CANONICAL_VISIBLE_PROJECTION"
        assert actual["target_scene_stimuli"] == [
            exploration_tasks.SCENE_LOCAL_STIMULUS_PREFIX + "CANONICAL_LOCAL_STIMULUS"
        ]
        assert "CANONICAL_HIDDEN_SECRET" not in json.dumps(actual)
    else:
        assert actual["target_knowledge"]["knows"] == ["OWN_KNOWN"]


async def test_repair_receives_only_local_candidate_and_verifiable_finding_excerpt(
    unit_context,
):
    start = _start()
    output = _line()
    data = exploration_tasks._scene_line_user_data(
        start=start,
        focus="CURRENT_FOCUS",
        target_ref="c_one",
        confirmed=unit_context,
        mode="revise",
        parent_payload=None,
        instruction="REVISE_CURRENT_UNIT",
    )
    findings = [
        AuditFindingOutput(
            kind=kind,
            severity=severity,
            message="REVIEW_MESSAGE_SECRET",
            source_key="REVIEW_SOURCE_SECRET",
            excerpt=excerpt,
        )
        for kind, severity, excerpt in (
            ("unsupported_fact", "major", output.rationale),
            ("premature_reveal", "blocker", "MERGED_OTHER_ITEM_SECRET"),
        )
    ]
    calls = await _run(
        start,
        unit_context,
        data,
        exploration_tasks._SYSTEM_PROMPTS[exploration_tasks.SCENE_LINE_ACTION],
        output,
        findings=findings,
        audit_output=lambda candidate: {
            "variants": [
                candidate.model_dump(mode="json"),
                {"line": "MERGED_OTHER_ITEM_SECRET"},
            ]
        },
    )
    generations = [request for schema, request in calls if schema is SceneLineOutputV1]
    assert len(calls) == 5
    assert len(generations) == 2
    repaired = generations[1]
    assistant_messages = [m.content for m in repaired.messages if m.role == "assistant"]
    assert len(assistant_messages) == 1
    assert json.loads(assistant_messages[0]) == output.model_dump(mode="json")
    feedback = json.loads(repaired.messages[-1].content.split("：", 1)[1])
    assert [(item["kind"], item["severity"]) for item in feedback] == [
        ("unsupported_fact", "major"),
        ("premature_reveal", "blocker"),
    ]
    assert feedback[0]["excerpt"] == output.rationale
    assert not feedback[1].get("excerpt")
    assert all(set(item) <= {"kind", "severity", "excerpt"} for item in feedback)
    text = json.dumps([m.model_dump(mode="json") for m in repaired.messages])
    for secret in (
        PRIVATE,
        "REVIEW_MESSAGE_SECRET",
        "REVIEW_SOURCE_SECRET",
        "MERGED_OTHER_ITEM_SECRET",
    ):
        assert secret not in text


@pytest.mark.parametrize("target", ["c_one", CANONICAL])
async def test_actor_director_receives_material_only_when_projection_has_content(
    unit_context, target
):
    start = _start()
    data = exploration_tasks._scene_line_user_data(
        start=start,
        focus="CURRENT_FOCUS",
        target_ref=target,
        confirmed=unit_context,
        mode="start",
        parent_payload=None,
        instruction="",
    )
    calls = await _run(
        start,
        unit_context,
        data,
        exploration_tasks._SYSTEM_PROMPTS[exploration_tasks.SCENE_LINE_ACTION],
        _line(target),
    )
    director = next(request for schema, request in calls if schema is DirectorShardPlan)
    director_text = "\n".join(message.content for message in director.messages)
    generation = next(request for schema, request in calls if schema is SceneLineOutputV1)
    packet = json.loads(next(m.content for m in generation.messages if m.role == "user"))
    if target == CANONICAL:
        assert "packet:confirmed_material" in director_text
        assert packet["confirmed_material"] == "CANONICAL_VISIBLE_PROJECTION"
    else:
        assert "packet:confirmed_material" not in director_text
        assert "confirmed_material" not in packet
    assert packet["target"]["ref"] == target
    assert packet["mode"] == "start"


@pytest.mark.parametrize(
    "target,excluded",
    [
        ("c_one", "target"),
        ("c_one", "target_knowledge"),
        ("c_one", "mode"),
        ("c_one", "output_rule"),
        ("c_one", "accumulated_observations"),
        (CANONICAL, "confirmed_material"),
    ],
)
async def test_empty_material_change_keeps_nonempty_and_control_packets_required(
    monkeypatch, unit_context, target, excluded
):
    seen_schemas = []
    original = ScriptedClient.generate_structured

    async def exclude_required(self, request, schema, **kwargs):
        seen_schemas.append(schema)
        result = await original(self, request, schema, **kwargs)
        if schema is DirectorShardPlan:
            selected = [
                item
                for item in result.dispositions
                if item.source_key == "packet:" + excluded
            ]
            assert len(selected) == 1
            selected[0].disposition = "director_audit_only"
        return result

    monkeypatch.setattr(ScriptedClient, "generate_structured", exclude_required)
    start = _start()
    data = exploration_tasks._rehearsal_performance_packet(
        start=start,
        focus="CURRENT_FOCUS",
        target_ref=target,
        confirmed=unit_context,
        round_number=2,
        previous_round=None,
    )
    data["accumulated_observations"] = ["OWN_PREVIOUSLY_OBSERVED"]
    output = FullRehearsalPerformance(
        target_ref=target, line_or_beat="LOCAL_BEAT", rationale="OWN_PREVIOUSLY_OBSERVED"
    )
    with pytest.raises(ConflictError, match="未保留本次探索必需"):
        await _run(
            start,
            unit_context,
            data,
            exploration_tasks.FULL_REHEARSAL_CARD_PROMPT,
            output,
        )
    assert seen_schemas == [DirectorShardPlan]
