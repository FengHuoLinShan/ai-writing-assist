from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import NotFoundError
from modules.world.map_schemas import (
    MapOpenTarget,
)
from modules.world.services.common import parse_uuid


class MapOpenTargetService:
    """Delegated dynamic-map service."""

    def __init__(self, owner: Any) -> None:
        self.owner = owner

    async def get_open_target(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        scene_id: str | None = None,
        focus_entity_id: str | None = None,
    ) -> MapOpenTarget:
        owner = self.owner
        nid = parse_uuid(novel_id, "novel_id")
        if scene_id:
            from modules.world.services.map.map_scene_summary import (
                MapSceneSummaryService,
            )

            summary = await MapSceneSummaryService().summarize(db, novel_id, scene_id)
            return summary.open_target

        if focus_entity_id:
            fid = parse_uuid(focus_entity_id, "focus_entity_id")
            entity = await owner._entity_repo.get(db, fid)
            if entity is None or entity.novel_id != nid:
                raise NotFoundError(
                    f"CoreEntity {focus_entity_id} not found",
                    code="entity_not_found",
                )
            map_id = await owner._map_id_for_entity_focus(
                db,
                nid,
                fid,
                entity.entity_type,
            )
            if map_id is not None:
                return MapOpenTarget(
                    mode="map",
                    map_id=str(map_id),
                    focus_entity_id=str(fid),
                )
            return MapOpenTarget(
                mode="recent",
                focus_entity_id=str(fid),
                fallback_reason="focus_without_map",
                fallback_message="该对象暂无地图位置，已回退到最近地图",
            )

        first_map = await owner._map_repo.first_by_novel(db, nid)
        if first_map is not None:
            return MapOpenTarget(mode="map", map_id=str(first_map.id))
        return MapOpenTarget(
            mode="overview",
            fallback_reason="no_map",
            fallback_message="当前项目暂无地图，请先创建世界地图",
        )

    async def _map_id_for_entity_focus(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        entity_id: uuid.UUID,
        entity_type: str,
    ) -> uuid.UUID | None:
        owner = self.owner
        binding = await owner._binding_repo.find_any_for_entity(db, novel_id, entity_id)
        if binding is not None:
            return binding.map_id
        marker = await owner._marker_repo.find_any_for_entity(db, novel_id, entity_id)
        if marker is not None:
            return marker.map_id
        if entity_type in {"organization", "faction"}:
            territory = await owner._territory_repo.find_any_for_faction(
                db,
                novel_id,
                entity_id,
            )
            if territory is not None:
                return territory.map_id
        path = await owner._path_repo.find_any_for_endpoint(db, novel_id, entity_id)
        if path is not None:
            return path.map_id
        return None
