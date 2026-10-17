"""Author-only HTTP endpoints for deterministic map auto drafts."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from core.dependencies import DbSession
from modules.project.facade import require_active_project
from modules.world.map_auto_draft_schemas import (
    MapAutoDraftBuildRequest,
    MapAutoDraftBuildResult,
    MapAutoDraftListResponse,
    MapAutoDraftRedoRequest,
    MapAutoDraftResumeRequest,
    MapAutoDraftTrayPlacementPreview,
    MapAutoDraftTrayPlacementPreviewRequest,
    MapAutoDraftTrayPlacementRequest,
    MapAutoDraftTrayPlacementResponse,
)
from modules.world.map_auto_draft_service import (
    build_map_auto_drafts,
    list_map_auto_drafts,
    place_map_auto_draft_tray_item,
    preview_map_auto_draft_tray_placement,
    redo_map_auto_drafts,
    resume_map_auto_drafts,
)

router = APIRouter(tags=["world-map-atlas-auto-drafts"])


async def _require_active_novel_id(db: DbSession, novel_id: UUID) -> str:
    await require_active_project(db, str(novel_id))
    return str(novel_id)


ActiveNovelId = Annotated[str, Depends(_require_active_novel_id)]


@router.get("/{novel_id}/auto-drafts", response_model=MapAutoDraftListResponse)
async def get_map_auto_drafts(
    db: DbSession,
    novel_id: ActiveNovelId,
    node_id: UUID | None = None,
    revision_id: UUID | None = None,
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    return await list_map_auto_drafts(
        db,
        novel_id,
        node_id=str(node_id) if node_id else None,
        revision_id=str(revision_id) if revision_id else None,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/{novel_id}/auto-drafts/build",
    response_model=MapAutoDraftBuildResult,
    status_code=202,
)
async def build_auto_drafts(
    db: DbSession, novel_id: ActiveNovelId, data: MapAutoDraftBuildRequest
):
    return await build_map_auto_drafts(db, novel_id, data)


@router.post(
    "/{novel_id}/auto-drafts/{batch_id}/resume",
    response_model=MapAutoDraftBuildResult,
)
async def resume_auto_drafts(
    db: DbSession,
    novel_id: ActiveNovelId,
    batch_id: UUID,
    data: MapAutoDraftResumeRequest,
):
    return await resume_map_auto_drafts(db, novel_id, str(batch_id), data)


@router.post(
    "/{novel_id}/auto-drafts/{batch_id}/redo",
    response_model=MapAutoDraftBuildResult,
    status_code=202,
)
async def redo_auto_drafts(
    db: DbSession,
    novel_id: ActiveNovelId,
    batch_id: UUID,
    data: MapAutoDraftRedoRequest,
):
    return await redo_map_auto_drafts(db, novel_id, str(batch_id), data)


@router.post(
    "/{novel_id}/auto-drafts/{batch_id}/nodes/{node_id}/revisions/{revision_id}"
    "/tray/{item_id}/preview",
    response_model=MapAutoDraftTrayPlacementPreview,
)
async def preview_auto_draft_tray_placement(
    db: DbSession,
    novel_id: ActiveNovelId,
    batch_id: UUID,
    node_id: UUID,
    revision_id: UUID,
    item_id: UUID,
    data: MapAutoDraftTrayPlacementPreviewRequest,
):
    return await preview_map_auto_draft_tray_placement(
        db,
        novel_id,
        str(batch_id),
        str(node_id),
        str(revision_id),
        str(item_id),
        data,
    )


@router.post(
    "/{novel_id}/auto-drafts/{batch_id}/nodes/{node_id}/revisions/{revision_id}"
    "/tray/{item_id}/place",
    response_model=MapAutoDraftTrayPlacementResponse,
)
async def place_auto_draft_tray_item(
    db: DbSession,
    novel_id: ActiveNovelId,
    batch_id: UUID,
    node_id: UUID,
    revision_id: UUID,
    item_id: UUID,
    data: MapAutoDraftTrayPlacementRequest,
):
    return await place_map_auto_draft_tray_item(
        db,
        novel_id,
        str(batch_id),
        str(node_id),
        str(revision_id),
        str(item_id),
        data,
    )


__all__ = ["router"]
