"""PostgreSQL JSON/lease gate for a paired local Agent task."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport
from pydantic import BaseModel
from pydantic_ai import Tool
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.main import app
from core.dependencies import get_db
from infrastructure.llm.agent_runtime import AgentRunBudget
from infrastructure.llm.schemas import LLMMessage
from infrastructure.tasks.lifecycle import TaskLifecycleService
from infrastructure.tasks.models import AsyncTask
from modules.local_agent.models import LocalAgentDevice, LocalAgentInvocation
from modules.local_agent.runtime import run_local_agent
from modules.project.models import Project
from tests.e2e.config import DATABASE_URL
from tests.e2e.seed_data import create_project
from tests.support.http import XhrAsyncClient

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]


@pytest_asyncio.fixture
async def live_project(isolated_global_database_manager):
    """Use committed test rows and independent sessions for relay concurrency."""
    engine = create_async_engine(DATABASE_URL)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as db:
        novel_id = (await create_project(db))["project_id"]
        await db.commit()

    async def database() -> AsyncGenerator:
        async with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = database
    try:
        async with XhrAsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client, sessions, novel_id
    finally:
        app.dependency_overrides.clear()
        async with sessions() as db:
            await db.execute(delete(Project).where(Project.id == uuid.UUID(novel_id)))
            await db.commit()
        await engine.dispose()


async def test_local_task_waits_for_owner_approval_and_device(db_session, project_client):
    client, novel_id = project_client
    created = await client.post(
        "/api/local-agent/devices/pair",
        json={"novel_id": novel_id, "name": "测试 Mac"},
    )
    assert created.status_code == 200, created.text
    paired = await client.post(
        "/api/local-agent/companion/activate",
        json={"code": created.json()["code"]},
    )
    assert paired.status_code == 200, paired.text
    task = AsyncTask(
        task_type="assistant_turn",
        novel_id=uuid.UUID(novel_id),
        status="pending",
        meta={
            "_local_agent": True,
            "_local_ready": False,
            "_local_approved": False,
            "_local_device_id": paired.json()["device_id"],
        },
    )
    db_session.add(task)
    await db_session.commit()
    lifecycle = TaskLifecycleService()
    assert (
        await lifecycle.claim_next(db_session, task_id=task.id, novel_id=novel_id) is None
    )
    approved = await client.post(
        f"/api/local-agent/tasks/{task.id}/approve",
        json={"novel_id": novel_id, "acknowledge_full_host_access": True},
    )
    assert approved.status_code == 200, approved.text
    claimed = await lifecycle.claim_next(db_session, task_id=task.id, novel_id=novel_id)
    assert claimed is not None and claimed.status == "running"


async def test_companion_tool_round_trip_on_postgres(live_project):
    client, sessions, novel_id = live_project
    pair = await client.post(
        "/api/local-agent/devices/pair", json={"novel_id": novel_id, "name": "测试 Mac"}
    )
    activated = await client.post(
        "/api/local-agent/companion/activate", json={"code": pair.json()["code"]}
    )
    device_id, token = activated.json()["device_id"], activated.json()["token"]
    async with sessions() as db:
        device = await db.get(LocalAgentDevice, uuid.UUID(device_id))
        owner_id = str(device.owner_id)
    task = AsyncTask(
        task_type="assistant_turn",
        novel_id=uuid.UUID(novel_id),
        status="pending",
        meta={
            "_local_agent": True,
            "_local_ready": False,
            "_local_approved": False,
            "_local_device_id": device_id,
        },
    )
    async with sessions() as db:
        db.add(task)
        await db.commit()
    approved = await client.post(
        f"/api/local-agent/tasks/{task.id}/approve",
        json={"novel_id": novel_id, "acknowledge_full_host_access": True},
    )
    assert approved.status_code == 200
    async with sessions() as db:
        assert await TaskLifecycleService().claim_next(
            db, task_id=task.id, novel_id=novel_id
        )

    async def lookup(name: str) -> str:
        """Read authorized synthetic evidence."""
        return f"证据：{name} 在城外"

    class Answer(BaseModel):
        answer: str

    async with sessions() as worker_db:
        worker = asyncio.create_task(
            run_local_agent(
                worker_db,
                task_id=str(task.id),
                novel_id=novel_id,
                owner_id=owner_id,
                device_id=device_id,
                cli="pi",
                messages=[LLMMessage(role="user", content="甲在哪里？")],
                tools=[Tool(lookup)],
                deps=None,
                output_type=Answer,
                output_validator=None,
                budget=AgentRunBudget(),
                checkpoint=None,
            )
        )
        try:
            async with asyncio.timeout(5):
                while True:
                    async with sessions() as db:
                        invocation = await db.scalar(
                            select(LocalAgentInvocation).where(
                                LocalAgentInvocation.task_id == task.id
                            )
                        )
                    if invocation:
                        break
                    await asyncio.sleep(0.01)
            headers = {"Authorization": f"Bearer {token}"}
            claimed = await client.post(
                "/api/local-agent/companion/claim", json={}, headers=headers
            )
            assert claimed.status_code == 200, claimed.text
            lease = claimed.json()["job"]["lease_id"]
            route = f"/api/local-agent/companion/jobs/{invocation.id}"
            call = await client.post(
                route + "/tools",
                json={
                    "lease_id": lease,
                    "call_id": "lookup-1",
                    "name": "lookup",
                    "arguments": {"name": "甲"},
                },
                headers=headers,
            )
            assert call.status_code == 200, call.text
            async with asyncio.timeout(5):
                while True:
                    result = await client.get(
                        route + "/tools/lookup-1",
                        params={"lease_id": lease},
                        headers=headers,
                    )
                    assert result.status_code == 200, result.text
                    if not result.json()["pending"]:
                        break
                    await asyncio.sleep(0.05)
            assert result.json()["result"] == {"value": "证据：甲 在城外"}
            invalid = await client.post(
                route + "/tools",
                json={
                    "lease_id": lease,
                    "call_id": "lookup-invalid",
                    "name": "lookup",
                    "arguments": {"wrong": "甲"},
                },
                headers=headers,
            )
            assert invalid.status_code == 200, invalid.text
            async with asyncio.timeout(5):
                while True:
                    failed_call = await client.get(
                        route + "/tools/lookup-invalid",
                        params={"lease_id": lease},
                        headers=headers,
                    )
                    assert failed_call.status_code == 200, failed_call.text
                    if not failed_call.json()["pending"]:
                        break
                    await asyncio.sleep(0.05)
            assert failed_call.json()["error"]
            finished = await client.post(
                route + "/finish",
                json={
                    "lease_id": lease,
                    "status": "completed",
                    "answer": '{"answer":"甲在城外"}',
                    "tool_attempts": 2,
                },
                headers=headers,
            )
            assert finished.status_code == 200, finished.text
            output = await asyncio.wait_for(worker, 5)
            assert output.output.answer == "甲在城外"
        finally:
            if not worker.done():
                worker.cancel()
                await asyncio.gather(worker, return_exceptions=True)
