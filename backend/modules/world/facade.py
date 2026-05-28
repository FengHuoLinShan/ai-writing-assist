"""
World Facade — 对外入口

其他模块只能从 facade 导入。
Facade 不写复杂业务逻辑，只做稳定的对外代理。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.schemas import (
    DuplicateSuggestionResult,
    WorldContextBundle,
    WorldEntityContext,
    WorldEntityResponse,
)
from modules.world.services import EntityCandidateService, EntityDedupService, RelationshipService, WorldEntityService

_entity_service = WorldEntityService()
_relationship_service = RelationshipService()
_candidate_service = EntityCandidateService()
_dedup_service = EntityDedupService()


async def list_entities(
    db: AsyncSession,
    novel_id: str,
    *,
    entity_type: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """获取世界对象摘要列表

    返回轻量结果（id, name, entity_type），供其他模块注入上下文。
    """
    result = await _entity_service.list(
        db, novel_id,
        entity_type=entity_type,
        limit=limit,
    )
    return [
        {"id": item.id, "name": item.name, "entity_type": item.entity_type}
        for item in result.items
    ]


async def run_entity_extraction(
    db: AsyncSession,
    novel_id: str,
    start_chapter: int,
    end_chapter: int,
    batch_size: int = 5,
) -> dict[str, Any]:
    """从章节正文中抽取世界对象候选

    调用 EntityExtractionService，返回抽取结果统计。
    """
    from modules.world.services import EntityExtractionService

    service = EntityExtractionService()
    result = await service.extract_entities_from_chapters(
        db,
        novel_id=novel_id,
        start_chapter=start_chapter,
        end_chapter=end_chapter,
        batch_size=batch_size,
    )
    return {
        "total_chapters": result.total_chapters,
        "total_created": result.total_created,
        "total_skipped": result.total_skipped,
        "items": result.items,
    }


async def count_pending_candidates(
    db: AsyncSession,
    novel_id: str,
) -> int:
    """统计待处理的候选对象数量"""
    result = await _candidate_service.list(
        db, novel_id,
        status="pending",
        limit=1,
    )
    return result.total


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


async def find_similar_entities(
    db: AsyncSession,
    novel_id: str,
    name: str,
    aliases: list[str] | None = None,
    entity_type: str | None = None,
) -> list[DuplicateSuggestionResult]:
    """查找相似实体（供抽取模块使用）

    对指定名称查找相似的正史对象。

    Args:
        db: 数据库 session
        novel_id: 项目 ID
        name: 待匹配名称
        aliases: 可选别名列表
        entity_type: 可选类型过滤

    Returns:
        list[DuplicateSuggestionResult] — 去重建议列表
    """
    return await _dedup_service.find_similar_entities(
        db, novel_id, name, aliases=aliases, entity_type=entity_type,
    )


async def accept_candidate(
    db: AsyncSession,
    novel_id: str,
    candidate_id: str,
    user_edits: dict[str, Any] | None = None,
) -> WorldEntityResponse:
    """接受候选对象：根据 suggested_action 创建实体/别名/合并

    Args:
        db: 数据库 session
        novel_id: 项目 ID
        candidate_id: 候选对象 ID
        user_edits: 用户编辑的可选覆盖字段

    Returns:
        WorldEntityResponse — 创建/更新后的正史对象
    """
    return await _candidate_service.accept_candidate(
        db, novel_id, candidate_id, user_edits=user_edits,
    )


async def merge_candidate_into_entity(
    db: AsyncSession,
    novel_id: str,
    candidate_id: str,
    target_entity_id: str,
) -> WorldEntityResponse:
    """合并候选到正史对象

    将候选对象的数据合并到指定的正史对象。

    Args:
        db: 数据库 session
        novel_id: 项目 ID
        candidate_id: 候选对象 ID
        target_entity_id: 目标正史对象 ID

    Returns:
        WorldEntityResponse — 更新后的正史对象
    """
    entity = await _dedup_service.merge_candidate_into_entity(
        db, novel_id, candidate_id, target_entity_id,
    )
    return WorldEntityResponse.model_validate(entity)


async def find_entity_id_by_name(
    db: AsyncSession,
    novel_id: str,
    name: str,
    entity_type: str | None = None,
) -> str | None:
    from shared.utils import parse_uuid
    nid = parse_uuid(novel_id, "novel_id")
    from modules.world.repositories import WorldEntityRepository
    repo = WorldEntityRepository()
    return await repo.find_entity_by_name(db, nid, name, entity_type=entity_type)


async def upsert_relationship(
    db: AsyncSession,
    novel_id: str,
    source_id: str,
    target_id: str,
    source_type: str,
    target_type: str,
    relation_type: str,
    description: str | None = None,
) -> None:
    from shared.utils import parse_uuid
    nid = parse_uuid(novel_id, "novel_id")
    from modules.world.repositories import RelationshipRepository
    repo = RelationshipRepository()
    await repo.upsert_relationship(
        db, nid, source_id, target_id,
        source_type, target_type, relation_type, description,
    )


async def get_location_factions(
    db: AsyncSession,
    novel_id: str,
    location_id: str,
) -> list[dict[str, Any]]:
    """获取控制/驻扎某地点的势力列表

    Args:
        db: 数据库 session
        novel_id: 项目 ID
        location_id: 地点 ID

    Returns:
        list[dict] — 势力列表，每项含 id, name, relation_type, description
    """
    from shared.utils import parse_uuid
    nid = parse_uuid(novel_id, "novel_id")
    from modules.world.repositories import RelationshipRepository, WorldEntityRepository
    rel_repo = RelationshipRepository()
    entity_repo = WorldEntityRepository()
    return await rel_repo.get_factions_for_location(db, nid, location_id, entity_repo)
