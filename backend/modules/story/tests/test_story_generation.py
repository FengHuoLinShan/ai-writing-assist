"""Generation, review and repair must share the same frozen inputs."""

import uuid

import pytest

from modules.evidence.compilation.knowledge.llm_schemas import AuditVerdictOutput
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
                    dimensions=[],
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
