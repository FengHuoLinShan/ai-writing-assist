"""Recursive layer tree, inherited display state, and lock enforcement."""

from __future__ import annotations

import uuid
from collections import defaultdict
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ConflictError, NotFoundError, ValidationError
from modules.world.map_repositories import (
    MapLayerNodeRepository,
    MapPathLayerRepository,
    MapTerrainLayerRepository,
)
from modules.world.map_schemas import (
    MapLayerNodeResponse,
    MapLayerNodeWrite,
    MapLayerTreeResponse,
)
from modules.world.services.common import parse_uuid
from modules.world.services.map.map_context import MapContext
from modules.world.services.map.map_revision import MapRevisionService

_MAX_DEPTH = 8
_SINGLETON_KEYS = {
    "baseTerrain",
    "location",
    "marker",
    "marker.character",
    "marker.event",
    "marker.item",
    "territory",
    "terrainOverlay",
    "path",
    "pending",
}
_GROUP_KEYS = {"marker", "terrainOverlay", "path"}


class MapLayerTreeService:
    def __init__(
        self,
        *,
        node_repo: MapLayerNodeRepository | None = None,
        terrain_repo: MapTerrainLayerRepository | None = None,
        path_layer_repo: MapPathLayerRepository | None = None,
        context: MapContext | None = None,
    ) -> None:
        self._node_repo = node_repo or MapLayerNodeRepository()
        self._terrain_repo = terrain_repo or MapTerrainLayerRepository()
        self._path_layer_repo = path_layer_repo or MapPathLayerRepository()
        self._ctx = context or MapContext()
        self._revision = MapRevisionService()

    @staticmethod
    def _default_values(
        map_id: uuid.UUID,
        terrain_layers: list[Any],
        path_layers: list[Any] | None = None,
    ) -> list[dict[str, Any]]:
        ids = {key: uuid.uuid5(map_id, f"map-layer:{key}") for key in _SINGLETON_KEYS}
        values: list[dict[str, Any]] = []
        roots = (
            ("baseTerrain", "底图", "leaf", 0),
            ("location", "地点", "leaf", 1),
            ("marker", "标记", "group", 2),
            ("territory", "领地", "leaf", 3),
            ("terrainOverlay", "覆盖素材", "group", 4),
            ("path", "线路", "group", 5),
            ("pending", "待处理", "leaf", 6),
        )
        for key, name, node_type, order in roots:
            values.append(
                {
                    "id": ids[key],
                    "parent_id": None,
                    "terrain_layer_id": None,
                    "path_layer_id": None,
                    "node_type": node_type,
                    "layer_key": key,
                    "name": name,
                    "visible": True,
                    "locked": False,
                    "opacity": 1.0,
                    "sort_order": order,
                    "selection_mode": "normal",
                    "floor_level": None,
                    "meta": {},
                }
            )
        for order, (key, name) in enumerate(
            (
                ("marker.character", "人物"),
                ("marker.event", "事件"),
                ("marker.item", "物品"),
            )
        ):
            values.append(
                {
                    "id": ids[key],
                    "parent_id": ids["marker"],
                    "terrain_layer_id": None,
                    "path_layer_id": None,
                    "node_type": "leaf",
                    "layer_key": key,
                    "name": name,
                    "visible": True,
                    "locked": False,
                    "opacity": 1.0,
                    "sort_order": order,
                    "selection_mode": "normal",
                    "floor_level": None,
                    "meta": {},
                }
            )
        for order, layer in enumerate(terrain_layers):
            values.append(
                {
                    "id": uuid.uuid5(layer.id, "map-layer:terrain"),
                    "parent_id": ids["terrainOverlay"],
                    "terrain_layer_id": layer.id,
                    "path_layer_id": None,
                    "node_type": "leaf",
                    "layer_key": None,
                    "name": layer.name,
                    "visible": layer.visible,
                    "locked": layer.locked,
                    "opacity": layer.opacity,
                    "sort_order": order,
                    "selection_mode": "normal",
                    "floor_level": None,
                    "meta": {},
                }
            )
        for order, layer in enumerate(path_layers or []):
            values.append(
                {
                    "id": uuid.uuid5(layer.id, "map-layer:path"),
                    "parent_id": ids["path"],
                    "terrain_layer_id": None,
                    "path_layer_id": layer.id,
                    "node_type": "leaf",
                    "layer_key": None,
                    "name": f"线路 {order + 1}",
                    "visible": True,
                    "locked": False,
                    "opacity": 1.0,
                    "sort_order": order,
                    "selection_mode": "normal",
                    "floor_level": None,
                    "meta": {},
                }
            )
        return values

    async def ensure_default_tree(
        self,
        db: AsyncSession,
        novel_id: str,
        map_id: str,
    ) -> list[Any]:
        config = await self._ctx.require_map(db, novel_id, map_id)
        nid = parse_uuid(novel_id, "novel_id")
        nodes = await self._node_repo.get_by_map(db, nid, config.id)
        layers = await self._terrain_repo.get_by_map(db, nid, config.id)
        path_layers = await self._path_layer_repo.get_by_map(db, nid, config.id)
        if not nodes:
            return await self._node_repo.create_many(
                db,
                nid,
                config.id,
                self._default_values(config.id, layers, path_layers),
            )

        path_group = next((node for node in nodes if node.layer_key == "path"), None)
        if path_group is None:
            root_order = max(
                (node.sort_order for node in nodes if node.parent_id is None),
                default=-1,
            ) + 1
            created = await self._node_repo.create(
                db,
                nid,
                config.id,
                {
                    "id": uuid.uuid5(config.id, "map-layer:path"),
                    "parent_id": None,
                    "terrain_layer_id": None,
                    "path_layer_id": None,
                    "node_type": "group",
                    "layer_key": "path",
                    "name": "线路",
                    "visible": True,
                    "locked": False,
                    "opacity": 1.0,
                    "sort_order": root_order,
                    "selection_mode": "normal",
                    "floor_level": None,
                    "meta": {},
                },
            )
            nodes.append(created)
            path_group = created

        terrain_ids = {node.terrain_layer_id for node in nodes if node.terrain_layer_id}
        overlay = next(
            (node for node in nodes if node.layer_key == "terrainOverlay"), None
        )
        if overlay is None:
            raise ConflictError(
                "地图图层树缺少覆盖素材组",
                code="map_layer_tree_corrupted",
            )
        missing = [layer for layer in layers if layer.id not in terrain_ids]
        if missing:
            next_order = max(
                (node.sort_order for node in nodes if node.parent_id == overlay.id),
                default=-1,
            ) + 1
            created = await self._node_repo.create_many(
                db,
                nid,
                config.id,
                [
                    {
                        "id": uuid.uuid5(layer.id, "map-layer:terrain"),
                        "parent_id": overlay.id,
                        "terrain_layer_id": layer.id,
                        "path_layer_id": None,
                        "node_type": "leaf",
                        "layer_key": None,
                        "name": layer.name,
                        "visible": layer.visible,
                        "locked": layer.locked,
                        "opacity": layer.opacity,
                        "sort_order": next_order + index,
                        "selection_mode": "normal",
                        "floor_level": None,
                        "meta": {},
                    }
                    for index, layer in enumerate(missing)
                ],
            )
            nodes.extend(created)

        path_ids = {node.path_layer_id for node in nodes if node.path_layer_id}
        missing_paths = [layer for layer in path_layers if layer.id not in path_ids]
        if missing_paths:
            next_order = max(
                (node.sort_order for node in nodes if node.parent_id == path_group.id),
                default=-1,
            ) + 1
            created = await self._node_repo.create_many(
                db,
                nid,
                config.id,
                [
                    {
                        "id": uuid.uuid5(layer.id, "map-layer:path"),
                        "parent_id": path_group.id,
                        "terrain_layer_id": None,
                        "path_layer_id": layer.id,
                        "node_type": "leaf",
                        "layer_key": None,
                        "name": f"线路 {next_order + index + 1}",
                        "visible": True,
                        "locked": False,
                        "opacity": 1.0,
                        "sort_order": next_order + index,
                        "selection_mode": "normal",
                        "floor_level": None,
                        "meta": {},
                    }
                    for index, layer in enumerate(missing_paths)
                ],
            )
            nodes.extend(created)
        return nodes

    @staticmethod
    def _ordered(nodes: list[Any]) -> tuple[list[Any], dict[uuid.UUID, dict[str, Any]]]:
        by_id = {node.id: node for node in nodes}
        children: dict[uuid.UUID | None, list[Any]] = defaultdict(list)
        for node in nodes:
            children[node.parent_id].append(node)
        for siblings in children.values():
            siblings.sort(key=lambda item: (item.sort_order, item.created_at, item.id))

        ordered: list[Any] = []
        effective: dict[uuid.UUID, dict[str, Any]] = {}

        def visit(node, parent_state: dict[str, Any] | None, depth: int) -> None:
            min_zoom = node.min_zoom
            max_zoom = node.max_zoom
            if parent_state:
                parent_min = parent_state["min_zoom"]
                parent_max = parent_state["max_zoom"]
                if parent_min is not None:
                    min_zoom = (
                        max(min_zoom, parent_min)
                        if min_zoom is not None
                        else parent_min
                    )
                if parent_max is not None:
                    max_zoom = (
                        min(max_zoom, parent_max)
                        if max_zoom is not None
                        else parent_max
                    )
            zoom_visible = not (
                min_zoom is not None and max_zoom is not None and min_zoom > max_zoom
            )
            state = {
                "visible": node.visible
                and (parent_state["visible"] if parent_state else True)
                and zoom_visible,
                "locked": node.locked
                or (parent_state["locked"] if parent_state else False),
                "opacity": node.opacity
                * (parent_state["opacity"] if parent_state else 1.0),
                "min_zoom": min_zoom,
                "max_zoom": max_zoom,
                "depth": depth,
            }
            effective[node.id] = state
            ordered.append(node)
            for child in children.get(node.id, []):
                visit(child, state, depth + 1)

        for root in children.get(None, []):
            visit(root, None, 1)
        if len(ordered) != len(by_id):
            raise ConflictError("地图图层树存在循环", code="map_layer_tree_corrupted")
        return ordered, effective

    async def get_tree(
        self,
        db: AsyncSession,
        novel_id: str,
        map_id: str,
    ) -> MapLayerTreeResponse:
        config = await self._ctx.require_map(db, novel_id, map_id)
        nodes = await self.ensure_default_tree(db, novel_id, map_id)
        ordered, effective = self._ordered(nodes)
        responses = []
        for node in ordered:
            state = effective[node.id]
            responses.append(
                MapLayerNodeResponse.model_validate(
                    {
                        **{
                            field: getattr(node, field)
                            for field in (
                                "id",
                                "novel_id",
                                "map_id",
                                "parent_id",
                                "terrain_layer_id",
                                "path_layer_id",
                                "node_type",
                                "layer_key",
                                "name",
                                "visible",
                                "locked",
                                "opacity",
                                "sort_order",
                                "min_zoom",
                                "max_zoom",
                                "selection_mode",
                                "floor_level",
                                "meta",
                            )
                        },
                        "effective_visible": state["visible"],
                        "effective_locked": state["locked"],
                        "effective_opacity": state["opacity"],
                        "effective_min_zoom": state["min_zoom"],
                        "effective_max_zoom": state["max_zoom"],
                        "depth": state["depth"],
                    }
                )
            )
        return MapLayerTreeResponse(
            map_id=map_id,
            editor_revision=config.editor_revision,
            nodes=responses,
        )

    async def assert_writable(
        self,
        db: AsyncSession,
        novel_id: str,
        map_id: str,
        *,
        layer_key: str | None = None,
        terrain_layer_id: str | uuid.UUID | None = None,
        path_layer_id: str | uuid.UUID | None = None,
        error_code: str = "map_layer_locked",
    ) -> None:
        await self._revision.lock_visual_write(db, map_id)
        nodes = await self.ensure_default_tree(db, novel_id, map_id)
        target = None
        if terrain_layer_id is not None:
            parsed = (
                terrain_layer_id
                if isinstance(terrain_layer_id, uuid.UUID)
                else parse_uuid(terrain_layer_id, "terrain_layer_id")
            )
            target = next(
                (node for node in nodes if node.terrain_layer_id == parsed), None
            )
        elif path_layer_id is not None:
            parsed = (
                path_layer_id
                if isinstance(path_layer_id, uuid.UUID)
                else parse_uuid(path_layer_id, "path_layer_id")
            )
            target = next((node for node in nodes if node.path_layer_id == parsed), None)
        elif layer_key is not None:
            target = next((node for node in nodes if node.layer_key == layer_key), None)
        if target is None:
            raise NotFoundError("地图图层不存在", code="map_layer_node_not_found")
        _, effective = self._ordered(nodes)
        if effective[target.id]["locked"]:
            raise ConflictError("图层已锁定，请先解锁", code=error_code)

    async def replace_tree(
        self,
        db: AsyncSession,
        novel_id: str,
        map_id: str,
        items: list[MapLayerNodeWrite],
        *,
        terrain_client_ids: dict[str, str] | None = None,
        path_client_ids: dict[str, str] | None = None,
        node_client_ids: dict[str, str] | None = None,
    ) -> tuple[MapLayerTreeResponse, dict[str, str]]:
        config = await self._ctx.require_map(db, novel_id, map_id)
        nid = parse_uuid(novel_id, "novel_id")
        existing = await self.ensure_default_tree(db, novel_id, map_id)
        _, existing_effective = self._ordered(existing)
        terrain_layers = await self._terrain_repo.get_by_map(db, nid, config.id)
        terrain_ids = {str(layer.id) for layer in terrain_layers}
        path_layers = await self._path_layer_repo.get_by_map(db, nid, config.id)
        path_ids = {str(layer.id) for layer in path_layers}
        terrain_client_ids = terrain_client_ids or {}
        path_client_ids = path_client_ids or {}
        node_client_ids = node_client_ids or {}

        client_id_map: dict[str, str] = {}
        for item in items:
            if item.client_id:
                if item.client_id in client_id_map:
                    raise ValidationError(
                        "layer tree client_id 重复", code="duplicate_map_client_id"
                    )
                client_id_map[item.client_id] = node_client_ids.get(
                    item.client_id, str(uuid.uuid4())
                )
        resolved_ids = {
            item.id or client_id_map[item.client_id]
            for item in items
            if item.id or item.client_id
        }
        if len(resolved_ids) != len(items):
            raise ValidationError("图层节点 ID 重复", code="duplicate_map_layer_node")

        submitted_ids = [
            parse_uuid(item.id, "layer_node_id") for item in items if item.id
        ]
        submitted_existing = await self._node_repo.get_existing_by_ids(
            db, submitted_ids
        )
        if len(submitted_existing) != len(submitted_ids) or any(
            node.novel_id != nid or node.map_id != config.id
            for node in submitted_existing
        ):
            raise ValidationError(
                "图层节点或 parent 不属于当前地图",
                code="invalid_map_layer_parent",
            )

        values: list[dict[str, Any]] = []
        seen_keys: set[str] = set()
        seen_terrain: set[str] = set()
        seen_path: set[str] = set()
        sibling_orders: set[tuple[str | None, int]] = set()
        for item in items:
            node_id = item.id or client_id_map[item.client_id]
            parent_id = item.parent_id
            if item.parent_client_id:
                parent_id = client_id_map.get(item.parent_client_id)
                if parent_id is None:
                    raise ValidationError(
                        "未知 parent_client_id", code="invalid_map_layer_parent"
                    )
            if parent_id and parent_id not in resolved_ids:
                raise ValidationError(
                    "parent 必须来自当前地图的完整图层树",
                    code="invalid_map_layer_parent",
                )
            terrain_id = item.terrain_layer_id
            if item.terrain_layer_client_id:
                terrain_id = terrain_client_ids.get(item.terrain_layer_client_id)
                if terrain_id is None:
                    raise ValidationError(
                        "未知 terrain_layer_client_id",
                        code="invalid_map_terrain_reference",
                    )
            if terrain_id:
                if terrain_id not in terrain_ids:
                    raise ValidationError(
                        "terrain layer 不属于当前地图",
                        code="invalid_map_terrain_reference",
                    )
                if terrain_id in seen_terrain:
                    raise ValidationError(
                        "每个 terrain layer 只能对应一个 leaf",
                        code="duplicate_map_terrain_leaf",
                    )
                seen_terrain.add(terrain_id)
            path_id = item.path_layer_id
            if item.path_layer_client_id:
                path_id = path_client_ids.get(item.path_layer_client_id)
                if path_id is None:
                    raise ValidationError(
                        "未知 path_layer_client_id",
                        code="invalid_map_path_reference",
                    )
            if path_id:
                if path_id not in path_ids:
                    raise ValidationError(
                        "path layer 不属于当前地图",
                        code="invalid_map_path_reference",
                    )
                if path_id in seen_path:
                    raise ValidationError(
                        "每个 path layer 只能对应一个 leaf",
                        code="duplicate_map_path_leaf",
                    )
                seen_path.add(path_id)
            if terrain_id and path_id:
                raise ValidationError(
                    "leaf 不能同时绑定 terrain 和 path layer",
                    code="invalid_map_layer_resource",
                )
            if item.layer_key:
                if item.layer_key in seen_keys:
                    raise ValidationError(
                        "singleton layer 重复", code="duplicate_map_layer_key"
                    )
                seen_keys.add(item.layer_key)
                expected_type = "group" if item.layer_key in _GROUP_KEYS else "leaf"
                if item.node_type != expected_type:
                    raise ValidationError(
                        f"{item.layer_key} 必须是 {expected_type}",
                        code="invalid_map_singleton_node_type",
                    )
                if terrain_id or path_id:
                    raise ValidationError(
                        "singleton 节点不能同时绑定 terrain layer",
                        code="invalid_map_terrain_reference",
                    )
            elif item.node_type == "leaf" and not (terrain_id or path_id):
                raise ValidationError(
                    "普通 leaf 必须绑定 terrain 或 path layer",
                    code="invalid_map_layer_resource",
                )
            if item.node_type == "leaf" and item.selection_mode != "normal":
                raise ValidationError(
                    "leaf 必须使用 normal 选择模式",
                    code="invalid_map_layer_selection_mode",
                )
            sibling_key = (parent_id, item.sort_order)
            if sibling_key in sibling_orders:
                raise ValidationError(
                    "同一组内 sort_order 重复", code="duplicate_map_layer_order"
                )
            sibling_orders.add(sibling_key)
            values.append(
                {
                    "id": parse_uuid(node_id, "layer_node_id"),
                    "parent_id": (
                        parse_uuid(parent_id, "parent_id") if parent_id else None
                    ),
                    "terrain_layer_id": (
                        parse_uuid(terrain_id, "terrain_layer_id") if terrain_id else None
                    ),
                    "path_layer_id": (
                        parse_uuid(path_id, "path_layer_id") if path_id else None
                    ),
                    "node_type": item.node_type,
                    "layer_key": item.layer_key,
                    "name": item.name,
                    "visible": item.visible,
                    "locked": item.locked,
                    "opacity": item.opacity,
                    "sort_order": item.sort_order,
                    "min_zoom": item.min_zoom,
                    "max_zoom": item.max_zoom,
                    "selection_mode": item.selection_mode,
                    "floor_level": item.floor_level,
                    "meta": item.meta or {},
                }
            )

        if seen_keys != _SINGLETON_KEYS:
            raise ValidationError(
                "完整图层树必须包含全部 singleton 节点",
                code="incomplete_map_layer_tree",
                context={"missing": sorted(_SINGLETON_KEYS - seen_keys)},
            )
        if seen_terrain != terrain_ids:
            raise ValidationError(
                "完整图层树必须包含全部 terrain leaf",
                code="incomplete_map_terrain_layers",
            )
        if seen_path != path_ids:
            raise ValidationError(
                "完整图层树必须包含全部 path leaf",
                code="incomplete_map_path_layers",
            )

        values_by_id = {str(value["id"]): value for value in values}
        children: dict[str, list[str]] = defaultdict(list)
        for value in values:
            if value["parent_id"]:
                children[str(value["parent_id"])].append(str(value["id"]))
        for value in values:
            node_id = str(value["id"])
            if value["node_type"] == "leaf" and children.get(node_id):
                raise ValidationError(
                    "leaf 不能包含子节点", code="map_layer_leaf_children"
                )
            depth = 1
            cursor = value["parent_id"]
            visited = {node_id}
            while cursor is not None:
                cursor_str = str(cursor)
                if cursor_str in visited:
                    raise ValidationError("图层树存在循环", code="map_layer_cycle")
                visited.add(cursor_str)
                depth += 1
                if depth > _MAX_DEPTH:
                    raise ValidationError(
                        f"图层树最大深度为 {_MAX_DEPTH}", code="map_layer_depth"
                    )
                cursor = values_by_id[cursor_str]["parent_id"]

        floor_levels: dict[str, set[int]] = defaultdict(set)
        for value in values:
            parent_id = value["parent_id"]
            if parent_id is None:
                if value["floor_level"] is not None:
                    raise ValidationError(
                        "顶层节点不能设置 floor_level",
                        code="invalid_map_floor_level",
                    )
                continue
            parent = values_by_id[str(parent_id)]
            if parent["selection_mode"] == "floor":
                if value["floor_level"] is None:
                    raise ValidationError(
                        "floor 分组的直接子节点必须设置 floor_level",
                        code="invalid_map_floor_level",
                    )
                parent_key = str(parent_id)
                if value["floor_level"] in floor_levels[parent_key]:
                    raise ValidationError(
                        "floor 分组内 floor_level 重复",
                        code="duplicate_map_floor_level",
                    )
                floor_levels[parent_key].add(value["floor_level"])
            elif value["floor_level"] is not None:
                raise ValidationError(
                    "floor_level 只能用于 floor 分组的直接子节点",
                    code="invalid_map_floor_level",
                )

        # Locked nodes may only be explicitly unlocked; descendants of a locked
        # ancestor require a separate unlock save before structural changes.
        comparable_fields = (
            "parent_id",
            "terrain_layer_id",
            "path_layer_id",
            "node_type",
            "layer_key",
            "name",
            "visible",
            "opacity",
            "sort_order",
            "min_zoom",
            "max_zoom",
            "selection_mode",
            "floor_level",
            "meta",
        )
        for old in existing:
            if not existing_effective[old.id]["locked"]:
                continue
            new = values_by_id.get(str(old.id))
            if new is None:
                raise ConflictError("锁定图层不能删除", code="map_layer_locked")
            unchanged = all(
                getattr(old, field) == new[field] for field in comparable_fields
            )
            locally_unlocking = old.locked and new["locked"] is False and unchanged
            fully_unchanged = unchanged and old.locked == new["locked"]
            if not (locally_unlocking or fully_unchanged):
                raise ConflictError("锁定图层不能移动或编辑", code="map_layer_locked")

        old_children: dict[str, set[str]] = defaultdict(set)
        new_children: dict[str, set[str]] = defaultdict(set)
        for node in existing:
            if node.parent_id is not None:
                old_children[str(node.parent_id)].add(str(node.id))
        for node_id, value in values_by_id.items():
            if value["parent_id"] is not None:
                new_children[str(value["parent_id"])].add(node_id)
        for old in existing:
            if old.node_type != "group" or not existing_effective[old.id]["locked"]:
                continue
            if old_children[str(old.id)] != new_children[str(old.id)]:
                raise ConflictError(
                    "锁定分组不能新增、移入或移出子图层",
                    code="map_layer_locked",
                )

        await self._node_repo.delete_for_map(db, nid, config.id)
        await self._node_repo.create_many(db, nid, config.id, values)
        await self._project_terrain_layers(db, novel_id, map_id)
        return await self.get_tree(db, novel_id, map_id), client_id_map

    async def create_terrain_leaf(
        self,
        db: AsyncSession,
        novel_id: str,
        map_id: str,
        terrain_layer_id: str,
    ) -> None:
        await self.assert_writable(
            db, novel_id, map_id, layer_key="terrainOverlay"
        )
        await self.ensure_default_tree(db, novel_id, map_id)
        nid = parse_uuid(novel_id, "novel_id")
        mid = parse_uuid(map_id, "map_id")
        lid = parse_uuid(terrain_layer_id, "terrain_layer_id")
        if await self._node_repo.get_by_terrain_layer(db, nid, mid, lid):
            return
        layer = await self._terrain_repo.get_in_map(db, nid, mid, lid)
        overlay = await self._node_repo.get_by_layer_key(
            db, nid, mid, "terrainOverlay"
        )
        if layer is None or overlay is None:
            raise NotFoundError(
                "terrain layer 不存在", code="map_terrain_layer_not_found"
            )
        siblings = [
            node
            for node in await self._node_repo.get_by_map(db, nid, mid)
            if node.parent_id == overlay.id
        ]
        await self._node_repo.create(
            db,
            nid,
            mid,
            {
                "id": uuid.uuid5(layer.id, "map-layer:terrain"),
                "parent_id": overlay.id,
                "terrain_layer_id": layer.id,
                "path_layer_id": None,
                "node_type": "leaf",
                "layer_key": None,
                "name": layer.name,
                "visible": layer.visible,
                "locked": layer.locked,
                "opacity": layer.opacity,
                "sort_order": len(siblings),
                "selection_mode": "normal",
                "floor_level": None,
                "meta": {},
            },
        )
        await self._project_terrain_layers(db, novel_id, map_id)

    async def create_path_leaf(
        self,
        db: AsyncSession,
        novel_id: str,
        map_id: str,
        path_layer_id: str,
        *,
        display_name: str,
        node_id: str | uuid.UUID | None = None,
    ) -> Any:
        # The path service validates the parent group lock immediately before it
        # creates the layer.  Re-running ensure_default_tree here would observe
        # the just-created layer and synthesize a generic leaf name first.
        nid = parse_uuid(novel_id, "novel_id")
        mid = parse_uuid(map_id, "map_id")
        lid = parse_uuid(path_layer_id, "path_layer_id")
        existing = await self._node_repo.get_by_path_layer(db, nid, mid, lid)
        if existing is not None:
            return existing
        layer = await self._path_layer_repo.get_in_map(db, nid, mid, lid)
        group = await self._node_repo.get_by_layer_key(db, nid, mid, "path")
        if layer is None or group is None:
            raise NotFoundError("path layer 不存在", code="map_path_layer_not_found")
        siblings = [
            node
            for node in await self._node_repo.get_by_map(db, nid, mid)
            if node.parent_id == group.id
        ]
        resolved_node_id = (
            node_id
            if isinstance(node_id, uuid.UUID)
            else parse_uuid(node_id, "layer_node_id")
            if node_id
            else uuid.uuid5(layer.id, "map-layer:path")
        )
        return await self._node_repo.create(
            db,
            nid,
            mid,
            {
                "id": resolved_node_id,
                "parent_id": group.id,
                "terrain_layer_id": None,
                "path_layer_id": layer.id,
                "node_type": "leaf",
                "layer_key": None,
                "name": display_name,
                "visible": True,
                "locked": False,
                "opacity": 1.0,
                "sort_order": len(siblings),
                "selection_mode": "normal",
                "floor_level": None,
                "meta": {},
            },
        )

    async def update_terrain_leaf_from_legacy(
        self,
        db: AsyncSession,
        novel_id: str,
        map_id: str,
        terrain_layer_id: str,
        values: dict[str, Any],
    ) -> None:
        nodes = await self.ensure_default_tree(db, novel_id, map_id)
        lid = parse_uuid(terrain_layer_id, "terrain_layer_id")
        node = next((item for item in nodes if item.terrain_layer_id == lid), None)
        if node is None:
            raise NotFoundError("terrain leaf 不存在", code="map_layer_node_not_found")
        if any(field in values for field in ("name", "visible", "locked", "opacity")):
            node_values = {
                field: values[field]
                for field in ("name", "visible", "locked", "opacity")
                if field in values
            }
            await self._node_repo.update(db, node, node_values)
        if "z_index" in values:
            siblings = sorted(
                (item for item in nodes if item.parent_id == node.parent_id),
                key=lambda item: (item.sort_order, item.created_at, item.id),
            )
            siblings.remove(node)
            target = max(0, min(int(values["z_index"]), len(siblings)))
            siblings.insert(target, node)
            for index, sibling in enumerate(siblings):
                sibling.sort_order = index
                db.add(sibling)
            await db.flush()
        await self._project_terrain_layers(db, novel_id, map_id)

    async def _project_terrain_layers(
        self,
        db: AsyncSession,
        novel_id: str,
        map_id: str,
    ) -> None:
        nid = parse_uuid(novel_id, "novel_id")
        mid = parse_uuid(map_id, "map_id")
        nodes = await self._node_repo.get_by_map(db, nid, mid)
        ordered, _ = self._ordered(nodes)
        layers = {
            layer.id: layer for layer in await self._terrain_repo.get_by_map(db, nid, mid)
        }
        z_index = 0
        for node in ordered:
            if node.terrain_layer_id is None:
                continue
            layer = layers.get(node.terrain_layer_id)
            if layer is None:
                continue
            await self._terrain_repo.update(
                db,
                layer,
                {
                    "name": node.name,
                    "visible": node.visible,
                    "locked": node.locked,
                    "opacity": node.opacity,
                    "z_index": z_index,
                },
            )
            z_index += 1

    async def sync_terrain_projection(
        self,
        db: AsyncSession,
        novel_id: str,
        map_id: str,
    ) -> None:
        """Recompute legacy terrain fields after a leaf is cascade-deleted."""
        await self._project_terrain_layers(db, novel_id, map_id)
