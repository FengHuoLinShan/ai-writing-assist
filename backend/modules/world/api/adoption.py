"""核心/设计检查点与采用包路由。"""

from __future__ import annotations

from fastapi import HTTPException

from core.api_params import NovelIdQuery
from core.dependencies import DbSession
from core.errors import ConflictError
from modules.project.facade import require_active_project
from modules.project.facade import (
    require_active_project_exclusive as _require_active_project_exclusive,
)
from modules.world.api._shared import (
    ActiveNovelIdQuery,
    _adoption_package_service,
    router,
)
from modules.world.schemas import (
    CreationSuggestionResponse,
    WorldAdoptionPackageApplyRequest,
    WorldAdoptionPackagePreviewResponse,
    WorldAdoptionPackageSaveRequest,
    WorldCoreCheckpointSaveRequest,
    WorldDesignCheckpointSaveRequest,
    WorldDesignRevisionRequest,
)


@router.post(
    "/core-checkpoints",
    response_model=CreationSuggestionResponse,
    status_code=201,
)
async def save_world_core_checkpoint(
    db: DbSession,
    data: WorldCoreCheckpointSaveRequest,
) -> CreationSuggestionResponse:
    await require_active_project(db, data.novel_id)
    return await _adoption_package_service.save_checkpoint(db, data)


@router.post(
    "/design-checkpoints",
    response_model=CreationSuggestionResponse,
    status_code=201,
)
async def save_world_design_checkpoint(
    db: DbSession,
    data: WorldDesignCheckpointSaveRequest,
) -> CreationSuggestionResponse:
    await require_active_project(db, data.novel_id)
    return await _adoption_package_service.save_design_checkpoint(db, data)


@router.post(
    "/design-checkpoints/revisions",
    response_model=CreationSuggestionResponse,
    status_code=201,
)
async def revise_world_design_checkpoint(db: DbSession, data: WorldDesignRevisionRequest):
    await require_active_project(db, data.novel_id)
    return await _adoption_package_service.revise_design_checkpoint(db, data)


@router.get(
    "/adoption-packages/{suggestion_id}", response_model=CreationSuggestionResponse
)
async def get_world_adoption_artifact(
    db: DbSession,
    suggestion_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
) -> CreationSuggestionResponse:
    return await _adoption_package_service.get(db, novel_id, suggestion_id)


@router.post(
    "/adoption-packages",
    response_model=CreationSuggestionResponse,
    status_code=201,
)
async def save_world_adoption_package(
    db: DbSession,
    data: WorldAdoptionPackageSaveRequest,
) -> CreationSuggestionResponse:
    await require_active_project(db, data.novel_id)
    return await _adoption_package_service.save(db, data)


@router.get(
    "/adoption-packages/{suggestion_id}/preview",
    response_model=WorldAdoptionPackagePreviewResponse,
)
async def preview_world_adoption_package(
    db: DbSession,
    suggestion_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
) -> WorldAdoptionPackagePreviewResponse:
    return await _adoption_package_service.preview(db, novel_id, suggestion_id)


@router.post(
    "/adoption-packages/{suggestion_id}/apply",
    response_model=CreationSuggestionResponse,
)
async def apply_world_adoption_package(
    db: DbSession,
    suggestion_id: str,
    data: WorldAdoptionPackageApplyRequest,
    *,
    novel_id: NovelIdQuery,
) -> CreationSuggestionResponse:
    await _require_active_project_exclusive(db, novel_id)
    try:
        async with db.begin_nested():
            return await _adoption_package_service.apply(
                db, novel_id, suggestion_id, data
            )
    except ConflictError as exc:
        if exc.code == "required_validation":
            raise
        raise HTTPException(status_code=409, detail=str(exc)) from exc
