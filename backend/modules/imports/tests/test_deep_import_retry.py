"""Deep import LLM retry diagnostics primitives."""

from __future__ import annotations

import json

import pytest

from infrastructure.llm.errors import LLMInvalidResponseError, LLMTimeoutError
from modules.imports.deep_import_retry import (
    DeepImportRetryResult,
    classify_deep_import_error,
    exceeds_final_422_rate_after_retry,
    final_422_rate_after_retry,
    run_deep_import_llm_with_retry,
    should_retry_deep_import_error,
)


class StatusCodeError(Exception):
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        super().__init__(f"HTTP {status_code}")


def failed_retry_result(error_type: str) -> DeepImportRetryResult:
    return DeepImportRetryResult(
        attempts=1,
        final_status="failed",
        final_error_type=error_type,
        diagnostics=[],
    )


def test_classifies_422_http_errors() -> None:
    assert classify_deep_import_error(StatusCodeError(422)) == "422"
    assert classify_deep_import_error(Exception("Error code: 422")) == "422"


def test_classifies_timeout_errors() -> None:
    assert classify_deep_import_error(TimeoutError()) == "timeout"
    assert classify_deep_import_error(LLMTimeoutError("timed out")) == "timeout"


def test_classifies_provider_503_text_as_network() -> None:
    assert classify_deep_import_error(Exception("Error code: 503")) == "network"
    assert (
        classify_deep_import_error(Exception("provider failover_exhausted"))
        == "network"
    )


def test_classifies_schema_and_empty_result_errors() -> None:
    assert (
        classify_deep_import_error(
            LLMInvalidResponseError("Schema validation failed")
        )
        == "schema_error"
    )
    assert (
        classify_deep_import_error(json.JSONDecodeError("bad json", "{", 0))
        == "schema_error"
    )
    assert (
        classify_deep_import_error(ValueError("Entity extraction is not valid JSON"))
        == "schema_error"
    )
    assert classify_deep_import_error(ValueError("LLM returned empty scenes list")) == (
        "empty_result"
    )


def test_retry_policy_does_not_retry_schema_or_quality_gate() -> None:
    assert not should_retry_deep_import_error(
        "schema_error",
        attempt=0,
        max_retries=1,
    )
    assert not should_retry_deep_import_error(
        "quality_gate",
        attempt=0,
        max_retries=1,
    )
    assert should_retry_deep_import_error(
        "empty_result",
        attempt=0,
        max_retries=1,
    )
    assert not should_retry_deep_import_error(
        "timeout",
        attempt=0,
        max_retries=1,
        retryable_error_types={"network", "rate_limit", "empty_result"},
    )


@pytest.mark.asyncio
async def test_retry_wrapper_retries_once_then_succeeds() -> None:
    calls = 0

    async def operation() -> dict[str, str]:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise StatusCodeError(422)
        return {"ok": "yes"}

    result = await run_deep_import_llm_with_retry(operation)

    assert calls == 2
    assert result.attempts == 2
    assert result.final_status == "success"
    assert result.final_error_type is None
    assert result.value == {"ok": "yes"}
    assert [d.error_type for d in result.diagnostics] == ["422", None]
    assert result.diagnostics[0].retry_scheduled is True


@pytest.mark.asyncio
async def test_retry_wrapper_respects_custom_retryable_error_types() -> None:
    calls = 0

    async def operation() -> dict[str, str]:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise StatusCodeError(503)
        return {"ok": "yes"}

    result = await run_deep_import_llm_with_retry(
        operation,
        retryable_error_types={"network", "rate_limit", "empty_result"},
    )

    assert calls == 2
    assert result.final_status == "success"
    assert [d.error_type for d in result.diagnostics] == ["network", None]


@pytest.mark.asyncio
async def test_retry_wrapper_custom_policy_does_not_retry_timeout() -> None:
    calls = 0

    async def operation() -> dict[str, str]:
        nonlocal calls
        calls += 1
        raise TimeoutError()

    result = await run_deep_import_llm_with_retry(
        operation,
        retryable_error_types={"network", "rate_limit", "empty_result"},
    )

    assert calls == 1
    assert result.final_status == "failed"
    assert result.final_error_type == "timeout"
    assert result.diagnostics[0].retry_scheduled is False


@pytest.mark.asyncio
async def test_retry_wrapper_stops_after_one_retry_failure() -> None:
    calls = 0

    async def operation() -> dict[str, str]:
        nonlocal calls
        calls += 1
        raise StatusCodeError(422)

    result = await run_deep_import_llm_with_retry(operation)

    assert calls == 2
    assert result.attempts == 2
    assert result.final_status == "failed"
    assert result.final_error_type == "422"
    assert [d.error_type for d in result.diagnostics] == ["422", "422"]
    assert result.diagnostics[1].retry_scheduled is False


@pytest.mark.asyncio
async def test_retry_wrapper_does_not_retry_schema_errors() -> None:
    calls = 0

    async def operation() -> dict[str, str]:
        nonlocal calls
        calls += 1
        raise LLMInvalidResponseError("Schema validation failed")

    result = await run_deep_import_llm_with_retry(operation)

    assert calls == 1
    assert result.attempts == 1
    assert result.final_status == "failed"
    assert result.final_error_type == "schema_error"
    assert result.diagnostics[0].retry_scheduled is False


@pytest.mark.asyncio
async def test_retry_wrapper_never_retries_schema_errors_from_custom_policy() -> None:
    calls = 0

    async def operation() -> dict[str, str]:
        nonlocal calls
        calls += 1
        raise LLMInvalidResponseError("Schema validation failed")

    result = await run_deep_import_llm_with_retry(
        operation,
        retryable_error_types={"schema_error"},
    )

    assert calls == 1
    assert result.attempts == 1
    assert result.final_status == "failed"
    assert result.final_error_type == "schema_error"
    assert result.diagnostics[0].retry_scheduled is False


@pytest.mark.asyncio
async def test_retry_wrapper_retries_empty_result_once_then_succeeds() -> None:
    calls = 0

    async def operation() -> list[dict[str, str]]:
        nonlocal calls
        calls += 1
        if calls == 1:
            return []
        return [{"ok": "yes"}]

    result = await run_deep_import_llm_with_retry(
        operation,
        is_empty_result=lambda value: not value,
    )

    assert calls == 2
    assert result.attempts == 2
    assert result.final_status == "success"
    assert result.final_error_type is None
    assert result.value == [{"ok": "yes"}]
    assert [d.error_type for d in result.diagnostics] == ["empty_result", None]
    assert result.diagnostics[0].retry_scheduled is True


@pytest.mark.asyncio
async def test_retry_wrapper_does_not_retry_empty_result_without_budget() -> None:
    calls = 0

    async def operation() -> list[dict[str, str]]:
        nonlocal calls
        calls += 1
        return []

    result = await run_deep_import_llm_with_retry(
        operation,
        is_empty_result=lambda value: not value,
        max_retries=0,
    )

    assert calls == 1
    assert result.attempts == 1
    assert result.final_status == "failed"
    assert result.final_error_type == "empty_result"
    assert result.diagnostics[0].retry_scheduled is False


def test_final_422_rate_after_retry_drives_blocking_threshold() -> None:
    results = [
        failed_retry_result("422"),
        failed_retry_result("422"),
        failed_retry_result("422"),
        failed_retry_result("timeout"),
        failed_retry_result("schema_error"),
    ]

    assert final_422_rate_after_retry(results) == 0.6
    assert exceeds_final_422_rate_after_retry(results, threshold=0.40) is True
