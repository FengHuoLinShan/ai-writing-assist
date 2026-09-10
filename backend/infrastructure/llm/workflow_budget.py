"""Meter existing deterministic review workflows without duplicating their retries."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import wraps
from typing import Any, get_type_hints

from infrastructure.llm.agent_runtime import AgentRunBudget


@dataclass
class WorkflowBudget:
    budget: AgentRunBudget
    checkpoint: Any
    future_requests: int = 0
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def before_request(self):
        async with self.lock:
            self.budget.reserve(requests=1, future_requests=self.future_requests)
            await self.checkpoint(self.budget.model_dump(mode="json"))

    async def completed(self, usage):
        async with self.lock:
            self.budget.add_usage(usage)
            await self.checkpoint(self.budget.model_dump(mode="json"))


_CURRENT: ContextVar[WorkflowBudget | None] = ContextVar(
    "review_workflow_budget", default=None
)


def current_workflow_budget() -> WorkflowBudget | None:
    return _CURRENT.get()


def budgeted_tool(function):
    """Charge model calls made while preparing/reading a tool, not its caller."""

    @wraps(function)
    async def run(ctx, *args, **kwargs):
        deps = ctx.deps
        with workflow_budget(
            deps.budget,
            deps.checkpoint,
            future_requests=getattr(deps, "final_requests", 1),
        ):
            return await function(ctx, *args, **kwargs)

    run.__annotations__ = get_type_hints(function)
    return run


@contextmanager
def workflow_budget(budget: AgentRunBudget, checkpoint, *, future_requests=0):
    token = _CURRENT.set(WorkflowBudget(budget, checkpoint, future_requests))
    try:
        yield _CURRENT.get()
    finally:
        _CURRENT.reset(token)
