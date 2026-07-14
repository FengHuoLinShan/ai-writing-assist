"""
Project API 层测试

通过 async_client 验证 HTTP 契约：创建、列表、编辑、软删除、
恢复、永久删除、空标题 422、404。
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.tasks.models import AsyncTask


@pytest_asyncio.fixture
async def sample_project(async_client: AsyncClient):
    resp = await async_client.post("/api/projects", json={"title": "API 测试小说"})
    assert resp.status_code == 201
    return resp.json()


@pytest.mark.asyncio
async def test_create_project(async_client: AsyncClient) -> None:
    resp = await async_client.post("/api/projects", json={"title": "HTTP 创建测试"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["title"] == "HTTP 创建测试"
    assert data["language"] == "zh"
    assert data["default_reveal_policy"] == "author_safe"


@pytest.mark.asyncio
async def test_create_project_empty_title_returns_422(async_client: AsyncClient) -> None:
    resp = await async_client.post("/api/projects", json={"title": ""})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_project_null_byte_title_returns_422(
    async_client: AsyncClient,
) -> None:
    resp = await async_client.post(
        "/api/projects",
        json={"title": "test\x00xyz", "language": "zh"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_project_whitespace_only_title_returns_422(
    async_client: AsyncClient,
) -> None:
    resp = await async_client.post(
        "/api/projects",
        json={"title": "   ", "language": "zh"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_list_projects_paginated(
    async_client: AsyncClient,
    sample_project: dict,
) -> None:
    resp = await async_client.get("/api/projects")
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert "total" in data
    assert len(data["items"]) >= 1


@pytest.mark.asyncio
async def test_get_project_not_found(async_client: AsyncClient) -> None:
    fake_id = str(uuid.uuid4())
    resp = await async_client.get(f"/api/projects/{fake_id}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_update_project(async_client: AsyncClient, sample_project: dict) -> None:
    pid = sample_project["id"]
    resp = await async_client.put(
        f"/api/projects/{pid}",
        json={"tone": "黑暗", "target_length": "novel"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["tone"] == "黑暗"
    assert data["target_length"] == "novel"


@pytest.mark.asyncio
async def test_soft_delete_and_restore(
    async_client: AsyncClient,
    sample_project: dict,
) -> None:
    pid = sample_project["id"]

    resp = await async_client.delete(f"/api/projects/{pid}")
    assert resp.status_code == 204

    resp = await async_client.get(f"/api/projects/{pid}")
    assert resp.status_code == 404

    resp = await async_client.get("/api/projects/recycle-bin")
    assert resp.status_code == 200
    assert any(p["id"] == pid for p in resp.json()["items"])

    resp = await async_client.post(f"/api/projects/{pid}/restore")
    assert resp.status_code == 200
    assert resp.json()["deleted_at"] is None


@pytest.mark.asyncio
async def test_soft_delete_cancels_unfinished_tasks_and_restore_does_not_restart(
    async_client: AsyncClient,
    db_session: AsyncSession,
    sample_project: dict,
) -> None:
    project_id = sample_project["id"]
    other_project_id = str(uuid.uuid4())
    tasks = [
        AsyncTask(
            task_type="pending-task",
            status="pending",
            meta={"novel_id": project_id},
        ),
        AsyncTask(
            task_type="running-task",
            status="running",
            meta={"novel_id": project_id},
            lease_id=str(uuid.uuid4()),
        ),
        AsyncTask(
            task_type="done-task",
            status="done",
            meta={"novel_id": project_id},
        ),
        AsyncTask(
            task_type="other-project-task",
            status="pending",
            meta={"novel_id": other_project_id},
        ),
    ]
    db_session.add_all(tasks)
    await db_session.flush()

    deleted = await async_client.delete(f"/api/projects/{project_id}")
    assert deleted.status_code == 204
    restored = await async_client.post(f"/api/projects/{project_id}/restore")
    assert restored.status_code == 200

    db_session.expire_all()
    task_by_type = {
        task.task_type: task
        for task in (await db_session.execute(select(AsyncTask))).scalars().all()
    }
    for task_type in ("pending-task", "running-task"):
        task = task_by_type[task_type]
        assert task.status == "cancelled"
        assert task.finished_at is not None
        assert task.lease_id is None
        assert task.transition_reason == "project_soft_deleted"
    assert task_by_type["done-task"].status == "done"
    assert task_by_type["other-project-task"].status == "pending"


@pytest.mark.asyncio
async def test_permanent_delete_only_after_soft_delete(
    async_client: AsyncClient,
    sample_project: dict,
) -> None:
    pid = sample_project["id"]

    # 缺少二次确认时不能永久删除
    resp = await async_client.delete(f"/api/projects/{pid}/permanent")
    assert resp.status_code == 400

    # 即使已确认，未软删也不能直接永久删除
    resp = await async_client.delete(
        f"/api/projects/{pid}/permanent",
        params={"confirmed": True},
    )
    assert resp.status_code == 404

    await async_client.delete(f"/api/projects/{pid}")
    resp = await async_client.delete(f"/api/projects/{pid}/permanent")
    assert resp.status_code == 400

    resp = await async_client.delete(
        f"/api/projects/{pid}/permanent",
        params={"confirmed": True},
    )
    assert resp.status_code == 204

    resp = await async_client.get(f"/api/projects/{pid}")
    assert resp.status_code == 404

    resp = await async_client.get("/api/projects/recycle-bin")
    assert resp.status_code == 200
    assert not any(p["id"] == pid for p in resp.json()["items"])


@pytest.mark.asyncio
async def test_bulk_permanent_delete_is_confirmed_and_atomic(
    async_client: AsyncClient,
) -> None:
    deleted_ids = []
    for title in ("批量删除 A", "批量删除 B"):
        created = await async_client.post("/api/projects", json={"title": title})
        project_id = created.json()["id"]
        deleted_ids.append(project_id)
        await async_client.delete(f"/api/projects/{project_id}")

    active = await async_client.post("/api/projects", json={"title": "未进回收站"})
    active_id = active.json()["id"]

    resp = await async_client.post(
        "/api/projects/recycle-bin/permanent-delete",
        json={"project_ids": deleted_ids, "confirmed": False},
    )
    assert resp.status_code == 400

    resp = await async_client.post(
        "/api/projects/recycle-bin/permanent-delete",
        json={"project_ids": [deleted_ids[0], active_id], "confirmed": True},
    )
    assert resp.status_code == 404
    recycle_bin = await async_client.get("/api/projects/recycle-bin")
    recycled_ids = {item["id"] for item in recycle_bin.json()["items"]}
    assert set(deleted_ids) <= recycled_ids

    resp = await async_client.post(
        "/api/projects/recycle-bin/permanent-delete",
        json={"project_ids": [*deleted_ids, deleted_ids[0]], "confirmed": True},
    )
    assert resp.status_code == 200
    assert resp.json() == {
        "deleted_ids": deleted_ids,
        "deleted_count": 2,
    }

    recycle_bin = await async_client.get("/api/projects/recycle-bin")
    recycled_ids = {item["id"] for item in recycle_bin.json()["items"]}
    assert not set(deleted_ids) & recycled_ids
