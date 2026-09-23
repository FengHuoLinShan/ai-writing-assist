"""Project-owner routes for the explicitly enabled reading trial."""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from core.dependencies import DbSession
from modules.evolution import workflow
from modules.evolution.ownership import switch_project_engine
from modules.project.facade import (
    require_active_project,
    require_active_project_exclusive,
)


async def _guard_project(request: Request, db: DbSession, novel_id: UUID):
    if request.method == "GET":
        await require_active_project(db, str(novel_id))
    else:
        await require_active_project_exclusive(db, str(novel_id))


router = APIRouter(
    prefix="/api/evolution", tags=["evolution"], dependencies=[Depends(_guard_project)]
)


class EngineSwitch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    engine: Literal["evolution", "read_only"]
    expected_epoch: int = Field(ge=1)
    stop_active: bool = False
    authorization_confirmed: Literal[True]


@router.get("/reading")
async def reading_status(db: DbSession, novel_id: UUID):
    return await workflow.reading_status(db, str(novel_id))


@router.post("/engine")
async def change_engine(db: DbSession, novel_id: UUID, data: EngineSwitch):
    return await switch_project_engine(
        db,
        str(novel_id),
        to_engine=data.engine,
        expected_epoch=data.expected_epoch,
        stop_active=data.stop_active,
    )


@router.post("/reading/preview")
async def preview_reading(db: DbSession, novel_id: UUID, data: workflow.ReadingRequest):
    return await workflow.preview_reading(db, str(novel_id), data)


@router.post("/reading", status_code=201)
async def start_reading(db: DbSession, novel_id: UUID, data: workflow.ReadingStart):
    return await workflow.start_reading(db, str(novel_id), data)


@router.post("/reading/{run_key}/resume")
async def resume_reading(db: DbSession, novel_id: UUID, run_key: str):
    return await workflow.resume_reading(db, str(novel_id), run_key)


@router.get("/reading/{run_key}/targets")
async def reading_targets(
    db: DbSession,
    novel_id: UUID,
    run_key: str,
    kind: Literal["entity", "observation"],
    query: str = Query(default="", max_length=200),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
):
    return await workflow.reading_targets(
        db, str(novel_id), run_key, kind=kind, query=query, offset=offset, limit=limit
    )


@router.get("/reading/{run_key}/proposals")
async def reading_proposals(
    db: DbSession,
    novel_id: UUID,
    run_key: str,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=50),
):
    return await workflow.reading_proposals(
        db, str(novel_id), run_key, offset=offset, limit=limit
    )
