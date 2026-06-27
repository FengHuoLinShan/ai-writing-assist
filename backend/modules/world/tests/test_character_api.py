"""
Character API 层测试

验证人物 CRUD 的 HTTP 契约，特别是实体存在性校验。
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.fixture
async def test_project(async_client: AsyncClient):
    resp = await async_client.post(
        "/api/projects",
        json={"title": "Character API 测试项目"},
    )
    assert resp.status_code == 201
    return resp.json()


@pytest.fixture
async def test_entity(async_client: AsyncClient, test_project: dict):
    resp = await async_client.post(
        f"/api/world/entities?novel_id={test_project['id']}",
        json={"entity_type": "character", "name": "测试角色", "status": "canonical"},
    )
    assert resp.status_code == 201
    return resp.json()


@pytest.mark.asyncio
async def test_create_character_for_deleted_entity_returns_404(
    async_client: AsyncClient,
    test_project: dict,
    test_entity: dict,
) -> None:
    """为已删除的核心实体创建人物应返回 404"""
    novel_id = test_project["id"]
    entity_id = test_entity["id"]

    delete_resp = await async_client.delete(
        f"/api/world/entities/{entity_id}?novel_id={novel_id}"
    )
    assert delete_resp.status_code == 204

    resp = await async_client.post(
        f"/api/world/characters?novel_id={novel_id}",
        json={"entity_id": entity_id, "name": "Ghost"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_create_character_for_nonexistent_entity_returns_404(
    async_client: AsyncClient,
    test_project: dict,
) -> None:
    """为不存在的核心实体 UUID 创建人物应返回 404"""
    novel_id = test_project["id"]
    fake_id = "00000000-0000-0000-0000-000000000000"

    resp = await async_client.post(
        f"/api/world/characters?novel_id={novel_id}",
        json={"entity_id": fake_id, "name": "Ghost"},
    )
    assert resp.status_code == 404
