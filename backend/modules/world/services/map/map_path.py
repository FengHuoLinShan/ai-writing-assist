"""Continuous path layers, paths, archive lifecycle, and typed path reads."""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ConflictError, NotFoundError, ValidationError
from modules.world.map_models import MapFact, MapObservation
from modules.world.map_repositories import (
    MapLayerNodeRepository,
    MapLocationBindingRepository,
    MapLocationLayoutRepository,
    MapPathLayerRepository,
    MapPathNodeRepository,
    MapPathRepository,
)
from modules.world.map_schemas import (
    TRANSPORT_PATH_TYPES,
    WATER_PATH_TYPES,
    MapPathArchiveImpactResponse,
    MapPathCreateData,
    MapPathLayerResponse,
    MapPathNodeResponse,
    MapPathResponse,
    MapPathStateResponse,
    MapPathStyle,
    MapPathUpdateData,
)
from modules.world.services.common import parse_uuid
from modules.world.services.map.map_context import MapContext
from modules.world.services.map.map_layer_tree import MapLayerTreeService

_MAX_PATHS_PER_MAP = 500
_MAX_NODES_PER_MAP = 20_000


class MapPathService:
    """Own continuous path resources and enforce their map/layer invariants."""

    def __init__(self) -> None:
        self._ctx = MapContext()
        self._layers = MapPathLayerRepository()
        self._paths = MapPathRepository()
        self._nodes = MapPathNodeRepository()
        self._layer_nodes = MapLayerNodeRepository()
        self._layouts = MapLocationLayoutRepository()
        self._bindings = MapLocationBindingRepository()
        self._tree = MapLayerTreeService(
            node_repo=self._layer_nodes,
            path_layer_repo=self._layers,
        )

    @staticmethod
    def _allowed_types(category: str) -> tuple[str, ...]:
        return TRANSPORT_PATH_TYPES if category == "transport" else WATER_PATH_TYPES

    @classmethod
    def _assert_type_matches(cls, category: str, path_type: str) -> None:
        if path_type not in cls._allowed_types(category):
            raise ValidationError(
                f"{path_type} 不属于 {category} 线路图层",
                code="invalid_map_path_type",
            )

    @classmethod
    def _node_values(
        cls,
        config: Any,
        nodes: list[Any],
        *,
        category: str,
    ) -> list[dict[str, Any]]:
        values: list[dict[str, Any]] = []
        allowed = set(cls._allowed_types(category))
        for node in nodes:
            if node.q >= config.grid_width or node.r >= config.grid_height:
                raise ValidationError(
                    "线路节点超出地图边界",
                    code="map_path_node_out_of_bounds",
                    context={"q": node.q, "r": node.r},
                )
            if node.segment_type is not None and node.segment_type not in allowed:
                raise ValidationError(
                    "segment_type 必须与所属线路图层同类",
                    code="invalid_map_path_segment_type",
                )
            values.append(node.model_dump())
        return values

    async def _require_layer(
        self,
        db: AsyncSession,
        novel_id: str,
        map_id: str,
        layer_id: str,
    ) -> Any:
        nid = parse_uuid(novel_id, "novel_id")
        mid = parse_uuid(map_id, "map_id")
        lid = parse_uuid(layer_id, "path_layer_id")
        layer = await self._layers.get_in_map(db, nid, mid, lid)
        if layer is None:
            raise NotFoundError("path layer 不存在", code="map_path_layer_not_found")
        return layer

    async def _require_path(
        self,
        db: AsyncSession,
        novel_id: str,
        map_id: str,
        path_id: str,
    ) -> Any:
        nid = parse_uuid(novel_id, "novel_id")
        mid = parse_uuid(map_id, "map_id")
        pid = parse_uuid(path_id, "path_id")
        path = await self._paths.get_in_map(db, nid, mid, pid)
        if path is None:
            raise NotFoundError("地图线路不存在", code="map_path_not_found")
        return path

    async def _validate_location(
        self,
        db: AsyncSession,
        novel_id: str,
        entity_id: str | None,
    ) -> Any | None:
        if entity_id is None:
            return None
        entity = await self._ctx.require_entity(db, novel_id, entity_id)
        if entity.entity_type != "location" or entity.status != "canonical":
            raise ValidationError(
                "线路端点只能绑定同项目已采用地点",
                code="invalid_map_path_endpoint",
            )
        return entity

    async def create_layer(
        self,
        db: AsyncSession,
        novel_id: str,
        map_id: str,
        *,
        layer_id: str,
        leaf_id: str,
        display_name: str,
        category: str,
        meta: dict | None,
    ) -> tuple[Any, Any]:
        await self._ctx.require_map(db, novel_id, map_id)
        await self._tree.assert_writable(db, novel_id, map_id, layer_key="path")
        nid = parse_uuid(novel_id, "novel_id")
        mid = parse_uuid(map_id, "map_id")
        lid = parse_uuid(layer_id, "path_layer_id")
        if await self._layers.get(db, lid) is not None:
            raise ValidationError(
                "服务端生成的 path layer ID 已存在",
                code="duplicate_map_resource_id",
            )
        layer = await self._layers.create(
            db,
            nid,
            mid,
            {"id": lid, "category": category, "meta": meta or {}},
        )
        leaf = await self._tree.create_path_leaf(
            db,
            novel_id,
            map_id,
            str(layer.id),
            display_name=display_name,
            node_id=leaf_id,
        )
        return layer, leaf

    async def delete_layer(
        self,
        db: AsyncSession,
        novel_id: str,
        map_id: str,
        layer_id: str,
    ) -> str:
        await self._ctx.require_map(db, novel_id, map_id)
        layer = await self._require_layer(db, novel_id, map_id, layer_id)
        await self._tree.assert_writable(
            db,
            novel_id,
            map_id,
            path_layer_id=layer.id,
        )
        nid = parse_uuid(novel_id, "novel_id")
        mid = parse_uuid(map_id, "map_id")
        if await self._paths.count_by_layer(db, nid, mid, layer.id):
            raise ConflictError(
                "含 active 或 archived 线路的图层不能删除",
                code="map_path_layer_not_empty",
            )
        await self._layers.delete(db, layer.id)
        return str(layer.id)

    async def _assert_capacity(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        map_id: uuid.UUID,
        *,
        added_paths: int = 0,
        replaced_path_id: uuid.UUID | None = None,
        next_node_count: int = 0,
    ) -> None:
        path_count = await self._paths.count_for_map(db, novel_id, map_id)
        if path_count + added_paths > _MAX_PATHS_PER_MAP:
            raise ValidationError(
                f"每张地图最多 {_MAX_PATHS_PER_MAP} 条线路",
                code="map_path_limit",
            )
        total_nodes = await self._nodes.count_for_map(db, novel_id, map_id)
        if replaced_path_id is not None:
            total_nodes -= len(
                await self._nodes.get_by_paths(
                    db,
                    novel_id,
                    map_id,
                    [replaced_path_id],
                )
            )
        if total_nodes + next_node_count > _MAX_NODES_PER_MAP:
            raise ValidationError(
                f"每张地图最多 {_MAX_NODES_PER_MAP} 个线路节点",
                code="map_path_node_limit",
            )

    async def create_path(
        self,
        db: AsyncSession,
        novel_id: str,
        map_id: str,
        *,
        path_id: str,
        layer_id: str,
        data: MapPathCreateData,
    ) -> Any:
        config = await self._ctx.require_map(db, novel_id, map_id)
        layer = await self._require_layer(db, novel_id, map_id, layer_id)
        await self._tree.assert_writable(db, novel_id, map_id, path_layer_id=layer.id)
        self._assert_type_matches(layer.category, data.path_type)
        node_values = self._node_values(config, data.nodes, category=layer.category)
        start = await self._validate_location(db, novel_id, data.start_location_entity_id)
        end = await self._validate_location(db, novel_id, data.end_location_entity_id)
        nid = parse_uuid(novel_id, "novel_id")
        mid = parse_uuid(map_id, "map_id")
        pid = parse_uuid(path_id, "path_id")
        if await self._paths.get(db, pid) is not None:
            raise ValidationError(
                "服务端生成的 path ID 已存在",
                code="duplicate_map_resource_id",
            )
        await self._assert_capacity(
            db,
            nid,
            mid,
            added_paths=1,
            next_node_count=len(node_values),
        )
        path = await self._paths.create(
            db,
            nid,
            mid,
            {
                "id": pid,
                "path_layer_id": layer.id,
                "name": data.name,
                "path_type": data.path_type,
                "sort_order": data.sort_order,
                "visible": data.visible,
                "locked": data.locked,
                "opacity": data.opacity,
                "min_zoom": data.min_zoom,
                "max_zoom": data.max_zoom,
                "style_json": data.style.model_dump() if data.style else {},
                "start_location_entity_id": start.id if start else None,
                "end_location_entity_id": end.id if end else None,
                "status": "active",
                "content_revision": 1,
                "meta": data.meta or {},
            },
        )
        await self._nodes.replace_for_path(db, nid, mid, path.id, node_values)
        return path

    @staticmethod
    def _assert_path_change_allowed(
        path: Any,
        values: dict[str, Any],
        *,
        moves_layer: bool = False,
        snaps_endpoint: bool = False,
    ) -> None:
        if not path.locked:
            return
        allowed_unlock = (
            values == {"locked": False} and not moves_layer and not snaps_endpoint
        )
        if not allowed_unlock:
            raise ConflictError(
                "线路已锁定，请先单独解锁",
                code="map_path_locked",
            )

    async def _representative_location_hex(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        map_id: uuid.UUID,
        entity_id: uuid.UUID,
    ) -> tuple[float, float] | None:
        layouts = [
            row
            for row in await self._layouts.get_by_map(db, novel_id, map_id)
            if row.location_entity_id == entity_id
        ]
        if layouts:
            layout = min(layouts, key=lambda row: (row.created_at, row.id))
            return float(layout.center_hex_q), float(layout.center_hex_r)
        bindings = [
            row
            for row in await self._bindings.get_by_map(db, novel_id, map_id)
            if row.location_entity_id == entity_id
        ]
        centers = [row for row in bindings if row.is_center]
        if centers:
            center = min(centers, key=lambda row: (row.hex_q, row.hex_r, row.id))
            return float(center.hex_q), float(center.hex_r)
        if not bindings:
            return None
        mean_q = sum(row.hex_q for row in bindings) / len(bindings)
        mean_r = sum(row.hex_r for row in bindings) / len(bindings)
        representative = min(
            bindings,
            key=lambda row: (
                (row.hex_q - mean_q) ** 2 + (row.hex_r - mean_r) ** 2,
                row.hex_q,
                row.hex_r,
                row.id,
            ),
        )
        return float(representative.hex_q), float(representative.hex_r)

    async def update_path(
        self,
        db: AsyncSession,
        novel_id: str,
        map_id: str,
        path_id: str,
        data: MapPathUpdateData,
        *,
        target_layer_id: str | None = None,
    ) -> Any:
        config = await self._ctx.require_map(db, novel_id, map_id)
        path = await self._require_path(db, novel_id, map_id, path_id)
        if path.status != "active":
            raise ConflictError(
                "已归档线路不能编辑",
                code="map_path_archived",
            )
        await self._tree.assert_writable(
            db, novel_id, map_id, path_layer_id=path.path_layer_id
        )
        layer = await self._require_layer(
            db,
            novel_id,
            map_id,
            target_layer_id or str(path.path_layer_id),
        )
        if layer.id != path.path_layer_id:
            await self._tree.assert_writable(db, novel_id, map_id, path_layer_id=layer.id)

        raw_values = data.model_dump(exclude_unset=True, exclude={"layer_ref"})
        raw_values.pop("snap_start", None)
        raw_values.pop("snap_end", None)
        if (
            not raw_values
            and not data.snap_start
            and not data.snap_end
            and target_layer_id is None
        ):
            raise ValidationError("线路更新不能为空", code="empty_map_path_update")
        self._assert_path_change_allowed(
            path,
            raw_values,
            moves_layer=layer.id != path.path_layer_id,
            snaps_endpoint=data.snap_start or data.snap_end,
        )

        next_type = data.path_type or path.path_type
        self._assert_type_matches(layer.category, next_type)
        next_min_zoom = (
            data.min_zoom if "min_zoom" in data.model_fields_set else path.min_zoom
        )
        next_max_zoom = (
            data.max_zoom if "max_zoom" in data.model_fields_set else path.max_zoom
        )
        if (
            next_min_zoom is not None
            and next_max_zoom is not None
            and next_min_zoom > next_max_zoom
        ):
            raise ValidationError(
                "min_zoom 不能大于 max_zoom",
                code="invalid_map_path_zoom",
            )
        nid = parse_uuid(novel_id, "novel_id")
        mid = parse_uuid(map_id, "map_id")
        nodes = (
            self._node_values(config, data.nodes, category=layer.category)
            if data.nodes is not None
            else None
        )
        existing_nodes = await self._nodes.get_by_paths(db, nid, mid, [path.id])
        if nodes is None:
            allowed_segments = set(self._allowed_types(layer.category))
            if any(
                node.segment_type is not None
                and node.segment_type not in allowed_segments
                for node in existing_nodes
            ):
                raise ValidationError(
                    "跨类别移动线路时必须同时替换不兼容的节点类型",
                    code="invalid_map_path_segment_type",
                )
        if nodes is not None:
            await self._assert_capacity(
                db,
                nid,
                mid,
                replaced_path_id=path.id,
                next_node_count=len(nodes),
            )
        else:
            nodes = [
                {
                    "q": node.q,
                    "r": node.r,
                    "width_scale": node.width_scale,
                    "tension": node.tension,
                    "segment_type": node.segment_type,
                }
                for node in existing_nodes
            ]

        start_value = (
            data.start_location_entity_id
            if "start_location_entity_id" in data.model_fields_set
            else str(path.start_location_entity_id)
            if path.start_location_entity_id
            else None
        )
        end_value = (
            data.end_location_entity_id
            if "end_location_entity_id" in data.model_fields_set
            else str(path.end_location_entity_id)
            if path.end_location_entity_id
            else None
        )
        start = await self._validate_location(db, novel_id, start_value)
        end = await self._validate_location(db, novel_id, end_value)
        if data.snap_start:
            if start is None:
                raise ValidationError(
                    "吸附起点前必须绑定地点",
                    code="map_path_endpoint_unresolved",
                )
            coordinate = await self._representative_location_hex(db, nid, mid, start.id)
            if coordinate is None:
                raise ConflictError(
                    "起点地点尚未布置在当前地图",
                    code="map_path_endpoint_unresolved",
                )
            nodes[0]["q"], nodes[0]["r"] = coordinate
        if data.snap_end:
            if end is None:
                raise ValidationError(
                    "吸附终点前必须绑定地点",
                    code="map_path_endpoint_unresolved",
                )
            coordinate = await self._representative_location_hex(db, nid, mid, end.id)
            if coordinate is None:
                raise ConflictError(
                    "终点地点尚未布置在当前地图",
                    code="map_path_endpoint_unresolved",
                )
            nodes[-1]["q"], nodes[-1]["r"] = coordinate

        values: dict[str, Any] = {}
        for field in (
            "name",
            "path_type",
            "sort_order",
            "visible",
            "locked",
            "opacity",
            "min_zoom",
            "max_zoom",
            "meta",
        ):
            if field in data.model_fields_set:
                values[field] = getattr(data, field)
        if "style" in data.model_fields_set:
            values["style_json"] = data.style.model_dump() if data.style else {}
        values.update(
            {
                "path_layer_id": layer.id,
                "start_location_entity_id": start.id if start else None,
                "end_location_entity_id": end.id if end else None,
                "content_revision": path.content_revision + 1,
            }
        )
        await self._paths.update(db, path, values)
        if data.nodes is not None or data.snap_start or data.snap_end:
            await self._nodes.replace_for_path(db, nid, mid, path.id, nodes)
        return path

    async def archive_path(
        self,
        db: AsyncSession,
        novel_id: str,
        map_id: str,
        path_id: str,
    ) -> Any:
        await self._ctx.require_map(db, novel_id, map_id)
        path = await self._require_path(db, novel_id, map_id, path_id)
        if path.status == "archived":
            return path
        await self._tree.assert_writable(
            db, novel_id, map_id, path_layer_id=path.path_layer_id
        )
        if path.locked:
            raise ConflictError("锁定线路不能归档", code="map_path_locked")
        return await self._paths.update(
            db,
            path,
            {"status": "archived", "archived_at": datetime.now(UTC)},
        )

    async def restore_path(
        self,
        db: AsyncSession,
        novel_id: str,
        map_id: str,
        path_id: str,
    ) -> Any:
        config = await self._ctx.require_map(db, novel_id, map_id)
        path = await self._require_path(db, novel_id, map_id, path_id)
        if path.status == "active":
            return path
        try:
            await self._validate_location(
                db,
                novel_id,
                str(path.start_location_entity_id)
                if path.start_location_entity_id
                else None,
            )
            await self._validate_location(
                db,
                novel_id,
                str(path.end_location_entity_id) if path.end_location_entity_id else None,
            )
        except (NotFoundError, ValidationError) as exc:
            raise ConflictError(
                "线路端点依赖已不可用，无法恢复",
                code="map_path_restore_dependency_conflict",
            ) from exc
        nid = parse_uuid(novel_id, "novel_id")
        nodes = await self._nodes.get_by_paths(db, nid, config.id, [path.id])
        if len(nodes) < 2:
            raise ConflictError(
                "线路几何已不完整，无法恢复",
                code="map_path_restore_dependency_conflict",
            )
        if any(
            node.q < 0
            or node.r < 0
            or node.q >= config.grid_width
            or node.r >= config.grid_height
            for node in nodes
        ):
            raise ConflictError(
                "线路几何已超出当前地图边界，无法恢复",
                code="map_path_restore_dependency_conflict",
            )
        await self._tree.assert_writable(
            db, novel_id, map_id, path_layer_id=path.path_layer_id
        )
        return await self._paths.update(
            db,
            path,
            {"status": "active", "archived_at": None},
        )

    async def archive_impact(
        self,
        db: AsyncSession,
        novel_id: str,
        map_id: str,
        path_id: str,
    ) -> MapPathArchiveImpactResponse:
        await self._ctx.require_map(db, novel_id, map_id)
        path = await self._require_path(db, novel_id, map_id, path_id)
        nid = parse_uuid(novel_id, "novel_id")
        rows = await db.execute(
            select(MapObservation).where(
                MapObservation.novel_id == nid,
            )
        )
        observation_count = sum(
            1
            for item in rows.scalars().all()
            if str((item.spatial_anchor or {}).get("path_id")) == str(path.id)
        )
        rows = await db.execute(
            select(MapFact).where(
                MapFact.novel_id == nid,
            )
        )
        fact_count = sum(
            1
            for item in rows.scalars().all()
            if str((item.spatial_anchor or {}).get("path_id")) == str(path.id)
        )
        return MapPathArchiveImpactResponse(
            path_id=str(path.id),
            observation_count=observation_count,
            fact_count=fact_count,
        )

    @staticmethod
    def _path_response(path: Any, nodes: list[Any]) -> MapPathResponse:
        return MapPathResponse.model_validate(
            {
                **{
                    field: getattr(path, field)
                    for field in (
                        "id",
                        "novel_id",
                        "map_id",
                        "path_layer_id",
                        "name",
                        "path_type",
                        "sort_order",
                        "visible",
                        "locked",
                        "opacity",
                        "min_zoom",
                        "max_zoom",
                        "start_location_entity_id",
                        "end_location_entity_id",
                        "status",
                        "archived_at",
                        "content_revision",
                        "meta",
                        "created_at",
                        "updated_at",
                    )
                },
                "style": MapPathStyle.model_validate(path.style_json or {}),
                "nodes": [MapPathNodeResponse.model_validate(node) for node in nodes],
            }
        )

    async def get_state(
        self,
        db: AsyncSession,
        novel_id: str,
        map_id: str,
        *,
        status: str = "active",
    ) -> MapPathStateResponse:
        config = await self._ctx.require_map(db, novel_id, map_id)
        nid = parse_uuid(novel_id, "novel_id")
        layers = await self._layers.get_by_map(db, nid, config.id)
        tree_nodes = await self._tree.ensure_default_tree(db, novel_id, map_id)
        leaf_by_layer = {
            node.path_layer_id: node for node in tree_nodes if node.path_layer_id
        }
        layer_responses = [
            MapPathLayerResponse.model_validate(
                {
                    "id": layer.id,
                    "novel_id": layer.novel_id,
                    "map_id": layer.map_id,
                    "category": layer.category,
                    "name": leaf_by_layer[layer.id].name,
                    "layer_node_id": leaf_by_layer[layer.id].id,
                    "created_at": layer.created_at,
                    "updated_at": layer.updated_at,
                }
            )
            for layer in layers
            if layer.id in leaf_by_layer
        ]
        paths = await self._paths.get_by_map(db, nid, config.id, status=status)
        all_nodes = await self._nodes.get_by_paths(
            db, nid, config.id, [path.id for path in paths]
        )
        by_path: dict[uuid.UUID, list[Any]] = defaultdict(list)
        for node in all_nodes:
            by_path[node.path_id].append(node)
        return MapPathStateResponse(
            map_id=map_id,
            editor_revision=config.editor_revision,
            layers=layer_responses,
            paths=[self._path_response(path, by_path[path.id]) for path in paths],
        )

    async def get_path(
        self,
        db: AsyncSession,
        novel_id: str,
        map_id: str,
        path_id: str,
    ) -> MapPathResponse:
        await self._ctx.require_map(db, novel_id, map_id)
        path = await self._require_path(db, novel_id, map_id, path_id)
        nid = parse_uuid(novel_id, "novel_id")
        nodes = await self._nodes.get_by_paths(db, nid, path.map_id, [path.id])
        return self._path_response(path, nodes)
