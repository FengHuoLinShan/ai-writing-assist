"""Cross-module authoring lifecycle integration tests."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.llm.schemas import LLMCallResponse
from infrastructure.tasks.models import AsyncTask

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


class _DeterministicWritingClient:
    model_name = "test-writing-model"

    def __init__(self) -> None:
        self.requests = []

    async def generate(self, request):
        self.requests.append(request)
        return LLMCallResponse(
            content="月蚀铜铃在第三章的旧塔回廊里响了三次。",
            model=self.model_name,
        )

    async def close(self) -> None:
        return None


async def _run_handler_as_task_worker(
    db_session: AsyncSession,
    task: AsyncTask,
    handler,
):
    """Execute one queued task with the same detached lease fence as TaskWorker."""
    from infrastructure.tasks.lifecycle import TaskLifecycleService
    from infrastructure.tasks.worker import TaskWorker, _TaskHandlerSession
    from run_worker import (
        _guard_active_task_project_finalize,
        _require_active_task_project,
    )

    lease_id = str(uuid.uuid4())
    task.mark_running(lease_id=lease_id)
    # The API test dependency shares this session and only flushes.  Release its
    # savepoint before opening the worker-like session, as a real claim does.
    await db_session.commit()
    db_session.expunge(task)

    bind = db_session.bind
    assert bind is not None
    lifecycle = TaskLifecycleService()
    task_session = _TaskHandlerSession(
        bind=bind,
        expire_on_commit=False,
        autoflush=False,
        join_transaction_mode="create_savepoint",
    )

    async def _checkpoint() -> bool:
        if not await _guard_active_task_project_finalize(task_session, task):
            return False
        return await lifecycle.checkpoint_running_attempt(
            task_session,
            task=task,
            lease_id=lease_id,
        )

    task_session.set_task_commit_hook(_checkpoint)
    try:
        task_session.begin_task_preflight()
        try:
            await _require_active_task_project(task_session, task)
            await TaskWorker._finish_task_preflight(task_session)
        finally:
            task_session.end_task_preflight()

        result = await handler(task_session, task)
        task_session.disable_task_commit_hook()
        assert await _guard_active_task_project_finalize(task_session, task)
        accepted = await lifecycle.finalize(
            task_session,
            task_id=task.id,
            lease_id=lease_id,
            status="done",
            result_data=result,
        )
        assert accepted is True
        return result
    finally:
        await task_session.close()


async def test_import_generate_publish_and_retrieve_serial_flow(
    async_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Imported canon can continue through generated prose into searchable canon."""
    from core.config import get_settings
    from modules.project import llm_runtime
    from modules.rag.facade import retrieve
    from modules.writing.tasks import handle_publish_chapter, handle_writing_generate

    writing_client = _DeterministicWritingClient()
    monkeypatch.setattr(
        llm_runtime.LLMClient,
        "from_resolved_profile",
        lambda _profile: writing_client,
    )
    embedding = [0.05] * get_settings().embedding_dim

    async def _deterministic_embedding(_self, value, **_kwargs):
        if isinstance(value, list):
            return [embedding.copy() for _ in value]
        return embedding.copy()

    monkeypatch.setattr(
        "infrastructure.llm.client.LLMClient.generate_embedding",
        _deterministic_embedding,
    )

    test_api_key = "sk-test-only"
    test_base_url = "https://llm.test/v1"

    project = await async_client.post(
        "/api/projects",
        json={
            "title": "串行创作生命周期",
            "settings": {
                "llm": {
                    "api_key": test_api_key,
                    "base_url": test_base_url,
                    "model": "test-model",
                }
            },
        },
    )
    assert project.status_code == 201, project.text
    novel_id = project.json()["id"]

    imported = await async_client.post(
        "/api/imports/upload",
        files={
            "file": (
                "serial-flow.txt",
                (
                    "第一章 雨夜\n林舟在钟楼收到一封信。\n\n"
                    "第二章 旧钥匙\n柳青带着旧钥匙与林舟会合。"
                ).encode(),
                "text/plain",
            )
        },
        data={"novel_id": novel_id},
    )
    assert imported.status_code == 201, imported.text
    assert imported.json()["total_chapters"] == 2

    first_chapter = await async_client.get(
        "/api/writing/chapters/1/draft",
        params={"novel_id": novel_id},
    )
    assert first_chapter.status_code == 200, first_chapter.text
    assert "林舟在钟楼收到一封信" in first_chapter.json()["content"]

    import_task_rows = await db_session.execute(
        select(AsyncTask).where(AsyncTask.task_type == "publish_chapter")
    )
    import_tasks = sorted(
        (
            task
            for task in import_task_rows.scalars()
            if task.meta and task.meta.get("novel_id") == novel_id
        ),
        key=lambda task: int(task.meta["chapter_index"]),
    )
    assert [task.meta["chapter_index"] for task in import_tasks] == [1, 2]
    for import_task in import_tasks:
        import_publish_result = await _run_handler_as_task_worker(
            db_session,
            import_task,
            handle_publish_chapter,
        )
        assert import_publish_result["rag_chunks"] >= 1
        assert import_publish_result["snapshot_id"]

    other_project = await async_client.post(
        "/api/projects",
        json={"title": "隔离对照项目"},
    )
    assert other_project.status_code == 201, other_project.text
    other_novel_id = other_project.json()["id"]
    other_published = await async_client.post(
        "/api/writing/drafts",
        json={
            "novel_id": other_novel_id,
            "chapter_index": 1,
            "title": "第一章 钟楼旧钥匙",
            "content": "异项目禁入标记藏在钟楼的旧钥匙背面。",
        },
    )
    assert other_published.status_code == 201, other_published.text
    other_publish_task = await db_session.get(
        AsyncTask,
        uuid.UUID(other_published.json()["task_id"]),
    )
    assert other_publish_task is not None
    await _run_handler_as_task_worker(
        db_session,
        other_publish_task,
        handle_publish_chapter,
    )

    confirmation = await async_client.post(
        "/api/context/confirm",
        json={
            "novel_id": novel_id,
            "action": "writing.generate",
            "task": "旧钥匙",
            "scope": "full",
            "visible_until_chapter": 2,
            "content_mode": "canonical",
        },
    )
    assert confirmation.status_code == 201, confirmation.text

    generation = await async_client.post(
        "/api/writing/generate",
        json={
            "novel_id": novel_id,
            "chapter_index": 3,
            "title": "第三章 月蚀铜铃",
            "instruction": "承接前两章并推进旧塔线索",
            "context_confirmation_id": confirmation.json()["id"],
        },
    )
    assert generation.status_code == 201, generation.text
    generation_task = await db_session.get(
        AsyncTask,
        uuid.UUID(generation.json()["task_id"]),
    )
    assert generation_task is not None

    generation_result = await _run_handler_as_task_worker(
        db_session,
        generation_task,
        handle_writing_generate,
    )
    candidate_id = generation_result["draft_id"]
    assert len(writing_client.requests) == 1
    generation_prompt = writing_client.requests[0].messages[-1].content
    assert "柳青带着旧钥匙与林舟会合" in generation_prompt
    assert "异项目禁入标记" not in generation_prompt
    assert test_api_key not in generation_prompt
    assert test_base_url not in generation_prompt
    assert "api_key" not in generation_prompt

    adopted = await async_client.post(
        f"/api/writing/drafts/{candidate_id}/adopt",
        params={"novel_id": novel_id},
    )
    assert adopted.status_code == 200, adopted.text
    adopted_draft = adopted.json()
    assert adopted_draft["status"] == "draft"
    assert adopted_draft["provenance_json"]["source_task_id"] == str(generation_task.id)

    published = await async_client.post(
        "/api/writing/drafts",
        json={
            "novel_id": novel_id,
            "chapter_index": 3,
            "title": adopted_draft["title"],
            "content": adopted_draft["content"],
            "draft_id": adopted_draft["id"],
            "expected_version": adopted_draft["version_number"],
        },
    )
    assert published.status_code == 201, published.text
    publish_payload = published.json()
    assert publish_payload["new_version"] is True
    assert publish_payload["draft"]["status"] == "published"
    assert publish_payload["task_id"]

    publish_task = await db_session.get(
        AsyncTask,
        uuid.UUID(publish_payload["task_id"]),
    )
    assert publish_task is not None
    publish_result = await _run_handler_as_task_worker(
        db_session,
        publish_task,
        handle_publish_chapter,
    )
    assert publish_result["rag_chunks"] >= 1
    assert publish_result["snapshot_id"]

    retrieved = await retrieve(
        db_session,
        novel_id,
        "月蚀铜铃",
        chapter_index=3,
        content_mode="canonical",
    )
    assert retrieved.chunks
    assert any("月蚀铜铃" in chunk.text for chunk in retrieved.chunks)
    assert all(chunk.novel_id == novel_id for chunk in retrieved.chunks)
