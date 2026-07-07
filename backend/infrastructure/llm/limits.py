"""Process-local LLM concurrency, rate, and circuit-breaker limits."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from time import monotonic
from typing import TypeVar

from core.config import get_settings
from infrastructure.llm.errors import LLMError

T = TypeVar("T")


class LLMCircuitBreakerOpenError(LLMError):
    """Raised when recent provider failures have opened the local breaker."""

    def __init__(self, *, retry_after: float) -> None:
        self.retry_after = retry_after
        super().__init__(
            f"LLM circuit breaker is open; retry after {retry_after:.1f}s",
            error_kind="circuit_breaker_open",
        )


@dataclass(frozen=True)
class _LimiterConfig:
    max_concurrent_requests: int
    rate_limit_per_minute: int
    circuit_breaker_failure_threshold: int
    circuit_breaker_reset_seconds: float


class LLMProcessLimiter:
    """Process-local limiter shared by all LLMClient instances."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._config: _LimiterConfig | None = None
        self._semaphore: asyncio.Semaphore | None = None
        self._tokens = 0.0
        self._last_refill_at = monotonic()
        self._failure_count = 0
        self._opened_at: float | None = None

    async def run(self, fn: Callable[[], Awaitable[T]]) -> T:
        """Run one provider operation under local limits."""
        async with self.scope():
            return await fn()

    @asynccontextmanager
    async def scope(self):
        """Hold local limits for the lifetime of one provider operation."""
        await self._ensure_ready()
        await self._wait_for_rate_token()
        semaphore = self._semaphore
        if semaphore is None:
            raise RuntimeError("LLM limiter semaphore was not initialized")

        async with semaphore:
            await self._raise_if_circuit_open()
            try:
                yield
            except Exception:
                await self.record_failure()
                raise
            await self.record_success()

    async def record_success(self) -> None:
        async with self._lock:
            self._failure_count = 0
            self._opened_at = None

    async def record_failure(self) -> None:
        async with self._lock:
            config = self._active_config()
            threshold = config.circuit_breaker_failure_threshold
            if threshold <= 0:
                return
            self._failure_count += 1
            if self._failure_count >= threshold:
                self._opened_at = monotonic()

    async def _ensure_ready(self) -> None:
        config = _settings_config()
        async with self._lock:
            if config == self._config and self._semaphore is not None:
                return
            self._config = config
            self._semaphore = asyncio.Semaphore(config.max_concurrent_requests)
            self._tokens = float(config.rate_limit_per_minute)
            self._last_refill_at = monotonic()
            self._failure_count = 0
            self._opened_at = None

    async def _wait_for_rate_token(self) -> None:
        while True:
            async with self._lock:
                config = self._active_config()
                per_minute = config.rate_limit_per_minute
                if per_minute <= 0:
                    return

                now = monotonic()
                elapsed = now - self._last_refill_at
                self._last_refill_at = now
                self._tokens = min(
                    float(per_minute),
                    self._tokens + elapsed * (per_minute / 60.0),
                )
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return

                wait_seconds = (1.0 - self._tokens) * 60.0 / per_minute
            await asyncio.sleep(wait_seconds)

    async def _raise_if_circuit_open(self) -> None:
        async with self._lock:
            config = self._active_config()
            if self._opened_at is None:
                return
            elapsed = monotonic() - self._opened_at
            if elapsed >= config.circuit_breaker_reset_seconds:
                self._failure_count = 0
                self._opened_at = None
                return
            raise LLMCircuitBreakerOpenError(
                retry_after=config.circuit_breaker_reset_seconds - elapsed
            )

    def _active_config(self) -> _LimiterConfig:
        if self._config is None:
            self._config = _settings_config()
        return self._config


_PROCESS_LIMITER = LLMProcessLimiter()


def get_llm_limiter() -> LLMProcessLimiter:
    return _PROCESS_LIMITER


def reset_llm_limiter_for_tests() -> None:
    global _PROCESS_LIMITER
    _PROCESS_LIMITER = LLMProcessLimiter()


def _settings_config() -> _LimiterConfig:
    settings = get_settings()
    return _LimiterConfig(
        max_concurrent_requests=max(1, int(settings.llm_max_concurrent_requests)),
        rate_limit_per_minute=max(0, int(settings.llm_rate_limit_per_minute)),
        circuit_breaker_failure_threshold=max(
            0,
            int(settings.llm_circuit_breaker_failure_threshold),
        ),
        circuit_breaker_reset_seconds=max(
            0.0,
            float(settings.llm_circuit_breaker_reset_seconds),
        ),
    )
