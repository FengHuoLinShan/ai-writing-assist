"""
Character Facade — 对外入口

其他模块只能从 facade 导入。
Facade 不写复杂业务逻辑，只做稳定的对外代理。
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from modules.character.schemas import (
    CharacterContextBundle,
    CharacterCreate,
    CharacterKnowledgeContext,
    CharacterResponse,
)
from modules.character.services import CharacterService

_service = CharacterService()


async def create_character(
    db: AsyncSession,
    novel_id: str,
    name: str,
    world_entity_id: str | None = None,
) -> CharacterResponse:
    """创建人物档案

    供 world 模块在确认人物类型候选后自动创建对应的人物档案。

    Args:
        db: 数据库 session
        novel_id: 项目 ID
        name: 人物名称
        world_entity_id: 关联的世界对象 ID（可选）

    Returns:
        CharacterResponse — 创建的人物
    """
    data = CharacterCreate(
        novel_id=novel_id,
        name=name,
        world_entity_id=world_entity_id,
    )
    return await _service.create_character(db, data)


async def get_character_id_by_world_entity(
    db: AsyncSession,
    novel_id: str,
    world_entity_id: str,
) -> str | None:
    """按 world_entity_id 查找已存在的人物 ID

    Returns:
        人物 ID 字符串，未找到返回 None
    """
    return await _service.get_character_id_by_world_entity(
        db, novel_id, world_entity_id,
    )


async def get_characters_context(
    db: AsyncSession,
    novel_id: str,
    character_ids: list[str],
    reveal_mode: str = "author_safe",
) -> CharacterContextBundle:
    """获取人物上下文包

    供 Context Compiler、Outline 等模块获取人物信息。

    Args:
        db: 数据库 session
        novel_id: 项目 ID (UUID hex string)
        character_ids: 人物 ID 列表
        reveal_mode: 揭示模式（author_safe / author_only），
                     author_safe 不返回 secret 字段

    Returns:
        CharacterContextBundle — 包含人物列表和元信息的上下文包
    """
    return await _service.get_characters_context(
        db, novel_id, character_ids, reveal_mode,
    )


async def get_character_knowledge_context(
    db: AsyncSession,
    novel_id: str,
    character_id: str,
    target_ids: list[str] | None = None,
) -> list[CharacterKnowledgeContext]:
    """获取人物知识上下文

    返回角色对指定目标的知识状况。
    供 Context Compiler、Review 模块判断是否违反知识边界。

    Args:
        db: 数据库 session
        novel_id: 项目 ID
        character_id: 人物 ID
        target_ids: 目标 ID 列表（可选，不传则返回所有目标的知识）

    Returns:
        list[CharacterKnowledgeContext] — 角色对目标的知识记录列表
    """
    return await _service.get_character_knowledge_context(
        db, novel_id, character_id, target_ids,
    )


async def filter_context_by_character_knowledge(
    db: AsyncSession,
    novel_id: str,
    character_id: str,
    context_items: list[dict],
) -> list[dict]:
    """按人物知识过滤上下文项

    根据角色对上下文项中目标的了解程度，决定哪些信息可暴露给角色视角。
    - knowledge_level=unknown → 移除该项
    - knowledge_level=false_belief → 替换为角色的误解内容
    - 其他（rumor/partial/full）→ 保留

    Args:
        db: 数据库 session
        novel_id: 项目 ID
        character_id: 人物 ID
        context_items: 待过滤的上下文项列表。
                       每项应包含 target_type 和 target_id 字段。

    Returns:
        list[dict] — 过滤后的上下文项列表
    """
    filtered, _, _ = await _service.filter_context_by_character_knowledge(
        db, novel_id, character_id, context_items,
    )
    return filtered
