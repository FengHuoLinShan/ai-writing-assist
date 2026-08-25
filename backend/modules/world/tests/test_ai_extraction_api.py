from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.tasks.models import AsyncTask
from modules.evidence.facade import attach_result_ref, require_confirmation


@pytest.mark.asyncio
async def test_world_alias_relation_extract_rejects_invalid_context_confirmation(
    async_client: AsyncClient,
) -> None:
    project_resp = await async_client.post(
        "/api/projects",
        json={"title": "别名关系补抽"},
    )
    assert project_resp.status_code == 201
    novel_id = project_resp.json()["id"]

    resp = await async_client.post(
        "/api/world/alias-relations/extract",
        json={
            "novel_id": novel_id,
            "context_confirmation_id": "00000000-0000-0000-0000-000000009999",
            "start_chapter": 1,
            "end_chapter": 3,
            "scene_ids": ["scene-a"],
        },
    )

    assert resp.status_code == 400
    assert "context_confirmation_id" in resp.text


@pytest.mark.asyncio
async def test_world_alias_relation_extract_enqueues_domain_task_after_confirmation(
    async_client: AsyncClient,
    db_session: AsyncSession,
    account_llm_connection: dict,
) -> None:
    project_resp = await async_client.post(
        "/api/projects",
        json={"title": "别名关系补抽"},
    )
    assert project_resp.status_code == 201
    novel_id = project_resp.json()["id"]
    confirmation_resp = await async_client.post(
        "/api/evidence/compilation/confirm",
        json={
            "novel_id": novel_id,
            "action": "world.alias_relations.extract",
            "task": "确认别名/关系补抽参考资料",
            "scope": "chapter",
            "chapter_index": 1,
        },
    )
    assert confirmation_resp.status_code == 201
    confirmation_id = confirmation_resp.json()["id"]

    resp = await async_client.post(
        "/api/world/alias-relations/extract",
        json={
            "novel_id": novel_id,
            "context_confirmation_id": confirmation_id,
            "start_chapter": 1,
            "end_chapter": 3,
            "scene_ids": ["scene-a"],
        },
    )

    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["status"] == "pending"
    result = await db_session.execute(
        select(AsyncTask).where(AsyncTask.id == uuid.UUID(data["task_id"]))
    )
    task = result.scalar_one()
    assert task.task_type == "world_alias_relation_extraction"
    assert task.meta["novel_id"] == novel_id
    assert task.meta["context_confirmation_id"] == confirmation_id
    assert task.meta["start_chapter"] == 1
    assert task.meta["end_chapter"] == 3
    assert task.meta["scene_ids"] == ["scene-a"]
    assert task.meta["llm_execution_snapshot"]["novel_id"] == novel_id
    assert task.meta["llm_execution_snapshot"]["profile_hash"]


@pytest.mark.asyncio
async def test_world_alias_relation_extraction_task_rejects_ordinary_session(
    db_session: AsyncSession,
) -> None:
    from modules.world import tasks as world_tasks

    class FakeTask:
        id = uuid.uuid4()
        task_type = "world_alias_relation_extraction"
        status = "running"
        attempt = 1
        lease_id = str(uuid.uuid4())
        meta = {
            "novel_id": "00000000-0000-0000-0000-000000000001",
            "context_confirmation_id": "00000000-0000-0000-0000-000000000002",
            "start_chapter": 1,
            "end_chapter": 3,
            "scene_ids": ["scene-a"],
        }
        result = {}

    with pytest.raises(RuntimeError, match="fenced TaskWorker handler session"):
        await world_tasks.handle_world_alias_relation_extraction(
            db_session,
            FakeTask(),
        )


@pytest.mark.asyncio
async def test_world_alias_relation_extraction_task_requires_novel_id() -> None:
    from modules.world import tasks as world_tasks

    db = SimpleNamespace(task_checkpoint_enabled=True)

    class FakeTask:
        id = uuid.uuid4()
        task_type = "world_alias_relation_extraction"
        status = "running"
        attempt = 1
        lease_id = str(uuid.uuid4())
        meta = {
            "context_confirmation_id": "00000000-0000-0000-0000-000000000002",
            "start_chapter": 1,
            "end_chapter": 3,
        }
        result = {}

        def update_progress(self, value: float) -> None:
            raise AssertionError(f"progress should not update: {value}")

    with pytest.raises(
        ValueError,
        match="novel_id is required for world_alias_relation_extraction",
    ):
        await world_tasks.handle_world_alias_relation_extraction(
            db,
            FakeTask(),
        )


@pytest.mark.asyncio
async def test_promoting_extracted_candidate_marks_confirmation_needs_review(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    project_resp = await async_client.post("/api/projects", json={"title": "世界补抽"})
    assert project_resp.status_code == 201
    novel_id = project_resp.json()["id"]

    entity_resp = await async_client.post(
        "/api/world/entities",
        params={"novel_id": novel_id},
        json={
            "entity_type": "item",
            "name": "霜华剑",
            "summary": "候选物品",
            "status": "candidate",
            "force_create": True,
        },
    )
    assert entity_resp.status_code == 201
    entity_id = entity_resp.json()["id"]

    confirmation_resp = await async_client.post(
        "/api/evidence/compilation/confirm",
        json={
            "novel_id": novel_id,
            "action": "world.alias_relations.extract",
            "task": "确认别名/关系补抽参考资料",
            "scope": "chapter",
            "chapter_index": 1,
        },
    )
    assert confirmation_resp.status_code == 201
    confirmation_id = confirmation_resp.json()["id"]
    await attach_result_ref(
        db_session,
        novel_id=novel_id,
        confirmation_id=confirmation_id,
        result_type="world_entity",
        result_id=entity_id,
        status="done",
    )

    promote_resp = await async_client.post(
        f"/api/world/entities/{entity_id}/promote",
        params={"novel_id": novel_id},
        json={"approved_by": "manual"},
    )

    assert promote_resp.status_code == 200, promote_resp.text
    confirmation = await require_confirmation(
        db_session,
        novel_id=novel_id,
        action="world.alias_relations.extract",
        confirmation_id=confirmation_id,
    )
    assert confirmation.result_status == "needs_review"
    assert "candidate_promoted" in confirmation.stale_reasons
