"""EventService — 事件 CRUD。继承 BaseCRUDService (ADR-0002)。"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from core.container import get
from core.crud import CrudService
from core.errors import ConflictError, NotFoundError, ValidationError
from core.service_keys import (
    WORLD_WORLDBUILDING_MARK_SYNOPSIS_SOURCE_CHANGED,
)
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
    删除只置 ``status="deprecated"``；已删除的扩展行对 get/update 表现为 404，
    对同一实体再次 create 时用新字段复活（主键即 entity_id）。
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
        eid = parse_uuid(data.entity_id, "entity_id")
        # 与对象类型切换共用实体锁；事件尚无扩展行时也能串行化首次创建。
        await self._entity_repo.get_many_for_update(
            db, nid, [eid, parse_uuid(data.location_entity_id, "entity_id")]
        )
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
        existing = await self.repo.get(db, eid)
        if existing is None:
            created = await super().create(db, novel_id, data)
        else:
            self._assert_found_in_novel(existing, data.entity_id, nid)
            if existing.status != "deprecated":
                raise ConflictError(f"Event {data.entity_id} already exists")
            created = self._to_response(await self.repo.restore(db, existing, data))
        mark_synopsis_source_changed = get(
            WORLD_WORLDBUILDING_MARK_SYNOPSIS_SOURCE_CHANGED
        )
        await mark_synopsis_source_changed(
            db,
            novel_id,
            source_type="event",
            source_id=created.entity_id,
        )
        return created

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
        self._assert_not_deprecated(event, id)
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
        self._assert_not_deprecated(event, id)
        location_id = data.location_entity_id or str(event.location_entity_id)
        await self._entity_repo.get_many_for_update(
            db, nid, [eid, parse_uuid(location_id, "entity_id")]
        )
        # 锁前读取只定位锁集合；锁后重新读取，不能信任 Session 中的旧状态。
        event = await self.repo.get(db, eid)
        self._assert_found_in_novel(event, id, nid)
        self._assert_not_deprecated(event, id)
        if (
            data.location_entity_id is None
            and str(event.location_entity_id) != location_id
        ):
            raise ConflictError("Event location changed; retry the update")
        await self._assert_entity_in_novel(
            db,
            id,
            nid,
            "Event entity",
            entity_type="event",
        )
        await self._assert_entity_in_novel(
            db,
            location_id,
            nid,
            "Event location",
            entity_type="location",
        )
        updated = await self.repo.update(db, eid, data)
        self._assert_found_in_novel(updated, id, nid)
        mark_synopsis_source_changed = get(
            WORLD_WORLDBUILDING_MARK_SYNOPSIS_SOURCE_CHANGED
        )
        await mark_synopsis_source_changed(
            db,
            novel_id,
            source_type="event",
            source_id=id,
        )
        return self._to_response(updated)

    async def delete(  # type: ignore[override]
        self,
        db: AsyncSession,
        id: str,
        *,
        novel_id: str,
    ) -> None:
        """软删除：置 deprecated 并把 novel_id 下推到 where 条件做纵深防御。

        与 base `CrudService.delete` 一致，重复删除已删除的事件是幂等 no-op。
        """
        rid = parse_uuid(id, self.id_param)
        nid = parse_uuid(novel_id, "novel_id")
        await self._entity_repo.get_for_update(db, rid, novel_id=nid)
        event = await self.repo.get(db, rid)
        self._assert_found_in_novel(event, id, nid)
        if event.status == "deprecated":
            return
        ok = await self.repo.deprecate(db, rid, novel_id=nid)
        if not ok:
            self._raise_404(id)
        mark_synopsis_source_changed = get(
            WORLD_WORLDBUILDING_MARK_SYNOPSIS_SOURCE_CHANGED
        )
        await mark_synopsis_source_changed(
            db,
            novel_id,
            source_type="event",
            source_id=id,
        )

    def _assert_not_deprecated(self, event: Event, raw_id: str) -> None:
        if event.status == "deprecated":
            self._raise_404(raw_id)

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
