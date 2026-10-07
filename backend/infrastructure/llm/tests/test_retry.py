"""LLM 重试逻辑测试"""

from __future__ import annotations

import logging

import pytest

from infrastructure.llm.errors import (
    LLMAuthError,
    LLMConnectionError,
    LLMContentFilterError,
    LLMError,
    LLMInvalidResponseError,
    LLMRateLimitError,
    LLMTimeoutError,
)
from infrastructure.llm.limits import LLMCircuitBreakerOpenError
from infrastructure.llm.retry import (
    is_retryable_llm_error,
    is_retryable_transport_error,
    retry_with_backoff,
)


@pytest.fixture
def retry_waits(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Capture deterministic backoff delays without waiting in real time."""
    waits: list[float] = []

    async def capture_sleep(delay: float) -> None:
        waits.append(delay)

    monkeypatch.setattr("infrastructure.llm.retry.asyncio.sleep", capture_sleep)
    monkeypatch.setattr(
        "infrastructure.llm.retry.random.uniform",
        lambda _minimum, _maximum: 1.0,
    )
    return waits


class TestIsRetryable:
    def test_timeout_is_retryable(self) -> None:
        assert is_retryable_transport_error(
            LLMTimeoutError("timeout", provider="test", model="m")
        )

    def test_rate_limit_is_retryable(self) -> None:
        assert is_retryable_transport_error(
            LLMRateLimitError("rate limited", provider="test", model="m", retry_after=5),
        )

    def test_connection_is_retryable(self) -> None:
        assert is_retryable_transport_error(
            LLMConnectionError("disconnected", provider="test")
        )

    def test_open_circuit_is_retryable_for_task_attempt(self) -> None:
        assert is_retryable_llm_error(LLMCircuitBreakerOpenError(retry_after=1.0))

    def test_auth_not_retryable(self) -> None:
        assert not is_retryable_transport_error(
            LLMAuthError("auth", provider="test", model="m")
        )

    def test_content_filter_not_retryable(self) -> None:
        assert not is_retryable_transport_error(
            LLMContentFilterError("filtered", provider="test", model="m"),
        )

    def test_invalid_response_not_retryable(self) -> None:
        assert not is_retryable_transport_error(
            LLMInvalidResponseError("bad response", provider="test"),
        )

    def test_only_explicit_temporary_provider_error_is_retryable(self) -> None:
        assert is_retryable_llm_error(
            LLMError(
                "temporary",
                provider="test",
                model="m",
                error_kind="server_error",
            )
        )
        assert not is_retryable_llm_error(
            LLMError("generic", provider="test", model="m")
        )

    def test_unknown_error_not_retryable(self) -> None:
        assert not is_retryable_transport_error(ValueError("something else"))


class TestWrappedErrorChain:
    """业务层把原始 LLM 错误包装成 RuntimeError 后，判定沿异常链回溯。"""

    @staticmethod
    def _wrapped(inner: Exception) -> Exception:
        """模拟生产代码 `raise RuntimeError(msg) from inner` 后被捕获的形态。"""
        try:
            raise RuntimeError(f"{type(inner).__name__}: {inner}") from inner
        except RuntimeError as wrapper:
            return wrapper

    @staticmethod
    def _deep_chain(links: int, tail: Exception) -> Exception:
        """用 links 层 RuntimeError 包装 tail，返回最外层异常。"""
        head: Exception = tail
        for _ in range(links):
            wrapper: Exception = RuntimeError("wrapper")
            wrapper.__cause__ = head
            head = wrapper
        return head

    def test_wrapped_rate_limit_is_retryable(self) -> None:
        inner = LLMRateLimitError(
            "rate limited", provider="test", model="m", retry_after=5
        )
        assert is_retryable_llm_error(self._wrapped(inner)) is True

    def test_wrapped_auth_is_not_retryable(self) -> None:
        inner = LLMAuthError("auth", provider="test", model="m")
        assert is_retryable_llm_error(self._wrapped(inner)) is False

    def test_wrapped_timeout_is_retryable(self) -> None:
        assert is_retryable_llm_error(self._wrapped(TimeoutError("boom"))) is True

    def test_plain_runtime_error_without_cause_is_not_retryable(self) -> None:
        assert is_retryable_llm_error(RuntimeError("plain")) is False

    def test_non_retryable_wins_over_retryable_in_chain(self) -> None:
        # 链上同时出现限流（可重试）与认证失败（不可重试）：不可重试优先。
        head = RuntimeError("head")
        middle = LLMRateLimitError(
            "rate limited", provider="test", model="m", retry_after=1
        )
        head.__cause__ = middle
        middle.__cause__ = LLMAuthError("auth", provider="test", model="m")
        assert is_retryable_llm_error(head) is False

    def test_transport_policy_keeps_wrapped_auth_terminal(self) -> None:
        wrapper = self._wrapped(LLMAuthError("auth", provider="test", model="m"))
        assert not is_retryable_transport_error(wrapper)

    def test_suppressed_context_is_still_considered(self) -> None:
        # `raise ... from None` 抹掉 cause 但隐式 __context__ 仍在：
        # 存量 from None 调用点的原始瞬时错误也应被识别。
        try:
            try:
                raise LLMTimeoutError("timeout", provider="test", model="m")
            except Exception:
                raise RuntimeError("suppressed") from None
        except RuntimeError as wrapper:
            suppressed = wrapper
        assert is_retryable_llm_error(suppressed) is True

    def test_cause_loop_terminates(self) -> None:
        looped: Exception = RuntimeError("looped")
        looped.__cause__ = looped
        assert is_retryable_llm_error(looped) is False

        first: Exception = RuntimeError("a")
        second: Exception = RuntimeError("b")
        first.__cause__ = second
        second.__cause__ = first
        assert is_retryable_llm_error(first) is False

    def test_chain_depth_is_bounded(self) -> None:
        tail = LLMRateLimitError(
            "rate limited", provider="test", model="m", retry_after=1
        )
        # 深度内：回溯能识别底层限流错误。
        assert is_retryable_llm_error(self._deep_chain(3, tail)) is True
        # 超过最大回溯深度：判定为不可重试，且不因深链/循环崩溃。
        assert is_retryable_llm_error(self._deep_chain(10, tail)) is False


class TestRetryWithBackoff:
    @pytest.mark.asyncio
    async def test_generic_llm_error_keeps_legacy_transport_retry(
        self,
        retry_waits: list[float],
    ) -> None:
        calls = 0

        async def eventually_succeed() -> str:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise LLMError("generic", provider="test", model="m")
            return "ok"

        assert await retry_with_backoff(eventually_succeed, max_attempts=2) == "ok"
        assert calls == 2
        assert retry_waits == [1.0]

    @pytest.mark.asyncio
    async def test_success_first_attempt(self, retry_waits: list[float]) -> None:
        """第一次成功，不应重试"""
        call_count = 0

        async def succeed() -> str:
            nonlocal call_count
            call_count += 1
            return "ok"

        result = await retry_with_backoff(succeed, max_attempts=3, base_delay=0.01)
        assert result == "ok"
        assert call_count == 1
        assert retry_waits == []

    @pytest.mark.asyncio
    async def test_retry_then_succeed(self, retry_waits: list[float]) -> None:
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
        assert retry_waits == [1.0, 1.0]

    @pytest.mark.asyncio
    async def test_all_attempts_fail(self, retry_waits: list[float]) -> None:
        """所有重试都失败，应抛出异常"""
        call_count = 0

        async def always_fail() -> str:
            nonlocal call_count
            call_count += 1
            raise LLMTimeoutError("timeout", provider="test", model="m")

        with pytest.raises(LLMTimeoutError):
            await retry_with_backoff(always_fail, max_attempts=2, base_delay=0.01)
        assert call_count == 2
        assert retry_waits == [1.0]

    @pytest.mark.asyncio
    async def test_non_retryable_raises_immediately(
        self,
        retry_waits: list[float],
    ) -> None:
        """不可重试错误不应重试"""
        call_count = 0

        async def auth_fail() -> str:
            nonlocal call_count
            call_count += 1
            raise LLMAuthError("bad key", provider="test", model="m")

        with pytest.raises(LLMAuthError):
            await retry_with_backoff(auth_fail, max_attempts=3, base_delay=0.01)
        assert call_count == 1
        assert retry_waits == []

    @pytest.mark.asyncio
    async def test_retry_logs_redact_credentials(
        self,
        retry_waits: list[float],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        secret = "private-retry-token-value"

        async def auth_fail() -> str:
            raise LLMAuthError(
                f"Authorization: Bearer {secret} api_key={secret}",
                provider="test",
                model="m",
            )

        with caplog.at_level(logging.WARNING, logger="infrastructure.llm.retry"):
            with pytest.raises(LLMAuthError):
                await retry_with_backoff(auth_fail, max_attempts=2)

        assert secret not in caplog.text
        assert "[REDACTED]" in caplog.text
        assert retry_waits == []


class TestDeadlineAwareBackoff:
    """完整 delay 会跨过活动信封剩余 deadline 时立即停止，不 sleep 不再请求。"""

    def _envelope_with_remaining(
        self,
        monkeypatch: pytest.MonkeyPatch,
        remaining: float | None,
    ) -> None:
        from infrastructure.llm import retry as retry_module

        monkeypatch.setattr(
            retry_module,
            "ai_run_remaining_seconds",
            lambda: remaining,
        )

    @pytest.mark.asyncio
    async def test_no_envelope_sleeps_as_before(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        waits: list[float] = []

        async def capture_sleep(delay: float) -> None:
            waits.append(delay)

        monkeypatch.setattr("infrastructure.llm.retry.asyncio.sleep", capture_sleep)
        from infrastructure.llm.retry import sleep_before_retry

        await sleep_before_retry(30.0, last_error=None)
        assert waits == [30.0]

    @pytest.mark.asyncio
    async def test_delay_crossing_deadline_raises_original_error(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        waits: list[float] = []

        async def capture_sleep(delay: float) -> None:
            waits.append(delay)

        monkeypatch.setattr("infrastructure.llm.retry.asyncio.sleep", capture_sleep)
        self._envelope_with_remaining(monkeypatch, remaining=2.0)
        from infrastructure.llm.retry import sleep_before_retry

        original = LLMTimeoutError("timeout", provider="test", model="m")
        with pytest.raises(LLMTimeoutError) as exc_info:
            await sleep_before_retry(30.0, last_error=original)
        assert exc_info.value is original
        assert waits == []

    @pytest.mark.asyncio
    async def test_delay_within_deadline_sleeps(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        waits: list[float] = []

        async def capture_sleep(delay: float) -> None:
            waits.append(delay)

        monkeypatch.setattr("infrastructure.llm.retry.asyncio.sleep", capture_sleep)
        self._envelope_with_remaining(monkeypatch, remaining=60.0)
        from infrastructure.llm.retry import sleep_before_retry

        await sleep_before_retry(5.0, last_error=None)
        assert waits == [5.0]

    @pytest.mark.asyncio
    async def test_transport_retry_stops_when_delay_crosses_deadline(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """transport 退避跨过 deadline：保留原始错误类型，不再发起下一次请求。"""
        calls = 0

        async def always_timeout() -> str:
            nonlocal calls
            calls += 1
            raise LLMTimeoutError("timeout", provider="test", model="m")

        waits: list[float] = []

        async def capture_sleep(delay: float) -> None:
            waits.append(delay)

        monkeypatch.setattr("infrastructure.llm.retry.asyncio.sleep", capture_sleep)
        monkeypatch.setattr(
            "infrastructure.llm.retry.random.uniform",
            lambda _minimum, _maximum: 1.0,
        )
        self._envelope_with_remaining(monkeypatch, remaining=1.0)

        with pytest.raises(LLMTimeoutError):
            await retry_with_backoff(always_timeout, max_attempts=3, base_delay=30.0)
        # deadline 只够覆盖决定重试，但覆盖不了 30s 退避：不 sleep，也不再请求。
        assert calls == 1
        assert waits == []
