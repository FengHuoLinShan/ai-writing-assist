"""
World Facade — 对外入口

其他模块只能从 facade 导入。导出 CoreEntity 相关操作。
别名操作已整合为 CoreEntity 的 add_alias/remove_alias 方法。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.schemas import (
    CoreEntityContext,
    CoreEntityResponse,
    DuplicateSuggestionResult,
    WorldContextBundle,
)
from modules.world.services import (
    CoreEntityService,
    EntityCandidateService,
    EntityDedupService,
    RelationshipService,
)

_entity_service = CoreEntityService()
_relationship_service = RelationshipService()
_candidate_service = EntityCandidateService()
_dedup_service = EntityDedupService()


# ---- Core Entity ----

async def create_entity(
    db: AsyncSession,
    novel_id: str,
    name: str,
    entity_type: str,
    *,
    aliases: list[dict] | None = None,
    summary: str | None = None,
    public_info: str | None = None,
    hidden_truth: str | None = None,
    importance: float = 0.5,
    importance_level: str = "normal",
    status: str = "draft",
    skip_dedup: bool = False,
) -> CoreEntityResponse:
    """创建核心实体 — 统一的实体创建入口

    供 world 模块 API 及 character/geo 等模块联动创建实体时调用。
    """
    from modules.world.schemas import CoreEntityCreate

    data = CoreEntityCreate(
        entity_type=entity_type,
        name=name,
        aliases=aliases or [],
        summary=summary,
        public_info=public_info,
        hidden_truth=hidden_truth,
        importance=importance,
        importance_level=importance_level,
        status=status,
    )
    return await _entity_service.create(db, novel_id, data, skip_dedup=skip_dedup)


async def get_entity(
    db: AsyncSession,
    entity_id: str,
    novel_id: str | None = None,
) -> CoreEntityResponse:
    """获取核心实体详情"""
    return await _entity_service.get(db, entity_id, novel_id)


async def list_entities(
    db: AsyncSession,
    novel_id: str,
    *,
    entity_type: str | None = None,
    status: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """获取核心实体摘要列表"""
    result = await _entity_service.list(
        db, novel_id, entity_type=entity_type, status=status, limit=limit,
    )
    return [
        {"id": item.id, "name": item.name, "entity_type": item.entity_type, "aliases": item.aliases}
        for item in result.items
    ]


async def list_entity_terms(
    db: AsyncSession,
    novel_id: str,
    *,
    limit: int = 500,
) -> list[dict[str, Any]]:
    """获取核心实体检索词典项（名称 + 别名）

    供 RAG 索引用于正文标注；返回轻量 dict。
    """
    from shared.utils import parse_uuid
    from modules.world.repositories import CoreEntityRepository

    nid = parse_uuid(novel_id, "novel_id")
    entities, _ = await CoreEntityRepository().get_by_novel(db, nid, limit=limit)

    terms: list[dict[str, Any]] = []
    for item in entities:
        if item.status not in ("canonical", "draft"):
            continue
        item_terms = [item.name]
        for a in (item.aliases or []):
            if isinstance(a, dict) and a.get("alias"):
                item_terms.append(a["alias"])
        terms.append({
            "id": str(item.id),
            "name": item.name,
            "entity_type": item.entity_type,
            "terms": [t for t in item_terms if t],
        })
    return terms


async def update_entity(
    db: AsyncSession,
    entity_id: str,
    novel_id: str | None = None,
    **fields,
) -> CoreEntityResponse:
    """更新核心实体字段"""
    from modules.world.schemas import CoreEntityUpdate

    data = CoreEntityUpdate(**{k: v for k, v in fields.items() if v is not None})
    return await _entity_service.update(db, entity_id, data, novel_id)


async def delete_entity(
    db: AsyncSession,
    entity_id: str,
    novel_id: str | None = None,
) -> None:
    """删除核心实体（CASCADE 清理扩展表）"""
    await _entity_service.delete(db, entity_id, novel_id)


# ---- Alias (now inline on CoreEntity) ----

async def add_alias(
    db: AsyncSession,
    entity_id: str,
    alias: str,
    alias_type: str = "name",
    novel_id: str | None = None,
) -> bool:
    """向核心实体添加别名"""
    return await _entity_service.add_alias(db, entity_id, alias, alias_type, novel_id=novel_id)


async def remove_alias(
    db: AsyncSession,
    entity_id: str,
    alias: str,
    novel_id: str | None = None,
) -> bool:
    """从核心实体移除别名"""
    return await _entity_service.remove_alias(db, entity_id, alias, novel_id=novel_id)


# ---- Entity Context ----

async def get_world_context(
    db: AsyncSession,
    novel_id: str,
    entity_ids: list[str] | None = None,
    reveal_mode: str = "author_safe",
    limit: int = 20,
) -> WorldContextBundle:
    """获取世界上下文 — 供其他模块（character、outline、context 等）使用"""
    return await _entity_service.get_entity_context(
        db, novel_id, entity_ids=entity_ids, reveal_mode=reveal_mode, limit=limit,
    )


async def get_entity_importance_map(
    db: AsyncSession,
    novel_id: str,
) -> dict[str, dict[str, object]]:
    """获取所有正史实体的重要性映射 — 供 RAG 索引使用"""
    from shared.utils import parse_uuid
    from modules.world.repositories import CoreEntityRepository

    nid = parse_uuid(novel_id, "novel_id")
    entities, _ = await CoreEntityRepository().get_by_novel(db, nid, limit=2000)
    result: dict[str, dict[str, object]] = {}
    for item in entities:
        if item.status in ("canonical", "draft"):
            result[str(item.id)] = {
                "importance": item.importance,
                "importance_level": item.importance_level,
            }
    return result


# ---- Entity Extraction ----

async def run_entity_extraction(
    db: AsyncSession,
    novel_id: str,
    start_chapter: int,
    end_chapter: int,
    batch_size: int = 5,
) -> dict[str, Any]:
    """从章节正文中抽取世界对象候选"""
    from modules.world.services import EntityExtractionService
    service = EntityExtractionService()
    result = await service.extract_entities_from_chapters(
        db, novel_id=novel_id, start_chapter=start_chapter,
        end_chapter=end_chapter, batch_size=batch_size,
    )
    return {
        "total_chapters": result.total_chapters,
        "total_created": result.total_created,
        "total_skipped": result.total_skipped,
        "items": result.items,
    }


# ---- Candidates ----

async def count_pending_candidates(
    db: AsyncSession,
    novel_id: str,
) -> int:
    """统计待处理的候选对象数量"""
    result = await _candidate_service.list(db, novel_id, status="pending", limit=1)
    return result.total


async def accept_candidate(
    db: AsyncSession,
    novel_id: str,
    candidate_id: str,
    user_edits: dict[str, Any] | None = None,
) -> CoreEntityResponse:
    """接受候选对象 → 创建 CoreEntity"""
    return await _candidate_service.accept_candidate(
        db, novel_id, candidate_id, user_edits=user_edits,
    )


async def merge_candidate_into_entity(
    db: AsyncSession,
    novel_id: str,
    candidate_id: str,
    target_entity_id: str,
) -> CoreEntityResponse:
    """合并候选到已有 CoreEntity"""
    entity = await _dedup_service.merge_candidate_into_entity(
        db, novel_id, candidate_id, target_entity_id,
    )
    return CoreEntityResponse.model_validate(entity)


# ---- Dedup ----

async def find_duplicate_entity_candidates(
    db: AsyncSession,
    novel_id: str,
    candidate_id: str,
) -> list[DuplicateSuggestionResult]:
    """查找候选对象的重复匹配"""
    return await _dedup_service.find_duplicates(db, novel_id, candidate_id)


async def find_similar_entities(
    db: AsyncSession,
    novel_id: str,
    name: str,
    aliases: list[str] | None = None,
    entity_type: str | None = None,
) -> list[DuplicateSuggestionResult]:
    """查找相似实体"""
    return await _dedup_service.find_similar_entities(
        db, novel_id, name, aliases=aliases, entity_type=entity_type,
    )


# ---- Relationships ----

async def find_entity_id_by_name(
    db: AsyncSession,
    novel_id: str,
    name: str,
    entity_type: str | None = None,
) -> str | None:
    """按名称查找实体 ID"""
    from shared.utils import parse_uuid
    from modules.world.repositories import CoreEntityRepository
    nid = parse_uuid(novel_id, "novel_id")
    return await CoreEntityRepository().find_entity_by_name(db, nid, name, entity_type=entity_type)


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
    from modules.world.repositories import RelationshipRepository
    nid = parse_uuid(novel_id, "novel_id")
    await RelationshipRepository().upsert_relationship(
        db, nid, source_id, target_id, source_type, target_type, relation_type, description,
    )


async def get_location_factions(
    db: AsyncSession,
    novel_id: str,
    location_id: str,
) -> list[dict[str, Any]]:
    """获取控制/驻扎某地点的势力列表"""
    from shared.utils import parse_uuid
    from modules.world.repositories import CoreEntityRepository, RelationshipRepository
    nid = parse_uuid(novel_id, "novel_id")
    return await RelationshipRepository().get_factions_for_location(
        db, nid, location_id, CoreEntityRepository(),
    )


async def expand_related_entities(
    db: AsyncSession,
    novel_id: str,
    seed_entity_ids: list[str],
    depth: int = 1,
    limit: int = 20,
) -> list[CoreEntityContext]:
    """扩展关联实体 — 从种子实体出发通过关系网络扩展"""
    return await _relationship_service.expand_related(
        db, novel_id, seed_entity_ids=seed_entity_ids, depth=depth, limit=limit,
    )
