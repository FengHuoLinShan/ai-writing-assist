"""
Outline API 路由

提供剧情线、篇章纲、章节卡、伏笔计划、揭示计划的 RESTful API。
API 层不写复杂业务逻辑，仅做参数校验和路由分发。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi import status as http_status

from core.dependencies import DbSession
from modules.outline.schemas import (
    ChapterCardContext,
    ChapterCardCreate,
    ChapterCardFromCandidateRequest,
    ChapterCardListResponse,
    ChapterCardResponse,
    ChapterCardUpdate,
    ForeshadowingPlanCreate,
    ForeshadowingPlanListResponse,
    ForeshadowingPlanResponse,
    ForeshadowingPlanUpdate,
    OutlineArcContext,
    OutlineArcCreate,
    OutlineArcListResponse,
    OutlineArcResponse,
    OutlineArcUpdate,
    PlotThreadContext,
    PlotThreadCreate,
    PlotThreadListResponse,
    PlotThreadResponse,
    PlotThreadUpdate,
    RevealPlanCreate,
    RevealPlanListResponse,
    RevealPlanResponse,
    RevealPlanUpdate,
)
from modules.outline.services import (
    ChapterCardService,
    ForeshadowingPlanService,
    OutlineArcService,
    PlotThreadService,
    RevealPlanService,
)
from shared.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE

router = APIRouter(prefix="/api/outline", tags=["outline"])

_thread_service = PlotThreadService()
_arc_service = OutlineArcService()
_chapter_service = ChapterCardService()
_foreshadowing_service = ForeshadowingPlanService()
_reveal_service = RevealPlanService()


# ============================================================
# PlotThread 路由
# ============================================================

@router.get("/threads", response_model=PlotThreadListResponse)
async def list_threads(
    db: DbSession,
    novel_id: str = Query(..., description="项目 ID"),
    thread_type: str | None = Query(None, description="剧情线类型过滤"),
    status: str | None = Query(None, description="状态过滤"),
    skip: int = Query(default=0, ge=0, description="跳过的记录数"),
    limit: int = Query(
        default=DEFAULT_PAGE_SIZE,
        ge=1,
        le=MAX_PAGE_SIZE,
        description="每页条数",
    ),
) -> PlotThreadListResponse:
    """获取剧情线列表"""
    return await _thread_service.list(
        db, novel_id,
        thread_type=thread_type,
        status=status,
        skip=skip,
        limit=limit,
    )


@router.post("/threads", response_model=PlotThreadResponse, status_code=201)
async def create_thread(
    db: DbSession,
    novel_id: str = Query(..., description="项目 ID"),
    data: PlotThreadCreate = ...,
) -> PlotThreadResponse:
    """创建剧情线"""
    return await _thread_service.create(db, novel_id, data)


@router.get(
    "/threads/active",
    response_model=list[PlotThreadContext],
)
async def get_active_threads(
    db: DbSession,
    novel_id: str = Query(..., description="项目 ID"),
    chapter_index: int | None = Query(None, ge=1, description="当前章节索引"),
    limit: int = Query(
        default=DEFAULT_PAGE_SIZE,
        ge=1,
        le=MAX_PAGE_SIZE,
        description="最大返回数量",
    ),
) -> list[PlotThreadContext]:
    """获取活跃剧情线"""
    return await _thread_service.get_active_threads(
        db, novel_id,
        chapter_index=chapter_index,
        limit=limit,
    )


@router.get("/threads/{thread_id}", response_model=PlotThreadResponse)
async def get_thread(
    db: DbSession,
    thread_id: str,
) -> PlotThreadResponse:
    """获取剧情线详情"""
    return await _thread_service.get(db, thread_id)


@router.put("/threads/{thread_id}", response_model=PlotThreadResponse)
async def update_thread(
    db: DbSession,
    thread_id: str,
    data: PlotThreadUpdate,
) -> PlotThreadResponse:
    """更新剧情线"""
    return await _thread_service.update(db, thread_id, data)


@router.delete("/threads/{thread_id}", status_code=204)
async def delete_thread(
    db: DbSession,
    thread_id: str,
) -> None:
    """删除剧情线"""
    await _thread_service.delete(db, thread_id)


# ============================================================
# OutlineArc 路由
# ============================================================

@router.get("/arcs", response_model=OutlineArcListResponse)
async def list_arcs(
    db: DbSession,
    novel_id: str = Query(..., description="项目 ID"),
    status: str | None = Query(None, description="状态过滤"),
    skip: int = Query(default=0, ge=0, description="跳过的记录数"),
    limit: int = Query(
        default=DEFAULT_PAGE_SIZE,
        ge=1,
        le=MAX_PAGE_SIZE,
        description="每页条数",
    ),
) -> OutlineArcListResponse:
    """获取篇章纲列表"""
    return await _arc_service.list(
        db, novel_id,
        status=status,
        skip=skip,
        limit=limit,
    )


@router.post("/arcs", response_model=OutlineArcResponse, status_code=201)
async def create_arc(
    db: DbSession,
    novel_id: str = Query(..., description="项目 ID"),
    data: OutlineArcCreate = ...,
) -> OutlineArcResponse:
    """创建篇章纲"""
    return await _arc_service.create(db, novel_id, data)


@router.get("/arcs/{arc_id}", response_model=OutlineArcResponse)
async def get_arc(
    db: DbSession,
    arc_id: str,
) -> OutlineArcResponse:
    """获取篇章纲详情"""
    return await _arc_service.get(db, arc_id)


@router.put("/arcs/{arc_id}", response_model=OutlineArcResponse)
async def update_arc(
    db: DbSession,
    arc_id: str,
    data: OutlineArcUpdate,
) -> OutlineArcResponse:
    """更新篇章纲"""
    return await _arc_service.update(db, arc_id, data)


@router.delete("/arcs/{arc_id}", status_code=204)
async def delete_arc(
    db: DbSession,
    arc_id: str,
) -> None:
    """删除篇章纲"""
    await _arc_service.delete(db, arc_id)


# ============================================================
# ChapterCard 路由
# ============================================================

@router.get("/chapters", response_model=ChapterCardListResponse)
async def list_chapters(
    db: DbSession,
    novel_id: str = Query(..., description="项目 ID"),
    arc_id: str | None = Query(None, description="所属篇章 ID"),
    status: str | None = Query(None, description="状态过滤"),
    skip: int = Query(default=0, ge=0, description="跳过的记录数"),
    limit: int = Query(
        default=DEFAULT_PAGE_SIZE,
        ge=1,
        le=MAX_PAGE_SIZE,
        description="每页条数",
    ),
) -> ChapterCardListResponse:
    """获取章节卡列表"""
    return await _chapter_service.list(
        db, novel_id,
        arc_id=arc_id,
        status=status,
        skip=skip,
        limit=limit,
    )


@router.post("/chapters", response_model=ChapterCardResponse, status_code=201)
async def create_chapter(
    db: DbSession,
    novel_id: str = Query(..., description="项目 ID"),
    data: ChapterCardCreate = ...,
) -> ChapterCardResponse:
    """创建章节卡"""
    return await _chapter_service.create(db, novel_id, data)


@router.get("/chapters/{card_id}", response_model=ChapterCardResponse)
async def get_chapter(
    db: DbSession,
    card_id: str,
) -> ChapterCardResponse:
    """获取章节卡详情"""
    return await _chapter_service.get(db, card_id)


@router.put("/chapters/{card_id}", response_model=ChapterCardResponse)
async def update_chapter(
    db: DbSession,
    card_id: str,
    data: ChapterCardUpdate,
) -> ChapterCardResponse:
    """更新章节卡"""
    return await _chapter_service.update(db, card_id, data)


@router.delete("/chapters/{card_id}", status_code=204)
async def delete_chapter(
    db: DbSession,
    card_id: str,
) -> None:
    """删除章节卡"""
    await _chapter_service.delete(db, card_id)


@router.get(
    "/chapters/by-index/{chapter_index}",
    response_model=ChapterCardResponse | None,
)
async def get_chapter_by_index(
    db: DbSession,
    novel_id: str = Query(..., description="项目 ID"),
    chapter_index: int = ...,
) -> ChapterCardResponse | None:
    """按章节索引获取章节卡"""
    return await _chapter_service.get_by_chapter_index(
        db, novel_id, chapter_index,
    )


@router.post(
    "/chapters/from-candidate",
    response_model=list[ChapterCardContext],
    status_code=201,
)
async def create_chapters_from_candidate(
    db: DbSession,
    request: ChapterCardFromCandidateRequest,
) -> list[ChapterCardContext]:
    """从候选批量创建章节卡"""
    return await _chapter_service.create_from_candidate(
        db, request.novel_id, request.cards,
    )


# ============================================================
# ForeshadowingPlan 路由
# ============================================================

@router.get("/foreshadowing", response_model=ForeshadowingPlanListResponse)
async def list_foreshadowing(
    db: DbSession,
    novel_id: str = Query(..., description="项目 ID"),
    status: str | None = Query(None, description="状态过滤"),
    skip: int = Query(default=0, ge=0, description="跳过的记录数"),
    limit: int = Query(
        default=DEFAULT_PAGE_SIZE,
        ge=1,
        le=MAX_PAGE_SIZE,
        description="每页条数",
    ),
) -> ForeshadowingPlanListResponse:
    """获取伏笔计划列表"""
    return await _foreshadowing_service.list(
        db, novel_id,
        status=status,
        skip=skip,
        limit=limit,
    )


@router.post(
    "/foreshadowing",
    response_model=ForeshadowingPlanResponse,
    status_code=201,
)
async def create_foreshadowing(
    db: DbSession,
    novel_id: str = Query(..., description="项目 ID"),
    data: ForeshadowingPlanCreate = ...,
) -> ForeshadowingPlanResponse:
    """创建伏笔计划"""
    return await _foreshadowing_service.create(db, novel_id, data)


@router.get(
    "/foreshadowing/{f_id}",
    response_model=ForeshadowingPlanResponse,
)
async def get_foreshadowing(
    db: DbSession,
    f_id: str,
) -> ForeshadowingPlanResponse:
    """获取伏笔计划详情"""
    return await _foreshadowing_service.get(db, f_id)


@router.put(
    "/foreshadowing/{f_id}",
    response_model=ForeshadowingPlanResponse,
)
async def update_foreshadowing(
    db: DbSession,
    f_id: str,
    data: ForeshadowingPlanUpdate,
) -> ForeshadowingPlanResponse:
    """更新伏笔计划"""
    return await _foreshadowing_service.update(db, f_id, data)


@router.delete("/foreshadowing/{f_id}", status_code=204)
async def delete_foreshadowing(
    db: DbSession,
    f_id: str,
) -> None:
    """删除伏笔计划"""
    await _foreshadowing_service.delete(db, f_id)


# ============================================================
# RevealPlan 路由
# ============================================================

@router.get("/reveals", response_model=RevealPlanListResponse)
async def list_reveals(
    db: DbSession,
    novel_id: str = Query(..., description="项目 ID"),
    target_type: str | None = Query(None, description="揭示目标类型过滤"),
    status: str | None = Query(None, description="状态过滤"),
    skip: int = Query(default=0, ge=0, description="跳过的记录数"),
    limit: int = Query(
        default=DEFAULT_PAGE_SIZE,
        ge=1,
        le=MAX_PAGE_SIZE,
        description="每页条数",
    ),
) -> RevealPlanListResponse:
    """获取揭示计划列表"""
    return await _reveal_service.list(
        db, novel_id,
        target_type=target_type,
        status=status,
        skip=skip,
        limit=limit,
    )


@router.post("/reveals", response_model=RevealPlanResponse, status_code=201)
async def create_reveal(
    db: DbSession,
    novel_id: str = Query(..., description="项目 ID"),
    data: RevealPlanCreate = ...,
) -> RevealPlanResponse:
    """创建揭示计划"""
    return await _reveal_service.create(db, novel_id, data)


@router.get("/reveals/{reveal_id}", response_model=RevealPlanResponse)
async def get_reveal(
    db: DbSession,
    reveal_id: str,
) -> RevealPlanResponse:
    """获取揭示计划详情"""
    return await _reveal_service.get(db, reveal_id)


@router.put("/reveals/{reveal_id}", response_model=RevealPlanResponse)
async def update_reveal(
    db: DbSession,
    reveal_id: str,
    data: RevealPlanUpdate,
) -> RevealPlanResponse:
    """更新揭示计划"""
    return await _reveal_service.update(db, reveal_id, data)


@router.delete("/reveals/{reveal_id}", status_code=204)
async def delete_reveal(
    db: DbSession,
    reveal_id: str,
) -> None:
    """删除揭示计划"""
    await _reveal_service.delete(db, reveal_id)
