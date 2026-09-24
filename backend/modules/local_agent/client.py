"""Duck-typed project client backed by a paired local CLI."""

from __future__ import annotations

from collections.abc import AsyncIterator

from infrastructure.llm.agent_runtime import AgentRunBudget
from infrastructure.llm.schemas import (
    LLMCallRequest,
    LLMCallResponse,
    LLMStreamChunk,
    LLMUsage,
)
from modules.local_agent.runtime import run_local_agent


class LocalCLIClient:
    is_local_agent = True

    def __init__(
        self,
        db,
        *,
        task_id: str,
        novel_id: str,
        owner_id: str,
        device_id: str,
        kind: str,
        budget: AgentRunBudget,
        checkpoint,
    ) -> None:
        self.db = db
        self.task_id = task_id
        self.novel_id = novel_id
        self.owner_id = owner_id
        self.device_id = device_id
        self.kind = kind
        self.budget = budget
        self.checkpoint = checkpoint
        self.model_name = f"local-cli/{kind}"

    async def run_agent(
        self,
        request,
        *,
        tools,
        deps,
        output_type,
        output_validator,
        budget,
        checkpoint,
        capability_id=None,
    ):
        return await run_local_agent(
            self.db,
            task_id=self.task_id,
            novel_id=self.novel_id,
            owner_id=self.owner_id,
            device_id=self.device_id,
            cli=self.kind,
            messages=request.messages,
            tools=tools,
            deps=deps,
            output_type=output_type,
            output_validator=output_validator,
            budget=budget,
            checkpoint=checkpoint,
            capability_id=capability_id,
        )

    async def generate(self, request: LLMCallRequest, **_kwargs) -> LLMCallResponse:
        result = await self.run_agent(
            request,
            tools=[],
            deps=None,
            output_type=str,
            output_validator=None,
            budget=self.budget,
            checkpoint=self.checkpoint,
        )
        return LLMCallResponse(
            content=result.output,
            finish_reason="stop",
            usage=LLMUsage(),
            model=self.model_name,
            provider=self.kind,
            raw={"usage_unknown": True},
        )

    async def generate_structured(self, request, schema, **_kwargs):
        result = await self.run_agent(
            request,
            tools=[],
            deps=None,
            output_type=schema,
            output_validator=None,
            budget=self.budget,
            checkpoint=self.checkpoint,
        )
        return result.output

    async def generate_stream(
        self, request: LLMCallRequest, **_kwargs
    ) -> AsyncIterator[LLMStreamChunk]:
        # The worker owns one AsyncSession; a concurrent producer would race its
        # transaction/checkpoint writes. Relay the finished text in this task.
        response = await self.generate(request)
        yield LLMStreamChunk(content=response.content)
        yield LLMStreamChunk(finish_reason="stop")

    async def close(self) -> None:
        return None
