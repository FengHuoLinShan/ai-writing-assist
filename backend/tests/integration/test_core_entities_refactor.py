from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from modules.project.models import Project


pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def test_core_entities_migration_copies_legacy_data_before_drop() -> None:
    migration_path = (
        Path(__file__).parents[2]
        / "alembic"
        / "versions"
        / "d967c0547254_refactor_core_entities_shared_table.py"
    )
    source = migration_path.read_text()

    first_copy = source.index("INSERT INTO core_entities")
    first_drop = source.index('op.drop_table("character_knowledge")')

    assert first_copy < first_drop
    assert "characters_new" in source
    assert "character_knowledge_new" in source
    assert "geo_locations_new" in source
    assert "geo_edges_new" in source
    assert "COALESCE(c.world_entity_id, c.id)" in source
    assert "parent.world_entity_id" in source
    # Verify target_id mapping resolves legacy extension table IDs
    assert "target_char.world_entity_id" in source
    assert "target_geo.world_entity_id" in source


async def _create_project(db_session: AsyncSession, title: str) -> str:
    project_id = uuid.uuid4()
    db_session.add(
        Project(
            id=project_id,
            title=title,
            genre="奇幻",
            tone="克制",
            language="zh",
        )
    )
    await db_session.flush()
    return str(project_id)


async def test_alias_api_rejects_cross_novel_writes(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    other_project_id = await _create_project(db_session, "另一本小说")

    created = await async_client.post(
        f"/api/world/entities?novel_id={test_project_id}",
        json={
            "entity_type": "item",
            "name": "青铜钥匙",
            "status": "canonical",
        },
    )
    assert created.status_code == 201
    entity_id = created.json()["id"]

    forbidden = await async_client.post(
        f"/api/world/entities/{entity_id}/aliases"
        f"?novel_id={other_project_id}&alias=别人的钥匙",
    )
    assert forbidden.status_code == 404

    fetched = await async_client.get(
        f"/api/world/entities/{entity_id}?novel_id={test_project_id}",
    )
    assert fetched.status_code == 200
    assert fetched.json()["aliases"] == []


async def test_get_characters_context_accepts_character_ids_keyword(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    from modules.character.facade import create_character_extension, get_characters_context
    from modules.world.facade import create_entity

    entity = await create_entity(
        db_session,
        test_project_id,
        name="林动",
        entity_type="character",
        status="canonical",
    )
    await create_character_extension(
        db_session,
        entity_id=entity.id,
        novel_id=test_project_id,
        role="protagonist",
    )

    bundle = await get_characters_context(
        db_session,
        test_project_id,
        character_ids=[entity.id],
    )

    assert bundle.total == 1
    assert bundle.characters[0].entity_id == entity.id
    assert bundle.characters[0].character_id == entity.id
    assert bundle.characters[0].role == "protagonist"


async def test_memory_geo_mutation_updates_character_location_by_core_entity_name(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    from modules.character.facade import (
        create_character_extension,
        get_character_location_id,
    )
    from modules.memory.facade import (
        confirm_memory_proposal,
        create_memory_update_proposals,
    )
    from modules.world.facade import create_entity

    character = await create_entity(
        db_session,
        test_project_id,
        name="林动",
        entity_type="character",
        status="canonical",
    )
    await create_character_extension(
        db_session,
        entity_id=character.id,
        novel_id=test_project_id,
    )
    location = await create_entity(
        db_session,
        test_project_id,
        name="炎城",
        entity_type="location",
        status="canonical",
    )

    proposals = await create_memory_update_proposals(
        db_session,
        test_project_id,
        source_type="chapter_text",
        source_id=str(uuid.uuid4()),
        extraction_result={
            "proposals": [
                {
                    "proposal_type": "create_memory",
                    "chapter_index": 3,
                    "payload": {
                        "memory_type": "chapter_state",
                        "summary": "林动前往炎城",
                        "chapter_index": 3,
                        "geo_mutations": {
                            "character_shifts": [
                                {
                                    "character_name": "林动",
                                    "destination_location_name": "炎城",
                                    "movement_type": "御剑飞行",
                                }
                            ],
                            "faction_shifts": [],
                        },
                    },
                }
            ]
        },
    )

    await confirm_memory_proposal(db_session, proposals[0].id, test_project_id)

    assert await get_character_location_id(
        db_session,
        test_project_id,
        character.id,
    ) == location.id


async def test_find_entity_by_name_alias_exact_match(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    """别名精确匹配应通过 Python 遍历找到正确实体。"""
    from modules.world.facade import add_alias, create_entity, find_entity_id_by_name

    entity = await create_entity(
        db_session,
        test_project_id,
        name="Fire City",
        entity_type="location",
        status="canonical",
    )
    await add_alias(db_session, entity.id, "炎城", alias_type="translation", novel_id=test_project_id)

    # Exact name match
    result = await find_entity_id_by_name(db_session, test_project_id, "Fire City")
    assert result == entity.id

    # Alias match
    result = await find_entity_id_by_name(db_session, test_project_id, "炎城")
    assert result == entity.id


async def test_find_entity_by_name_alias_respects_entity_type(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    """同名别名在不同 entity_type 下应区分。"""
    from modules.world.facade import add_alias, create_entity, find_entity_id_by_name

    loc = await create_entity(
        db_session,
        test_project_id,
        name="Location Alpha",
        entity_type="location",
        status="canonical",
    )
    await add_alias(db_session, loc.id, "阿尔法", novel_id=test_project_id)

    char = await create_entity(
        db_session,
        test_project_id,
        name="Character Beta",
        entity_type="character",
        status="canonical",
    )
    await add_alias(db_session, char.id, "贝塔", novel_id=test_project_id)

    # Type-filtered alias search
    assert await find_entity_id_by_name(db_session, test_project_id, "阿尔法", entity_type="location") == loc.id
    assert await find_entity_id_by_name(db_session, test_project_id, "阿尔法", entity_type="character") is None
    assert await find_entity_id_by_name(db_session, test_project_id, "贝塔", entity_type="character") == char.id


async def test_find_entity_by_name_empty_aliases(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    """无别名的实体按别名查找应返回 None。"""
    from modules.world.facade import create_entity, find_entity_id_by_name

    await create_entity(
        db_session,
        test_project_id,
        name="唯一名称",
        entity_type="item",
        status="canonical",
    )

    assert await find_entity_id_by_name(db_session, test_project_id, "不存在的别名") is None


async def test_find_entity_by_name_special_characters(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    """含特殊字符的别名不应导致查询异常。"""
    from modules.world.facade import add_alias, create_entity, find_entity_id_by_name

    entity = await create_entity(
        db_session,
        test_project_id,
        name='Item "Special"',
        entity_type="item",
        status="canonical",
    )
    # Alias with quotes and special chars — previously this would have broken
    # JSONPath string interpolation.
    await add_alias(db_session, entity.id, '带有"引号"的别名', novel_id=test_project_id)

    result = await find_entity_id_by_name(db_session, test_project_id, '带有"引号"的别名')
    assert result == entity.id


async def test_dedup_service_alias_search(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    """去重服务的别名搜索应通过 Python 遍历正确匹配。"""
    from modules.world.facade import add_alias, create_entity
    from modules.world.services.dedup_service import EntityDedupService
    from shared.utils import parse_uuid

    entity = await create_entity(
        db_session,
        test_project_id,
        name="青铜古剑",
        entity_type="item",
        status="canonical",
    )
    await add_alias(db_session, entity.id, "古剑", novel_id=test_project_id)

    service = EntityDedupService()
    nid = parse_uuid(test_project_id, "novel_id")

    # Exact alias match
    matches = await service._find_alias_matches_in_jsonb(db_session, nid, "古剑")
    assert len(matches) == 1
    assert matches[0]["entity_id"] == entity.id
    assert matches[0]["entity_name"] == "青铜古剑"

    # Non-match
    matches = await service._find_alias_matches_in_jsonb(db_session, nid, "不存在的别名")
    assert matches == []
