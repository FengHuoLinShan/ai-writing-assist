"""创作建议队列与冲突队列路由。"""

from __future__ import annotations

from fastapi import HTTPException, Query

from core.dependencies import DbSession
from modules.world.api._shared import (
    ActiveNovelIdQuery,
    _conflict_queue_service,
    _suggestion_service,
    router,
)
from modules.world.schemas import (
    ConflictQueueListResponse,
    ConflictResolveRequest,
    CoreEntitySuggestionEditConfirmRequest,
    CreationSuggestionListResponse,
    CreationSuggestionResponse,
    EntityMergeRequest,
    EntityResolveAsAliasRequest,
    SuggestionDecisionResponse,
)
from modules.world.services.worldbuilding.worldbuilding_service import (
    SuggestionAlreadyProcessedError,
)


@router.get("/suggestions", response_model=CreationSuggestionListResponse)
async def list_world_suggestions(
    db: DbSession,
    *,
    novel_id: ActiveNovelIdQuery,
    source_module: str | None = Query(None),
    review_group: str | None = Query(None),
    risk_level: str | None = Query(None),
    status: str | None = Query(None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> CreationSuggestionListResponse:
    items, total = await _suggestion_service.list(
        db,
        novel_id,
        source_module=source_module,
        review_group=review_group,
        risk_level=risk_level,
        status=status,
        skip=skip,
        limit=limit,
    )
    return CreationSuggestionListResponse(items=items, total=total)


@router.get("/suggestions/{suggestion_id}", response_model=CreationSuggestionResponse)
async def get_world_suggestion(
    db: DbSession, suggestion_id: str, *, novel_id: ActiveNovelIdQuery
):
    return await _suggestion_service.get(db, novel_id, suggestion_id)


@router.post(
    "/suggestions/{suggestion_id}/confirm",
    response_model=SuggestionDecisionResponse,
)
async def confirm_world_suggestion(
    db: DbSession,
    suggestion_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
) -> SuggestionDecisionResponse:
    try:
        suggestion = await _suggestion_service.confirm(db, novel_id, suggestion_id)
    except SuggestionAlreadyProcessedError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "status": "already_processed",
                "suggestion_status": exc.status,
            },
        ) from exc
    return SuggestionDecisionResponse(
        status="accepted",
        suggestion_status=suggestion.status,
        result_ref_json=suggestion.result_ref_json,
    )


@router.post(
    "/suggestions/{suggestion_id}/edit-confirm",
    response_model=SuggestionDecisionResponse,
)
async def edit_and_confirm_world_suggestion(
    db: DbSession,
    suggestion_id: str,
    data: CoreEntitySuggestionEditConfirmRequest,
    *,
    novel_id: ActiveNovelIdQuery,
) -> SuggestionDecisionResponse:
    try:
        suggestion = await _suggestion_service.edit_and_confirm_core_entity(
            db,
            novel_id,
            suggestion_id,
            data,
        )
    except SuggestionAlreadyProcessedError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "status": "already_processed",
                "suggestion_status": exc.status,
            },
        ) from exc
    return SuggestionDecisionResponse(
        status="accepted",
        suggestion_status=suggestion.status,
        result_ref_json=suggestion.result_ref_json,
    )




@router.post(
    "/suggestions/{suggestion_id}/merge",
    response_model=SuggestionDecisionResponse,
)
async def merge_world_suggestion(
    db: DbSession,
    suggestion_id: str,
    data: EntityMergeRequest,
    *,
    novel_id: ActiveNovelIdQuery,
) -> SuggestionDecisionResponse:
    try:
        suggestion = await _suggestion_service.merge_core_entity(
            db,
            novel_id,
            suggestion_id,
            data,
        )
    except SuggestionAlreadyProcessedError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "status": "already_processed",
                "suggestion_status": exc.status,
            },
        ) from exc
    return SuggestionDecisionResponse(
        status="accepted",
        suggestion_status=suggestion.status,
        result_ref_json=suggestion.result_ref_json,
    )


@router.post(
    "/suggestions/{suggestion_id}/resolve-as-alias",
    response_model=SuggestionDecisionResponse,
)
async def resolve_world_suggestion_as_alias(
    db: DbSession,
    suggestion_id: str,
    data: EntityResolveAsAliasRequest,
    *,
    novel_id: ActiveNovelIdQuery,
) -> SuggestionDecisionResponse:
    try:
        suggestion = await _suggestion_service.resolve_core_entity_as_alias(
            db,
            novel_id,
            suggestion_id,
            data,
        )
    except SuggestionAlreadyProcessedError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "status": "already_processed",
                "suggestion_status": exc.status,
            },
        ) from exc
    return SuggestionDecisionResponse(
        status="accepted",
        suggestion_status=suggestion.status,
        result_ref_json=suggestion.result_ref_json,
    )


@router.post(
    "/suggestions/{suggestion_id}/reject",
    response_model=SuggestionDecisionResponse,
)
async def reject_world_suggestion(
    db: DbSession,
    suggestion_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
) -> SuggestionDecisionResponse:
    try:
        suggestion = await _suggestion_service.reject(db, novel_id, suggestion_id)
    except SuggestionAlreadyProcessedError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "status": "already_processed",
                "suggestion_status": exc.status,
            },
        ) from exc
    return SuggestionDecisionResponse(
        status="rejected",
        suggestion_status=suggestion.status,
        result_ref_json=suggestion.result_ref_json,
    )


@router.get("/conflicts", response_model=ConflictQueueListResponse)
async def list_world_conflicts(
    db: DbSession,
    *,
    novel_id: ActiveNovelIdQuery,
    status: str | None = Query(None),
    conflict_type: str | None = Query(None),
    skip: int = Query(default=0, ge=0, le=100_000),
    limit: int = Query(default=20, ge=1, le=100),
) -> ConflictQueueListResponse:
    items, total = await _conflict_queue_service.list(
        db,
        novel_id,
        status=status,
        conflict_type=conflict_type,
        skip=skip,
        limit=limit,
    )
    return ConflictQueueListResponse(items=items, total=total, skip=skip, limit=limit)


@router.post("/conflicts/{conflict_id}/resolve")
async def resolve_world_conflict(
    db: DbSession,
    conflict_id: str,
    data: ConflictResolveRequest,
    *,
    novel_id: ActiveNovelIdQuery,
) -> dict:
    item = await _conflict_queue_service.resolve(
        db,
        novel_id,
        conflict_id,
        status=data.status,
        resolution_json=data.resolution_json,
    )
    return {"status": item.status, "id": item.id}
