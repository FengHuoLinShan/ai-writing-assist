"""
World API 路由 — v3 因果时空网

提供核心实体、事件、关系、版本、人物的 RESTful API。
"""

from __future__ import annotations

from fastapi import APIRouter, Query

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
)
from modules.world.services import (
    CharacterKnowledgeService,
    CharacterService,
    EntityRelationService,
    EntityRevisionService,
    EventService,
    WorldEntityService,
)
from modules.world.services.dedup_service import EntityDedupService
from shared.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE

router = APIRouter(prefix="/api/world", tags=["world"])

_entity_service = WorldEntityService()
_relation_service = EntityRelationService()
_dedup_service = EntityDedupService()
_revision_service = EntityRevisionService()
_event_service = EventService()
_character_service = CharacterService()
_knowledge_service = CharacterKnowledgeService()


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
    return await _relation_service.get_by_entity(db, novel_id, entity_id)


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
    items, total = await _character_service.list(
        db, novel_id, skip=skip, limit=limit,
    )
    return CharacterListResponse(items=items, total=total)


@router.post("/characters", response_model=CharacterResponse, status_code=201)
async def create_character(
    db: DbSession,
    novel_id: str = Query(..., description="项目 ID"),
    data: CharacterCreate = ...,
) -> CharacterResponse:
    return await _character_service.create(db, novel_id, data)


@router.get("/characters/{character_id}", response_model=CharacterResponse)
async def get_character(
    db: DbSession,
    character_id: str,
    novel_id: str = Query(..., description="项目 ID"),
) -> CharacterResponse:
    return await _character_service.get(
        db, character_id, novel_id=novel_id,
    )


@router.put("/characters/{character_id}", response_model=CharacterResponse)
async def update_character(
    db: DbSession,
    character_id: str,
    data: CharacterUpdate,
    novel_id: str = Query(..., description="项目 ID"),
) -> CharacterResponse:
    return await _character_service.update(
        db, character_id, data, novel_id=novel_id,
    )


@router.delete("/characters/{character_id}", status_code=204)
async def delete_character(
    db: DbSession,
    character_id: str,
    novel_id: str = Query(..., description="项目 ID"),
) -> None:
    await _character_service.delete(db, character_id, novel_id=novel_id)


# ============================================================
# CharacterKnowledge 路由 (独立 CharacterKnowledgeService)
# ============================================================

@router.get(
    "/characters/{character_id}/knowledge",
    response_model=CharacterKnowledgeListResponse,
)
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
    return await _knowledge_service.list(
        db, novel_id, character_id, skip=skip, limit=limit,
    )


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
    return await _knowledge_service.create(db, novel_id, data)


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
    return await _knowledge_service.update(
        db, knowledge_id, data, novel_id=novel_id,
    )


@router.delete("/knowledge/{knowledge_id}", status_code=204)
async def delete_knowledge(
    db: DbSession,
    knowledge_id: str,
    novel_id: str = Query(..., description="项目 ID"),
) -> None:
    await _knowledge_service.delete(
        db, knowledge_id, novel_id=novel_id,
    )


@router.get("/entity-batches")
async def list_entity_batches(
    db: DbSession,
    novel_id: str = Query(..., description="项目 ID"),
    limit: int = Query(default=10, ge=1, le=50, description="最多返回的批次数量"),
) -> list[dict]:
    """获取自动入库实体的批次分组列表

    每次 LLM 抽取生成一个 batch_id，同一批次的实体归为一组。
    按入库时间倒序排列。
    """
    return await _entity_service.list_entity_batches(
        db, novel_id, limit=limit,
    )
