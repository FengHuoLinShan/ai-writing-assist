"""Live counterexamples: task inputs cannot disappear inside knowledge selection."""

import json

import pytest

from core.errors import ConflictError
from infrastructure.llm.schemas import AIStepCallKind, LLMUsage
from infrastructure.llm.workflow_budget import (
    AIManagedStepContext,
    managed_step_scope,
    new_ai_run_envelope,
)
from modules.story import exploration_tasks

pytest_plugins = ["modules.story.tests.test_exploration_worker"]


@pytest.mark.parametrize(
    "scale,excluded,diagnostic_question",
    [
        ("sandbox", "author_packet", None),
        ("scene_line", "target_knowledge", None),
        ("scene_line", "question", "能抱箱子通过桌边吗？"),
        ("scene_line", "spatial_material", "能抱箱子通过桌边吗？"),
    ],
)
async def test_director_cannot_silently_remove_required_task_input(
    exploration_flow, monkeypatch, scale, excluded, diagnostic_question
):
    flow = exploration_flow
    original = flow.provider.generate

    async def exclude_required(request):
        response = await original(request)
        if '创作知识治理的"导演"' in request.messages[0].content:
            prompt = next(
                message.content for message in request.messages if message.role == "user"
            )
            assert (
                "这是作者侧探索"
                if scale == "sandbox" or diagnostic_question
                else "这是人物侧生成"
            ) in prompt
            payload = json.loads(response.content)
            for item in payload["dispositions"]:
                if item["source_key"] == "packet:" + excluded:
                    item["disposition"] = "director_audit_only"
            response = response.model_copy(update={"content": json.dumps(payload)})
        return response

    monkeypatch.setattr(flow.provider, "generate", exclude_required)
    spec, envelope = await flow.setup(
        chain="progression" if scale == "sandbox" else "scene", scale=scale
    )
    action = (
        exploration_tasks.SANDBOX_ACTION
        if scale == "sandbox"
        else exploration_tasks.SCENE_LINE_ACTION
    )
    task = await flow.run(
        await flow.enqueue(
            spec,
            envelope,
            action=action,
            **(
                {"diagnostic_question": diagnostic_question}
                if diagnostic_question
                else {"target_ref": "c_baker"}
                if scale == "scene_line"
                else {}
            ),
        )
    )
    assert task.status == "failed"
    assert "未保留本次探索必需的任务输入" in task.error_message
    assert len(flow.provider.requests) == 1
    assert flow.provider.generation_requests == []


async def test_semantic_failure_is_not_reclassified_by_soft_token_threshold():
    envelope = new_ai_run_envelope(
        operation_id="counterexample",
        run_id="counterexample",
        root_capability_id="story.exploration",
        novel_id="n",
        request_limit=5,
        token_limit=100,
    )
    with managed_step_scope(
        AIManagedStepContext(
            step_name="story.exploration.sandbox.generate",
            call_kind=AIStepCallKind.generate,
            capability_id="story.exploration",
            profile_source="project",
            profile_summary={"provider_id": "codex", "model": "gpt-6-luna"},
        )
    ):
        reservation = await envelope.reserve(provider_id="codex", model="gpt-6-luna")
        await envelope.settle(
            reservation,
            usage=LLMUsage(prompt_tokens=80, completion_tokens=1, total_tokens=81),
        )
    assert exploration_tasks.budget_stop_reason(envelope) == "token_budget_80_percent"
    error = ConflictError("审查阻断", code="exploration_knowledge_blocked")
    assert exploration_tasks._classify_stop(error, {}, envelope) is None


@pytest.mark.parametrize("scale", ["sandbox", "scene_line"])
async def test_existing_root_keeps_legacy_preview_and_budget(exploration_flow, scale):
    from infrastructure.llm.collaboration import content_hash
    from infrastructure.llm.schemas import read_ai_run_envelope
    from modules.story.exploration_budget import exploration_preview_identity
    from modules.story.models import StorySceneDirectorRoot
    from modules.story.world_progression_models import StoryWorldProgressionRoot

    flow = exploration_flow
    spec, envelope = await flow.setup(
        chain="scene" if scale == "scene_line" else "progression", scale=scale
    )
    root_model = (
        StorySceneDirectorRoot if scale == "scene_line" else StoryWorldProgressionRoot
    )
    before = envelope.snapshot()
    async with flow.sessions.begin() as db:
        root = await db.get(root_model, spec.root_id)
        request = dict(root.request_json)
        request.pop("exploration_budget_policy_version")
        root.request_json = request
    legacy_hash = content_hash(
        exploration_preview_identity(
            novel_id=str(spec.novel_id),
            scale=scale,
            start=flow.start,
            focus=flow.focus,
            budget_policy_version=1,
        )
    )
    task = await flow.run(
        await flow.enqueue(
            spec,
            envelope,
            action=exploration_tasks.SCENE_LINE_ACTION
            if scale == "scene_line"
            else exploration_tasks.SANDBOX_ACTION,
            preview_hash=legacy_hash,
            **({"target_ref": "c_baker"} if scale == "scene_line" else {}),
        )
    )
    assert task.status == "done", task.error_message
    assert task.result["status"] == "completed"
    async with flow.sessions() as db:
        root = await db.get(root_model, spec.root_id)
        after = read_ai_run_envelope(root.run_envelope_json)
        assert after.token_limit == before.token_limit
        assert after.request_limit == before.request_limit
