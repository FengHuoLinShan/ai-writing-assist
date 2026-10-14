"""Process-local LLM concurrency, rate, and availability limits."""

from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from contextlib import AsyncExitStack, asynccontextmanager, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from time import monotonic
from typing import TypeVar
from urllib.parse import urlsplit

from core.config import get_settings
from infrastructure.llm.errors import (
    LLMAdmissionStoppedError,
    LLMAuthError,
    LLMConnectionError,
    LLMContentFilterError,
    LLMError,
    LLMInvalidResponseError,
    LLMQuotaError,
    LLMRateLimitError,
    LLMTimeoutError,
)
from infrastructure.llm.model_limits import get_model_limits, model_source

logger = logging.getLogger(__name__)

T = TypeVar("T")
_MAX_BREAKER_BUCKETS = 256
_HALF_OPEN_RETRY_SECONDS = 1.0


_request_stops: ContextVar[tuple[asyncio.Event, ...]] = ContextVar(
    "llm_request_stops", default=()
)


@contextmanager
def request_admission_scope(stop: asyncio.Event):
    token = _request_stops.set((*_request_stops.get(), stop))
    try:
        yield
    finally:
        _request_stops.reset(token)


def require_request_admission():
    if any(stop.is_set() for stop in _request_stops.get()):
        raise LLMAdmissionStoppedError()


def stop_request_admission(error=None):
    if isinstance(error, LLMInvalidResponseError) and error.usage is not None:
        return
    for stop in _request_stops.get():
        stop.set()


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
    provider_id: str = "legacy"
    model: str = "legacy"

    @classmethod
    def for_call(
        cls,
        *,
        novel_id: str | None,
        operation_kind: str,
        base_url: str,
        provider_id: str,
        model: str = "legacy",
    ) -> LLMLimiterScope:
        owner = f"project:{novel_id}" if novel_id else "system"
        operation = str(operation_kind or "chat").strip().lower() or "chat"
        endpoint = _normalize_endpoint(base_url, provider_id=provider_id)
        return cls(
            owner=owner,
            operation_kind=operation,
            endpoint=endpoint,
            provider_id=provider_id,
            model=model,
        )


@dataclass(frozen=True)
class _LimiterConfig:
    circuit_breaker_failure_threshold: int
    circuit_breaker_reset_seconds: float


@dataclass
class _ModelPool:
    concurrency: int
    rpm: int
    semaphore: asyncio.Semaphore
    tokens: float
    last_refill_at: float
    users: int = 0


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
    """Per-model admission with project/model availability breakers."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._config: _LimiterConfig | None = None
        self._pools: OrderedDict[tuple[str, ...], _ModelPool] = OrderedDict()
        self._breakers: OrderedDict[LLMLimiterScope, _BreakerState] = OrderedDict()

    async def run(
        self,
        fn: Callable[[], Awaitable[T]],
        *,
        limiter_scope: LLMLimiterScope | None = None,
    ) -> T:
        """Run one provider operation under its model pool limits."""
        async with self.scope(limiter_scope=limiter_scope):
            return await fn()

    @asynccontextmanager
    async def scope(
        self,
        *,
        limiter_scope: LLMLimiterScope | None = None,
    ):
        """Hold one model pool admission for a provider operation."""
        require_request_admission()
        await self._ensure_ready()
        bucket = limiter_scope or _LEGACY_SCOPE
        half_open_probe = await self._begin_breaker_request(bucket)
        key = (
            model_source(bucket.provider_id),
            bucket.provider_id,
            bucket.endpoint,
            bucket.model,
        )
        if bucket.provider_id == "codex":
            from infrastructure.llm.codex_identity import codex_login_identity

            key = (*key, codex_login_identity())
        pool = None
        admitted = False
        account_admission = AsyncExitStack()
        try:
            pool = await self._pool(key, bucket)
            await self._acquire_semaphore(pool.semaphore)
            admitted = True
            require_request_admission()
            from infrastructure.llm.model_admission import model_admission

            await account_admission.enter_async_context(
                model_admission(key, pool.concurrency, rpm=pool.rpm)
            )
            await self._wait_for_rate_token(pool)
            require_request_admission()
            try:
                yield
            except Exception as exc:
                stop_request_admission(exc)
                if _counts_toward_circuit_breaker(exc):
                    await self.record_failure(bucket)
                elif _proves_provider_available(exc):
                    await self.record_success(bucket)
                else:
                    await self._release_half_open_probe(
                        bucket, half_open_probe=half_open_probe
                    )
                raise
            else:
                await self.record_success(bucket)
        except BaseException as exc:
            stop_request_admission(exc)
            await self._release_half_open_probe(bucket, half_open_probe=half_open_probe)
            raise
        finally:
            await account_admission.aclose()
            if admitted:
                pool.semaphore.release()
            if pool is not None:
                async with self._lock:
                    pool.users -= 1

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
        async with self._lock:
            self._config = _settings_config()

    async def _pool(self, key, bucket):
        limits = get_model_limits(
            bucket.provider_id, bucket.model, settings=get_settings()
        )
        while True:
            require_request_admission()
            async with self._lock:
                pool = self._pools.get(key)
                if pool and (pool.concurrency, pool.rpm) != (
                    limits.concurrency,
                    limits.rpm,
                ):
                    if pool.users:
                        pool = "waiting"
                    else:
                        pool = None
                if pool != "waiting":
                    if pool is None:
                        if (
                            key not in self._pools
                            and len(self._pools) >= _MAX_BREAKER_BUCKETS
                        ):
                            idle = next(
                                (k for k, v in self._pools.items() if not v.users), None
                            )
                            if idle is None:
                                raise LLMError(
                                    "模型池正在使用，请稍后重试",
                                    error_kind="model_admission_capacity",
                                )
                            self._pools.pop(idle)
                        pool = _ModelPool(
                            limits.concurrency,
                            limits.rpm,
                            asyncio.Semaphore(limits.concurrency),
                            float(limits.rpm),
                            monotonic(),
                        )
                        self._pools[key] = pool
                    pool.users += 1
                    self._pools.move_to_end(key)
                    return pool

            remaining = _ai_run_remaining_seconds()
            if remaining is not None and remaining <= 0:
                _raise_ai_run_deadline()
            await asyncio.sleep(min(0.025, remaining) if remaining is not None else 0.025)

    async def _wait_for_rate_token(self, pool) -> None:
        while pool.rpm > 0:
            require_request_admission()
            async with self._lock:
                now = monotonic()
                elapsed = now - pool.last_refill_at
                pool.last_refill_at = now
                pool.tokens = min(float(pool.rpm), pool.tokens + elapsed * pool.rpm / 60)
                if pool.tokens >= 1:
                    pool.tokens -= 1
                    return
                wait_seconds = (1 - pool.tokens) * 60 / pool.rpm
            remaining = _ai_run_remaining_seconds()
            if remaining is not None and wait_seconds >= remaining:
                _raise_ai_run_deadline()
            await asyncio.sleep(
                min(wait_seconds, 0.025) if _request_stops.get() else wait_seconds
            )

    @staticmethod
    async def _acquire_semaphore(semaphore: asyncio.Semaphore) -> None:
        while True:
            require_request_admission()
            remaining = _ai_run_remaining_seconds()
            if remaining is not None and remaining <= 0:
                _raise_ai_run_deadline()
            wait = min(0.025, remaining) if remaining is not None else 0.025
            if not _request_stops.get():
                wait = remaining
            try:
                async with asyncio.timeout(wait):
                    await semaphore.acquire()
                return
            except TimeoutError as exc:
                if not _request_stops.get():
                    _raise_ai_run_deadline(cause=exc)

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


def _ai_run_remaining_seconds() -> float | None:
    from infrastructure.llm.workflow_budget import current_ai_run_envelope

    envelope = current_ai_run_envelope()
    return envelope.remaining_seconds() if envelope is not None else None


def _raise_ai_run_deadline(*, cause: BaseException | None = None) -> None:
    from infrastructure.llm.workflow_budget import (
        AIRunDeadlineExceededError,
        current_ai_run_envelope,
    )

    envelope = current_ai_run_envelope()
    error = AIRunDeadlineExceededError(
        "run deadline passed while waiting for provider admission",
        run_id=envelope.run_id if envelope is not None else "",
    )
    if cause is not None:
        raise error from cause
    raise error


def get_llm_limiter() -> LLMProcessLimiter:
    return _PROCESS_LIMITER


def _counts_toward_circuit_breaker(exc: Exception) -> bool:
    """Count provider availability failures, not deterministic request errors."""
    if isinstance(exc, LLMError) and exc.error_kind in {
        "codex_configuration",
        "input_budget_exceeded",
        "context_policy_changed",
        "request_admission_stopped",
        "model_admission_configuration",
    }:
        return False
    if isinstance(
        exc,
        (
            LLMAuthError,
            LLMContentFilterError,
            LLMInvalidResponseError,
            LLMQuotaError,
        ),
    ):
        return False
    return isinstance(
        exc,
        (LLMConnectionError, LLMRateLimitError, LLMTimeoutError, LLMError),
    )


def _proves_provider_available(exc: Exception) -> bool:
    return isinstance(
        exc,
        (
            LLMAuthError,
            LLMContentFilterError,
            LLMInvalidResponseError,
            LLMQuotaError,
        ),
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
        circuit_breaker_failure_threshold=max(
            0,
            int(settings.llm_circuit_breaker_failure_threshold),
        ),
        circuit_breaker_reset_seconds=max(
            0.0,
            float(settings.llm_circuit_breaker_reset_seconds),
        ),
    )
