"""World Entity Facade — 实体 / 关系 / 去重子域的对外入口。"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.schemas import (
    EntityFusionApplyItem,
    EntityRelationResponse,
    WorldContextBundle,
    WorldEntityContext,
)
from modules.world.services import (
    EntityAliasService,
    EntityContextService,
    EntityEmbeddingService,
    EntityRelationService,
    EntityStatsService,
    WorldEntityService,
)
from modules.world.services.core.dedup_service import EntityDedupService

_entity_service = WorldEntityService()
_context_service = EntityContextService()
_alias_service = EntityAliasService()
_embedding_service = EntityEmbeddingService()
_stats_service = EntityStatsService()
_relation_service = EntityRelationService()
_dedup_service = EntityDedupService()


async def list_entities(
    db: AsyncSession,
    novel_id: str,
    *,
    entity_type: str | None = None,
    statuses: list[str] | tuple[str, ...] | None = None,
    display_state: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """获取世界对象摘要列表"""
    return await _context_service.list_entity_summaries(
        db,
        novel_id,
        entity_type=entity_type,
        statuses=statuses,
        display_state=display_state,
        limit=limit,
    )


async def list_entity_terms(
    db: AsyncSession,
    novel_id: str,
    *,
    limit: int = 500,
) -> list[dict[str, Any]]:
    """获取世界对象检索词典项（名称 + 已确认别名）。"""
    return await _context_service.list_entity_terms(db, novel_id, limit=limit)


async def get_world_context(
    db: AsyncSession,
    novel_id: str,
    entity_ids: list[str] | None = None,
    reveal_mode: str = "author_safe",
    limit: int = 20,
    current_chapter: int | None = None,
    include_review: bool = False,
) -> WorldContextBundle:
    """获取世界上下文；默认只包含已采用对象。"""
    return await _context_service.get_entity_context(
        db,
        novel_id,
        entity_ids=entity_ids,
        reveal_mode=reveal_mode,
        limit=limit,
        current_chapter=current_chapter,
        include_review=include_review,
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
        db,
        novel_id,
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
    return await _context_service.find_by_name(
        db,
        novel_id,
        name,
        entity_type=entity_type,
    )


async def find_working_entity_id_by_name(
    db: AsyncSession,
    novel_id: str,
    name: str,
    entity_type: str | None = None,
) -> str | None:
    """按名称或别名解析 working context 内的实体 ID。"""
    return await _context_service.find_working_entity_by_name(
        db,
        novel_id,
        name,
        entity_type=entity_type,
    )


async def find_working_entity_ids_by_names(
    db: AsyncSession,
    novel_id: str,
    names: list[str] | tuple[str, ...] | set[str],
    entity_type: str | None = None,
) -> dict[str, str]:
    """批量按名称或别名解析 working context 内的实体 ID。"""
    return await _context_service.find_working_entities_by_names(
        db,
        novel_id,
        names,
        entity_type=entity_type,
    )


async def append_candidate_alias(
    db: AsyncSession,
    novel_id: str,
    entity_id: str,
    *,
    alias: str,
    alias_type: str = "alias",
    workflow_id: str | None = None,
    scene_id: str | None = None,
    scene_index: int | None = None,
    confidence: float = 0.5,
    quote: str | None = None,
) -> bool:
    """追加待复核别名，已存在时返回 False。"""
    return await _alias_service.append_candidate_alias(
        db,
        novel_id,
        entity_id,
        alias=alias,
        alias_type=alias_type,
        workflow_id=workflow_id,
        scene_id=scene_id,
        scene_index=scene_index,
        confidence=confidence,
        quote=quote,
    )


async def rollback_deep_import_aliases_by_workflow(
    db: AsyncSession,
    novel_id: str,
    workflow_id: str,
) -> int:
    return await _alias_service.rollback_deep_import_candidates_by_workflow(
        db,
        novel_id,
        workflow_id,
    )


async def rollback_deep_import_relations_by_workflow(
    db: AsyncSession,
    novel_id: str,
    workflow_id: str,
) -> int:
    return await _relation_service.rollback_deep_import_candidates_by_workflow(
        db,
        novel_id,
        workflow_id,
    )


async def repair_deep_import_alias_metadata(
    db: AsyncSession,
    novel_id: str,
) -> int:
    """Normalize old deep-import alias metadata in world-owned entities."""
    from sqlalchemy import select

    from modules.world.models import CoreEntity
    from shared.utils import parse_uuid

    nid = parse_uuid(novel_id, "novel_id")
    stmt = select(CoreEntity).where(CoreEntity.novel_id == nid)
    result = await db.execute(stmt)
    repaired = 0
    for entity in result.scalars().all():
        content = dict(entity.content_json or {})
        meta = content.get("_meta") or {}
        if meta.get("source") != "deep_import":
            continue
        aliases = content.get("aliases") or []
        if not isinstance(aliases, list):
            continue
        next_aliases: list[dict[str, Any]] = []
        changed = False
        for alias_item in aliases:
            normalized = _normalize_deep_import_alias(alias_item, meta)
            if normalized is None:
                changed = True
                continue
            if normalized != alias_item:
                changed = True
                repaired += 1
            next_aliases.append(normalized)
        if changed:
            content["aliases"] = next_aliases
            entity.content_json = content
    await db.flush()
    return repaired


async def get_deep_import_alias_metadata_summary(
    db: AsyncSession,
    novel_id: str,
) -> dict[str, int]:
    """Count alias metadata gaps for old deep-import entities."""
    from sqlalchemy import select

    from modules.world.models import CoreEntity
    from shared.utils import parse_uuid

    nid = parse_uuid(novel_id, "novel_id")
    result = await db.execute(select(CoreEntity).where(CoreEntity.novel_id == nid))
    alias_missing = 0
    alias_total = 0
    for entity in result.scalars().all():
        content = entity.content_json or {}
        for alias_item in content.get("aliases") or []:
            alias_total += 1
            if not (
                isinstance(alias_item, dict)
                and alias_item.get("source")
                and alias_item.get("status")
            ):
                alias_missing += 1
    return {
        "alias_total": alias_total,
        "alias_missing_metadata": alias_missing,
    }


def _normalize_deep_import_alias(
    alias_item: Any,
    meta: dict[str, Any],
) -> dict[str, Any] | None:
    if isinstance(alias_item, dict):
        raw_alias = alias_item.get("alias") or alias_item.get("name") or ""
        alias_type = alias_item.get("type") or alias_item.get("alias_type") or "alias"
        quote = alias_item.get("quote")
        confidence = alias_item.get("confidence")
    else:
        raw_alias = alias_item
        alias_type = "alias"
        quote = None
        confidence = None
    alias_text = " ".join(str(raw_alias).strip().split())
    if not alias_text:
        return None
    return {
        "alias": alias_text,
        "type": alias_type,
        "status": "candidate",
        "source": "deep_import",
        "workflow_id": meta.get("workflow_id"),
        "scene_id": meta.get("scene_id"),
        "scene_index": meta.get("source_scene_index"),
        "confidence": confidence if confidence is not None else meta.get("confidence"),
        "quote": quote,
        "needs_review": True,
    }


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
        db,
        novel_id,
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
    response = await _relation_service.list(db, novel_id, skip=skip, limit=limit)
    if isinstance(response, tuple):
        return response
    return response.items, response.total


async def create_relation(
    db: AsyncSession,
    novel_id: str,
    data: dict,
) -> EntityRelationResponse:
    from modules.world.schemas import EntityRelationCreate

    rel_data = EntityRelationCreate(**data)
    return await _relation_service.create(db, novel_id, rel_data)


async def create_or_merge_relation(
    db: AsyncSession,
    novel_id: str,
    data: dict,
) -> dict[str, Any]:
    from modules.world.schemas import EntityRelationCreate

    rel_data = EntityRelationCreate(**data)
    return await _relation_service.create_or_merge(db, novel_id, rel_data)


async def upsert_relation(
    db: AsyncSession,
    novel_id: str,
    source_id: str,
    target_id: str,
    relation_type: str,
    description: str | None = None,
) -> EntityRelationResponse:
    return await _relation_service.upsert(
        db,
        novel_id,
        source_id,
        target_id,
        relation_type,
        description=description,
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
        db,
        novel_id,
        name,
        aliases=aliases,
        entity_type=entity_type,
        query_embedding=query_embedding,
    )


async def merge_candidate_into_entity(
    db: AsyncSession,
    novel_id: str,
    candidate_id: str,
    target_entity_id: str,
) -> Any:  # MergeResult
    return await _dedup_service.merge_candidate_into_entity(
        db,
        novel_id,
        candidate_id,
        target_entity_id,
    )


async def suggest_entity_fusion(
    db,
    novel_id: str,
    *,
    entity_type: str | None = None,
    status: str | None = None,
    limit: int = 200,
    max_suggestions: int = 50,
    progress_callback=None,
) -> dict:
    """Generate world entity duplicate suggestions."""
    from modules.world.entity_fusion import WorldEntityFusionService

    return await WorldEntityFusionService().suggest(
        db,
        novel_id=novel_id,
        entity_type=entity_type,
        status=status,
        limit=limit,
        max_suggestions=max_suggestions,
        progress_callback=progress_callback,
    )


async def apply_entity_fusion(
    db,
    novel_id: str,
    *,
    confirmed: bool,
    suggestions: list[dict],
) -> dict:
    """Apply user-confirmed entity fusion suggestions."""
    from modules.world.entity_fusion import WorldEntityFusionService

    items = [EntityFusionApplyItem(**item) for item in suggestions]
    return await WorldEntityFusionService().apply(
        db,
        novel_id=novel_id,
        confirmed=confirmed,
        suggestions=items,
    )


async def create_entity(
    db: AsyncSession,
    novel_id: str,
    data: dict[str, Any],
) -> dict[str, Any]:
    """创建单个 CoreEntity，返回 dict。"""
    from modules.world.schemas import CoreEntityCreate

    entity_data = CoreEntityCreate(**data)
    result = await _entity_service.create(db, novel_id, entity_data)
    return result.model_dump()


async def update_entity(
    db: AsyncSession,
    novel_id: str,
    entity_id: str,
    data: dict[str, Any],
) -> dict[str, Any] | None:
    """更新单个 CoreEntity（仅允许 status 等自由字段），返回 dict 或 None。"""
    from modules.world.schemas import CoreEntityUpdate
    from shared.utils import parse_uuid

    eid = parse_uuid(entity_id, "entity_id")
    update_data = CoreEntityUpdate(**data)
    result = await _entity_service.update(db, str(eid), update_data, novel_id=novel_id)
    return result.model_dump() if result else None


async def count_entities(
    db: AsyncSession,
    novel_id: str,
    *,
    status_filter: list[str] | None = None,
) -> int:
    """统计 novel 的 CoreEntity 数量。"""
    return await _stats_service.count_entities(
        db,
        novel_id,
        status_filter=status_filter,
    )


async def list_auto_ingested_entities(
    db: AsyncSession,
    novel_id: str,
    *,
    start_chapter: int | None = None,
    end_chapter: int | None = None,
    limit: int = 10000,
    status_filter: list[str] | None = None,
) -> list[dict[str, Any]]:
    """列出 novel 中由深度导入自动生成的实体。"""
    return await _stats_service.list_auto_ingested_entities(
        db,
        novel_id,
        start_chapter=start_chapter,
        end_chapter=end_chapter,
        limit=limit,
        status_filter=status_filter,
    )


async def deprecate_deep_import_entities_by_workflow(
    db: AsyncSession,
    novel_id: str,
    workflow_id: str,
) -> int:
    """Soft-deprecate entities from one deep import workflow."""
    return await _stats_service.deprecate_deep_import_entities_by_workflow(
        db,
        novel_id,
        workflow_id,
    )


async def backfill_entity_embeddings(
    db: AsyncSession,
    novel_id: str,
    *,
    batch_size: int = 64,
) -> int:
    """回填 novel 中缺少 embedding 的实体向量。返回回填数量。"""
    return await _embedding_service.backfill_embeddings(
        db,
        novel_id,
        batch_size=batch_size,
    )
