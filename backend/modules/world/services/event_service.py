"""EventService — 事件 CRUD"""

from __future__ import annotations

from fastapi import HTTPException
from fastapi import status as http_status
from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.repositories import EventRepository
from modules.world.schemas import (
    EventCreate,
    EventListResponse,
    EventResponse,
    EventUpdate,
)
from modules.world.services.helpers import parse_uuid
from shared.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE


class EventService:
    """事件业务服务"""

    def __init__(self) -> None:
        self._repo = EventRepository()

    async def create(
        self,
        db: AsyncSession,
        novel_id: str,
        data: EventCreate,
    ) -> EventResponse:
        nid = parse_uuid(novel_id, "novel_id")
        event = await self._repo.create(db, nid, data)
        return EventResponse.model_validate(event)

    async def get(
        self,
        db: AsyncSession,
        entity_id: str,
        novel_id: str | None = None,
    ) -> EventResponse:
        eid = parse_uuid(entity_id, "entity_id")
        event = await self._repo.get(db, eid)
        if event is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Event {entity_id} not found",
            )
        if novel_id and str(event.novel_id) != novel_id:
            raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND)
        return EventResponse.model_validate(event)

    async def list(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        skip: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> tuple[list[EventResponse], int]:
        nid = parse_uuid(novel_id, "novel_id")
        limit = min(limit, MAX_PAGE_SIZE)
        items, total = await self._repo.get_by_novel(db, nid, skip=skip, limit=limit)
        return [EventResponse.model_validate(e) for e in items], total

    async def update(
        self,
        db: AsyncSession,
        entity_id: str,
        data: EventUpdate,
        novel_id: str | None = None,
    ) -> EventResponse:
        eid = parse_uuid(entity_id, "entity_id")
        if novel_id:
            existing = await self._repo.get(db, eid)
            if existing is None or str(existing.novel_id) != novel_id:
                raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND)
        event = await self._repo.update(db, eid, data)
        if event is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Event {entity_id} not found",
            )
        return EventResponse.model_validate(event)

    async def delete(
        self,
        db: AsyncSession,
        entity_id: str,
        novel_id: str | None = None,
    ) -> None:
        eid = parse_uuid(entity_id, "entity_id")
        if novel_id:
            existing = await self._repo.get(db, eid)
            if existing is None or str(existing.novel_id) != novel_id:
                raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND)
        deleted = await self._repo.delete(db, eid)
        if not deleted:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Event {entity_id} not found",
            )

    async def get_events_for_chapter(
        self,
        db: AsyncSession,
        novel_id: str,
        chapter_id: str,
    ) -> list[EventResponse]:
        """获取某章节的所有事件"""
        nid = parse_uuid(novel_id, "novel_id")
        cid = parse_uuid(chapter_id, "chapter_id")
        events = await self._repo.get_events_for_chapter(db, nid, cid)
        return [EventResponse.model_validate(e) for e in events]

    async def get_events_in_order(
        self,
        db: AsyncSession,
        novel_id: str,
        limit: int = 50,
    ) -> list[EventResponse]:
        """按时间线顺序获取事件"""
        nid = parse_uuid(novel_id, "novel_id")
        events = await self._repo.get_events_in_order(db, nid, limit=limit)
        return [EventResponse.model_validate(e) for e in events]
