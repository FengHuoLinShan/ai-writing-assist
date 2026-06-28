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
