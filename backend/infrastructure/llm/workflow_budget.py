"""Meter deterministic review workflows and the unified AI run ledger.

- `WorkflowBudget` / `workflow_budget` 计量既有确定性审查工作流的请求与用量。
- `AIRunEnvelope` / `ai_run_scope` 是统一运行信封的运行期累计账本：一次权威领域
  运行只有一个 run，自动重试、恢复、requeue 与 manual resume 都累加同一账本。
  它只保存稳定 ID、计数、哈希与安全错误类型，不保存 Prompt、正文或 Key。
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import wraps
from typing import Any, Literal, get_type_hints

from infrastructure.llm.agent_runtime import AgentRunBudget
from infrastructure.llm.schemas import (
    AI_RUN_RECENT_ATTEMPT_LIMIT,
    AIChargeState,
    AIRequestOutcome,
    AIRunAuthorizationReason,
    AIRunAuthorizationV1,
    AIRunEnvelopeV1,
    AIRunStatus,
    AIStepAttemptV1,
    AIStepCallKind,
    AIStepPurpose,
    AIStepReceiptV1,
    AITaskIdentityV1,
    LLMUsage,
    profile_summary_hash,
    safe_profile_source,
    safe_receipt_token,
    sanitize_profile_summary,
)

RETRY_KINDS = ("transport", "structured", "format", "semantic")
RetryKind = Literal["transport", "structured", "format", "semantic"]

_RETRY_FIELDS: dict[str, str] = {
    "transport": "transport_retries",
    "structured": "structured_retries",
    "format": "format_retries",
    "semantic": "semantic_retries",
}


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


class AIRunEnvelopeError(RuntimeError):
    """运行信封拒绝本次操作；拒绝发生在任何计数或 provider I/O 之前。"""

    def __init__(self, message: str, *, run_id: str = "") -> None:
        self.run_id = run_id
        super().__init__(message)


class AIRunBudgetExceededError(AIRunEnvelopeError):
    """请求额度已用尽；只有作者显式续算才能在同一 run 内增加。"""


class AIRunDeadlineExceededError(AIRunEnvelopeError):
    """运行 deadline 已过；不得再 sleep 或发出下一次请求。"""


class AIRunIdentityError(AIRunEnvelopeError):
    """同一 run 内身份漂移：run 嵌套冲突或 step 能力越界。"""


class AIManagedStepContextError(AIRunEnvelopeError):
    """provider 请求没有可归属的受管 step 上下文。"""


class AIRunStateError(AIRunEnvelopeError):
    """运行已进入终态，不再接受新的请求或状态迁移。"""


@dataclass(frozen=True)
class AIManagedStepContext:
    """当前受管 step 的身份；provider I/O 只能归属到显式 step。"""

    step_name: str
    call_kind: AIStepCallKind
    capability_id: str | None = None
    purpose: AIStepPurpose = AIStepPurpose.primary
    profile_source: str = "unknown"
    profile_summary: Mapping[str, Any] = field(default_factory=dict)
    input_fingerprint: str | None = None
    prompt_contract_id: str | None = None
    prompt_contract_version: str | None = None
    prompt_contract_hash: str | None = None

    def resolved_capability_id(self, root_capability_id: str) -> str:
        """内部 helper 省略 capability 时归属本 run 的 root。"""
        return self.capability_id or root_capability_id


_CURRENT_STEP_CONTEXT: ContextVar[AIManagedStepContext | None] = ContextVar(
    "ai_managed_step_context", default=None
)
_CURRENT_RUN_ENVELOPE: ContextVar[AIRunEnvelope | None] = ContextVar(
    "ai_run_envelope", default=None
)


@contextmanager
def managed_step_scope(context: AIManagedStepContext) -> Iterator[AIManagedStepContext]:
    """在当前 async 任务内声明受管 step；退出后恢复外层 step。"""
    token = _CURRENT_STEP_CONTEXT.set(context)
    try:
        yield context
    finally:
        _CURRENT_STEP_CONTEXT.reset(token)


def current_managed_step_context() -> AIManagedStepContext | None:
    return _CURRENT_STEP_CONTEXT.get()


def current_ai_run_envelope() -> AIRunEnvelope | None:
    return _CURRENT_RUN_ENVELOPE.get()


@contextmanager
def ai_run_scope(envelope: AIRunEnvelope) -> Iterator[AIRunEnvelope]:
    """注入一次权威运行的累计账本。

    嵌套进入同一 run 复用外层账本而不重置计数；不同 run 的嵌套属于身份漂移，
    必须由领域显式建立新运行边界而不是在这里悄悄开新账。
    """
    current = _CURRENT_RUN_ENVELOPE.get()
    if current is not None:
        if current.run_id != envelope.run_id:
            raise AIRunIdentityError(
                "cannot nest a different AI run inside the active run",
                run_id=envelope.run_id,
            )
        yield current
        return
    token = _CURRENT_RUN_ENVELOPE.set(envelope)
    try:
        yield envelope
    finally:
        _CURRENT_RUN_ENVELOPE.reset(token)


@dataclass
class AIRunRequestReservation:
    """一次已在账本中预留的 provider 请求。"""

    run_id: str
    step_name: str
    step_capability_id: str
    call_kind: AIStepCallKind
    purpose: AIStepPurpose
    profile_hash: str
    request_index: int
    started_at: datetime
    monotonic_started: float
    settled: bool = False


def new_ai_run_envelope(
    *,
    operation_id: str,
    run_id: str,
    root_capability_id: str,
    novel_id: str,
    request_limit: int,
    deadline_at: datetime | None = None,
    previous_run_id: str | None = None,
    task: AITaskIdentityV1 | None = None,
    legacy_untracked: bool = False,
    started_at: datetime | None = None,
) -> AIRunEnvelope:
    """按领域冻结的额度与 deadline 建立 v1 运行账本。"""
    return AIRunEnvelope(
        AIRunEnvelopeV1(
            operation_id=operation_id,
            run_id=run_id,
            previous_run_id=previous_run_id,
            root_capability_id=root_capability_id,
            novel_id=novel_id,
            task=task,
            started_at=started_at or datetime.now(UTC),
            deadline_at=deadline_at,
            request_limit=request_limit,
            legacy_untracked=legacy_untracked,
            usage_complete=not legacy_untracked,
        )
    )


def _serialized(method):
    """把"变更 + checkpoint"串行化。

    并发 reserve/settle 必须让 checkpoint 的落盘顺序与变更顺序一致，否则旧快照可能
    后写并回退新状态。临界区包含 `on_change` 的 await，因此回调不得重入同一账本。
    """

    @wraps(method)
    async def run(self, *args, **kwargs):
        async with self._lock:
            return await method(self, *args, **kwargs)

    return run


class AIRunEnvelope:
    """一次权威领域运行的累计账本。

    所有公开变更都经 `_serialized` 串行化：计数变更与 `on_change` checkpoint 在
    同一临界区内完成，保证持久化顺序单调，不会出现旧快照覆盖新快照。
    `on_change` 回调不得重入同一账本（会自锁），只应把快照写入领域 checkpoint。
    """

    def __init__(
        self,
        envelope: AIRunEnvelopeV1,
        *,
        clock: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] | None = None,
        on_change: Callable[[AIRunEnvelopeV1], Awaitable[None]] | None = None,
    ) -> None:
        self._envelope = envelope.model_copy(deep=True)
        self._clock = clock or (lambda: datetime.now(UTC))
        self._monotonic = monotonic or time.monotonic
        self._on_change = on_change
        self._lock = asyncio.Lock()
        self._steps: dict[tuple[str, str, str, str, str], AIStepReceiptV1] = {
            _step_key(step): step for step in self._envelope.steps
        }

    @property
    def run_id(self) -> str:
        return self._envelope.run_id

    @property
    def operation_id(self) -> str:
        return self._envelope.operation_id

    @property
    def root_capability_id(self) -> str:
        return self._envelope.root_capability_id

    @property
    def request_limit(self) -> int:
        return self._envelope.request_limit

    def remaining_seconds(self) -> float | None:
        deadline = self._envelope.deadline_at
        if deadline is None:
            return None
        return (deadline - self._clock()).total_seconds()

    def deadline_exceeded(self) -> bool:
        remaining = self.remaining_seconds()
        return remaining is not None and remaining <= 0

    def snapshot(self) -> AIRunEnvelopeV1:
        self._refresh_derived()
        return self._envelope.model_copy(deep=True)

    @_serialized
    async def reserve(
        self, *, purpose: AIStepPurpose | None = None
    ) -> AIRunRequestReservation:
        """预留一次 provider 请求；被预算/deadline 拒绝时不产生任何计数。"""
        context = current_managed_step_context()
        if context is None:
            raise AIManagedStepContextError(
                "provider request has no managed step context", run_id=self.run_id
            )
        if self._envelope.status is not AIRunStatus.running:
            raise AIRunStateError(
                f"run is {self._envelope.status.value}; no further request is authorized",
                run_id=self.run_id,
            )
        if self.deadline_exceeded():
            raise AIRunDeadlineExceededError(
                "run deadline passed before the request started", run_id=self.run_id
            )
        if self._envelope.requests_started >= self._envelope.request_limit:
            raise AIRunBudgetExceededError(
                "run request limit reached; only an explicit author authorization "
                "may raise it",
                run_id=self.run_id,
            )
        step = self._ensure_step(context, purpose or context.purpose)
        step.requests_started += 1
        self._envelope.requests_started += 1
        started_at = self._clock()
        reservation = AIRunRequestReservation(
            run_id=self.run_id,
            step_name=step.step_name,
            step_capability_id=step.step_capability_id,
            call_kind=step.call_kind,
            purpose=step.purpose,
            profile_hash=step.profile_hash,
            request_index=self._envelope.requests_started,
            started_at=started_at,
            monotonic_started=self._monotonic(),
        )
        self._append_attempt(
            AIStepAttemptV1(
                step_name=step.step_name,
                step_capability_id=step.step_capability_id,
                call_kind=step.call_kind,
                purpose=step.purpose,
                request_index=reservation.request_index,
                started_at=started_at,
            )
        )
        self._refresh_derived()
        await self._notify()
        return reservation

    @_serialized
    async def settle(
        self,
        reservation: AIRunRequestReservation,
        *,
        usage: LLMUsage | None = None,
        elapsed_ms: float | None = None,
        finish_reason: str = "",
        error_kind: str = "",
        retryable: bool = False,
        outcome: AIRequestOutcome | None = None,
    ) -> None:
        """落定一次请求；缺少 usage 时记为 possible，不得写成零用量。"""
        self._require_open(reservation)
        step = self._step_for(reservation)
        elapsed = (
            max(float(elapsed_ms), 0.0)
            if elapsed_ms is not None
            else max(self._monotonic() - reservation.monotonic_started, 0.0) * 1000.0
        )
        if usage is None:
            step.requests_unknown += 1
            self._envelope.requests_unknown += 1
        else:
            step.requests_settled += 1
            self._envelope.requests_settled += 1
            step.usage = _add_usage(step.usage, usage)
        step.elapsed_ms += elapsed
        step.retryable = step.retryable or retryable
        if finish_reason:
            step.finish_reason = safe_receipt_token(finish_reason, limit=64)
        if error_kind:
            step.error_kind = safe_receipt_token(error_kind, limit=64)
        reservation.settled = True
        self._resolve_attempt(
            reservation,
            outcome=outcome
            or (
                AIRequestOutcome.succeeded
                if usage is not None
                else AIRequestOutcome.unknown
            ),
            usage_known=usage is not None,
            elapsed_ms=elapsed,
            error_kind=error_kind,
            retryable=retryable,
        )
        self._refresh_derived()
        await self._notify()

    @_serialized
    async def record_retry(
        self, reservation: AIRunRequestReservation, *, kind: RetryKind
    ) -> None:
        """在 step 回执上累计一次显式重试；自动恢复不得重置这些计数。"""
        if kind not in _RETRY_FIELDS:
            raise ValueError(f"unknown retry kind {kind!r}")
        step = self._step_for(reservation)
        field_name = _RETRY_FIELDS[kind]
        setattr(step, field_name, getattr(step, field_name) + 1)
        self._refresh_derived()
        await self._notify()

    @_serialized
    async def authorize_additional_requests(
        self, additional: int, *, reason: AIRunAuthorizationReason
    ) -> None:
        """作者明确续算或确认可能重复扣费时增加额度；不移动既有 deadline。"""
        if additional < 1:
            raise ValueError("additional requests must be positive")
        revision = self._envelope.authorization_revision + 1
        self._envelope.authorization_revision = revision
        self._envelope.request_limit += additional
        self._envelope.authorizations.append(
            AIRunAuthorizationV1(
                revision=revision,
                additional_requests=additional,
                reason=reason,
                authorized_at=self._clock(),
            )
        )
        await self._notify()

    @_serialized
    async def mark_in_flight_unknown(self) -> int:
        """恢复时把未 settle 的请求转为 unknown/possible，不删除也不当成未请求。"""
        converted = self._converge_in_flight()
        if converted:
            self._refresh_derived()
            await self._notify()
        return converted

    @_serialized
    async def finish(self, status: AIRunStatus) -> None:
        if status is AIRunStatus.running:
            raise AIRunStateError(
                "finish() requires a terminal run status", run_id=self.run_id
            )
        if self._envelope.status is not AIRunStatus.running:
            raise AIRunStateError(
                f"run already finished as {self._envelope.status.value}",
                run_id=self.run_id,
            )
        self._converge_in_flight()
        self._envelope.status = status
        self._refresh_derived()
        await self._notify()

    def _ensure_step(
        self, context: AIManagedStepContext, purpose: AIStepPurpose
    ) -> AIStepReceiptV1:
        step_name = safe_receipt_token(context.step_name)
        if not step_name:
            raise AIManagedStepContextError(
                "managed step requires a non-empty step_name", run_id=self.run_id
            )
        capability_id = safe_receipt_token(
            context.resolved_capability_id(self._envelope.root_capability_id)
        )
        if not self._envelope.step_capability_allowed(capability_id):
            raise AIRunIdentityError(
                f"step capability {capability_id!r} is neither the run root nor "
                "infrastructure.*",
                run_id=self.run_id,
            )
        profile_summary = sanitize_profile_summary(context.profile_summary)
        receipt = AIStepReceiptV1(
            step_name=step_name,
            step_capability_id=capability_id,
            call_kind=context.call_kind,
            purpose=purpose,
            profile_hash=profile_summary_hash(profile_summary),
            profile_source=safe_profile_source(context.profile_source),
            profile_summary=profile_summary,
            input_fingerprint=safe_receipt_token(context.input_fingerprint, limit=128)
            or None,
            prompt_contract_id=safe_receipt_token(
                context.prompt_contract_id, limit=160
            )
            or None,
            prompt_contract_version=safe_receipt_token(
                context.prompt_contract_version, limit=64
            )
            or None,
            prompt_contract_hash=safe_receipt_token(
                context.prompt_contract_hash, limit=128
            )
            or None,
        )
        key = _step_key(receipt)
        existing = self._steps.get(key)
        if existing is not None:
            return existing
        self._steps[key] = receipt
        self._envelope.steps.append(receipt)
        return receipt

    def _step_for(self, reservation: AIRunRequestReservation) -> AIStepReceiptV1:
        key = (
            reservation.step_name,
            reservation.step_capability_id,
            reservation.call_kind.value,
            reservation.purpose.value,
            reservation.profile_hash,
        )
        step = self._steps.get(key)
        if step is None:
            raise AIRunEnvelopeError(
                "reservation does not belong to this run ledger", run_id=self.run_id
            )
        return step

    def _require_open(self, reservation: AIRunRequestReservation) -> None:
        if reservation.run_id != self.run_id:
            raise AIRunIdentityError(
                "reservation belongs to a different run", run_id=self.run_id
            )
        if reservation.settled:
            raise AIRunEnvelopeError(
                "provider request was already settled", run_id=self.run_id
            )

    def _append_attempt(self, attempt: AIStepAttemptV1) -> None:
        """只保留最近 N 条 attempt 摘要；溢出计入 overflow，总计数不受影响。"""
        attempts = self._envelope.recent_attempts
        if len(attempts) >= AI_RUN_RECENT_ATTEMPT_LIMIT:
            del attempts[0]
            self._envelope.recent_attempts_overflow += 1
        attempts.append(attempt)

    def _converge_in_flight(self) -> int:
        """把仍在途的请求收敛为 unknown/possible；返回收敛数量。"""
        converted = 0
        for step in self._envelope.steps:
            in_flight = (
                step.requests_started - step.requests_settled - step.requests_unknown
            )
            if in_flight <= 0:
                continue
            step.requests_unknown += in_flight
            self._envelope.requests_unknown += in_flight
            converted += in_flight
        if converted:
            for attempt in self._envelope.recent_attempts:
                if attempt.outcome is AIRequestOutcome.in_flight:
                    attempt.outcome = AIRequestOutcome.unknown
        return converted

    def _resolve_attempt(
        self,
        reservation: AIRunRequestReservation,
        *,
        outcome: AIRequestOutcome,
        usage_known: bool,
        elapsed_ms: float,
        error_kind: str,
        retryable: bool,
    ) -> None:
        for attempt in self._envelope.recent_attempts:
            if attempt.request_index != reservation.request_index:
                continue
            attempt.outcome = outcome
            attempt.elapsed_ms = elapsed_ms
            attempt.retryable = retryable
            if error_kind:
                attempt.error_kind = safe_receipt_token(error_kind, limit=64)
            attempt.charge_state = (
                AIChargeState.recorded if usage_known else AIChargeState.possible
            )
            return

    def _refresh_derived(self) -> None:
        self._envelope.usage = _sum_usage(step.usage for step in self._envelope.steps)
        for step in self._envelope.steps:
            step.usage_complete = step.requests_unknown == 0
            if step.requests_unknown:
                step.charge_state = AIChargeState.possible
            elif step.requests_settled:
                step.charge_state = AIChargeState.recorded
            else:
                step.charge_state = AIChargeState.none
        if self._envelope.legacy_untracked:
            self._envelope.usage_complete = False
        else:
            self._envelope.usage_complete = all(
                step.usage_complete for step in self._envelope.steps
            ) and self._envelope.requests_unknown == 0
        if any(
            step.charge_state is AIChargeState.possible for step in self._envelope.steps
        ):
            self._envelope.charge_state = AIChargeState.possible
        elif any(
            step.charge_state is AIChargeState.recorded for step in self._envelope.steps
        ):
            self._envelope.charge_state = AIChargeState.recorded
        else:
            self._envelope.charge_state = AIChargeState.none

    async def _notify(self) -> None:
        if self._on_change is None:
            return
        await self._on_change(self.snapshot())


def _step_key(step: AIStepReceiptV1) -> tuple[str, str, str, str, str]:
    return (
        step.step_name,
        step.step_capability_id,
        step.call_kind.value,
        step.purpose.value,
        step.profile_hash,
    )


def _add_usage(left: LLMUsage, right: LLMUsage) -> LLMUsage:
    return LLMUsage(
        prompt_tokens=left.prompt_tokens + right.prompt_tokens,
        completion_tokens=left.completion_tokens + right.completion_tokens,
        total_tokens=left.total_tokens + right.total_tokens,
    )


def _sum_usage(items) -> LLMUsage:
    total = LLMUsage()
    for item in items:
        total = _add_usage(total, item)
    return total
