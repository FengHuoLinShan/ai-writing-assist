"""Deterministic information-flow checks for Story simulation_v3 rounds."""

import json
import uuid

from infrastructure.llm.agent_runtime import AgentRunBudget
from infrastructure.llm.schemas import LLMCallResponse, LLMToolCall, LLMUsage
from modules.story.simulation import rehearse_round
from modules.story.simulation_v3 import FiniteResolution


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
            assert schema is FiniteResolution
            payload = json.loads(request.messages[-1].content)
            return schema(
                outcomes=[
                    {"intent_id": intent["intent_id"], "outcome": "succeeded"}
                    for intent in payload["intents"]
                ]
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
