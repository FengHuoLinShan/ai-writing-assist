from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from core.dependencies import get_db
from infrastructure.tasks.models import AsyncTask


@pytest_asyncio.fixture
async def async_client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"X-Requested-With": "XMLHttpRequest"},
    ) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_submit_task_rejects_dangerous_domain_task(
    async_client: AsyncClient,
) -> None:
    resp = await async_client.post(
        "/api/tasks",
        json={
            "task_type": "world_entity_extraction",
            "meta": {
                "novel_id": "00000000-0000-0000-0000-000000000701",
                "start_chapter": 1,
                "end_chapter": 3,
            },
        },
    )

    assert resp.status_code == 403
    assert "module API" in resp.text


@pytest.mark.asyncio
async def test_task_status_requires_matching_novel_id(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    owner_novel = "00000000-0000-0000-0000-000000000702"
    other_novel = "00000000-0000-0000-0000-000000000703"
    task = AsyncTask(
        id=uuid.uuid4(),
        task_type="test_safe_task",
        status="done",
        meta={"novel_id": owner_novel, "secret": "only-owner"},
        result={"ok": True},
    )
    db_session.add(task)
    await db_session.flush()

    missing = await async_client.get(f"/api/tasks/{task.id}")
    assert missing.status_code == 422

    wrong = await async_client.get(
        f"/api/tasks/{task.id}",
        params={"novel_id": other_novel},
    )
    assert wrong.status_code == 404
    assert "only-owner" not in wrong.text

    ok = await async_client.get(
        f"/api/tasks/{task.id}",
        params={"novel_id": owner_novel},
    )
    assert ok.status_code == 200
    assert ok.json()["meta"]["secret"] == "only-owner"


@pytest.mark.asyncio
async def test_cancel_task_requires_matching_novel_id(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    owner_novel = "00000000-0000-0000-0000-000000000704"
    other_novel = "00000000-0000-0000-0000-000000000705"
    task = AsyncTask(
        id=uuid.uuid4(),
        task_type="test_safe_task",
        status="pending",
        meta={"novel_id": owner_novel},
    )
    db_session.add(task)
    await db_session.flush()

    wrong = await async_client.post(
        f"/api/tasks/{task.id}/cancel",
        params={"novel_id": other_novel},
    )
    assert wrong.status_code == 404

    ok = await async_client.post(
        f"/api/tasks/{task.id}/cancel",
        params={"novel_id": owner_novel},
    )
    assert ok.status_code == 200
    assert ok.json()["cancelled"] is True


@pytest.mark.asyncio
async def test_retry_task_is_novel_isolated_and_policy_limited(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    owner_novel = "00000000-0000-0000-0000-000000000706"
    task = AsyncTask(
        id=uuid.uuid4(),
        task_type="rag_reindex_novel",
        status="failed",
        meta={"novel_id": owner_novel},
        recovery_policy="auto_requeue",
        attempt=1,
        max_attempts=2,
    )
    db_session.add(task)
    await db_session.flush()

    wrong = await async_client.post(
        f"/api/tasks/{task.id}/retry",
        params={"novel_id": "00000000-0000-0000-0000-000000000707"},
    )
    assert wrong.status_code == 404

    retried = await async_client.post(
        f"/api/tasks/{task.id}/retry",
        params={"novel_id": owner_novel},
    )
    assert retried.status_code == 200
    assert retried.json()["status"] == "pending"

    rejected = await async_client.post(
        f"/api/tasks/{task.id}/retry",
        params={"novel_id": owner_novel},
    )
    assert rejected.status_code == 409
