"""
Character Facade — 对外入口

Character 以 entity_id 为 PK (= core_entities.id)，仅管理扩展字段。
公共字段（name, aliases, status）通过 world.facade 操作 core_entities。
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from modules.character.schemas import (
    CharacterContextBundle,
    CharacterCreate,
    CharacterKnowledgeContext,
    CharacterResponse,
)
from modules.character.services import CharacterService

logger = logging.getLogger(__name__)
_service = CharacterService()


async def create_character_extension(
    db: AsyncSession,
    entity_id: str,
    novel_id: str,
    **kwargs,
) -> CharacterResponse:
    """创建人物扩展记录 — 供 world 模块在创建 character 类型后调用"""
    data = CharacterCreate(
        entity_id=entity_id,
        novel_id=novel_id,
        **{k: v for k, v in kwargs.items() if v is not None},
    )
    return await _service.create_character(db, data)


async def create_character(
    db: AsyncSession,
    novel_id: str,
    entity_id: str,
) -> CharacterResponse:
    """最简创建人物扩展记录"""
    data = CharacterCreate(entity_id=entity_id, novel_id=novel_id)
    return await _service.create_character(db, data)


async def get_character(
    db: AsyncSession,
    entity_id: str,
    novel_id: str | None = None,
) -> CharacterResponse:
    return await _service.get_character(db, entity_id, novel_id)


async def update_character(
    db: AsyncSession,
    entity_id: str,
    novel_id: str | None = None,
    **fields,
) -> CharacterResponse:
    from modules.character.schemas import CharacterUpdate
    data = CharacterUpdate(**{k: v for k, v in fields.items() if v is not None})
    return await _service.update_character(db, entity_id, data, novel_id)


async def delete_character(
    db: AsyncSession,
    entity_id: str,
    novel_id: str | None = None,
) -> None:
    await _service.delete_character(db, entity_id, novel_id)


async def list_characters(
    db: AsyncSession,
    novel_id: str,
    skip: int = 0,
    limit: int = 100,
) -> tuple[list[CharacterResponse], int]:
    return await _service.list_characters(db, novel_id, skip=skip, limit=limit)


async def get_characters_context(
    db: AsyncSession,
    novel_id: str,
    character_ids: list[str] | None = None,
    reveal_mode: str = "author_safe",
    *,
    entity_ids: list[str] | None = None,
) -> CharacterContextBundle:
    if entity_ids is not None and character_ids is not None:
        logger.warning(
            "get_characters_context: both entity_ids and character_ids provided; "
            "entity_ids takes priority (character_ids ignored)",
        )
    ids = entity_ids if entity_ids is not None else (character_ids or [])
    return await _service.get_characters_context(db, novel_id, ids, reveal_mode)


async def get_character_knowledge_context(
    db: AsyncSession,
    novel_id: str,
    character_id: str,
    target_ids: list[str] | None = None,
) -> list[CharacterKnowledgeContext]:
    return await _service.get_character_knowledge_context(db, novel_id, character_id, target_ids)


async def filter_context_by_character_knowledge(
    db: AsyncSession,
    novel_id: str,
    character_id: str,
    context_items: list[dict],
) -> list[dict]:
    filtered, _, _ = await _service.filter_context_by_character_knowledge(
        db, novel_id, character_id, context_items,
    )
    return filtered


async def find_character_id_by_name(
    db: AsyncSession,
    novel_id: str,
    name: str,
) -> str | None:
    """按正史人物名/别名查找人物 entity_id。"""
    from modules.world.facade import find_entity_id_by_name

    return await find_entity_id_by_name(db, novel_id, name, entity_type="character")


async def get_unknown_target_ids(
    db: AsyncSession,
    novel_id: str,
    character_id: str,
) -> dict[str, list[str]]:
    """获取角色标记为 unknown 的目标 ID 集合

    供 RAG 检索进行硬过滤，防止角色视角越权。
    返回 {"entity_ids": [...], "character_ids": [...]}。
    """
    return await _service.get_unknown_target_ids(db, novel_id, character_id)


async def update_character_location(
    db: AsyncSession,
    novel_id: str,
    entity_id: str,
    location_id: str,
    text_state: str,
    chapter_index: int,
) -> None:
    from shared.utils import parse_uuid
    from modules.character.repositories import CharacterRepository
    eid = parse_uuid(entity_id, "entity_id")
    await CharacterRepository().update_character_meta_location(db, eid, location_id, text_state, chapter_index)


async def get_characters_at_location(
    db: AsyncSession,
    novel_id: str,
    location_id: str,
) -> list[dict]:
    from shared.utils import parse_uuid
    from modules.character.repositories import CharacterRepository
    nid = parse_uuid(novel_id, "novel_id")
    return await CharacterRepository().find_characters_by_location(db, nid, location_id)


async def get_character_location_id(
    db: AsyncSession,
    novel_id: str,
    entity_id: str,
) -> str | None:
    from shared.utils import parse_uuid
    from modules.character.repositories import CharacterRepository
    eid = parse_uuid(entity_id, "entity_id")
    return await CharacterRepository().get_character_location_id(db, eid)
