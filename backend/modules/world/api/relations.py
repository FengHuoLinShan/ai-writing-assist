"""实体关系路由。"""

from __future__ import annotations

from typing import Literal

from fastapi import Query

from core.dependencies import DbSession
from modules.world.api._shared import (
    ActiveNovelIdQuery,
    _relation_service,
    router,
)
from modules.world.relation_schemas import (
    WorldRelationMembershipBatchRequest,
    WorldRelationMembershipBatchResponse,
)
from modules.world.schemas import (
    EntityRelationCreate,
    EntityRelationListResponse,
    EntityRelationResponse,
    EntityRelationReviewBatchRequest,
    EntityRelationReviewEditRequest,
    EntityRelationReviewGroupListResponse,
    EntityRelationUpdate,
    RelationKind,
    ReviewBatchResponse,
)
from shared.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE


@router.get("/relations", response_model=EntityRelationListResponse)
async def list_relations(
    db: DbSession,
    *,
    novel_id: ActiveNovelIdQuery,
    status: str | None = Query(None, description="状态过滤"),
    relation_type: str | None = Query(None, description="关系类型过滤"),
    relation_kind: RelationKind | None = Query(None, description="最小语义类型过滤"),
    q: str | None = Query(None, description="关系/端点名称搜索"),
    source_chapter_id: str | None = Query(None, description="来源章节 ID"),
    strength_min: float | None = Query(None, ge=0.0, le=1.0, description="最低强度"),
    strength_max: float | None = Query(None, ge=0.0, le=1.0, description="最高强度"),
    skip: int = Query(default=0, ge=0, description="跳过的记录数"),
    limit: int = Query(
        default=DEFAULT_PAGE_SIZE,
        ge=1,
        le=MAX_PAGE_SIZE,
        description="每页条数",
    ),
) -> EntityRelationListResponse:
    return await _relation_service.list(
        db,
        novel_id,
        status=status,
        relation_type=relation_type,
        relation_kind=relation_kind,
        q=q,
        source_chapter_id=source_chapter_id,
        strength_min=strength_min,
        strength_max=strength_max,
        skip=skip,
        limit=limit,
    )


@router.get(
    "/relations/review-groups",
    response_model=EntityRelationReviewGroupListResponse,
)
async def list_relation_review_groups(
    db: DbSession,
    *,
    novel_id: ActiveNovelIdQuery,
    q: str | None = Query(None),
    relation_type: str | None = Query(None),
    relation_kind: RelationKind | None = Query(None),
    source_chapter_id: str | None = Query(None),
    scene_id: str | None = Query(None),
    scene_index: int | None = Query(None),
    source_chapter_index: int | None = Query(None),
    strength_min: float | None = Query(None, ge=0.0, le=1.0),
    strength_max: float | None = Query(None, ge=0.0, le=1.0),
    has_quote: bool | None = Query(None),
    type_kind: Literal["recommended", "custom"] | None = Query(None),
    multi_type_only: bool = Query(False),
    has_reverse_candidates: bool | None = Query(None),
    has_canonical_relation: bool | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=50),
) -> EntityRelationReviewGroupListResponse:
    return await _relation_service.list_review_groups(
        db,
        novel_id,
        q=q,
        relation_type=relation_type,
        relation_kind=relation_kind,
        source_chapter_id=source_chapter_id,
        scene_id=scene_id,
        scene_index=scene_index,
        source_chapter_index=source_chapter_index,
        strength_min=strength_min,
        strength_max=strength_max,
        has_quote=has_quote,
        type_kind=type_kind,
        multi_type_only=multi_type_only,
        has_reverse_candidates=has_reverse_candidates,
        has_canonical_relation=has_canonical_relation,
        skip=skip,
        limit=limit,
    )


@router.post(
    "/relations/review-batch",
    response_model=ReviewBatchResponse,
)
async def review_relations_batch(
    db: DbSession,
    data: EntityRelationReviewBatchRequest,
    *,
    novel_id: ActiveNovelIdQuery,
) -> ReviewBatchResponse:
    return await _relation_service.review_batch(db, novel_id, data)


@router.post(
    "/relations/membership-batch",
    response_model=WorldRelationMembershipBatchResponse,
)
async def apply_world_relation_membership_batch(
    db: DbSession,
    data: WorldRelationMembershipBatchRequest,
    *,
    novel_id: ActiveNovelIdQuery,
) -> WorldRelationMembershipBatchResponse:
    """世界库关系视角的单个／批量成员维护（整批一个事务）。"""
    return await _relation_service.membership_batch(db, novel_id, data)


@router.post("/relations", response_model=EntityRelationResponse, status_code=201)
async def create_relation(
    db: DbSession,
    *,
    novel_id: ActiveNovelIdQuery,
    data: EntityRelationCreate = ...,
) -> EntityRelationResponse:
    return await _relation_service.create(db, novel_id, data)


@router.put("/relations/{rel_id}", response_model=EntityRelationResponse)
async def update_relation(
    db: DbSession,
    rel_id: str,
    data: EntityRelationUpdate,
    *,
    novel_id: ActiveNovelIdQuery,
) -> EntityRelationResponse:
    return await _relation_service.update(db, rel_id, data, novel_id=novel_id)


@router.patch("/relations/{rel_id}/review-edit")
async def review_edit_relation(
    db: DbSession,
    rel_id: str,
    data: EntityRelationReviewEditRequest,
    *,
    novel_id: ActiveNovelIdQuery,
) -> dict[str, object]:
    return await _relation_service.review_edit(db, novel_id, rel_id, data)


@router.delete("/relations/{rel_id}", status_code=204)
async def delete_relation(
    db: DbSession,
    rel_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
) -> None:
    await _relation_service.delete(db, rel_id, novel_id=novel_id)
