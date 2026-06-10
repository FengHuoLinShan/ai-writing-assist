from __future__ import annotations

from fastapi import APIRouter, Query
from fastapi import status as http_status

from core.dependencies import DbSession
from modules.outline.schemas import (
    OutlineArcCreate,
    OutlineArcListResponse,
    OutlineArcResponse,
    OutlineArcUpdate,
    PlotThreadCreate,
    PlotThreadListResponse,
    PlotThreadResponse,
    PlotThreadUpdate,
)
from modules.outline.services import (
    OutlineArcService,
    PlotStructureGenerator,
    PlotThreadService,
)
from shared.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE

router = APIRouter(prefix="/api/outline", tags=["outline"])

_thread_service = PlotThreadService()
_arc_service = OutlineArcService()
_generator = PlotStructureGenerator()


# ============================================================
# PlotThreads
# ============================================================

@router.post("/threads", response_model=PlotThreadResponse, status_code=http_status.HTTP_201_CREATED)
async def api_create_thread(
    data: PlotThreadCreate,
    db: DbSession,
    novel_id: str = Query(..., description="项目 ID"),
):
    return await _thread_service.create(db, novel_id, data)


@router.get("/threads", response_model=PlotThreadListResponse)
async def api_list_threads(
    db: DbSession,
    novel_id: str = Query(..., description="项目 ID"),
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
):
    return await _thread_service.list_with_response(db, novel_id, skip=skip, limit=limit)


@router.get("/threads/{thread_id}", response_model=PlotThreadResponse)
async def api_get_thread(
    thread_id: str,
    db: DbSession,
    novel_id: str = Query(..., description="项目 ID"),
):
    return await _thread_service.get(db, thread_id, novel_id=novel_id)


@router.patch("/threads/{thread_id}", response_model=PlotThreadResponse)
async def api_update_thread(
    thread_id: str,
    data: PlotThreadUpdate,
    db: DbSession,
    novel_id: str = Query(..., description="项目 ID"),
):
    return await _thread_service.update(db, thread_id, data, novel_id=novel_id)


@router.delete("/threads/{thread_id}", status_code=http_status.HTTP_204_NO_CONTENT)
async def api_delete_thread(
    thread_id: str,
    db: DbSession,
    novel_id: str = Query(..., description="项目 ID"),
):
    await _thread_service.delete(db, thread_id, novel_id=novel_id)


# ============================================================
# OutlineArcs
# ============================================================

@router.post("/arcs", response_model=OutlineArcResponse, status_code=http_status.HTTP_201_CREATED)
async def api_create_arc(
    data: OutlineArcCreate,
    db: DbSession,
    novel_id: str = Query(..., description="项目 ID"),
):
    return await _arc_service.create(db, novel_id, data)


@router.get("/arcs", response_model=OutlineArcListResponse)
async def api_list_arcs(
    db: DbSession,
    novel_id: str = Query(..., description="项目 ID"),
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
):
    return await _arc_service.list_with_response(db, novel_id, skip=skip, limit=limit)


@router.get("/arcs/{arc_id}", response_model=OutlineArcResponse)
async def api_get_arc(
    arc_id: str,
    db: DbSession,
    novel_id: str = Query(..., description="项目 ID"),
):
    return await _arc_service.get(db, arc_id, novel_id=novel_id)


@router.patch("/arcs/{arc_id}", response_model=OutlineArcResponse)
async def api_update_arc(
    arc_id: str,
    data: OutlineArcUpdate,
    db: DbSession,
    novel_id: str = Query(..., description="项目 ID"),
):
    return await _arc_service.update(db, arc_id, data, novel_id=novel_id)


@router.delete("/arcs/{arc_id}", status_code=http_status.HTTP_204_NO_CONTENT)
async def api_delete_arc(
    arc_id: str,
    db: DbSession,
    novel_id: str = Query(..., description="项目 ID"),
):
    await _arc_service.delete(db, arc_id, novel_id=novel_id)


# ============================================================
# AI Generation
# ============================================================

@router.post("/generate", status_code=http_status.HTTP_201_CREATED)
async def api_generate_plot_structure(
    db: DbSession,
    novel_id: str = Query(..., description="项目 ID"),
    start_chapter: int = Query(1, ge=1, description="起始章节"),
    end_chapter: int = Query(10, ge=1, description="结束章节"),
):
    result = await _generator.generate(db, novel_id, start_chapter, end_chapter)
    return result
