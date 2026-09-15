"""Exercise the real PydanticAI loop and the existing provider boundary."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import BaseModel, ValidationError
from pydantic_ai import Tool
from pydantic_ai.exceptions import ModelRetry
from pydantic_ai.messages import ModelRequest, UserPromptPart
from pydantic_ai.models import ModelRequestParameters

from infrastructure.llm.agent_runtime import (
    AGENT_STEP_NAME,
    AgentBudgetError,
    AgentRunBudget,
    ProjectGatewayModel,
    run_project_agent,
)
from infrastructure.llm.client import LLMClient
from infrastructure.llm.native_search import (
    research_with_supplier,
)
from infrastructure.llm.providers import OpenAIProvider
from infrastructure.llm.schemas import (
    AIRunEnvelopeV1,
    AIStepCallKind,
    LLMCallRequest,
    LLMCallResponse,
    LLMMessage,
    LLMStreamChunk,
    LLMToolCall,
    LLMToolDefinition,
    LLMToolDelta,
    LLMUsage,
)
from infrastructure.llm.workflow_budget import (
    AIManagedStepContext,
    AIManagedStepContextError,
    AIRunEnvelope,
    AIRunIdentityError,
    ai_run_scope,
    current_ai_run_envelope,
    current_managed_step_context,
    workflow_budget,
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


# ---------------------------------------------------------------------------
# W2-Agent：有界 Agent、工具内嵌 step 与 research 共用同一个 run
# ---------------------------------------------------------------------------

_STARTED_AT = datetime(2026, 9, 15, 10, 0, tzinfo=UTC)


def _agent_ledger(**overrides) -> AIRunEnvelope:
    options = {
        "operation_id": "op-agent",
        "run_id": "run-agent",
        "root_capability_id": "assistant.turn",
        "novel_id": "novel-1",
        "started_at": _STARTED_AT,
        "deadline_at": datetime.now(UTC) + timedelta(minutes=20),
        "request_limit": 6,
    }
    options.update(overrides)
    return AIRunEnvelope(AIRunEnvelopeV1(**options))


def _tool_turn(name: str = "lookup", arguments: str = '{"name":"甲"}'):
    return LLMCallResponse(
        tool_calls=[LLMToolCall(id="read-1", name=name, arguments=arguments)],
        usage=LLMUsage(prompt_tokens=10, completion_tokens=3, total_tokens=13),
    )


def _answer_turn(answer: str = "甲在城外", exclude: tuple[str, ...] = ("lookup",)):
    def respond(request: LLMCallRequest) -> LLMCallResponse:
        output_tool = next(tool for tool in request.tools if tool.name not in exclude)
        return LLMCallResponse(
            tool_calls=[
                LLMToolCall(
                    id="answer-1",
                    name=output_tool.name,
                    arguments=json.dumps({"answer": answer}, ensure_ascii=False),
                )
            ],
            usage=LLMUsage(prompt_tokens=20, completion_tokens=5, total_tokens=25),
        )

    return respond


def _evidence_turn(content: str = "证据：甲在城外") -> LLMCallResponse:
    return LLMCallResponse(
        content=content,
        usage=LLMUsage(prompt_tokens=6, completion_tokens=2, total_tokens=8),
    )


class ScriptedProvider:
    """最小 provider 替身：计量由真实 `LLMClient` 的 provider 单入口承担。

    每次 provider I/O 记录请求、调用瞬间的受管 step 与供应商 SDK 替身（research）。
    """

    name = "scripted"

    def __init__(self, responses=(), sdk=None) -> None:
        self._responses = list(responses)
        self.sdk = sdk
        self.requests: list[LLMCallRequest] = []
        self.steps: list[AIManagedStepContext | None] = []
        self.research_questions: list[str] = []

    async def generate(self, request: LLMCallRequest) -> LLMCallResponse:
        self.requests.append(request)
        self.steps.append(current_managed_step_context())
        item = self._responses[len(self.requests) - 1]
        if callable(item):
            item = item(request)
        if isinstance(item, Exception):
            raise item
        return item

    async def research(self, *, provider_id, model, question, before_request):
        if self.sdk is None:
            raise AssertionError("this provider does not implement research")
        self.research_questions.append(question)
        # 替身固定按 deepseek 隔离协议转发；客户端的 provider 归属由 profile 决定。
        return await research_with_supplier(
            self.sdk,
            provider_id="deepseek",
            model="deepseek-v4-flash",
            question=question,
            before_request=before_request,
        )


def _scripted_client(responses, sdk=None) -> tuple[LLMClient, ScriptedProvider]:
    client = LLMClient()
    provider = ScriptedProvider(responses, sdk=sdk)
    client._provider = provider  # type: ignore[assignment]
    return client, provider


async def _lookup(name: str) -> str:
    """Read a named character's authorized evidence."""
    return "证据：甲在城外"


@pytest.mark.asyncio
async def test_agent_model_requests_are_metered_once_in_envelope_and_agent_budget():
    client, provider = _scripted_client([_tool_turn(), _answer_turn()])
    ledger = _agent_ledger()
    budget = AgentRunBudget()
    checkpoints = []

    async def checkpoint(value):
        checkpoints.append(value)

    with ai_run_scope(ledger):
        result = await run_project_agent(
            client,
            LLMCallRequest(messages=[LLMMessage(role="user", content="甲在哪里？")]),
            tools=[Tool(_lookup, name="lookup")],
            deps=None,
            output_type=Answer,
            budget=budget,
            input_limit=8000,
            checkpoint=checkpoint,
            capability_id="assistant.turn",
        )

    assert result.output.answer == "甲在城外"
    assert len(provider.requests) == 2
    envelope = ledger.snapshot()
    assert envelope.requests_started == 2 and envelope.requests_settled == 2
    assert envelope.requests_unknown == 0 and envelope.usage.total_tokens == 38
    # 同一批 provider 请求在 AgentRunBudget 上也恰好各记一次。
    assert budget.requests == 2 and budget.tool_attempts == 2
    assert budget.prompt_tokens == 30 and budget.completion_tokens == 8
    assert [item["requests"] for item in checkpoints][0] == 1
    step = envelope.steps[0]
    assert [item.step_name for item in envelope.steps] == [AGENT_STEP_NAME]
    assert step.call_kind is AIStepCallKind.generate
    assert step.step_capability_id == "assistant.turn"
    assert step.requests_started == 2 and step.requests_settled == 2
    # profile 摘要来自真实 client 且按 allowlist 净化，只保留稳定身份字段。
    assert step.profile_summary["model"] == "deepseek-flash"
    assert "api_key" not in step.profile_summary
    assert [item.step_name for item in provider.steps] == [AGENT_STEP_NAME] * 2


@pytest.mark.asyncio
async def test_agent_run_requires_explicit_root_capability_under_an_active_run():
    client, provider = _scripted_client([_answer_turn()])
    ledger = _agent_ledger()
    with ai_run_scope(ledger), pytest.raises(AIManagedStepContextError):
        await run_project_agent(
            client,
            LLMCallRequest(messages=[LLMMessage(role="user", content="甲在哪里？")]),
            tools=[],
            deps=None,
            output_type=Answer,
            budget=AgentRunBudget(),
            input_limit=8000,
        )
    assert provider.requests == []
    assert ledger.snapshot().requests_started == 0


@pytest.mark.asyncio
async def test_agent_run_rejects_a_capability_that_is_not_the_run_root():
    client, provider = _scripted_client([_answer_turn()])
    ledger = _agent_ledger()
    budget = AgentRunBudget()
    with ai_run_scope(ledger), pytest.raises(AIRunIdentityError):
        await run_project_agent(
            client,
            LLMCallRequest(messages=[LLMMessage(role="user", content="甲在哪里？")]),
            tools=[],
            deps=None,
            output_type=Answer,
            budget=budget,
            input_limit=8000,
            capability_id="infrastructure.format_repair",
        )
    assert provider.requests == []
    assert budget.requests == 0
    assert ledger.snapshot().requests_started == 0


@pytest.mark.asyncio
async def test_tool_embedded_managed_step_joins_the_same_run():
    from infrastructure.llm.agent_step_harness import run_managed_generate

    client, provider = _scripted_client(
        [
            _tool_turn(name="search", arguments='{"query":"甲"}'),
            _evidence_turn(),
            _answer_turn(exclude=("search",)),
        ]
    )
    ledger = _agent_ledger()
    budget = AgentRunBudget()

    async def search(query: str) -> str:
        """Search authorized evidence through a managed deterministic step."""
        response = await run_managed_generate(
            client,
            LLMCallRequest(messages=[LLMMessage(role="user", content=query)]),
            step_name="assistant.evidence.search",
        )
        return response.content

    with ai_run_scope(ledger):
        result = await run_project_agent(
            client,
            LLMCallRequest(messages=[LLMMessage(role="user", content="甲在哪里？")]),
            tools=[Tool(search)],
            deps=None,
            output_type=Answer,
            budget=budget,
            input_limit=8000,
            capability_id="assistant.turn",
        )

    assert result.output.answer == "甲在城外"
    envelope = ledger.snapshot()
    # 信封覆盖同一 run 的全部 provider I/O：2 次模型请求 + 1 次工具内嵌受管 step。
    assert envelope.requests_started == 3
    assert budget.requests == 2
    assert {step.step_name: step.requests_started for step in envelope.steps} == {
        AGENT_STEP_NAME: 2,
        "assistant.evidence.search": 1,
    }
    tool_step = next(
        step for step in envelope.steps if step.step_name == "assistant.evidence.search"
    )
    # helper 省略 capability 时归属本 run 的 root。
    assert tool_step.step_capability_id == "assistant.turn"


@pytest.mark.asyncio
async def test_agent_output_retry_reserves_each_provider_call_once():
    client, provider = _scripted_client(
        [_answer_turn("重试前"), _answer_turn("甲在城外")]
    )
    ledger = _agent_ledger()
    budget = AgentRunBudget()

    def reject_first(value: Answer) -> Answer:
        if value.answer == "重试前":
            raise ModelRetry("请换一个答案")
        return value

    with ai_run_scope(ledger):
        result = await run_project_agent(
            client,
            LLMCallRequest(messages=[LLMMessage(role="user", content="甲在哪里？")]),
            tools=[],
            deps=None,
            output_type=Answer,
            budget=budget,
            input_limit=8000,
            output_validator=reject_first,
            capability_id="assistant.turn",
        )

    assert result.output.answer == "甲在城外"
    assert len(provider.requests) == 2
    assert ledger.snapshot().requests_started == 2
    assert ledger.snapshot().steps[0].requests_started == 2
    assert budget.requests == 2
    assert budget.prompt_tokens == 40 and budget.completion_tokens == 10


@pytest.mark.asyncio
async def test_research_sub_requests_join_the_agent_run(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(
        "infrastructure.llm.native_search.verified_native_search",
        lambda provider_id, model: "deepseek-responses-web-search-v1",
    )
    payload = {
        "output": [
            {"type": "web_search_call", "status": "completed"},
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": "水在标准大气压下的沸点约为 100 摄氏度。",
                        "annotations": [
                            {
                                "type": "url_citation",
                                "url": "https://example.org/facts",
                                "title": "来源",
                            }
                        ],
                    }
                ],
            },
        ],
        "usage": {"input_tokens": 12, "output_tokens": 5, "total_tokens": 17},
    }

    class Responses:
        async def create(self, **kwargs):
            return SimpleNamespace(model_dump=lambda: payload)

    client, provider = _scripted_client(
        [
            _tool_turn(name="research", arguments='{"question":"水的沸点"}'),
            _answer_turn(exclude=("research",)),
        ],
        sdk=SimpleNamespace(responses=Responses()),
    )
    ledger = _agent_ledger()
    budget = AgentRunBudget()

    async def research(question: str) -> str:
        """查证现实通用事实。"""

        async def reserve():
            budget.reserve(requests=1, web=1)

        result = await client.research(question, before_request=reserve)
        return result.answer

    with ai_run_scope(ledger):
        result = await run_project_agent(
            client,
            LLMCallRequest(messages=[LLMMessage(role="user", content="查证沸点")]),
            tools=[Tool(research)],
            deps=None,
            output_type=Answer,
            budget=budget,
            input_limit=8000,
            capability_id="assistant.turn",
        )

    assert result.output.answer == "甲在城外"
    envelope = ledger.snapshot()
    assert envelope.requests_started == 3
    assert {step.step_name for step in envelope.steps} == {
        AGENT_STEP_NAME,
        "infrastructure.native_search",
    }
    search_step = next(
        step
        for step in envelope.steps
        if step.step_name == "infrastructure.native_search"
    )
    assert search_step.call_kind is AIStepCallKind.research
    assert search_step.requests_started == 1 and search_step.requests_settled == 1
    assert provider.research_questions == ["水的沸点"]
    # research 既有的 requests/web_requests 记账语义保留。
    assert budget.requests == 3 and budget.web_requests == 1


@pytest.mark.asyncio
async def test_resumed_agent_keeps_the_same_run_counts_and_deadline():
    request = LLMCallRequest(messages=[LLMMessage(role="user", content="甲在哪里？")])
    ledger = _agent_ledger()
    deadline = ledger.snapshot().deadline_at
    budget = AgentRunBudget()
    states = []

    async def save_state(value):
        states.append(value)

    interrupted, _ = _scripted_client(
        [_tool_turn(), ConnectionError("synthetic interruption")]
    )
    with ai_run_scope(ledger), pytest.raises(ConnectionError):
        await run_project_agent(
            interrupted,
            request,
            tools=[Tool(_lookup, name="lookup")],
            deps=None,
            output_type=Answer,
            budget=budget,
            input_limit=8000,
            state_checkpoint=save_state,
            capability_id="assistant.turn",
        )

    envelope = ledger.snapshot()
    assert envelope.requests_started == 2 and envelope.requests_unknown == 1
    assert budget.requests == 2

    restored = AgentRunBudget.model_validate(budget.model_dump(mode="json"))
    resumed, _ = _scripted_client([_answer_turn()])
    with ai_run_scope(ledger):
        result = await run_project_agent(
            resumed,
            request,
            tools=[Tool(_lookup, name="lookup")],
            deps=None,
            output_type=Answer,
            budget=restored,
            input_limit=8000,
            state=states[-1],
            capability_id="assistant.turn",
        )

    assert result.output.answer == "甲在城外"
    # manual resume / 重排继续同一 run：计数累加、deadline 与预算起点都不重置。
    assert restored.requests == 3 and restored.started_at == budget.started_at
    resumed_envelope = ledger.snapshot()
    assert resumed_envelope.requests_started == 3
    assert resumed_envelope.requests_unknown == 1
    assert resumed_envelope.deadline_at == deadline


@pytest.mark.asyncio
async def test_agent_without_an_active_run_keeps_previous_accounting():
    seen = []

    class StepAwareClient(ScriptedClient):
        async def generate(self, request, *, transport_retries):
            seen.append(current_managed_step_context())
            return await super().generate(
                request, transport_retries=transport_retries
            )

    budget = AgentRunBudget()
    checkpoints = []

    async def checkpoint(value):
        checkpoints.append(value)

    result = await run_project_agent(
        StepAwareClient(),
        LLMCallRequest(messages=[LLMMessage(role="user", content="甲在哪里？")]),
        tools=[Tool(_lookup, name="lookup")],
        deps=None,
        output_type=Answer,
        budget=budget,
        input_limit=8000,
        checkpoint=checkpoint,
    )

    assert result.output.answer == "甲在城外"
    assert current_ai_run_envelope() is None
    assert budget.requests == 2 and budget.tool_attempts == 2
    assert budget.prompt_tokens == 30 and budget.completion_tokens == 8
    assert checkpoints[0]["requests"] == 1
    assert [item.step_name for item in seen] == [AGENT_STEP_NAME] * 2
    assert all(item.capability_id is None for item in seen)


@pytest.mark.asyncio
async def test_workflow_meter_and_agent_budget_never_reserve_the_same_request_twice():
    client, provider = _scripted_client([_tool_turn(), _answer_turn()])
    budget = AgentRunBudget()
    saved = []

    async def checkpoint(value):
        saved.append(value)

    with workflow_budget(budget, checkpoint):
        result = await run_project_agent(
            client,
            LLMCallRequest(messages=[LLMMessage(role="user", content="甲在哪里？")]),
            tools=[Tool(_lookup, name="lookup")],
            deps=None,
            output_type=Answer,
            budget=budget,
            input_limit=8000,
            checkpoint=checkpoint,
        )

    assert result.output.answer == "甲在城外"
    assert len(provider.requests) == 2
    # 互斥前同一请求会同时被 ProjectGatewayModel 与 provider_request 各记一次。
    assert budget.requests == 2 and budget.tool_attempts == 2
    assert budget.prompt_tokens == 30 and budget.completion_tokens == 8
    assert [item["requests"] for item in saved] == [0, 1, 1, 1, 1, 2, 2, 2]


@pytest.mark.asyncio
async def test_nested_workflow_meter_owns_the_model_request():
    client, provider = _scripted_client([_tool_turn(), _answer_turn()])
    agent_budget = AgentRunBudget()
    tool_budget = AgentRunBudget()
    saved = []

    async def checkpoint(value):
        saved.append(value)

    with workflow_budget(tool_budget, checkpoint):
        await run_project_agent(
            client,
            LLMCallRequest(messages=[LLMMessage(role="user", content="甲在哪里？")]),
            tools=[Tool(_lookup, name="lookup")],
            deps=None,
            output_type=Answer,
            budget=agent_budget,
            input_limit=8000,
            checkpoint=checkpoint,
        )

    assert len(provider.requests) == 2
    # budgeted_tool 的既定语义：工具内准备的模型调用记在工具账本上，不重复也无需虚增。
    assert tool_budget.requests == 2 and tool_budget.prompt_tokens == 30
    assert agent_budget.requests == 0 and agent_budget.prompt_tokens == 0
    assert agent_budget.tool_attempts == 2
    # 最后一次落盘来自 AgentRunBudget（只累计工具尝试），请求数保持 0。
    assert saved[-1]["requests"] == 0 and saved[-1]["tool_attempts"] == 2


@pytest.mark.asyncio
async def test_envelope_refusal_releases_the_agent_budget_request_reservation():
    """信封在 provider I/O 前拒绝：网关的兼容"已请求"预留必须回滚。"""
    from infrastructure.llm.workflow_budget import AIRunBudgetExceededError

    client, provider = _scripted_client([_tool_turn(), _answer_turn()])
    # 额度只够第一次请求：第二次请求的拒绝发生在信封内、provider I/O 前。
    ledger = _agent_ledger(request_limit=1)
    budget = AgentRunBudget()

    with ai_run_scope(ledger), pytest.raises(AIRunBudgetExceededError):
        await run_project_agent(
            client,
            LLMCallRequest(messages=[LLMMessage(role="user", content="甲在哪里？")]),
            tools=[Tool(_lookup, name="lookup")],
            deps=None,
            output_type=Answer,
            budget=budget,
            input_limit=8000,
            capability_id="assistant.turn",
        )

    assert len(provider.requests) == 1
    envelope = ledger.snapshot()
    assert envelope.requests_started == 1
    # 拒绝后兼容账本回到"只有第一次成功请求"的状态，没有幽灵计数。
    assert budget.requests == 1
    assert budget.pending_usage == 0


@pytest.mark.asyncio
async def test_stream_envelope_refusal_releases_the_budget_before_any_io():
    """建流被信封拒绝：流式请求的兼容预留同样回滚，不产生未知用量。"""
    from infrastructure.llm.workflow_budget import AIRunBudgetExceededError

    client, provider = _scripted_client([])
    ledger = _agent_ledger(request_limit=0)
    budget = AgentRunBudget()
    model = ProjectGatewayModel(client, LLMCallRequest(), budget, input_limit=8000)
    with ai_run_scope(ledger):
        with pytest.raises(AIRunBudgetExceededError):
            async with model.request_stream(
                [ModelRequest([UserPromptPart("hi")])], None, ModelRequestParameters()
            ) as stream:
                async for _event in stream:
                    pass

    assert provider.requests == []
    assert budget.requests == 0
    assert budget.pending_usage == 0
    assert ledger.snapshot().requests_started == 0
