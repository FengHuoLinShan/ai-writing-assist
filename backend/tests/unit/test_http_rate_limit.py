from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app.http_rate_limit import HttpRateLimitMiddleware, _direct_peer_key
from app.main import _TimingMiddleware, app


def _limited_app(*, clock, rate: int = 60, burst: int = 2) -> FastAPI:
    test_app = FastAPI()
    test_app.add_middleware(
        HttpRateLimitMiddleware,
        requests_per_minute=rate,
        burst=burst,
        max_clients=8,
        clock=clock,
    )

    @test_app.get("/probe")
    async def _probe() -> dict[str, bool]:
        return {"ok": True}

    return test_app


def _edge_sanitized_limited_app(*, clock, rate: int = 60, burst: int = 2):
    return ProxyHeadersMiddleware(
        _limited_app(clock=clock, rate=rate, burst=burst),
        trusted_hosts="*",
    )


@pytest.mark.asyncio
async def test_token_bucket_rejects_burst_and_refills_with_retry_after() -> None:
    now = [100.0]
    test_app = _limited_app(clock=lambda: now[0])
    transport = ASGITransport(app=test_app, client=("198.51.100.8", 4000))

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.get("/probe")).status_code == 200
        assert (await client.get("/probe")).status_code == 200
        limited = await client.get("/probe")
        assert limited.status_code == 429
        assert limited.json() == {"detail": "Too many requests"}
        assert limited.headers["retry-after"] == "1"
        assert limited.headers["cache-control"] == "no-store"

        now[0] += 1.0
        assert (await client.get("/probe")).status_code == 200


@pytest.mark.asyncio
async def test_direct_peers_have_independent_buckets_and_ports_share_one() -> None:
    test_app = _limited_app(clock=lambda: 100.0, burst=1)

    async def status_for(peer: str, port: int) -> int:
        transport = ASGITransport(app=test_app, client=(peer, port))
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            return (await client.get("/probe")).status_code

    assert await status_for("198.51.100.1", 4000) == 200
    assert await status_for("198.51.100.1", 5000) == 429
    assert await status_for("198.51.100.2", 4000) == 200


@pytest.mark.asyncio
async def test_unwrapped_limiter_ignores_raw_forwarded_headers() -> None:
    test_app = _limited_app(clock=lambda: 100.0, burst=1)
    transport = ASGITransport(app=test_app, client=("192.0.2.10", 4000))

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        first = await client.get("/probe", headers={"X-Forwarded-For": "198.51.100.1"})
        second = await client.get("/probe", headers={"X-Forwarded-For": "198.51.100.2"})

    assert first.status_code == 200
    assert second.status_code == 429


@pytest.mark.asyncio
async def test_edge_sanitized_forwarded_client_uses_one_rate_limit_bucket() -> None:
    test_app = _edge_sanitized_limited_app(clock=lambda: 100.0, burst=1)
    transport = ASGITransport(app=test_app, client=("127.0.0.1", 4000))

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        first = await client.get("/probe", headers={"X-Forwarded-For": "198.51.100.1"})
        second = await client.get("/probe", headers={"X-Forwarded-For": "198.51.100.1"})

    assert first.status_code == 200
    assert second.status_code == 429


@pytest.mark.asyncio
async def test_options_and_disabled_limiter_pass_through() -> None:
    calls = []

    async def downstream(scope, receive, send):
        calls.append(scope["type"])
        if scope["type"] == "http":
            await send({"type": "http.response.start", "status": 204, "headers": []})
            await send({"type": "http.response.body", "body": b""})
        else:
            await send({"type": "websocket.close", "code": 1000})

    limiter = HttpRateLimitMiddleware(
        downstream,
        requests_per_minute=1,
        burst=1,
    )
    messages = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        messages.append(message)

    await limiter(
        {"type": "http", "method": "OPTIONS", "client": ("127.0.0.1", 1)},
        receive,
        send,
    )
    await HttpRateLimitMiddleware(
        downstream,
        requests_per_minute=0,
        burst=0,
    )(
        {"type": "websocket", "client": ("127.0.0.1", 1)},
        receive,
        send,
    )

    assert calls == ["http", "websocket"]
    assert messages[0]["status"] == 204


def test_depleted_lru_bucket_cap_uses_bounded_overflow() -> None:
    limiter = HttpRateLimitMiddleware(
        lambda scope, receive, send: None,
        requests_per_minute=1,
        burst=1,
        max_clients=2,
        clock=lambda: 100.0,
    )

    assert limiter._consume("client-a")[0] is True
    assert limiter._consume("client-b")[0] is True
    assert limiter._consume("client-a")[0] is False
    assert limiter._consume("client-c")[0] is True

    assert list(limiter._buckets) == ["client-b", "client-a"]
    assert limiter._overflow_bucket is not None


def test_client_churn_cannot_reset_a_depleted_bucket() -> None:
    limiter = HttpRateLimitMiddleware(
        lambda scope, receive, send: None,
        requests_per_minute=1,
        burst=1,
        max_clients=2,
        clock=lambda: 100.0,
    )

    assert limiter._consume("client-a")[0] is True
    assert limiter._consume("client-b")[0] is True
    assert limiter._consume("client-c")[0] is True
    assert limiter._consume("client-d")[0] is False
    assert limiter._consume("client-a")[0] is False
    assert list(limiter._buckets) == ["client-b", "client-a"]
    assert len(limiter._buckets) == limiter.max_clients


def test_fully_refilled_oldest_bucket_can_be_safely_replaced() -> None:
    now = [100.0]
    limiter = HttpRateLimitMiddleware(
        lambda scope, receive, send: None,
        requests_per_minute=60,
        burst=1,
        max_clients=1,
        clock=lambda: now[0],
    )

    assert limiter._consume("client-a")[0] is True
    now[0] += 1.0
    assert limiter._consume("client-b")[0] is True
    assert list(limiter._buckets) == ["client-b"]


def test_clock_rollback_does_not_grant_an_extra_refill() -> None:
    now = [100.0]
    limiter = HttpRateLimitMiddleware(
        lambda scope, receive, send: None,
        requests_per_minute=60,
        burst=1,
        clock=lambda: now[0],
    )

    assert limiter._consume("client-a")[0] is True
    now[0] = 90.0
    assert limiter._consume("client-a")[0] is False
    now[0] = 100.0
    assert limiter._consume("client-a")[0] is False
    now[0] = 101.0
    assert limiter._consume("client-a")[0] is True


def test_clock_rollback_from_zero_does_not_grant_an_extra_refill() -> None:
    now = [0.0]
    limiter = HttpRateLimitMiddleware(
        lambda scope, receive, send: None,
        requests_per_minute=60,
        burst=1,
        clock=lambda: now[0],
    )

    assert limiter._consume("client-a")[0] is True
    now[0] = -1.0
    assert limiter._consume("client-a")[0] is False
    now[0] = 0.0
    assert limiter._consume("client-a")[0] is False
    now[0] = 1.0
    assert limiter._consume("client-a")[0] is True


def test_non_finite_clock_reading_freezes_refill() -> None:
    now = [100.0]
    limiter = HttpRateLimitMiddleware(
        lambda scope, receive, send: None,
        requests_per_minute=60,
        burst=1,
        clock=lambda: now[0],
    )

    assert limiter._consume("client-a")[0] is True
    now[0] = float("nan")
    assert limiter._consume("client-a")[0] is False
    now[0] = 101.0
    assert limiter._consume("client-a")[0] is True


def test_concurrent_consumers_cannot_exceed_burst() -> None:
    limiter = HttpRateLimitMiddleware(
        lambda scope, receive, send: None,
        requests_per_minute=60,
        burst=5,
        clock=lambda: 100.0,
    )

    with ThreadPoolExecutor(max_workers=16) as executor:
        results = list(executor.map(lambda _: limiter._consume("client-a")[0], range(64)))

    assert results.count(True) == 5
    assert results.count(False) == 59


def test_direct_peer_key_is_bounded_and_has_safe_fallback() -> None:
    assert _direct_peer_key({"client": ("a" * 200, 123)}) == "a" * 128
    assert _direct_peer_key({"client": None}) == "<unknown>"
    assert _direct_peer_key({"client": (123, 456)}) == "<unknown>"


@pytest.mark.asyncio
async def test_malformed_method_object_is_not_stringified() -> None:
    class ExplodingMethod:
        def __str__(self) -> str:
            raise AssertionError("untrusted method must not be stringified")

    calls = 0

    async def downstream(scope, receive, send):
        nonlocal calls
        calls += 1
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    limiter = HttpRateLimitMiddleware(
        downstream,
        requests_per_minute=60,
        burst=1,
    )
    sent = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http",
        "method": ExplodingMethod(),
        "client": ("127.0.0.1", 1),
    }
    await limiter(scope, receive, send)
    await limiter(scope, receive, send)

    assert calls == 1
    assert sent[-2]["status"] == 429


def test_invalid_limiter_configuration_is_rejected() -> None:
    async def downstream(scope, receive, send):
        return None

    with pytest.raises(ValueError, match="requests_per_minute"):
        HttpRateLimitMiddleware(downstream, requests_per_minute=-1, burst=1)
    with pytest.raises(ValueError, match="burst must be positive"):
        HttpRateLimitMiddleware(downstream, requests_per_minute=1, burst=0)
    with pytest.raises(ValueError, match="max_clients"):
        HttpRateLimitMiddleware(
            downstream,
            requests_per_minute=1,
            burst=1,
            max_clients=0,
        )


def test_application_middleware_order_keeps_timing_outermost() -> None:
    assert app.user_middleware[0].cls is _TimingMiddleware
    assert app.user_middleware[1].cls is HttpRateLimitMiddleware


@pytest.mark.asyncio
async def test_rate_limit_response_gets_outer_security_headers_and_access_log(
    caplog,
) -> None:
    now = [100.0]
    test_app = _limited_app(clock=lambda: now[0], burst=1)
    test_app.add_middleware(_TimingMiddleware)
    transport = ASGITransport(app=test_app, client=("198.51.100.8", 4000))

    with caplog.at_level("INFO", logger="app.main"):
        async with AsyncClient(transport=transport, base_url="https://test") as client:
            assert (await client.get("/probe")).status_code == 200
            limited = await client.get("/probe")

    assert limited.status_code == 429
    assert limited.headers["x-content-type-options"] == "nosniff"
    assert limited.headers["x-frame-options"] == "DENY"
    assert limited.headers["strict-transport-security"] == "max-age=31536000"
    assert len(limited.headers.get_list("x-request-time-ms")) == 1
    assert "status=429" in caplog.text
