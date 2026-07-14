import asyncio
import logging
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse, Response
from httpx import ASGITransport, AsyncClient
from starlette.middleware.errors import ServerErrorMiddleware

from app.http_rate_limit import HttpRateLimitMiddleware
from app.main import (
    _internal_server_error_response,
    _redact_request_path,
    _request_log_fields,
    _TimingMiddleware,
    app,
    global_exception_handler,
)
from core.logging_context import bind_validated_novel_id, current_novel_id_for_log


def _access_log_records(caplog):
    return [
        record
        for record in caplog.records
        if record.name == "app.main"
        and record.getMessage().startswith(("Request completed ", "Request failed "))
    ]


def _assert_security_headers(response, *, expect_hsts: bool) -> None:
    assert response.headers.get_list("x-content-type-options") == ["nosniff"]
    assert response.headers.get_list("x-frame-options") == ["DENY"]
    if expect_hsts:
        assert response.headers.get_list("strict-transport-security") == [
            "max-age=31536000"
        ]
    else:
        assert "strict-transport-security" not in response.headers


def test_redact_request_path_replaces_uuid_digits_and_long_hash_segments():
    path = (
        "/api/projects/123/scenes/"
        "550e8400-e29b-41d4-a716-446655440000/assets/"
        "a3f8c1d9e7b45a6c9d0123456789abcd"
    )

    assert _redact_request_path(path) == "/api/projects/<id>/scenes/<id>/assets/<id>"


def test_redact_request_path_replaces_long_slug_like_identifier():
    path = "/api/imports/batch-20260707-a3f8c1d9e7b45a6c9d0/status"

    assert _redact_request_path(path) == "/api/imports/<id>/status"


def test_redact_request_path_truncates_total_length():
    redacted = _redact_request_path(f"/api/static/{'z' * 240}")

    assert len(redacted) == 160
    assert redacted.endswith("...")


def test_redact_request_path_keeps_ordinary_static_segments():
    path = "/api/health/static-assets/status"

    assert _redact_request_path(path) == path


@pytest.mark.asyncio
async def test_timing_middleware_exception_log_omits_actual_path(caplog):
    raw_uuid = "550e8400-e29b-41d4-a716-446655440000"
    private_slug = "customer-private-name"

    async def failing_app(scope, receive, send):
        raise RuntimeError("boom")

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        return None

    middleware = _TimingMiddleware(failing_app)
    scope = {
        "type": "http",
        "method": "GET",
        "path": f"/api/projects/{private_slug}/scenes/{raw_uuid}",
        "route": SimpleNamespace(path="/api/projects/{project_id}/scenes/{scene_id}"),
    }

    with caplog.at_level(logging.ERROR, logger="app.main"):
        with pytest.raises(RuntimeError):
            await middleware(scope, receive, send)

    records = _access_log_records(caplog)
    assert len(records) == 1
    assert records[0].levelno == logging.ERROR
    assert (
        records[0]
        .getMessage()
        .startswith(
            "Request failed method=GET "
            "route=/api/projects/{project_id}/scenes/{scene_id} "
            "status=500 duration_ms="
        )
    )
    assert raw_uuid not in caplog.text
    assert private_slug not in caplog.text


@pytest.mark.asyncio
async def test_timing_middleware_logs_completed_request_with_route_template(caplog):
    test_app = FastAPI()
    test_app.add_middleware(_TimingMiddleware)

    @test_app.get("/probe/{item_id}")
    async def _probe(item_id: str) -> dict[str, str]:
        return {"item_id": item_id}

    private_item_id = "customer-private-name"
    transport = ASGITransport(app=test_app)
    with caplog.at_level(logging.INFO, logger="app.main"):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(
                f"/probe/{private_item_id}",
                params={"query": "private-query"},
            )

    records = _access_log_records(caplog)
    assert len(records) == 1
    message = records[0].getMessage()
    assert message.startswith(
        "Request completed method=GET route=/probe/{item_id} status=200 duration_ms="
    )
    assert records[0].levelno == logging.INFO
    assert private_item_id not in caplog.text
    assert "private-query" not in caplog.text
    assert response.status_code == 200
    assert len(response.headers.get_list("x-request-time-ms")) == 1


@pytest.mark.asyncio
async def test_timing_middleware_logs_validated_novel_id_and_clears_scope(caplog):
    test_app = FastAPI()
    test_app.add_middleware(_TimingMiddleware)
    novel_id = "123e4567-e89b-42d3-a456-426614174000"

    @test_app.get("/probe")
    async def _probe() -> dict[str, bool]:
        assert bind_validated_novel_id(novel_id) is True
        return {"ok": True}

    transport = ASGITransport(app=test_app)
    with caplog.at_level(logging.INFO, logger="app.main"):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/probe")

    assert response.status_code == 200
    records = _access_log_records(caplog)
    assert len(records) == 1
    assert records[0].getMessage().endswith(f"novel_id={novel_id}")
    assert current_novel_id_for_log() == "<none>"


@pytest.mark.asyncio
async def test_timing_middleware_binds_successful_project_path_only(caplog):
    test_app = FastAPI()
    test_app.add_middleware(_TimingMiddleware)
    project_id = "123e4567-e89b-42d3-a456-426614174000"

    @test_app.get("/projects/{project_id}")
    async def _project(project_id: str) -> dict[str, str]:
        return {"project_id": project_id}

    @test_app.get("/missing/{project_id}")
    async def _missing(project_id: str) -> JSONResponse:
        return JSONResponse(status_code=404, content={"project_id": project_id})

    transport = ASGITransport(app=test_app)
    with caplog.at_level(logging.INFO, logger="app.main"):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            ok_response = await client.get(f"/projects/{project_id}")
            missing_response = await client.get(f"/missing/{project_id}")

    assert ok_response.status_code == 200
    assert missing_response.status_code == 404
    records = _access_log_records(caplog)
    assert len(records) == 2
    assert records[0].getMessage().endswith(f"novel_id={project_id}")
    assert records[1].getMessage().endswith("novel_id=<none>")
    assert current_novel_id_for_log() == "<none>"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("base_url", "expect_hsts"),
    [("http://test", False), ("https://test", True)],
)
async def test_outer_middleware_adds_security_headers_by_request_scheme(
    base_url: str,
    expect_hsts: bool,
) -> None:
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url=base_url) as client:
        response = await client.get("/")

    assert response.status_code == 200
    assert response.json()["name"]
    _assert_security_headers(response, expect_hsts=expect_hsts)


@pytest.mark.asyncio
async def test_outer_middleware_adds_security_headers_to_unhandled_500_response(
    caplog,
):
    test_app = FastAPI()
    test_app.add_exception_handler(Exception, global_exception_handler)
    test_app.add_middleware(
        ServerErrorMiddleware,
        handler=_internal_server_error_response,
        debug=False,
    )
    test_app.add_middleware(_TimingMiddleware)

    @test_app.get("/boom")
    async def _boom() -> None:
        raise RuntimeError("private failure content")

    transport = ASGITransport(app=test_app, raise_app_exceptions=False)
    with caplog.at_level(logging.ERROR, logger="app.main"):
        async with AsyncClient(transport=transport, base_url="https://test") as client:
            response = await client.get("/boom")

    assert response.status_code == 500
    assert response.json() == {
        "error": "InternalServerError",
        "message": "服务器内部错误，请稍后重试。",
        "status_code": 500,
    }
    _assert_security_headers(response, expect_hsts=True)
    assert len(response.headers.get_list("x-request-time-ms")) == 1
    assert (
        len(
            [
                record
                for record in caplog.records
                if record.name == "app.main"
                and record.getMessage().startswith("Unhandled exception novel_id=")
            ]
        )
        == 1
    )
    assert len(_access_log_records(caplog)) == 1
    assert "private failure content" not in caplog.text
    assert "type=RuntimeError stack=" in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [204, 304])
async def test_outer_middleware_preserves_bodyless_response_semantics(
    status_code: int,
) -> None:
    test_app = FastAPI()
    test_app.add_middleware(_TimingMiddleware)

    @test_app.get("/bodyless")
    async def _bodyless() -> Response:
        return Response(status_code=status_code)

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="https://test") as client:
        response = await client.get("/bodyless")

    assert response.status_code == status_code
    assert response.content == b""
    _assert_security_headers(response, expect_hsts=True)
    assert len(response.headers.get_list("x-request-time-ms")) == 1


@pytest.mark.asyncio
async def test_outer_middleware_does_not_trust_forwarded_proto_for_hsts():
    test_app = FastAPI()
    test_app.add_middleware(_TimingMiddleware)

    @test_app.get("/probe")
    async def _probe() -> Response:
        return Response(
            status_code=200,
            headers={"Strict-Transport-Security": "max-age=0"},
        )

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/probe",
            headers={"X-Forwarded-Proto": "https"},
        )

    _assert_security_headers(response, expect_hsts=False)


@pytest.mark.asyncio
async def test_timing_middleware_leaves_non_http_scope_unchanged():
    received_scope = None
    sent_messages = []

    async def downstream_app(scope, receive, send):
        nonlocal received_scope
        received_scope = scope
        await send({"type": "websocket.close", "code": 1000})

    async def receive():
        return {"type": "websocket.connect"}

    async def send(message):
        sent_messages.append(message)

    scope = {"type": "websocket", "scheme": "wss", "path": "/socket"}
    await _TimingMiddleware(downstream_app)(scope, receive, send)

    assert received_scope is scope
    assert sent_messages == [{"type": "websocket.close", "code": 1000}]


@pytest.mark.asyncio
async def test_timing_middleware_replaces_duplicate_downstream_security_headers():
    sent_messages = []

    async def downstream_app(scope, receive, send):
        await send(
            {
                "type": "http.response.start",
                "status": 204,
                "headers": [
                    (b"X-Frame-Options", b"SAMEORIGIN"),
                    (b"x-frame-options", b"ALLOW-FROM https://private.example"),
                    (b"X-Content-Type-Options", b"invalid"),
                    (b"Strict-Transport-Security", b"max-age=0"),
                    (b"X-Request-Time-Ms", b"999"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": b""})

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent_messages.append(message)

    await _TimingMiddleware(downstream_app)(
        {"type": "http", "method": "GET", "path": "/", "scheme": "https"},
        receive,
        send,
    )

    headers = sent_messages[0]["headers"]
    by_name: dict[bytes, list[bytes]] = {}
    for name, value in headers:
        by_name.setdefault(name.lower(), []).append(value)
    assert by_name[b"x-frame-options"] == [b"DENY"]
    assert by_name[b"x-content-type-options"] == [b"nosniff"]
    assert by_name[b"strict-transport-security"] == [b"max-age=31536000"]
    assert len(by_name[b"x-request-time-ms"]) == 1


@pytest.mark.asyncio
async def test_timing_middleware_logs_5xx_completion_at_error(caplog):
    sent_messages = []

    async def failing_response_app(scope, receive, send):
        scope["route"] = SimpleNamespace(path="/probe/{item_id}")
        response = JSONResponse(status_code=503, content={"detail": "private"})
        await response(scope, receive, send)

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent_messages.append(message)

    middleware = _TimingMiddleware(failing_response_app)
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/probe/private-item",
    }

    with caplog.at_level(logging.INFO, logger="app.main"):
        await middleware(scope, receive, send)

    records = _access_log_records(caplog)
    assert len(records) == 1
    assert records[0].levelno == logging.ERROR
    assert (
        records[0]
        .getMessage()
        .startswith(
            "Request completed method=POST route=/probe/{item_id} status=503 duration_ms="
        )
    )
    assert "private-item" not in caplog.text
    assert "private" not in caplog.text
    timing_headers = [
        value
        for name, value in sent_messages[0]["headers"]
        if name.lower() == b"x-request-time-ms"
    ]
    assert len(timing_headers) == 1


@pytest.mark.asyncio
async def test_timing_middleware_logs_only_after_stream_finishes(caplog):
    response_started = asyncio.Event()
    finish_response = asyncio.Event()
    sent_messages = []

    async def streaming_app(scope, receive, send):
        scope["route"] = SimpleNamespace(path="/stream/{item_id}")
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"text/plain")],
            }
        )
        response_started.set()
        await finish_response.wait()
        await send({"type": "http.response.body", "body": b"first", "more_body": True})
        await send({"type": "http.response.body", "body": b"last"})

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent_messages.append(message)

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/stream/private-item",
    }
    middleware = _TimingMiddleware(streaming_app)

    with caplog.at_level(logging.INFO, logger="app.main"):
        task = asyncio.create_task(middleware(scope, receive, send))
        await response_started.wait()
        assert _access_log_records(caplog) == []
        finish_response.set()
        await task

    records = _access_log_records(caplog)
    assert len(records) == 1
    assert (
        records[0]
        .getMessage()
        .startswith(
            "Request completed method=GET route=/stream/{item_id} status=200 duration_ms="
        )
    )
    response_headers = sent_messages[0]["headers"]
    timing_headers = [
        value for name, value in response_headers if name.lower() == b"x-request-time-ms"
    ]
    assert len(timing_headers) == 1
    assert float(timing_headers[0]) >= 0
    assert "private-item" not in caplog.text


@pytest.mark.asyncio
async def test_timing_middleware_logs_exception_after_response_start_once(caplog):
    sent_messages = []

    async def failing_stream(scope, receive, send):
        scope["route"] = SimpleNamespace(path="/stream/{item_id}")
        await send({"type": "http.response.start", "status": 202, "headers": []})
        raise RuntimeError("private failure content")

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent_messages.append(message)

    middleware = _TimingMiddleware(failing_stream)
    scope = {"type": "http", "method": "POST", "path": "/stream/private-item"}

    with caplog.at_level(logging.INFO, logger="app.main"):
        with pytest.raises(RuntimeError, match="private failure content"):
            await middleware(scope, receive, send)

    records = _access_log_records(caplog)
    assert len(records) == 1
    assert records[0].levelno == logging.ERROR
    assert (
        records[0]
        .getMessage()
        .startswith(
            "Request failed method=POST route=/stream/{item_id} status=202 duration_ms="
        )
    )
    assert "private-item" not in caplog.text
    assert "private failure content" not in caplog.text
    assert len(sent_messages) == 1


@pytest.mark.asyncio
async def test_outer_timing_middleware_covers_security_short_circuit(caplog):
    assert app.user_middleware[0].cls is _TimingMiddleware
    assert app.user_middleware[1].cls is HttpRateLimitMiddleware
    assert app.user_middleware[2].cls is ServerErrorMiddleware
    transport = ASGITransport(app=app)
    private_path = "/api/projects/private-project-name"
    private_token = "Bearer private-access-token"
    private_body = "private project title"

    with caplog.at_level(logging.INFO, logger="app.main"):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                private_path,
                params={"secret_query": "private-query"},
                headers={"Authorization": private_token},
                json={"title": private_body},
            )

    assert response.status_code == 403
    assert len(response.headers.get_list("x-request-time-ms")) == 1
    _assert_security_headers(response, expect_hsts=False)
    records = _access_log_records(caplog)
    assert len(records) == 1
    assert records[0].levelno == logging.INFO
    assert (
        records[0]
        .getMessage()
        .startswith(
            "Request completed method=POST route=<unresolved> status=403 duration_ms="
        )
    )
    assert "private-project-name" not in caplog.text
    assert "private-access-token" not in caplog.text
    assert "private-query" not in caplog.text
    assert private_body not in caplog.text


@pytest.mark.asyncio
async def test_outer_timing_middleware_covers_cors_preflight(caplog):
    transport = ASGITransport(app=app)
    private_origin = "http://private-origin.example"

    with caplog.at_level(logging.INFO, logger="app.main"):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.options(
                "/api/projects/private-project-name",
                headers={
                    "Origin": private_origin,
                    "Access-Control-Request-Method": "POST",
                },
            )

    assert response.status_code == 200
    assert len(response.headers.get_list("x-request-time-ms")) == 1
    _assert_security_headers(response, expect_hsts=False)
    records = _access_log_records(caplog)
    assert len(records) == 1
    assert (
        records[0]
        .getMessage()
        .startswith(
            "Request completed method=OPTIONS route=<unresolved> status=200 duration_ms="
        )
    )
    assert "private-project-name" not in caplog.text
    assert private_origin not in caplog.text


def test_request_log_fields_rejects_malformed_method_and_route():
    class SecretMethod:
        def __str__(self):
            raise AssertionError("untrusted method must not be stringified")

    class ExplodingRoute:
        @property
        def path(self):
            raise RuntimeError("private route property")

    scope = {
        "type": "http",
        "method": SecretMethod(),
        "route": ExplodingRoute(),
        "path": "/private-actual-path",
    }

    assert _request_log_fields(scope) == ("UNKNOWN", "<unresolved>")


@pytest.mark.parametrize(
    "scope",
    [
        None,
        {},
        {
            "type": "websocket",
            "method": "GET",
            "route": SimpleNamespace(path="/private/{item_id}"),
        },
        {
            "type": "http",
            "method": "GET\nBearer private-token",
            "route": SimpleNamespace(path="/probe/{item_id}\u2028private"),
        },
    ],
)
def test_request_log_fields_safely_falls_back_for_untrusted_scope(scope):
    assert _request_log_fields(scope) == ("UNKNOWN", "<unresolved>")
