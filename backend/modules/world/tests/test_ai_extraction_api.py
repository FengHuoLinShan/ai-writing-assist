from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.tasks.models import AsyncTask
from modules.context.facade import attach_result_ref, require_confirmation
from modules.world.services.core.extraction_service import ExtractionResult


@pytest.mark.asyncio
async def test_entity_extraction_routes_new_assets_through_suggestion_queue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modules.world.models import CoreEntity
    from modules.world.schemas import WorldContextBundle
    from modules.world.services.core.extraction_service import EntityExtractionService

    novel_id = str(uuid.uuid4())
    draft_provider = SimpleNamespace(
        load_chapters=AsyncMock(
            return_value=[
                {
                    "chapter_index": 1,
                    "title": "雨夜",
                    "content": "沈砚在雨夜进入巡夜司。",
                }
            ]
        )
    )

    @asynccontextmanager
    async def _open_fake_project_llm_client(_db, actual_novel_id):
        assert actual_novel_id == novel_id
        yield FakeLLM()

    service = EntityExtractionService(
        draft_provider=draft_provider,
        project_llm_opener=_open_fake_project_llm_client,
    )
    entity_id = uuid.uuid4()
    suggestion_id = uuid.uuid4()
    entity = CoreEntity(
        id=entity_id,
        novel_id=uuid.UUID(novel_id),
        entity_type="character",
        name="沈砚",
        summary="巡夜人",
        public_info="雨夜入城",
        hidden_truth="身份不明",
        content_json={"_meta": {"auto_ingested": True}},
        status="candidate",
    )

    monkeypatch.setattr(
        "modules.world.facade.get_world_context",
        AsyncMock(
            return_value=WorldContextBundle(
                novel_id=novel_id,
                entities=[],
                total_count=0,
                reveal_mode="author_safe",
            )
        ),
    )

    class FakeLLM:
        model_name = "fake-model"

        @classmethod
        def from_project_settings(cls, _settings):
            return cls()

        async def generate_embedding(self, texts, *, is_query=False):
            del is_query
            return [[0.1] for _ in texts]

    monkeypatch.setattr("infrastructure.llm.client.LLMClient", FakeLLM)
    monkeypatch.setattr(
        "infrastructure.llm.prompt_loader.load_prompt",
        lambda *_args, **_kwargs: "extract",
    )

    async def fake_structured(_llm, _request, schema, **_kwargs):
        return schema(
            entities=[
                {
                    "name": "沈砚",
                    "entity_type": "character",
                    "summary": "巡夜人",
                    "public_info": "雨夜入城",
                    "hidden_truth": "身份不明",
                    "importance": 0.8,
                    "suggested_action": "create_new",
                    "candidate_reason": "长期主角",
                    "confidence": 0.9,
                    "source_chapter": 1,
                }
            ]
        )

    monkeypatch.setattr(
        "infrastructure.llm.agent_step_harness.run_managed_structured",
        fake_structured,
    )
    service._dedup_service.find_similar_entities = AsyncMock(return_value=[])
    service._suggestion_queue.create_core_entity_suggestion = AsyncMock(
        return_value=(
            SimpleNamespace(id=str(suggestion_id)),
            SimpleNamespace(id=str(entity_id)),
        )
    )
    service._entity_repo.get = AsyncMock(return_value=entity)
    service._entity_repo.create = AsyncMock(
        side_effect=AssertionError("extraction must not write CoreEntity directly")
    )
    db = AsyncMock()

    result = await service.extract_entities_from_chapters(
        db,
        novel_id,
        1,
        1,
    )

    assert result.total_created == 1
    assert result.items[0]["suggestion_id"] == str(suggestion_id)
    queue_call = service._suggestion_queue.create_core_entity_suggestion.await_args
    assert queue_call.kwargs["source_module"] == "world_extraction"
    assert queue_call.kwargs["compatibility_status"] == "candidate"
    service._entity_repo.create.assert_not_awaited()


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
) -> None:
    project_resp = await async_client.post(
        "/api/projects",
        json={"title": "别名关系补抽"},
    )
    assert project_resp.status_code == 201
    novel_id = project_resp.json()["id"]
    confirmation_resp = await async_client.post(
        "/api/context/confirm",
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
async def test_world_entity_extraction_task_attaches_created_entity_refs(
    async_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modules.world.services.core.extraction_service import EntityExtractionService
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
    suggestion_id = str(uuid.uuid4())

    async def fake_extract(self, db, novel_id, start_chapter, end_chapter, batch_size):
        return ExtractionResult(
            total_chapters=1,
            total_created=1,
            total_skipped=0,
            items=[
                {
                    "id": entity_id,
                    "suggestion_id": suggestion_id,
                    "name": "霜华剑",
                }
            ],
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
    assert {
        "type": "creation_suggestion",
        "id": suggestion_id,
    } in confirmation.result_refs


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
