"""核心实体路由：CRUD、图片与候选、融合、别名关系补抽。"""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response

from core.csrf import require_xhr_request
from core.dependencies import DbSession
from infrastructure.tasks.facade import (
    enqueue_task_with_optional_operation,
    get_operation_task,
)
from modules.account.facade import current_account_id
from modules.evidence.facade import attach_result_ref, require_fresh_confirmation
from modules.project.facade import (
    build_project_llm_execution_snapshot,
    require_active_project,
)
from modules.world.api._shared import (
    ActiveNovelIdQuery,
    _alias_service,
    _dedup_service,
    _entity_image_generation_service,
    _entity_image_service,
    _entity_service,
    _fusion_service,
    _relation_service,
    router,
)
from modules.world.schemas import (
    CoreEntityCreate,
    CoreEntityListResponse,
    CoreEntityResponse,
    CoreEntityUpdate,
    EntityFusionApplyRequest,
    EntityFusionApplyResponse,
    EntityFusionSuggestionRequest,
    EntityFusionSuggestionResponse,
    EntityMergeRequest,
    EntityMergeResponse,
    EntityPromoteRequest,
    EntityPromoteResponse,
    EntityRelationListResponse,
    EntityResolveAsAliasRequest,
    EntityTypeCatalogResponse,
    ReviewTypeCatalogResponse,
    WorldAliasRelationExtractRequest,
    WorldAliasRelationExtractResponse,
)
from modules.world.services.core.review_queue import review_type_catalog
from modules.world.world_object_image_generation import (
    WorldObjectImageCandidateAction,
    WorldObjectImageCandidateAdoptResponse,
    WorldObjectImageCandidateCreate,
    WorldObjectImageCandidateView,
    WorldObjectImageGenerationInfo,
)
from modules.world.world_object_images import (
    MAX_UPLOAD_BYTES as MAX_WORLD_OBJECT_IMAGE_BYTES,
)
from shared.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE


@router.get("/entity-types", response_model=EntityTypeCatalogResponse)
async def list_entity_types(
    db: DbSession,
    *,
    novel_id: ActiveNovelIdQuery,
) -> EntityTypeCatalogResponse:
    return await _entity_service.list_entity_types(db, novel_id)


@router.get("/review-type-catalog", response_model=ReviewTypeCatalogResponse)
async def get_review_type_catalog() -> ReviewTypeCatalogResponse:
    """Author-facing recommendations; relation and alias values remain open strings."""
    return ReviewTypeCatalogResponse.model_validate(review_type_catalog())


@router.get("/entities", response_model=CoreEntityListResponse)
async def list_entities(
    db: DbSession,
    *,
    novel_id: ActiveNovelIdQuery,
    entity_type: str | None = Query(None, description="实体类型过滤"),
    status: str | None = Query(None, description="状态过滤"),
    display_state: Literal["active", "review", "archived"] | None = Query(
        None,
        description="作者展示状态过滤（兼容保留 status）",
    ),
    q: str | None = Query(None, description="名称、别名或描述的模糊搜索"),
    source: str | None = Query(None, description="来源过滤"),
    workflow_id: str | None = Query(None, description="深度导入 workflow ID"),
    needs_review: bool | None = Query(None, description="是否需要复核"),
    auto_ingested: bool | None = Query(None, description="是否自动导入"),
    suggested_action: str | None = Query(None, description="待处理项的建议动作"),
    scene_id: str | None = Query(None, description="来源 Scene ID"),
    scene_index: int | None = Query(None, description="来源 Scene 索引"),
    source_chapter_index: int | None = Query(None, description="来源章节索引"),
    confidence_min: float | None = Query(None, ge=0.0, le=1.0, description="最低置信度"),
    confidence_max: float | None = Query(None, ge=0.0, le=1.0, description="最高置信度"),
    view_mode: Literal["normal", "hot"] = Query(
        "normal",
        description="列表浏览模式：normal / hot",
    ),
    focus: Literal["important", "hot", "other"] | None = Query(
        None,
        description="热点模式聚合筛选",
    ),
    skip: int = Query(default=0, ge=0, description="跳过的记录数"),
    limit: int = Query(
        default=DEFAULT_PAGE_SIZE,
        ge=1,
        le=MAX_PAGE_SIZE,
        description="每页条数",
    ),
) -> CoreEntityListResponse:
    return await _entity_service.list(
        db,
        novel_id,
        entity_type=entity_type,
        status=status,
        display_state=display_state,
        q=q,
        source=source,
        workflow_id=workflow_id,
        needs_review=needs_review,
        auto_ingested=auto_ingested,
        suggested_action=suggested_action,
        scene_id=scene_id,
        scene_index=scene_index,
        source_chapter_index=source_chapter_index,
        confidence_min=confidence_min,
        confidence_max=confidence_max,
        view_mode=view_mode,
        focus=focus,
        skip=skip,
        limit=limit,
    )


@router.post("/entities", response_model=CoreEntityResponse, status_code=201)
async def create_entity(
    db: DbSession,
    *,
    novel_id: ActiveNovelIdQuery,
    data: CoreEntityCreate = ...,
) -> CoreEntityResponse:
    return await _entity_service.create(db, novel_id, data)


@router.post(
    "/alias-relations/extract",
    response_model=WorldAliasRelationExtractResponse,
    status_code=201,
)
async def extract_alias_relations(
    db: DbSession,
    data: WorldAliasRelationExtractRequest,
) -> WorldAliasRelationExtractResponse:
    """提交手动别名/关系补抽任务。"""
    await require_active_project(db, data.novel_id)
    if not data.context_confirmation_id:
        raise HTTPException(
            status_code=400,
            detail="context_confirmation_id is required",
        )
    payload = data.model_dump(mode="json", exclude_none=True, exclude={"operation_id"})
    try:
        existing = await get_operation_task(
            db,
            operation_id=str(data.operation_id) if data.operation_id else None,
            task_type="world_alias_relation_extraction",
            novel_id=data.novel_id,
            request_payload=payload,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if existing is not None:
        return WorldAliasRelationExtractResponse(
            task_id=existing.task_id,
            status=existing.status,
        )
    try:
        await require_fresh_confirmation(
            db,
            novel_id=data.novel_id,
            action="world.alias_relations.extract",
            confirmation_id=data.context_confirmation_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    frozen_scene_ids = data.scene_ids
    if frozen_scene_ids is None:
        from modules.story.facade import get_scenes_by_novel

        scenes = await get_scenes_by_novel(
            db,
            data.novel_id,
            status_filter=["draft", "canonical"],
        )
        frozen_scene_ids = [
            str(scene["id"])
            for scene in scenes
            if data.start_chapter
            <= max(
                [
                    int(chapter)
                    for chapter in scene.get("chapter_ids") or []
                    if str(chapter).isdigit()
                ]
                or [int(scene.get("scene_index") or 0)]
            )
            <= data.end_chapter
        ]

    llm_execution_snapshot = await build_project_llm_execution_snapshot(
        db,
        data.novel_id,
    )
    try:
        receipt = await enqueue_task_with_optional_operation(
            db,
            operation_id=str(data.operation_id) if data.operation_id else None,
            task_type="world_alias_relation_extraction",
            novel_id=data.novel_id,
            request_payload=payload,
            meta={
                **payload,
                # Freeze an omitted chapter-range selection before enqueue so
                # the run budget and provider inputs share one exact Scene set.
                "scene_ids": frozen_scene_ids,
                "llm_execution_snapshot": llm_execution_snapshot,
            },
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not receipt.reused:
        await attach_result_ref(
            db,
            novel_id=data.novel_id,
            confirmation_id=data.context_confirmation_id,
            result_type="task",
            result_id=receipt.task_id,
            status="running",
        )
    await db.flush()
    return WorldAliasRelationExtractResponse(
        task_id=receipt.task_id,
        status=receipt.status,
    )


@router.get("/entities/{entity_id}", response_model=CoreEntityResponse)
async def get_entity(
    db: DbSession,
    entity_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
) -> CoreEntityResponse:
    return await _entity_service.get(db, entity_id, novel_id=novel_id)


@router.put(
    "/entities/{entity_id}/image",
    response_model=CoreEntityResponse,
    dependencies=[Depends(require_xhr_request)],
)
async def upload_entity_image(
    db: DbSession,
    entity_id: str,
    image: Annotated[UploadFile, File()],
    *,
    novel_id: ActiveNovelIdQuery,
) -> CoreEntityResponse:
    payload = await image.read(MAX_WORLD_OBJECT_IMAGE_BYTES)
    if len(payload) >= MAX_WORLD_OBJECT_IMAGE_BYTES or await image.read(1):
        raise HTTPException(status_code=413, detail="图片必须小于 6MiB")
    try:
        return await _entity_image_service.upload(
            db,
            novel_id=novel_id,
            entity_id=entity_id,
            payload=payload,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/entities/{entity_id}/image")
async def get_entity_image(
    db: DbSession,
    entity_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
    variant: Literal["thumbnail", "full"] = Query(default="thumbnail"),
    expected_version: uuid.UUID | None = Query(default=None),
) -> Response:
    payload = await _entity_image_service.get(
        db,
        novel_id=novel_id,
        entity_id=entity_id,
        variant=variant,
        expected_version=str(expected_version) if expected_version else None,
    )
    return Response(
        payload,
        media_type="image/webp",
        headers={"Cache-Control": "private, no-store"},
    )


@router.get(
    "/entities/{entity_id}/image-generation",
    response_model=WorldObjectImageGenerationInfo,
)
async def get_entity_image_generation(
    db: DbSession,
    entity_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
) -> WorldObjectImageGenerationInfo:
    return await _entity_image_generation_service.generation_info(
        db,
        novel_id=novel_id,
        entity_id=entity_id,
        owner_id=str(current_account_id()),
    )


@router.post(
    "/entities/{entity_id}/image-candidates",
    response_model=WorldObjectImageCandidateView,
    dependencies=[Depends(require_xhr_request)],
)
async def create_entity_image_candidate(
    db: DbSession,
    entity_id: str,
    data: WorldObjectImageCandidateCreate,
) -> WorldObjectImageCandidateView:
    await require_active_project(db, data.novel_id)
    return await _entity_image_generation_service.create_candidate(
        db,
        novel_id=data.novel_id,
        entity_id=entity_id,
        owner_id=str(current_account_id()),
        data=data,
    )


@router.get(
    "/image-candidates/{candidate_id}",
    response_model=WorldObjectImageCandidateView,
)
async def get_image_candidate(
    db: DbSession,
    candidate_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
) -> WorldObjectImageCandidateView:
    return await _entity_image_generation_service.get_candidate(
        db, novel_id=novel_id, candidate_id=candidate_id
    )


@router.get("/image-candidates/{candidate_id}/image")
async def get_image_candidate_image(
    db: DbSession,
    candidate_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
) -> Response:
    payload = await _entity_image_generation_service.get_candidate_image(
        db, novel_id=novel_id, candidate_id=candidate_id
    )
    return Response(
        payload,
        media_type="image/png",
        headers={"Cache-Control": "private, no-store"},
    )


@router.post(
    "/image-candidates/{candidate_id}/adopt",
    response_model=WorldObjectImageCandidateAdoptResponse,
    dependencies=[Depends(require_xhr_request)],
)
async def adopt_image_candidate(
    db: DbSession,
    candidate_id: str,
    data: WorldObjectImageCandidateAction,
) -> WorldObjectImageCandidateAdoptResponse:
    await require_active_project(db, data.novel_id)
    return await _entity_image_generation_service.adopt_candidate(
        db, novel_id=data.novel_id, candidate_id=candidate_id
    )


@router.post(
    "/image-candidates/{candidate_id}/discard",
    response_model=WorldObjectImageCandidateView,
    dependencies=[Depends(require_xhr_request)],
)
async def discard_image_candidate(
    db: DbSession,
    candidate_id: str,
    data: WorldObjectImageCandidateAction,
) -> WorldObjectImageCandidateView:
    await require_active_project(db, data.novel_id)
    return await _entity_image_generation_service.discard_candidate(
        db, novel_id=data.novel_id, candidate_id=candidate_id
    )


@router.put("/entities/{entity_id}", response_model=CoreEntityResponse)
async def update_entity(
    db: DbSession,
    entity_id: str,
    data: CoreEntityUpdate,
    *,
    novel_id: ActiveNovelIdQuery,
) -> CoreEntityResponse:
    return await _entity_service.update(
        db,
        entity_id,
        data,
        novel_id=novel_id,
        expected_updated_at=data.expected_updated_at,
        require_edit_baseline=True,
    )


@router.delete("/entities/{entity_id}", status_code=204)
async def delete_entity(
    db: DbSession,
    entity_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
) -> None:
    await _entity_service.delete(db, entity_id, novel_id=novel_id)


@router.post("/entities/{candidate_id}/merge", response_model=EntityMergeResponse)
async def merge_entity(
    db: DbSession,
    candidate_id: str,
    data: EntityMergeRequest,
    *,
    novel_id: ActiveNovelIdQuery,
) -> EntityMergeResponse:
    result = await _dedup_service.merge_candidate_into_entity(
        db,
        novel_id,
        candidate_id,
        data.target_entity_id,
    )
    affected_ids = [result.candidate_entity_id, result.target_entity_id]
    return EntityMergeResponse(
        target_entity_id=result.target_entity_id,
        candidate_entity_id=result.candidate_entity_id,
        affected_ids=affected_ids,
        merged_ids=[result.candidate_entity_id],
    )


@router.post("/entities/{candidate_id}/resolve-as-alias")
async def resolve_entity_as_alias(
    db: DbSession,
    candidate_id: str,
    data: EntityResolveAsAliasRequest,
    *,
    novel_id: ActiveNovelIdQuery,
) -> dict:
    return await _alias_service.resolve_candidate_as_alias(
        db,
        novel_id,
        candidate_id,
        target_entity_id=data.target_entity_id,
        alias=data.alias,
        alias_type=data.alias_type,
        alias_kind=data.alias_kind,
    )


@router.post(
    "/entities/fusion-suggestions",
    response_model=EntityFusionSuggestionResponse,
    status_code=201,
)
async def create_entity_fusion_suggestions(
    db: DbSession,
    data: EntityFusionSuggestionRequest,
) -> EntityFusionSuggestionResponse:
    await require_active_project(db, data.novel_id)
    if not data.context_confirmation_id:
        raise HTTPException(status_code=400, detail="context_confirmation_id is required")
    payload = data.model_dump(mode="json", exclude_none=True, exclude={"operation_id"})
    try:
        existing = await get_operation_task(
            db,
            operation_id=str(data.operation_id) if data.operation_id else None,
            task_type="world_entity_fusion_suggestions",
            novel_id=data.novel_id,
            request_payload=payload,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if existing is not None:
        return EntityFusionSuggestionResponse(
            task_id=existing.task_id,
            status=existing.status,
        )
    try:
        await require_fresh_confirmation(
            db,
            novel_id=data.novel_id,
            action="world.entity_fusion.suggest",
            confirmation_id=data.context_confirmation_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        receipt = await enqueue_task_with_optional_operation(
            db,
            operation_id=str(data.operation_id) if data.operation_id else None,
            task_type="world_entity_fusion_suggestions",
            novel_id=data.novel_id,
            request_payload=payload,
            meta=payload,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not receipt.reused:
        await attach_result_ref(
            db,
            novel_id=data.novel_id,
            confirmation_id=data.context_confirmation_id,
            result_type="task",
            result_id=receipt.task_id,
            status="running",
        )
    await db.flush()
    return EntityFusionSuggestionResponse(
        task_id=receipt.task_id,
        status=receipt.status,
    )


@router.post(
    "/entities/fusion-suggestions/apply",
    response_model=EntityFusionApplyResponse,
)
async def apply_entity_fusion_suggestions(
    db: DbSession,
    data: EntityFusionApplyRequest,
) -> EntityFusionApplyResponse:
    await require_active_project(db, data.novel_id)
    result = await _fusion_service.apply(
        db,
        novel_id=data.novel_id,
        confirmed=data.confirmed,
        suggestions=data.suggestions,
    )
    return EntityFusionApplyResponse(**result)


@router.post(
    "/entities/{entity_id}/promote",
    response_model=EntityPromoteResponse,
)
async def promote_entity(
    db: DbSession,
    entity_id: str,
    data: EntityPromoteRequest = EntityPromoteRequest(),
    *,
    novel_id: ActiveNovelIdQuery,
) -> EntityPromoteResponse:
    """采用待处理实体；原始状态字段保持兼容。"""
    return await _entity_service.promote(
        db,
        entity_id,
        data,
        novel_id=novel_id,
    )


@router.get("/entities/{entity_id}/relations", response_model=EntityRelationListResponse)
async def get_entity_relations(
    db: DbSession,
    entity_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
) -> EntityRelationListResponse:
    """获取实体的关联关系"""
    return await _relation_service.get_by_entity(db, novel_id, entity_id)
