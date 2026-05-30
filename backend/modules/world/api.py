"""
World API 路由

提供核心实体、关系、候选对象的 RESTful API。
别名操作已整合为核心实体 aliases JSONB 字段，通过实体更新接口管理。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi import status as http_status

from core.dependencies import DbSession
from modules.world.schemas import (
    CoreEntityCreate,
    CoreEntityListResponse,
    CoreEntityResponse,
    CoreEntityUpdate,
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
)
from shared.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE

router = APIRouter(prefix="/api/world", tags=["world"])

_entity_service = CoreEntityService()
_relationship_service = RelationshipService()
_candidate_service = EntityCandidateService()
_dedup_service = EntityDedupService()


# ============================================================
# CoreEntity 路由
# ============================================================

@router.get("/entities", response_model=CoreEntityListResponse)
async def list_entities(
    db: DbSession,
    novel_id: str = Query(..., description="项目 ID"),
    entity_type: str | None = Query(None, description="对象类型过滤"),
    status: str | None = Query(None, description="状态过滤"),
    skip: int = Query(default=0, ge=0, description="跳过的记录数"),
    limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE, description="每页条数"),
) -> CoreEntityListResponse:
    """获取核心实体列表"""
    return await _entity_service.list(db, novel_id, entity_type=entity_type, status=status, skip=skip, limit=limit)


@router.post("/entities", response_model=CoreEntityResponse, status_code=201)
async def create_entity(
    db: DbSession,
    novel_id: str = Query(..., description="项目 ID"),
    data: CoreEntityCreate = ...,
) -> CoreEntityResponse:
    """创建核心实体（统一入口）"""
    return await _entity_service.create(db, novel_id, data)


@router.get("/entities/{entity_id}", response_model=CoreEntityResponse)
async def get_entity(
    db: DbSession,
    entity_id: str,
    novel_id: str = Query(..., description="项目 ID"),
) -> CoreEntityResponse:
    """获取核心实体详情"""
    return await _entity_service.get(db, entity_id, novel_id=novel_id)


@router.put("/entities/{entity_id}", response_model=CoreEntityResponse)
async def update_entity(
    db: DbSession,
    entity_id: str,
    data: CoreEntityUpdate,
    novel_id: str = Query(..., description="项目 ID"),
) -> CoreEntityResponse:
    """更新核心实体（公共字段一次修改，全域生效）"""
    return await _entity_service.update(db, entity_id, data, novel_id=novel_id)


@router.delete("/entities/{entity_id}", status_code=204)
async def delete_entity(
    db: DbSession,
    entity_id: str,
    novel_id: str = Query(..., description="项目 ID"),
) -> None:
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
# Relationship 路由
# ============================================================

@router.get("/relationships", response_model=RelationshipListResponse)
async def list_relationships(
    db: DbSession,
    novel_id: str = Query(..., description="项目 ID"),
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
