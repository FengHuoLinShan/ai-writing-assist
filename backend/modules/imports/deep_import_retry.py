"""Retry diagnostics for resilient deep import LLM calls."""

from __future__ import annotations

import json
import time
from collections.abc import Awaitable, Callable, Sequence
from typing import Any, Literal

import httpx
from pydantic import BaseModel, Field, ValidationError

from infrastructure.llm.errors import (
    LLMConnectionError,
    LLMInvalidResponseError,
    LLMRateLimitError,
    LLMTimeoutError,
)
from infrastructure.llm.redaction import redact_diagnostic

DeepImportErrorType = Literal[
    "422",
    "network",
    "timeout",
    "rate_limit",
    "schema_error",
    "empty_result",
    "quality_gate",
    "http_error",
    "unknown",
]
DeepImportFinalStatus = Literal["success", "failed"]

RETRYABLE_DEEP_IMPORT_ERROR_TYPES = {
    "422",
    "network",
    "timeout",
    "rate_limit",
    "empty_result",
}
NON_RETRYABLE_DEEP_IMPORT_ERROR_TYPES = {
    "schema_error",
    "quality_gate",
}


class DeepImportAttemptDiagnostic(BaseModel):
    """One LLM attempt and the retry decision made from its outcome."""

    attempt: int = Field(..., ge=1)
    status: DeepImportFinalStatus
    error_type: DeepImportErrorType | None = None
    message: str = ""
    elapsed_ms: float = Field(default=0.0, ge=0.0)
    retry_scheduled: bool = False


class DeepImportRetryResult(BaseModel):
    """Result shape consumed by Phase 0/1 quality statistics."""

    attempts: int = Field(..., ge=1)
    final_status: DeepImportFinalStatus
    final_error_type: DeepImportErrorType | None = None
    diagnostics: list[DeepImportAttemptDiagnostic] = Field(default_factory=list)
    value: Any | None = None


class DeepImportEmptyResultError(ValueError):
    """Raised internally when a successful LLM call returns no usable payload."""


def classify_deep_import_error(exc: Exception) -> DeepImportErrorType:
    """Classify LLM/HTTP/parse failures into deep-import diagnostic buckets."""

    status_code = _status_code_from_error(exc)
    text = str(exc).lower()

    if status_code == 422 or "error code: 422" in text or "unprocessable" in text:
        return "422"
    if status_code in {408, 504}:
        return "timeout"
    if isinstance(exc, (LLMTimeoutError, TimeoutError)):
        return "timeout"
    if isinstance(exc, httpx.TimeoutException):
        return "timeout"
    if _looks_like_empty_result(exc):
        return "empty_result"
    if status_code == 429 or isinstance(exc, LLMRateLimitError):
        return "rate_limit"
    if "error code: 429" in text or "rate limit" in text:
        return "rate_limit"
    if status_code is not None and status_code >= 500:
        return "network"
    if "error code: 5" in text or "failover_exhausted" in text:
        return "network"
    if isinstance(exc, (LLMConnectionError, httpx.RequestError, ConnectionError)):
        return "network"
    if isinstance(
        exc,
        (LLMInvalidResponseError, json.JSONDecodeError, ValidationError),
    ):
        return "schema_error"
    if isinstance(exc, ValueError) and "valid json" in text:
        return "schema_error"
    if status_code is not None:
        return "http_error"
    return "unknown"


def should_retry_deep_import_error(
    error_type: str,
    *,
    attempt: int,
    max_retries: int = 1,
    retryable_error_types: set[str] | None = None,
) -> bool:
    """Return whether a failed attempt should be retried.

    ``attempt`` is zero-based: the first failed call is attempt ``0``.
    """

    retry_budget = min(max(max_retries, 0), 1)
    if error_type in NON_RETRYABLE_DEEP_IMPORT_ERROR_TYPES:
        return False
    retryable = retryable_error_types or RETRYABLE_DEEP_IMPORT_ERROR_TYPES
    return error_type in retryable and attempt < retry_budget


async def run_deep_import_llm_with_retry[T](
    operation: Callable[[], Awaitable[T]],
    *,
    is_empty_result: Callable[[T], bool] | None = None,
    max_retries: int = 1,
    retryable_error_types: set[str] | None = None,
) -> DeepImportRetryResult:
    """Run one deep-import LLM operation with at most one retry by default."""

    diagnostics: list[DeepImportAttemptDiagnostic] = []
    retry_budget = min(max(max_retries, 0), 1)

    for attempt_index in range(retry_budget + 1):
        attempt_number = attempt_index + 1
        started_at = time.monotonic()
        try:
            value = await operation()
            if is_empty_result is not None and is_empty_result(value):
                raise DeepImportEmptyResultError("LLM returned empty result")
        except Exception as exc:
            elapsed_ms = _elapsed_ms(started_at)
            error_type = classify_deep_import_error(exc)
            retry_scheduled = should_retry_deep_import_error(
                error_type,
                attempt=attempt_index,
                max_retries=retry_budget,
                retryable_error_types=retryable_error_types,
            )
            diagnostics.append(
                DeepImportAttemptDiagnostic(
                    attempt=attempt_number,
                    status="failed",
                    error_type=error_type,
                    message=_safe_message(exc),
                    elapsed_ms=elapsed_ms,
                    retry_scheduled=retry_scheduled,
                )
            )
            if retry_scheduled:
                continue
            return DeepImportRetryResult(
                attempts=len(diagnostics),
                final_status="failed",
                final_error_type=error_type,
                diagnostics=diagnostics,
            )

        diagnostics.append(
            DeepImportAttemptDiagnostic(
                attempt=attempt_number,
                status="success",
                elapsed_ms=_elapsed_ms(started_at),
            )
        )
        return DeepImportRetryResult(
            attempts=len(diagnostics),
            final_status="success",
            diagnostics=diagnostics,
            value=value,
        )

    return DeepImportRetryResult(
        attempts=len(diagnostics),
        final_status="failed",
        final_error_type="unknown",
        diagnostics=diagnostics,
    )


def final_422_rate_after_retry(
    results: Sequence[DeepImportRetryResult],
    *,
    total_batches: int | None = None,
) -> float:
    """Count only retry-final 422 failures over the total planned batch count."""

    denominator = len(results) if total_batches is None else total_batches
    if denominator <= 0:
        return 0.0
    final_422_batches = sum(
        1
        for result in results
        if result.final_status == "failed" and result.final_error_type == "422"
    )
    return final_422_batches / denominator


def exceeds_final_422_rate_after_retry(
    results: Sequence[DeepImportRetryResult],
    *,
    total_batches: int | None = None,
    threshold: float = 0.40,
) -> bool:
    """Return whether retry-final 422 failures exceed the blocking threshold."""

    return final_422_rate_after_retry(results, total_batches=total_batches) > threshold


def _status_code_from_error(exc: Exception) -> int | None:
    status_code = getattr(exc, "status_code", None)
    if isinstance(status_code, int):
        return status_code

    response = getattr(exc, "response", None)
    response_status = getattr(response, "status_code", None)
    if isinstance(response_status, int):
        return response_status
    return None


def _looks_like_empty_result(exc: Exception) -> bool:
    if isinstance(exc, DeepImportEmptyResultError):
        return True
    text = str(exc).lower()
    return "empty result" in text or "empty scenes" in text or "empty scenes list" in text


def _elapsed_ms(started_at: float) -> float:
    return round((time.monotonic() - started_at) * 1000, 2)


def _safe_message(exc: Exception) -> str:
    return redact_diagnostic(exc, limit=300)
