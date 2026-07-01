from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.tasks.models import AsyncTask
from modules.context.facade import attach_result_ref, require_confirmation
from modules.world.services.extraction_service import ExtractionResult


@pytest.mark.asyncio
async def test_world_extract_rejects_missing_context_confirmation(
    async_client: AsyncClient,
) -> None:
    project_resp = await async_client.post("/api/projects", json={"title": "世界补抽"})
    assert project_resp.status_code == 201
    novel_id = project_resp.json()["id"]

    resp = await async_client.post(
        "/api/world/entities/extract",
        json={
            "novel_id": novel_id,
            "context_confirmation_id": "00000000-0000-0000-0000-000000009999",
            "start_chapter": 1,
            "end_chapter": 3,
        },
    )

    assert resp.status_code == 400
    assert "context_confirmation_id" in resp.text


@pytest.mark.asyncio
async def test_world_extract_enqueues_domain_task_after_confirmation(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    project_resp = await async_client.post("/api/projects", json={"title": "世界补抽"})
    assert project_resp.status_code == 201
    novel_id = project_resp.json()["id"]

    confirmation_resp = await async_client.post(
        "/api/context/confirm",
        json={
            "novel_id": novel_id,
            "action": "world.entities.extract",
            "task": "确认世界对象补抽参考资料",
            "scope": "chapter",
            "chapter_index": 1,
        },
    )
    assert confirmation_resp.status_code == 201
    confirmation_id = confirmation_resp.json()["id"]

    resp = await async_client.post(
        "/api/world/entities/extract",
        json={
            "novel_id": novel_id,
            "context_confirmation_id": confirmation_id,
            "start_chapter": 1,
            "end_chapter": 3,
            "batch_size": 2,
            "instruction": "只补抽长期资产",
        },
    )

    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["status"] == "pending"
    result = await db_session.execute(
        select(AsyncTask).where(AsyncTask.id == uuid.UUID(data["task_id"]))
    )
    task = result.scalar_one()
    assert task.task_type == "world_entity_extraction"
    assert task.meta["novel_id"] == novel_id
    assert task.meta["context_confirmation_id"] == confirmation_id
    assert task.meta["batch_size"] == 2


@pytest.mark.asyncio
async def test_world_alias_relation_extract_enqueues_domain_task(
    async_client: AsyncClient,
    db_session: AsyncSession,
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
    assert task.meta["start_chapter"] == 1
    assert task.meta["end_chapter"] == 3
    assert task.meta["scene_ids"] == ["scene-a"]


@pytest.mark.asyncio
async def test_world_entity_extraction_task_attaches_created_entity_refs(
    async_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modules.world.services.extraction_service import EntityExtractionService
    from modules.world.tasks import handle_world_entity_extraction

    project_resp = await async_client.post("/api/projects", json={"title": "世界补抽"})
    assert project_resp.status_code == 201
    novel_id = project_resp.json()["id"]
    confirmation_resp = await async_client.post(
        "/api/context/confirm",
        json={
            "novel_id": novel_id,
            "action": "world.entities.extract",
            "task": "确认世界对象补抽参考资料",
            "scope": "chapter",
            "chapter_index": 1,
        },
    )
    assert confirmation_resp.status_code == 201
    confirmation_id = confirmation_resp.json()["id"]
    entity_id = str(uuid.uuid4())

    async def fake_extract(self, db, novel_id, start_chapter, end_chapter, batch_size):
        return ExtractionResult(
            total_chapters=1,
            total_created=1,
            total_skipped=0,
            items=[{"id": entity_id, "name": "霜华剑"}],
        )

    monkeypatch.setattr(
        EntityExtractionService,
        "extract_entities_from_chapters",
        fake_extract,
    )

    class FakeTask:
        id = uuid.uuid4()
        meta = {
            "novel_id": novel_id,
            "start_chapter": 1,
            "end_chapter": 1,
            "context_confirmation_id": confirmation_id,
        }

        def __init__(self) -> None:
            self.progress: float | None = None

        def update_progress(self, value: float) -> None:
            self.progress = value

    task = FakeTask()
    result = await handle_world_entity_extraction(db_session, task)

    assert result["total_created"] == 1
    assert task.progress == 1.0
    confirmation = await require_confirmation(
        db_session,
        novel_id=novel_id,
        action="world.entities.extract",
        confirmation_id=confirmation_id,
    )
    assert {"type": "world_entity", "id": entity_id} in confirmation.result_refs


@pytest.mark.asyncio
async def test_world_alias_relation_extraction_task_invokes_di_handler(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modules.world import tasks as world_tasks

    calls: list[dict] = []

    async def fake_handler(db, novel_id, **kwargs):
        calls.append({"novel_id": novel_id, **kwargs})
        return {
            "total_aliases": 2,
            "total_relations": 1,
            "alias_relation_scenes": 3,
        }

    monkeypatch.setattr(
        world_tasks,
        "_container_get",
        lambda name: fake_handler
        if name == "world.run_alias_relation_extraction"
        else None,
    )

    class FakeTask:
        id = uuid.uuid4()
        meta = {
            "novel_id": "00000000-0000-0000-0000-000000000001",
            "start_chapter": 1,
            "end_chapter": 3,
            "scene_ids": ["scene-a"],
        }

        def __init__(self) -> None:
            self.progress: float | None = None

        def update_progress(self, value: float) -> None:
            self.progress = value

    task = FakeTask()
    result = await world_tasks.handle_world_alias_relation_extraction(db_session, task)

    assert result["total_aliases"] == 2
    assert result["total_relations"] == 1
    assert task.progress == 1.0
    assert calls == [
        {
            "novel_id": "00000000-0000-0000-0000-000000000001",
            "workflow_id": str(task.id),
            "scene_ids": ["scene-a"],
            "start_chapter": 1,
            "end_chapter": 3,
        }
    ]


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
        "/api/context/confirm",
        json={
            "novel_id": novel_id,
            "action": "world.entities.extract",
            "task": "确认世界对象补抽参考资料",
            "scope": "chapter",
            "chapter_index": 1,
        },
    )
    assert confirmation_resp.status_code == 201
    confirmation_id = confirmation_resp.json()["id"]
    await attach_result_ref(
        db_session,
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
        action="world.entities.extract",
        confirmation_id=confirmation_id,
    )
    assert confirmation.result_status == "needs_review"
    assert "candidate_promoted" in confirmation.stale_reasons
