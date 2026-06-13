"""EntityAliasService 测试"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.models import CoreEntity
from modules.world.schemas import CoreEntityCreate
from modules.world.services import WorldEntityService
from modules.world.services.entity_alias_service import EntityAliasService
from modules.world.services.helpers import parse_uuid


@pytest.fixture
def novel_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def alias_service() -> EntityAliasService:
    return EntityAliasService()


@pytest.fixture
def entity_service() -> WorldEntityService:
    return WorldEntityService()


@pytest.mark.asyncio
async def test_list_aliases_returns_alias_for_entity(
    db_session: AsyncSession,
    novel_id: str,
    alias_service: EntityAliasService,
    entity_service: WorldEntityService,
) -> None:
    entity = await entity_service.create(
        db_session,
        novel_id,
        CoreEntityCreate(
            entity_type="character",
            name="Arthur",
            content_json={"aliases": [{"alias": "Art", "type": "nickname"}]},
        ),
    )

    aliases = await alias_service.list_aliases(db_session, novel_id)

    assert len(aliases) == 1
    assert aliases[0]["entity_id"] == entity.id
    assert aliases[0]["entity_name"] == "Arthur"
    assert aliases[0]["alias"] == "Art"
    assert aliases[0]["alias_type"] == "nickname"


@pytest.mark.asyncio
async def test_list_aliases_pagination(
    db_session: AsyncSession,
    novel_id: str,
    alias_service: EntityAliasService,
    entity_service: WorldEntityService,
) -> None:
    await entity_service.create(
        db_session,
        novel_id,
        CoreEntityCreate(
            entity_type="character",
            name="Arthur",
            content_json={"aliases": ["Art", "Athy"]},
        ),
    )
    await entity_service.create(
        db_session,
        novel_id,
        CoreEntityCreate(
            entity_type="character",
            name="Bella",
            content_json={"aliases": ["Bell", "Bells"]},
        ),
    )

    all_aliases = await alias_service.list_aliases(db_session, novel_id)
    paginated = await alias_service.list_aliases(db_session, novel_id, skip=1, limit=2)

    assert len(paginated) == 2
    for alias_item in paginated:
        assert alias_item in all_aliases


@pytest.mark.asyncio
async def test_create_alias_adds_to_content_json(
    db_session: AsyncSession,
    novel_id: str,
    alias_service: EntityAliasService,
    entity_service: WorldEntityService,
) -> None:
    entity = await entity_service.create(
        db_session,
        novel_id,
        CoreEntityCreate(
            entity_type="character",
            name="Arthur",
        ),
    )

    result = await alias_service.create_alias(
        db_session, novel_id, entity.id, "Art", "nickname"
    )

    assert result["entity_id"] == entity.id
    assert result["alias"] == "Art"
    assert result["alias_type"] == "nickname"

    reloaded = await db_session.get(CoreEntity, parse_uuid(entity.id))
    assert reloaded is not None
    aliases = reloaded.content_json.get("aliases", [])
    assert any(
        alias_item["alias"] == "Art" and alias_item["type"] == "nickname"
        for alias_item in aliases
    )


@pytest.mark.asyncio
async def test_delete_alias_removes_from_content_json(
    db_session: AsyncSession,
    novel_id: str,
    alias_service: EntityAliasService,
    entity_service: WorldEntityService,
) -> None:
    entity = await entity_service.create(
        db_session,
        novel_id,
        CoreEntityCreate(
            entity_type="character",
            name="Arthur",
            content_json={"aliases": [{"alias": "Art", "type": "nickname"}]},
        ),
    )

    result = await alias_service.delete_alias(db_session, novel_id, entity.id, "Art")

    assert result["entity_id"] == entity.id
    assert result["alias"] == "Art"
    assert result["deleted"] is True

    reloaded = await db_session.get(CoreEntity, parse_uuid(entity.id))
    assert reloaded is not None
    aliases = reloaded.content_json.get("aliases", [])
    assert not any(alias_item.get("alias") == "Art" for alias_item in aliases)


@pytest.mark.asyncio
async def test_create_alias_entity_not_found_returns_404(
    db_session: AsyncSession,
    novel_id: str,
    alias_service: EntityAliasService,
) -> None:
    with pytest.raises(HTTPException) as exc_info:
        await alias_service.create_alias(
            db_session, novel_id, str(uuid.uuid4()), "Art"
        )
    assert exc_info.value.status_code == 404
    assert "Entity not found" in exc_info.value.detail


@pytest.mark.asyncio
async def test_create_alias_cross_novel_returns_404(
    db_session: AsyncSession,
    novel_id: str,
    alias_service: EntityAliasService,
    entity_service: WorldEntityService,
) -> None:
    entity = await entity_service.create(
        db_session,
        novel_id,
        CoreEntityCreate(
            entity_type="character",
            name="Arthur",
        ),
    )
    other_novel_id = str(uuid.uuid4())

    with pytest.raises(HTTPException) as exc_info:
        await alias_service.create_alias(
            db_session, other_novel_id, entity.id, "Art"
        )
    assert exc_info.value.status_code == 404
    assert "Entity not found" in exc_info.value.detail


@pytest.mark.asyncio
async def test_create_alias_duplicate_returns_409(
    db_session: AsyncSession,
    novel_id: str,
    alias_service: EntityAliasService,
    entity_service: WorldEntityService,
) -> None:
    entity = await entity_service.create(
        db_session,
        novel_id,
        CoreEntityCreate(
            entity_type="character",
            name="Arthur",
            content_json={"aliases": [{"alias": "Art", "type": "nickname"}]},
        ),
    )

    with pytest.raises(HTTPException) as exc_info:
        await alias_service.create_alias(db_session, novel_id, entity.id, "Art")
    assert exc_info.value.status_code == 409
    assert "Alias already exists: Art" in exc_info.value.detail


@pytest.mark.asyncio
async def test_delete_alias_not_found_returns_404(
    db_session: AsyncSession,
    novel_id: str,
    alias_service: EntityAliasService,
    entity_service: WorldEntityService,
) -> None:
    entity = await entity_service.create(
        db_session,
        novel_id,
        CoreEntityCreate(
            entity_type="character",
            name="Arthur",
        ),
    )

    with pytest.raises(HTTPException) as exc_info:
        await alias_service.delete_alias(db_session, novel_id, entity.id, "Art")
    assert exc_info.value.status_code == 404
    assert "Alias not found: Art" in exc_info.value.detail


@pytest.mark.asyncio
async def test_delete_alias_cross_novel_returns_404(
    db_session: AsyncSession,
    novel_id: str,
    alias_service: EntityAliasService,
    entity_service: WorldEntityService,
) -> None:
    entity = await entity_service.create(
        db_session,
        novel_id,
        CoreEntityCreate(
            entity_type="character",
            name="Arthur",
            content_json={"aliases": [{"alias": "Art", "type": "nickname"}]},
        ),
    )
    other_novel_id = str(uuid.uuid4())

    with pytest.raises(HTTPException) as exc_info:
        await alias_service.delete_alias(
            db_session, other_novel_id, entity.id, "Art"
        )
    assert exc_info.value.status_code == 404
    assert "Entity not found" in exc_info.value.detail


@pytest.mark.asyncio
async def test_list_aliases_handles_string_aliases(
    db_session: AsyncSession,
    novel_id: str,
    alias_service: EntityAliasService,
    entity_service: WorldEntityService,
) -> None:
    entity = await entity_service.create(
        db_session,
        novel_id,
        CoreEntityCreate(
            entity_type="character",
            name="Arthur",
            content_json={"aliases": ["Art"]},
        ),
    )

    aliases = await alias_service.list_aliases(db_session, novel_id)

    assert len(aliases) == 1
    assert aliases[0]["entity_id"] == entity.id
    assert aliases[0]["entity_name"] == "Arthur"
    assert aliases[0]["alias"] == "Art"
    assert aliases[0]["alias_type"] == "name"
