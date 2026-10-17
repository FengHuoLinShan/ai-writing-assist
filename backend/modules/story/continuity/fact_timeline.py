"""Author-scoped read projection for recorded Story fact events."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import NotFoundError
from modules.story.continuity.chapter_order import StoryChapterOrderService
from modules.story.continuity.chapter_order_projection import (
    build_chapter_order_transitions,
    project_current_chapter_index,
)
from modules.story.continuity.models import (
    MemoryEvent,
    StoryChapterOrderReceipt,
)
from modules.story.continuity.schemas import (
    MemoryEventResponse,
    StoryFactTimelineItemResponse,
    StoryFactTimelineQuery,
    StoryFactTimelineResponse,
)
from modules.story.outline_state.models import Scene, SceneChapterLink

_PRIVATE_FACT_KEYS = {
    "id",
    "novel_id",
    "scene_id",
    "draft_id",
    "entity_id",
    "character_id",
    "source_confirmation_id",
    "idempotency_key",
    "event_key",
    "source_hash",
    "content_hash",
    "range_hash",
    "start_offset",
    "end_offset",
    "meta",
}
_UUID_TEXT = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


class StoryFactTimelineService:
    """Read existing fact events with author scope and an optional Scene cutoff."""

    async def list(
        self,
        db: AsyncSession,
        novel_id: str,
        query: StoryFactTimelineQuery,
    ) -> StoryFactTimelineResponse:
        nid = uuid.UUID(str(novel_id))
        cutoff = None
        if query.cutoff_scene_id is not None:
            cutoff = await db.scalar(
                select(Scene).where(
                    Scene.novel_id == nid,
                    Scene.id == query.cutoff_scene_id,
                )
            )
            if cutoff is None:
                raise NotFoundError("截止 Scene 不属于当前作品")

        receipts = list(
            (
                await db.scalars(
                    select(StoryChapterOrderReceipt)
                    .where(StoryChapterOrderReceipt.novel_id == nid)
                    .order_by(
                        StoryChapterOrderReceipt.created_at, StoryChapterOrderReceipt.id
                    )
                )
            ).all()
        )
        order_transitions = build_chapter_order_transitions(receipts)
        pending_reorders = {
            uuid.UUID(value): receipt.created_at
            for receipt in receipts
            if receipt.status == "applied"
            for value in (receipt.impact_json or {}).get("affected_scene_ids", [])
        }
        visible_base = self._base_query(nid, query, cutoff, pending_reorders)
        total = int(
            await db.scalar(select(func.count()).select_from(visible_base.subquery()))
            or 0
        )

        unknown_query = (
            select(func.count(MemoryEvent.id))
            .outerjoin(
                Scene,
                and_(
                    Scene.id == MemoryEvent.scene_id,
                    Scene.novel_id == MemoryEvent.novel_id,
                ),
            )
            .where(
                MemoryEvent.novel_id == nid,
                or_(Scene.id.is_(None), MemoryEvent.scene_id.is_(None)),
            )
        )
        if query.entity_id is not None:
            unknown_query = unknown_query.where(MemoryEvent.entity_id == query.entity_id)
        if query.source is not None:
            unknown_query = unknown_query.where(MemoryEvent.source == query.source)
        # An unanchored event cannot be placed before a Scene cutoff.
        unknown_time_count = (
            int(await db.scalar(unknown_query) or 0) if cutoff is None else 0
        )

        page = (
            await db.execute(
                visible_base.order_by(
                    Scene.scene_index.asc().nullslast(),
                    MemoryEvent.scene_sequence.asc().nullslast(),
                    MemoryEvent.chapter_index,
                    MemoryEvent.sequence,
                    MemoryEvent.id,
                )
                .offset(query.skip)
                .limit(query.limit)
            )
        ).all()
        events = [event for event, _scene in page]
        scene_ids = {event.scene_id for event in events if event.scene_id is not None}
        links_by_scene: dict[uuid.UUID, set[int]] = {
            scene_id: set() for scene_id in scene_ids
        }
        if scene_ids:
            for link in (
                await db.scalars(
                    select(SceneChapterLink).where(
                        SceneChapterLink.novel_id == nid,
                        SceneChapterLink.scene_id.in_(scene_ids),
                    )
                )
            ).all():
                links_by_scene.setdefault(link.scene_id, set()).add(
                    int(link.chapter_index)
                )
        scene_by_id = {scene.id: scene for _, scene in page if scene is not None}
        for scene_id, scene in scene_by_id.items():
            for value in scene.chapter_ids or []:
                try:
                    links_by_scene.setdefault(scene_id, set()).add(int(value))
                except (TypeError, ValueError):
                    continue
            for chunk in scene.scene_chunks or []:
                if not isinstance(chunk, dict):
                    continue
                index = _scene_chunk_chapter_index(chunk)
                if index is not None:
                    links_by_scene.setdefault(scene_id, set()).add(index)

        items: list[StoryFactTimelineItemResponse] = []
        for event, scene in page:
            status = _event_status(event, pending_reorders)
            chapter_index = project_current_chapter_index(
                event.chapter_index, event.created_at, order_transitions
            )
            if scene is None:
                status = "unknown"
                chapter_index = None
            elif chapter_index not in links_by_scene.get(scene.id, set()):
                chapter_index = None
                # Scene time can be known even when the exact physical chapter
                # is not; status describes time visibility, not chapter linkage.
            event_data = MemoryEventResponse.model_validate(event).model_dump()
            event_data["snapshot_before"] = _author_snapshot(event.snapshot_before)
            event_data["snapshot_after"] = _author_snapshot(event.snapshot_after)
            items.append(
                StoryFactTimelineItemResponse(
                    **event_data,
                    entity_label=_entity_label(event.entity_type, event.snapshot_after)
                    if event.entity_id is not None
                    else None,
                    current_chapter_index=chapter_index,
                    current_scene_index=int(scene.scene_index)
                    if scene is not None
                    else None,
                    time_status=status,
                )
            )

        source_options_scope = query.model_copy(update={"source": None})
        source_options = list(
            (
                await db.scalars(
                    self._base_query(nid, source_options_scope, cutoff, pending_reorders)
                    .with_only_columns(MemoryEvent.source)
                    .distinct()
                    .order_by(MemoryEvent.source)
                )
            ).all()
        )
        entity_options_scope = query.model_copy(update={"entity_id": None})
        entity_rows = (
            await db.execute(
                self._base_query(nid, entity_options_scope, cutoff, pending_reorders)
                .where(MemoryEvent.entity_id.is_not(None))
                .with_only_columns(
                    MemoryEvent.entity_id,
                    MemoryEvent.entity_type,
                    MemoryEvent.snapshot_after,
                )
                .order_by(
                    MemoryEvent.created_at.desc(),
                    MemoryEvent.sequence.desc(),
                    MemoryEvent.id,
                )
                .limit(2000)
            )
        ).all()
        entity_options: dict[uuid.UUID, dict[str, Any]] = {}
        for entity_id, entity_type, snapshot_after in entity_rows:
            if entity_id in entity_options:
                continue
            entity_options[entity_id] = {
                "entity_id": str(entity_id),
                "entity_type": entity_type,
                "label": _entity_label(entity_type, snapshot_after),
            }
            if len(entity_options) >= 200:
                break
        scene_options_query = select(Scene.id, Scene.scene_index, Scene.title).where(
            Scene.novel_id == nid
        )
        if cutoff is not None:
            scene_options_query = scene_options_query.where(
                Scene.scene_index <= int(cutoff.scene_index)
            )
        scene_options = (
            await db.execute(
                scene_options_query.order_by(Scene.scene_index, Scene.id).limit(2000)
            )
        ).all()
        # Plan revalidation references are novel-wide; do not expose their
        # labels or counts in a Scene-bounded timeline.
        pending_reviews = (
            await StoryChapterOrderService().list_pending_plan_reviews(db, novel_id)
            if cutoff is None
            else []
        )
        return StoryFactTimelineResponse(
            items=items,
            total=total,
            unknown_time_count=unknown_time_count,
            pending_revalidation_count=len(pending_reviews),
            cutoff_scene=(
                {
                    "scene_id": str(cutoff.id),
                    "scene_index": int(cutoff.scene_index),
                    "title": cutoff.title,
                }
                if cutoff is not None
                else None
            ),
            source_options=[str(value) for value in source_options],
            entity_options=list(entity_options.values()),
            scene_options=[
                {
                    "scene_id": str(scene_id),
                    "scene_index": int(scene_index),
                    "title": title,
                }
                for scene_id, scene_index, title in scene_options
            ],
            pending_revalidations=pending_reviews,
        )

    @staticmethod
    def _base_query(
        novel_id: uuid.UUID,
        query: StoryFactTimelineQuery,
        cutoff: Scene | None,
        pending_reorders: dict[uuid.UUID, datetime | None],
    ):
        statement = (
            select(MemoryEvent, Scene)
            .outerjoin(
                Scene,
                and_(
                    Scene.id == MemoryEvent.scene_id,
                    Scene.novel_id == MemoryEvent.novel_id,
                ),
            )
            .where(MemoryEvent.novel_id == novel_id)
        )
        if query.entity_id is not None:
            statement = statement.where(MemoryEvent.entity_id == query.entity_id)
        if query.source is not None:
            statement = statement.where(MemoryEvent.source == query.source)
        if cutoff is not None:
            statement = statement.where(
                Scene.id.is_not(None),
                Scene.scene_index <= int(cutoff.scene_index),
            )
        if query.status == "unknown":
            statement = statement.where(
                or_(Scene.id.is_(None), MemoryEvent.scene_id.is_(None))
            )
        elif query.status == "stale":
            statement = statement.where(Scene.id.is_not(None))
            pending = _pending_reorder_predicate(pending_reorders)
            if pending is not None:
                statement = statement.where(
                    or_(MemoryEvent.source_stale.is_(True), pending)
                )
            else:
                statement = statement.where(MemoryEvent.source_stale.is_(True))
        elif query.status == "current":
            predicates = [
                MemoryEvent.source_stale.is_(False),
                MemoryEvent.scene_id.is_not(None),
                Scene.id.is_not(None),
            ]
            pending = _pending_reorder_predicate(pending_reorders)
            if pending is not None:
                predicates.append(~pending)
            statement = statement.where(*predicates)
        return statement


def _scene_chunk_chapter_index(chunk: dict[str, Any]) -> int | None:
    values = []
    for key in ("chapter_index", "chapter_id"):
        if chunk.get(key) is not None:
            try:
                values.append(int(chunk[key]))
            except (TypeError, ValueError):
                pass
    if len(set(values)) > 1:
        return None
    return values[0] if values else None


def _pending_reorder_predicate(pending_reorders: dict[uuid.UUID, datetime | None]):
    predicates = []
    for scene_id, applied_at in pending_reorders.items():
        scene_match = MemoryEvent.scene_id == scene_id
        if applied_at is None:
            predicates.append(scene_match)
        else:
            predicates.append(
                and_(
                    scene_match,
                    or_(
                        MemoryEvent.created_at.is_(None),
                        MemoryEvent.created_at < applied_at,
                    ),
                )
            )
    return or_(*predicates) if predicates else None


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _event_status(
    event: MemoryEvent, pending_reorders: dict[uuid.UUID, datetime | None]
) -> str:
    if event.scene_id is None:
        return "unknown"
    applied_at = pending_reorders.get(event.scene_id)
    event_at = _as_utc(event.created_at)
    applied_at = _as_utc(applied_at)
    if event.source_stale or (
        event.scene_id in pending_reorders
        and (event_at is None or applied_at is None or event_at < applied_at)
    ):
        return "stale"
    return "current"


def _entity_label(entity_type: str | None, snapshot: Any) -> str:
    if isinstance(snapshot, dict):
        for key in ("name", "entity_name", "display_name"):
            value = snapshot.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()[:120]
        entity = snapshot.get("entity")
        if isinstance(entity, dict):
            value = entity.get("name") or entity.get("display_name")
            if isinstance(value, str) and value.strip():
                return value.strip()[:120]
    return f"{entity_type or '未知类型'}对象"


def _author_snapshot(value: Any, *, depth: int = 0) -> Any:
    """Hide trace/source identifiers and bound the author-facing event payload."""
    if depth > 4:
        return None
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            normalized = str(key).strip().lower()
            if (
                normalized in _PRIVATE_FACT_KEYS
                or normalized.endswith("_id")
                or normalized.endswith("_ids")
                or "hash" in normalized
                or "token" in normalized
                or "prompt" in normalized
            ):
                continue
            projected = _author_snapshot(item, depth=depth + 1)
            if projected is None or projected == {} or projected == []:
                continue
            result[str(key)[:80]] = projected
            if len(result) >= 20:
                break
        return result
    if isinstance(value, list):
        items = [
            projected
            for item in value[:20]
            if (projected := _author_snapshot(item, depth=depth + 1)) is not None
        ]
        return items
    if isinstance(value, str):
        if _UUID_TEXT.fullmatch(value.strip()):
            return None
        return value[:1000]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:1000]


__all__ = ["StoryFactTimelineService"]
