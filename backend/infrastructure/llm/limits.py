"""Process-local LLM concurrency, rate, and availability limits."""

from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from time import monotonic
from typing import TypeVar
from urllib.parse import urlsplit

from core.config import get_settings
from infrastructure.llm.errors import (
    LLMAuthError,
    LLMConnectionError,
    LLMContentFilterError,
    LLMError,
    LLMInvalidResponseError,
    LLMRateLimitError,
    LLMTimeoutError,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")
_MAX_BREAKER_BUCKETS = 256
_HALF_OPEN_RETRY_SECONDS = 1.0


class LLMCircuitBreakerOpenError(LLMError):
    """Raised when recent provider failures have opened the local breaker."""

    def __init__(self, *, retry_after: float) -> None:
        self.retry_after = retry_after
        super().__init__(
            f"LLM circuit breaker is open; retry after {retry_after:.1f}s",
            error_kind="circuit_breaker_open",
        )


@dataclass(frozen=True)
class LLMLimiterScope:
    """Secret-free identity for one process-local availability bucket."""

    owner: str
    operation_kind: str
    endpoint: str

    @classmethod
    def for_call(
        cls,
        *,
        novel_id: str | None,
        operation_kind: str,
        base_url: str,
        provider_id: str,
    ) -> LLMLimiterScope:
        owner = f"project:{novel_id}" if novel_id else "system"
        operation = str(operation_kind or "chat").strip().lower() or "chat"
        endpoint = _normalize_endpoint(base_url, provider_id=provider_id)
        return cls(owner=owner, operation_kind=operation, endpoint=endpoint)


@dataclass(frozen=True)
class _LimiterConfig:
    max_concurrent_requests: int
    rate_limit_per_minute: int
    circuit_breaker_failure_threshold: int
    circuit_breaker_reset_seconds: float


@dataclass
class _BreakerState:
    failure_count: int
    opened_at: float | None
    half_open_probe: bool
    last_touched_at: float


_LEGACY_SCOPE = LLMLimiterScope(
    owner="system",
    operation_kind="chat",
    endpoint="provider:legacy",
)


class LLMProcessLimiter:
    """Process-local global admission control with scoped availability breakers."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._config: _LimiterConfig | None = None
        self._semaphore: asyncio.Semaphore | None = None
        self._tokens = 0.0
        self._last_refill_at = monotonic()
        self._breakers: OrderedDict[LLMLimiterScope, _BreakerState] = OrderedDict()

    async def run(
        self,
        fn: Callable[[], Awaitable[T]],
        *,
        limiter_scope: LLMLimiterScope | None = None,
    ) -> T:
        """Run one provider operation under global and scoped limits."""
        async with self.scope(limiter_scope=limiter_scope):
            return await fn()

    @asynccontextmanager
    async def scope(
        self,
        *,
        limiter_scope: LLMLimiterScope | None = None,
    ):
        """Hold global admission limits for one scoped provider operation."""
        await self._ensure_ready()
        bucket = limiter_scope or _LEGACY_SCOPE
        half_open_probe = await self._begin_breaker_request(bucket)
        try:
            await self._wait_for_rate_token()
            semaphore = self._semaphore
            if semaphore is None:
                raise RuntimeError("LLM limiter semaphore was not initialized")

            async with semaphore:
                try:
                    yield
                except Exception as exc:
                    if _counts_toward_circuit_breaker(exc):
                        await self.record_failure(bucket)
                    elif _proves_provider_available(exc):
                        await self.record_success(bucket)
                    else:
                        await self._release_half_open_probe(
                            bucket,
                            half_open_probe=half_open_probe,
                        )
                    raise
                else:
                    await self.record_success(bucket)
        except BaseException:
            await self._release_half_open_probe(
                bucket,
                half_open_probe=half_open_probe,
            )
            raise

    async def record_success(
        self,
        limiter_scope: LLMLimiterScope | None = None,
    ) -> None:
        bucket = limiter_scope or _LEGACY_SCOPE
        async with self._lock:
            self._breakers.pop(bucket, None)

    async def record_failure(
        self,
        limiter_scope: LLMLimiterScope | None = None,
    ) -> None:
        bucket = limiter_scope or _LEGACY_SCOPE
        async with self._lock:
            config = self._active_config()
            threshold = config.circuit_breaker_failure_threshold
            if threshold <= 0:
                self._breakers.pop(bucket, None)
                return

            now = monotonic()
            state = self._breakers.get(bucket)
            if state is None:
                state = self._create_breaker_state(bucket, now=now)
                if state is None:
                    return

            if state.half_open_probe or state.opened_at is not None:
                state.failure_count = max(state.failure_count, threshold)
                state.opened_at = now
                state.half_open_probe = False
            else:
                state.failure_count += 1
                if state.failure_count >= threshold:
                    state.opened_at = now
            state.last_touched_at = now
            self._breakers.move_to_end(bucket)

    async def _ensure_ready(self) -> None:
        config = _settings_config()
        async with self._lock:
            if config == self._config and self._semaphore is not None:
                return
            self._config = config
            self._semaphore = asyncio.Semaphore(config.max_concurrent_requests)
            self._tokens = float(config.rate_limit_per_minute)
            self._last_refill_at = monotonic()
            self._breakers.clear()

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

    async def _begin_breaker_request(self, bucket: LLMLimiterScope) -> bool:
        async with self._lock:
            config = self._active_config()
            if config.circuit_breaker_failure_threshold <= 0:
                return False
            state = self._breakers.get(bucket)
            if state is None or state.opened_at is None:
                return False

            now = monotonic()
            state.last_touched_at = now
            self._breakers.move_to_end(bucket)
            elapsed = now - state.opened_at
            if elapsed < config.circuit_breaker_reset_seconds:
                raise LLMCircuitBreakerOpenError(
                    retry_after=config.circuit_breaker_reset_seconds - elapsed
                )
            if state.half_open_probe:
                raise LLMCircuitBreakerOpenError(retry_after=_HALF_OPEN_RETRY_SECONDS)
            state.half_open_probe = True
            return True

    async def _release_half_open_probe(
        self,
        bucket: LLMLimiterScope,
        *,
        half_open_probe: bool,
    ) -> None:
        if not half_open_probe:
            return
        async with self._lock:
            state = self._breakers.get(bucket)
            if state is not None and state.half_open_probe:
                state.half_open_probe = False
                state.last_touched_at = monotonic()
                self._breakers.move_to_end(bucket)

    def _create_breaker_state(
        self,
        bucket: LLMLimiterScope,
        *,
        now: float,
    ) -> _BreakerState | None:
        if len(self._breakers) >= _MAX_BREAKER_BUCKETS:
            eviction_key = next(
                (
                    key
                    for key, state in self._breakers.items()
                    if not state.half_open_probe
                ),
                None,
            )
            if eviction_key is None:
                logger.warning(
                    "LLM breaker registry is saturated with active probes; "
                    "new availability failure will not be retained"
                )
                return None
            self._breakers.pop(eviction_key, None)

        state = _BreakerState(
            failure_count=0,
            opened_at=None,
            half_open_probe=False,
            last_touched_at=now,
        )
        self._breakers[bucket] = state
        return state

    def _active_config(self) -> _LimiterConfig:
        if self._config is None:
            self._config = _settings_config()
        return self._config


_PROCESS_LIMITER = LLMProcessLimiter()


def get_llm_limiter() -> LLMProcessLimiter:
    return _PROCESS_LIMITER


def _counts_toward_circuit_breaker(exc: Exception) -> bool:
    """Count provider availability failures, not deterministic request errors."""
    if isinstance(
        exc,
        (LLMAuthError, LLMContentFilterError, LLMInvalidResponseError),
    ):
        return False
    return isinstance(
        exc,
        (LLMConnectionError, LLMRateLimitError, LLMTimeoutError, LLMError),
    )


def _proves_provider_available(exc: Exception) -> bool:
    return isinstance(
        exc,
        (LLMAuthError, LLMContentFilterError, LLMInvalidResponseError),
    )


def _normalize_endpoint(base_url: str, *, provider_id: str) -> str:
    raw_url = str(base_url or "").strip()
    if raw_url:
        try:
            parsed = urlsplit(raw_url)
            scheme = parsed.scheme.lower()
            host = (parsed.hostname or "").lower()
            port = parsed.port
        except ValueError:
            scheme = ""
            host = ""
            port = None
        if scheme and host:
            default_port = (scheme == "https" and port == 443) or (
                scheme == "http" and port == 80
            )
            port_part = "" if port is None or default_port else f":{port}"
            path = parsed.path.rstrip("/")
            return f"{scheme}://{host}{port_part}{path}"

    safe_provider = str(provider_id or "unknown").strip().lower() or "unknown"
    return f"provider:{safe_provider}"


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
