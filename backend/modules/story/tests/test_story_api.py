from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from pydantic import ValidationError

from modules.account.context import bind_principal, reset_principal
from modules.account.contracts import BOOTSTRAP_ACCOUNT_ID, AccountPrincipal
from modules.story.models import StorySimulationRun
from modules.story.schemas import StoryOneClickTaskRequest, StoryTaskResponse
from modules.world.models import CoreEntity


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
async def test_legacy_one_click_keeps_the_frozen_operation_request_shape(
    db_session, test_project_id, monkeypatch
):
    from modules.story import api

    captured = {}

    async def fresh(*_args, **_kwargs):
        return None

    async def snapshot(*_args, **_kwargs):
        return {"gateway": True}

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
        simulation_protocol="legacy",
    )
    await api._enqueue_confirmed_task(
        db_session,
        data,
        action="story.one_click.simulate",
        task_type="story_one_click",
    )
    assert captured["llm_execution_snapshot"] == {"gateway": True}
    assert "simulation_protocol" not in captured["request"]
    assert "rehearsal_rounds" not in captured["request"]
    assert "fork_round" not in captured["request"]
    assert not any(key.startswith("_local") for key in captured)
    assert "agent_llm_execution_snapshot" not in captured


@pytest.mark.asyncio
async def test_rehearsal_http_uses_simulation_v3_without_actor_cap(
    async_client: AsyncClient,
) -> None:
    novel_id = await _create_project(async_client, "Story simulation v3")
    scene_id = str(uuid.uuid4())
    actor_ids = [str(uuid.uuid4()) for _ in range(5)]
    with (
        patch(
            "core.config.get_settings",
            autospec=True,
            return_value=SimpleNamespace(story_rehearsal_enabled=True),
        ),
        patch(
            "modules.story.api._enqueue_confirmed_task",
            autospec=True,
            return_value=StoryTaskResponse(task_id="v3-task", status="pending"),
        ) as enqueue,
    ):
        response = await async_client.post(
            f"/api/story/scenes/{scene_id}/rehearsals",
            json={
                "novel_id": novel_id,
                "scene_id": scene_id,
                "character_ids": actor_ids,
                "context_confirmation_id": "v3-confirmation",
                "simulation_protocol": "simulation_v3",
                "rehearsal_rounds": 1,
            },
        )

    assert response.status_code == 202
    assert enqueue.await_args.args[1].simulation_protocol == "simulation_v3"
    assert enqueue.await_args.args[1].rehearsal_rounds == 1


@pytest.mark.asyncio
async def test_rehearsal_http_rejects_multi_round_submission_without_budget_preview(
    async_client: AsyncClient,
) -> None:
    novel_id = await _create_project(async_client, "Story v3 round budget")
    scene_id = str(uuid.uuid4())
    with patch(
        "core.config.get_settings",
        autospec=True,
        return_value=SimpleNamespace(story_rehearsal_enabled=True),
    ):
        response = await async_client.post(
            f"/api/story/scenes/{scene_id}/rehearsals",
            json={
                "novel_id": novel_id,
                "scene_id": scene_id,
                "character_ids": [str(uuid.uuid4())],
                "context_confirmation_id": "v3-confirmation",
                "simulation_protocol": "simulation_v3",
                "rehearsal_rounds": 2,
            },
        )

    assert response.status_code == 409
    assert "当前一次只提交一回合" in response.json()["detail"]


@pytest.mark.asyncio
@pytest.mark.parametrize("reference_kind", ["object", "map_node"])
async def test_rehearsal_http_rejects_unowned_or_missing_world_identity_before_enqueue(
    async_client: AsyncClient, db_session, test_project_id, reference_kind: str
) -> None:
    actor = CoreEntity(
        novel_id=uuid.UUID(test_project_id),
        entity_type="character",
        name="已采用角色",
        status="canonical",
    )
    db_session.add(actor)
    await db_session.flush()
    scene_id = str(uuid.uuid4())
    with (
        patch(
            "core.config.get_settings",
            autospec=True,
            return_value=SimpleNamespace(story_rehearsal_enabled=True),
        ),
        patch("modules.story.api.require_fresh_confirmation", autospec=True) as fresh,
    ):
        response = await async_client.post(
            f"/api/story/scenes/{scene_id}/rehearsals",
            json={
                "novel_id": test_project_id,
                "scene_id": scene_id,
                "character_ids": [str(actor.id)],
                "context_confirmation_id": "v3-confirmation",
                "simulation_protocol": "simulation_v3",
                "simulation_seed": {
                    "participants": [{"kind": "object", "id": str(actor.id)}],
                    "locations": [{"kind": reference_kind, "id": str(uuid.uuid4())}],
                },
            },
        )
    assert response.status_code == 400
    assert "不属于当前作品或尚未采用" in response.json()["detail"]
    fresh.assert_not_awaited()


@pytest.mark.asyncio
async def test_scene_rehearsal_route_returns_read_only_conflict_for_old_protocol(
    async_client: AsyncClient,
) -> None:
    novel_id = await _create_project(async_client, "Story old rehearsal route")
    scene_id = str(uuid.uuid4())
    response = await async_client.post(
        f"/api/story/scenes/{scene_id}/rehearsals",
        json={
            "novel_id": novel_id,
            "scene_id": scene_id,
            "character_ids": [str(uuid.uuid4())],
            "context_confirmation_id": "old-confirmation",
            "simulation_protocol": "observation_v2",
            "rehearsal_rounds": 1,
        },
    )

    assert response.status_code == 409
    assert "旧协议排演只读" in response.json()["detail"]


def test_one_click_catalog_default_stays_legacy_and_v3_round_default_is_versioned():
    common = {
        "novel_id": str(uuid.uuid4()),
        "scene_id": str(uuid.uuid4()),
        "character_ids": [str(uuid.uuid4())],
        "context_confirmation_id": "catalog-confirmation",
    }
    catalog_request = StoryOneClickTaskRequest(**common)
    assert catalog_request.simulation_protocol == "legacy"

    v3_request = StoryOneClickTaskRequest(
        **common,
        simulation_protocol="simulation_v3",
    )
    assert v3_request.rehearsal_rounds == 1

    for protocol in ("rehearsal_v1", "observation_v2"):
        with pytest.raises(ValidationError, match="一至三名人物"):
            StoryOneClickTaskRequest(
                **{
                    **common,
                    "character_ids": [str(uuid.uuid4()) for _ in range(4)],
                },
                simulation_protocol=protocol,
            )


@pytest.mark.asyncio
async def test_one_click_rejects_new_old_protocol_and_old_history_cannot_cross_fork(
    async_client: AsyncClient,
    db_session,
    test_project_id: str,
) -> None:
    scene_id, actor_id, run_id = (uuid.uuid4() for _ in range(3))
    old_run = StorySimulationRun(
        id=run_id,
        novel_id=uuid.UUID(test_project_id),
        scene_id=scene_id,
        parent_id=None,
        fork_round=0,
        source_hash="b" * 64,
        request_json={
            "novel_id": test_project_id,
            "scene_id": str(scene_id),
            "character_ids": [str(actor_id)],
            "context_confirmation_id": "legacy-confirmation",
            "simulation_protocol": "rehearsal_v1",
            "rehearsal_rounds": 1,
            "fork_round": 0,
            "parent_rehearsal_id": None,
            "parent_round_hash": None,
        },
        budget_json={},
        result_json={"preview_only": True},
    )
    db_session.add(old_run)
    await db_session.flush()

    old_create = await async_client.post(
        "/api/story/tasks/one-click",
        json={
            "novel_id": test_project_id,
            "scene_id": str(scene_id),
            "character_ids": [str(actor_id)],
            "context_confirmation_id": "legacy-confirmation",
            "simulation_protocol": "rehearsal_v1",
            "rehearsal_rounds": 1,
        },
    )
    assert old_create.status_code == 409

    fork = await async_client.post(
        f"/api/story/rehearsals/{run_id}/forks",
        json={
            "novel_id": test_project_id,
            "scene_id": str(scene_id),
            "character_ids": [str(actor_id)],
            "context_confirmation_id": "v3-confirmation",
            "simulation_protocol": "simulation_v3",
            "rehearsal_rounds": 1,
            "parent_rehearsal_id": str(run_id),
            "fork_round": 1,
            "parent_round_hash": "c" * 64,
        },
    )
    assert fork.status_code == 409
    assert "不能跨协议重解释" in fork.json()["detail"]


@pytest.mark.asyncio
async def test_demo_cannot_read_or_replay_private_rehearsal(
    async_client: AsyncClient, test_project_id: str
) -> None:
    token = bind_principal(
        AccountPrincipal(
            account_id=BOOTSTRAP_ACCOUNT_ID,
            status="active",
            identity_type="demo_readonly",
            support_code="story-demo",
            access_scope="demo_readonly",
            demo_project_id=uuid.UUID(test_project_id),
        )
    )
    run_id = uuid.uuid4()
    try:
        with (
            patch("modules.story.rehearsals.read_rehearsal", autospec=True) as read,
            patch("modules.story.rehearsals.replay_rehearsal", autospec=True) as replay,
        ):
            shown = await async_client.get(
                f"/api/story/rehearsals/{run_id}",
                params={"novel_id": test_project_id},
            )
            replayed = await async_client.post(
                f"/api/story/rehearsals/{run_id}/replay",
                params={"novel_id": test_project_id},
            )
        assert shown.status_code == replayed.status_code == 404
        read.assert_not_awaited()
        replay.assert_not_awaited()
    finally:
        reset_principal(token)
