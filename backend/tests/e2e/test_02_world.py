"""
世界对象 E2E 测试 — CRUD + 关系 + 别名
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.e2e.seed_data import create_base_scene

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]


class TestWorldEntityCRUD:
    """世界对象 CRUD E2E 测试 — 覆盖创建、列表、查询、更新、删除"""

    @pytest.fixture
    async def ctx(self, async_client: AsyncClient, db_session: AsyncSession):
        """返回 (client, project_id, entity_ids)"""
        meta = await create_base_scene(db_session)
        await db_session.flush()
        return async_client, meta["project_id"], meta["entity_ids"]

    async def test_world_entity_create_basic_returns_201_with_draft_status(self, ctx):
        """使用基本字段创建世界对象应返回 201 且状态为 draft"""
        client, pid, _ = ctx

        # Act
        resp = await client.post(
            f"/api/world/entities?novel_id={pid}",
            json={
                "name": "测试城市",
                "entity_type": "location",
                "summary": "一座测试城市",
            },
        )

        # Assert
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "测试城市"
        assert data["entity_type"] == "location"
        assert data["status"] == "draft"

    async def test_world_entity_create_with_all_fields_persists_all_values(self, ctx):
        """使用完整字段创建世界对象应持久化所有字段值"""
        client, pid, _ = ctx

        # Arrange
        payload = {
            "name": "完整对象",
            "entity_type": "faction",
            "summary": "摘要",
            "public_info": "公开信息",
            "hidden_truth": "隐藏真相",
            "importance": 0.9,
            "importance_level": "core",
            "reveal_level": "author_only",
        }

        # Act
        resp = await client.post(f"/api/world/entities?novel_id={pid}", json=payload)

        # Assert
        assert resp.status_code == 201
        data = resp.json()
        assert data["public_info"] == "公开信息"
        assert data["hidden_truth"] == "隐藏真相"
        assert data["importance"] == 0.9
        assert data["importance_level"] == "core"

    async def test_world_entity_create_minimal_uses_default_importance(self, ctx):
        """仅必填字段创建世界对象应使用默认 importance"""
        client, pid, _ = ctx

        # Act
        resp = await client.post(
            f"/api/world/entities?novel_id={pid}",
            json={"name": "最小", "entity_type": "item"},
        )

        # Assert
        assert resp.status_code == 201
        assert resp.json()["importance"] == 0.5  # 默认值

    async def test_world_entity_list_returns_seeded_entities(self, ctx):
        """列表接口应返回种子数据中预置的实体"""
        client, pid, eids = ctx

        # Act
        resp = await client.get(f"/api/world/entities?novel_id={pid}")

        # Assert
        assert resp.status_code == 200
        data = resp.json()
        items = data.get("items", [])
        assert len(items) >= 10
        names = [e["name"] for e in items]
        assert "克莱恩·莫雷蒂" in names
        assert "廷根市" in names

    async def test_world_entity_list_filter_by_type_returns_only_matching(self, ctx):
        """按 entity_type 过滤应仅返回匹配类型的实体"""
        client, pid, _ = ctx

        # Act
        resp = await client.get(
            f"/api/world/entities?novel_id={pid}&entity_type=location"
        )

        # Assert
        assert resp.status_code == 200
        items = resp.json().get("items", [])
        assert all(e["entity_type"] == "location" for e in items)

    async def test_world_entity_get_by_id_returns_correct_entity_with_hidden_truth(
        self, ctx
    ):
        """按 ID 获取实体应返回正确对象及其隐藏真相"""
        client, pid, eids = ctx
        eid = eids["克莱恩·莫雷蒂"]

        # Act
        resp = await client.get(f"/api/world/entities/{eid}?novel_id={pid}")

        # Assert
        assert resp.status_code == 200
        assert resp.json()["name"] == "克莱恩·莫雷蒂"
        assert (
            resp.json()["hidden_truth"]
            == "来自另一个世界的穿越者，灵魂附身于克莱恩·莫雷蒂"
        )

    async def test_world_entity_get_nonexistent_returns_404(self, ctx):
        """获取不存在的实体 ID 应返回 404"""
        client, pid, _ = ctx

        # Act
        resp = await client.get(f"/api/world/entities/{uuid.uuid4()}?novel_id={pid}")

        # Assert
        assert resp.status_code == 404

    async def test_world_entity_update_summary_persists_change(self, ctx):
        """更新实体 summary 应持久化新值"""
        client, pid, eids = ctx
        eid = eids["值夜者"]

        # Act
        resp = await client.put(
            f"/api/world/entities/{eid}?novel_id={pid}",
            json={"summary": "更新后的摘要"},
        )

        # Assert
        assert resp.status_code == 200
        assert resp.json()["summary"] == "更新后的摘要"

    async def test_world_entity_update_partial_preserves_untouched_fields(self, ctx):
        """部分更新实体应只修改指定字段，其余保持不变"""
        client, pid, eids = ctx
        eid = eids["值夜者"]

        # Act
        resp = await client.put(
            f"/api/world/entities/{eid}?novel_id={pid}",
            json={"summary": "仅更新摘要"},
        )

        # Assert
        assert resp.status_code == 200
        data = resp.json()
        assert data["summary"] == "仅更新摘要"
        assert data["name"] == "值夜者"  # 原名称不变

    async def test_world_entity_delete_removes_entity_and_returns_404(self, ctx):
        """删除实体后再次获取应返回 404"""
        client, pid, _ = ctx

        # Arrange
        create = await client.post(
            f"/api/world/entities?novel_id={pid}",
            json={"name": "待删除", "entity_type": "item"},
        )
        eid = create.json()["id"]

        # Act
        del_resp = await client.delete(f"/api/world/entities/{eid}?novel_id={pid}")

        # Assert
        assert del_resp.status_code == 204

        # Act
        get_resp = await client.get(f"/api/world/entities/{eid}?novel_id={pid}")

        # Assert
        assert get_resp.status_code == 404


class TestRelationshipCRUD:
    """关系 CRUD E2E 测试 — 覆盖创建、列表、删除"""

    @pytest.fixture
    async def ctx(self, async_client: AsyncClient, db_session: AsyncSession):
        meta = await create_base_scene(db_session)
        await db_session.flush()
        return async_client, meta["project_id"], meta["entity_ids"]

    async def test_relationship_create_between_entities_returns_201(self, ctx):
        """在两个实体之间创建关系应返回 201"""
        client, pid, eids = ctx

        # Arrange
        payload = {
            "source_type": "world_entity",
            "source_id": eids["克莱恩·莫雷蒂"],
            "target_type": "world_entity",
            "target_id": eids["值夜者"],
            "relation_type": "member_of",
            "description": "克莱恩是值夜者成员",
        }

        # Act
        resp = await client.post(f"/api/world/relations?novel_id={pid}", json=payload)

        # Assert
        assert resp.status_code == 201
        assert resp.json()["relation_type"] == "member_of"

    async def test_relationship_list_returns_created_relationships(self, ctx):
        """列表接口应返回已创建的关系"""
        client, pid, eids = ctx

        # Arrange
        for rel in [
            ("member_of", "值夜者"),
            ("related_to", "源堡"),
            ("related_to", "罗塞尔日记"),
        ]:
            await client.post(
                f"/api/world/relations?novel_id={pid}",
                json={
                    "source_type": "world_entity",
                    "source_id": eids["克莱恩·莫雷蒂"],
                    "target_type": "world_entity",
                    "target_id": eids[rel[1]],
                    "relation_type": rel[0],
                },
            )

        # Act
        resp = await client.get(f"/api/world/relations?novel_id={pid}")

        # Assert
        assert resp.status_code == 200
        items = resp.json().get("items", [])
        assert len(items) >= 3

    async def test_relationship_delete_returns_204(self, ctx):
        """删除关系应返回 204"""
        client, pid, eids = ctx

        # Arrange
        create = await client.post(
            f"/api/world/relations?novel_id={pid}",
            json={
                "source_type": "world_entity",
                "source_id": eids["克莱恩·莫雷蒂"],
                "target_type": "world_entity",
                "target_id": eids["秘修会"],
                "relation_type": "opposes",
            },
        )
        rel_id = create.json()["id"]

        # Act
        del_resp = await client.delete(f"/api/world/relations/{rel_id}?novel_id={pid}")

        # Assert
        assert del_resp.status_code == 204


class TestAliasCRUD:
    """别名 CRUD E2E 测试 — 覆盖创建、列表、删除"""

    @pytest.fixture
    async def ctx(self, async_client: AsyncClient, db_session: AsyncSession):
        meta = await create_base_scene(db_session)
        await db_session.flush()
        return async_client, meta["project_id"], meta["entity_ids"]

    async def test_alias_create_for_entity_returns_201(self, ctx):
        pytest.skip("端点已移除: /api/world/aliases")

    async def test_alias_list_by_entity_returns_all_aliases(self, ctx):
        pytest.skip("端点已移除: /api/world/aliases")

    async def test_alias_delete_returns_204(self, ctx):
        pytest.skip("端点已移除: /api/world/aliases")


class TestWorldCandidateAndGraphFlows:
    """候选对象接受/忽略、抽取任务、关联图谱 E2E 测试"""

    @pytest.fixture
    async def ctx(self, async_client: AsyncClient, db_session: AsyncSession):
        meta = await create_base_scene(db_session)
        await db_session.flush()
        return async_client, meta["project_id"], meta["entity_ids"]

    async def test_candidate_accept_creates_canonical_entity(self, ctx):
        pytest.skip("端点已移除: /api/world/candidates")

    async def test_candidate_ignore_updates_suggested_action(self, ctx):
        pytest.skip("端点已移除: /api/world/candidates")

    async def test_task_submit_entity_extraction_returns_pending_task(self, ctx):
        """提交实体抽取任务应返回 pending 状态的任务"""
        client, pid, _ = ctx

        # Act
        submit_resp = await client.post(
            "/api/tasks",
            json={
                "task_type": "world_entity_extraction",
                "meta": {
                    "novel_id": pid,
                    "start_chapter": 1,
                    "end_chapter": 1,
                },
            },
        )

        # Assert
        assert submit_resp.status_code == 201
        data = submit_resp.json()
        assert "task_id" in data
        assert data["status"] == "pending"

        # Act — 查询任务详情
        task_id = data["task_id"]
        status_resp = await client.get(f"/api/tasks/{task_id}")

        # Assert
        assert status_resp.status_code == 200
        status_data = status_resp.json()
        assert status_data["task_type"] == "world_entity_extraction"
        assert status_data["status"] in ("pending", "running", "completed", "failed")

    async def test_world_entity_related_graph_returns_list_with_expected_fields(
        self, ctx
    ):
        pytest.skip("端点已移除: /api/world/entities/{eid}/related")
