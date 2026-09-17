from types import SimpleNamespace

import pytest
from pydantic import BaseModel
from pydantic_ai import RunContext, Tool

from infrastructure.llm.agent_runtime import AgentRunBudget, run_project_agent
from infrastructure.llm.client import LLMClient
from infrastructure.llm.schemas import (
    LLMCallRequest,
    LLMCallResponse,
    LLMMessage,
    LLMToolCall,
    LLMUsage,
)
from infrastructure.llm.workflow_budget import (
    budgeted_tool,
    current_workflow_budget,
    workflow_budget,
)


@pytest.mark.asyncio
async def test_tool_preparation_and_nested_workflow_share_one_budget_and_restore_scope():
    saved = []

    async def checkpoint(values):
        saved.append(values)

    async def read(ctx: RunContext, query: str) -> dict:
        """Read a scoped value."""
        meter = current_workflow_budget()
        await meter.before_request()
        await meter.completed(LLMUsage(prompt_tokens=5, completion_tokens=2))
        with workflow_budget(ctx.deps.budget, checkpoint):
            inner = current_workflow_budget()
            await inner.before_request()
            await inner.completed(LLMUsage(prompt_tokens=3, completion_tokens=1))
        assert current_workflow_budget() is meter
        return {"query": query}

    wrapped = budgeted_tool(read)
    assert (
        Tool(wrapped).function_schema.json_schema
        == Tool(read).function_schema.json_schema
    )
    budget = AgentRunBudget()
    result = await wrapped(
        SimpleNamespace(deps=SimpleNamespace(budget=budget, checkpoint=checkpoint)),
        "query",
    )
    assert result == {"query": "query"}
    assert (
        budget.requests == 2
        and budget.prompt_tokens == 8
        and budget.completion_tokens == 3
    )
    assert current_workflow_budget() is None
    assert [item["requests"] for item in saved] == [1, 1, 2, 2]


class _Answer(BaseModel):
    answer: str


class _ScriptedProvider:
    """最小 provider 替身：计量由真实 LLMClient 的 workflow meter 承担。"""

    name = "scripted"

    def __init__(self) -> None:
        self.requests: list[LLMCallRequest] = []

    async def generate(self, request: LLMCallRequest) -> LLMCallResponse:
        self.requests.append(request)
        if len(self.requests) == 1:
            return LLMCallResponse(
                tool_calls=[
                    LLMToolCall(id="read-1", name="lookup", arguments='{"name":"甲"}')
                ],
                usage=LLMUsage(prompt_tokens=10, completion_tokens=3, total_tokens=13),
            )
        output = next(tool for tool in request.tools if tool.name != "lookup")
        return LLMCallResponse(
            tool_calls=[
                LLMToolCall(
                    id="answer-1", name=output.name, arguments='{"answer":"甲在城外"}'
                )
            ],
            usage=LLMUsage(prompt_tokens=20, completion_tokens=5, total_tokens=25),
        )


@pytest.mark.asyncio
async def test_budgeted_tool_charges_an_embedded_agent_run_once():
    client = LLMClient()
    provider = _ScriptedProvider()
    client._provider = provider  # type: ignore[assignment]
    budget = AgentRunBudget()
    saved = []

    async def checkpoint(values):
        saved.append(values)

    async def lookup(name: str) -> str:
        """Read a named character's authorized evidence."""
        return "证据：甲在城外"

    async def plan(ctx: RunContext, query: str) -> dict:
        """Plan through the bounded agent loop."""
        result = await run_project_agent(
            ctx.deps.client,
            LLMCallRequest(messages=[LLMMessage(role="user", content=query)]),
            tools=[Tool(lookup)],
            deps=None,
            output_type=_Answer,
            budget=ctx.deps.budget,
            input_limit=8000,
            checkpoint=ctx.deps.checkpoint,
        )
        return {"answer": result.output.answer}

    wrapped = budgeted_tool(plan)
    result = await wrapped(
        SimpleNamespace(
            deps=SimpleNamespace(
                client=client, budget=budget, checkpoint=checkpoint
            )
        ),
        "甲在哪里？",
    )

    assert result == {"answer": "甲在城外"}
    assert len(provider.requests) == 2
    # budgeted_tool 的 meter 与 ProjectGatewayModel 不会对同一次请求各记一次。
    assert (
        budget.requests == 2
        and budget.prompt_tokens == 30
        and budget.completion_tokens == 8
    )
    assert current_workflow_budget() is None
    assert [item["requests"] for item in saved][-1] == 2


@pytest.mark.asyncio
async def test_workflow_budget_checkpoint_failure_releases_pending_request() -> None:
    """P1-4：checkpoint 失败的请求没有发出 provider I/O，不得留下幻影计数。"""
    from infrastructure.llm.agent_runtime import AgentRunBudget
    from infrastructure.llm.workflow_budget import WorkflowBudget

    async def failing_checkpoint(_payload):
        raise RuntimeError("checkpoint down")

    budget = AgentRunBudget(mode="author")
    workflow = WorkflowBudget(budget, failing_checkpoint)
    with pytest.raises(RuntimeError, match="checkpoint down"):
        await workflow.before_request()
    assert budget.requests == 0
    assert budget.pending_usage == 0
    assert budget.usage_complete is True
