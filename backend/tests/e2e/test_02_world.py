"""
世界对象 E2E 测试 — CRUD + 关系 + 别名
"""

from __future__ import annotations

import uuid

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.e2e.seed_data import create_base_scene


class TestWorldEntityCRUD:
    """世界对象 CRUD"""

    @pytest_asyncio.fixture
    async def ctx(self, async_client: AsyncClient, db_session: AsyncSession):
        """返回 (client, project_id, entity_ids)"""
        meta = await create_base_scene(db_session)
        await db_session.flush()
        return async_client, meta["project_id"], meta["entity_ids"]

    async def test_create_entity(self, ctx):
        client, pid, _ = ctx
        resp = await client.post(f"/api/world/entities?novel_id={pid}", json={
            "name": "测试城市", "entity_type": "location", "summary": "一座测试城市",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "测试城市"
        assert data["entity_type"] == "location"
        assert data["status"] == "draft"

    async def test_create_entity_all_fields(self, ctx):
        client, pid, _ = ctx
        resp = await client.post(f"/api/world/entities?novel_id={pid}", json={
            "name": "完整对象", "entity_type": "faction",
            "summary": "摘要", "public_info": "公开信息", "hidden_truth": "隐藏真相",
            "importance": 0.9, "importance_level": "core", "reveal_level": "author_only",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["public_info"] == "公开信息"
        assert data["hidden_truth"] == "隐藏真相"
        assert data["importance"] == 0.9
        assert data["importance_level"] == "core"

    async def test_create_entity_minimal(self, ctx):
        client, pid, _ = ctx
        resp = await client.post(f"/api/world/entities?novel_id={pid}", json={
            "name": "最小", "entity_type": "item",
        })
        assert resp.status_code == 201
        assert resp.json()["importance"] == 0.5  # 默认值

    async def test_list_entities(self, ctx):
        client, pid, eids = ctx
        # eids 已有 14 个世界对象
        resp = await client.get(f"/api/world/entities?novel_id={pid}")
        assert resp.status_code == 200
        data = resp.json()
        items = data.get("items", [])
        assert len(items) >= 10
        names = [e["name"] for e in items]
        assert "克莱恩·莫雷蒂" in names
        assert "廷根市" in names

    async def test_list_entities_filter_by_type(self, ctx):
        client, pid, _ = ctx
        resp = await client.get(f"/api/world/entities?novel_id={pid}&entity_type=location")
        assert resp.status_code == 200
        items = resp.json().get("items", [])
        assert all(e["entity_type"] == "location" for e in items)

    async def test_get_entity(self, ctx):
        client, pid, eids = ctx
        eid = eids["克莱恩·莫雷蒂"]
        resp = await client.get(f"/api/world/entities/{eid}?novel_id={pid}")
        assert resp.status_code == 200
        assert resp.json()["name"] == "克莱恩·莫雷蒂"
        assert resp.json()["hidden_truth"] == "来自另一个世界的穿越者，灵魂附身于克莱恩·莫雷蒂"

    async def test_get_entity_not_found(self, ctx):
        client, pid, _ = ctx
        resp = await client.get(f"/api/world/entities/{uuid.uuid4()}?novel_id={pid}")
        assert resp.status_code == 404

    async def test_update_entity(self, ctx):
        client, pid, eids = ctx
        eid = eids["值夜者"]
        resp = await client.put(f"/api/world/entities/{eid}?novel_id={pid}", json={
            "summary": "更新后的摘要",
        })
        assert resp.status_code == 200
        assert resp.json()["summary"] == "更新后的摘要"

    async def test_update_entity_partial(self, ctx):
        client, pid, eids = ctx
        eid = eids["值夜者"]
        # 只更新 summary，其他字段不变
        resp = await client.put(f"/api/world/entities/{eid}?novel_id={pid}", json={
            "summary": "仅更新摘要",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["summary"] == "仅更新摘要"
        assert data["name"] == "值夜者"  # 原名称不变

    async def test_delete_entity(self, ctx):
        client, pid, _ = ctx
        # 创建一个新对象再删除
        create = await client.post(f"/api/world/entities?novel_id={pid}", json={
            "name": "待删除", "entity_type": "item",
        })
        eid = create.json()["id"]
        del_resp = await client.delete(f"/api/world/entities/{eid}?novel_id={pid}")
        assert del_resp.status_code == 204
        get_resp = await client.get(f"/api/world/entities/{eid}?novel_id={pid}")
        assert get_resp.status_code == 404


class TestRelationshipCRUD:
    """关系 CRUD"""

    @pytest_asyncio.fixture
    async def ctx(self, async_client, db_session):
        meta = await create_base_scene(db_session)
        await db_session.flush()
        return async_client, meta["project_id"], meta["entity_ids"]

    async def test_create_relationship(self, ctx):
        client, pid, eids = ctx
        resp = await client.post(f"/api/world/relationships?novel_id={pid}", json={
            "source_type": "world_entity", "source_id": eids["克莱恩·莫雷蒂"],
            "target_type": "world_entity", "target_id": eids["值夜者"],
            "relation_type": "member_of",
            "description": "克莱恩是值夜者成员",
        })
        assert resp.status_code == 201
        assert resp.json()["relation_type"] == "member_of"

    async def test_list_relationships(self, ctx):
        client, pid, eids = ctx
        # 创建一些关系
        for rel in [("member_of", "值夜者"), ("related_to", "源堡"), ("related_to", "罗塞尔日记")]:
            await client.post(f"/api/world/relationships?novel_id={pid}", json={
                "source_type": "world_entity", "source_id": eids["克莱恩·莫雷蒂"],
                "target_type": "world_entity", "target_id": eids[rel[1]],
                "relation_type": rel[0],
            })
        resp = await client.get(f"/api/world/relationships?novel_id={pid}")
        assert resp.status_code == 200
        items = resp.json().get("items", [])
        assert len(items) >= 3

    async def test_delete_relationship(self, ctx):
        client, pid, eids = ctx
        create = await client.post(f"/api/world/relationships?novel_id={pid}", json={
            "source_type": "world_entity", "source_id": eids["克莱恩·莫雷蒂"],
            "target_type": "world_entity", "target_id": eids["秘修会"],
            "relation_type": "opposes",
        })
        rel_id = create.json()["id"]
        del_resp = await client.delete(f"/api/world/relationships/{rel_id}?novel_id={pid}")
        assert del_resp.status_code == 204


class TestAliasCRUD:
    """别名 CRUD"""

    @pytest_asyncio.fixture
    async def ctx(self, async_client, db_session):
        meta = await create_base_scene(db_session)
        await db_session.flush()
        return async_client, meta["project_id"], meta["entity_ids"]

    async def test_create_alias(self, ctx):
        client, pid, eids = ctx
        resp = await client.post(f"/api/world/aliases?novel_id={pid}", json={
            "entity_id": eids["克莱恩·莫雷蒂"],
            "alias": "愚者",
            "alias_type": "nickname",
        })
        assert resp.status_code == 201
        assert resp.json()["alias"] == "愚者"

    async def test_get_aliases(self, ctx):
        client, pid, eids = ctx
        eid = eids["克莱恩·莫雷蒂"]
        # 创建两个别名
        for alias, atype in [("愚者", "nickname"), ("夏洛克·莫里亚蒂", "alias")]:
            await client.post(f"/api/world/aliases?novel_id={pid}", json={
                "entity_id": eid, "alias": alias, "alias_type": atype,
            })
        resp = await client.get(f"/api/world/aliases?novel_id={pid}&entity_id={eid}")
        assert resp.status_code == 200
        aliases = resp.json().get("items", [])
        assert len(aliases) >= 2
        alias_names = [a["alias"] for a in aliases]
        assert "愚者" in alias_names

    async def test_delete_alias(self, ctx):
        client, pid, eids = ctx
        create = await client.post(f"/api/world/aliases?novel_id={pid}", json={
            "entity_id": eids["克莱恩·莫雷蒂"],
            "alias": "临时别名",
            "alias_type": "alias",
        })
        aid = create.json()["id"]
        del_resp = await client.delete(f"/api/world/aliases/{aid}?novel_id={pid}")
        assert del_resp.status_code == 204


class TestWorldMissingFlows:
    """候选对象接受/忽略、抽取任务、关联图谱"""

    @pytest_asyncio.fixture
    async def ctx(self, async_client: AsyncClient, db_session: AsyncSession):
        meta = await create_base_scene(db_session)
        await db_session.flush()
        return async_client, meta["project_id"], meta["entity_ids"]

    async def test_accept_candidate_creates_entity(self, ctx):
        client, pid, _ = ctx
        create_resp = await client.post(f"/api/world/candidates?novel_id={pid}", json={
            "name": "夜之女王",
            "entity_type": "character_ref",
            "summary": "神秘的夜之统治者",
            "suggested_action": "create_new",
        })
        assert create_resp.status_code == 201
        candidate_id = create_resp.json()["id"]

        accept_resp = await client.post(
            f"/api/world/candidates/{candidate_id}/accept?novel_id={pid}"
        )
        assert accept_resp.status_code == 200
        data = accept_resp.json()
        assert data["name"] == "夜之女王"
        assert data["entity_type"] == "character_ref"
        assert data["status"] == "draft"

        get_resp = await client.get(f"/api/world/entities/{data['id']}?novel_id={pid}")
        assert get_resp.status_code == 200
        assert get_resp.json()["name"] == "夜之女王"

    async def test_ignore_candidate(self, ctx):
        client, pid, _ = ctx
        create_resp = await client.post(f"/api/world/candidates?novel_id={pid}", json={
            "name": "路人甲",
            "entity_type": "character_ref",
            "summary": "一个不重要的角色",
            "suggested_action": "needs_user_decision",
        })
        assert create_resp.status_code == 201
        candidate_id = create_resp.json()["id"]
        assert create_resp.json()["status"] == "pending"

        update_resp = await client.put(
            f"/api/world/candidates/{candidate_id}?novel_id={pid}",
            json={"suggested_action": "ignore"},
        )
        assert update_resp.status_code == 200
        data = update_resp.json()
        assert data["suggested_action"] == "ignore"

    async def test_entity_extraction_task(self, ctx):
        client, pid, _ = ctx
        submit_resp = await client.post("/api/tasks", json={
            "task_type": "world_entity_extraction",
            "meta": {
                "novel_id": pid,
                "start_chapter": 1,
                "end_chapter": 1,
            },
        })
        assert submit_resp.status_code == 201
        data = submit_resp.json()
        assert "task_id" in data
        assert data["status"] == "pending"

        task_id = data["task_id"]
        status_resp = await client.get(f"/api/tasks/{task_id}")
        assert status_resp.status_code == 200
        status_data = status_resp.json()
        assert status_data["task_type"] == "world_entity_extraction"
        assert status_data["status"] in ("pending", "running", "completed", "failed")

    async def test_related_entity_graph(self, ctx):
        client, pid, eids = ctx
        eid = eids["克莱恩·莫雷蒂"]
        resp = await client.get(f"/api/world/entities/{eid}/related?novel_id={pid}")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        if len(data) > 0:
            item = data[0]
            assert "entity_id" in item
            assert "name" in item
            assert "entity_type" in item
