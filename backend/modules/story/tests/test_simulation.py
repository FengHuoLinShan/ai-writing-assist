"""Deterministic information-flow and simultaneous-action checks."""

import json
import uuid

import pytest

from infrastructure.llm.agent_runtime import AgentRunBudget
from infrastructure.llm.schemas import LLMCallResponse, LLMToolCall, LLMUsage
from modules.story.simulation import (
    ActionIntent,
    RoundResolution,
    rehearse_round,
    resolve_events,
)


def test_whisper_does_not_reach_third_actor_or_expose_internal_reason():
    intents = {
        "a": ActionIntent(
            kind="speak",
            action="钥匙在井底",
            visibility="whisper",
            audience=["b"],
            internal_reason="我其实是凶手",
        ),
        "b": ActionIntent(kind="wait", action="等待"),
        "c": ActionIntent(kind="observe", action="看着门口"),
    }
    events, state = resolve_events(
        intents,
        RoundResolution(
            outcomes=[{"actor_id": actor, "outcome": "succeeded"} for actor in intents]
        ),
        {},
    )
    assert "钥匙在井底" not in json.dumps(state["observations"]["c"], ensure_ascii=False)
    assert "钥匙在井底" in json.dumps(state["observations"]["b"], ensure_ascii=False)
    assert "凶手" not in json.dumps(events, ensure_ascii=False)
    assert "凶手" not in json.dumps(state, ensure_ascii=False)


def test_two_actors_cannot_both_acquire_one_resource_and_branch_state_is_copied():
    baseline = {"resource_holders": {"铜钥匙": "keeper"}}
    intents = {
        actor: ActionIntent(kind="act", action="抓取铜钥匙", resource_key="铜钥匙")
        for actor in ("a", "b")
    }
    events, state = resolve_events(
        intents,
        RoundResolution(
            outcomes=[{"actor_id": actor, "outcome": "succeeded"} for actor in intents]
        ),
        baseline,
    )
    assert all(event["outcome"] == "uncertain" for event in events)
    assert state["resource_holders"]["铜钥匙"] == "keeper"
    assert baseline == {"resource_holders": {"铜钥匙": "keeper"}}
    with pytest.raises(ValueError):
        resolve_events(
            intents,
            RoundResolution(outcomes=[{"actor_id": "outsider", "outcome": "succeeded"}]),
            baseline,
        )


async def test_same_round_actors_only_receive_their_packet_and_prior_observations():
    a, b = str(uuid.uuid4()), str(uuid.uuid4())
    seen, saved = {}, []

    class Client:
        model_name = "deepseek-flash"

        async def generate(self, request, **kwargs):
            payload = json.loads(request.messages[-1].content)
            actor = payload["actor_id"]
            seen[actor] = payload
            tool = next(
                tool for tool in request.tools if tool.name.startswith("final_result")
            )
            return LLMCallResponse(
                tool_calls=[
                    LLMToolCall(
                        id=actor,
                        name=tool.name,
                        arguments=json.dumps(
                            {
                                "kind": "wait",
                                "action": "等候",
                                "internal_reason": "下一步私有意图",
                            }
                        ),
                    )
                ],
                usage=LLMUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            )

        async def generate_structured(self, request, schema, **kwargs):
            assert "下一步私有意图" not in request.messages[-1].content
            return schema(
                outcomes=[{"actor_id": actor, "outcome": "succeeded"} for actor in (a, b)]
            )

    async def checkpoint(_values):
        pass

    async def save_items(values):
        saved[:] = values

    kwargs = dict(
        client=Client(),
        packets={a: "只许甲知道的秘密", b: "乙怀疑有危险"},
        state={},
        authority="作者规则",
        budget=AgentRunBudget(policy_version="team_v1"),
        checkpoint=checkpoint,
        capability_id="story.one_click",
        input_limit=10000,
        save_items=save_items,
    )
    result = await rehearse_round(**kwargs)
    assert "秘密" not in json.dumps(seen[b], ensure_ascii=False)
    assert "作者规则" not in json.dumps(seen, ensure_ascii=False)
    assert len(result["events"]) == 2
    first_calls = len(seen)
    await rehearse_round(**kwargs, saved_items=saved)
    assert len(seen) == first_calls
