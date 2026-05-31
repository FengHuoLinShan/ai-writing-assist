"""
World API 路由 — v3 因果时空网

提供核心实体、事件、关系、版本、人物的 RESTful API。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi import status as http_status

from core.dependencies import DbSession
from modules.world.schemas import (
    CharacterCreate,
    CharacterKnowledgeCreate,
    CharacterKnowledgeListResponse,
    CharacterKnowledgeResponse,
    CharacterKnowledgeUpdate,
    CharacterListResponse,
    CharacterResponse,
    CharacterUpdate,
    CoreEntityCreate,
    CoreEntityListResponse,
    CoreEntityResponse,
    CoreEntityUpdate,
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
)
# 已废弃服务直接导入
from modules.world.services.alias_service import AliasService
from modules.world.services.candidate_service import EntityCandidateService
from modules.world.services.dedup_service import EntityDedupService
from shared.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE

router = APIRouter(prefix="/api/world", tags=["world"])

_entity_service = WorldEntityService()
_relation_service = EntityRelationService()
_candidate_service = EntityCandidateService()
_alias_service = AliasService()
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


@router.post("/entities", response_model=CoreEntityResponse, status_code=201)
async def create_entity(
    db: DbSession,
    novel_id: str = Query(..., description="项目 ID"),
    data: CoreEntityCreate = ...,
) -> CoreEntityResponse:
    return await _entity_service.create(db, novel_id, data)


@router.get("/entities/{entity_id}", response_model=CoreEntityResponse)
async def get_entity(
    db: DbSession,
    entity_id: str,
    novel_id: str = Query(..., description="项目 ID"),
) -> CoreEntityResponse:
    return await _entity_service.get(db, entity_id, novel_id=novel_id)


@router.put("/entities/{entity_id}", response_model=CoreEntityResponse)
async def update_entity(
    db: DbSession,
    entity_id: str,
    data: CoreEntityUpdate,
    novel_id: str = Query(..., description="项目 ID"),
) -> CoreEntityResponse:
    return await _entity_service.update(db, entity_id, data, novel_id=novel_id)


@router.delete("/entities/{entity_id}", status_code=204)
async def delete_entity(
    db: DbSession,
    entity_id: str,
    novel_id: str = Query(..., description="项目 ID"),
) -> None:
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
    )


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
# 已废弃服务 — 直接导入子模块
from modules.world.services.alias_service import AliasService  # noqa: E402
from modules.world.services.candidate_service import EntityCandidateService  # noqa: E402

@router.get("/relationships", response_model=EntityRelationListResponse)
async def list_relationships(
    db: DbSession,
    novel_id: str = Query(..., description="项目 ID"),
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
