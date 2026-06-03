"""World Character Facade — 人物子域的对外入口。"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.schemas import (
    CharacterContextBundle,
    CharacterKnowledgeContext,
    CharacterResponse,
)
from modules.world.services import CharacterService

_character_service = CharacterService()


# ============================================================
# 兼容性 facade（其他模块仍在调用）
# ============================================================

async def get_character_id_by_world_entity(
    db: AsyncSession,
    novel_id: str,
    world_entity_id: str,
) -> str | None:
    """按核心实体 ID 查找人物（新模型中 entity_id == character PK）。"""
    return await _character_service.get_id_by_world_entity(
        db, novel_id, world_entity_id,
    )


# ============================================================
# Character CRUD
# ============================================================

async def create_character(
    db: AsyncSession,
    novel_id: str,
    name: str,
    world_entity_id: str | None = None,
) -> CharacterResponse:
    from modules.world.schemas import CharacterCreate
    entity_id = world_entity_id or ""
    data = CharacterCreate(name=name, entity_id=entity_id)
    return await _character_service.create(db, novel_id, data)


async def get_characters_context(
    db: AsyncSession,
    novel_id: str,
    character_ids: list[str],
    reveal_mode: str = "author_safe",
) -> CharacterContextBundle:
    return await _character_service.get_characters_context(
        db, novel_id, character_ids, reveal_mode,
    )


async def get_character_knowledge_context(
    db: AsyncSession,
    novel_id: str,
    character_id: str,
    target_ids: list[str] | None = None,
) -> list[CharacterKnowledgeContext]:
    return await _character_service.get_character_knowledge_context(
        db, novel_id, character_id, target_ids,
    )


async def filter_context_by_character_knowledge(
    db: AsyncSession,
    novel_id: str,
    character_id: str,
    context_items: list[dict],
) -> list[dict]:
    filtered, _, _ = await _character_service.filter_context_by_character_knowledge(
        db, novel_id, character_id, context_items,
    )
    return filtered


async def find_character_id_by_name(
    db: AsyncSession,
    novel_id: str,
    name: str,
) -> str | None:
    """按 character name 查正史 character 的 entity_id。"""
    return await _character_service.find_by_name(db, novel_id, name)


async def update_character_location(
    db: AsyncSession,
    novel_id: str,
    character_id: str,
    location_id: str,
    text_state: str,
    chapter_index: int,
) -> None:
    """更新 character 的位置元数据。"""
    await _character_service.update_location(
        db, novel_id, character_id, location_id, text_state, chapter_index,
    )


async def get_characters_at_location(
    db: AsyncSession,
    novel_id: str,
    location_id: str,
) -> list[dict]:
    """查某 location 下的所有正史 character。"""
    return await _character_service.get_characters_at_location(
        db, novel_id, location_id,
    )


async def get_character_location_id(
    db: AsyncSession,
    novel_id: str,
    character_id: str,
) -> str | None:
    """查 character 的 location_id, 返 str 或 None。"""
    return await _character_service.get_location_id(db, novel_id, character_id)


async def list_characters(
    db: AsyncSession,
    novel_id: str,
    skip: int = 0,
    limit: int = 100,
) -> tuple[list[CharacterResponse], int]:
    result = await _character_service.list(
        db, novel_id, skip=skip, limit=limit,
    )
    return result[0], result[1]
