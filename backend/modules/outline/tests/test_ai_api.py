from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.tasks.models import AsyncTask


@pytest.mark.parametrize(
    ("path", "action", "task_type", "payload"),
    [
        (
            "/api/outline/analyze",
            "outline.analyze",
            "outline_analyze",
            {"start_chapter": 1, "end_chapter": 5, "instruction": "分析节奏"},
        ),
        (
            "/api/outline/generate",
            "outline.generate",
            "outline_generate",
            {"start_chapter": 1, "end_chapter": 5, "instruction": "生成主线"},
        ),
        (
            "/api/outline/chapter-scenes/extract",
            "outline.chapter_scenes.extract",
            "outline_chapter_scenes_extract",
            {"chapter_index": 2, "instruction": "提取 Scene 卡"},
        ),
    ],
)
@pytest.mark.asyncio
async def test_outline_ai_apis_reject_missing_context_confirmation(
    async_client: AsyncClient,
    path: str,
    action: str,
    task_type: str,
    payload: dict,
) -> None:
    project_resp = await async_client.post("/api/projects", json={"title": "大纲 AI"})
    assert project_resp.status_code == 201
    novel_id = project_resp.json()["id"]

    resp = await async_client.post(
        path,
        json={
            "novel_id": novel_id,
            "context_confirmation_id": "00000000-0000-0000-0000-000000009999",
            **payload,
        },
    )

    assert resp.status_code == 400
    assert "context_confirmation_id" in resp.text


@pytest.mark.parametrize(
    ("path", "action", "task_type", "payload"),
    [
        (
            "/api/outline/analyze",
            "outline.analyze",
            "outline_analyze",
            {"start_chapter": 1, "end_chapter": 5, "instruction": "分析节奏"},
        ),
        (
            "/api/outline/generate",
            "outline.generate",
            "outline_generate",
            {"start_chapter": 1, "end_chapter": 5, "instruction": "生成主线"},
        ),
        (
            "/api/outline/chapter-scenes/extract",
            "outline.chapter_scenes.extract",
            "outline_chapter_scenes_extract",
            {"chapter_index": 2, "instruction": "提取 Scene 卡"},
        ),
    ],
)
@pytest.mark.asyncio
async def test_outline_ai_apis_enqueue_domain_tasks_after_confirmation(
    async_client: AsyncClient,
    db_session: AsyncSession,
    path: str,
    action: str,
    task_type: str,
    payload: dict,
) -> None:
    project_resp = await async_client.post("/api/projects", json={"title": "大纲 AI"})
    assert project_resp.status_code == 201
    novel_id = project_resp.json()["id"]

    confirmation_resp = await async_client.post(
        "/api/context/confirm",
        json={
            "novel_id": novel_id,
            "action": action,
            "task": "确认大纲 AI 参考资料",
            "scope": "chapter",
            "chapter_index": payload.get("chapter_index") or payload.get("start_chapter"),
        },
    )
    assert confirmation_resp.status_code == 201
    confirmation_id = confirmation_resp.json()["id"]

    resp = await async_client.post(
        path,
        json={
            "novel_id": novel_id,
            "context_confirmation_id": confirmation_id,
            **payload,
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
    assert task.task_type == task_type
    assert task.meta["novel_id"] == novel_id
    assert task.meta["context_confirmation_id"] == confirmation_id
    assert task.meta["llm_execution_snapshot"]["profile_hash"]
