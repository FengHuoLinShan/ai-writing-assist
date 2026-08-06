"""Lifecycle contracts for HTTP request-owned database dependencies."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import pytest
from fastapi import FastAPI
from starlette.types import Message

from core.dependencies import DbSession, get_db


async def _invoke_post(app: FastAPI, send: Callable[[Message], Awaitable[None]]) -> None:
    request_received = False

    async def receive() -> Message:
        nonlocal request_received
        if request_received:
            return {"type": "http.disconnect"}
        request_received = True
        return {"type": "http.request", "body": b"", "more_body": False}

    await app(
        {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.4"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/write",
            "raw_path": b"/write",
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 80),
            "root_path": "",
        },
        receive,
        send,
    )


@pytest.mark.asyncio
async def test_db_dependency_exits_before_success_response_starts() -> None:
    events: list[str] = []
    test_app = FastAPI()

    @test_app.post("/write", status_code=201)
    async def write(_db: DbSession) -> dict[str, str]:
        events.append("handler")
        return {"status": "created"}

    async def recording_db():
        try:
            yield object()
        finally:
            events.append("commit")

    async def send(message: Message) -> None:
        if message["type"] == "http.response.start":
            events.append("response_start")

    test_app.dependency_overrides[get_db] = recording_db

    await _invoke_post(test_app, send)

    assert events == ["handler", "commit", "response_start"]


@pytest.mark.asyncio
async def test_db_commit_failure_cannot_emit_success_response_first() -> None:
    messages: list[Message] = []
    test_app = FastAPI()

    @test_app.post("/write", status_code=201)
    async def write(_db: DbSession) -> dict[str, str]:
        return {"status": "created"}

    async def failing_db():
        yield object()
        raise RuntimeError("commit failed")

    async def send(message: Message) -> None:
        messages.append(message)

    test_app.dependency_overrides[get_db] = failing_db

    with pytest.raises(RuntimeError, match="commit failed"):
        await _invoke_post(test_app, send)

    statuses = [
        message["status"]
        for message in messages
        if message["type"] == "http.response.start"
    ]
    assert statuses == [500]
