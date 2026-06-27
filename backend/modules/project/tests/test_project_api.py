"""
Project API 层测试

通过 async_client 验证 HTTP 契约：创建、列表、编辑、软删除、
恢复、永久删除、空标题 422、404。
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient


@pytest.fixture
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
async def test_permanent_delete_only_after_soft_delete(
    async_client: AsyncClient,
    sample_project: dict,
) -> None:
    pid = sample_project["id"]

    # 未软删不能直接永久删除
    resp = await async_client.delete(f"/api/projects/{pid}/permanent")
    assert resp.status_code == 404

    await async_client.delete(f"/api/projects/{pid}")
    resp = await async_client.delete(f"/api/projects/{pid}/permanent")
    assert resp.status_code == 204

    resp = await async_client.get(f"/api/projects/{pid}")
    assert resp.status_code == 404

    resp = await async_client.get("/api/projects/recycle-bin")
    assert resp.status_code == 200
    assert not any(p["id"] == pid for p in resp.json()["items"])
