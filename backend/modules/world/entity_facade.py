"""World Entity Facade — 实体 / 关系 / 去重子域的对外入口。"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.schemas import (
    EntityRelationResponse,
    WorldContextBundle,
    WorldEntityContext,
)
from modules.world.services import (
    EntityRelationService,
    WorldEntityService,
)
from modules.world.services.dedup_service import EntityDedupService

_entity_service = WorldEntityService()
_relation_service = EntityRelationService()
_dedup_service = EntityDedupService()


async def list_entities(
    db: AsyncSession,
    novel_id: str,
    *,
    entity_type: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """获取世界对象摘要列表"""
    return await _entity_service.list_entity_summaries(
        db, novel_id,
        entity_type=entity_type,
        limit=limit,
    )


async def list_entity_terms(
    db: AsyncSession,
    novel_id: str,
    *,
    limit: int = 500,
) -> list[dict[str, Any]]:
    """获取世界对象检索词典项（名称 + 已确认别名）。"""
    return await _entity_service.list_entity_terms(db, novel_id, limit=limit)


async def get_world_context(
    db: AsyncSession,
    novel_id: str,
    entity_ids: list[str] | None = None,
    reveal_mode: str = "author_safe",
    limit: int = 20,
) -> WorldContextBundle:
    """获取世界上下文"""
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
    """扩展关联实体"""
    return await _relation_service.expand_related(
        db, novel_id,
        seed_entity_ids=seed_entity_ids,
        depth=depth,
        limit=limit,
    )


async def find_entity_id_by_name(
    db: AsyncSession,
    novel_id: str,
    name: str,
    entity_type: str | None = None,
) -> str | None:
    """按名称查正史实体 ID。"""
    return await _entity_service.find_by_name(
        db, novel_id, name, entity_type=entity_type,
    )


# ============================================================
# EntityRelation
# ============================================================

async def upsert_relationship(
    db: AsyncSession,
    novel_id: str,
    source_id: str,
    target_id: str,
    source_type: str = "",
    target_type: str = "",
    relation_type: str = "",
    description: str | None = None,
) -> None:
    """兼容旧接口，委托新的 upsert 方法"""
    await _relation_service.upsert(
        db, novel_id,
        source_id=source_id,
        target_id=target_id,
        relation_type=relation_type,
        description=description,
    )


async def get_entity_relations(
    db: AsyncSession,
    novel_id: str,
    skip: int = 0,
    limit: int = 100,
) -> tuple[list[EntityRelationResponse], int]:
    return await _relation_service.list(db, novel_id, skip=skip, limit=limit)


async def create_relation(
    db: AsyncSession,
    novel_id: str,
    data: dict,
) -> EntityRelationResponse:
    from modules.world.schemas import EntityRelationCreate
    rel_data = EntityRelationCreate(**data)
    return await _relation_service.create(db, novel_id, rel_data)


async def upsert_relation(
    db: AsyncSession,
    novel_id: str,
    source_id: str,
    target_id: str,
    relation_type: str,
    description: str | None = None,
) -> EntityRelationResponse:
    return await _relation_service.upsert(
        db, novel_id, source_id, target_id,
        relation_type, description=description,
    )


# ============================================================
# Dedup
# ============================================================

async def find_similar_entities(
    db: AsyncSession,
    novel_id: str,
    name: str,
    aliases: list[str] | None = None,
    entity_type: str | None = None,
    query_embedding: list[float] | None = None,
) -> list:
    return await _dedup_service.find_similar_entities(
        db, novel_id, name, aliases=aliases, entity_type=entity_type,
        query_embedding=query_embedding,
    )


async def merge_candidate_into_entity(
    db: AsyncSession,
    novel_id: str,
    candidate_id: str,
    target_entity_id: str,
) -> Any:  # MergeResult
    return await _dedup_service.merge_candidate_into_entity(
        db, novel_id, candidate_id, target_entity_id,
    )
