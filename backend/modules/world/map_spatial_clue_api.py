"""Author-only review endpoints for map spatial clue candidates."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from core.dependencies import DbSession
from modules.account.facade import current_account_id
from modules.project.facade import require_active_project
from modules.world.map_spatial_clue_schemas import (
    MapSpatialClueDecisionRequest,
    MapSpatialClueListResponse,
    MapSpatialClueResponse,
    MapSpatialClueStatus,
)
from modules.world.map_spatial_clue_service import (
    list_spatial_clues,
    review_spatial_clue,
)

router = APIRouter(tags=["world-map-spatial-clues"])


async def _require_active_novel_id(db: DbSession, novel_id: str) -> str:
    await require_active_project(db, novel_id)
    return novel_id


ActiveNovelId = Annotated[str, Depends(_require_active_novel_id)]


@router.get("/{novel_id}/spatial-clues", response_model=MapSpatialClueListResponse)
async def get_spatial_clues(
    db: DbSession,
    novel_id: ActiveNovelId,
    status: Annotated[list[MapSpatialClueStatus] | None, Query()] = None,
    scene_id: UUID | None = None,
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    return await list_spatial_clues(
        db,
        novel_id,
        statuses=status,
        scene_id=str(scene_id) if scene_id else None,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/{novel_id}/spatial-clues/{clue_id}/review",
    response_model=MapSpatialClueResponse,
    openapi_extra={
        "x-novelcraft-operation-exemption": (
            "This single-clue author review has a different input and CAS contract "
            "from the map.review_spatial_clues batch operation."
        )
    },
)
async def review_spatial_clue_endpoint(
    db: DbSession,
    novel_id: str,
    clue_id: UUID,
    data: MapSpatialClueDecisionRequest,
):
    return await review_spatial_clue(
        db, novel_id, str(clue_id), data, decided_by=str(current_account_id())
    )


__all__ = ["router"]
