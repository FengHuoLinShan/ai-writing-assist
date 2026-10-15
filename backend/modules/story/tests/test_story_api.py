from __future__ import annotations

import uuid
from contextlib import asynccontextmanager, contextmanager
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from pydantic import ValidationError
from sqlalchemy import select

from infrastructure.tasks.models import AsyncTask
from modules.account.context import bind_principal, reset_principal
from modules.account.contracts import BOOTSTRAP_ACCOUNT_ID, AccountPrincipal
from modules.evidence.compilation.knowledge.llm_schemas import (
    AuditDimensionCheck,
    AuditVerdictOutput,
)
from modules.story import tasks as story_tasks
from modules.story.generation import STORY_CHARACTER_CARD_ACTION, STORY_REACTION_ACTION
from modules.story.models import StorySimulationRun
from modules.story.outline_state.models import Scene
from modules.story.schemas import StoryOneClickTaskRequest, StoryTaskResponse
from modules.world.models import Character, CoreEntity


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
async def test_story_http_confirmation_enqueue_and_worker_return_source_bound_previews(
    async_client: AsyncClient,
    db_session,
    monkeypatch,
) -> None:
    project = await _create_project(async_client, "Story confirmed generation")
    scene_id = uuid.uuid4()
    character_id = uuid.uuid4()
    db_session.add_all(
        [
            Scene(
                id=scene_id,
                novel_id=uuid.UUID(project),
                scene_index=0,
                title="码头夜巡",
                goal="决定是否先保护同伴",
                status="canonical",
            ),
            CoreEntity(
                id=character_id,
                novel_id=uuid.UUID(project),
                entity_type="character",
                name="阿澜",
                status="canonical",
            ),
            Character(
                entity_id=character_id,
                novel_id=uuid.UUID(project),
                name="阿澜",
                personality="克制而警觉",
                status="canonical",
            ),
        ]
    )
    await db_session.flush()

    async def llm_snapshot(_db, novel_id):
        return {"novel_id": novel_id, "profile": {"model": "offline-test"}}

    async def settings(_db, _novel_id, _snapshot):
        return {"model": "offline-test"}

    @asynccontextmanager
    async def fake_client(_settings, _novel_id):
        class OfflineClient:
            model_name = "offline-test"

            async def generate_structured(self, request, schema, **_kwargs):
                if schema is AuditVerdictOutput:
                    required = []
                    for message in request.messages:
                        for line in (message.content or "").splitlines():
                            if line.startswith("必查维度："):
                                required = [
                                    value.strip()
                                    for value in line.split("：", 1)[1].split(",")
                                    if value.strip()
                                ]
                    return schema(
                        findings=[],
                        dimensions=[
                            AuditDimensionCheck(dimension=value, checked=True)
                            for value in required
                        ],
                        verdict="pass",
                    )
                fact_id = f"character_profile:{character_id}:personality"
                if schema.__name__ == "_CardOutput":
                    return schema(
                        interpretations=[
                            {
                                "category": "temperament",
                                "statement": "警觉使她先确认同伴的位置。",
                                "source_fact_ids": [fact_id],
                            }
                        ],
                        warnings=[],
                    )
                return schema(
                    scene_id=scene_id,
                    schema_version="story.reaction.v2",
                    proposals=[
                        {
                            "character_id": character_id,
                            "internal_pressure": "必须立即选择行动顺序",
                            "performances": [
                                {
                                    "option_id": "protect_first",
                                    "motivation": "先确保同伴安全",
                                    "source_fact_ids": [fact_id],
                                    "action": "把同伴拉到门后",
                                    "facial_expression": "眉心收紧",
                                    "body_language": "侧身挡住门口",
                                    "voice_and_dialogue": "压低声音说：先退后",
                                    "inner_response": "担心门后还有人",
                                    "attention": "盯着门闩的松动处",
                                    "change": "由观察转为保护同伴",
                                },
                                {
                                    "option_id": "control_risk",
                                    "motivation": "抢先控制门口风险",
                                    "source_fact_ids": [fact_id],
                                    "action": "先压住门闩",
                                    "facial_expression": "目光紧盯锁舌",
                                    "body_language": "一手按门一手护住工具",
                                    "voice_and_dialogue": "短促地说：我来压门",
                                    "inner_response": "害怕门被推开",
                                    "attention": "留意门外脚步",
                                    "change": "由观察转为抢险",
                                },
                            ],
                        }
                    ],
                    warnings=[],
                )

            async def close(self):
                return None

        yield OfflineClient()

    @contextmanager
    def no_provenance_scope():
        yield []

    async def no_checkpoint(*_args, **_kwargs):
        return None

    monkeypatch.setattr(
        "modules.story.task_submission.build_project_llm_execution_snapshot",
        llm_snapshot,
    )
    monkeypatch.setattr(story_tasks, "restore_project_llm_execution_settings", settings)
    monkeypatch.setattr(story_tasks, "_open_client", fake_client)
    monkeypatch.setattr(story_tasks, "_checkpoint_before_provider", no_checkpoint)
    monkeypatch.setattr(story_tasks, "require_task_checkpoint_session", lambda _db: None)
    monkeypatch.setattr(story_tasks, "managed_llm_provenance_scope", no_provenance_scope)

    scenarios = [
        (
            STORY_CHARACTER_CARD_ACTION,
            "/api/story/tasks/character-card",
            {
                "novel_id": project,
                "scene_id": str(scene_id),
                "character_id": str(character_id),
                "context_confirmation_id": None,
                "confirmed": True,
            },
            "story_character_card_generate",
            story_tasks.handle_story_character_card_generate,
            {
                "scope": "scene",
                "reveal_mode": "character",
                "viewpoint_character_id": str(character_id),
            },
        ),
        (
            STORY_REACTION_ACTION,
            "/api/story/tasks/reaction",
            {
                "novel_id": project,
                "scene_id": str(scene_id),
                "character_ids": [str(character_id)],
                "context_confirmation_id": None,
                "confirmed": True,
            },
            "story_reaction_propose",
            story_tasks.handle_story_reaction_propose,
            {"scope": "scene", "reveal_mode": "author_safe"},
        ),
    ]

    for action, route, task_payload, task_type, handler, scope in scenarios:
        confirmed = await async_client.post(
            "/api/evidence/compilation/confirm",
            json={
                "novel_id": project,
                "action": action,
                "task": action,
                "scene_id": str(scene_id),
                "character_ids": [str(character_id)],
                "visible_until_scene_id": str(scene_id),
                "budget_tokens": 6000,
                "content_mode": "canonical",
                **scope,
            },
        )
        assert confirmed.status_code == 201, confirmed.text
        task_payload["context_confirmation_id"] = confirmed.json()["id"]

        submitted = await async_client.post(route, json=task_payload)
        assert submitted.status_code == 202, submitted.text
        task = await db_session.get(AsyncTask, uuid.UUID(submitted.json()["task_id"]))
        assert task is not None and task.task_type == task_type
        assert task.meta["action"] == action
        assert task.meta["request"]["context_confirmation_id"] == confirmed.json()["id"]
        result = await handler(db_session, task)
        assert result["preview_only"] is True
        assert result["context_snapshot_id"]
        assert result["writes"] == []
        if action == STORY_CHARACTER_CARD_ACTION:
            content = result["preview"]["content"]
            assert content["version"] == "character_card.v2"
            assert content["fact_basis"]
            basis_ids = {item["fact_id"] for item in content["fact_basis"]}
            assert content["interpretations"][0]["source_fact_ids"] == [
                f"character_profile:{character_id}:personality"
            ]
            assert set(content["interpretations"][0]["source_fact_ids"]).issubset(
                basis_ids
            )
        else:
            assert result["preview"]["schema_version"] == "story.reaction.v2"
            performances = result["preview"]["proposals"][0]["performances"]
            assert len(performances) == 2
            assert all(
                item["source_fact_ids"]
                == [f"character_profile:{character_id}:personality"]
                for item in performances
            )
            assert all(not item["source_pattern_ids"] for item in performances)

    from modules.story.models import CharacterCard

    assert await db_session.scalar(select(CharacterCard.id)) is None


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

    from modules.story import task_submission

    async def fresh(*_args, **_kwargs):
        return None

    async def snapshot(*_args, **_kwargs):
        return {"gateway": True}

    async def enqueue(*_args, **kwargs):
        captured.update(kwargs["meta"])
        return SimpleNamespace(task_id=str(uuid.uuid4()), status="pending", reused=True)

    monkeypatch.setattr(task_submission, "require_fresh_confirmation", fresh)
    monkeypatch.setattr(task_submission, "build_project_llm_execution_snapshot", snapshot)
    monkeypatch.setattr(task_submission, "enqueue_task_with_optional_operation", enqueue)
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
        patch(
            "modules.story.task_submission.require_fresh_confirmation", autospec=True
        ) as fresh,
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


@pytest.mark.parametrize("declared_ids", [[], [str(uuid.uuid4())]])
def test_v3_seed_participants_must_match_selected_actors(declared_ids: list[str]) -> None:
    selected = str(uuid.uuid4())
    with pytest.raises(ValidationError, match="participants must match selected actors"):
        StoryOneClickTaskRequest(
            novel_id=str(uuid.uuid4()),
            scene_id=str(uuid.uuid4()),
            character_ids=[selected],
            context_confirmation_id="v3-confirmation",
            simulation_protocol="simulation_v3",
            simulation_seed={
                "participants": [
                    {"kind": "object", "id": identifier} for identifier in declared_ids
                ]
            },
        )


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


@pytest.mark.asyncio
async def test_assistant_story_task_keeps_the_root_provider_snapshot(
    db_session, test_project_id, monkeypatch
):
    from modules.story import task_submission
    from modules.story.schemas import StoryCardTaskRequest

    captured = {}

    async def fresh(*_args, **_kwargs):
        return SimpleNamespace(
            compile_options={
                "consumer_action": "story.character_card.generate",
                "retrieval_purpose": "story_character_card",
                "scope": "scene",
                "scene_id": str(request.scene_id),
                "visible_until_scene_id": str(request.scene_id),
                "chapter_index": None,
                "visible_until_chapter": None,
                "visible_until_offset": None,
                "content_mode": "canonical",
                "context_mode": "canonical",
                "include_pending_objects": False,
                "budget_tokens": 6000,
                "character_ids": [str(request.character_id)],
                "reveal_mode": "character",
                "viewpoint_character_id": str(request.character_id),
            }
        )

    async def no_existing(*_args, **_kwargs):
        return None

    async def no_fallback(*_args, **_kwargs):
        raise AssertionError("assistant snapshot must not be replaced")

    async def enqueue(*_args, **kwargs):
        captured.update(kwargs["meta"])
        return SimpleNamespace(task_id="task-1", status="pending", reused=True)

    monkeypatch.setattr(task_submission, "require_fresh_confirmation", fresh)
    monkeypatch.setattr(task_submission, "get_operation_task", no_existing)
    monkeypatch.setattr(
        task_submission, "build_project_llm_execution_snapshot", no_fallback
    )
    monkeypatch.setattr(task_submission, "enqueue_task_with_optional_operation", enqueue)
    request = StoryCardTaskRequest(
        novel_id=test_project_id,
        scene_id=str(uuid.uuid4()),
        character_id=str(uuid.uuid4()),
        context_confirmation_id="confirmation-1",
        operation_id=uuid.uuid4(),
        confirmed=True,
    )
    snapshot = {"novel_id": test_project_id, "gateway": "root-run-snapshot"}
    result = await task_submission.enqueue_confirmed_story_task(
        db_session,
        request,
        action="story.character_card.generate",
        task_type="story_character_card_generate",
        llm_execution_snapshot=snapshot,
    )
    assert result.task_id == "task-1"
    assert captured["llm_execution_snapshot"] == snapshot
    assert captured["action"] == "story.character_card.generate"
