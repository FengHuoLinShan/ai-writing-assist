"""World Event Facade — 事件 / 修订 / 抽取 / 状态导出子域的对外入口。"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.schemas import (
    EventContext,
    EventsContextBundle,
)
from modules.world.services import (
    EntityRevisionService,
    EventService,
)

_event_service = EventService()
_revision_service = EntityRevisionService()


# ============================================================
# Event
# ============================================================


async def create_event(
    db: AsyncSession,
    novel_id: str,
    data: dict,
) -> dict:
    from modules.world.schemas import EventCreate

    event_data = EventCreate(**data)
    event = await _event_service.create(db, novel_id, event_data)
    return EventContext(
        entity_id=event.entity_id,
        entity_name="",
        timeline_order=event.timeline_order,
        occurrence_time_label=event.occurrence_time_label,
    ).model_dump()


async def get_events_context(
    db: AsyncSession,
    novel_id: str,
    limit: int = 50,
) -> EventsContextBundle:
    """获取事件上下文（含实体名称）"""
    events = await _event_service.get_events_in_order(db, novel_id, limit=limit)

    event_contexts: list[EventContext] = []
    for ev in events:
        event_contexts.append(
            EventContext(
                entity_id=ev.entity_id,
                entity_name="",
                timeline_order=ev.timeline_order,
                occurrence_time_label=ev.occurrence_time_label,
            )
        )

    return EventsContextBundle(
        novel_id=novel_id,
        events=event_contexts,
        total_count=len(event_contexts),
    )


# ============================================================
# EntityRevision
# ============================================================


async def get_entity_revisions(
    db: AsyncSession,
    novel_id: str,
    entity_id: str,
    skip: int = 0,
    limit: int = 20,
) -> dict:
    return await _revision_service.get_revisions(
        db,
        entity_id,
        novel_id,
        skip=skip,
        limit=limit,
    )


async def rollback_to_revision(
    db: AsyncSession,
    novel_id: str,
    entity_id: str,
    revision_id: str,
) -> dict:
    return await _revision_service.rollback_to_revision(
        db,
        entity_id,
        revision_id,
        novel_id,
    )


# ============================================================
# Extraction
# ============================================================


async def run_entity_extraction(
    db: AsyncSession,
    novel_id: str,
    start_chapter: int,
    end_chapter: int,
    batch_size: int = 5,
) -> dict[str, Any]:
    from modules.world.services.core.extraction_service import EntityExtractionService

    service = EntityExtractionService()
    result = await service.extract_entities_from_chapters(
        db,
        novel_id=novel_id,
        start_chapter=start_chapter,
        end_chapter=end_chapter,
        batch_size=batch_size,
    )
    return {
        "total_chapters": result.total_chapters,
        "total_created": result.total_created,
        "total_skipped": result.total_skipped,
        "failed_chapters": result.failed_chapters,
        "items": result.items,
    }


# ============================================================
# 完整状态导出（供 memory 模块快照用）
# ============================================================


async def get_full_state(
    db: AsyncSession,
    novel_id: str,
) -> dict[str, Any]:
    """导出当前世界完整状态，供 memory 模块捕捉快照。

    委托给 state_assembler.assemble, 保留跨模块契约。
    ADR-0001: 真正的实现归 world.state_assembler, facade 只剩薄代理。
    """
    from modules.world.state_assembler import assemble

    return await assemble(db, novel_id)
