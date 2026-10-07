"""世界书校验与影响预览路由。"""

from __future__ import annotations

from typing import Literal

from fastapi import HTTPException, Query

from core.api_params import NovelIdQuery
from core.dependencies import DbSession
from modules.evidence.facade import attach_result_ref, require_fresh_confirmation
from modules.project.facade import require_active_project
from modules.project.facade import (
    require_active_project_exclusive as _require_active_project_exclusive,
)
from modules.world.api._shared import (
    ActiveNovelIdQuery,
    _world_impact_service,
    _world_validation_service,
    router,
)
from modules.world.schemas import (
    WorldBiblePageDraftResponse,
    WorldBiblePageResponse,
    WorldImpactPreviewResponse,
    WorldImpactSourceReadRequest,
    WorldImpactSourceReadResponse,
    WorldValidationFindingsPage,
    WorldValidationPolicyDraftUpsert,
    WorldValidationPolicyStatus,
    WorldValidationReviewListResponse,
    WorldValidationReviewRequest,
    WorldValidationRunContinueRequest,
    WorldValidationRunCreate,
    WorldValidationRunListResponse,
    WorldValidationRunResponse,
    WorldValidationWarningAcceptRequest,
)


@router.get(
    "/bible/validation-policy",
    response_model=WorldValidationPolicyStatus,
)
async def get_world_validation_policy_status(
    db: DbSession,
    *,
    novel_id: ActiveNovelIdQuery,
) -> WorldValidationPolicyStatus:
    return await _world_validation_service.policy_status(db, novel_id)


@router.post(
    "/bible/validation-policy/activate",
    response_model=WorldBiblePageResponse,
    status_code=201,
)
async def activate_world_validation_policy(
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
) -> WorldBiblePageResponse:
    await _require_active_project_exclusive(db, novel_id)
    return await _world_validation_service.activate_builtin_policy(db, novel_id)


@router.post(
    "/bible/validation-runs",
    response_model=WorldValidationRunResponse,
    status_code=202,
)
async def create_world_validation_run(
    db: DbSession,
    data: WorldValidationRunCreate,
) -> WorldValidationRunResponse:
    await _require_active_project_exclusive(db, data.novel_id)
    policy = await _world_validation_service.policy_status(db, data.novel_id)
    if policy.semantic_enabled:
        if not data.context_confirmation_id:
            raise HTTPException(
                status_code=400,
                detail="context_confirmation_id is required",
            )
        try:
            await require_fresh_confirmation(
                db,
                novel_id=data.novel_id,
                action="world.validation.semantic",
                confirmation_id=data.context_confirmation_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        result = await _world_validation_service.create_run(db, data)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if data.context_confirmation_id and result.task_id:
        await attach_result_ref(
            db,
            novel_id=data.novel_id,
            confirmation_id=data.context_confirmation_id,
            result_type="task",
            result_id=result.task_id,
            status="running",
        )
    return result


@router.get(
    "/bible/validation-runs",
    response_model=WorldValidationRunListResponse,
)
async def list_world_validation_runs(
    db: DbSession,
    *,
    novel_id: ActiveNovelIdQuery,
    limit: int = Query(default=10, ge=1, le=20),
) -> WorldValidationRunListResponse:
    return await _world_validation_service.list_runs(db, novel_id, limit=limit)


@router.get(
    "/bible/validation-runs/latest",
    response_model=WorldValidationRunResponse | None,
)
async def get_latest_world_validation_run(
    db: DbSession,
    *,
    novel_id: ActiveNovelIdQuery,
    scope: Literal["targeted", "full"] | None = Query(default=None),
    target_type: (
        Literal["world_bible_draft", "world_adoption_package", "semantic_gap"] | None
    ) = Query(default=None),
    target_id: str | None = Query(default=None),
) -> WorldValidationRunResponse | None:
    return await _world_validation_service.latest(
        db,
        novel_id,
        scope=scope,
        target_type=target_type,
        target_id=target_id,
    )


@router.get(
    "/bible/validation-runs/{run_id}",
    response_model=WorldValidationRunResponse,
)
async def get_world_validation_run(
    db: DbSession,
    run_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
) -> WorldValidationRunResponse:
    return await _world_validation_service.get(db, novel_id, run_id)


@router.post(
    "/bible/validation-runs/{run_id}/accept-warnings",
    response_model=WorldValidationRunResponse,
)
async def accept_world_validation_warnings(
    db: DbSession,
    run_id: str,
    data: WorldValidationWarningAcceptRequest,
    *,
    novel_id: ActiveNovelIdQuery,
) -> WorldValidationRunResponse:
    return await _world_validation_service.accept_warnings(
        db,
        novel_id,
        run_id,
        data,
    )


@router.get(
    "/bible/validation-runs/{run_id}/findings",
    response_model=WorldValidationFindingsPage,
)
async def list_world_validation_findings(
    db: DbSession,
    run_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
    severity: Literal["error", "warning"] | None = Query(default=None),
    action: str | None = Query(default=None, max_length=64),
    category: str | None = Query(default=None, max_length=64),
    page: int = Query(default=1, ge=1, le=10_000),
    page_size: int = Query(default=20, ge=1, le=100),
) -> WorldValidationFindingsPage:
    return await _world_validation_service.findings_page(
        db,
        novel_id,
        run_id,
        severity=severity,
        action=action,
        category=category,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/bible/validation-runs/{run_id}/review-items",
    response_model=WorldValidationReviewListResponse,
)
async def list_world_validation_review_items(
    db: DbSession,
    run_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
) -> WorldValidationReviewListResponse:
    return await _world_validation_service.list_review_items(db, novel_id, run_id)


@router.post(
    "/bible/validation-runs/{run_id}/review-items",
    response_model=WorldValidationRunResponse,
)
async def create_world_validation_review_items(
    db: DbSession,
    run_id: str,
    data: WorldValidationReviewRequest,
    *,
    novel_id: ActiveNovelIdQuery,
) -> WorldValidationRunResponse:
    await _require_active_project_exclusive(db, novel_id)
    return await _world_validation_service.review_items(db, novel_id, run_id, data)


@router.post(
    "/bible/validation-runs/{run_id}/continue",
    response_model=WorldValidationRunResponse,
    status_code=202,
)
async def continue_world_validation_run(
    db: DbSession,
    run_id: str,
    data: WorldValidationRunContinueRequest,
    *,
    novel_id: NovelIdQuery,
) -> WorldValidationRunResponse:
    await _require_active_project_exclusive(db, novel_id)
    policy = await _world_validation_service.policy_status(db, novel_id)
    if policy.semantic_enabled:
        if not data.context_confirmation_id:
            raise HTTPException(
                status_code=400,
                detail="context_confirmation_id is required",
            )
        try:
            await require_fresh_confirmation(
                db,
                novel_id=novel_id,
                action="world.validation.semantic",
                confirmation_id=data.context_confirmation_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    result = await _world_validation_service.continue_run(
        db,
        novel_id,
        run_id,
        context_confirmation_id=data.context_confirmation_id,
    )
    if data.context_confirmation_id and result.task_id:
        await attach_result_ref(
            db,
            novel_id=novel_id,
            confirmation_id=data.context_confirmation_id,
            result_type="task",
            result_id=result.task_id,
            status="running",
        )
    return result


@router.post(
    "/bible/validation-policy/draft",
    response_model=WorldBiblePageDraftResponse,
)
async def save_world_validation_policy_draft(
    db: DbSession,
    data: WorldValidationPolicyDraftUpsert,
    *,
    novel_id: NovelIdQuery,
) -> WorldBiblePageDraftResponse:
    await _require_active_project_exclusive(db, novel_id)
    return await _world_validation_service.save_policy_draft(db, novel_id, data)


@router.post("/impact-preview/source", response_model=WorldImpactSourceReadResponse)
async def read_world_impact_source(db: DbSession, data: WorldImpactSourceReadRequest):
    await require_active_project(db, data.novel_id)
    return await _world_impact_service.read_source(db, data)


@router.get(
    "/bible/validation-runs/{run_id}/source", response_model=WorldImpactSourceReadResponse
)
async def read_world_validation_source(
    db: DbSession,
    run_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
    source_key: str = Query(..., max_length=256),
):
    return await _world_validation_service.read_review_source(
        db, novel_id, run_id, source_key
    )


@router.get("/impact-preview", response_model=WorldImpactPreviewResponse)
async def preview_world_impact(
    db: DbSession,
    *,
    novel_id: ActiveNovelIdQuery,
    target_type: Literal["world_bible_page", "core_entity", "entity_relation"] = Query(),
    target_id: str = Query(),
) -> WorldImpactPreviewResponse:
    return await _world_impact_service.preview(
        db,
        novel_id,
        target_type=target_type,
        target_id=target_id,
    )
