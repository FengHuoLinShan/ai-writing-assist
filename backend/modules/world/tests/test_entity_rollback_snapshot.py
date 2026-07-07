"""
实体手动编辑回滚快照测试

验证 WorldEntityService.update() 会创建 EntityRevision 快照，
使得后续 rollback 可以恢复到编辑前状态。
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import NotFoundError


@pytest.fixture
async def test_project(async_client: AsyncClient):
    resp = await async_client.post(
        "/api/projects",
        json={"title": "回滚快照测试项目"},
    )
    assert resp.status_code == 201
    return resp.json()


@pytest.fixture
async def test_entity(async_client: AsyncClient, test_project: dict):
    resp = await async_client.post(
        f"/api/world/entities?novel_id={test_project['id']}",
        json={
            "entity_type": "character",
            "name": "原始名字",
            "summary": "原始摘要",
            "status": "canonical",
        },
    )
    assert resp.status_code == 201
    return resp.json()


@pytest.mark.asyncio
async def test_manual_entity_update_creates_revision_snapshot(
    async_client: AsyncClient,
    test_project: dict,
    test_entity: dict,
) -> None:
    """手动编辑实体后应生成 revision 快照，支持回滚"""
    novel_id = test_project["id"]
    entity_id = test_entity["id"]

    # 编辑实体
    update_resp = await async_client.put(
        f"/api/world/entities/{entity_id}?novel_id={novel_id}",
        json={"summary": "编辑后的摘要"},
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["summary"] == "编辑后的摘要"

    # 查询版本列表应非空
    revisions_resp = await async_client.get(
        f"/api/world/entities/{entity_id}/revisions?novel_id={novel_id}"
    )
    assert revisions_resp.status_code == 200
    revisions = revisions_resp.json()
    assert revisions["total"] >= 1
    assert len(revisions["items"]) >= 1

    # 回滚到 scene_index 0 应恢复到原始摘要
    rollback_resp = await async_client.post(
        f"/api/world/entities/{entity_id}/rollback?novel_id={novel_id}",
        json={"target_scene_index": 0},
    )
    assert rollback_resp.status_code == 200
    assert "summary" in rollback_resp.json()["restored_fields"]

    entity_resp = await async_client.get(
        f"/api/world/entities/{entity_id}?novel_id={novel_id}"
    )
    assert entity_resp.json()["summary"] == "原始摘要"


@pytest.mark.asyncio
async def test_rollback_with_no_data_returns_200_with_warning(
    async_client: AsyncClient,
    test_project: dict,
) -> None:
    """无 TextArchive 或 EntityRevision 时回滚应返回 200 + 警告，而非 404"""
    novel_id = test_project["id"]

    entity_resp = await async_client.post(
        f"/api/world/entities?novel_id={novel_id}",
        json={
            "entity_type": "character",
            "name": "无历史角色",
            "summary": "当前摘要",
            "status": "canonical",
        },
    )
    assert entity_resp.status_code == 201
    entity_id = entity_resp.json()["id"]

    rollback_resp = await async_client.post(
        f"/api/world/entities/{entity_id}/rollback?novel_id={novel_id}",
        json={"target_scene_index": 0},
    )
    assert rollback_resp.status_code == 200
    data = rollback_resp.json()
    assert data["restored_fields"] == []
    assert any("no rollback data" in w.lower() for w in data["warnings"])


@pytest.mark.asyncio
async def test_create_snapshot_rejects_cross_novel_entity(
    db_session: AsyncSession,
) -> None:
    """底层 snapshot 入口也必须校验 entity 归属。"""
    from modules.project.models import Project
    from modules.world.models import CoreEntity
    from modules.world.services.core.entity_revision_service import EntityRevisionService

    novel_id = uuid.uuid4()
    other_novel_id = uuid.uuid4()
    entity_id = uuid.uuid4()
    db_session.add_all(
        [
            Project(id=novel_id, title="项目一"),
            Project(id=other_novel_id, title="项目二"),
            CoreEntity(
                id=entity_id,
                novel_id=other_novel_id,
                entity_type="character",
                name="跨项目角色",
                status="canonical",
            ),
        ]
    )
    await db_session.flush()

    with pytest.raises(NotFoundError) as exc:
        await EntityRevisionService().create_snapshot(
            db_session,
            entity_id=str(entity_id),
            novel_id=str(novel_id),
        )
    assert exc.value.status_code == 404
