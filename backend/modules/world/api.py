"""
World API 路由 — v3 因果时空网

<<<<<<< HEAD
提供核心实体、关系、候选对象的 RESTful API。
别名操作已整合为核心实体 aliases JSONB 字段，通过实体更新接口管理。
=======
提供核心实体、事件、关系、版本、人物的 RESTful API。
>>>>>>> origin/worktree-grill-v3
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi import status as http_status

from core.dependencies import DbSession
from modules.world.schemas import (
<<<<<<< HEAD
=======
    CharacterCreate,
    CharacterKnowledgeCreate,
    CharacterKnowledgeListResponse,
    CharacterKnowledgeResponse,
    CharacterKnowledgeUpdate,
    CharacterListResponse,
    CharacterResponse,
    CharacterUpdate,
>>>>>>> origin/worktree-grill-v3
    CoreEntityCreate,
    CoreEntityListResponse,
    CoreEntityResponse,
    CoreEntityUpdate,
<<<<<<< HEAD
    CoreEntityContext,
    DuplicateSuggestionResult,
    EntityCandidateCreate,
    EntityCandidateListResponse,
    EntityCandidateResponse,
    EntityCandidateUpdate,
    RelationshipCreate,
    RelationshipListResponse,
    RelationshipResponse,
    RelationshipUpdate,
    WorldContextBundle,
)
from modules.world.services import (
    CoreEntityService,
    EntityCandidateService,
    EntityDedupService,
    RelationshipService,
=======
    EntityRelationCreate,
    EntityRelationListResponse,
    EntityRelationResponse,
    EntityRelationUpdate,
    EventCreate,
    EventListResponse,
    EventResponse,
    EventUpdate,
    WorldContextBundle,
    WorldEntityContext,
)
from modules.world.services import (
    CharacterService,
    EntityRelationService,
    EntityRevisionService,
    EventService,
    WorldEntityService,
>>>>>>> origin/worktree-grill-v3
)
# 已废弃服务直接导入
from modules.world.services.alias_service import AliasService
from modules.world.services.candidate_service import EntityCandidateService
from modules.world.services.dedup_service import EntityDedupService
from shared.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE

router = APIRouter(prefix="/api/world", tags=["world"])

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


# ============================================================
# CoreEntity 路由
# ============================================================

@router.get("/entities", response_model=CoreEntityListResponse)
async def list_entities(
    db: DbSession,
    novel_id: str = Query(..., description="项目 ID"),
    entity_type: str | None = Query(None, description="实体类型过滤"),
    status: str | None = Query(None, description="状态过滤"),
    skip: int = Query(default=0, ge=0, description="跳过的记录数"),
<<<<<<< HEAD
    limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE, description="每页条数"),
) -> CoreEntityListResponse:
    """获取核心实体列表"""
    return await _entity_service.list(db, novel_id, entity_type=entity_type, status=status, skip=skip, limit=limit)
=======
    limit: int = Query(
        default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE,
        description="每页条数",
    ),
) -> CoreEntityListResponse:
    return await _entity_service.list(
        db, novel_id,
        entity_type=entity_type,
        status=status,
        skip=skip,
        limit=limit,
    )
>>>>>>> origin/worktree-grill-v3


@router.post("/entities", response_model=CoreEntityResponse, status_code=201)
async def create_entity(
    db: DbSession,
    novel_id: str = Query(..., description="项目 ID"),
    data: CoreEntityCreate = ...,
) -> CoreEntityResponse:
<<<<<<< HEAD
    """创建核心实体（统一入口）"""
=======
>>>>>>> origin/worktree-grill-v3
    return await _entity_service.create(db, novel_id, data)


@router.get("/entities/{entity_id}", response_model=CoreEntityResponse)
async def get_entity(
    db: DbSession,
    entity_id: str,
    novel_id: str = Query(..., description="项目 ID"),
) -> CoreEntityResponse:
<<<<<<< HEAD
    """获取核心实体详情"""
=======
>>>>>>> origin/worktree-grill-v3
    return await _entity_service.get(db, entity_id, novel_id=novel_id)


@router.put("/entities/{entity_id}", response_model=CoreEntityResponse)
async def update_entity(
    db: DbSession,
    entity_id: str,
    data: CoreEntityUpdate,
    novel_id: str = Query(..., description="项目 ID"),
) -> CoreEntityResponse:
<<<<<<< HEAD
    """更新核心实体（公共字段一次修改，全域生效）"""
=======
>>>>>>> origin/worktree-grill-v3
    return await _entity_service.update(db, entity_id, data, novel_id=novel_id)


@router.delete("/entities/{entity_id}", status_code=204)
async def delete_entity(
    db: DbSession,
    entity_id: str,
    novel_id: str = Query(..., description="项目 ID"),
) -> None:
<<<<<<< HEAD
    """删除核心实体（ON DELETE CASCADE 自动清理扩展表）"""
    await _entity_service.delete(db, entity_id, novel_id=novel_id)


@router.get("/entities/{entity_id}/related", response_model=list[CoreEntityContext])
async def get_related_entities(
    db: DbSession,
    entity_id: str,
    novel_id: str = Query(..., description="项目 ID"),
    depth: int = Query(default=1, ge=1, le=2, description="扩展深度"),
    limit: int = Query(default=20, ge=1, le=MAX_PAGE_SIZE, description="最大返回数量"),
) -> list[CoreEntityContext]:
    """获取对象的关联实体（关系一跳/二跳扩展）"""
    return await _relationship_service.expand_related(
        db, novel_id, seed_entity_ids=[entity_id], depth=depth, limit=limit,
=======
    await _entity_service.delete(db, entity_id, novel_id=novel_id)


@router.get("/entities/{entity_id}/relations", response_model=EntityRelationListResponse)
async def get_entity_relations(
    db: DbSession,
    entity_id: str,
    novel_id: str = Query(..., description="项目 ID"),
) -> EntityRelationListResponse:
    """获取实体的关联关系"""
    from modules.world.repositories import EntityRelationRepository
    from shared.utils import parse_uuid
    nid = parse_uuid(novel_id, "novel_id")
    eid = parse_uuid(entity_id, "entity_id")
    repo = EntityRelationRepository()
    source_rels = await repo.get_by_source(db, nid, eid, limit=MAX_PAGE_SIZE)
    target_rels = await repo.get_by_target(db, nid, eid, limit=MAX_PAGE_SIZE)
    all_rels = source_rels + target_rels
    return EntityRelationListResponse(
        items=[EntityRelationResponse.model_validate(r) for r in all_rels],
        total=len(all_rels),
>>>>>>> origin/worktree-grill-v3
    )


# ---- Alias (inline on CoreEntity) ----

@router.post("/entities/{entity_id}/aliases", status_code=201)
async def add_alias(
    db: DbSession,
    entity_id: str,
    alias: str = Query(..., description="别名文本"),
    alias_type: str = Query("name", description="别名类型"),
    novel_id: str = Query(..., description="项目 ID"),
) -> dict:
    """向实体添加别名"""
    ok = await _entity_service.add_alias(db, entity_id, alias, alias_type, novel_id=novel_id)
    if not ok:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Entity not found")
    return {"status": "ok"}


@router.delete("/entities/{entity_id}/aliases", status_code=204)
async def remove_alias(
    db: DbSession,
    entity_id: str,
    alias: str = Query(..., description="要移除的别名"),
    novel_id: str = Query(..., description="项目 ID"),
) -> None:
    """从实体移除别名（幂等：不存在即 204）"""
    await _entity_service.remove_alias(db, entity_id, alias, novel_id=novel_id)
    # 幂等删除：不检查返回值，不存在也返回 204


# ============================================================
# Event 路由
# ============================================================

@router.get("/events", response_model=EventListResponse)
async def list_events(
    db: DbSession,
    novel_id: str = Query(..., description="项目 ID"),
    skip: int = Query(default=0, ge=0, description="跳过的记录数"),
    limit: int = Query(
        default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE,
        description="每页条数",
    ),
) -> EventListResponse:
    items, total = await _event_service.list(db, novel_id, skip=skip, limit=limit)
    return EventListResponse(items=items, total=total)


@router.post("/events", response_model=EventResponse, status_code=201)
async def create_event(
    db: DbSession,
    novel_id: str = Query(..., description="项目 ID"),
    data: EventCreate = ...,
) -> EventResponse:
    return await _event_service.create(db, novel_id, data)


@router.get("/events/{entity_id}", response_model=EventResponse)
async def get_event(
    db: DbSession,
    entity_id: str,
    novel_id: str = Query(..., description="项目 ID"),
) -> EventResponse:
    return await _event_service.get(db, entity_id, novel_id=novel_id)


@router.put("/events/{entity_id}", response_model=EventResponse)
async def update_event(
    db: DbSession,
    entity_id: str,
    data: EventUpdate,
    novel_id: str = Query(..., description="项目 ID"),
) -> EventResponse:
    return await _event_service.update(db, entity_id, data, novel_id=novel_id)


@router.delete("/events/{entity_id}", status_code=204)
async def delete_event(
    db: DbSession,
    entity_id: str,
    novel_id: str = Query(..., description="项目 ID"),
) -> None:
    await _event_service.delete(db, entity_id, novel_id=novel_id)


# ============================================================
# EntityRelation 路由
# ============================================================

@router.get("/relations", response_model=EntityRelationListResponse)
async def list_relations(
    db: DbSession,
    novel_id: str = Query(..., description="项目 ID"),
    skip: int = Query(default=0, ge=0, description="跳过的记录数"),
    limit: int = Query(
        default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE,
        description="每页条数",
    ),
) -> EntityRelationListResponse:
    items, total = await _relation_service.list(db, novel_id, skip=skip, limit=limit)
    return EntityRelationListResponse(items=items, total=total)


@router.post("/relations", response_model=EntityRelationResponse, status_code=201)
async def create_relation(
    db: DbSession,
    novel_id: str = Query(..., description="项目 ID"),
    data: EntityRelationCreate = ...,
) -> EntityRelationResponse:
    return await _relation_service.create(db, novel_id, data)


@router.put("/relations/{rel_id}", response_model=EntityRelationResponse)
async def update_relation(
    db: DbSession,
    rel_id: str,
    data: EntityRelationUpdate,
    novel_id: str = Query(..., description="项目 ID"),
) -> EntityRelationResponse:
    return await _relation_service.update(db, rel_id, data, novel_id=novel_id)


@router.delete("/relations/{rel_id}", status_code=204)
async def delete_relation(
    db: DbSession,
    rel_id: str,
    novel_id: str = Query(..., description="项目 ID"),
) -> None:
    await _relation_service.delete(db, rel_id, novel_id=novel_id)


# ============================================================
# EntityRevision 路由
# ============================================================

@router.get("/entities/{entity_id}/revisions")
async def list_revisions(
    db: DbSession,
    entity_id: str,
    novel_id: str = Query(..., description="项目 ID"),
    skip: int = Query(default=0, ge=0, description="跳过的记录数"),
    limit: int = Query(default=20, ge=1, le=100, description="每页条数"),
):
    return await _revision_service.get_revisions(
        db, entity_id, novel_id, skip=skip, limit=limit,
    )


@router.post("/entities/{entity_id}/rollback")
async def rollback_entity(
    db: DbSession,
    entity_id: str,
    revision_id: str = Query(..., description="目标版本 ID"),
    novel_id: str = Query(..., description="项目 ID"),
):
    return await _revision_service.rollback_to_revision(
        db, entity_id, revision_id, novel_id,
    )


# ============================================================
# Character 路由
# ============================================================

@router.get("/characters", response_model=CharacterListResponse)
async def list_characters(
    db: DbSession,
    novel_id: str = Query(..., description="项目 ID"),
    skip: int = Query(default=0, ge=0, description="跳过的记录数"),
    limit: int = Query(
        default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE,
        description="每页条数",
    ),
) -> CharacterListResponse:
    return await _character_service.list_characters(
        db, novel_id, skip=skip, limit=limit,
    )


@router.post("/characters", response_model=CharacterResponse, status_code=201)
async def create_character(
    db: DbSession,
    novel_id: str = Query(..., description="项目 ID"),
    data: CharacterCreate = ...,
) -> CharacterResponse:
    return await _character_service.create_character(db, data)


@router.get("/characters/{character_id}", response_model=CharacterResponse)
async def get_character(
    db: DbSession,
    character_id: str,
    novel_id: str = Query(..., description="项目 ID"),
) -> CharacterResponse:
    return await _character_service.get_character(db, character_id, novel_id=novel_id)


@router.put("/characters/{character_id}", response_model=CharacterResponse)
async def update_character(
    db: DbSession,
    character_id: str,
    data: CharacterUpdate,
    novel_id: str = Query(..., description="项目 ID"),
) -> CharacterResponse:
    return await _character_service.update_character(
        db, character_id, data, novel_id=novel_id,
    )


@router.delete("/characters/{character_id}", status_code=204)
async def delete_character(
    db: DbSession,
    character_id: str,
    novel_id: str = Query(..., description="项目 ID"),
) -> None:
    await _character_service.delete_character(db, character_id, novel_id=novel_id)


# ============================================================
# CharacterKnowledge 路由
# ============================================================

@router.get("/characters/{character_id}/knowledge", response_model=CharacterKnowledgeListResponse)
async def list_knowledge(
    db: DbSession,
    character_id: str,
    novel_id: str = Query(..., description="项目 ID"),
    skip: int = Query(default=0, ge=0, description="跳过的记录数"),
    limit: int = Query(
        default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE,
        description="每页条数",
    ),
) -> CharacterKnowledgeListResponse:
    items, total = await _character_service.list_knowledge(
        db, novel_id, character_id, skip=skip, limit=limit,
    )
    return CharacterKnowledgeListResponse(items=items, total=total)


@router.post(
    "/characters/{character_id}/knowledge",
    response_model=CharacterKnowledgeResponse,
    status_code=201,
)
async def create_knowledge(
    db: DbSession,
    character_id: str,
    data: CharacterKnowledgeCreate,
    novel_id: str = Query(..., description="项目 ID"),
) -> CharacterKnowledgeResponse:
    return await _character_service.create_knowledge(
        db, data, novel_id=novel_id,
    )


@router.put(
    "/knowledge/{knowledge_id}",
    response_model=CharacterKnowledgeResponse,
)
async def update_knowledge(
    db: DbSession,
    knowledge_id: str,
    data: CharacterKnowledgeUpdate,
    novel_id: str = Query(..., description="项目 ID"),
) -> CharacterKnowledgeResponse:
    return await _character_service.update_knowledge(
        db, knowledge_id, data, novel_id=novel_id,
    )


@router.delete("/knowledge/{knowledge_id}", status_code=204)
async def delete_knowledge(
    db: DbSession,
    knowledge_id: str,
    novel_id: str = Query(..., description="项目 ID"),
) -> None:
    await _character_service.delete_knowledge(db, knowledge_id, novel_id=novel_id)


# ============================================================
# 保留的旧路由（兼容）
# ============================================================

from modules.world.schemas import (  # noqa: E402
    EntityAliasListResponse,
    EntityAliasResponse,
    WorldEntityListResponse,
    WorldEntityResponse,
)
from modules.world.services import (  # noqa: E402
    AliasService,
    EntityCandidateService,
)

@router.get("/relationships", response_model=EntityRelationListResponse)
async def list_relationships(
    db: DbSession,
    novel_id: str = Query(..., description="项目 ID"),
<<<<<<< HEAD
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
) -> RelationshipListResponse:
    """获取关系列表"""
    items, total = await _relationship_service.list(db, novel_id, skip=skip, limit=limit)
    return RelationshipListResponse(items=items, total=total)


@router.post("/relationships", response_model=RelationshipResponse, status_code=201)
async def create_relationship(
    db: DbSession,
    novel_id: str = Query(..., description="项目 ID"),
    data: RelationshipCreate = ...,
) -> RelationshipResponse:
    """创建关系"""
    return await _relationship_service.create(db, novel_id, data)


@router.put("/relationships/{rel_id}", response_model=RelationshipResponse)
async def update_relationship(
    db: DbSession, rel_id: str, data: RelationshipUpdate,
    novel_id: str = Query(..., description="项目 ID"),
) -> RelationshipResponse:
    """更新关系"""
    return await _relationship_service.update(db, rel_id, data, novel_id=novel_id)


@router.delete("/relationships/{rel_id}", status_code=204)
async def delete_relationship(
    db: DbSession, rel_id: str,
    novel_id: str = Query(..., description="项目 ID"),
) -> None:
    """删除关系"""
    await _relationship_service.delete(db, rel_id, novel_id=novel_id)


# ============================================================
# EntityCandidate 路由
# ============================================================

@router.get("/candidates", response_model=EntityCandidateListResponse)
async def list_candidates(
    db: DbSession,
    novel_id: str = Query(..., description="项目 ID"),
    status: str | None = Query(None),
    suggested_action: str | None = Query(None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
) -> EntityCandidateListResponse:
    """获取候选对象列表"""
    return await _candidate_service.list(db, novel_id, status=status, suggested_action=suggested_action, skip=skip, limit=limit)


@router.post("/candidates", response_model=EntityCandidateResponse, status_code=201)
async def create_candidate(
    db: DbSession,
    novel_id: str = Query(..., description="项目 ID"),
    data: EntityCandidateCreate = ...,
) -> EntityCandidateResponse:
    """创建候选对象"""
    return await _candidate_service.create(db, novel_id, data)


@router.get("/candidates/{candidate_id}", response_model=EntityCandidateResponse)
async def get_candidate(
    db: DbSession, candidate_id: str,
    novel_id: str = Query(..., description="项目 ID"),
) -> EntityCandidateResponse:
    """获取候选对象详情"""
    return await _candidate_service.get(db, candidate_id, novel_id=novel_id)


@router.put("/candidates/{candidate_id}", response_model=EntityCandidateResponse)
async def update_candidate(
    db: DbSession, candidate_id: str, data: EntityCandidateUpdate,
    novel_id: str = Query(..., description="项目 ID"),
) -> EntityCandidateResponse:
    """更新候选对象"""
    return await _candidate_service.update(db, candidate_id, data, novel_id=novel_id)


@router.post("/candidates/{candidate_id}/accept", response_model=CoreEntityResponse)
async def accept_candidate(
    db: DbSession, candidate_id: str,
    novel_id: str = Query(..., description="项目 ID"),
) -> CoreEntityResponse:
    """接受候选对象：创建 CoreEntity"""
    from modules.world.facade import accept_candidate as _accept
    return await _accept(db, novel_id, candidate_id)


@router.delete("/candidates/{candidate_id}", status_code=204)
async def delete_candidate(
    db: DbSession, candidate_id: str,
    novel_id: str = Query(..., description="项目 ID"),
) -> None:
    """删除候选对象"""
    await _candidate_service.delete(db, candidate_id, novel_id=novel_id)


@router.post("/candidates/{candidate_id}/dedup", response_model=list[DuplicateSuggestionResult])
async def dedup_candidate(
    db: DbSession, candidate_id: str,
    novel_id: str = Query(..., description="项目 ID"),
) -> list[DuplicateSuggestionResult]:
    """去重检查"""
    return await _dedup_service.find_duplicates(db, novel_id, candidate_id)


@router.post("/entities/{entity_id}/merge-from-candidate/{candidate_id}", response_model=CoreEntityResponse)
async def merge_from_candidate(
    db: DbSession, entity_id: str, candidate_id: str,
    novel_id: str = Query(..., description="项目 ID"),
) -> CoreEntityResponse:
    """将候选对象合并到指定 CoreEntity"""
    entity = await _dedup_service.merge_candidate_into_entity(db, novel_id, candidate_id, entity_id)
    return CoreEntityResponse.model_validate(entity)
=======
    skip: int = Query(default=0, ge=0, description="跳过的记录数"),
    limit: int = Query(
        default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE,
        description="每页条数",
    ),
) -> EntityRelationListResponse:
    """旧关系路由 — 委派到新的 relations 路由"""
    items, total = await _relation_service.list(db, novel_id, skip=skip, limit=limit)
    return EntityRelationListResponse(items=items, total=total)


@router.get("/aliases", response_model=EntityAliasListResponse)
async def list_aliases(
    db: DbSession,
    novel_id: str = Query(..., description="项目 ID"),
    entity_id: str | None = Query(None, description="所属对象 ID"),
    skip: int = Query(default=0, ge=0, description="跳过的记录数"),
    limit: int = Query(
        default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE,
        description="每页条数",
    ),
) -> EntityAliasListResponse:
    """旧别名路由 — 从 content_json 读取"""
    items, total = await _alias_service.list(
        db, novel_id, entity_id=entity_id, skip=skip, limit=limit,
    )
    return EntityAliasListResponse(items=items, total=total)


@router.get("/candidates", response_model=WorldEntityListResponse)
async def list_candidates(
    db: DbSession,
    novel_id: str = Query(..., description="项目 ID"),
    status: str | None = Query(None, description="状态过滤"),
    skip: int = Query(default=0, ge=0, description="跳过的记录数"),
    limit: int = Query(
        default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE,
        description="每页条数",
    ),
) -> WorldEntityListResponse:
    """旧候选路由 — 基本兼容实现"""
    items, total = await _candidate_service.list(
        db, novel_id, status=status, skip=skip, limit=limit,
    )
    return WorldEntityListResponse(items=items, total=total)
>>>>>>> origin/worktree-grill-v3
