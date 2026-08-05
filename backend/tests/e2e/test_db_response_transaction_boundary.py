"""PostgreSQL proof that response start follows request transaction commit."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

import pytest
from fastapi import FastAPI
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.types import Message

from core.database import assert_database_target_for_testing
from core.dependencies import DbSession
from infrastructure.tasks.models import AsyncTask
from tests.e2e.config import DATABASE_URL, require_e2e_database_url

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]


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


async def test_independent_connection_observes_write_at_response_start() -> None:
    database_url = require_e2e_database_url(DATABASE_URL)
    observer_engine = create_async_engine(database_url, pool_size=1, max_overflow=0)
    assert_database_target_for_testing(database_url, observer_engine.url)
    observer_sessions = async_sessionmaker(observer_engine, expire_on_commit=False)
    task_id = uuid.uuid4()
    response_started = False
    test_app = FastAPI()

    @test_app.post("/write", status_code=201)
    async def write(db: DbSession) -> dict[str, str]:
        db.add(
            AsyncTask(
                id=task_id,
                task_type="transaction_boundary_test",
                meta={"source": "db_response_transaction_boundary"},
            )
        )
        await db.flush()
        return {"task_id": str(task_id)}

    async def send(message: Message) -> None:
        nonlocal response_started
        if message["type"] != "http.response.start":
            return
        response_started = True
        async with observer_sessions() as observer:
            observed = await observer.scalar(
                select(AsyncTask.id).where(AsyncTask.id == task_id)
            )
        assert observed == task_id

    try:
        await _invoke_post(test_app, send)
        assert response_started is True
    finally:
        async with observer_sessions() as observer:
            await observer.execute(delete(AsyncTask).where(AsyncTask.id == task_id))
            await observer.commit()
        await observer_engine.dispose()
