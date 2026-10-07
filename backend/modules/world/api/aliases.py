"""实体别名路由（操作 core_entities.content_json.aliases）。"""

from __future__ import annotations

from typing import Literal

from fastapi import Query

from core.dependencies import DbSession
from modules.world.api._shared import (
    ActiveNovelIdQuery,
    _alias_service,
    router,
)
from modules.world.schemas import (
    AliasKind,
    EntityAliasCreate,
    EntityAliasEditRequest,
    EntityAliasReviewBatchRequest,
    EntityAliasReviewGroupListResponse,
    EntityAliasUpdate,
    ReviewBatchResponse,
)


@router.get("/aliases")
async def list_aliases(
    db: DbSession,
    *,
    novel_id: ActiveNovelIdQuery,
    q: str | None = Query(None, description="别名/对象/引用搜索"),
    display_state: Literal["active", "review", "archived"] | None = Query(
        None,
        description="作者展示态过滤",
    ),
    status: str | None = Query(None, description="状态过滤"),
    alias_kind: AliasKind | None = Query(None, description="最小语义类型过滤"),
    needs_review: bool | None = Query(None, description="是否需要复核"),
    source: str | None = Query(None, description="来源过滤"),
    workflow_id: str | None = Query(None, description="深度导入 workflow ID"),
    scene_id: str | None = Query(None, description="来源 Scene ID"),
    scene_index: int | None = Query(None, description="来源 Scene 索引"),
    source_chapter_index: int | None = Query(None, description="来源章节索引"),
    confidence_min: float | None = Query(None, ge=0.0, le=1.0, description="最低置信度"),
    confidence_max: float | None = Query(None, ge=0.0, le=1.0, description="最高置信度"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
) -> dict:
    """列出项目下所有实体的别名"""
    return await _alias_service.list_aliases_page(
        db,
        novel_id,
        q=q,
        display_state=display_state,
        status=status,
        alias_kind=alias_kind,
        needs_review=needs_review,
        source=source,
        workflow_id=workflow_id,
        scene_id=scene_id,
        scene_index=scene_index,
        source_chapter_index=source_chapter_index,
        confidence_min=confidence_min,
        confidence_max=confidence_max,
        skip=skip,
        limit=limit,
    )


@router.get(
    "/aliases/review-groups",
    response_model=EntityAliasReviewGroupListResponse,
)
async def list_alias_review_groups(
    db: DbSession,
    *,
    novel_id: ActiveNovelIdQuery,
    q: str | None = Query(None),
    source: str | None = Query(None),
    workflow_id: str | None = Query(None),
    scene_id: str | None = Query(None),
    scene_index: int | None = Query(None),
    source_chapter_index: int | None = Query(None),
    confidence_min: float | None = Query(None, ge=0.0, le=1.0),
    confidence_max: float | None = Query(None, ge=0.0, le=1.0),
    has_quote: bool | None = Query(None),
    type_kind: Literal["recommended", "custom"] | None = Query(None),
    alias_kind: AliasKind | None = Query(None),
    multi_alias_only: bool = Query(False),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=50),
) -> EntityAliasReviewGroupListResponse:
    return await _alias_service.list_review_groups(
        db,
        novel_id,
        q=q,
        source=source,
        workflow_id=workflow_id,
        scene_id=scene_id,
        scene_index=scene_index,
        source_chapter_index=source_chapter_index,
        confidence_min=confidence_min,
        confidence_max=confidence_max,
        has_quote=has_quote,
        type_kind=type_kind,
        alias_kind=alias_kind,
        multi_alias_only=multi_alias_only,
        skip=skip,
        limit=limit,
    )


@router.post(
    "/aliases/review-batch",
    response_model=ReviewBatchResponse,
)
async def review_aliases_batch(
    db: DbSession,
    data: EntityAliasReviewBatchRequest,
    *,
    novel_id: ActiveNovelIdQuery,
) -> ReviewBatchResponse:
    return await _alias_service.review_batch(db, novel_id, data)


@router.post("/aliases", status_code=201)
async def create_alias(
    db: DbSession,
    *,
    novel_id: ActiveNovelIdQuery,
    data: EntityAliasCreate = ...,
) -> dict:
    """为实体添加别名"""
    return await _alias_service.create_alias(
        db,
        novel_id,
        data.entity_id,
        data.alias,
        data.alias_type,
        alias_kind=data.alias_kind,
        status=data.status,
        source="manual",
        source_chapter_index=data.source_chapter_index,
        confidence=data.confidence,
    )


@router.patch("/entities/{entity_id}/aliases")
async def update_alias(
    db: DbSession,
    entity_id: str,
    data: EntityAliasUpdate,
    *,
    novel_id: ActiveNovelIdQuery,
    alias: str = Query(..., description="要更新的别名文本"),
) -> dict:
    """更新实体的指定别名元数据。"""
    return await _alias_service.update_alias(
        db,
        novel_id,
        entity_id,
        alias,
        data.model_dump(exclude_unset=True),
    )


@router.patch("/entities/{entity_id}/aliases/edit")
async def edit_alias(
    db: DbSession,
    entity_id: str,
    data: EntityAliasEditRequest,
    *,
    novel_id: ActiveNovelIdQuery,
    alias: str = Query(..., description="要编辑的原别名文本"),
) -> dict:
    return await _alias_service.edit_alias(
        db,
        novel_id,
        entity_id,
        alias,
        target_entity_id=data.target_entity_id,
        alias=data.alias,
        alias_type=data.alias_type,
        alias_kind=data.alias_kind,
        confirm_review=data.confirm_review,
    )


@router.delete("/entities/{entity_id}/aliases")
async def delete_alias(
    db: DbSession,
    entity_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
    alias: str = Query(..., description="要删除的别名文本"),
) -> dict:
    """删除实体的指定别名"""
    return await _alias_service.delete_alias(
        db,
        novel_id,
        entity_id,
        alias,
    )
