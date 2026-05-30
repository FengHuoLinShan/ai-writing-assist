"""
World Facade — 对外入口

其他模块只能从 facade 导入。导出 CoreEntity 相关操作。
别名操作已整合为 CoreEntity 的 add_alias/remove_alias 方法。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.schemas import (
<<<<<<< HEAD
    CoreEntityContext,
    CoreEntityResponse,
    DuplicateSuggestionResult,
=======
    CharacterContextBundle,
    CharacterKnowledgeContext,
    CharacterResponse,
    CoreEntityResponse,
    EntityRelationResponse,
    EventContext,
    EventsContextBundle,
>>>>>>> origin/worktree-grill-v3
    WorldContextBundle,
)
from modules.world.services import (
<<<<<<< HEAD
    CoreEntityService,
    EntityCandidateService,
    EntityDedupService,
    RelationshipService,
=======
    CharacterService,
    EntityRelationService,
    EntityRevisionService,
    EventService,
    WorldEntityService,
>>>>>>> origin/worktree-grill-v3
)
# 已废弃服务直接导入（不在 services/__init__ 中重导出）
from modules.world.services.candidate_service import EntityCandidateService
from modules.world.services.dedup_service import EntityDedupService

<<<<<<< HEAD
_entity_service = CoreEntityService()
_relationship_service = RelationshipService()
=======
_entity_service = WorldEntityService()
_relation_service = EntityRelationService()
>>>>>>> origin/worktree-grill-v3
_candidate_service = EntityCandidateService()
_dedup_service = EntityDedupService()
_revision_service = EntityRevisionService()
_event_service = EventService()
_character_service = CharacterService()


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
<<<<<<< HEAD
    """获取核心实体摘要列表"""
    result = await _entity_service.list(
        db, novel_id, entity_type=entity_type, status=status, limit=limit,
    )
    return [
        {"id": item.id, "name": item.name, "entity_type": item.entity_type, "aliases": item.aliases}
        for item in result.items
    ]
=======
    """获取世界对象摘要列表"""
    return await _entity_service.list_entity_summaries(
        db, novel_id,
        entity_type=entity_type,
        limit=limit,
    )
>>>>>>> origin/worktree-grill-v3


async def list_entity_terms(
    db: AsyncSession,
    novel_id: str,
    *,
    limit: int = 500,
) -> list[dict[str, Any]]:
<<<<<<< HEAD
    """获取核心实体检索词典项（名称 + 别名）

    供 RAG 索引用于正文标注；返回轻量 dict。
    """
=======
    """获取世界对象检索词典项（名称 + 已确认别名）"""
    from modules.world.repositories import CoreEntityRepository
>>>>>>> origin/worktree-grill-v3
    from shared.utils import parse_uuid
    from modules.world.repositories import CoreEntityRepository

    nid = parse_uuid(novel_id, "novel_id")
<<<<<<< HEAD
    entities, _ = await CoreEntityRepository().get_by_novel(db, nid, limit=limit)
=======
    entity_repo = CoreEntityRepository()
    entities, _ = await entity_repo.get_by_novel(db, nid, limit=limit)
>>>>>>> origin/worktree-grill-v3

    terms: list[dict[str, Any]] = []
    for item in entities:
        if item.status not in ("canonical", "draft"):
            continue
        item_terms = [item.name]
<<<<<<< HEAD
        for a in (item.aliases or []):
            if isinstance(a, dict) and a.get("alias"):
                item_terms.append(a["alias"])
=======
        # 别名存储在 content_json 中
        aliases = (item.content_json or {}).get("aliases", [])
        item_terms.extend(a if isinstance(a, str) else a.get("alias", "") for a in aliases)
>>>>>>> origin/worktree-grill-v3
        terms.append({
            "id": str(item.id),
            "name": item.name,
            "entity_type": item.entity_type,
            "terms": [t for t in item_terms if t],
        })
    return terms


<<<<<<< HEAD
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

=======
>>>>>>> origin/worktree-grill-v3
async def get_world_context(
    db: AsyncSession,
    novel_id: str,
    entity_ids: list[str] | None = None,
    reveal_mode: str = "author_safe",
    limit: int = 20,
) -> WorldContextBundle:
<<<<<<< HEAD
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
=======
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
    from shared.utils import parse_uuid
    nid = parse_uuid(novel_id, "novel_id")
    from modules.world.repositories import CoreEntityRepository
    repo = CoreEntityRepository()
    return await repo.find_entity_by_name(db, nid, name, entity_type=entity_type)


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


# ============================================================
# 兼容性 facade（其他模块仍在调用）
# ============================================================

async def get_location_factions(
    db: AsyncSession,
    novel_id: str,
    location_id: str,
) -> list[dict[str, Any]]:
    """获取控制/驻扎某地点的势力列表（兼容旧接口）"""
    return []


async def get_character_id_by_world_entity(
    db: AsyncSession,
    novel_id: str,
    world_entity_id: str,
) -> str | None:
    """按核心实体 ID 查找人物（新模型中 entity_id == character PK）"""
    from shared.utils import parse_uuid
    nid = parse_uuid(novel_id, "novel_id")
    weid = parse_uuid(world_entity_id, "entity_id")
    from modules.world.repositories import CharacterRepository
    repo = CharacterRepository()
    char = await repo.get(db, weid)
    if char is None:
        return None
    return str(char.entity_id)


async def check_timeline_conflicts(
    db: AsyncSession,
    novel_id: str,
    payload: dict,
) -> list[dict]:
    """时间线冲突检查（v3 暂未实现，返回空列表）"""
    return []


async def get_geo_effects_up_to_chapter(
    db: AsyncSession,
    novel_id: str,
    chapter_index: int,
) -> list[dict]:
    """获取截止到某章节的地理影响（v3 暂未实现，返回空列表）"""
    return []


# ============================================================
# 候选池 facade（保持兼容，但已标记废弃）
# ============================================================

async def count_pending_candidates(
    db: AsyncSession,
    novel_id: str,
) -> int:
    result = await _candidate_service.list(
        db, novel_id,
        status="pending",
        limit=1,
    )
    return result.total


async def find_duplicate_entity_candidates(
    db: AsyncSession,
    novel_id: str,
    candidate_id: str,
) -> list:
    return await _dedup_service.find_duplicates(db, novel_id, candidate_id)


async def accept_candidate(
    db: AsyncSession,
    novel_id: str,
    candidate_id: str,
    user_edits: dict[str, Any] | None = None,
) -> WorldEntityResponse:
    return await _candidate_service.accept_candidate(
        db, novel_id, candidate_id, user_edits=user_edits,
    )


# ============================================================
# Event facade
# ============================================================

async def create_event(
    db: AsyncSession,
    novel_id: str,
    data: dict,
) -> dict:
    from modules.world.schemas import EventCreate
    event_data = EventCreate(**data)
    event = await _event_service.create(db, novel_id, event_data)
    return EventContext(
        entity_id=event.entity_id,
        entity_name="",
        timeline_order=event.timeline_order,
        occurrence_time_label=event.occurrence_time_label,
    ).model_dump()


async def get_events_context(
    db: AsyncSession,
    novel_id: str,
    limit: int = 50,
) -> EventsContextBundle:
    """获取事件上下文（含实体名称）"""
    events = await _event_service.get_events_in_order(db, novel_id, limit=limit)

    event_contexts: list[EventContext] = []
    for ev in events:
        event_contexts.append(EventContext(
            entity_id=ev.entity_id,
            entity_name="",
            timeline_order=ev.timeline_order,
            occurrence_time_label=ev.occurrence_time_label,
        ))

    return EventsContextBundle(
        novel_id=novel_id,
        events=event_contexts,
        total_count=len(event_contexts),
    )


# ============================================================
# EntityRelation facade
# ============================================================

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
# EntityRevision facade
# ============================================================

async def get_entity_revisions(
    db: AsyncSession,
    novel_id: str,
    entity_id: str,
    skip: int = 0,
    limit: int = 20,
) -> dict:
    return await _revision_service.get_revisions(
        db, entity_id, novel_id, skip=skip, limit=limit,
    )


async def rollback_to_revision(
    db: AsyncSession,
    novel_id: str,
    entity_id: str,
    revision_id: str,
) -> dict:
    return await _revision_service.rollback_to_revision(
        db, entity_id, revision_id, novel_id,
    )


# ============================================================
# Character facade（从 character 模块迁入）
# ============================================================

async def create_character(
    db: AsyncSession,
    novel_id: str,
    name: str,
    world_entity_id: str | None = None,
) -> CharacterResponse:
    from modules.world.schemas import CharacterCreate
    entity_id = world_entity_id or ""
    data = CharacterCreate(
        novel_id=novel_id,
        name=name,
        entity_id=entity_id,
    )
    return await _character_service.create_character(db, data)


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
    from shared.utils import parse_uuid
    nid = parse_uuid(novel_id, "novel_id")
    from modules.world.repositories import CharacterRepository
    repo = CharacterRepository()
    return await repo.find_character_by_name(db, nid, name)


async def update_character_location(
    db: AsyncSession,
    novel_id: str,
    character_id: str,
    location_id: str,
    text_state: str,
    chapter_index: int,
) -> None:
    from shared.utils import parse_uuid
    cid = parse_uuid(character_id, "character_id")
    loc_id = parse_uuid(location_id, "location_id")
    from modules.world.repositories import CharacterRepository
    repo = CharacterRepository()
    await repo.update_character_meta_location(db, cid, loc_id, text_state, chapter_index)


async def get_characters_at_location(
    db: AsyncSession,
    novel_id: str,
    location_id: str,
) -> list[dict]:
    from shared.utils import parse_uuid
    nid = parse_uuid(novel_id, "novel_id")
    loc_id = parse_uuid(location_id, "location_id")
    from modules.world.repositories import CharacterRepository
    repo = CharacterRepository()
    return await repo.find_characters_by_location(db, nid, loc_id)


async def get_character_location_id(
    db: AsyncSession,
    novel_id: str,
    character_id: str,
) -> str | None:
    from shared.utils import parse_uuid
    cid = parse_uuid(character_id, "character_id")
    from modules.world.repositories import CharacterRepository
    repo = CharacterRepository()
    return await repo.get_character_location_id(db, cid)


async def list_characters(
    db: AsyncSession,
    novel_id: str,
    skip: int = 0,
    limit: int = 100,
) -> tuple[list[CharacterResponse], int]:
    result = await _character_service.list_characters(
        db, novel_id, skip=skip, limit=limit,
    )
    return result.items, result.total


# ============================================================
# 保留的旧 facade（委派到新实现）
# ============================================================
>>>>>>> origin/worktree-grill-v3

async def run_entity_extraction(
    db: AsyncSession,
    novel_id: str,
    start_chapter: int,
    end_chapter: int,
    batch_size: int = 5,
) -> dict[str, Any]:
<<<<<<< HEAD
    """从章节正文中抽取世界对象候选"""
=======
>>>>>>> origin/worktree-grill-v3
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


<<<<<<< HEAD
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
=======
async def find_similar_entities(
    db: AsyncSession,
    novel_id: str,
    name: str,
    aliases: list[str] | None = None,
    entity_type: str | None = None,
) -> list:
    return await _dedup_service.find_similar_entities(
        db, novel_id, name, aliases=aliases, entity_type=entity_type,
>>>>>>> origin/worktree-grill-v3
    )


async def merge_candidate_into_entity(
    db: AsyncSession,
    novel_id: str,
    candidate_id: str,
    target_entity_id: str,
<<<<<<< HEAD
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
=======
) -> WorldEntityResponse:
    entity = await _dedup_service.merge_candidate_into_entity(
        db, novel_id, candidate_id, target_entity_id,
    )
    return WorldEntityResponse.model_validate(entity)
>>>>>>> origin/worktree-grill-v3
