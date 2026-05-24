"""
World API 路由

提供世界对象、关系、别名、候选对象的 RESTful API。
API 层不写复杂业务逻辑，仅做参数校验和路由分发。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi import status as http_status

from core.dependencies import DbSession
from modules.world.schemas import (
    DuplicateSuggestionResult,
    EntityAliasCreate,
    EntityAliasListResponse,
    EntityAliasResponse,
    EntityCandidateCreate,
    EntityCandidateListResponse,
    EntityCandidateResponse,
    EntityCandidateUpdate,
    RelationshipCreate,
    RelationshipListResponse,
    RelationshipResponse,
    RelationshipUpdate,
    WorldContextBundle,
    WorldEntityContext,
    WorldEntityCreate,
    WorldEntityListResponse,
    WorldEntityResponse,
    WorldEntityUpdate,
)
from modules.world.services import (
    AliasService,
    EntityCandidateService,
    EntityDedupService,
    RelationshipService,
    WorldEntityService,
)
from shared.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE

router = APIRouter(prefix="/api/world", tags=["world"])

_entity_service = WorldEntityService()
_relationship_service = RelationshipService()
_candidate_service = EntityCandidateService()
_alias_service = AliasService()
_dedup_service = EntityDedupService()


# ============================================================
# WorldEntity 路由
# ============================================================

@router.get("/entities", response_model=WorldEntityListResponse)
async def list_entities(
    db: DbSession,
    novel_id: str = Query(..., description="项目 ID"),
    entity_type: str | None = Query(None, description="对象类型过滤"),
    status: str | None = Query(None, description="状态过滤"),
    skip: int = Query(default=0, ge=0, description="跳过的记录数"),
    limit: int = Query(
        default=DEFAULT_PAGE_SIZE,
        ge=1,
        le=MAX_PAGE_SIZE,
        description="每页条数",
    ),
) -> WorldEntityListResponse:
    """获取世界对象列表"""
    return await _entity_service.list(
        db, novel_id,
        entity_type=entity_type,
        status=status,
        skip=skip,
        limit=limit,
    )


@router.post("/entities", response_model=WorldEntityResponse, status_code=201)
async def create_entity(
    db: DbSession,
    novel_id: str = Query(..., description="项目 ID"),
    data: WorldEntityCreate = ...,
) -> WorldEntityResponse:
    """创建世界对象"""
    return await _entity_service.create(db, novel_id, data)


@router.get("/entities/{entity_id}", response_model=WorldEntityResponse)
async def get_entity(
    db: DbSession,
    entity_id: str,
) -> WorldEntityResponse:
    """获取世界对象详情"""
    return await _entity_service.get(db, entity_id)


@router.put("/entities/{entity_id}", response_model=WorldEntityResponse)
async def update_entity(
    db: DbSession,
    entity_id: str,
    data: WorldEntityUpdate,
) -> WorldEntityResponse:
    """更新世界对象"""
    return await _entity_service.update(db, entity_id, data)


@router.delete("/entities/{entity_id}", status_code=204)
async def delete_entity(
    db: DbSession,
    entity_id: str,
) -> None:
    """删除世界对象"""
    await _entity_service.delete(db, entity_id)


@router.get("/entities/{entity_id}/related", response_model=list[WorldEntityContext])
async def get_related_entities(
    db: DbSession,
    entity_id: str,
    novel_id: str = Query(..., description="项目 ID"),
    depth: int = Query(default=1, ge=1, le=2, description="扩展深度（1=一跳，2=二跳）"),
    limit: int = Query(
        default=20,
        ge=1,
        le=MAX_PAGE_SIZE,
        description="最大返回数量",
    ),
) -> list[WorldEntityContext]:
    """获取对象的关联实体（关系一跳/二跳扩展）"""
    return await _relationship_service.expand_related(
        db, novel_id,
        seed_entity_ids=[entity_id],
        depth=depth,
        limit=limit,
    )


# ============================================================
# Relationship 路由
# ============================================================

@router.get("/relationships", response_model=RelationshipListResponse)
async def list_relationships(
    db: DbSession,
    novel_id: str = Query(..., description="项目 ID"),
    skip: int = Query(default=0, ge=0, description="跳过的记录数"),
    limit: int = Query(
        default=DEFAULT_PAGE_SIZE,
        ge=1,
        le=MAX_PAGE_SIZE,
        description="每页条数",
    ),
) -> RelationshipListResponse:
    """获取关系列表"""
    items, total = await _relationship_service.list(
        db, novel_id,
        skip=skip,
        limit=limit,
    )
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
    db: DbSession,
    rel_id: str,
    data: RelationshipUpdate,
) -> RelationshipResponse:
    """更新关系"""
    return await _relationship_service.update(db, rel_id, data)


@router.delete("/relationships/{rel_id}", status_code=204)
async def delete_relationship(
    db: DbSession,
    rel_id: str,
) -> None:
    """删除关系"""
    await _relationship_service.delete(db, rel_id)


# ============================================================
# EntityAlias 路由
# ============================================================

@router.get("/aliases", response_model=EntityAliasListResponse)
async def list_aliases(
    db: DbSession,
    novel_id: str = Query(..., description="项目 ID"),
    entity_id: str | None = Query(None, description="所属对象 ID"),
    skip: int = Query(default=0, ge=0, description="跳过的记录数"),
    limit: int = Query(
        default=DEFAULT_PAGE_SIZE,
        ge=1,
        le=MAX_PAGE_SIZE,
        description="每页条数",
    ),
) -> EntityAliasListResponse:
    """获取别名列表"""
    items, total = await _alias_service.list(
        db, novel_id,
        entity_id=entity_id,
        skip=skip,
        limit=limit,
    )
    return EntityAliasListResponse(items=items, total=total)


@router.post("/aliases", response_model=EntityAliasResponse, status_code=201)
async def create_alias(
    db: DbSession,
    novel_id: str = Query(..., description="项目 ID"),
    data: EntityAliasCreate = ...,
) -> EntityAliasResponse:
    """创建别名"""
    return await _alias_service.create(db, novel_id, data)


@router.delete("/aliases/{alias_id}", status_code=204)
async def delete_alias(
    db: DbSession,
    alias_id: str,
) -> None:
    """删除别名"""
    await _alias_service.delete(db, alias_id)


# ============================================================
# EntityCandidate 路由
# ============================================================

@router.get("/candidates", response_model=EntityCandidateListResponse)
async def list_candidates(
    db: DbSession,
    novel_id: str = Query(..., description="项目 ID"),
    status: str | None = Query(None, description="状态过滤"),
    suggested_action: str | None = Query(None, description="建议动作过滤"),
    skip: int = Query(default=0, ge=0, description="跳过的记录数"),
    limit: int = Query(
        default=DEFAULT_PAGE_SIZE,
        ge=1,
        le=MAX_PAGE_SIZE,
        description="每页条数",
    ),
) -> EntityCandidateListResponse:
    """获取候选对象列表"""
    return await _candidate_service.list(
        db, novel_id,
        status=status,
        suggested_action=suggested_action,
        skip=skip,
        limit=limit,
    )


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
    db: DbSession,
    candidate_id: str,
) -> EntityCandidateResponse:
    """获取候选对象详情"""
    return await _candidate_service.get(db, candidate_id)


@router.put("/candidates/{candidate_id}", response_model=EntityCandidateResponse)
async def update_candidate(
    db: DbSession,
    candidate_id: str,
    data: EntityCandidateUpdate,
) -> EntityCandidateResponse:
    """更新候选对象"""
    return await _candidate_service.update(db, candidate_id, data)


@router.delete("/candidates/{candidate_id}", status_code=204)
async def delete_candidate(
    db: DbSession,
    candidate_id: str,
) -> None:
    """删除候选对象"""
    await _candidate_service.delete(db, candidate_id)


@router.post(
    "/candidates/{candidate_id}/dedup",
    response_model=list[DuplicateSuggestionResult],
)
async def dedup_candidate(
    db: DbSession,
    candidate_id: str,
    novel_id: str = Query(..., description="项目 ID"),
) -> list[DuplicateSuggestionResult]:
    """对候选对象进行去重检查"""
    return await _dedup_service.find_duplicates(db, novel_id, candidate_id)
