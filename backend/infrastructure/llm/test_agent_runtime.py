"""Exercise the real PydanticAI loop and the existing provider boundary."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import BaseModel, ValidationError
from pydantic_ai import Tool
from pydantic_ai.messages import ModelRequest, UserPromptPart
from pydantic_ai.models import ModelRequestParameters

from infrastructure.llm.agent_runtime import (
    AgentBudgetError,
    AgentRunBudget,
    ProjectGatewayModel,
    run_project_agent,
)
from infrastructure.llm.providers import OpenAIProvider
from infrastructure.llm.schemas import (
    LLMCallRequest,
    LLMCallResponse,
    LLMMessage,
    LLMStreamChunk,
    LLMToolCall,
    LLMToolDefinition,
    LLMToolDelta,
    LLMUsage,
)


class Answer(BaseModel):
    answer: str


class ScriptedClient:
    model_name = "deepseek-v4-flash"

    def __init__(self):
        self.requests = []

    async def generate(self, request, *, transport_retries):
        assert transport_retries is False
        assert request.tool_choice == "auto"
        self.requests.append(request)
        if len(self.requests) == 1:
            return LLMCallResponse(
                tool_calls=[
                    LLMToolCall(id="read-1", name="lookup", arguments='{"name":"甲"}')
                ],
                reasoning_content="provider-private-continuation",
                usage=LLMUsage(prompt_tokens=10, completion_tokens=3, total_tokens=13),
            )
        assert request.messages[-1].role == "tool"
        assert request.messages[-1].tool_call_id == "read-1"
        assert request.messages[-1].content == "证据：甲在城外"
        assert request.messages[-2].reasoning_content == "provider-private-continuation"
        output_tool = next(t for t in request.tools if t.name != "lookup")
        return LLMCallResponse(
            tool_calls=[
                LLMToolCall(
                    id="answer-1",
                    name=output_tool.name,
                    arguments='{"answer":"甲在城外"}',
                )
            ],
            usage=LLMUsage(prompt_tokens=20, completion_tokens=5, total_tokens=25),
        )


@pytest.mark.asyncio
async def test_real_agent_loop_uses_gateway_and_pairs_read_results():
    client = ScriptedClient()
    calls = []
    checkpoints = []

    async def lookup(name: str) -> str:
        """Read a named character's authorized evidence."""
        calls.append(name)
        return "证据：甲在城外"

    async def checkpoint(value):
        checkpoints.append(value)

    budget = AgentRunBudget()
    result = await run_project_agent(
        client,
        LLMCallRequest(messages=[LLMMessage(role="user", content="甲在哪里？")]),
        tools=[Tool(lookup)],
        deps=None,
        output_type=Answer,
        budget=budget,
        input_limit=8000,
        checkpoint=checkpoint,
    )
    assert result.output.answer == "甲在城外"
    assert calls == ["甲"]
    assert budget.requests == 2 and budget.tool_attempts == 2
    assert budget.prompt_tokens == 30 and budget.completion_tokens == 8
    assert checkpoints[0]["requests"] == 1
    assert "provider-private-continuation" not in str(checkpoints)


@pytest.mark.asyncio
async def test_restored_budget_stops_before_provider_io():
    client = ScriptedClient()
    budget = AgentRunBudget.model_validate(
        AgentRunBudget(requests=12).model_dump(mode="json")
    )
    with pytest.raises(AgentBudgetError):
        await run_project_agent(
            client,
            LLMCallRequest(messages=[LLMMessage(content="hi")]),
            tools=[],
            deps=None,
            budget=budget,
            input_limit=8000,
        )
    assert client.requests == []
    expired = AgentRunBudget(started_at=datetime.now(UTC) - timedelta(minutes=31))
    with pytest.raises(AgentBudgetError):
        expired.reserve(requests=1)


def test_tool_history_rejects_unpaired_duplicate_and_unresolved_calls():
    call = LLMMessage(
        role="assistant", tool_calls=[LLMToolCall(id="a", name="read", arguments="{}")]
    )
    returned = LLMMessage(role="tool", tool_call_id="a", content="ok")
    LLMCallRequest(messages=[call, returned])
    for messages in [
        [call],
        [returned],
        [call, returned, returned],
        [call, returned, call, returned],
    ]:
        with pytest.raises(ValidationError):
            LLMCallRequest(messages=messages)
    message = LLMMessage(role="assistant", content="visible", reasoning_content="private")
    assert message.model_dump() == {"role": "assistant", "content": "visible"}
    assert message.provider_message()["reasoning_content"] == "private"


def test_provider_only_serializes_typed_tools_and_rejects_extra_bypass():
    provider = OpenAIProvider.__new__(OpenAIProvider)
    request = LLMCallRequest(
        tools=[LLMToolDefinition(name="read", parameters={"type": "object"})]
    )
    kwargs = provider._build_kwargs(request, "model")
    assert kwargs["tools"][0]["function"]["name"] == "read"
    for extra in [{"tools": []}, {"extra_body": {"tools": []}}]:
        with pytest.raises(ValueError, match="reserved"):
            provider._build_kwargs(LLMCallRequest(extra=extra), "model")


@pytest.mark.asyncio
async def test_stream_assembles_tool_json_and_preserves_private_reasoning():
    closed = []

    class StreamClient:
        model_name = "deepseek-v4-flash"

        async def generate_stream(self, _request, *, transport_retries):
            assert not transport_retries
            try:
                yield LLMStreamChunk(reasoning_content="private")
                yield LLMStreamChunk(
                    tool_deltas=[
                        LLMToolDelta(index=0, id="a", name="lookup", arguments='{"name":')
                    ]
                )
                yield LLMStreamChunk(
                    tool_deltas=[LLMToolDelta(index=0, arguments='"甲"}')],
                    finish_reason="tool_calls",
                    usage=LLMUsage(
                        prompt_tokens=10, completion_tokens=5, total_tokens=15
                    ),
                )
            finally:
                closed.append(True)

    budget = AgentRunBudget()
    model = ProjectGatewayModel(
        StreamClient(), LLMCallRequest(), budget, input_limit=8000
    )
    async with model.request_stream(
        [ModelRequest([UserPromptPart("hi")])], None, ModelRequestParameters()
    ) as stream:
        async for _event in stream:
            pass
        response = stream.get()
    assert response.parts[-1].tool_name == "lookup"
    assert response.parts[-1].args_as_dict() == {"name": "甲"}
    assert response.parts[0].content == "private"
    assert budget.tool_attempts == 1 and budget.requests == 1
    assert budget.completion_tokens == 5 and closed == [True]


@pytest.mark.asyncio
async def test_private_checkpoint_resumes_after_a_tool_without_repeating_it():
    called = []
    states = []

    class InterruptedClient(ScriptedClient):
        async def generate(self, request, *, transport_retries):
            if self.requests:
                raise ConnectionError("synthetic interruption")
            return await super().generate(request, transport_retries=transport_retries)

    async def lookup(name: str) -> str:
        called.append(name)
        return "证据：甲在城外"

    async def save_state(value):
        states.append(value)

    budget = AgentRunBudget()
    request = LLMCallRequest(messages=[LLMMessage(content="甲在哪里？")])
    with pytest.raises(ConnectionError):
        await run_project_agent(
            InterruptedClient(),
            request,
            tools=[Tool(lookup)],
            deps=None,
            output_type=Answer,
            budget=budget,
            input_limit=8000,
            state_checkpoint=save_state,
        )
    resumed = ScriptedClient()
    resumed.requests = [request]
    result = await run_project_agent(
        resumed,
        request,
        tools=[Tool(lookup)],
        deps=None,
        output_type=Answer,
        budget=AgentRunBudget.model_validate(budget.model_dump(mode="json")),
        input_limit=8000,
        state=states[-1],
    )
    assert result.output.answer == "甲在城外" and called == ["甲"]
    assert budget.requests == 2


def test_rp_preparation_reserves_the_final_story_request():
    budget = AgentRunBudget(mode="rp", requests=7)
    with pytest.raises(AgentBudgetError):
        budget.reserve(requests=1, future_requests=1)
    budget.reserve(requests=1)
    assert budget.requests == 8


def test_in_flight_usage_is_unknown_after_restart_and_native_requests_are_settled():
    budget = AgentRunBudget()
    budget.reserve(requests=1)
    assert budget.model_dump()["usage_complete"] is False
    restored = AgentRunBudget.model_validate(budget.model_dump(mode="json"))
    restored.reserve(requests=2, web=2)
    restored.add_usage(
        LLMUsage(prompt_tokens=4, completion_tokens=2, total_tokens=6), requests=2
    )
    assert restored.pending_usage == 1 and not restored.usage_complete
    restored.add_usage(None)
    assert restored.pending_usage == 0 and not restored.usage_complete
