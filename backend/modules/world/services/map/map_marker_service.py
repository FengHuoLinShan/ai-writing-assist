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
from modules.world.services.common import parse_uuid
from modules.world.services.map.map_context import MapContext
from modules.world.services.map.map_layer_tree import MapLayerTreeService
from modules.world.services.map.map_revision import MapRevisionService

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
        self._layer_tree = MapLayerTreeService(context=self._ctx)
        self._revision = MapRevisionService()

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

        markers = await self.repo.get_by_map_and_scene_for_entity_statuses(
            db,
            nid,
            mid,
            statuses=["canonical"],
            scene_id=sid,
            scene_index=None,
        )
        return [MapMarkerResponse.model_validate(m) for m in markers]

    async def create(
        self,
        db: AsyncSession,
        novel_id: str,
        map_id: str,
        data: MapMarkerCreate,
        *,
        bump_revision: bool = True,
        id_override: uuid.UUID | None = None,
    ) -> MapMarkerResponse:
        locked_config = (
            await self._revision.lock_active(db, novel_id, map_id)
            if bump_revision
            else None
        )
        config = await self._ctx.require_map(db, novel_id, map_id)
        await self._layer_tree.assert_writable(
            db, novel_id, map_id, layer_key=f"marker.{data.marker_type}"
        )
        self._ctx.assert_hex_in_bounds(config, data.hex_q, data.hex_r)
        await self._ctx.require_canonical_entity(db, novel_id, data.entity_id)

        nid = parse_uuid(novel_id, "novel_id")
        mid = parse_uuid(map_id, "map_id")
        values: dict[str, Any] = {
            **({"id": id_override} if id_override else {}),
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
        if bump_revision:
            await self._revision.bump(
                db,
                novel_id,
                map_id,
                locked_config=locked_config,
            )
        return MapMarkerResponse.model_validate(marker)

    async def update(
        self,
        db: AsyncSession,
        novel_id: str,
        marker_id: str,
        data: MapMarkerUpdate,
        *,
        map_id: str | None = None,
        bump_revision: bool = True,
    ) -> MapMarkerResponse:
        nid = parse_uuid(novel_id, "novel_id")
        mkid = parse_uuid(marker_id, "marker_id")

        marker = (
            await self.repo.get_in_map(
                db,
                nid,
                parse_uuid(map_id, "map_id"),
                mkid,
            )
            if map_id
            else await self.repo.get(db, mkid)
        )
        if marker is None or marker.novel_id != nid:
            raise NotFoundError(
                f"MapMarker {marker_id} not found",
                code="map_marker_not_found",
            )
        resolved_map_id = map_id or str(marker.map_id)
        locked_config = (
            await self._revision.lock_active(db, novel_id, resolved_map_id)
            if bump_revision
            else None
        )
        await self._ctx.require_canonical_entity(
            db,
            novel_id,
            str(marker.entity_id),
        )
        await self._layer_tree.assert_writable(
            db,
            novel_id,
            resolved_map_id,
            layer_key=f"marker.{marker.marker_type}",
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
            if field in data.model_fields_set:
                value = getattr(data, field)
                if value is not None or field in {
                    "label",
                    "style_json",
                    "start_scene_index",
                    "end_scene_index",
                }:
                    values[field] = value
        if "start_scene_id" in data.model_fields_set:
            values["start_scene_id"] = (
                uuid.UUID(data.start_scene_id) if data.start_scene_id else None
            )
        if "end_scene_id" in data.model_fields_set:
            values["end_scene_id"] = (
                uuid.UUID(data.end_scene_id) if data.end_scene_id else None
            )

        if "hex_q" in values or "hex_r" in values:
            config = await self._ctx.require_map(db, novel_id, str(marker.map_id))
            next_q = values.get("hex_q", marker.hex_q)
            next_r = values.get("hex_r", marker.hex_r)
            self._ctx.assert_hex_in_bounds(config, next_q, next_r)

        updated = await self.repo.update(db, marker, values)
        assert updated is not None
        if bump_revision:
            await self._revision.bump(
                db,
                novel_id,
                resolved_map_id,
                locked_config=locked_config,
            )
        return MapMarkerResponse.model_validate(updated)

    async def delete(
        self,
        db: AsyncSession,
        novel_id: str,
        marker_id: str,
        *,
        map_id: str | None = None,
        bump_revision: bool = True,
    ) -> None:
        nid = parse_uuid(novel_id, "novel_id")
        mkid = parse_uuid(marker_id, "marker_id")

        marker = (
            await self.repo.get_in_map(
                db,
                nid,
                parse_uuid(map_id, "map_id"),
                mkid,
            )
            if map_id
            else await self.repo.get(db, mkid)
        )
        if marker is None or marker.novel_id != nid:
            raise NotFoundError(
                f"MapMarker {marker_id} not found",
                code="map_marker_not_found",
            )
        resolved_map_id = map_id or str(marker.map_id)
        locked_config = (
            await self._revision.lock_active(db, novel_id, resolved_map_id)
            if bump_revision
            else None
        )
        await self._layer_tree.assert_writable(
            db,
            novel_id,
            resolved_map_id,
            layer_key=f"marker.{marker.marker_type}",
        )
        await self.repo.delete(db, mkid)
        if bump_revision:
            await self._revision.bump(
                db,
                novel_id,
                resolved_map_id,
                locked_config=locked_config,
            )
