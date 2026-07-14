"""
世界对象 E2E 测试 — CRUD + 关系 + 别名
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.e2e.seed_data import create_base_scene

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]


class TestWorldEntityCRUD:
    """世界对象 CRUD E2E 测试 — 覆盖创建、列表、查询、更新、删除"""

    @pytest_asyncio.fixture
    async def ctx(self, async_client: AsyncClient, db_session: AsyncSession):
        """返回 (client, project_id, entity_ids)"""
        meta = await create_base_scene(db_session)
        await db_session.flush()
        return async_client, meta["project_id"], meta["entity_ids"]

    async def test_world_entity_create_basic_returns_active_canonical(self, ctx):
        """人工创建的世界对象应直接成为已采用资产。"""
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
        assert data["status"] == "canonical"
        assert data["display_state"] == "active"

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

    async def test_world_entity_delete_deprecates_entity(self, ctx):
        """删除实体后保留记录并标记为 deprecated"""
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
        assert get_resp.status_code == 200
        assert get_resp.json()["status"] == "deprecated"


class TestRelationshipCRUD:
    """关系 CRUD E2E 测试 — 覆盖创建、列表、删除"""

    @pytest_asyncio.fixture
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
            "relation_type": "works_with",
            "description": "克莱恩与值夜者协作",
        }

        # Act
        resp = await client.post(f"/api/world/relations?novel_id={pid}", json=payload)

        # Assert
        assert resp.status_code == 201
        assert resp.json()["relation_type"] == "works_with"

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

    @pytest_asyncio.fixture
    async def ctx(self, async_client: AsyncClient, db_session: AsyncSession):
        meta = await create_base_scene(db_session)
        await db_session.flush()
        return async_client, meta["project_id"], meta["entity_ids"]

    async def test_alias_create_for_entity_returns_201(self, ctx):
        client, pid, eids = ctx
        response = await client.post(
            f"/api/world/aliases?novel_id={pid}",
            json={
                "entity_id": eids["克莱恩·莫雷蒂"],
                "alias": "愚者",
                "alias_type": "title",
            },
        )
        assert response.status_code == 201, response.text
        assert response.json()["alias"] == "愚者"

    async def test_alias_list_by_entity_returns_all_aliases(self, ctx):
        client, pid, eids = ctx
        await client.post(
            f"/api/world/aliases?novel_id={pid}",
            json={
                "entity_id": eids["克莱恩·莫雷蒂"],
                "alias": "周明瑞",
                "alias_type": "name",
            },
        )
        response = await client.get(f"/api/world/aliases?novel_id={pid}&q=周明瑞")
        assert response.status_code == 200, response.text
        assert response.json()["total"] == 1
        assert response.json()["items"][0]["entity_id"] == eids["克莱恩·莫雷蒂"]

    async def test_alias_delete_returns_204(self, ctx):
        client, pid, eids = ctx
        await client.post(
            f"/api/world/aliases?novel_id={pid}",
            json={
                "entity_id": eids["克莱恩·莫雷蒂"],
                "alias": "克莱恩",
                "alias_type": "name",
            },
        )
        response = await client.delete(
            f"/api/world/entities/{eids['克莱恩·莫雷蒂']}/aliases",
            params={"novel_id": pid, "alias": "克莱恩"},
        )
        assert response.status_code == 200, response.text
        listed = await client.get(f"/api/world/aliases?novel_id={pid}&q=克莱恩")
        assert listed.json()["total"] == 0


class TestWorldCandidateAndGraphFlows:
    """候选对象接受/忽略、抽取任务、关联图谱 E2E 测试"""

    @pytest_asyncio.fixture
    async def ctx(self, async_client: AsyncClient, db_session: AsyncSession):
        meta = await create_base_scene(db_session)
        await db_session.flush()
        return async_client, meta["project_id"], meta["entity_ids"]

    async def test_candidate_accept_creates_canonical_entity(self, ctx):
        client, pid, _ = ctx
        created = await client.post(
            f"/api/world/entities?novel_id={pid}",
            json={"name": "待确认遗物", "entity_type": "item", "status": "candidate"},
        )
        assert created.status_code == 201, created.text
        entity_id = created.json()["id"]
        promoted = await client.post(
            f"/api/world/entities/{entity_id}/promote?novel_id={pid}",
            json={"approved_by": "e2e"},
        )
        assert promoted.status_code == 200, promoted.text
        assert promoted.json()["status"] == "canonical"

    async def test_candidate_ignore_updates_suggested_action(self, ctx):
        client, pid, eids = ctx
        candidate = await client.post(
            f"/api/world/entities?novel_id={pid}",
            json={"name": "愚者", "entity_type": "character", "status": "candidate"},
        )
        assert candidate.status_code == 201, candidate.text
        candidate_id = candidate.json()["id"]
        resolved = await client.post(
            f"/api/world/entities/{candidate_id}/resolve-as-alias?novel_id={pid}",
            json={
                "target_entity_id": eids["克莱恩·莫雷蒂"],
                "alias": "愚者",
                "alias_type": "title",
            },
        )
        assert resolved.status_code == 200, resolved.text
        assert resolved.json()["candidate_entity_id"] == candidate_id
        merged = await client.get(f"/api/world/entities/{candidate_id}?novel_id={pid}")
        assert merged.json()["status"] == "merged"

    async def test_generic_task_submit_rejects_module_owned_type(self, ctx):
        """通用任务端点不得绕过业务模块的请求 schema。"""
        client, pid, _ = ctx

        submit_resp = await client.post(
            "/api/tasks",
            json={
                "task_type": "publish_chapter",
                "meta": {
                    "novel_id": pid,
                    "start_chapter": 1,
                    "end_chapter": 1,
                },
            },
        )

        assert submit_resp.status_code == 403

    async def test_world_entity_related_graph_returns_list_with_expected_fields(
        self, ctx
    ):
        client, pid, eids = ctx
        created = await client.post(
            f"/api/world/relations?novel_id={pid}",
            json={
                "source_id": eids["克莱恩·莫雷蒂"],
                "target_id": eids["值夜者"],
                "relation_type": "serves_with",
            },
        )
        assert created.status_code == 201, created.text
        response = await client.get(
            f"/api/world/entities/{eids['克莱恩·莫雷蒂']}/relations?novel_id={pid}"
        )
        assert response.status_code == 200, response.text
        items = response.json()["items"]
        assert any(item["id"] == created.json()["id"] for item in items)
