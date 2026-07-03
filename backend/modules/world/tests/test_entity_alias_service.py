"""EntityAliasService 测试 — 纯单元测试，repo 用 AsyncMock 替换。"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from modules.world.services.entity_alias_service import EntityAliasService


@pytest.fixture
def novel_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def alias_service() -> EntityAliasService:
    return EntityAliasService(repo=MagicMock())


def _make_entity(
    *,
    entity_id: str | None = None,
    novel_id: str | None = None,
    name: str = "Arthur",
    content_json: dict | None = None,
) -> MagicMock:
    entity = MagicMock()
    entity.id = uuid.UUID(entity_id) if entity_id else uuid.uuid4()
    entity.novel_id = uuid.UUID(novel_id) if novel_id else uuid.uuid4()
    entity.name = name
    entity.content_json = content_json if content_json is not None else {}
    return entity


@pytest.mark.asyncio
async def test_list_aliases_returns_alias_for_entity(
    novel_id: str,
    alias_service: EntityAliasService,
) -> None:
    entity = _make_entity(
        content_json={"aliases": [{"alias": "Art", "type": "nickname"}]},
    )
    alias_service.repo.get_by_novel = AsyncMock(return_value=([entity], 1))
    db = MagicMock()

    aliases = await alias_service.list_aliases(db, novel_id)

    assert len(aliases) == 1
    assert aliases[0]["entity_id"] == str(entity.id)
    assert aliases[0]["entity_name"] == "Arthur"
    assert aliases[0]["alias"] == "Art"
    assert aliases[0]["alias_type"] == "nickname"


@pytest.mark.asyncio
async def test_list_aliases_pagination(
    novel_id: str,
    alias_service: EntityAliasService,
) -> None:
    arthur = _make_entity(
        name="Arthur",
        content_json={"aliases": ["Art", "Athy"]},
    )
    bella = _make_entity(
        name="Bella",
        content_json={"aliases": ["Bell", "Bells"]},
    )
    alias_service.repo.get_by_novel = AsyncMock(return_value=([arthur, bella], 2))
    db = MagicMock()

    paginated = await alias_service.list_aliases(db, novel_id, skip=1, limit=2)

    assert len(paginated) == 2
    assert paginated[0]["alias"] == "Athy"
    assert paginated[1]["alias"] == "Bell"


@pytest.mark.asyncio
async def test_create_alias_adds_to_content_json(
    novel_id: str,
    alias_service: EntityAliasService,
) -> None:
    entity = _make_entity(novel_id=novel_id)
    alias_service.repo.get = AsyncMock(return_value=entity)
    db = AsyncMock()

    result = await alias_service.create_alias(
        db, novel_id, str(entity.id), "Art", "nickname"
    )

    assert result["entity_id"] == str(entity.id)
    assert result["alias"] == "Art"
    assert result["alias_type"] == "nickname"
    assert entity.content_json["aliases"] == [{"alias": "Art", "type": "nickname"}]
    db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_alias_removes_from_content_json(
    novel_id: str,
    alias_service: EntityAliasService,
) -> None:
    entity = _make_entity(
        novel_id=novel_id,
        content_json={"aliases": [{"alias": "Art", "type": "nickname"}]},
    )
    alias_service.repo.get = AsyncMock(return_value=entity)
    db = AsyncMock()

    result = await alias_service.delete_alias(db, novel_id, str(entity.id), "Art")

    assert result["entity_id"] == str(entity.id)
    assert result["alias"] == "Art"
    assert result["deleted"] is True
    assert entity.content_json["aliases"] == []
    db.flush.assert_awaited_once()


@pytest.mark.parametrize("scenario", ["not_found", "cross_novel"])
@pytest.mark.asyncio
async def test_create_alias_not_found_variants(
    novel_id: str,
    alias_service: EntityAliasService,
    scenario: str,
) -> None:
    if scenario == "cross_novel":
        entity = _make_entity(novel_id=str(uuid.uuid4()))
        alias_service.repo.get = AsyncMock(return_value=entity)
    else:
        alias_service.repo.get = AsyncMock(return_value=None)

    db = MagicMock()
    with pytest.raises(HTTPException) as exc_info:
        await alias_service.create_alias(db, novel_id, str(uuid.uuid4()), "Art")
    assert exc_info.value.status_code == 404
    assert "Entity not found" in exc_info.value.detail


@pytest.mark.asyncio
async def test_create_alias_duplicate_returns_409(
    novel_id: str,
    alias_service: EntityAliasService,
) -> None:
    entity = _make_entity(
        novel_id=novel_id,
        content_json={"aliases": [{"alias": "Art", "type": "nickname"}]},
    )
    alias_service.repo.get = AsyncMock(return_value=entity)
    db = MagicMock()

    with pytest.raises(HTTPException) as exc_info:
        await alias_service.create_alias(db, novel_id, str(entity.id), "Art")
    assert exc_info.value.status_code == 409
    assert "Alias already exists: Art" in exc_info.value.detail


@pytest.mark.parametrize(
    "scenario,expected_detail",
    [
        ("not_found", "Alias not found: Art"),
        ("cross_novel", "Entity not found"),
    ],
)
@pytest.mark.asyncio
async def test_delete_alias_not_found_variants(
    novel_id: str,
    alias_service: EntityAliasService,
    scenario: str,
    expected_detail: str,
) -> None:
    if scenario == "cross_novel":
        entity = _make_entity(
            novel_id=str(uuid.uuid4()),
            content_json={"aliases": [{"alias": "Art", "type": "nickname"}]},
        )
    else:
        entity = _make_entity(novel_id=novel_id, content_json={})
    alias_service.repo.get = AsyncMock(return_value=entity)
    db = MagicMock()

    with pytest.raises(HTTPException) as exc_info:
        await alias_service.delete_alias(db, novel_id, str(entity.id), "Art")
    assert exc_info.value.status_code == 404
    assert expected_detail in exc_info.value.detail


@pytest.mark.asyncio
async def test_list_aliases_handles_string_aliases(
    novel_id: str,
    alias_service: EntityAliasService,
) -> None:
    entity = _make_entity(content_json={"aliases": ["Art"]})
    alias_service.repo.get_by_novel = AsyncMock(return_value=([entity], 1))
    db = MagicMock()

    aliases = await alias_service.list_aliases(db, novel_id)

    assert len(aliases) == 1
    assert aliases[0]["entity_id"] == str(entity.id)
    assert aliases[0]["entity_name"] == "Arthur"
    assert aliases[0]["alias"] == "Art"
    assert aliases[0]["alias_type"] == "name"


@pytest.mark.asyncio
async def test_append_candidate_alias_upgrades_existing_plain_alias(
    novel_id: str,
    alias_service: EntityAliasService,
) -> None:
    entity = _make_entity(
        novel_id=novel_id,
        content_json={"aliases": [{"alias": "Art", "type": "nickname"}]},
    )
    alias_service.repo.get = AsyncMock(return_value=entity)
    db = AsyncMock()

    appended = await alias_service.append_candidate_alias(
        db,
        novel_id,
        str(entity.id),
        alias=" Art ",
        alias_type="alias",
        workflow_id="wf-1",
        scene_id="scene-1",
        scene_index=7,
        confidence=0.82,
        quote="有人称他为 Art。",
    )

    assert appended is True
    assert entity.content_json["aliases"] == [
        {
            "alias": "Art",
            "type": "nickname",
            "status": "candidate",
            "source": "deep_import",
            "workflow_id": "wf-1",
            "scene_id": "scene-1",
            "scene_index": 7,
            "confidence": 0.82,
            "quote": "有人称他为 Art。",
            "needs_review": True,
        }
    ]
    db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_append_candidate_alias_keeps_enriched_duplicate_unchanged(
    novel_id: str,
    alias_service: EntityAliasService,
) -> None:
    existing = {
        "alias": "Art",
        "type": "alias",
        "status": "candidate",
        "source": "deep_import",
        "workflow_id": "wf-1",
        "needs_review": True,
    }
    entity = _make_entity(novel_id=novel_id, content_json={"aliases": [existing]})
    alias_service.repo.get = AsyncMock(return_value=entity)
    db = AsyncMock()

    appended = await alias_service.append_candidate_alias(
        db,
        novel_id,
        str(entity.id),
        alias="Art",
        workflow_id="wf-2",
    )

    assert appended is False
    assert entity.content_json["aliases"] == [existing]
    db.flush.assert_not_awaited()
