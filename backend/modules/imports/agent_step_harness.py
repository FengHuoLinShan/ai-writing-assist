"""Controlled agent harness primitives for deep import Phase 0/1.

This module is deliberately small-surface. It records deterministic step/tool
execution and schema guard outcomes, but it does not implement an autonomous
agent loop or tool-choice policy.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, TypeVar, get_origin

from pydantic import BaseModel, ValidationError

from infrastructure.llm.token_estimation import estimate_token_count


class AgentPermissionLevel(StrEnum):
    """Trust ladder for workflow agent operations."""

    read = "Read"
    suggest = "Suggest"
    draft = "Draft"
    act_with_confirmation = "Act with Confirmation"
    autonomous = "Autonomous"


class StepExecutionStatus(StrEnum):
    succeeded = "succeeded"
    failed = "failed"
    degraded = "degraded"


class AgentErrorKind(StrEnum):
    invalid_json = "invalid_json"
    schema_validation = "schema_validation"
    repair_failed = "repair_failed"
    timeout = "timeout"
    provider_http_422 = "provider_http_422"
    rate_limit = "rate_limit"
    context_overflow = "context_overflow"
    missing_chapter_coverage = "missing_chapter_coverage"
    degraded_fallback = "degraded_fallback"
    unknown = "unknown"


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 1
    retry_on: tuple[str, ...] = (
        AgentErrorKind.timeout.value,
        AgentErrorKind.rate_limit.value,
    )


@dataclass(frozen=True)
class ContextBudget:
    max_input_chars: int = 32000
    max_output_chars: int = 32000
    context_limit_tokens: int = 128000
    trigger_ratio: float = 0.7


@dataclass(frozen=True)
class ContextBudgetEvent:
    event_type: str
    level: str
    before_chars: int
    after_chars: int
    reason: str
    details: dict[str, Any] = field(default_factory=dict)

    def model_dump(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type,
            "level": self.level,
            "before_chars": self.before_chars,
            "after_chars": self.after_chars,
            "reason": self.reason,
            "details": self.details,
        }


@dataclass(frozen=True)
class ContextBudgetResult:
    content: Any
    degraded: bool = False
    error_kind: str | None = None
    events: list[ContextBudgetEvent] = field(default_factory=list)

    def model_dump(self) -> dict[str, Any]:
        return {
            "content": self.content,
            "degraded": self.degraded,
            "error_kind": self.error_kind,
            "events": [event.model_dump() for event in self.events],
        }


@dataclass(frozen=True)
class StepToolEnvelope:
    name: str
    input_schema: type[BaseModel] | dict[str, Any] | None = None
    output_schema: type[BaseModel] | dict[str, Any] | None = None
    permission_level: AgentPermissionLevel = AgentPermissionLevel.read
    read_only: bool = True
    concurrent_safe: bool = True
    timeout: int | float | None = None
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    context_budget: ContextBudget = field(default_factory=ContextBudget)
    output_guard: bool = True

    def __post_init__(self) -> None:
        if self.permission_level == AgentPermissionLevel.autonomous:
            raise ValueError("Autonomous permission is disabled for imports agent steps")


@dataclass(frozen=True)
class AgentJournalEvent:
    event: str
    step_name: str
    elapsed_ms: int | None = None
    error_kind: str | None = None
    degraded: bool = False
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentRunJournal:
    events: list[AgentJournalEvent] = field(default_factory=list)

    def record(
        self,
        event: str,
        step_name: str,
        *,
        elapsed_ms: int | None = None,
        error_kind: str | None = None,
        degraded: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.events.append(
            AgentJournalEvent(
                event=event,
                step_name=step_name,
                elapsed_ms=elapsed_ms,
                error_kind=error_kind,
                degraded=degraded,
                details=details or {},
            )
        )

    def model_dump(self) -> list[dict[str, Any]]:
        return [
            {
                "event": event.event,
                "step_name": event.step_name,
                "elapsed_ms": event.elapsed_ms,
                "error_kind": event.error_kind,
                "degraded": event.degraded,
                "details": event.details,
            }
            for event in self.events
        ]


@dataclass
class StepExecutionResult:
    status: StepExecutionStatus
    output: Any = None
    degraded: bool = False
    error_kind: str | None = None
    repair_attempts: int = 0
    elapsed_ms: int = 0
    token_usage: dict[str, Any] = field(default_factory=dict)
    quality_stats: dict[str, Any] = field(default_factory=dict)
    journal_events: list[dict[str, Any]] = field(default_factory=list)
    exception: Exception | None = field(default=None, repr=False)


@dataclass
class OutputGuardResult:
    status: StepExecutionStatus
    output: Any = None
    degraded: bool = False
    error_kind: str | None = None
    repair_attempts: int = 0
    validation_errors: list[dict[str, Any]] = field(default_factory=list)
    raw_output_hash: str = ""


T = TypeVar("T", bound=BaseModel)
Repairer = Callable[[dict[str, Any]], Any | Awaitable[Any]]


class OutputGuard:
    """Strict schema validation with one bounded repair opportunity."""

    def __init__(
        self,
        schema: type[T],
        *,
        repairer: Repairer | None = None,
        max_repair_attempts: int = 1,
    ) -> None:
        self.schema = schema
        self.repairer = repairer
        self.max_repair_attempts = max(max_repair_attempts, 0)

    async def validate(self, raw_output: Any) -> OutputGuardResult:
        raw_hash = _raw_hash(raw_output)
        result = self._validate_once(raw_output, raw_hash)
        if result.status == StepExecutionStatus.succeeded:
            return result
        if self.repairer is None or self.max_repair_attempts <= 0:
            return result

        repair_payload = {
            "raw_output_hash": raw_hash,
            "schema": self.schema.model_json_schema(),
            "validation_errors": result.validation_errors,
            "error_kind": result.error_kind,
        }
        try:
            repaired = self.repairer(repair_payload)
            if inspect.isawaitable(repaired):
                repaired = await repaired
        except Exception:
            return OutputGuardResult(
                status=StepExecutionStatus.degraded,
                degraded=True,
                error_kind=AgentErrorKind.repair_failed.value,
                repair_attempts=1,
                validation_errors=result.validation_errors,
                raw_output_hash=raw_hash,
            )

        repaired_result = self._validate_once(repaired, _raw_hash(repaired))
        repaired_result.repair_attempts = 1
        if repaired_result.status == StepExecutionStatus.succeeded:
            return repaired_result
        repaired_result.status = StepExecutionStatus.degraded
        repaired_result.degraded = True
        repaired_result.error_kind = AgentErrorKind.repair_failed.value
        return repaired_result

    def _validate_once(self, raw_output: Any, raw_hash: str) -> OutputGuardResult:
        try:
            data = _decode_raw_output(raw_output)
        except json.JSONDecodeError as exc:
            return OutputGuardResult(
                status=StepExecutionStatus.degraded,
                degraded=True,
                error_kind=AgentErrorKind.invalid_json.value,
                validation_errors=[{"message": str(exc)}],
                raw_output_hash=raw_hash,
            )

        data = _normalize_for_schema(data, self.schema)
        try:
            output = self.schema.model_validate(data)
        except ValidationError as exc:
            return OutputGuardResult(
                status=StepExecutionStatus.degraded,
                degraded=True,
                error_kind=AgentErrorKind.schema_validation.value,
                validation_errors=exc.errors(),
                raw_output_hash=raw_hash,
            )
        return OutputGuardResult(
            status=StepExecutionStatus.succeeded,
            output=output,
            raw_output_hash=raw_hash,
        )


class ContextBudgetGuard:
    """Deterministic context shaping for managed workflow steps.

    This is not a conversation memory system. It only bounds payloads that the
    imports workflow already owns: step input, tool output, older tool results,
    and compact working sections.
    """

    def __init__(self, budget: ContextBudget | None = None) -> None:
        self.budget = budget or ContextBudget()

    def enforce_step_input(self, content: Any) -> ContextBudgetResult:
        return self._cap_content(
            content,
            max_chars=self.budget.max_input_chars,
            level="step_input",
            reason="step_input_budget",
        )

    def enforce_tool_output(self, content: Any) -> ContextBudgetResult:
        return self._cap_content(
            content,
            max_chars=self.budget.max_output_chars,
            level="tool_output",
            reason="tool_result_budget",
        )

    def snip_old_tool_results(
        self,
        tool_results: list[dict[str, Any]],
        *,
        protect_recent: int = 2,
    ) -> ContextBudgetResult:
        before_text = _stable_text(tool_results)
        if len(before_text) <= self.budget.max_input_chars:
            return ContextBudgetResult(content=tool_results)

        protected_start = max(len(tool_results) - max(protect_recent, 0), 0)
        shaped: list[dict[str, Any]] = []
        for index, item in enumerate(tool_results):
            copied = dict(item)
            if index < protected_start:
                copied["output"] = _snipped_marker(item)
                copied["snipped"] = True
            shaped.append(copied)

        shaped_text = _stable_text(shaped)
        if len(shaped_text) > self.budget.max_input_chars:
            return self._cap_content(
                shaped,
                max_chars=self.budget.max_input_chars,
                level="old_tool_results",
                reason="old_tool_results_snipped_and_capped",
            )

        return ContextBudgetResult(
            content=shaped,
            degraded=True,
            error_kind=AgentErrorKind.context_overflow.value,
            events=[
                ContextBudgetEvent(
                    event_type="snipped",
                    level="old_tool_results",
                    before_chars=len(before_text),
                    after_chars=len(shaped_text),
                    reason="old_tool_results_snipped",
                    details={"protected_recent": max(protect_recent, 0)},
                )
            ],
        )

    def microcompact_context(
        self,
        sections: list[dict[str, Any]],
        *,
        content_key: str = "content",
        head_chars: int = 800,
        tail_chars: int = 800,
    ) -> ContextBudgetResult:
        before_text = _stable_text(sections)
        if len(before_text) <= self.budget.max_input_chars:
            return ContextBudgetResult(content=sections)

        shaped: list[dict[str, Any]] = []
        for section in sections:
            copied = dict(section)
            content = str(copied.get(content_key) or "")
            if len(content) > head_chars + tail_chars:
                copied[content_key] = (
                    content[:head_chars].rstrip()
                    + "\n[...context microcompacted...]\n"
                    + content[-tail_chars:].lstrip()
                )
                copied["microcompacted"] = True
            shaped.append(copied)

        shaped_text = _stable_text(shaped)
        if len(shaped_text) > self.budget.max_input_chars:
            return self._cap_content(
                shaped,
                max_chars=self.budget.max_input_chars,
                level="working_context",
                reason="microcompact_then_cap",
            )

        return ContextBudgetResult(
            content=shaped,
            degraded=True,
            error_kind=AgentErrorKind.context_overflow.value,
            events=[
                ContextBudgetEvent(
                    event_type="microcompacted",
                    level="working_context",
                    before_chars=len(before_text),
                    after_chars=len(shaped_text),
                    reason="working_context_microcompact",
                    details={
                        "head_chars": head_chars,
                        "tail_chars": tail_chars,
                    },
                )
            ],
        )

    def autocompact_fallback(self, content: Any) -> ContextBudgetResult:
        text = _stable_text(content)
        estimated_tokens = _estimate_tokens(text)
        threshold_tokens = int(
            self.budget.context_limit_tokens * self.budget.trigger_ratio
        )
        if estimated_tokens <= threshold_tokens:
            return ContextBudgetResult(content=content)

        marker = {
            "autocompact_required": True,
            "reason": "estimated_context_exceeds_trigger_ratio",
            "original_chars": len(text),
            "estimated_tokens": estimated_tokens,
            "threshold_tokens": threshold_tokens,
            "raw_context_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        }
        return ContextBudgetResult(
            content=marker,
            degraded=True,
            error_kind=AgentErrorKind.context_overflow.value,
            events=[
                ContextBudgetEvent(
                    event_type="autocompact_fallback",
                    level="working_context",
                    before_chars=len(text),
                    after_chars=len(_stable_text(marker)),
                    reason="estimated_context_exceeds_trigger_ratio",
                    details={
                        "estimated_tokens": estimated_tokens,
                        "threshold_tokens": threshold_tokens,
                    },
                )
            ],
        )

    def _cap_content(
        self,
        content: Any,
        *,
        max_chars: int,
        level: str,
        reason: str,
    ) -> ContextBudgetResult:
        text = _stable_text(content)
        if len(text) <= max_chars:
            return ContextBudgetResult(content=content)
        capped = text[:max_chars]
        return ContextBudgetResult(
            content=capped,
            degraded=True,
            error_kind=AgentErrorKind.context_overflow.value,
            events=[
                ContextBudgetEvent(
                    event_type="truncated",
                    level=level,
                    before_chars=len(text),
                    after_chars=len(capped),
                    reason=reason,
                )
            ],
        )


class ManagedLLMStep:
    """Measured deterministic LLM step executor."""

    def __init__(
        self,
        envelope: StepToolEnvelope,
        *,
        journal: AgentRunJournal | None = None,
    ) -> None:
        if envelope.permission_level == AgentPermissionLevel.autonomous:
            raise ValueError("Autonomous permission is disabled for imports agent steps")
        self.envelope = envelope
        self.journal = journal or AgentRunJournal()

    async def run(
        self,
        operation: Callable[[], Any | Awaitable[Any]],
        *,
        token_usage: dict[str, Any] | None = None,
        quality_stats: dict[str, Any] | None = None,
    ) -> StepExecutionResult:
        start = time.monotonic()
        self.journal.record("started", self.envelope.name)
        try:
            if self.envelope.timeout:
                output = await asyncio.wait_for(
                    _maybe_await(operation()),
                    timeout=float(self.envelope.timeout),
                )
            else:
                output = await _maybe_await(operation())
        except Exception as exc:
            elapsed_ms = _elapsed_ms(start)
            error_kind = _classify_step_exception(exc)
            self.journal.record(
                "ended",
                self.envelope.name,
                elapsed_ms=elapsed_ms,
                error_kind=error_kind,
                degraded=True,
                details={
                    "token_usage": token_usage or {},
                    "quality_stats": quality_stats or {},
                },
            )
            return StepExecutionResult(
                status=StepExecutionStatus.failed,
                degraded=True,
                error_kind=error_kind,
                elapsed_ms=elapsed_ms,
                token_usage=token_usage or {},
                quality_stats=quality_stats or {},
                journal_events=self.journal.model_dump(),
                exception=exc,
            )

        elapsed_ms = _elapsed_ms(start)
        normalized = await self._normalize_output(output)
        degraded = normalized.degraded
        error_kind = normalized.error_kind
        self.journal.record(
            "ended",
            self.envelope.name,
            elapsed_ms=elapsed_ms,
            error_kind=error_kind,
            degraded=degraded,
            details={
                "token_usage": token_usage or {},
                "quality_stats": quality_stats or {},
                **normalized.journal_details,
            },
        )
        return StepExecutionResult(
            status=normalized.status,
            output=normalized.output,
            degraded=degraded,
            error_kind=error_kind,
            repair_attempts=normalized.repair_attempts,
            elapsed_ms=elapsed_ms,
            token_usage=token_usage or {},
            quality_stats=quality_stats or {},
            journal_events=self.journal.model_dump(),
        )

    async def _normalize_output(self, output: Any) -> _NormalizedStepOutput:
        if isinstance(output, ContextBudgetResult):
            return _NormalizedStepOutput(
                status=(
                    StepExecutionStatus.degraded
                    if output.degraded
                    else StepExecutionStatus.succeeded
                ),
                output=output.content,
                degraded=output.degraded,
                error_kind=output.error_kind,
                journal_details={
                    "budget_events": [e.model_dump() for e in output.events]
                },
            )
        if isinstance(output, OutputGuardResult):
            return _normalized_from_guard(output)

        schema = self.envelope.output_schema
        if (
            self.envelope.output_guard
            and isinstance(schema, type)
            and issubclass(schema, BaseModel)
        ):
            guarded = await OutputGuard(schema).validate(output)
            return _normalized_from_guard(guarded)

        degraded = bool(getattr(output, "degraded", False))
        status = getattr(output, "status", None)
        error_kind = getattr(output, "error_kind", None)
        if degraded or status == StepExecutionStatus.degraded:
            return _NormalizedStepOutput(
                status=StepExecutionStatus.degraded,
                output=output,
                degraded=True,
                error_kind=error_kind or AgentErrorKind.degraded_fallback.value,
            )
        return _NormalizedStepOutput(status=StepExecutionStatus.succeeded, output=output)


@dataclass(frozen=True)
class _NormalizedStepOutput:
    status: StepExecutionStatus
    output: Any
    degraded: bool = False
    error_kind: str | None = None
    repair_attempts: int = 0
    journal_details: dict[str, Any] = field(default_factory=dict)


def _decode_raw_output(raw_output: Any) -> Any:
    if isinstance(raw_output, BaseModel):
        return raw_output.model_dump(mode="json")
    if isinstance(raw_output, str):
        return json.loads(raw_output)
    return raw_output


def _normalize_for_schema(data: Any, schema: type[BaseModel]) -> Any:
    if isinstance(data, list):
        fields = list(schema.model_fields.items())
        if len(fields) == 1 and get_origin(fields[0][1].annotation) is list:
            data = {fields[0][0]: data}
    if not isinstance(data, dict):
        return data

    normalized = dict(data)
    for field_name, field_info in schema.model_fields.items():
        if field_name in normalized:
            continue
        if get_origin(field_info.annotation) is list:
            normalized[field_name] = []
    return normalized


async def _maybe_await(value: Any | Awaitable[Any]) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _raw_hash(raw_output: Any) -> str:
    if isinstance(raw_output, str):
        text = raw_output
    else:
        try:
            text = json.dumps(raw_output, ensure_ascii=False, sort_keys=True, default=str)
        except TypeError:
            text = str(raw_output)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _stable_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    except TypeError:
        return str(value)


def _estimate_tokens(text: str) -> int:
    return estimate_token_count(text)


def _normalized_from_guard(result: OutputGuardResult) -> _NormalizedStepOutput:
    return _NormalizedStepOutput(
        status=result.status,
        output=result.output,
        degraded=result.degraded,
        error_kind=result.error_kind,
        repair_attempts=result.repair_attempts,
        journal_details={
            "output_guard": {
                "raw_output_hash": result.raw_output_hash,
                "repair_attempts": result.repair_attempts,
                "validation_error_count": len(result.validation_errors),
            }
        },
    )


def _snipped_marker(item: dict[str, Any]) -> dict[str, Any]:
    text = _stable_text(item.get("output", item))
    return {
        "snipped": True,
        "original_chars": len(text),
        "raw_output_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "reason": "old_tool_result_snipped",
    }


def _elapsed_ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)


def _classify_step_exception(exc: Exception) -> str:
    text = f"{type(exc).__name__} {exc}".lower()
    if isinstance(exc, TimeoutError) or "timeout" in text:
        return AgentErrorKind.timeout.value
    if "422" in text:
        return AgentErrorKind.provider_http_422.value
    if "429" in text or "rate" in text:
        return AgentErrorKind.rate_limit.value
    if "context" in text and "overflow" in text:
        return AgentErrorKind.context_overflow.value
    return AgentErrorKind.unknown.value
