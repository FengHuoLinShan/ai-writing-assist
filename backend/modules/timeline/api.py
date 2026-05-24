"""
Timeline API 路由

提供时间线事件的 CRUD API 和冲突检查接口。
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from core.dependencies import DbSession
from modules.timeline.schemas import (
    TimelineEventCreate,
    TimelineEventListResponse,
    TimelineEventResponse,
    TimelineEventUpdate,
)
from modules.timeline.services import TimelineService
from shared.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE

router = APIRouter(prefix="/api/novels/{novel_id}/timeline", tags=["timeline"])
_service = TimelineService()


@router.post("/events", response_model=TimelineEventResponse, status_code=201)
async def create_timeline_event(
    db: DbSession,
    novel_id: str,
    data: TimelineEventCreate,
) -> TimelineEventResponse:
    """创建时间线事件"""
    return await _service.create_event(db, novel_id, data)


@router.get("/events", response_model=TimelineEventListResponse)
async def list_timeline_events(
    db: DbSession,
    novel_id: str,
    skip: int = Query(default=0, ge=0, description="跳过的记录数"),
    limit: int = Query(
        default=DEFAULT_PAGE_SIZE,
        ge=1,
        le=MAX_PAGE_SIZE,
        description="每页条数",
    ),
    status: str | None = Query(None, description="状态过滤"),
    event_type: str | None = Query(None, description="事件类型过滤"),
    before_chapter: int | None = Query(
        None, description="只返回该章节之前的事件"
    ),
    character_id: str | None = Query(
        None, description="按关联角色 ID 过滤"
    ),
) -> TimelineEventListResponse:
    """获取时间线事件列表"""
    items, total = await _service.list_events(
        db,
        novel_id,
        skip=skip,
        limit=limit,
        status=status,
        event_type=event_type,
        before_chapter=before_chapter,
        character_id=character_id,
    )
    return TimelineEventListResponse(items=items, total=total)


@router.get("/events/{event_id}", response_model=TimelineEventResponse)
async def get_timeline_event(
    db: DbSession,
    novel_id: str,
    event_id: str,
) -> TimelineEventResponse:
    """获取时间线事件详情"""
    return await _service.get_event(db, event_id)


@router.put("/events/{event_id}", response_model=TimelineEventResponse)
async def update_timeline_event(
    db: DbSession,
    novel_id: str,
    event_id: str,
    data: TimelineEventUpdate,
) -> TimelineEventResponse:
    """更新时间线事件"""
    return await _service.update_event(db, event_id, data)


@router.delete("/events/{event_id}", status_code=204)
async def delete_timeline_event(
    db: DbSession,
    novel_id: str,
    event_id: str,
) -> None:
    """删除时间线事件"""
    await _service.delete_event(db, event_id)
