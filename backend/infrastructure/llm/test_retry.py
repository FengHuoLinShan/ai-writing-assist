"""LLM 重试逻辑测试"""

from __future__ import annotations

import pytest

from infrastructure.llm.errors import (
    LLMAuthError,
    LLMContentFilterError,
    LLMError,
    LLMInvalidResponseError,
    LLMRateLimitError,
    LLMTimeoutError,
)
from infrastructure.llm.retry import _is_retryable, retry_with_backoff


class TestIsRetryable:
    def test_timeout_is_retryable(self) -> None:
        assert _is_retryable(LLMTimeoutError("timeout", provider="test", model="m"))

    def test_rate_limit_is_retryable(self) -> None:
        assert _is_retryable(
            LLMRateLimitError("rate limited", provider="test", model="m", retry_after=5),
        )

    def test_auth_not_retryable(self) -> None:
        assert not _is_retryable(LLMAuthError("auth", provider="test", model="m"))

    def test_content_filter_not_retryable(self) -> None:
        assert not _is_retryable(
            LLMContentFilterError("filtered", provider="test", model="m"),
        )

    def test_invalid_response_not_retryable(self) -> None:
        assert not _is_retryable(
            LLMInvalidResponseError("bad response", provider="test"),
        )

    def test_generic_llm_error_is_retryable(self) -> None:
        assert _is_retryable(LLMError("generic", provider="test", model="m"))

    def test_unknown_error_not_retryable(self) -> None:
        assert not _is_retryable(ValueError("something else"))


class TestRetryWithBackoff:
    @pytest.mark.asyncio
    async def test_success_first_attempt(self) -> None:
        """第一次成功，不应重试"""
        call_count = 0

        async def succeed() -> str:
            nonlocal call_count
            call_count += 1
            return "ok"

        result = await retry_with_backoff(succeed, max_attempts=3, base_delay=0.01)
        assert result == "ok"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_retry_then_succeed(self) -> None:
        """前两次失败，第三次成功"""
        call_count = 0

        async def eventually_succeed() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise LLMTimeoutError("timeout", provider="test", model="m")
            return "ok"

        result = await retry_with_backoff(
            eventually_succeed,
            max_attempts=3,
            base_delay=0.01,
        )
        assert result == "ok"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_all_attempts_fail(self) -> None:
        """所有重试都失败，应抛出异常"""
        call_count = 0

        async def always_fail() -> str:
            nonlocal call_count
            call_count += 1
            raise LLMTimeoutError("timeout", provider="test", model="m")

        with pytest.raises(LLMTimeoutError):
            await retry_with_backoff(always_fail, max_attempts=2, base_delay=0.01)
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_non_retryable_raises_immediately(self) -> None:
        """不可重试错误不应重试"""
        call_count = 0

        async def auth_fail() -> str:
            nonlocal call_count
            call_count += 1
            raise LLMAuthError("bad key", provider="test", model="m")

        with pytest.raises(LLMAuthError):
            await retry_with_backoff(auth_fail, max_attempts=3, base_delay=0.01)
        assert call_count == 1
