from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.map_schemas import (
    MapDashboardResponse,
)
from modules.world.services.helpers import parse_uuid


class MapDashboardService:
    """Delegated dynamic-map service."""

    def __init__(self, owner: Any) -> None:
        self.owner = owner

    async def get_dashboard(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        map_id: str,
        scene_id: str | None = None,
        focus_entity_id: str | None = None,
    ) -> MapDashboardResponse:
        owner = self.owner
        """构建世界动态总控台派生视图。"""
        await owner._ctx.require_map(db, novel_id, map_id)
        nid = parse_uuid(novel_id, "novel_id")
        mid = parse_uuid(map_id, "map_id")
        focus_id = (
            parse_uuid(focus_entity_id, "focus_entity_id")
            if focus_entity_id
            else None
        )

        observations = await owner._observation_repo.list_for_dashboard(
            db,
            nid,
            map_id=mid,
            limit=120,
        )
        facts, _ = await owner._fact_repo.list(
            db,
            nid,
            map_id=mid,
            fact_status="confirmed",
            limit=120,
        )
        active_observations = [
            item
            for item in observations
            if item.review_state in {"candidate", "conflicted"}
        ]
        queue = [
            *(owner._queue_item_from_observation(item) for item in active_observations),
            *(owner._queue_item_from_fact(item) for item in facts),
        ]
        queue.sort(key=lambda item: (-item.priority, item.time_label, item.title))
        queue = queue[:80]
        if scene_id:
            queue = owner._filter_queue_for_scene(queue, scene_id)
        dashboard_queue = (
            owner._filter_queue_for_focus(queue, str(focus_id))
            if focus_id
            else queue
        )

        inspector = owner._build_dashboard_inspector(
            dashboard_queue,
            focus_entity_id=str(focus_id) if focus_id else None,
        )
        risk_summary = owner._build_risk_summary(dashboard_queue)
        return MapDashboardResponse(
            map_id=map_id,
            first_visual_layer=owner._build_first_visual_layer(
                dashboard_queue,
                scene_id=scene_id,
                risk_summary=risk_summary,
            ),
            dynamic_queue=dashboard_queue,
            inspector=inspector,
            batch_groups=owner._build_batch_groups(dashboard_queue),
            risk_summary=risk_summary,
        )
