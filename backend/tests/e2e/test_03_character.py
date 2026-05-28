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


class TestCharacterMissingFlows:

    @pytest_asyncio.fixture
    async def ctx(self, async_client: AsyncClient, db_session: AsyncSession):
        meta = await create_base_scene(db_session)
        await db_session.flush()
        return async_client, meta["project_id"], meta["character_ids"], meta["entity_ids"]

    async def test_knowledge_list(self, ctx):
        client, pid, cids, eids = ctx
        cid = cids["克莱恩·莫雷蒂"]
        resp = await client.get(f"/api/characters/{cid}/knowledge?novel_id={pid}")
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "total" in data

    async def test_add_knowledge(self, ctx):
        client, pid, cids, eids = ctx
        cid = cids["克莱恩·莫雷蒂"]
        target_id = eids["源堡"]
        resp = await client.post(
            f"/api/characters/{cid}/knowledge?novel_id={pid}",
            json={
                "novel_id": pid,
                "character_id": cid,
                "target_type": "entity",
                "target_id": target_id,
                "knowledge_level": "partial",
                "known_content": "克莱恩知道源堡的存在",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["knowledge_level"] == "partial"
        assert data["known_content"] == "克莱恩知道源堡的存在"
        assert data["character_id"] == cid
        assert data["target_type"] == "entity"

    async def test_update_knowledge(self, ctx):
        client, pid, cids, eids = ctx
        cid = cids["克莱恩·莫雷蒂"]
        target_id = eids["源堡"]
        create_resp = await client.post(
            f"/api/characters/{cid}/knowledge?novel_id={pid}",
            json={
                "novel_id": pid,
                "character_id": cid,
                "target_type": "entity",
                "target_id": target_id,
                "knowledge_level": "partial",
                "known_content": "克莱恩知道源堡的存在",
            },
        )
        assert create_resp.status_code == 201
        kid = create_resp.json()["id"]

        update_resp = await client.put(
            f"/api/characters/knowledge/{kid}?novel_id={pid}",
            json={
                "knowledge_level": "full",
                "known_content": "克莱恩完全了解源堡的秘密",
            },
        )
        assert update_resp.status_code == 200
        data = update_resp.json()
        assert data["knowledge_level"] == "full"
        assert data["known_content"] == "克莱恩完全了解源堡的秘密"

    async def test_delete_knowledge(self, ctx):
        client, pid, cids, eids = ctx
        cid = cids["克莱恩·莫雷蒂"]
        target_id = eids["源堡"]
        create_resp = await client.post(
            f"/api/characters/{cid}/knowledge?novel_id={pid}",
            json={
                "novel_id": pid,
                "character_id": cid,
                "target_type": "entity",
                "target_id": target_id,
                "knowledge_level": "partial",
                "known_content": "克莱恩知道源堡的存在",
            },
        )
        assert create_resp.status_code == 201
        kid = create_resp.json()["id"]

        delete_resp = await client.delete(
            f"/api/characters/knowledge/{kid}?novel_id={pid}",
        )
        assert delete_resp.status_code == 204

        list_resp = await client.get(f"/api/characters/{cid}/knowledge?novel_id={pid}")
        items = list_resp.json()["items"]
        remaining_ids = [item["id"] for item in items]
        assert kid not in remaining_ids

    async def test_single_character_extract(self, ctx):
        client, pid, cids, eids = ctx
        cid = cids["克莱恩·莫雷蒂"]
        resp = await client.post(f"/api/characters/{cid}/extract?novel_id={pid}")
        assert resp.status_code == 201
        data = resp.json()
        assert "task_id" in data
        assert data["status"] == "pending"

        task_id = data["task_id"]
        task_resp = await client.get(f"/api/tasks/{task_id}")
        assert task_resp.status_code == 200
        task_data = task_resp.json()
        assert task_data["status"] == "pending"
        assert task_data["task_type"] == "character_extract"

    async def test_apply_suggestions(self, ctx):
        client, pid, cids, eids = ctx
        cid = cids["克莱恩·莫雷蒂"]

        await client.put(
            f"/api/characters/{cid}?novel_id={pid}",
            json={
                "meta": {
                    "ai_suggestions": {
                        "desire": "探寻非凡世界的终极真相",
                        "fear": "失去对自我的掌控",
                    },
                    "ai_suggestions_at": "2026-05-28T00:00:00Z",
                },
            },
        )

        resp = await client.put(
            f"/api/characters/{cid}/apply-suggestions?novel_id={pid}",
            json={"fields": ["desire", "fear"]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["desire"] == "探寻非凡世界的终极真相"
        assert data["fear"] == "失去对自我的掌控"
        assert "desire" not in data.get("meta", {}).get("ai_suggestions", {})
        assert "fear" not in data.get("meta", {}).get("ai_suggestions", {})

    async def test_extract_all_characters(self, ctx):
        client, pid, cids, eids = ctx
        resp = await client.post(f"/api/characters/extract-all?novel_id={pid}")
        assert resp.status_code == 201, f"extract-all: {resp.status_code} {resp.text[:300]}"
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 1
        for item in data:
            assert "task_id" in item
            assert item["status"] == "pending"
