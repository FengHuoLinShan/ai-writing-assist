"""Atomic map editor command application."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import NotFoundError, ValidationError
from modules.world.map_repositories import (
    MapLocationBindingRepository,
    MapLocationLayoutRepository,
    MapMarkerRepository,
    MapPathLayerRepository,
    MapPathNodeRepository,
    MapPathRepository,
    MapTerrainLayerRepository,
    MapTerrainPatchRepository,
    MapTerritoryRepository,
)
from modules.world.map_schemas import (
    MapEditorApplyRequest,
    MapEditorApplyResponse,
    MapLocationLayoutReplaceRequest,
    MapTerrainPatchReplaceRequest,
    MapTerritoryCreate,
    MapTileBatchUpdate,
)
from modules.world.services.common import parse_uuid
from modules.world.services.map.map_layer_tree import MapLayerTreeService
from modules.world.services.map.map_location_binding_service import (
    MapLocationBindingService,
)
from modules.world.services.map.map_location_layout import MapLocationLayoutService
from modules.world.services.map.map_marker_service import MapMarkerService
from modules.world.services.map.map_path import MapPathService
from modules.world.services.map.map_revision import MapRevisionService
from modules.world.services.map.map_terrain import MapTerrainService
from modules.world.services.map.map_territory_service import MapTerritoryService
from modules.world.services.map.map_tile_service import MapTileService

_MAX_CHANGED_HEXES = 20_000
_MAX_CHANGED_PATH_NODES = 2_000


class MapEditorApplyService:
    """Validate and apply a visual command batch under one map row lock."""

    def __init__(self) -> None:
        self._revision = MapRevisionService()
        self._tiles = MapTileService()
        self._layouts = MapLocationLayoutService()
        self._bindings = MapLocationBindingService()
        self._terrain = MapTerrainService()
        self._markers = MapMarkerService()
        self._paths = MapPathService()
        self._territories = MapTerritoryService()
        self._layer_tree = MapLayerTreeService()
        self._terrain_repo = MapTerrainLayerRepository()
        self._terrain_patch_repo = MapTerrainPatchRepository()
        self._territory_repo = MapTerritoryRepository()
        self._marker_repo = MapMarkerRepository()
        self._path_layer_repo = MapPathLayerRepository()
        self._path_node_repo = MapPathNodeRepository()
        self._path_repo = MapPathRepository()
        self._layout_repo = MapLocationLayoutRepository()
        self._binding_repo = MapLocationBindingRepository()

    async def _preflight(
        self,
        db: AsyncSession,
        novel_id: str,
        map_id: str,
        data: MapEditorApplyRequest,
    ) -> tuple[dict[str, str], dict[str, str]]:
        nid = parse_uuid(novel_id, "novel_id")
        mid = parse_uuid(map_id, "map_id")
        existing_bindings = await self._binding_repo.get_by_map(db, nid, mid)
        existing_patches = await self._terrain_patch_repo.get_by_map(db, nid, mid)
        existing_territories = await self._territory_repo.get_by_map(db, nid, mid)
        path_update_ids = [
            parse_uuid(command.ref.id, "path_id")
            for command in data.commands
            if command.type == "path_update"
            and command.ref.id
            and (
                command.data.nodes is not None
                or command.data.snap_start
                or command.data.snap_end
            )
        ]
        existing_path_node_counts: dict[uuid.UUID, int] = {}
        for node in await self._path_node_repo.get_by_paths(
            db,
            nid,
            mid,
            path_update_ids,
        ):
            existing_path_node_counts[node.path_id] = (
                existing_path_node_counts.get(node.path_id, 0) + 1
            )
        client_id_map: dict[str, str] = {}
        client_kind: dict[str, str] = {}
        seen_clients: set[str] = set()
        path_leaf_clients: set[str] = set()
        tree_node_clients: set[str] = set()

        def declare(client_id: str, kind: str, *, allow_same_node: bool = False) -> None:
            if client_id in client_id_map:
                if (
                    allow_same_node
                    and kind == "layer_node"
                    and client_kind.get(client_id) == "layer_node"
                ):
                    return
                raise ValidationError(
                    f"client_id {client_id!r} 重复",
                    code="duplicate_map_client_id",
                )
            # Client identifiers are correlation aliases only.  Even a UUID-shaped
            # alias never controls the formal persisted resource identifier.
            client_id_map[client_id] = str(uuid.uuid4())
            client_kind[client_id] = kind

        for command in data.commands:
            if command.type == "terrain_layer_create":
                declare(command.client_id, "terrain")
            elif command.type == "marker_create":
                declare(command.client_id, "marker")
            elif command.type == "path_layer_create":
                declare(command.client_id, "path_layer")
                declare(command.leaf_client_id, "layer_node")
                path_leaf_clients.add(command.leaf_client_id)
            elif command.type == "path_create":
                declare(command.client_id, "path")
            elif command.type == "layer_tree_replace":
                for node in command.nodes:
                    if node.client_id:
                        if node.client_id in tree_node_clients:
                            raise ValidationError(
                                f"client_id {node.client_id!r} 重复",
                                code="duplicate_map_client_id",
                            )
                        declare(
                            node.client_id,
                            "layer_node",
                            allow_same_node=node.client_id in path_leaf_clients,
                        )
                        tree_node_clients.add(node.client_id)

        changed_hexes = 0
        changed_path_nodes = 0
        tree_indexes = [
            index
            for index, command in enumerate(data.commands)
            if command.type == "layer_tree_replace"
        ]
        if len(tree_indexes) > 1:
            raise ValidationError(
                "每批最多一个 layer_tree_replace",
                code="duplicate_map_layer_tree_command",
            )
        if tree_indexes:
            tree_index = tree_indexes[0]
            if any(
                index > tree_index
                and command.type in {"path_layer_create", "path_layer_delete"}
                for index, command in enumerate(data.commands)
            ):
                raise ValidationError(
                    "path layer 创建或删除必须位于图层树替换之前",
                    code="invalid_map_command_order",
                )
        binding_count = len(existing_bindings)
        patch_counts: dict[str, int] = {}
        for patch in existing_patches:
            key = str(patch.layer_id)
            patch_counts[key] = patch_counts.get(key, 0) + 1
        territory_counts: dict[str, int] = {}
        for territory in existing_territories:
            key = str(territory.faction_entity_id)
            territory_counts[key] = territory_counts.get(key, 0) + 1
        existing_layouts = {
            item.location_entity_id: (
                item.center_hex_q,
                item.center_hex_r,
            )
            for item in await self._layout_repo.get_by_map(db, nid, mid)
        }
        location_binding_counts: dict[uuid.UUID, int] = {}
        for binding in existing_bindings:
            location_binding_counts[binding.location_entity_id] = (
                location_binding_counts.get(binding.location_entity_id, 0) + 1
            )

        for command in data.commands:
            match command.type:
                case "base_terrain_replace":
                    changed_hexes += len(command.changes)
                case "location_binding_replace":
                    next_count = sum(len(item.hexes) for item in command.items)
                    changed_hexes += binding_count + next_count
                    binding_count = next_count
                    location_binding_counts = {
                        parse_uuid(item.location_entity_id, "location_entity_id"): len(
                            item.hexes
                        )
                        for item in command.items
                    }
                case "location_layout_replace" if command.sync_bindings:
                    for layout in command.layouts:
                        entity_id = parse_uuid(
                            layout.location_entity_id, "location_entity_id"
                        )
                        next_center = (layout.center_hex_q, layout.center_hex_r)
                        if existing_layouts.get(entity_id) != next_center:
                            changed_hexes += max(
                                1,
                                location_binding_counts.get(entity_id, 0),
                            )
                        existing_layouts[entity_id] = next_center
                case "terrain_patch_replace":
                    layer_key = (
                        str(parse_uuid(command.layer_ref.id, "terrain_layer_id"))
                        if command.layer_ref.id
                        else client_id_map.get(
                            command.layer_ref.client_id,
                            f"client:{command.layer_ref.client_id}",
                        )
                    )
                    next_count = len(command.data.patches)
                    changed_hexes += patch_counts.get(layer_key, 0) + next_count
                    patch_counts[layer_key] = next_count
                case "terrain_layer_delete":
                    layer_key = (
                        str(parse_uuid(command.ref.id, "terrain_layer_id"))
                        if command.ref.id
                        else client_id_map.get(
                            command.ref.client_id,
                            f"client:{command.ref.client_id}",
                        )
                    )
                    changed_hexes += patch_counts.get(layer_key, 0)
                    patch_counts[layer_key] = 0
                case "territory_replace":
                    faction_key = str(
                        parse_uuid(command.faction_entity_id, "faction_entity_id")
                    )
                    next_count = len(command.hexes)
                    changed_hexes += territory_counts.get(faction_key, 0) + next_count
                    territory_counts[faction_key] = next_count
                case "path_create":
                    changed_path_nodes += len(command.data.nodes)
                case "path_update" if command.data.nodes is not None:
                    if command.ref.id:
                        path_id = parse_uuid(command.ref.id, "path_id")
                        changed_path_nodes += existing_path_node_counts.get(path_id, 0)
                    changed_path_nodes += len(command.data.nodes)
                case "path_update" if command.data.snap_start or command.data.snap_end:
                    if command.ref.id:
                        path_id = parse_uuid(command.ref.id, "path_id")
                        changed_path_nodes += 2 * existing_path_node_counts.get(
                            path_id, 0
                        )
        if changed_hexes > _MAX_CHANGED_HEXES:
            raise ValidationError(
                f"单批展开后的 hex 变更不能超过 {_MAX_CHANGED_HEXES}",
                code="map_editor_hex_limit",
            )
        if changed_path_nodes > _MAX_CHANGED_PATH_NODES:
            raise ValidationError(
                f"单批线路节点变更不能超过 {_MAX_CHANGED_PATH_NODES}",
                code="map_editor_path_node_limit",
            )

        deleted_resources: set[tuple[str, str]] = set()

        async def validate_ref(ref, kind: str) -> None:
            if ref.client_id:
                if (
                    ref.client_id not in seen_clients
                    or client_kind.get(ref.client_id) != kind
                ):
                    raise ValidationError(
                        "client_id 只能在对应创建命令之后引用",
                        code="invalid_map_client_reference",
                    )
                return
            resource_id = parse_uuid(ref.id, f"{kind}_id")
            if (kind, str(resource_id)) in deleted_resources:
                raise ValidationError(
                    "已删除资源不能在同一批次继续引用",
                    code="invalid_map_command_order",
                )
            if kind == "terrain":
                resource = await self._terrain_repo.get_in_map(db, nid, mid, resource_id)
            elif kind == "marker":
                resource = await self._marker_repo.get_in_map(db, nid, mid, resource_id)
            elif kind == "path_layer":
                resource = await self._path_layer_repo.get_in_map(
                    db, nid, mid, resource_id
                )
            else:
                resource = await self._path_repo.get_in_map(db, nid, mid, resource_id)
            if resource is None:
                raise NotFoundError(
                    f"{kind} resource 不属于当前地图",
                    code=f"map_{kind}_not_found",
                )

        tree_count = 0
        modified_resources: set[tuple[str, str]] = set()

        def modification_key(ref, kind: str) -> tuple[str, str]:
            resource_id = ref.id or client_id_map.get(ref.client_id, "")
            return kind, resource_id

        def mark_modified(ref, kind: str) -> None:
            key = modification_key(ref, kind)
            if key in modified_resources:
                raise ValidationError(
                    "同一批不能重复修改同一地图资源",
                    code="duplicate_map_resource_command",
                )
            modified_resources.add(key)

        for command in data.commands:
            match command.type:
                case "terrain_layer_create" | "marker_create":
                    seen_clients.add(command.client_id)
                case "path_layer_create":
                    seen_clients.add(command.client_id)
                    seen_clients.add(command.leaf_client_id)
                case "terrain_layer_update" | "terrain_layer_delete":
                    await validate_ref(command.ref, "terrain")
                    mark_modified(command.ref, "terrain")
                    if command.type == "terrain_layer_delete":
                        deleted_resources.add(modification_key(command.ref, "terrain"))
                case "terrain_patch_replace":
                    await validate_ref(command.layer_ref, "terrain")
                case "marker_update" | "marker_delete":
                    await validate_ref(command.ref, "marker")
                    mark_modified(command.ref, "marker")
                    if command.type == "marker_delete":
                        deleted_resources.add(modification_key(command.ref, "marker"))
                case "path_layer_delete":
                    await validate_ref(command.ref, "path_layer")
                    if command.ref.client_id:
                        raise ValidationError(
                            "新建 path layer 不能在同批删除",
                            code="invalid_map_command_order",
                        )
                    mark_modified(command.ref, "path_layer")
                    deleted_resources.add(modification_key(command.ref, "path_layer"))
                case "path_create":
                    seen_clients.add(command.client_id)
                    await validate_ref(command.data.layer_ref, "path_layer")
                case "path_update":
                    await validate_ref(command.ref, "path")
                    if command.ref.client_id:
                        raise ValidationError(
                            "新建 path 不能在同批再更新",
                            code="invalid_map_command_order",
                        )
                    if command.data.layer_ref:
                        await validate_ref(command.data.layer_ref, "path_layer")
                    mark_modified(command.ref, "path")
                case "path_archive" | "path_restore":
                    await validate_ref(command.ref, "path")
                    if command.ref.client_id:
                        raise ValidationError(
                            "新建 path 不能在同批归档或恢复",
                            code="invalid_map_command_order",
                        )
                    mark_modified(command.ref, "path")
                case "layer_tree_replace":
                    tree_count += 1
                    if tree_count > 1:
                        raise ValidationError(
                            "每批最多一个 layer_tree_replace",
                            code="duplicate_map_layer_tree_command",
                        )
                    for node in command.nodes:
                        if node.terrain_layer_client_id:
                            client_id = node.terrain_layer_client_id
                            if (
                                client_id not in seen_clients
                                or client_kind.get(client_id) != "terrain"
                            ):
                                raise ValidationError(
                                    "图层树只能引用此前创建的 terrain client_id",
                                    code="invalid_map_client_reference",
                                )
                        if node.path_layer_client_id:
                            client_id = node.path_layer_client_id
                            if (
                                client_id not in seen_clients
                                or client_kind.get(client_id) != "path_layer"
                            ):
                                raise ValidationError(
                                    "图层树只能引用此前创建的 path layer client_id",
                                    code="invalid_map_client_reference",
                                )
        return client_id_map, client_kind

    @staticmethod
    def _resolve_ref(ref, client_id_map: dict[str, str]) -> str:
        if ref.id:
            return ref.id
        try:
            return client_id_map[ref.client_id]
        except KeyError as exc:
            raise ValidationError(
                "未知 client_id", code="invalid_map_client_reference"
            ) from exc

    async def apply(
        self,
        db: AsyncSession,
        novel_id: str,
        map_id: str,
        data: MapEditorApplyRequest,
    ) -> MapEditorApplyResponse:
        # The request dependency owns the outer transaction.  A savepoint keeps
        # the batch atomic even for injected sessions and callers that catch a
        # DomainError without rolling back the surrounding unit of work.
        async with db.begin_nested():
            return await self._apply_in_transaction(db, novel_id, map_id, data)

    async def _apply_in_transaction(
        self,
        db: AsyncSession,
        novel_id: str,
        map_id: str,
        data: MapEditorApplyRequest,
    ) -> MapEditorApplyResponse:
        locked_config = await self._revision.lock_active(
            db,
            novel_id,
            map_id,
            expected_revision=data.expected_revision,
        )
        client_id_map, client_kind = await self._preflight(db, novel_id, map_id, data)
        results: list[dict] = []
        for index, command in enumerate(data.commands):
            result: dict = {"index": index, "type": command.type}
            match command.type:
                case "base_terrain_replace":
                    rows = await self._tiles.batch_update(
                        db,
                        novel_id,
                        map_id,
                        MapTileBatchUpdate(changes=command.changes),
                        bump_revision=False,
                    )
                    result["count"] = len(rows)
                case "location_layout_replace":
                    rows = await self._layouts.replace(
                        db,
                        novel_id,
                        map_id,
                        MapLocationLayoutReplaceRequest(
                            layouts=command.layouts,
                            sync_bindings=command.sync_bindings,
                        ),
                        bump_revision=False,
                    )
                    result["count"] = rows.total
                case "location_binding_replace":
                    await self._bindings.clear_map(
                        db, novel_id, map_id, bump_revision=False
                    )
                    rows = await self._bindings.batch_create_many(
                        db,
                        novel_id,
                        map_id,
                        command.items,
                        bump_revision=False,
                    )
                    result["count"] = len(rows)
                case "terrain_layer_create":
                    layer_id = client_id_map[command.client_id]
                    state = await self._terrain.replace_layer_patches(
                        db,
                        novel_id,
                        map_id,
                        layer_id,
                        MapTerrainPatchReplaceRequest(
                            layer=command.data,
                            regions=[],
                            patches=[],
                        ),
                        bump_revision=False,
                    )
                    result.update({"id": layer_id, "count": len(state.layers)})
                case "terrain_layer_update":
                    layer_id = self._resolve_ref(command.ref, client_id_map)
                    row = await self._terrain.update_layer(
                        db,
                        novel_id,
                        map_id,
                        layer_id,
                        command.data,
                        bump_revision=False,
                    )
                    result["id"] = row.id
                case "terrain_layer_delete":
                    layer_id = self._resolve_ref(command.ref, client_id_map)
                    row = await self._terrain.delete_layer(
                        db,
                        novel_id,
                        map_id,
                        layer_id,
                        bump_revision=False,
                    )
                    result.update(row.model_dump())
                case "terrain_patch_replace":
                    layer_id = self._resolve_ref(command.layer_ref, client_id_map)
                    patch_data = command.data
                    if command.layer_ref.client_id:
                        client_layer_id = command.layer_ref.client_id
                        try:
                            comparable_client_layer_id = str(uuid.UUID(client_layer_id))
                        except (TypeError, ValueError, AttributeError):
                            comparable_client_layer_id = client_layer_id
                        if any(
                            region.layer_id != comparable_client_layer_id
                            for region in patch_data.regions
                        ):
                            raise ValidationError(
                                "region.layer_id 必须等于同批新建图层的 client_id",
                                code="invalid_terrain_region_layer",
                            )
                        # Re-validate the rewritten nested models: model_copy(update=...)
                        # would bypass Pydantic validators for the changed fields.
                        patch_data = MapTerrainPatchReplaceRequest.model_validate(
                            {
                                **patch_data.model_dump(),
                                "regions": [
                                    {
                                        **region.model_dump(),
                                        "layer_id": layer_id,
                                    }
                                    for region in patch_data.regions
                                ],
                            }
                        )
                    state = await self._terrain.replace_layer_patches(
                        db,
                        novel_id,
                        map_id,
                        layer_id,
                        patch_data,
                        bump_revision=False,
                    )
                    result["count"] = len(state.patches)
                case "path_layer_create":
                    layer_id = client_id_map[command.client_id]
                    leaf_id = client_id_map[command.leaf_client_id]
                    layer, leaf = await self._paths.create_layer(
                        db,
                        novel_id,
                        map_id,
                        layer_id=layer_id,
                        leaf_id=leaf_id,
                        display_name=command.display_name,
                        category=command.category,
                        meta=command.meta,
                    )
                    result.update({"id": str(layer.id), "leaf_id": str(leaf.id)})
                case "path_layer_delete":
                    layer_id = self._resolve_ref(command.ref, client_id_map)
                    result["id"] = await self._paths.delete_layer(
                        db, novel_id, map_id, layer_id
                    )
                case "path_create":
                    path_id = client_id_map[command.client_id]
                    layer_id = self._resolve_ref(command.data.layer_ref, client_id_map)
                    row = await self._paths.create_path(
                        db,
                        novel_id,
                        map_id,
                        path_id=path_id,
                        layer_id=layer_id,
                        data=command.data,
                    )
                    result.update(
                        {"id": str(row.id), "content_revision": row.content_revision}
                    )
                case "path_update":
                    path_id = self._resolve_ref(command.ref, client_id_map)
                    target_layer_id = (
                        self._resolve_ref(command.data.layer_ref, client_id_map)
                        if command.data.layer_ref
                        else None
                    )
                    row = await self._paths.update_path(
                        db,
                        novel_id,
                        map_id,
                        path_id,
                        command.data,
                        target_layer_id=target_layer_id,
                    )
                    result.update(
                        {"id": str(row.id), "content_revision": row.content_revision}
                    )
                case "path_archive":
                    path_id = self._resolve_ref(command.ref, client_id_map)
                    row = await self._paths.archive_path(db, novel_id, map_id, path_id)
                    result.update({"id": str(row.id), "status": row.status})
                case "path_restore":
                    path_id = self._resolve_ref(command.ref, client_id_map)
                    row = await self._paths.restore_path(db, novel_id, map_id, path_id)
                    result.update({"id": str(row.id), "status": row.status})
                case "marker_create":
                    marker_id = parse_uuid(client_id_map[command.client_id], "marker_id")
                    row = await self._markers.create(
                        db,
                        novel_id,
                        map_id,
                        command.data,
                        bump_revision=False,
                        id_override=marker_id,
                    )
                    result["id"] = row.id
                case "marker_update":
                    marker_id = self._resolve_ref(command.ref, client_id_map)
                    row = await self._markers.update(
                        db,
                        novel_id,
                        marker_id,
                        command.data,
                        map_id=map_id,
                        bump_revision=False,
                    )
                    result["id"] = row.id
                case "marker_delete":
                    marker_id = self._resolve_ref(command.ref, client_id_map)
                    await self._markers.delete(
                        db,
                        novel_id,
                        marker_id,
                        map_id=map_id,
                        bump_revision=False,
                    )
                    result["id"] = marker_id
                case "territory_replace":
                    await self._territories.delete_by_faction(
                        db,
                        novel_id,
                        map_id,
                        command.faction_entity_id,
                        bump_revision=False,
                    )
                    rows = []
                    if command.hexes:
                        rows = await self._territories.create(
                            db,
                            novel_id,
                            map_id,
                            MapTerritoryCreate(
                                faction_entity_id=command.faction_entity_id,
                                hexes=command.hexes,
                            ),
                            bump_revision=False,
                        )
                    result["count"] = len(rows)
                case "layer_tree_replace":
                    terrain_clients = {
                        key: value
                        for key, value in client_id_map.items()
                        if client_kind.get(key) == "terrain"
                    }
                    path_clients = {
                        key: value
                        for key, value in client_id_map.items()
                        if client_kind.get(key) == "path_layer"
                    }
                    node_clients = {
                        key: value
                        for key, value in client_id_map.items()
                        if client_kind.get(key) == "layer_node"
                    }
                    tree, node_ids = await self._layer_tree.replace_tree(
                        db,
                        novel_id,
                        map_id,
                        command.nodes,
                        terrain_client_ids=terrain_clients,
                        path_client_ids=path_clients,
                        node_client_ids=node_clients,
                    )
                    client_id_map.update(node_ids)
                    result["count"] = len(tree.nodes)
            results.append(result)

        revision = await self._revision.bump(
            db,
            novel_id,
            map_id,
            locked_config=locked_config,
        )
        return MapEditorApplyResponse(
            map_id=map_id,
            editor_revision=revision,
            command_results=results,
            client_id_map=client_id_map,
        )
