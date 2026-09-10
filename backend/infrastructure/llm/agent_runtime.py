"""Bounded PydanticAI execution through the project-owned LLM gateway (ADR-0023)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic_ai import Agent, Tool
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.messages import (
    ModelMessage,
    ModelMessagesTypeAdapter,
    ModelRequest,
    ModelResponse,
    ModelResponseStreamEvent,
    RetryPromptPart,
    SystemPromptPart,
    TextPart,
    ThinkingPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models import Model, ModelRequestParameters, StreamedResponse
from pydantic_ai.settings import ModelSettings
from pydantic_ai.usage import RequestUsage, UsageLimits

from infrastructure.llm.client import LLMClient
from infrastructure.llm.schemas import (
    LLMCallRequest,
    LLMCallResponse,
    LLMMessage,
    LLMStreamChunk,
    LLMToolCall,
    LLMToolDefinition,
    LLMUsage,
)
from infrastructure.llm.token_estimation import estimate_token_count


class AgentBudgetError(ValueError):
    """The saved run needs explicit continuation, not automatic replay."""


class AgentRunBudget(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["author", "rp", "background"] = "author"
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    requests: int = Field(default=0, ge=0)
    tool_attempts: int = Field(default=0, ge=0)
    web_requests: int = Field(default=0, ge=0)
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    usage_complete: bool = True
    pending_usage: int = Field(default=0, ge=0)
    usage_unknown: bool = False

    @model_validator(mode="before")
    @classmethod
    def preserve_legacy_unknown_usage(cls, value):
        if (
            isinstance(value, dict)
            and "pending_usage" not in value
            and value.get("usage_complete") is False
        ):
            return {**value, "usage_unknown": True}
        return value

    @property
    def limits(self) -> tuple[int, int, int]:
        return {"author": (12, 32, 4), "rp": (8, 24, 2), "background": (6, 16, 2)}[
            self.mode
        ]

    @property
    def remaining_seconds(self) -> float:
        start = self.started_at
        if start.tzinfo is None:
            start = start.replace(tzinfo=UTC)
        return max(0, (start + timedelta(minutes=30) - datetime.now(UTC)).total_seconds())

    def reserve(
        self, *, requests: int = 0, tools: int = 0, web: int = 0, future_requests: int = 0
    ) -> None:
        if min(requests, tools, web, future_requests) < 0:
            raise ValueError("Budget reservations must be nonnegative")
        limits = self.limits
        if self.remaining_seconds <= 0 or any(
            value > limit
            for value, limit in zip(
                (
                    self.requests + requests + future_requests,
                    self.tool_attempts + tools,
                    self.web_requests + web,
                ),
                limits,
                strict=True,
            )
        ):
            raise AgentBudgetError("本次查证已达到预算，请查看已有结果后决定是否继续。")
        self.requests += requests
        self.pending_usage += requests
        if requests:
            self.usage_complete = False
        self.tool_attempts += tools
        self.web_requests += web

    def add_usage(self, usage: LLMUsage | None, *, requests: int = 1) -> None:
        self.pending_usage = max(0, self.pending_usage - requests)
        if usage is None or usage.total_tokens == 0:
            self.usage_unknown = True
        self.usage_complete = not self.pending_usage and not self.usage_unknown
        if usage is not None:
            self.prompt_tokens += usage.prompt_tokens
            self.completion_tokens += usage.completion_tokens


BudgetCheckpoint = Callable[[dict[str, Any]], Awaitable[None]]
_HISTORY_VERSION = "pydantic-ai-2.42.0"


def _usage(value: LLMUsage) -> RequestUsage:
    return RequestUsage(
        input_tokens=value.prompt_tokens, output_tokens=value.completion_tokens
    )


def _history(messages: list[LLMMessage]) -> list[ModelMessage]:
    result: list[ModelMessage] = []
    for message in messages:
        if message.role == "assistant":
            parts: list[Any] = []
            if message.reasoning_content:
                parts.append(ThinkingPart(message.reasoning_content))
            if message.content:
                parts.append(TextPart(message.content))
            parts.extend(
                ToolCallPart(c.name, c.arguments, c.id) for c in message.tool_calls
            )
            result.append(ModelResponse(parts))
        elif message.role == "tool":
            result.append(
                ModelRequest(
                    [ToolReturnPart("result", message.content, message.tool_call_id)]
                )
            )
        else:
            part = (
                SystemPromptPart(message.content)
                if message.role == "system"
                else UserPromptPart(message.content)
            )
            result.append(ModelRequest([part]))
    return result


class ProjectGatewayModel(Model):
    """Adapter, not a second provider or credential owner."""

    def __init__(
        self,
        client: LLMClient,
        template: LLMCallRequest,
        budget: AgentRunBudget,
        *,
        input_limit: int,
        checkpoint: BudgetCheckpoint | None = None,
        state_checkpoint: BudgetCheckpoint | None = None,
        future_requests: int = 0,
    ) -> None:
        super().__init__(
            profile={"supports_tools": True, "default_structured_output_mode": "tool"}
        )
        self.client = client
        self.template = template
        self.budget = budget
        self.input_limit = input_limit
        self.checkpoint = checkpoint
        self.state_checkpoint = state_checkpoint
        self.future_requests = future_requests

    @property
    def model_name(self) -> str:
        return self.client.model_name

    @property
    def system(self) -> str:
        return "novelcraft"

    async def save_budget(self) -> None:
        if self.checkpoint is not None:
            await self.checkpoint(self.budget.model_dump(mode="json"))

    async def save_history(self, messages: list[ModelMessage]) -> None:
        if self.state_checkpoint is not None:
            await self.state_checkpoint(
                {
                    "version": _HISTORY_VERSION,
                    "messages": ModelMessagesTypeAdapter.dump_python(
                        messages, mode="json"
                    ),
                }
            )

    def _request(
        self, messages: list[ModelMessage], params: ModelRequestParameters
    ) -> LLMCallRequest:
        if params.native_tools:
            raise ValueError("Native tools must use the isolated project research entry")
        converted: list[LLMMessage] = []
        instructions = self._get_instruction_parts(messages, params)
        if instructions:
            converted.append(
                LLMMessage(
                    role="system", content="\n\n".join(p.content for p in instructions)
                )
            )
        for message in messages:
            if isinstance(message, ModelResponse):
                converted.append(
                    LLMMessage(
                        role="assistant",
                        content="".join(
                            p.content for p in message.parts if isinstance(p, TextPart)
                        ),
                        reasoning_content="".join(
                            p.content
                            for p in message.parts
                            if isinstance(p, ThinkingPart)
                        )
                        or None,
                        tool_calls=[
                            LLMToolCall(
                                id=p.tool_call_id,
                                name=p.tool_name,
                                arguments=p.args_as_json_str(),
                            )
                            for p in message.parts
                            if isinstance(p, ToolCallPart)
                        ],
                    )
                )
            else:
                for part in message.parts:
                    if isinstance(part, (SystemPromptPart, UserPromptPart)):
                        if not isinstance(part.content, str):
                            raise ValueError(
                                "Project agents currently accept text content only"
                            )
                        converted.append(
                            LLMMessage(
                                role="system"
                                if isinstance(part, SystemPromptPart)
                                else "user",
                                content=part.content,
                            )
                        )
                    elif isinstance(part, ToolReturnPart):
                        converted.append(
                            LLMMessage(
                                role="tool",
                                tool_call_id=part.tool_call_id,
                                content=part.model_response_str(),
                            )
                        )
                    elif isinstance(part, RetryPromptPart):
                        converted.append(
                            LLMMessage(
                                role="tool" if part.tool_name else "user",
                                tool_call_id=part.tool_call_id
                                if part.tool_name
                                else None,
                                content=part.model_response(),
                            )
                        )
                    else:
                        raise ValueError("Unsupported project agent history part")
        tools = [
            LLMToolDefinition(
                name=t.name,
                description=t.description or "",
                parameters=t.parameters_json_schema,
            )
            for t in [*params.function_tools, *params.output_tools]
        ]
        payload = self.template.model_dump(
            exclude={"messages", "tools", "tool_choice", "response_format"}
        )
        request = LLMCallRequest(
            **payload,
            messages=converted,
            tools=tools,
            tool_choice="auto",
        )
        size = estimate_token_count(
            json.dumps([m.provider_message() for m in converted], ensure_ascii=False)
            + json.dumps([t.model_dump() for t in tools], ensure_ascii=False),
            model=self.model_name,
        )
        if size > self.input_limit:
            raise AgentBudgetError("本轮资料超过已验证上下文范围，请缩小范围后继续。")
        return request

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        _, params = self.prepare_request(model_settings, model_request_parameters)
        request = self._request(messages, params)
        self.budget.reserve(requests=1, future_requests=self.future_requests)
        await self.save_budget()
        await self.save_history(messages)
        response = await self.client.generate(request, transport_retries=False)
        self.budget.add_usage(response.usage)
        # Count all proposed calls, including invalid/unknown calls, before execution.
        try:
            self.budget.reserve(tools=len(response.tool_calls))
        finally:
            await self.save_budget()
        return self._response(response)

    def _response(self, response: LLMCallResponse) -> ModelResponse:
        parts: list[Any] = []
        if response.reasoning_content:
            parts.append(ThinkingPart(response.reasoning_content))
        if response.content:
            parts.append(TextPart(response.content))
        parts.extend(ToolCallPart(c.name, c.arguments, c.id) for c in response.tool_calls)
        return ModelResponse(
            parts,
            model_name=self.model_name,
            usage=_usage(response.usage),
            provider_name="novelcraft",
            finish_reason="tool_call"
            if response.tool_calls
            else "length"
            if response.finish_reason == "length"
            else "stop",
        )

    @asynccontextmanager
    async def request_stream(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
        run_context=None,
    ):
        _, params = self.prepare_request(model_settings, model_request_parameters)
        request = self._request(messages, params)
        self.budget.reserve(requests=1, future_requests=self.future_requests)
        await self.save_budget()
        await self.save_history(messages)
        stream = self.client.generate_stream(request, transport_retries=False)
        try:
            yield GatewayStream(params, self, stream)
        finally:
            await stream.aclose()


class GatewayStream(StreamedResponse):
    def __init__(
        self,
        params: ModelRequestParameters,
        model: ProjectGatewayModel,
        stream: AsyncIterator[LLMStreamChunk],
    ):
        super().__init__(params)
        self.model = model
        self.stream = stream
        self._timestamp = datetime.now(UTC)

    @property
    def model_name(self) -> str:
        return self.model.model_name

    @property
    def provider_name(self) -> str:
        return "novelcraft"

    @property
    def provider_url(self) -> None:
        return None

    @property
    def timestamp(self) -> datetime:
        return self._timestamp

    async def _get_event_iterator(self) -> AsyncIterator[ModelResponseStreamEvent]:
        seen: set[int] = set()
        final_usage = None
        try:
            async for chunk in self.stream:
                if chunk.usage is not None:
                    final_usage = chunk.usage
                    self._usage = _usage(chunk.usage)
                if chunk.reasoning_content:
                    for event in self._parts_manager.handle_thinking_delta(
                        vendor_part_id="thinking", content=chunk.reasoning_content
                    ):
                        yield event
                if chunk.content:
                    for event in self._parts_manager.handle_text_delta(
                        vendor_part_id="text", content=chunk.content
                    ):
                        yield event
                for delta in chunk.tool_deltas:
                    if delta.index not in seen:
                        self.model.budget.reserve(tools=1)
                        seen.add(delta.index)
                        await self.model.save_budget()
                    event = self._parts_manager.handle_tool_call_delta(
                        vendor_part_id=delta.index,
                        tool_name=delta.name,
                        args=delta.arguments,
                        tool_call_id=delta.id,
                    )
                    if event is not None:
                        yield event
                if chunk.finish_reason:
                    self.finish_reason = (
                        "tool_call"
                        if chunk.finish_reason == "tool_calls"
                        else "length"
                        if chunk.finish_reason == "length"
                        else "stop"
                    )
        finally:
            self.model.budget.add_usage(final_usage)
            if not asyncio.current_task().cancelling():
                await self.model.save_budget()

    async def close_stream(self) -> None:
        await self.stream.aclose()


async def run_project_agent(
    client: LLMClient,
    request: LLMCallRequest,
    *,
    tools: list[Tool],
    deps: Any,
    output_type: type = str,
    budget: AgentRunBudget,
    input_limit: int,
    checkpoint: BudgetCheckpoint | None = None,
    state_checkpoint: BudgetCheckpoint | None = None,
    state: dict | None = None,
    future_requests: int = 0,
    output_validator=None,
):
    """Caller owns data/permissions and client lifetime; no automatic run replay."""
    model = ProjectGatewayModel(
        client,
        request,
        budget,
        input_limit=input_limit,
        checkpoint=checkpoint,
        state_checkpoint=state_checkpoint,
        future_requests=future_requests,
    )
    agent = Agent(model=model, tools=tools, output_type=output_type, retries=1)
    if output_validator is not None:
        agent.output_validator(output_validator)
    if state is not None:
        if state.get("version") != _HISTORY_VERSION:
            raise ValueError("Agent history version changed; start a new run")
        history = ModelMessagesTypeAdapter.validate_python(state["messages"])
    else:
        history = _history(request.messages)
    async with asyncio.timeout(budget.remaining_seconds):
        try:
            return await agent.run(
                message_history=history,
                deps=deps,
                usage_limits=UsageLimits(request_limit=budget.limits[0]),
                infer_name=False,
            )
        except UsageLimitExceeded as error:
            raise AgentBudgetError(
                "本轮已达到执行上限，请查看过程资料后决定是否继续"
            ) from error
