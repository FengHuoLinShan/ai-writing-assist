from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.map_schemas import (
    MapPlaybackEvent,
    MapPlaybackResponse,
)
from modules.world.services.common import parse_uuid


class MapPlaybackMixin:
    """Internal playback projection owned by MapDynamicFactService."""

    async def get_playback(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        map_id: str,
        scene_id: str | None = None,
        focus_entity_id: str | None = None,
        include_candidates: bool = True,
    ) -> MapPlaybackResponse:
        """构建只读电影化播放事件流。"""
        owner = self
        await owner._ctx.require_map(db, novel_id, map_id)
        nid = parse_uuid(novel_id, "novel_id")
        mid = parse_uuid(map_id, "map_id")
        focus_id = (
            parse_uuid(focus_entity_id, "focus_entity_id") if focus_entity_id else None
        )

        observations = await owner._observation_repo.list_for_dashboard(
            db,
            nid,
            map_id=mid,
            limit=160,
        )
        facts, _ = await owner._fact_repo.list(
            db,
            nid,
            map_id=mid,
            fact_status="confirmed",
            limit=160,
        )
        items: list[tuple[str, Any]] = [("fact", fact) for fact in facts]
        if include_candidates:
            items.extend(
                ("observation", obs)
                for obs in observations
                if obs.review_state in {"candidate", "conflicted"}
            )
        if scene_id:
            scene_uuid = owner._safe_uuid(scene_id)
            items = [
                (kind, item)
                for kind, item in items
                if getattr(item, "scene_id", None) in {None, scene_uuid}
                or str(getattr(item, "scene_id", "")) == scene_id
            ]
        if focus_id:
            items = [
                (kind, item)
                for kind, item in items
                if getattr(item, "target_entity_id", None) in {None, focus_id}
            ]

        events: list[MapPlaybackEvent] = []
        for kind, item in items:
            event = owner._playback_event_from_item(kind, item)
            if event is not None:
                events.append(event)
        events.sort(
            key=lambda event: (
                event.scene_index is None,
                event.scene_index if event.scene_index is not None else 10**6,
                event.scene_sequence is None,
                event.scene_sequence if event.scene_sequence is not None else 10**6,
                event.source_chapter_index
                if event.source_chapter_index is not None
                else 10**6,
                event.time_label,
                event.title,
            )
        )
        return MapPlaybackResponse(
            map_id=map_id,
            events=events[:120],
            tracks=owner._build_playback_tracks(events),
            low_motion_recommended=len(events) > 40,
        )


class MapPlaybackService(MapPlaybackMixin):
    """Compatibility adapter for former owner-bound imports."""

    def __init__(self, owner: Any) -> None:
        self._owner = owner

    def __getattr__(self, name):
        return getattr(self._owner, name)


__all__ = ["MapPlaybackMixin", "MapPlaybackService"]
