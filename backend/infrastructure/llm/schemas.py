"""
LLM 调用相关的 Pydantic schema

定义 LLM 调用的入参和出参结构。
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from infrastructure.llm.redaction import redact_diagnostic


class LLMToolCall(BaseModel):
    """Provider tool call; arguments remain JSON until tool schema validation."""

    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=256)
    name: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,128}$")
    arguments: str = Field(default="{}", max_length=100000)


class LLMToolDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,128}$")
    description: str = Field(default="", max_length=8000)
    parameters: dict[str, Any]


class LLMToolDelta(BaseModel):
    """Incomplete JSON is permitted only while assembling a provider stream."""

    index: int = Field(ge=0)
    id: str | None = None
    name: str | None = None
    arguments: str | None = None


class LLMMessage(BaseModel):
    """LLM 对话消息"""

    role: Literal["system", "user", "assistant", "tool"] = "user"
    content: str = ""
    tool_calls: list[LLMToolCall] = Field(
        default_factory=list, exclude_if=lambda value: not value
    )
    tool_call_id: str | None = Field(default=None, exclude_if=lambda value: value is None)
    reasoning_content: str | None = Field(default=None, exclude=True, repr=False)

    @model_validator(mode="after")
    def validate_tool_role(self) -> LLMMessage:
        if self.tool_calls and self.role != "assistant":
            raise ValueError("Only assistant messages can request tools")
        if (self.role == "tool") != bool(self.tool_call_id):
            raise ValueError("Tool results require a paired tool call ID")
        return self

    def provider_message(self) -> dict[str, Any]:
        result = self.model_dump()
        if self.tool_calls:
            result["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {"name": call.name, "arguments": call.arguments},
                }
                for call in self.tool_calls
            ]
        if self.reasoning_content is not None:
            result["reasoning_content"] = self.reasoning_content
        return result


class LLMCallRequest(BaseModel):
    """LLM 调用请求参数"""

    model: str = "deepseek-flash"
    """模型名称"""
    messages: list[LLMMessage] = Field(default_factory=list)
    """对话消息列表"""
    temperature: float | None = 0.7
    """生成温度"""
    max_tokens: int | None = None
    """最大输出 token 数；None 表示继承当前 LLMClient 的默认值"""
    response_format: dict[str, str] | None = None
    """响应格式约束，如 {"type": "json_object"}"""
    stop: list[str] | None = None
    """停止序列"""
    top_p: float | None = None
    """Top-p 采样"""
    frequency_penalty: float | None = None
    """频率惩罚"""
    presence_penalty: float | None = None
    """存在惩罚"""
    seed: int | None = None
    """随机种子（用于可复现生成）"""
    extra: dict[str, Any] = Field(default_factory=dict)
    """额外 provider 特定参数"""
    tools: list[LLMToolDefinition] = Field(default_factory=list)
    tool_choice: Literal["auto", "none", "required"] | None = None

    @model_validator(mode="after")
    def validate_tool_history(self) -> LLMCallRequest:
        names = [tool.name for tool in self.tools]
        if len(set(names)) != len(names):
            raise ValueError("Tool names must be unique")
        pending: set[str] = set()
        seen: set[str] = set()
        for message in self.messages:
            if message.role == "tool":
                if message.tool_call_id not in pending:
                    raise ValueError("Unpaired or duplicate tool result")
                pending.remove(message.tool_call_id)
            else:
                if pending:
                    raise ValueError(
                        "Tool calls must be resolved before the next message"
                    )
                for call in message.tool_calls:
                    if call.id in seen:
                        raise ValueError("Tool call IDs must be unique")
                    seen.add(call.id)
                    pending.add(call.id)
        if pending:
            raise ValueError("Unresolved tool calls cannot be sent to the model")
        return self


class LLMUsage(BaseModel):
    """LLM 调用 token 用量"""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class LLMCallResponse(BaseModel):
    """LLM 调用响应"""

    content: str = ""
    """生成的文本内容"""
    finish_reason: str = ""
    """结束原因：stop / length / content_filter / tool_calls"""
    usage: LLMUsage = Field(default_factory=LLMUsage)
    """token 用量统计"""
    model: str = ""
    """实际使用的模型名称"""
    provider: str = ""
    """使用的 provider 名称"""
    latency_ms: float = 0.0
    """调用耗时（毫秒）"""
    raw: dict[str, Any] = Field(default_factory=dict)
    """原始响应（调试用）"""
    tool_calls: list[LLMToolCall] = Field(default_factory=list)
    reasoning_content: str | None = Field(default=None, exclude=True, repr=False)

    @model_validator(mode="after")
    def unique_tool_calls(self):
        if len({call.id for call in self.tool_calls}) != len(self.tool_calls):
            raise ValueError("Provider returned duplicate tool call IDs in one response")
        return self


class LLMStreamChunk(BaseModel):
    """流式输出片段"""

    content: str = ""
    """当前片段文本"""
    reasoning_chars: int = Field(default=0, ge=0, exclude=True)
    """Internal count only; never forward reasoning text or add it to browser wire."""
    finish_reason: str | None = None
    """如果该片段是最后一个，提供结束原因"""
    usage: LLMUsage | None = None
    """最后一块可能包含用量信息"""
    tool_deltas: list[LLMToolDelta] = Field(default_factory=list)
    reasoning_content: str | None = Field(default=None, exclude=True, repr=False)


# ---------------------------------------------------------------------------
# 统一 AI 运行信封（run envelope）
#
# ADR-0023 保留有界 Agent 与累计预算；ADR-0025 保留 canonical capability。
# 本契约只承载稳定 ID、计数、哈希与安全错误类型：provider 正文、Prompt、
# endpoint、API Key 与隐藏 reasoning 一律不得进入信封。
# ---------------------------------------------------------------------------

AI_RUN_ENVELOPE_VERSION = 1
AI_RUN_ENVELOPE_KEY = "_ai_run_envelope"
AI_RUN_RECENT_ATTEMPT_LIMIT = 256
AI_RUN_STEP_RECEIPT_LIMIT = 64
INFRASTRUCTURE_CAPABILITY_PREFIX = "infrastructure."

_SAFE_RECEIPT_TOKEN = re.compile(r"[^A-Za-z0-9_.:\-]")
_ENDPOINT_RE = re.compile(r"[A-Za-z][A-Za-z0-9+.\-]*://\S+")
_RECEIPT_TOKEN_LIMIT = 160
_IDENTIFIER_LIMIT = 128


def safe_receipt_token(value: Any, *, limit: int = _RECEIPT_TOKEN_LIMIT) -> str:
    """把运行期文本收敛为脱敏回执 token。

    先经 redact_diagnostic 去除凭据，再去掉完整 endpoint，最后只保留
    [A-Za-z0-9_.:-]；其余字符（含空白、引号、换行、非 ASCII 正文）折叠为
    下划线。回执不得因此携带 provider 正文、Key 或 endpoint。
    """
    if value is None:
        return ""
    text = _ENDPOINT_RE.sub("endpoint", redact_diagnostic(value)).strip()
    if not text:
        return ""
    return _SAFE_RECEIPT_TOKEN.sub("_", text)[:limit]


class AIRunStatus(StrEnum):
    """一次权威领域运行的状态；自动重试/恢复保持同一 run。"""

    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"
    interrupted = "interrupted"


class AIStepCallKind(StrEnum):
    """provider 调用形态；图片 generate/edit 共用 capability，只由本字段区分。"""

    generate = "generate"
    structured = "structured"
    stream = "stream"
    research = "research"
    image_generate = "image_generate"
    image_edit = "image_edit"


class AIStepPurpose(StrEnum):
    """同一步内这次请求的用途；semantic repair 是 purpose，不是新 capability。"""

    primary = "primary"
    schema_repair = "schema_repair"
    format_repair = "format_repair"
    semantic_repair = "semantic_repair"


class AIChargeState(StrEnum):
    """费用只记录状态，不估算货币金额。"""

    none = "none"
    recorded = "recorded"
    possible = "possible"


class AIRequestOutcome(StrEnum):
    """单个 provider 请求的落定状态；in_flight 只应存在于运行中的快照。"""

    in_flight = "in_flight"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"
    unknown = "unknown"


class AIRunAuthorizationReason(StrEnum):
    """同 run 增加额度只允许这几种可审计原因；不记录作者自由文本。"""

    author_resume = "author_resume"
    duplicate_charge_confirmed = "duplicate_charge_confirmed"
    domain_recovery = "domain_recovery"


class AITaskIdentityV1(BaseModel):
    """当前执行载体与所有权；不替代 operation/run 身份。"""

    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(min_length=1, max_length=_IDENTIFIER_LIMIT)
    attempt: int = Field(default=1, ge=0)
    lease_id: str | None = Field(default=None, max_length=_IDENTIFIER_LIMIT)


class AIRunAuthorizationV1(BaseModel):
    """同一 run 内追加请求额度的作者授权记录；不移动既有 deadline。"""

    model_config = ConfigDict(extra="forbid")

    revision: int = Field(ge=1)
    additional_requests: int = Field(ge=1)
    reason: AIRunAuthorizationReason
    authorized_at: datetime


class AIStepAttemptV1(BaseModel):
    """有界 recent attempt 摘要；总计数与用量聚合不依赖本列表。"""

    model_config = ConfigDict(extra="forbid")

    step_name: str = Field(min_length=1, max_length=_RECEIPT_TOKEN_LIMIT)
    step_capability_id: str = Field(min_length=1, max_length=_RECEIPT_TOKEN_LIMIT)
    call_kind: AIStepCallKind
    purpose: AIStepPurpose
    request_index: int = Field(ge=1)
    started_at: datetime
    elapsed_ms: float = Field(default=0.0, ge=0.0)
    outcome: AIRequestOutcome = AIRequestOutcome.in_flight
    error_kind: str = Field(default="", max_length=64)
    retryable: bool = False
    charge_state: AIChargeState = AIChargeState.none


class AIStepReceiptV1(BaseModel):
    """一个 (step, capability, call_kind, purpose, profile) 身份的聚合回执。"""

    model_config = ConfigDict(extra="forbid")

    step_name: str = Field(min_length=1, max_length=_RECEIPT_TOKEN_LIMIT)
    step_capability_id: str = Field(min_length=1, max_length=_RECEIPT_TOKEN_LIMIT)
    call_kind: AIStepCallKind
    purpose: AIStepPurpose = AIStepPurpose.primary
    profile_hash: str = Field(default="", max_length=128)
    profile_source: str = Field(default="unknown", max_length=64)
    profile_summary: dict[str, Any] = Field(default_factory=dict)
    input_fingerprint: str | None = Field(default=None, max_length=128)
    prompt_contract_id: str | None = Field(default=None, max_length=160)
    prompt_contract_version: str | None = Field(default=None, max_length=64)
    prompt_contract_hash: str | None = Field(default=None, max_length=128)
    requests_started: int = Field(default=0, ge=0)
    requests_settled: int = Field(default=0, ge=0)
    requests_unknown: int = Field(default=0, ge=0)
    transport_retries: int = Field(default=0, ge=0)
    structured_retries: int = Field(default=0, ge=0)
    format_retries: int = Field(default=0, ge=0)
    semantic_retries: int = Field(default=0, ge=0)
    elapsed_ms: float = Field(default=0.0, ge=0.0)
    finish_reason: str = Field(default="", max_length=64)
    error_kind: str = Field(default="", max_length=64)
    retryable: bool = False
    usage: LLMUsage = Field(default_factory=LLMUsage)
    usage_complete: bool = True
    charge_state: AIChargeState = AIChargeState.none


class AIRunEnvelopeV1(BaseModel):
    """一次权威领域运行及其累计授权账本。

    requests_settled 只统计已取得完整回执（含 usage）的请求；requests_unknown
    统计已发出但结果或用量的证据不完整的请求（超时、中断、取消、崩溃或 provider
    未返回 usage）。两者之和不超过 requests_started，差额表示仍在途。自动重试、
    恢复、requeue 与 manual resume 都累加同一 run；只有作者明确续算才通过
    AIRunAuthorizationV1 增加请求额度。
    """

    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = AI_RUN_ENVELOPE_VERSION
    operation_id: str = Field(min_length=1, max_length=_IDENTIFIER_LIMIT)
    run_id: str = Field(min_length=1, max_length=_IDENTIFIER_LIMIT)
    previous_run_id: str | None = Field(default=None, max_length=_IDENTIFIER_LIMIT)
    root_capability_id: str = Field(min_length=1, max_length=_RECEIPT_TOKEN_LIMIT)
    novel_id: str = Field(min_length=1, max_length=_IDENTIFIER_LIMIT)
    task: AITaskIdentityV1 | None = None
    started_at: datetime
    deadline_at: datetime | None = None
    request_limit: int = Field(ge=0)
    requests_started: int = Field(default=0, ge=0)
    requests_settled: int = Field(default=0, ge=0)
    requests_unknown: int = Field(default=0, ge=0)
    authorization_revision: int = Field(default=0, ge=0)
    authorizations: list[AIRunAuthorizationV1] = Field(default_factory=list)
    usage: LLMUsage = Field(default_factory=LLMUsage)
    usage_complete: bool = True
    charge_state: AIChargeState = AIChargeState.none
    status: AIRunStatus = AIRunStatus.running
    legacy_untracked: bool = False
    steps: list[AIStepReceiptV1] = Field(default_factory=list)
    recent_attempts: list[AIStepAttemptV1] = Field(default_factory=list)
    recent_attempts_overflow: int = Field(default=0, ge=0)

    @field_validator("started_at", "deadline_at")
    @classmethod
    def require_aware_timestamps(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("run envelope timestamps must be timezone-aware")
        return value

    def step_capability_allowed(self, capability_id: str) -> bool:
        """step 能力只能是本 run 的 root，或显式 infrastructure.* helper。"""
        return capability_id == self.root_capability_id or capability_id.startswith(
            INFRASTRUCTURE_CAPABILITY_PREFIX
        )

    @model_validator(mode="after")
    def validate_ledger(self) -> AIRunEnvelopeV1:
        if self.requests_settled + self.requests_unknown > self.requests_started:
            raise ValueError("settled and unknown requests cannot exceed started")
        if self.requests_started > self.request_limit:
            raise ValueError("requests_started exceeds the frozen request_limit")
        if len(self.recent_attempts) > AI_RUN_RECENT_ATTEMPT_LIMIT:
            raise ValueError("recent attempt summary must stay bounded")
        if self.legacy_untracked and self.usage_complete:
            raise ValueError("legacy untracked runs cannot claim complete usage")
        for step in self.steps:
            if not self.step_capability_allowed(step.step_capability_id):
                raise ValueError(
                    f"step capability {step.step_capability_id!r} is neither the run "
                    "root nor infrastructure.*"
                )
            if step.requests_settled + step.requests_unknown > step.requests_started:
                raise ValueError("step settled and unknown requests exceed started")
        if sum(step.requests_started for step in self.steps) != self.requests_started:
            raise ValueError("step receipts must account for every started request")
        if sum(step.requests_settled for step in self.steps) != self.requests_settled:
            raise ValueError("step receipts must account for every settled request")
        if sum(step.requests_unknown for step in self.steps) != self.requests_unknown:
            raise ValueError("step receipts must account for every unknown request")
        if sum(step.usage.total_tokens for step in self.steps) != self.usage.total_tokens:
            raise ValueError("step receipts must account for the aggregate usage")
        return self


class AIRunEnvelopeVersionError(ValueError):
    """信封版本无法识别；调用方必须失败关闭而不是猜测。"""


def read_ai_run_envelope(payload: Any) -> AIRunEnvelopeV1 | None:
    """读取 v1 运行信封；v0（managed_llm_steps 列表或无 version 的旧结构）返回 None。"""
    if payload is None:
        return None
    if isinstance(payload, AIRunEnvelopeV1):
        return payload
    if isinstance(payload, (list, tuple)):
        return None
    if isinstance(payload, Mapping):
        version = payload.get("version")
        if version is None:
            return None
        if version != AI_RUN_ENVELOPE_VERSION:
            raise AIRunEnvelopeVersionError(
                f"unsupported AI run envelope version {version!r}"
            )
        return AIRunEnvelopeV1.model_validate(payload)
    raise AIRunEnvelopeVersionError(
        f"unexpected AI run envelope payload type {type(payload).__name__}"
    )
