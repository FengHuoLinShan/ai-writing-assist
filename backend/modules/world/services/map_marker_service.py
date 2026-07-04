from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import NotFoundError
from modules.world.map_repositories import (
    MapMarkerRepository,
)
from modules.world.map_schemas import (
    MapMarkerCreate,
    MapMarkerResponse,
    MapMarkerUpdate,
)
from modules.world.services.helpers import parse_uuid
from modules.world.services.map_context import MapContext

logger = logging.getLogger(__name__)


class MapMarkerService:
    """动态标记服务（P1）。"""

    def __init__(
        self,
        marker_repo: MapMarkerRepository | None = None,
        context: MapContext | None = None,
    ) -> None:
        self.repo = marker_repo or MapMarkerRepository()
        self._ctx = context or MapContext()

    async def list(
        self,
        db: AsyncSession,
        novel_id: str,
        map_id: str,
        scene_id: str | None = None,
    ) -> list[MapMarkerResponse]:
        await self._ctx.require_map(db, novel_id, map_id)
        nid = parse_uuid(novel_id, "novel_id")
        mid = parse_uuid(map_id, "map_id")
        sid = parse_uuid(scene_id, "scene_id") if scene_id else None

        markers = await self.repo.get_by_map_and_scene(
            db, nid, mid, scene_id=sid, scene_index=None
        )
        return [MapMarkerResponse.model_validate(m) for m in markers]

    async def create(
        self,
        db: AsyncSession,
        novel_id: str,
        map_id: str,
        data: MapMarkerCreate,
    ) -> MapMarkerResponse:
        config = await self._ctx.require_map(db, novel_id, map_id)
        self._ctx.assert_hex_in_bounds(config, data.hex_q, data.hex_r)
        await self._ctx.require_entity(db, novel_id, data.entity_id)

        nid = parse_uuid(novel_id, "novel_id")
        mid = parse_uuid(map_id, "map_id")
        values: dict[str, Any] = {
            "entity_id": uuid.UUID(data.entity_id),
            "marker_type": data.marker_type,
            "hex_q": data.hex_q,
            "hex_r": data.hex_r,
            "offset_x": data.offset_x,
            "offset_y": data.offset_y,
            "label": data.label,
            "style_json": data.style_json or {},
            "start_scene_id": (
                uuid.UUID(data.start_scene_id) if data.start_scene_id else None
            ),
            "start_scene_index": data.start_scene_index,
            "end_scene_id": (uuid.UUID(data.end_scene_id) if data.end_scene_id else None),
            "end_scene_index": data.end_scene_index,
            "visible": data.visible,
        }
        marker = await self.repo.create(db, nid, mid, values)
        return MapMarkerResponse.model_validate(marker)

    async def update(
        self,
        db: AsyncSession,
        novel_id: str,
        marker_id: str,
        data: MapMarkerUpdate,
    ) -> MapMarkerResponse:
        nid = parse_uuid(novel_id, "novel_id")
        mkid = parse_uuid(marker_id, "marker_id")

        marker = await self.repo.get(db, mkid)
        if marker is None or marker.novel_id != nid:
            raise NotFoundError(
                f"MapMarker {marker_id} not found",
                code="map_marker_not_found",
            )

        values: dict[str, Any] = {}
        for field in (
            "hex_q",
            "hex_r",
            "offset_x",
            "offset_y",
            "label",
            "style_json",
            "start_scene_index",
            "end_scene_index",
            "visible",
        ):
            value = getattr(data, field, None)
            if value is not None:
                values[field] = value
        if data.start_scene_id is not None:
            values["start_scene_id"] = uuid.UUID(data.start_scene_id)
        if data.end_scene_id is not None:
            values["end_scene_id"] = uuid.UUID(data.end_scene_id)

        if "hex_q" in values or "hex_r" in values:
            config = await self._ctx.require_map(db, novel_id, str(marker.map_id))
            next_q = values.get("hex_q", marker.hex_q)
            next_r = values.get("hex_r", marker.hex_r)
            self._ctx.assert_hex_in_bounds(config, next_q, next_r)

        updated = await self.repo.update(db, marker, values)
        assert updated is not None
        return MapMarkerResponse.model_validate(updated)

    async def delete(
        self,
        db: AsyncSession,
        novel_id: str,
        marker_id: str,
    ) -> None:
        nid = parse_uuid(novel_id, "novel_id")
        mkid = parse_uuid(marker_id, "marker_id")

        marker = await self.repo.get(db, mkid)
        if marker is None or marker.novel_id != nid:
            raise NotFoundError(
                f"MapMarker {marker_id} not found",
                code="map_marker_not_found",
            )
        await self.repo.delete(db, mkid)
