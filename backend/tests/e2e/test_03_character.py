"""
人物档案与知识边界 E2E 测试
"""
from __future__ import annotations

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.e2e.seed_data import create_base_scene


class TestCharacterCRUD:
    """人物 CRUD"""

    @pytest_asyncio.fixture
    async def ctx(self, async_client: AsyncClient, db_session: AsyncSession):
        meta = await create_base_scene(db_session)
        await db_session.flush()
        return async_client, meta["project_id"], meta["character_ids"]

    async def test_create_character(self, ctx):
        client, pid, _ = ctx
        resp = await client.post("/api/characters", json={
            "novel_id": pid, "name": "梅丽莎·莫雷蒂", "role": "supporting",
        })
        assert resp.status_code == 201
        assert resp.json()["name"] == "梅丽莎·莫雷蒂"

    async def test_create_character_minimal(self, ctx):
        client, pid, _ = ctx
        resp = await client.post("/api/characters", json={
            "novel_id": pid, "name": "本森·莫雷蒂",
        })
        assert resp.status_code == 201

    async def test_list_characters(self, ctx):
        client, pid, _ = ctx
        resp = await client.get(f"/api/characters?novel_id={pid}")
        assert resp.status_code == 200
        items = resp.json().get("items", [])
        assert len(items) >= 5
        names = [c["name"] for c in items]
        assert "克莱恩·莫雷蒂" in names

    async def test_get_character(self, ctx):
        client, pid, cids = ctx
        cid = cids["克莱恩·莫雷蒂"]
        resp = await client.get(f"/api/characters/{cid}?novel_id={pid}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "克莱恩·莫雷蒂"
        assert data["role"] == "protagonist"

    async def test_update_character(self, ctx):
        client, pid, cids = ctx
        cid = cids["克莱恩·莫雷蒂"]
        resp = await client.put(f"/api/characters/{cid}?novel_id={pid}", json={
            "current_state": "值夜者正式成员",
            "current_goal": "寻找源堡的秘密",
        })
        assert resp.status_code == 200
        assert resp.json()["current_state"] == "值夜者正式成员"

    async def test_update_character_state(self, ctx):
        client, pid, cids = ctx
        cid = cids["克莱恩·莫雷蒂"]
        resp = await client.request(
            "PATCH",
            f"/api/characters/{cid}/state?novel_id={pid}&current_state=受伤恢复中&current_emotion=谨慎",
        )
        assert resp.status_code == 200, f"PATCH failed: {resp.text[:200]}"


class TestCharacterKnowledge:
    """知识边界 CRUD + 过滤"""

    @pytest_asyncio.fixture
    async def ctx(self, async_client, db_session):
        meta = await create_base_scene(db_session)
        await db_session.flush()
        return async_client, meta["project_id"], meta["entity_ids"], meta["character_ids"]

    async def test_filter_context(self, ctx):
        """角色视角过滤"""
        client, pid, eids, cids = ctx
        resp = await client.post(
            f"/api/characters/{cids['克莱恩·莫雷蒂']}/filter-context?novel_id={pid}",
            json={
                "context_items": [
                    {"type": "world_entity", "id": eids["源堡"], "content": "源堡是灰雾之上的神秘空间"},
                    {"type": "world_entity", "id": eids["值夜者"], "content": "值夜者是官方非凡者组织"},
                ],
            },
        )
        assert resp.status_code == 200
