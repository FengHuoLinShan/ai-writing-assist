"""World map facade.

跨模块调用地图动态能力时只从这里进入；具体编排仍由 world/map 拥有。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.services.map_service import MapDynamicFactService

_map_dynamic_facts = MapDynamicFactService()


async def create_map_observation_from_delta_event(
    db: AsyncSession,
    novel_id: str,
    *,
    event: dict[str, Any],
    scene_index: int,
    context_snapshot_id: str | None = None,
    delta_log_id: str | None = None,
) -> dict[str, Any]:
    """将通用 delta_event 归一为地图观察候选。"""
    observation = await _map_dynamic_facts.create_observation_from_delta_event(
        db,
        novel_id,
        event=event,
        scene_index=scene_index,
        context_snapshot_id=context_snapshot_id,
        delta_log_id=delta_log_id,
    )
    return observation.model_dump()


async def summarize_scene_map_for_writing(
    db: AsyncSession,
    novel_id: str,
    scene_id: str,
    *,
    include_candidates: bool = False,
) -> dict[str, Any]:
    """Return a Scene map summary for writing conflict checks.

    V1 checks default to canonical map context. include_candidates lets writing
    conflict checks opt into candidate/conflicted map observation evidence.
    """
    from modules.world.services.map.map_scene_summary import MapSceneSummaryService

    summary = await MapSceneSummaryService().summarize(
        db,
        novel_id,
        scene_id,
        include_candidates=include_candidates,
    )
    return summary.model_dump()


async def count_deep_import_map_observations_by_workflow(
    db: AsyncSession,
    novel_id: str,
    workflow_id: str,
) -> int:
    """Count unconfirmed map observations for cleanup reporting only."""
    from sqlalchemy import select

    from modules.world.map_models import MapObservation
    from shared.utils import parse_uuid

    nid = parse_uuid(novel_id, "novel_id")
    stmt = select(MapObservation).where(
        MapObservation.novel_id == nid,
        MapObservation.review_state.in_(["candidate", "conflicted"]),
    )
    result = await db.execute(stmt)
    observations = result.scalars().all()
    return sum(
        1
        for observation in observations
        if (observation.source_ref or {}).get("workflow_id") == workflow_id
        and (observation.source_ref or {}).get("auto_ingested") is True
    )
