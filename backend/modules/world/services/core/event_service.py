"""EventService — 事件 CRUD。继承 BaseCRUDService (ADR-0002)。"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from core.crud import CrudService
from core.errors import NotFoundError
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
        await self._assert_entity_in_novel(db, data.entity_id, nid, "Event entity")
        await self._assert_entity_in_novel(
            db,
            data.location_entity_id,
            nid,
            "Event location",
        )
        return await super().create(db, novel_id, data)

    async def update(
        self,
        db: AsyncSession,
        id: str,
        data: EventUpdate,
        *,
        novel_id: str,
    ) -> EventResponse:
        nid = parse_uuid(novel_id, "novel_id")
        if data.location_entity_id is not None:
            await self._assert_entity_in_novel(
                db,
                data.location_entity_id,
                nid,
                "Event location",
            )
        return await super().update(db, id, data, novel_id=novel_id)

    async def _assert_entity_in_novel(
        self,
        db: AsyncSession,
        entity_id: str,
        novel_id,
        label: str,
    ) -> None:
        eid = parse_uuid(entity_id, "entity_id")
        entity = await self._entity_repo.get(db, eid)
        if (
            entity is None
            or entity.novel_id != novel_id
            or getattr(entity, "status", None) == "deprecated"
        ):
            raise NotFoundError(f"{label} not found in this novel")

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
