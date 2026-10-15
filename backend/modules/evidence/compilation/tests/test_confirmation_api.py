from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from httpx import AsyncClient

from modules.evidence.compilation.api import _validate_character_reveal_mode
from modules.evidence.compilation.models import ContextConfirmation
from modules.evidence.compilation.schemas import ContextConfirmRequest
from modules.evidence.compilation.services.confirmation_service import (
    resolve_retrieval_purpose,
)
from modules.story.outline_state.models import Scene
from modules.world.models import Character, CoreEntity


@pytest.mark.asyncio
async def test_get_confirmation_is_project_scoped_and_private(
    async_client: AsyncClient,
) -> None:
    project = await async_client.post("/api/projects", json={"title": "Trace owner"})
    other_project = await async_client.post(
        "/api/projects", json={"title": "Trace other"}
    )
    assert project.status_code == 201
    assert other_project.status_code == 201
    novel_id = project.json()["id"]
    other_novel_id = other_project.json()["id"]
    created = await async_client.post(
        "/api/evidence/compilation/confirm",
        json={
            "novel_id": novel_id,
            "action": "writing.generate",
            "task": "生成正文建议",
            "scope": "chapter",
            "chapter_index": 1,
        },
    )
    assert created.status_code == 201, created.text
    confirmation_id = created.json()["id"]

    response = await async_client.get(
        f"/api/evidence/compilation/confirmations/{confirmation_id}",
        params={"novel_id": novel_id},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["id"] == confirmation_id
    assert payload["result_status"] == "confirmed"
    assert payload["stale_reasons"] == []
    assert "compile_options" not in payload
    assert "rendered_context" not in payload

    cross_project = await async_client.get(
        f"/api/evidence/compilation/confirmations/{confirmation_id}",
        params={"novel_id": other_novel_id},
    )
    missing = await async_client.get(
        f"/api/evidence/compilation/confirmations/{uuid.uuid4()}",
        params={"novel_id": novel_id},
    )
    assert cross_project.status_code == 404
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_story_confirmation_validates_scene_cutoff_and_pov_ownership(
    async_client: AsyncClient,
    db_session,
) -> None:
    project = await async_client.post("/api/projects", json={"title": "Story cutoff"})
    other_project = await async_client.post(
        "/api/projects", json={"title": "Story cutoff other"}
    )
    assert project.status_code == other_project.status_code == 201
    novel_id = project.json()["id"]
    other_novel_id = other_project.json()["id"]
    scene_id = uuid.uuid4()
    foreign_scene_id = uuid.uuid4()
    character_id = uuid.uuid4()
    foreign_character_id = uuid.uuid4()
    db_session.add_all(
        [
            Scene(
                id=scene_id,
                novel_id=uuid.UUID(novel_id),
                scene_index=0,
                title="夜巡",
                goal="确认潮门是否被动过",
                status="canonical",
            ),
            Scene(
                id=foreign_scene_id,
                novel_id=uuid.UUID(other_novel_id),
                scene_index=0,
                title="他作的夜巡",
                goal="校验作品归属",
                status="canonical",
            ),
            CoreEntity(
                id=character_id,
                novel_id=uuid.UUID(novel_id),
                entity_type="character",
                name="阿澜",
                status="canonical",
            ),
            Character(
                entity_id=character_id,
                novel_id=uuid.UUID(novel_id),
                name="阿澜",
                personality="警觉",
                status="canonical",
            ),
            CoreEntity(
                id=foreign_character_id,
                novel_id=uuid.UUID(other_novel_id),
                entity_type="character",
                name="他作人物",
                status="canonical",
            ),
            Character(
                entity_id=foreign_character_id,
                novel_id=uuid.UUID(other_novel_id),
                name="他作人物",
                personality="警觉",
                status="canonical",
            ),
        ]
    )
    await db_session.flush()

    base = {
        "novel_id": novel_id,
        "action": "story.character_card.generate",
        "task": "人物卡预览",
        "scope": "scene",
        "scene_id": str(scene_id),
        "visible_until_scene_id": str(scene_id),
        "character_ids": [str(character_id)],
        "reveal_mode": "character",
        "viewpoint_character_id": str(character_id),
        "retrieval_purpose": "story_character_card",
        "budget_tokens": 6000,
    }
    confirmed = await async_client.post("/api/evidence/compilation/confirm", json=base)
    assert confirmed.status_code == 201, confirmed.text
    confirmation_record = await db_session.get(
        ContextConfirmation, uuid.UUID(confirmed.json()["id"])
    )
    assert confirmation_record is not None
    assert confirmation_record.action == base["action"]
    assert confirmation_record.compile_options["consumer_action"] == base["action"]
    assert (
        confirmation_record.compile_options["retrieval_purpose"] == "story_character_card"
    )
    assert confirmation_record.compile_options["viewpoint_character_id"] == str(
        character_id
    )
    assert confirmation_record.compile_options["visible_until_scene_id"] == str(scene_id)

    unknown_character_id = str(uuid.uuid4())
    missing_pov = await async_client.post(
        "/api/evidence/compilation/confirm",
        json={
            **base,
            "character_ids": [unknown_character_id],
            "viewpoint_character_id": unknown_character_id,
        },
    )
    assert missing_pov.status_code == 404

    absent_pov = await async_client.post(
        "/api/evidence/compilation/confirm",
        json={**base, "viewpoint_character_id": None},
    )
    assert absent_pov.status_code == 400

    foreign_pov = await async_client.post(
        "/api/evidence/compilation/confirm",
        json={
            **base,
            "character_ids": [str(foreign_character_id)],
            "viewpoint_character_id": str(foreign_character_id),
        },
    )
    assert foreign_pov.status_code == 404

    foreign_scene = await async_client.post(
        "/api/evidence/compilation/confirm",
        json={
            **base,
            "scene_id": str(foreign_scene_id),
            "visible_until_scene_id": str(foreign_scene_id),
        },
    )
    assert foreign_scene.status_code == 404

    mismatched_cutoff = await async_client.post(
        "/api/evidence/compilation/confirm",
        json={**base, "visible_until_scene_id": str(uuid.uuid4())},
    )
    assert mismatched_cutoff.status_code == 400

    widened_chapter = await async_client.post(
        "/api/evidence/compilation/confirm",
        json={**base, "visible_until_chapter": 4},
    )
    assert widened_chapter.status_code == 400

    mismatched_purpose = await async_client.post(
        "/api/evidence/compilation/confirm",
        json={**base, "retrieval_purpose": "story_character_reaction"},
    )
    assert mismatched_purpose.status_code == 400


def test_story_confirmation_schema_accepts_scene_cutoff_and_story_purposes() -> None:
    novel_id = str(uuid.uuid4())
    scene_id = str(uuid.uuid4())
    character_id = str(uuid.uuid4())
    request = ContextConfirmRequest(
        novel_id=novel_id,
        action="story.character_card.generate",
        task="人物卡预览",
        scope="scene",
        scene_id=scene_id,
        visible_until_scene_id=scene_id,
        character_ids=[character_id],
        reveal_mode="character",
        viewpoint_character_id=character_id,
        retrieval_purpose="story_character_card",
        budget_tokens=6000,
    )
    _validate_character_reveal_mode(request)

    without_cutoff = request.model_copy(update={"visible_until_scene_id": None})
    with pytest.raises(HTTPException) as error:
        _validate_character_reveal_mode(without_cutoff)
    assert error.value.status_code == 400


def test_story_retrieval_purpose_is_bound_to_operation():
    assert (
        resolve_retrieval_purpose(
            "story.character_card.generate",
            "generic_context",
            reveal_mode="character",
        )
        == "story_character_card"
    )
    assert (
        resolve_retrieval_purpose(
            "story.reaction.generate",
            "generic_context",
            reveal_mode="author_safe",
        )
        == "story_character_reaction"
    )
    assert (
        resolve_retrieval_purpose(
            "story.script.generate",
            "generic_context",
            reveal_mode="author_safe",
        )
        == "story_scene_script"
    )
