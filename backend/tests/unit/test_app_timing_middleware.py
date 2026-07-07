import logging

import pytest

from app.main import _redact_request_path, _TimingMiddleware


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
async def test_timing_middleware_exception_log_uses_redacted_path(caplog):
    raw_uuid = "550e8400-e29b-41d4-a716-446655440000"

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
        "path": f"/api/projects/987/scenes/{raw_uuid}",
    }

    with caplog.at_level(logging.ERROR, logger="app.main"):
        with pytest.raises(RuntimeError):
            await middleware(scope, receive, send)

    assert "/api/projects/<id>/scenes/<id>" in caplog.text
    assert raw_uuid not in caplog.text
