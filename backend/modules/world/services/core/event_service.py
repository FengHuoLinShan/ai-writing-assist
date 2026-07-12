"""EventService — 事件 CRUD。继承 BaseCRUDService (ADR-0002)。"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from core.crud import CrudService
from core.errors import NotFoundError, ValidationError
from modules.world.models import Event
from modules.world.repositories import CoreEntityRepository, EventRepository
from modules.world.schemas import (
    EventCreate,
    EventResponse,
    EventUpdate,
)
from modules.world.services.common import parse_uuid


class EventService(
    CrudService[Event, EventCreate, EventUpdate, EventResponse],
):
    """事件业务服务。

    标准 5 verb (get / list / create / update / delete) 继承自 base,
    novel_id keyword-only 必填 (per world/CLAUDE.md §4)。
    """

    repo = EventRepository()
    response = EventResponse
    label = "Event"
    id_param = "event_id"  # Event PK 复用 CoreEntity.entity_id, parse_uuid 报错的字段名

    def __init__(self) -> None:
        self._entity_repo = CoreEntityRepository()

    async def create(
        self,
        db: AsyncSession,
        novel_id: str,
        data: EventCreate,
    ) -> EventResponse:
        nid = parse_uuid(novel_id, "novel_id")
        await self._assert_entity_in_novel(
            db,
            data.entity_id,
            nid,
            "Event entity",
            entity_type="event",
        )
        await self._assert_entity_in_novel(
            db,
            data.location_entity_id,
            nid,
            "Event location",
            entity_type="location",
        )
        return await super().create(db, novel_id, data)

    async def get(  # type: ignore[override]
        self,
        db: AsyncSession,
        id: str,
        *,
        novel_id: str,
    ) -> EventResponse:
        eid = parse_uuid(id, self.id_param)
        nid = parse_uuid(novel_id, "novel_id")
        event = await self.repo.get(db, eid)
        self._assert_found_in_novel(event, id, nid)
        await self._assert_active_event(db, event, nid, raw_id=id)
        return self._to_response(event)

    async def update(
        self,
        db: AsyncSession,
        id: str,
        data: EventUpdate,
        *,
        novel_id: str,
    ) -> EventResponse:
        nid = parse_uuid(novel_id, "novel_id")
        eid = parse_uuid(id, self.id_param)
        event = await self.repo.get(db, eid)
        self._assert_found_in_novel(event, id, nid)
        await self._assert_entity_in_novel(
            db,
            id,
            nid,
            "Event entity",
            entity_type="event",
        )
        location_id = data.location_entity_id or str(event.location_entity_id)
        await self._assert_entity_in_novel(
            db,
            location_id,
            nid,
            "Event location",
            entity_type="location",
        )
        updated = await self.repo.update(db, eid, data)
        self._assert_found_in_novel(updated, id, nid)
        return self._to_response(updated)

    async def _assert_entity_in_novel(
        self,
        db: AsyncSession,
        entity_id: str,
        novel_id,
        label: str,
        *,
        entity_type: str,
    ) -> None:
        eid = parse_uuid(entity_id, "entity_id")
        entity = await self._entity_repo.get(db, eid)
        if entity is None or entity.novel_id != novel_id or entity.status != "canonical":
            raise NotFoundError(f"{label} not found in this novel")
        if entity.entity_type != entity_type:
            raise ValidationError(
                f"{label} must reference a {entity_type} CoreEntity",
                status_code=422,
            )

    async def _assert_active_event(
        self,
        db: AsyncSession,
        event: Event,
        novel_id,
        *,
        raw_id: str,
    ) -> None:
        await self._assert_entity_in_novel(
            db,
            raw_id,
            novel_id,
            "Event entity",
            entity_type="event",
        )
        await self._assert_entity_in_novel(
            db,
            str(event.location_entity_id),
            novel_id,
            "Event location",
            entity_type="location",
        )

    # ============================================================
    # 特例方法 (深度不同的部分, 不归 base)
    # ============================================================

    async def get_events_for_chapter(
        self,
        db: AsyncSession,
        novel_id: str,
        chapter_id: str,
    ) -> list[EventResponse]:
        """获取某章节的所有事件。"""
        nid = parse_uuid(novel_id, "novel_id")
        cid = parse_uuid(chapter_id, "chapter_id")
        events = await self.repo.get_events_for_chapter(db, nid, cid)
        return [EventResponse.model_validate(e) for e in events]

    async def get_events_in_order(
        self,
        db: AsyncSession,
        novel_id: str,
        limit: int = 50,
    ) -> list[EventResponse]:
        """按时间线顺序获取事件。"""
        nid = parse_uuid(novel_id, "novel_id")
        events = await self.repo.get_events_in_order(db, nid, limit=limit)
        return [EventResponse.model_validate(e) for e in events]
