"""Process-local HTTP token-bucket middleware.

The limiter keys requests by the final ASGI scope client and never parses forwarding
headers. In production, Uvicorn may normalize that scope from edge-sanitized XFF.
"""

from __future__ import annotations

import math
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


@dataclass
class _TokenBucket:
    tokens: float
    updated_at: float


class HttpRateLimitMiddleware:
    """Bound per-process HTTP request rate by the final ASGI scope client.

    A zero rate explicitly disables the limiter for local development and tests.
    Deployment configuration validation prevents that setting outside local
    runtimes. Each worker owns its own buckets, so a future multi-worker deployment
    must divide the intended aggregate allowance across workers.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        requests_per_minute: int,
        burst: int,
        max_clients: int = 10_000,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if requests_per_minute < 0:
            raise ValueError("requests_per_minute must be non-negative")
        if burst < 0:
            raise ValueError("burst must be non-negative")
        if requests_per_minute > 0 and burst == 0:
            raise ValueError("burst must be positive when rate limiting is enabled")
        if max_clients <= 0:
            raise ValueError("max_clients must be positive")

        self.app = app
        self.requests_per_minute = requests_per_minute
        self.burst = burst
        self.max_clients = max_clients
        self._clock = clock
        self._buckets: OrderedDict[str, _TokenBucket] = OrderedDict()
        self._overflow_bucket: _TokenBucket | None = None
        self._last_now: float | None = None
        self._lock = threading.Lock()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        method = scope.get("method")
        if (
            scope.get("type") != "http"
            or self.requests_per_minute == 0
            or (isinstance(method, str) and method.upper() == "OPTIONS")
        ):
            await self.app(scope, receive, send)
            return

        allowed, retry_after = self._consume(_direct_peer_key(scope))
        if not allowed:
            response = JSONResponse(
                status_code=429,
                content={"detail": "Too many requests"},
                headers={
                    "Retry-After": str(retry_after),
                    "Cache-Control": "no-store",
                },
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)

    def _consume(self, client_key: str) -> tuple[bool, int]:
        observed_now = self._clock()
        refill_per_second = self.requests_per_minute / 60.0
        with self._lock:
            # A monotonic clock should never move backwards, but clamping here keeps
            # an injected/test clock or rare platform anomaly from granting tokens
            # twice after a rollback. Non-finite readings conservatively freeze time.
            if math.isfinite(observed_now):
                previous_now = observed_now if self._last_now is None else self._last_now
                now = max(observed_now, previous_now)
                self._last_now = now
            else:
                now = 0.0 if self._last_now is None else self._last_now

            bucket = self._buckets.pop(client_key, None)
            if bucket is None:
                if len(self._buckets) >= self.max_clients:
                    oldest_key, oldest = next(iter(self._buckets.items()))
                    self._refill(oldest, now, refill_per_second)
                    if oldest.tokens >= float(self.burst):
                        del self._buckets[oldest_key]
                    else:
                        # Do not reset a still-depleted client merely because new
                        # peer identities churn through the bounded table. Excess
                        # identities share one conservative overflow bucket.
                        if self._overflow_bucket is None:
                            self._overflow_bucket = _TokenBucket(
                                tokens=float(self.burst),
                                updated_at=now,
                            )
                        return self._consume_bucket(
                            self._overflow_bucket,
                            now,
                            refill_per_second,
                        )
                bucket = _TokenBucket(tokens=float(self.burst), updated_at=now)
            else:
                self._refill(bucket, now, refill_per_second)

            self._buckets[client_key] = bucket
            return self._consume_bucket(bucket, now, refill_per_second)

    def _consume_bucket(
        self,
        bucket: _TokenBucket,
        now: float,
        refill_per_second: float,
    ) -> tuple[bool, int]:
        self._refill(bucket, now, refill_per_second)
        if bucket.tokens >= 1.0:
            bucket.tokens -= 1.0
            return True, 0

        retry_after = max(
            1,
            math.ceil((1.0 - bucket.tokens) / refill_per_second),
        )
        return False, retry_after

    def _refill(
        self,
        bucket: _TokenBucket,
        now: float,
        refill_per_second: float,
    ) -> None:
        elapsed = max(0.0, now - bucket.updated_at)
        bucket.tokens = min(
            float(self.burst),
            bucket.tokens + elapsed * refill_per_second,
        )
        bucket.updated_at = max(bucket.updated_at, now)


def _direct_peer_key(scope: Scope) -> str:
    """Return a bounded final scope-client key without parsing forwarding headers."""
    client = scope.get("client")
    if (
        isinstance(client, (tuple, list))
        and client
        and isinstance(client[0], str)
        and client[0]
    ):
        return client[0][:128]
    return "<unknown>"
