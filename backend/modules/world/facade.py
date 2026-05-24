"""
World Facade — 对外入口

其他模块只能从 facade 导入。
Facade 不写复杂业务逻辑，只做稳定的对外代理。
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.schemas import (
    DuplicateSuggestionResult,
    WorldContextBundle,
    WorldEntityContext,
)
from modules.world.services import EntityDedupService, RelationshipService, WorldEntityService

_entity_service = WorldEntityService()
_relationship_service = RelationshipService()
_dedup_service = EntityDedupService()


async def get_world_context(
    db: AsyncSession,
    novel_id: str,
    entity_ids: list[str] | None = None,
    reveal_mode: str = "author_safe",
    limit: int = 20,
) -> WorldContextBundle:
    """获取世界上下文

    供其他模块（character、outline、context 等）获取世界对象信息。
    可指定 entity_ids 获取特定对象，或留空获取所有正史对象。

    Args:
        db: 数据库 session
        novel_id: 项目 ID
        entity_ids: 可选，指定对象 ID 列表
        reveal_mode: 揭示模式（author_only / author_safe / reader_known）
        limit: 最大返回数量

    Returns:
        WorldContextBundle — 世界上下文组合包
    """
    return await _entity_service.get_entity_context(
        db, novel_id,
        entity_ids=entity_ids,
        reveal_mode=reveal_mode,
        limit=limit,
    )


async def expand_related_entities(
    db: AsyncSession,
    novel_id: str,
    seed_entity_ids: list[str],
    depth: int = 1,
    limit: int = 20,
) -> list[WorldEntityContext]:
    """扩展关联实体

    从一组种子实体出发，通过关系网络扩展一跳或二跳的相关实体。

    Args:
        db: 数据库 session
        novel_id: 项目 ID
        seed_entity_ids: 种子对象 ID 列表
        depth: 扩展深度（1=一跳，2=二跳）
        limit: 最大返回数量

    Returns:
        list[WorldEntityContext] — 相关对象的上下文列表
    """
    return await _relationship_service.expand_related(
        db, novel_id,
        seed_entity_ids=seed_entity_ids,
        depth=depth,
        limit=limit,
    )


async def find_duplicate_entity_candidates(
    db: AsyncSession,
    novel_id: str,
    candidate_id: str,
) -> list[DuplicateSuggestionResult]:
    """查找候选对象的重复匹配

    对指定候选对象执行去重检查，返回所有可能的匹配建议。

    Args:
        db: 数据库 session
        novel_id: 项目 ID
        candidate_id: 候选对象 ID

    Returns:
        list[DuplicateSuggestionResult] — 去重建议列表
    """
    return await _dedup_service.find_duplicates(db, novel_id, candidate_id)
