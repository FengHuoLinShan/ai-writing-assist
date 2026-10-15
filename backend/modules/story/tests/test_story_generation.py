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
            return schema(content={"personality": "谨慎", "current_goal": "守住码头"})

    client = Client()
    result = await StoryGenerationService().card_preview(
        client,
        context_markdown="前文" * 13000 + "尾部规则：潮门不能运送生命。",
        scene_context={"scene_id": "scene-1", "situation": "盐料只剩一日"},
        character_id=str(uuid.uuid4()),
        additional_notes="保留焦虑但不让他逃离岗位",
    )
    assert result.knowledge_review["status"] == "passed"
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
