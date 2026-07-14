"""Read-only multi-map presence for world objects."""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.map_repositories import (
    MapConfigRepository,
    MapLayerNodeRepository,
    MapPresenceRepository,
)
from modules.world.map_schemas import (
    MapEntityPresenceItem,
    MapEntityPresenceResponse,
    MapOpenTarget,
)
from modules.world.services.map.map_context import MapContext


class MapEntityPresenceService:
    def __init__(
        self,
        *,
        presence_repo: MapPresenceRepository | None = None,
        config_repo: MapConfigRepository | None = None,
        context: MapContext | None = None,
        layer_node_repo: MapLayerNodeRepository | None = None,
    ) -> None:
        self._presence_repo = presence_repo or MapPresenceRepository()
        self._config_repo = config_repo or MapConfigRepository()
        self._ctx = context or MapContext(entity_repo=None)
        self._layer_node_repo = layer_node_repo or MapLayerNodeRepository()

    @staticmethod
    def _layer_dfs_ranks(nodes: list) -> dict[object, int]:
        by_id = {node.id: node for node in nodes}
        children: dict[object | None, list] = defaultdict(list)
        for node in nodes:
            parent_id = node.parent_id if node.parent_id in by_id else None
            children[parent_id].append(node)

        def sibling_key(node) -> tuple:
            created_at = getattr(node, "created_at", None)
            return (
                node.sort_order,
                created_at.isoformat() if created_at is not None else "",
                str(node.id),
            )

        ranks: dict[object, int] = {}

        def visit(node) -> None:
            if node.id in ranks:
                return
            ranks[node.id] = len(ranks)
            for child in sorted(children.get(node.id, []), key=sibling_key):
                visit(child)

        for root in sorted(children.get(None, []), key=sibling_key):
            visit(root)
        for node in sorted(nodes, key=sibling_key):
            visit(node)
        return ranks

    async def list_for_entity(
        self,
        db: AsyncSession,
        novel_id: str,
        entity_id: str,
        *,
        include_candidates: bool = False,
    ) -> MapEntityPresenceResponse:
        entity = await self._ctx.require_entity(db, novel_id, entity_id)
        if entity.status not in {"canonical", "candidate"}:
            return MapEntityPresenceResponse(entity_id=entity_id, total=0)
        if entity.status == "candidate" and not include_candidates:
            return MapEntityPresenceResponse(entity_id=entity_id, total=0)
        rows = await self._presence_repo.list_for_entity(
            db,
            entity.novel_id,
            entity.id,
            include_candidates=include_candidates,
        )
        by_map: dict[object, dict[str, list]] = defaultdict(
            lambda: {
                "bindings": [],
                "layouts": [],
                "markers": [],
                "territories": [],
                "terrain_bindings": [],
                "terrain_patches": [],
                "path_starts": [],
                "path_ends": [],
                "path_nodes": [],
            }
        )
        for kind, items in rows.items():
            for item in items:
                by_map[item.map_id][kind].append(item)

        configs = await self._config_repo.get_many_active_in_novel(
            db,
            entity.novel_id,
            list(by_map),
        )
        configs_by_id = {config.id: config for config in configs}
        layer_nodes_by_map: dict[object, list] = defaultdict(list)
        layer_nodes = await self._layer_node_repo.get_by_maps(
            db,
            entity.novel_id,
            list(configs_by_id),
        )
        for node in layer_nodes:
            layer_nodes_by_map[node.map_id].append(node)

        result: list[MapEntityPresenceItem] = []
        for map_id, placements in by_map.items():
            config = configs_by_id.get(map_id)
            if config is None:
                continue
            roles: list[str] = []
            if placements["layouts"] or placements["bindings"]:
                roles.append("location")
            roles.extend(
                f"marker.{marker.marker_type}" for marker in placements["markers"]
            )
            if placements["territories"]:
                roles.append("territory")
            if placements["terrain_bindings"]:
                roles.append("terrain")
            if placements["path_starts"]:
                roles.append("path.start")
            if placements["path_ends"]:
                roles.append("path.end")
            roles = list(dict.fromkeys(roles))

            layer_nodes = layer_nodes_by_map[map_id]
            leaf_by_layer = {
                node.path_layer_id: node for node in layer_nodes if node.path_layer_id
            }
            dfs_ranks = self._layer_dfs_ranks(layer_nodes)
            endpoint_roles: dict[object, set[str]] = defaultdict(set)
            paths_by_id = {}
            for path in placements["path_starts"]:
                paths_by_id[path.id] = path
                endpoint_roles[path.id].add("path.start")
            for path in placements["path_ends"]:
                paths_by_id[path.id] = path
                endpoint_roles[path.id].add("path.end")
            ordered_paths = sorted(
                paths_by_id.values(),
                key=lambda path: (
                    dfs_ranks.get(leaf_by_layer[path.path_layer_id].id, 10**6)
                    if path.path_layer_id in leaf_by_layer
                    else 10**6,
                    path.sort_order,
                    path.id,
                ),
            )
            path_refs = [
                {
                    "path_id": str(path.id),
                    "path_name": path.name,
                    "roles": sorted(endpoint_roles[path.id]),
                    "layer_node_id": (
                        str(leaf_by_layer[path.path_layer_id].id)
                        if path.path_layer_id in leaf_by_layer
                        else None
                    ),
                }
                for path in ordered_paths
            ]
            nodes_by_path: dict[object, list] = defaultdict(list)
            for node in placements["path_nodes"]:
                nodes_by_path[node.path_id].append(node)

            representative = None
            if placements["layouts"]:
                layout = sorted(
                    placements["layouts"], key=lambda item: (item.created_at, item.id)
                )[0]
                representative = (layout.center_hex_q, layout.center_hex_r)
            elif placements["bindings"]:
                binding = sorted(
                    placements["bindings"],
                    key=lambda item: (
                        not item.is_center,
                        item.hex_q,
                        item.hex_r,
                        item.id,
                    ),
                )[0]
                representative = (binding.hex_q, binding.hex_r)
            elif placements["markers"]:
                marker = sorted(
                    placements["markers"], key=lambda item: (item.created_at, item.id)
                )[0]
                representative = (marker.hex_q, marker.hex_r)
            elif placements["territories"]:
                territory = sorted(
                    placements["territories"],
                    key=lambda item: (item.hex_q, item.hex_r, item.id),
                )[0]
                representative = (territory.hex_q, territory.hex_r)
            elif placements["terrain_patches"]:
                patch = sorted(
                    placements["terrain_patches"],
                    key=lambda item: (item.hex_q, item.hex_r, item.id),
                )[0]
                representative = (patch.hex_q, patch.hex_r)
            elif ordered_paths:
                path = ordered_paths[0]
                path_nodes = sorted(
                    nodes_by_path[path.id], key=lambda node: (node.sort_order, node.id)
                )
                if path_nodes:
                    node = (
                        path_nodes[0]
                        if "path.start" in endpoint_roles[path.id]
                        else path_nodes[-1]
                    )
                    representative = (node.q, node.r)

            scene_indexes = [
                value
                for marker in placements["markers"]
                for value in (marker.start_scene_index, marker.end_scene_index)
                if value is not None
            ]
            binding_count = (
                len(placements["bindings"])
                or len(placements["layouts"])
            ) + len(placements["markers"]) + len(placements["territories"]) + len(
                placements["terrain_bindings"]
            ) + len(ordered_paths)
            active_placements = bool(
                placements["layouts"]
                or placements["bindings"]
                or placements["markers"]
                or placements["territories"]
                or any(
                    binding.review_state == "confirmed"
                    for binding in placements["terrain_bindings"]
                )
                or ordered_paths
            )
            primary_path = ordered_paths[0] if ordered_paths else None
            primary_leaf = (
                leaf_by_layer.get(primary_path.path_layer_id)
                if primary_path is not None
                else None
            )
            result.append(
                MapEntityPresenceItem(
                    map_id=str(config.id),
                    map_name=config.name,
                    roles=roles,
                    binding_count=binding_count,
                    representative_hex_q=(
                        round(representative[0]) if representative else None
                    ),
                    representative_hex_r=(
                        round(representative[1]) if representative else None
                    ),
                    representative_world_q=(
                        float(representative[0]) if representative else None
                    ),
                    representative_world_r=(
                        float(representative[1]) if representative else None
                    ),
                    path_refs=path_refs,
                    scene_index_min=min(scene_indexes) if scene_indexes else None,
                    scene_index_max=max(scene_indexes) if scene_indexes else None,
                    display_state=(
                        "active"
                        if entity.status == "canonical" and active_placements
                        else "review"
                    ),
                    open_target=MapOpenTarget(
                        mode="map",
                        map_id=str(config.id),
                        focus_entity_id=str(entity.id),
                        focus_path_id=(
                            str(primary_path.id) if primary_path is not None else None
                        ),
                        focus_layer_node_id=(
                            str(primary_leaf.id) if primary_leaf is not None else None
                        ),
                    ),
                )
            )
        result.sort(key=lambda item: (item.map_name, item.map_id))
        return MapEntityPresenceResponse(
            entity_id=str(entity.id),
            items=result,
            total=len(result),
        )
