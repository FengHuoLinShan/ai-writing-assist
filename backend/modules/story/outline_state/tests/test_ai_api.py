from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.tasks.models import AsyncTask


def _story_outline_payload() -> dict:
    return {
        "base_revision_id": None,
        "idempotency_key": "p20-api-story-outline",
        "source": "manual",
        "provenance": {"actor": "author"},
        "title": "群岛共同体",
        "creative_core": {
            "premise": "孤立群岛必须共同面对退潮遗迹。",
            "tone_and_reader_promise": "克制的海洋奇幻。",
            "story_engine": "每次退潮都带来资源、真相与代价。",
            "ending_direction": "分权联盟取代单一王座。",
        },
        "outline_markdown": "# 总体方向\n\n故事围绕共同承担秩序推进。",
        "major_storylines": [],
        "macro_movements": [],
        "open_decisions": [],
    }


@pytest.mark.parametrize(
    "path",
    [
        "/api/outline/chapter-scenes/extract",
        "/api/outline/chapter-scenes/apply",
    ],
)
@pytest.mark.asyncio
async def test_removed_chapter_scene_preview_routes_return_not_found(
    async_client: AsyncClient,
    path: str,
) -> None:
    response = await async_client.post(path, json={})

    assert response.status_code == 404


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
            {
                "contract_version": "outline_layer_v2",
                "target": "plot_thread",
                "mode": "create",
                "start_chapter": 1,
                "end_chapter": 5,
                "instruction": "生成主线",
                "selected_thread_ids": [],
                "selected_arc_ids": [],
                "selected_scene_ids": [],
            },
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
            {
                "contract_version": "outline_layer_v2",
                "target": "plot_thread",
                "mode": "create",
                "start_chapter": 1,
                "end_chapter": 5,
                "instruction": "生成主线",
                "selected_thread_ids": [],
                "selected_arc_ids": [],
                "selected_scene_ids": [],
            },
        ),
    ],
)
@pytest.mark.asyncio
async def test_outline_ai_apis_enqueue_domain_tasks_after_confirmation(
    async_client: AsyncClient,
    db_session: AsyncSession,
    account_llm_connection: dict,
    path: str,
    action: str,
    task_type: str,
    payload: dict,
) -> None:
    project_resp = await async_client.post("/api/projects", json={"title": "大纲 AI"})
    assert project_resp.status_code == 201
    novel_id = project_resp.json()["id"]

    if task_type == "outline_generate":
        outline_resp = await async_client.post(
            "/api/outline/story-outline/revisions",
            params={"novel_id": novel_id},
            json=_story_outline_payload(),
        )
        assert outline_resp.status_code == 201, outline_resp.text

    confirmation_resp = await async_client.post(
        "/api/evidence/compilation/confirm",
        json={
            "novel_id": novel_id,
            "action": action,
            "task": "确认大纲 AI 参考资料",
            "scope": "full" if task_type == "outline_generate" else "chapter",
            "chapter_index": payload.get("start_chapter"),
            "budget_tokens": 0 if task_type == "outline_generate" else 4000,
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
    if task_type == "outline_generate":
        assert task.meta["contract_version"] == "outline_layer_v2"
        assert task.meta["submission_fingerprint"]
        assert task.meta["context_provenance"]["input_budget_policy"] == (
            "no_application_truncation"
        )
        assert task.meta["context_provenance"]["actual_input_chars"] > 0


@pytest.mark.asyncio
async def test_p20_does_not_reintroduce_excluded_character_or_world_sections(
    async_client: AsyncClient,
    db_session: AsyncSession,
    account_llm_connection: dict,
) -> None:
    project_resp = await async_client.post(
        "/api/projects",
        json={"title": "P20 排除回流"},
    )
    assert project_resp.status_code == 201
    novel_id = project_resp.json()["id"]
    outline_resp = await async_client.post(
        "/api/outline/story-outline/revisions",
        params={"novel_id": novel_id},
        json=_story_outline_payload(),
    )
    assert outline_resp.status_code == 201, outline_resp.text
    character_resp = await async_client.post(
        f"/api/world/entities?novel_id={novel_id}",
        json={
            "entity_type": "character",
            "name": "被排除的人物",
            "status": "canonical",
        },
    )
    assert character_resp.status_code == 201, character_resp.text
    entity_resp = await async_client.post(
        f"/api/world/entities?novel_id={novel_id}",
        json={
            "entity_type": "artifact",
            "name": "被排除的对象",
            "status": "canonical",
        },
    )
    assert entity_resp.status_code == 201, entity_resp.text
    confirmation_resp = await async_client.post(
        "/api/evidence/compilation/confirm",
        json={
            "novel_id": novel_id,
            "action": "outline.generate",
            "task": "确认排除人物与世界对象",
            "scope": "full",
            "budget_tokens": 0,
            "excluded_asset_ids": {
                "context_sections": ["pov_knowledge", "world_entities"]
            },
        },
    )
    assert confirmation_resp.status_code == 201, confirmation_resp.text

    response = await async_client.post(
        "/api/outline/generate",
        json={
            "contract_version": "outline_layer_v2",
            "novel_id": novel_id,
            "context_confirmation_id": confirmation_resp.json()["id"],
            "target": "plot_thread",
            "mode": "create",
            "instruction": "设计不依赖已排除资料的新剧情线。",
            "selected_thread_ids": [],
            "selected_arc_ids": [],
            "selected_scene_ids": [],
        },
    )
    assert response.status_code == 201, response.text
    task = (
        await db_session.execute(
            select(AsyncTask).where(AsyncTask.id == uuid.UUID(response.json()["task_id"]))
        )
    ).scalar_one()
    provenance = task.meta["context_provenance"]
    assert provenance["included_asset_ids"]["characters"] == []
    assert provenance["included_asset_ids"]["entities"] == []
    assert provenance["top_k"]["characters"] == {
        "limit": 6,
        "candidate_count": 0,
        "reason": "confirmed_context_section_excluded",
    }
    assert provenance["top_k"]["world_entities"] == {
        "limit": 16,
        "candidate_count": 0,
        "reason": "confirmed_context_section_excluded",
    }


@pytest.mark.asyncio
async def test_p20_requires_explicit_no_eviction_confirmation(
    async_client: AsyncClient,
) -> None:
    project_resp = await async_client.post("/api/projects", json={"title": "P20 预算"})
    novel_id = project_resp.json()["id"]
    outline_resp = await async_client.post(
        "/api/outline/story-outline/revisions",
        params={"novel_id": novel_id},
        json={**_story_outline_payload(), "idempotency_key": "p20-budget-outline"},
    )
    assert outline_resp.status_code == 201
    confirmation_resp = await async_client.post(
        "/api/evidence/compilation/confirm",
        json={
            "novel_id": novel_id,
            "action": "outline.generate",
            "task": "确认默认预算会被拒绝",
            "scope": "full",
        },
    )
    assert confirmation_resp.status_code == 201

    response = await async_client.post(
        "/api/outline/generate",
        json={
            "contract_version": "outline_layer_v2",
            "novel_id": novel_id,
            "context_confirmation_id": confirmation_resp.json()["id"],
            "target": "plot_thread",
            "mode": "create",
            "instruction": "设计主线。",
        },
    )

    assert response.status_code == 400
    assert "no-eviction context confirmation" in response.text
