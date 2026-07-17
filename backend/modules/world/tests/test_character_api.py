"""
Character API 层测试

验证人物 CRUD 的 HTTP 契约，特别是实体存在性校验。
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import AsyncClient


@pytest_asyncio.fixture
async def test_project(async_client: AsyncClient):
    resp = await async_client.post(
        "/api/projects",
        json={"title": "Character API 测试项目"},
    )
    assert resp.status_code == 201
    return resp.json()


@pytest_asyncio.fixture
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


@pytest.mark.asyncio
async def test_adopted_character_entity_materializes_character_profile(
    async_client: AsyncClient,
    test_project: dict,
) -> None:
    """采用人物身份后应立即可被人物和 POV 选择器读取。"""
    novel_id = test_project["id"]
    entity_resp = await async_client.post(
        f"/api/world/entities?novel_id={novel_id}",
        json={
            "entity_type": "character",
            "name": "克莱恩",
            "summary": "廷根的年轻历史系毕业生",
            "public_info": "莫雷蒂家的次子",
            "hidden_truth": "来自另一个世界",
            "status": "canonical",
        },
    )
    assert entity_resp.status_code == 201

    listed = await async_client.get(
        f"/api/world/characters?novel_id={novel_id}",
    )

    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    profile = listed.json()["items"][0]
    assert profile["entity_id"] == entity_resp.json()["id"]
    assert profile["name"] == "克莱恩"
    assert profile["secret"] == "来自另一个世界"
    assert profile["meta"]["auto_materialized"] is True
    assert profile["meta"]["core_summary"] == "廷根的年轻历史系毕业生"


@pytest.mark.asyncio
async def test_explicit_character_create_upgrades_materialized_profile(
    async_client: AsyncClient,
    test_project: dict,
) -> None:
    """旧两步创建调用应升级 scaffold，而不是因主键重复失败。"""
    novel_id = test_project["id"]
    entity = await async_client.post(
        f"/api/world/entities?novel_id={novel_id}",
        json={
            "entity_type": "character",
            "name": "梅丽莎",
            "status": "canonical",
        },
    )
    entity_id = entity.json()["id"]

    created = await async_client.post(
        f"/api/world/characters?novel_id={novel_id}",
        json={
            "entity_id": entity_id,
            "name": "梅丽莎",
            "personality": "务实、节俭而关心家人",
        },
    )

    assert created.status_code == 201
    assert created.json()["personality"] == "务实、节俭而关心家人"
    assert created.json()["meta"]["auto_materialized"] is False
    listed = await async_client.get(
        f"/api/world/characters?novel_id={novel_id}",
    )
    assert listed.json()["total"] == 1


@pytest.mark.asyncio
async def test_promoted_character_entity_materializes_profile(
    async_client: AsyncClient,
    test_project: dict,
) -> None:
    novel_id = test_project["id"]
    candidate = await async_client.post(
        f"/api/world/entities?novel_id={novel_id}",
        json={
            "entity_type": "character",
            "name": "伦纳德",
            "status": "candidate",
        },
    )
    entity_id = candidate.json()["id"]
    before = await async_client.get(
        f"/api/world/characters?novel_id={novel_id}",
    )
    assert before.json()["total"] == 0

    promoted = await async_client.post(
        f"/api/world/entities/{entity_id}/promote?novel_id={novel_id}",
        json={},
    )

    assert promoted.status_code == 200
    after = await async_client.get(
        f"/api/world/characters?novel_id={novel_id}",
    )
    assert after.json()["total"] == 1
    assert after.json()["items"][0]["entity_id"] == entity_id


@pytest.mark.asyncio
async def test_auto_materialized_profile_does_not_block_entity_type_correction(
    async_client: AsyncClient,
    test_project: dict,
) -> None:
    novel_id = test_project["id"]
    entity = await async_client.post(
        f"/api/world/entities?novel_id={novel_id}",
        json={
            "entity_type": "character",
            "name": "错误分类对象",
            "status": "canonical",
        },
    )
    entity_id = entity.json()["id"]

    corrected = await async_client.put(
        f"/api/world/entities/{entity_id}?novel_id={novel_id}",
        json={"entity_type": "location"},
    )

    assert corrected.status_code == 200
    assert corrected.json()["entity_type"] == "location"
    listed = await async_client.get(
        f"/api/world/characters?novel_id={novel_id}",
    )
    assert listed.json()["total"] == 0
