"""Author HTTP API for confirmed character arc plans and cutoff comparisons."""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException
from fastapi import status as http_status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError

from core.api_params import NovelIdQuery
from core.dependencies import DbSession
from core.errors import ConflictError, NotFoundError, ValidationError
from modules.project.facade import require_active_project

from . import facade
from .operations import OPERATIONS_SPEC
from .schemas import (
    ArchiveArcPlanInput,
    ArcPlanPreviewResponse,
    ArcPlanWriteInput,
    CharacterArcComparisonResponse,
    ConfirmArcPlanInput,
    RestoreArcPlanInput,
    SceneCharacterOptionsResponse,
)
from .service import _owned_project, _trace

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/story/character-arcs", tags=["story-character-arcs"])


class PlanHistoryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    character_id: UUID
    character_name: str
    deleted: bool
    current_version: int | None = None
    items: list[dict] = Field(default_factory=list, max_length=50)


def _error(exc: Exception) -> HTTPException:
    if isinstance(exc, ConflictError):
        return HTTPException(status_code=http_status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, NotFoundError):
        return HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail=str(exc))
    if isinstance(exc, (ValidationError, ValueError)):
        return HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST, detail=str(exc)
        )
    if isinstance(exc, IntegrityError):
        return HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail="人物弧计划版本已变化，请重新读取后再试。",
        )
    logger.exception("story character arc api operation failed")
    return HTTPException(
        status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="服务器内部错误，请稍后重试。",
    )


async def _active_author(db, novel_id: str):
    await require_active_project(db, novel_id, allow_demo_readonly=False)
    return await _owned_project(db, novel_id)


def _operation_fingerprint(operation_id: str, preview: dict) -> str | None:
    if operation_id == "story.character_arc_plan.save":
        return preview.get("preview_fingerprint")
    return preview.get("fingerprint")


async def _preview_operation(db, novel_id: str, op_id: str, data):
    project = await _active_author(db, novel_id)
    spec = OPERATIONS_SPEC[op_id]
    args = spec["schema"].model_validate(data.model_dump(mode="json"))
    preview = await spec["prepare"](db, novel_id, args, context=None)
    value = preview.model_dump(mode="json") if hasattr(preview, "model_dump") else preview
    await _trace(
        db,
        novel_id,
        project.owner_id,
        args.operation_id,
        op_id,
        "previewed",
        args.model_dump(mode="json"),
        result={"type": "story.character_arc_plan_preview", "id": str(args.character_id)},
    )
    return value


async def _confirm_operation(db, novel_id: str, op_id: str, data):
    await _active_author(db, novel_id)
    spec = OPERATIONS_SPEC[op_id]
    args = spec["schema"].model_validate(data.model_dump(mode="json"))
    if not args.preview_fingerprint:
        raise ConflictError("确认写入前需要提交预览指纹", code="PREVIEW_REQUIRED")
    preview = await spec["prepare"](db, novel_id, args, context=None)
    value = preview.model_dump(mode="json") if hasattr(preview, "model_dump") else preview
    if _operation_fingerprint(op_id, value) != args.preview_fingerprint:
        raise ConflictError("人物弧计划预览已变化，请重新核对", code="PREVIEW_STALE")
    result = await spec["apply"](db, novel_id, args, value, context=None)
    return result.model_dump(mode="json") if hasattr(result, "model_dump") else result


@router.get("/scenes/{scene_id}/characters", response_model=SceneCharacterOptionsResponse)
async def api_scene_characters(
    scene_id: str,
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
) -> SceneCharacterOptionsResponse:
    try:
        await _active_author(db, novel_id)
        return await facade.scene_character_options(db, novel_id, scene_id)
    except Exception as exc:
        raise _error(exc) from exc


@router.get(
    "/scenes/{scene_id}/characters/{character_id}/comparison",
    response_model=CharacterArcComparisonResponse,
)
async def api_compare_character_arc(
    scene_id: str,
    character_id: str,
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
) -> CharacterArcComparisonResponse:
    try:
        await _active_author(db, novel_id)
        return await facade.compare_character_arc(db, novel_id, scene_id, character_id)
    except Exception as exc:
        raise _error(exc) from exc


@router.get(
    "/scenes/{scene_id}/characters/{character_id}/history",
    response_model=PlanHistoryResponse,
)
async def api_character_arc_history(
    scene_id: str,
    character_id: str,
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
) -> PlanHistoryResponse:
    try:
        await _active_author(db, novel_id)
        return await facade.plan_history(db, novel_id, scene_id, character_id)
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/plans/preview", response_model=ArcPlanPreviewResponse)
async def api_preview_character_arc_plan(
    data: ArcPlanWriteInput,
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
) -> ArcPlanPreviewResponse:
    try:
        return ArcPlanPreviewResponse.model_validate(
            await _preview_operation(db, novel_id, "story.character_arc_plan.save", data)
        )
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/plans/confirm")
async def api_confirm_character_arc_plan(
    data: ConfirmArcPlanInput,
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
):
    try:
        return await _confirm_operation(
            db, novel_id, "story.character_arc_plan.save", data
        )
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/plans/restore/preview")
async def api_preview_restore_character_arc_plan(
    data: RestoreArcPlanInput,
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
):
    try:
        return await _preview_operation(
            db, novel_id, "story.character_arc_plan.restore", data
        )
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/plans/restore/confirm")
async def api_confirm_restore_character_arc_plan(
    data: RestoreArcPlanInput,
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
):
    try:
        return await _confirm_operation(
            db, novel_id, "story.character_arc_plan.restore", data
        )
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/plans/archive/preview")
async def api_preview_archive_character_arc_plan(
    data: ArchiveArcPlanInput,
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
):
    try:
        return await _preview_operation(
            db, novel_id, "story.character_arc_plan.archive", data
        )
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/plans/archive/confirm")
async def api_confirm_archive_character_arc_plan(
    data: ArchiveArcPlanInput,
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
):
    try:
        return await _confirm_operation(
            db, novel_id, "story.character_arc_plan.archive", data
        )
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/plans/unarchive/preview")
async def api_preview_unarchive_character_arc_plan(
    data: ArchiveArcPlanInput,
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
):
    try:
        return await _preview_operation(
            db, novel_id, "story.character_arc_plan.unarchive", data
        )
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/plans/unarchive/confirm")
async def api_confirm_unarchive_character_arc_plan(
    data: ArchiveArcPlanInput,
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
):
    try:
        return await _confirm_operation(
            db, novel_id, "story.character_arc_plan.unarchive", data
        )
    except Exception as exc:
        raise _error(exc) from exc
