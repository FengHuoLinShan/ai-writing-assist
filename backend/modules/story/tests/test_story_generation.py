"""Generation, review and repair must share the same frozen inputs."""

import uuid

import pytest

from modules.evidence.compilation.knowledge.llm_schemas import (
    AuditDimensionCheck,
    AuditVerdictOutput,
)
from modules.story.generation import StoryGenerationService


@pytest.mark.asyncio
async def test_card_review_sees_scene_target_and_context_tail_and_repair_sees_draft():
    class Client:
        model_name = "test"

        def __init__(self):
            self.audits = []
            self.generations = []

        async def generate_structured(self, request, schema, **_kwargs):
            if schema is AuditVerdictOutput:
                self.audits.append(request.messages[-1].content)
                return schema(
                    findings=[],
                    dimensions=[
                        {"dimension": dimension, "checked": True}
                        for dimension in _required_dimensions(request.messages)
                    ],
                    verdict="blocked" if len(self.audits) == 1 else "pass",
                )
            self.generations.append(request)
            return schema(
                interpretations=[
                    {
                        "category": "goal",
                        "statement": "守住码头",
                        "source_fact_ids": ["story:known-goal"],
                    }
                ]
            )

    client = Client()
    character_id = str(uuid.uuid4())
    result = await StoryGenerationService().card_preview(
        client,
        context_markdown="前文" * 13000 + "尾部规则：潮门不能运送生命。",
        scene_context={"scene_id": "scene-1", "situation": "盐料只剩一日"},
        character_id=character_id,
        additional_notes="保留焦虑但不让他逃离岗位",
        deterministic_facts=[
            {
                "fact_id": "story:known-goal",
                "kind": "story_state",
                "layer": "fact",
                "subject_id": character_id,
                "dimension": "entities",
                "field": "current_goal",
                "value": "守住码头",
                "checkpoint_id": "checkpoint-1",
            }
        ],
    )
    assert result.knowledge_review["status"] == "passed"
    assert result.content.version == "character_card.v2"
    assert result.content.fact_basis[0].fact_id == "story:known-goal"
    assert result.content.interpretations[0].source_fact_ids == ["story:known-goal"]
    assert len(client.generations) == len(client.audits) == 2
    for prompt in client.audits:
        assert "尾部规则：潮门不能运送生命。" in prompt
        assert "盐料只剩一日" in prompt
        assert "保留焦虑但不让他逃离岗位" in prompt
    repair = client.generations[-1]
    assert any(
        message.role == "assistant" and "守住码头" in message.content
        for message in repair.messages
    )


def _required_dimensions(messages) -> list[str]:
    """从审查 prompt 读取必查维度；合成审查者按全部维度已查应答。"""
    for message in messages:
        for line in (message.content or "").splitlines():
            if line.startswith("必查维度："):
                return [
                    item.strip()
                    for item in line.split("：", 1)[1].split(",")
                    if item.strip()
                ]
    return []


@pytest.mark.asyncio
async def test_script_review_records_missing_map_as_advisory_omission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import modules.evidence.contracts as evidence_contracts
    from modules.story.schemas import ScriptPreview

    run_audit = evidence_contracts.run_knowledge_audit
    captured: dict[str, object] = {}

    async def capture_audit(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        captured["scope_build"] = kwargs["scope_build"]
        captured["plan"] = kwargs["plan"]
        return await run_audit(*args, **kwargs)

    monkeypatch.setattr(evidence_contracts, "run_knowledge_audit", capture_audit)

    class Client:
        model_name = "test"

        async def generate_structured(self, request, schema, **_kwargs):
            if schema is AuditVerdictOutput:
                return schema(
                    findings=[],
                    dimensions=[
                        AuditDimensionCheck(dimension=dimension, checked=True)
                        for dimension in _required_dimensions(request.messages)
                    ],
                    verdict="pass",
                )
            return ScriptPreview(
                scene_id=scene_id,
                script_text="他停在门前。",
                narrative_plan="等待回应",
            )

    scene_id = uuid.uuid4()
    result = await StoryGenerationService().script_preview(
        Client(),
        context_markdown="前文片段",
        scene_context={"scene_id": str(scene_id)},
        character_ids=[],
    )

    assert result.knowledge_review["status"] == "passed"
    scope_build = captured["scope_build"]
    assert scope_build.receipt.policy_version == 2
    assert scope_build.receipt.scope_complete is True
    assert scope_build.receipt.omitted == ()
    assert [item.dimension for item in scope_build.receipt.advisory_omitted] == [
        "map_spatial"
    ]
    assert captured["plan"].policy_version == 2


@pytest.mark.asyncio
async def test_card_rejects_unavailable_source_id():
    class Client:
        model_name = "test"

        async def generate_structured(self, _request, schema, **_kwargs):
            if schema is AuditVerdictOutput:
                return schema(
                    findings=[],
                    dimensions=[
                        {"dimension": item, "checked": True}
                        for item in _required_dimensions(_request.messages)
                    ],
                    verdict="pass",
                )
            return schema(
                interpretations=[
                    {
                        "category": "personality",
                        "statement": "看似谨慎",
                        "source_fact_ids": ["story:not-in-scope"],
                    }
                ]
            )

    character_id = str(uuid.uuid4())
    with pytest.raises(ValueError, match="unknown fact id"):
        await StoryGenerationService().card_preview(
            Client(),
            context_markdown="可见人物资料",
            scene_context={"scene_id": "scene"},
            character_id=character_id,
            deterministic_facts=[
                {
                    "fact_id": "story:known-goal",
                    "kind": "story_state",
                    "layer": "fact",
                    "subject_id": character_id,
                    "dimension": "entities",
                    "field": "goal",
                    "value": "守门",
                }
            ],
        )


def test_card_v1_payload_remains_readable_and_v2_requires_source_references():
    from pydantic import ValidationError

    from modules.story.schemas import CharacterCardContent

    legacy = CharacterCardContent.model_validate({"personality": "谨慎"})
    assert legacy.version == "character_card.v1"
    with pytest.raises(ValidationError, match="require at least one source id"):
        CharacterCardContent(
            version="character_card.v2",
            interpretations=[{"category": "personality", "statement": "谨慎"}],
        )


def test_reaction_motivations_are_optional_but_source_bound_and_two_to_four():
    from pydantic import ValidationError

    from modules.story.schemas import ReactionProposal

    character_id = uuid.uuid4()
    motivation = {
        "category": "fear",
        "statement": "他担心潮门失守",
        "source_fact_ids": ["story:fear"],
    }
    base = {
        "character_id": character_id,
        "intended_action": "先核对门闩",
        "internal_pressure": "时间不足",
    }
    valid = ReactionProposal(
        **base,
        motivations=[motivation, {**motivation, "statement": "担心同伴受伤"}],
    )
    assert len(valid.motivations) == 2
    with pytest.raises(ValidationError, match="omitted or contain 2 to 4"):
        ReactionProposal(**base, motivations=[motivation])


@pytest.mark.asyncio
async def test_reaction_rejects_unknown_source_id():
    from modules.story.schemas import ReactionPreview

    class Client:
        model_name = "test"

        async def generate_structured(self, request, schema, **_kwargs):
            if schema is AuditVerdictOutput:
                return schema(
                    findings=[],
                    dimensions=[
                        {"dimension": item, "checked": True}
                        for item in _required_dimensions(request.messages)
                    ],
                    verdict="pass",
                )
            return ReactionPreview(
                scene_id=scene_id,
                proposals=[
                    {
                        "character_id": character_id,
                        "intended_action": "核对门闩",
                        "internal_pressure": "時間不足",
                        "motivations": [
                            {
                                "category": "fear",
                                "statement": "担心潮门失守",
                                "source_fact_ids": ["story:not-in-scope"],
                            },
                            {
                                "category": "goal",
                                "statement": "想守住仓库",
                                "source_fact_ids": ["story:known-goal"],
                            },
                        ],
                    }
                ],
            )

    scene_id = uuid.uuid4()
    character_id = uuid.uuid4()
    with pytest.raises(ValueError, match="unknown fact id"):
        await StoryGenerationService().reaction_preview(
            Client(),
            context_markdown="角色可见事实",
            scene_context={"scene_id": str(scene_id)},
            character_ids=[str(character_id)],
            deterministic_facts=[
                {
                    "fact_id": "story:known-goal",
                    "kind": "story_state",
                    "layer": "fact",
                    "subject_id": str(character_id),
                    "dimension": "entities",
                    "field": "goal",
                    "value": "守住仓库",
                }
            ],
        )
