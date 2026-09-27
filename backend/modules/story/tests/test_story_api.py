from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from httpx import AsyncClient

from modules.story.schemas import StoryOneClickTaskRequest, StoryTaskResponse


async def _create_project(client: AsyncClient, title: str) -> str:
    response = await client.post("/api/projects", json={"title": title})
    assert response.status_code == 201
    return response.json()["id"]


@pytest.mark.asyncio
async def test_story_list_forwards_the_owned_novel_scope(
    async_client: AsyncClient,
) -> None:
    novel_id = await _create_project(async_client, "Story HTTP scope")
    with patch(
        "modules.story.api.list_character_cards",
        autospec=True,
        return_value=[],
    ) as list_cards:
        response = await async_client.get(
            "/api/story/character-cards",
            params={"novel_id": novel_id},
        )

    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0}
    assert str(list_cards.await_args.args[1]) == novel_id


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    [
        "/api/story/character-cards",
        "/api/story/character-cards/card-1",
        "/api/story/character-cards/card-1/revisions",
        "/api/story/scenes/scene-1/script-files",
        "/api/story/script-files/file-1",
        "/api/story/script-files/file-1/revisions",
        "/api/story/scenes/scene-1/story-context",
        "/api/story/scenes/scene-1/scripts",
    ],
)
async def test_story_reads_require_novel_id(
    async_client: AsyncClient,
    path: str,
) -> None:
    response = await async_client.get(path)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_story_task_route_preserves_202_and_action_contract(
    async_client: AsyncClient,
) -> None:
    novel_id = await _create_project(async_client, "Story task HTTP")
    scene_id = str(uuid.uuid4())
    with patch(
        "modules.story.api._enqueue_confirmed_task",
        autospec=True,
        return_value=StoryTaskResponse(task_id="task-1", status="pending"),
    ) as enqueue:
        response = await async_client.post(
            "/api/story/tasks/reaction",
            json={
                "novel_id": novel_id,
                "scene_id": scene_id,
                "context_confirmation_id": "confirmation-1",
                "confirmed": True,
            },
        )

    assert response.status_code == 202
    assert response.json() == {"task_id": "task-1", "status": "pending"}
    assert enqueue.await_args.kwargs["action"] == "story.reaction.generate"
    assert enqueue.await_args.kwargs["task_type"] == "story_reaction_propose"


@pytest.mark.asyncio
async def test_story_scene_alias_rejects_path_body_mismatch(
    async_client: AsyncClient,
) -> None:
    novel_id = await _create_project(async_client, "Story path mismatch")
    response = await async_client.post(
        f"/api/story/scenes/{uuid.uuid4()}/script-files",
        json={
            "novel_id": novel_id,
            "scene_id": str(uuid.uuid4()),
            "file_key": "main",
            "title": "主剧本",
            "confirmed": True,
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "scene path does not match body"


@pytest.mark.asyncio
async def test_rehearsal_submission_freezes_local_agent_separately(
    db_session, test_project_id, monkeypatch
):
    from modules.story import api

    captured = {}

    async def fresh(*_args, **_kwargs):
        return None

    async def snapshot(*_args, agent_executor=False, **_kwargs):
        return (
            {"local_agent": {"kind": "pi", "device_id": str(uuid.uuid4())}}
            if agent_executor
            else {"gateway": True}
        )

    async def enqueue(*_args, **kwargs):
        captured.update(kwargs["meta"])
        return SimpleNamespace(task_id=str(uuid.uuid4()), status="pending", reused=True)

    monkeypatch.setattr(api, "require_fresh_confirmation", fresh)
    monkeypatch.setattr(api, "build_project_llm_execution_snapshot", snapshot)
    monkeypatch.setattr(api, "enqueue_task_with_optional_operation", enqueue)
    data = StoryOneClickTaskRequest(
        novel_id=test_project_id,
        scene_id=str(uuid.uuid4()),
        character_ids=[str(uuid.uuid4())],
        context_confirmation_id="synthetic",
        simulation_protocol="rehearsal_v1",
        rehearsal_rounds=1,
    )
    await api._enqueue_confirmed_task(
        db_session,
        data,
        action="story.one_click.simulate",
        task_type="story_one_click",
    )
    assert captured["llm_execution_snapshot"] == {"gateway": True}
    assert captured["agent_llm_execution_snapshot"]["local_agent"]["kind"] == "pi"
    assert captured["_local_agent"] is True
    assert captured["_local_approved"] is False
