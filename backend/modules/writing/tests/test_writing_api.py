"""
Writing API 层测试

验证 HTTP 契约：多 Tab 冲突检测、获取草稿、版本历史等。
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.tasks.models import AsyncTask
from modules.evidence.compilation.models import ContextConfirmation
from modules.evidence.indexing.repositories import RagChunkRepository
from modules.writing.repositories import WritingDraftRepository
from modules.writing.schemas import WritingDraftCreate
from modules.writing.tasks import handle_publish_chapter


@pytest_asyncio.fixture
async def sample_draft(async_client: AsyncClient):
    project_resp = await async_client.post(
        "/api/projects",
        json={"title": "冲突测试项目"},
    )
    assert project_resp.status_code == 201
    novel_id = project_resp.json()["id"]

    resp = await async_client.post(
        "/api/writing/drafts",
        json={
            "novel_id": novel_id,
            "chapter_index": 1,
            "title": "v1 标题",
            "content": "v1 内容",
        },
    )
    assert resp.status_code == 201
    return resp.json()["draft"]


@pytest.mark.asyncio
async def test_update_draft_conflict_on_stale_updated_at(
    async_client: AsyncClient,
    sample_draft: dict,
) -> None:
    """Tab A 暂存后，Tab B 使用旧的 expected_updated_at 应收到 409"""
    draft_id = sample_draft["id"]
    novel_id = sample_draft["novel_id"]
    stale_updated_at = sample_draft["updated_at"]

    # Tab A 暂存
    resp = await async_client.put(
        f"/api/writing/drafts/{draft_id}?novel_id={novel_id}",
        json={
            "title": "Tab A 标题",
            "content": "Tab A 内容",
            "expected_updated_at": stale_updated_at,
        },
    )
    assert resp.status_code == 200

    # Tab B 仍使用旧的 expected_updated_at 保存
    resp = await async_client.put(
        f"/api/writing/drafts/{draft_id}?novel_id={novel_id}",
        json={
            "title": "Tab B 标题",
            "content": "Tab B 内容",
            "expected_updated_at": stale_updated_at,
        },
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_generate_rejects_missing_context_confirmation(
    async_client: AsyncClient,
) -> None:
    project_resp = await async_client.post(
        "/api/projects",
        json={"title": "AI 生成确认项目"},
    )
    assert project_resp.status_code == 201
    novel_id = project_resp.json()["id"]

    resp = await async_client.post(
        "/api/writing/generate",
        json={
            "novel_id": novel_id,
            "chapter_index": 1,
            "instruction": "写一个克制的开场",
            "context_confirmation_id": "00000000-0000-0000-0000-000000009999",
        },
    )

    assert resp.status_code == 400
    assert "context_confirmation_id" in resp.text


@pytest.mark.asyncio
async def test_adopt_candidate_route_returns_new_working_draft(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    project_resp = await async_client.post(
        "/api/projects",
        json={"title": "AI 建议采用项目"},
    )
    novel_id = project_resp.json()["id"]
    repo = WritingDraftRepository()
    candidate = await repo.create_with_status(
        db_session,
        WritingDraftCreate(
            novel_id=novel_id,
            chapter_index=1,
            title="AI 建议",
            content="采用后的正文",
            provenance_json={"source": "writing_generate", "prompt_hash": "abc"},
        ),
        status="candidate",
    )

    response = await async_client.post(
        f"/api/writing/drafts/{candidate.id}/adopt?novel_id={novel_id}",
    )

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["id"] != str(candidate.id)
    assert data["status"] == "draft"
    assert data["display_state"] == "active"
    assert data["source"] == "ai_generated"
    assert data["provenance_json"]["adopted_from_candidate_id"] == str(candidate.id)
    assert data["provenance_json"]["adopted_by"] == "author"
    assert data["provenance_json"]["prompt_hash"] == "abc"

    duplicate = await async_client.post(
        f"/api/writing/drafts/{candidate.id}/adopt?novel_id={novel_id}",
    )
    assert duplicate.status_code == 400
    assert "Only a candidate writing suggestion can be adopted" in duplicate.text


@pytest.mark.asyncio
async def test_generate_enqueues_domain_task_after_context_confirmation(
    async_client: AsyncClient,
    db_session: AsyncSession,
    account_llm_connection: dict,
) -> None:
    project_resp = await async_client.post(
        "/api/projects",
        json={"title": "AI 生成入队项目"},
    )
    assert project_resp.status_code == 201
    novel_id = project_resp.json()["id"]

    confirmation_resp = await async_client.post(
        "/api/evidence/compilation/confirm",
        json={
            "novel_id": novel_id,
            "action": "writing.generate",
            "task": "生成第 2 章候选正文",
            "scope": "chapter",
            "chapter_index": 2,
        },
    )
    assert confirmation_resp.status_code == 201
    confirmation_id = confirmation_resp.json()["id"]

    resp = await async_client.post(
        "/api/writing/generate",
        json={
            "novel_id": novel_id,
            "chapter_index": 2,
            "title": "第二章",
            "instruction": "保持悬疑感",
            "context_confirmation_id": confirmation_id,
        },
    )

    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["task_id"]
    assert data["status"] == "pending"

    result = await db_session.execute(
        select(AsyncTask).where(AsyncTask.id == uuid.UUID(data["task_id"]))
    )
    task = result.scalar_one()
    assert task.task_type == "writing_generate"
    assert task.meta["novel_id"] == novel_id
    assert task.meta["chapter_index"] == 2
    assert task.meta["context_confirmation_id"] == confirmation_id
    assert task.meta["generation_mode"] == "draft"
    assert task.meta["base_draft_id"] is None
    snapshot = task.meta["llm_execution_snapshot"]
    assert snapshot["novel_id"] == novel_id
    assert snapshot["profile"]["model"] == account_llm_connection["model"]
    assert snapshot["profile_hash"]
    serialized_snapshot = json.dumps(snapshot, ensure_ascii=False)
    assert account_llm_connection["api_key"] not in serialized_snapshot
    assert "api_key" not in snapshot["profile"]
    assert snapshot["sources"]["api_key"] == "account"

    confirmation_result = await db_session.execute(
        select(ContextConfirmation).where(
            ContextConfirmation.id == uuid.UUID(confirmation_id)
        )
    )
    confirmation = confirmation_result.scalar_one()
    assert confirmation.result_status == "running"
    assert {"type": "task", "id": data["task_id"]} in confirmation.result_refs


@pytest.mark.asyncio
async def test_generate_continue_requires_base_draft_id(
    async_client: AsyncClient,
) -> None:
    response = await async_client.post(
        "/api/writing/generate",
        json={
            "novel_id": str(uuid.uuid4()),
            "chapter_index": 2,
            "context_confirmation_id": str(uuid.uuid4()),
            "generation_mode": "continue",
        },
    )

    assert response.status_code == 422
    assert "base_draft_id is required for continue mode" in response.text


@pytest.mark.asyncio
async def test_saved_draft_publish_task_indexes_latest_content(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    project_resp = await async_client.post(
        "/api/projects",
        json={"title": "保存后发布项目"},
    )
    assert project_resp.status_code == 201
    novel_id = project_resp.json()["id"]

    saved_resp = await async_client.post(
        "/api/writing/drafts/autosave",
        json={
            "novel_id": novel_id,
            "chapter_index": 3,
            "title": "第 3 章",
            "content": "暂存旧正文",
        },
    )
    assert saved_resp.status_code == 201, saved_resp.text

    publish_resp = await async_client.post(
        "/api/writing/drafts",
        json={
            "novel_id": novel_id,
            "chapter_index": 3,
            "title": "第 3 章",
            "content": "发布时的新正文。潮声越过旧巷，角色终于做出选择。" * 12,
        },
    )
    assert publish_resp.status_code == 201, publish_resp.text
    task_id = publish_resp.json()["task_id"]

    result = await db_session.execute(
        select(AsyncTask).where(AsyncTask.id == uuid.UUID(task_id))
    )
    task = result.scalar_one()
    task.mark_running()
    await db_session.flush()

    with patch("infrastructure.llm.client.LLMClient", autospec=True) as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.generate_embedding = AsyncMock(
            side_effect=Exception("embedding down"),
        )
        mock_client_cls.return_value = mock_client

        # Direct handler execution emulates TaskWorker's fenced session.
        db_session.task_checkpoint_enabled = True  # type: ignore[attr-defined]
        publish_result = await handle_publish_chapter(db_session, task)

    assert publish_result["rag_chunks"] > 0

    chunks = await RagChunkRepository().find_by_chapter(
        db_session,
        uuid.UUID(novel_id),
        3,
    )
    assert chunks
    combined_text = "\n".join(chunk.text for chunk in chunks)
    assert "发布时的新正文" in combined_text
    assert "暂存旧正文" not in combined_text
