from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.outline.contracts import OutlineArcContract, PlotThreadContract
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
from modules.outline.services import OutlineArcService, PlotThreadService
from shared.constants import DEFAULT_PAGE_SIZE

_thread_service = PlotThreadService()
_arc_service = OutlineArcService()


# ============================================================
# PlotThread
# ============================================================

async def create_thread(
    db: AsyncSession, novel_id: str, data: PlotThreadCreate,
) -> PlotThreadResponse:
    return await _thread_service.create(db, novel_id, data)


async def get_thread(
    db: AsyncSession, thread_id: str, *, novel_id: str,
) -> PlotThreadResponse:
    return await _thread_service.get(db, thread_id, novel_id=novel_id)


async def list_threads(
    db: AsyncSession, novel_id: str,
    *, skip: int = 0, limit: int = DEFAULT_PAGE_SIZE,
) -> PlotThreadListResponse:
    items, total = await _thread_service.list(
        db, novel_id, skip=skip, limit=limit,
    )
    return PlotThreadListResponse(items=items, total=total)


async def update_thread(
    db: AsyncSession, thread_id: str, data: PlotThreadUpdate, *,
    novel_id: str,
) -> PlotThreadResponse:
    return await _thread_service.update(
        db, thread_id, data, novel_id=novel_id,
    )


async def delete_thread(
    db: AsyncSession, thread_id: str, *, novel_id: str,
) -> None:
    await _thread_service.delete(db, thread_id, novel_id=novel_id)


async def get_active_threads(
    db: AsyncSession, novel_id: str, chapter_index: int,
) -> list[PlotThreadContract]:
    return await _thread_service.get_active(db, novel_id, chapter_index)


# ============================================================
# OutlineArc
# ============================================================

async def create_arc(
    db: AsyncSession, novel_id: str, data: OutlineArcCreate,
) -> OutlineArcResponse:
    return await _arc_service.create(db, novel_id, data)


async def get_arc(
    db: AsyncSession, arc_id: str, *, novel_id: str,
) -> OutlineArcResponse:
    return await _arc_service.get(db, arc_id, novel_id=novel_id)


async def list_arcs(
    db: AsyncSession, novel_id: str,
    *, skip: int = 0, limit: int = DEFAULT_PAGE_SIZE,
) -> OutlineArcListResponse:
    items, total = await _arc_service.list(
        db, novel_id, skip=skip, limit=limit,
    )
    return OutlineArcListResponse(items=items, total=total)


async def update_arc(
    db: AsyncSession, arc_id: str, data: OutlineArcUpdate, *,
    novel_id: str,
) -> OutlineArcResponse:
    return await _arc_service.update(
        db, arc_id, data, novel_id=novel_id,
    )


async def delete_arc(
    db: AsyncSession, arc_id: str, *, novel_id: str,
) -> None:
    await _arc_service.delete(db, arc_id, novel_id=novel_id)


async def get_arc_by_chapter(
    db: AsyncSession, novel_id: str, chapter_index: int,
) -> OutlineArcContract | None:
    return await _arc_service.get_by_chapter(db, novel_id, chapter_index)


# ============================================================
# AI Generation
# ============================================================

async def generate_plot_structure(
    db: AsyncSession,
    novel_id: str,
    start_chapter: int,
    end_chapter: int,
) -> dict[str, Any]:
    from modules.outline.services import PlotStructureGenerator

    generator = PlotStructureGenerator()
    return await generator.generate(db, novel_id, start_chapter, end_chapter)
