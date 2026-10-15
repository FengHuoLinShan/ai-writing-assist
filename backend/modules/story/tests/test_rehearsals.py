"""Persist real rounds; replay/fork never reruns or rewrites their prefix."""

import json
import uuid
from copy import deepcopy
from types import SimpleNamespace

import pytest

from core.errors import ConflictError
from infrastructure.llm.collaboration import content_hash
from infrastructure.llm.schemas import LLMCallResponse, LLMToolCall, LLMUsage
from modules.story.models import StorySimulationRun, StorySimulationStep
from modules.story.observations import (
    ObservationIntent,
    ResolutionProposal,
    replay_batch,
    resolve_batch,
    seeded_state,
)
from modules.story.rehearsals import (
    read_rehearsal,
    replay_rehearsal,
    run_rehearsal,
)
from modules.story.schemas import ScriptPreview, StoryOneClickTaskRequest
from modules.story.simulation_v3 import FiniteResolution
from modules.story.tests.test_story_service import _character, _scene


def _stored_rehearsal_request(novel_id: str, scene_id: str, actor_id: str, protocol: str):
    return {
        "novel_id": novel_id,
        "scene_id": scene_id,
        "character_ids": [actor_id],
        "context_confirmation_id": "historical-confirmation",
        "simulation_protocol": protocol,
        "simulation_seed": None,
        "rehearsal_rounds": 1,
        "fork_round": 0,
        "parent_rehearsal_id": None,
        "parent_round_hash": None,
        "narrator_character_id": None,
    }


async def test_story_worker_refuses_to_create_a_legacy_protocol_run(
    db_session, test_project_id
):
    actor_id, scene_id = str(uuid.uuid4()), str(uuid.uuid4())
    data = StoryOneClickTaskRequest(
        novel_id=test_project_id,
        scene_id=scene_id,
        character_ids=[actor_id],
        context_confirmation_id="legacy-confirmation",
        simulation_protocol="rehearsal_v1",
        rehearsal_rounds=1,
    )
    task = SimpleNamespace(id=uuid.uuid4())

    with pytest.raises(ConflictError, match="旧协议排演只读"):
        await run_rehearsal(
            db_session,
            task,
            data,
            client=None,
            authority="",
            scene_context={},
            character_reveals={},
        )
    assert await db_session.get(StorySimulationRun, task.id) is None


async def test_story_worker_refuses_unreviewed_multi_round_v3_run(
    db_session, test_project_id
):
    actor_id, scene_id = str(uuid.uuid4()), str(uuid.uuid4())
    data = StoryOneClickTaskRequest(
        novel_id=test_project_id,
        scene_id=scene_id,
        character_ids=[actor_id],
        context_confirmation_id="v3-confirmation",
        simulation_protocol="simulation_v3",
        rehearsal_rounds=2,
    )
    task = SimpleNamespace(id=uuid.uuid4())

    with pytest.raises(ConflictError, match="当前一次只提交一回合"):
        await run_rehearsal(
            db_session,
            task,
            data,
            client=None,
            authority="",
            scene_context={},
            character_reveals={},
        )
    assert await db_session.get(StorySimulationRun, task.id) is None


async def test_historical_rehearsal_v1_remains_readable_without_reinterpretation(
    db_session, test_project_id
):
    actor_id, scene_id, run_id = (uuid.uuid4() for _ in range(3))
    request_json = _stored_rehearsal_request(
        test_project_id, str(scene_id), str(actor_id), "rehearsal_v1"
    )
    run = StorySimulationRun(
        id=run_id,
        novel_id=uuid.UUID(test_project_id),
        scene_id=scene_id,
        parent_id=None,
        fork_round=0,
        source_hash="a" * 64,
        request_json=request_json,
        budget_json={"policy_version": "team_v1"},
        result_json={"preview_only": True, "legacy": True},
    )
    legacy_state = {"legacy_state": "unchanged"}
    step = StorySimulationStep(
        novel_id=uuid.UUID(test_project_id),
        run_id=run_id,
        round_number=1,
        input_hash="b" * 64,
        output_hash="c" * 64,
        intents_json={"legacy_intent": "wait"},
        events_json=[{"action": "等待", "observers": [str(actor_id)]}],
        state_json=legacy_state,
    )
    db_session.add(run)
    db_session.add(step)
    await db_session.flush()
    frozen_request = deepcopy(run.request_json)
    frozen_step_state = deepcopy(legacy_state)

    view = await read_rehearsal(db_session, test_project_id, str(run_id))

    assert view["protocol"] == "rehearsal_v1"
    assert view["rounds"] == [
        {
            "number": 1,
            "hash": "c" * 64,
            "events": [{"action": "等待", "observers": [str(actor_id)]}],
        }
    ]
    assert run.request_json == frozen_request
    assert run.result_json == {"preview_only": True, "legacy": True}
    assert step.state_json == frozen_step_state


async def test_historical_observation_v2_batch_replays_without_model_or_writes(
    db_session, test_project_id
):
    actor_id, scene_id, run_id = (uuid.uuid4() for _ in range(3))
    actor = str(actor_id)
    request_json = _stored_rehearsal_request(
        test_project_id, str(scene_id), actor, "observation_v2"
    )
    base_state = seeded_state(None, [actor])
    batch = resolve_batch(
        {actor: ObservationIntent(kind="wait", action="守候")},
        ResolutionProposal(outcomes=[{"actor_id": actor, "outcome": "succeeded"}]),
        base_state,
        observers={actor},
        rule_revision="d" * 64,
    )
    replayed = replay_batch(base_state, batch)
    run = StorySimulationRun(
        id=run_id,
        novel_id=uuid.UUID(test_project_id),
        scene_id=scene_id,
        parent_id=None,
        fork_round=0,
        source_hash="e" * 64,
        request_json=request_json,
        budget_json={"policy_version": "team_v1"},
        result_json={"preview_only": True},
    )
    intents_json = {
        "intents": {actor: {"kind": "wait", "action": "守候"}},
        "resolution_batch": batch.model_dump(mode="json"),
    }
    step = StorySimulationStep(
        novel_id=uuid.UUID(test_project_id),
        run_id=run_id,
        round_number=1,
        input_hash="f" * 64,
        output_hash=content_hash({"stored_batch": batch.model_dump(mode="json")}),
        intents_json=intents_json,
        events_json=batch.events,
        state_json=replayed,
    )
    db_session.add_all([run, step])
    await db_session.flush()
    frozen_request = deepcopy(run.request_json)
    frozen_intents = deepcopy(step.intents_json)
    frozen_state = deepcopy(step.state_json)

    replay = await replay_rehearsal(db_session, test_project_id, str(run_id))
    view = await read_rehearsal(db_session, test_project_id, str(run_id))

    assert replay == {
        "verified": True,
        "model_requests": 0,
        "rounds": [{"number": 1, "state_hash": content_hash(replayed)}],
    }
    assert view["protocol"] == "observation_v2"
    assert run.request_json == frozen_request
    assert step.intents_json == frozen_intents
    assert step.state_json == frozen_state


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
            if schema is FiniteResolution:
                calls.append("resolver")
                payload = json.loads(request.messages[-1].content)
                return schema(
                    outcomes=[
                        {
                            "intent_id": payload["intents"][0]["intent_id"],
                            "outcome": "succeeded",
                        }
                    ]
                )
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
        simulation_protocol="simulation_v3",
        rehearsal_rounds=1,
    )
    kwargs = dict(
        client=Client(),
        authority="作者规则",
        scene_context={"context_hash": "source-v1"},
        character_reveals={actor: {"markdown": "私密动机", "hash": "a" * 64}},
    )
    parent = task()
    original = await run_rehearsal(db_session, parent, data, **kwargs)
    assert original["round_count"] == 1 and original["writes"] == []
    replay = await replay_rehearsal(db_session, test_project_id, str(parent.id))
    assert replay["verified"] is True
    assert replay["model_requests"] == 0
    assert [round_result["number"] for round_result in replay["rounds"]] == [1]
    assert calls.count("actor") == calls.count("resolver") == 1
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
    assert calls.count("actor") == calls.count("resolver") == 2
    assert await read_rehearsal(db_session, test_project_id, str(parent.id)) == view
    current.context_hash = "source-v2"
    with pytest.raises(ConflictError):
        await run_rehearsal(db_session, task(), data, **kwargs)
