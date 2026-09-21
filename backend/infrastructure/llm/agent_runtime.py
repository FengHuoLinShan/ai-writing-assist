"""Bounded PydanticAI execution through the project-owned LLM gateway (ADR-0023)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator, Mapping
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal

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
    AIStepCallKind,
    LLMCallRequest,
    LLMCallResponse,
    LLMMessage,
    LLMStreamChunk,
    LLMToolCall,
    LLMToolDefinition,
    LLMUsage,
)
from infrastructure.llm.token_estimation import estimate_token_count

if TYPE_CHECKING:
    from infrastructure.llm.workflow_budget import AIManagedStepContext

AGENT_STEP_NAME = "infrastructure.agent_loop"
"""有界 Agent 自身模型回合的稳定 step 名；不携带请求序数或动态后缀。"""


def _workflow_meter_owns_provider_request() -> bool:
    """本次 provider 请求是否已由外层 WorkflowBudget 承担预留与用量。

    `LLMClient.generate()` 的 provider_request 闭包在存在 WorkflowBudget 时会先
    `before_request()` 预留一次；`budgeted_tool` 的既定语义是“工具内准备的模型调用记在
    工具账本上”。因此内层显式 meter 存在时由它计量，AgentRunBudget 不再对同一次 provider
    I/O 预留或落定用量，一次请求只在一个 meter 上记一次。
    """
    from infrastructure.llm.workflow_budget import current_workflow_budget

    return current_workflow_budget() is not None


def _require_root_capability(capability_id: str | None) -> None:
    """活动运行信封下必须显式声明本 run 的 root capability。

    声明早于任何预算预留与 provider I/O：缺失或与本 run root 不一致时失败关闭，
    不把 Agent 循环静默归属到信封 root。
    """
    from infrastructure.llm.workflow_budget import (
        AIManagedStepContextError,
        AIRunIdentityError,
        current_ai_run_envelope,
    )

    envelope = current_ai_run_envelope()
    if envelope is None:
        return
    if capability_id is None:
        raise AIManagedStepContextError(
            "run_project_agent 在活动运行信封下必须显式声明 root capability"
        )
    if capability_id != envelope.root_capability_id:
        raise AIRunIdentityError(
            f"run_project_agent 声明的 capability {capability_id!r} 不是本 run 的 root",
            run_id=envelope.run_id,
        )


class AgentBudgetError(ValueError):
    """The saved run needs explicit continuation, not automatic replay."""


@dataclass
class AgentAllocation:
    """A member's slice of the root ledger, never an additional budget."""

    work_item_id: str
    request_limit: int = 4
    requests: int = 0
    final_reserve: int = 6
    prompt_tokens: int = 0
    completion_tokens: int = 0
    usage_unknown: bool = False


_ALLOCATION: ContextVar[AgentAllocation | None] = ContextVar(
    "agent_allocation", default=None
)


@contextmanager
def agent_allocation(allocation: AgentAllocation):
    token = _ALLOCATION.set(allocation)
    try:
        yield allocation
    finally:
        _ALLOCATION.reset(token)


class AgentRunBudget(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["author", "rp", "background"] = "author"
    policy_version: Literal["legacy_v1", "team_v1"] = "legacy_v1"
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
        if self.policy_version == "team_v1":
            return (30, 48, 4)
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
        allocation = _ALLOCATION.get()
        if allocation:
            future_requests = max(future_requests, allocation.final_reserve)
            if allocation.requests + requests > allocation.request_limit:
                raise AgentBudgetError(
                    "本项查证达到分配额度，保留其余专项与最终复核额度。"
                )
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
        if allocation:
            allocation.requests += requests
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
        if allocation := _ALLOCATION.get():
            if usage is None or not usage.total_tokens:
                allocation.usage_unknown = True
            else:
                allocation.prompt_tokens += usage.prompt_tokens
                allocation.completion_tokens += usage.completion_tokens

    def release_pending_request(self, *, requests: int = 1) -> None:
        """撤销一次尚未发出 provider I/O 的请求预留。

        活动运行信封在 provider I/O 前拒绝时，兼容账本同样不得留下"已请求"
        计数；工具数与 web 子预算不受影响。
        """
        if requests < 0:
            raise ValueError("Budget releases must be nonnegative")
        self.requests = max(0, self.requests - requests)
        if allocation := _ALLOCATION.get():
            allocation.requests = max(0, allocation.requests - requests)
        self.pending_usage = max(0, self.pending_usage - requests)
        self.usage_complete = not self.pending_usage and not self.usage_unknown


BudgetCheckpoint = Callable[[dict[str, Any]], Awaitable[None]]
_LEGACY_HISTORY_VERSION = "pydantic-ai-2.42.0"
_HISTORY_VERSION = "pydantic-ai-2.42.0/tool-identity-v2"


def _usage(value: LLMUsage) -> RequestUsage:
    return RequestUsage(
        input_tokens=value.prompt_tokens, output_tokens=value.completion_tokens
    )


def _history(messages: list[LLMMessage]) -> list[ModelMessage]:
    result: list[ModelMessage] = []
    tool_names: dict[str, str] = {}
    for message in messages:
        if message.role == "assistant":
            tool_names.update({call.id: call.name for call in message.tool_calls})
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
                    [
                        ToolReturnPart(
                            tool_names[message.tool_call_id],
                            message.content,
                            message.tool_call_id,
                        )
                    ]
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


def _restore_history(state: dict) -> list[ModelMessage]:
    version = state.get("version")
    if version not in {_HISTORY_VERSION, _LEGACY_HISTORY_VERSION}:
        raise ValueError("Agent history version changed; start a new run")
    history = ModelMessagesTypeAdapter.validate_python(state["messages"])
    calls, returned = {}, set()
    for message in history:
        for part in message.parts:
            if isinstance(part, ToolCallPart):
                if part.tool_call_id in calls:
                    raise ValueError("Agent history contains duplicate tool calls")
                calls[part.tool_call_id] = part.tool_name
            elif isinstance(part, ToolReturnPart):
                expected = calls.get(part.tool_call_id)
                if expected is None or part.tool_call_id in returned:
                    raise ValueError("Agent history contains an unpaired tool return")
                if part.tool_name != expected:
                    if version != _LEGACY_HISTORY_VERSION or part.tool_name != "result":
                        raise ValueError("Agent history tool identity mismatch")
                    # v1's initial-history adapter lost names. The original call
                    # is the only authority for this deterministic migration.
                    part.tool_name = expected
                returned.add(part.tool_call_id)
    return history


class ProjectGatewayModel(Model):
    """Adapter, not a second provider or credential owner."""

    def __init__(
        self,
        client: LLMClient,
        template: LLMCallRequest,
        budget: AgentRunBudget,
        *,
        input_limit: int,
        capability_id: str | None = None,
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
        self.capability_id = capability_id
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

    def _step_context(self) -> AIManagedStepContext:
        """本模型回合的受管 step 归属；信封据此把请求计入 run 的 root capability。"""
        from infrastructure.llm.workflow_budget import AIManagedStepContext

        runtime_scope = getattr(self.client, "runtime_scope", None)
        profile_summary = getattr(self.client, "profile_summary", None)
        return AIManagedStepContext(
            step_name=AGENT_STEP_NAME,
            call_kind=AIStepCallKind.generate,
            capability_id=self.capability_id,
            profile_source=(
                str(runtime_scope.get("profile_source") or "")
                if isinstance(runtime_scope, Mapping)
                else ""
            ),
            profile_summary=(
                dict(profile_summary) if isinstance(profile_summary, Mapping) else {}
            ),
        )

    def _managed_step(self) -> Iterator[AIManagedStepContext]:
        from infrastructure.llm.workflow_budget import managed_step_scope

        return managed_step_scope(self._step_context())

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
        # 外层 WorkflowBudget 已承担本次请求的预留与用量时不再重复预留。
        delegated = _workflow_meter_owns_provider_request()
        from infrastructure.llm.workflow_budget import AIRunEnvelopeError

        if not delegated:
            self.budget.reserve(requests=1, future_requests=self.future_requests)
        try:
            await self.save_budget()
            await self.save_history(messages)
        except BaseException:
            if not delegated:
                self.budget.release_pending_request()
            raise
        try:
            with self._managed_step():
                response = await self.client.generate(request, transport_retries=False)
        except AIRunEnvelopeError:
            # 信封在 provider I/O 前拒绝：兼容账本回滚本次请求预留，两个账本
            # 都不留下部分变更，异常按原类型继续向上传播。
            if not delegated:
                self.budget.release_pending_request()
                await self.save_budget()
            raise
        if not delegated:
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
        # 流式不经 client.generate 的 provider_request 闭包，不查 WorkflowBudget；
        # 因此流式请求仍由 AgentRunBudget 单独计量，避免用量无人落定。
        self.budget.reserve(requests=1, future_requests=self.future_requests)
        await self.save_budget()
        await self.save_history(messages)
        stream = self.client.generate_stream(request, transport_retries=False)
        try:
            # 生成器在首次迭代才发请求，受管 step 必须覆盖整个消费区间。
            with self._managed_step():
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
        stream_opened = False
        request_released = False
        from infrastructure.llm.workflow_budget import AIRunEnvelopeError

        try:
            async for chunk in self.stream:
                stream_opened = True
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
        except AIRunEnvelopeError:
            if not stream_opened:
                # 流从未打开：信封在 provider I/O 前拒绝建流，回滚兼容账本的
                # 请求预留，不把这次拒绝当成未知用量的真实请求。
                request_released = True
                self.model.budget.release_pending_request()
                await self.model.save_budget()
            raise
        finally:
            if not request_released:
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
    capability_id: str | None = None,
):
    """Caller owns data/permissions and client lifetime; no automatic run replay.

    ``capability_id`` 是本 Agent 循环服务的 canonical root capability。活动运行信封下必须
    显式声明：每次模型请求、工具内嵌的受管 step 与 research 子请求都以它归入同一 run，
    与信封 root 不一致时由信封拒绝；没有活动信封时省略即可保持原有 AgentRunBudget 行为。
    """
    _require_root_capability(capability_id)
    model = ProjectGatewayModel(
        client,
        request,
        budget,
        input_limit=input_limit,
        capability_id=capability_id,
        checkpoint=checkpoint,
        state_checkpoint=state_checkpoint,
        future_requests=future_requests,
    )
    agent = Agent(model=model, tools=tools, output_type=output_type, retries=1)
    if output_validator is not None:
        agent.output_validator(output_validator)
    if state is not None:
        history = _restore_history(state)
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
