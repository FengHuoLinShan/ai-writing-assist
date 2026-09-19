"""Persist real rounds; replay/fork never reruns or rewrites their prefix."""

import json
import uuid
from types import SimpleNamespace

import pytest

from core.errors import ConflictError
from infrastructure.llm.schemas import LLMCallResponse, LLMToolCall, LLMUsage
from modules.story.rehearsals import read_rehearsal, run_rehearsal
from modules.story.schemas import ScriptPreview, StoryOneClickTaskRequest
from modules.story.simulation import RoundResolution
from modules.story.tests.test_story_service import _character, _scene


async def test_round_replay_fork_and_source_change(
    db_session, test_project_id, monkeypatch
):
    scene = await _scene(db_session, test_project_id)
    actor = str(await _character(db_session, test_project_id))
    current = SimpleNamespace(context_hash="source-v1")
    calls = []

    async def prepare(*args, **kwargs):
        return None

    async def context(*args, **kwargs):
        return current

    monkeypatch.setattr("modules.story.rehearsals.prepare_confirmed_ai_action", prepare)
    monkeypatch.setattr("modules.story.facade.get_scene_story_context", context)
    monkeypatch.setattr(
        "modules.story.rehearsals.capability_from_execution_snapshot",
        lambda _: SimpleNamespace(hard_input_tokens=20000),
    )

    class Client:
        model_name = "synthetic"

        async def generate(self, request, **kwargs):
            calls.append("actor")
            tool = next(t for t in request.tools if t.name.startswith("final_result"))
            return LLMCallResponse(
                tool_calls=[
                    LLMToolCall(
                        id=str(uuid.uuid4()),
                        name=tool.name,
                        arguments=json.dumps({"kind": "wait", "action": "在门边等候"}),
                    )
                ],
                usage=LLMUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            )

        async def generate_structured(self, request, schema, **kwargs):
            if schema is RoundResolution:
                calls.append("resolver")
                return schema(outcomes=[{"actor_id": actor, "outcome": "succeeded"}])
            if schema is ScriptPreview:
                calls.append("script")
                assert "私密动机" not in str(request.messages)
                return schema(
                    scene_id=scene.id, script_text="他在门边等候。", narrative_plan="等候"
                )
            return schema(
                verdict="pass",
                findings=[],
                dimensions=[{"dimension": "scene", "checked": True}],
            )

    def task():
        return SimpleNamespace(
            id=uuid.uuid4(),
            meta={"llm_execution_snapshot": {}},
            update_progress=lambda _: None,
        )

    data = StoryOneClickTaskRequest(
        novel_id=test_project_id,
        scene_id=str(scene.id),
        character_ids=[actor],
        context_confirmation_id="synthetic-confirmation",
        simulation_protocol="rehearsal_v1",
        rehearsal_rounds=2,
    )
    kwargs = dict(
        client=Client(),
        authority="作者规则",
        scene_context={"context_hash": "source-v1"},
        character_reveals={actor: {"markdown": "私密动机", "hash": "a" * 64}},
    )
    parent = task()
    original = await run_rehearsal(db_session, parent, data, **kwargs)
    assert original["round_count"] == 2 and original["writes"] == []
    assert calls.count("actor") == calls.count("resolver") == 2
    before = list(calls)
    assert await run_rehearsal(db_session, parent, data, **kwargs) == original
    assert calls == before
    view = await read_rehearsal(db_session, test_project_id, str(parent.id))
    assert "私密动机" not in json.dumps(view, ensure_ascii=False)
    fork = task()
    fork_data = data.model_copy(
        update={
            "parent_rehearsal_id": parent.id,
            "fork_round": 1,
            "parent_round_hash": view["rounds"][0]["hash"],
            "rehearsal_rounds": 1,
        }
    )
    await run_rehearsal(db_session, fork, fork_data, **kwargs)
    fork_view = await read_rehearsal(db_session, test_project_id, str(fork.id))
    assert fork_view["rounds"][0] == view["rounds"][0]
    assert calls.count("actor") == calls.count("resolver") == 3
    assert await read_rehearsal(db_session, test_project_id, str(parent.id)) == view
    current.context_hash = "source-v2"
    with pytest.raises(ConflictError):
        await run_rehearsal(db_session, task(), data, **kwargs)
