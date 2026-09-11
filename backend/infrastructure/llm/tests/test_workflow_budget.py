from types import SimpleNamespace

import pytest
from pydantic_ai import RunContext, Tool

from infrastructure.llm.agent_runtime import AgentRunBudget
from infrastructure.llm.schemas import LLMUsage
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
