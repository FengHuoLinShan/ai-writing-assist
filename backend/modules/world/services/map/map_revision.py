"""Map visual editor revision coordination and immutable reversible history."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, func, select
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ConflictError, NotFoundError, ValidationError
from modules.world.map_models import (
    MapConfig,
    MapLayerNode,
    MapLocationBinding,
    MapLocationLayout,
    MapMarker,
    MapPath,
    MapPathLayer,
    MapPathNode,
    MapTerrainBinding,
    MapTerrainLayer,
    MapTerrainPatch,
    MapTerrainRegion,
    MapTerritoryTile,
    MapTile,
    MapVisualRevision,
)
from modules.world.map_repositories import MapConfigRepository
from modules.world.map_schemas import (
    MapVisualRevisionListResponse,
    MapVisualRevisionResponse,
    MapVisualRevisionRestoreResponse,
)
from modules.world.services.common import parse_uuid
from modules.world.services.map.map_context import MapContext

_BASELINE_KEY = "map_visual_revision_baselines"
_RESOURCE_MODELS = (
    MapTile,
    MapLocationBinding,
    MapLocationLayout,
    MapTerrainLayer,
    MapPathLayer,
    MapLayerNode,
    MapPath,
    MapPathNode,
    MapTerrainRegion,
    MapTerrainPatch,
    MapTerrainBinding,
    MapMarker,
    MapTerritoryTile,
)
_MODEL_BY_TABLE = {model.__tablename__: model for model in _RESOURCE_MODELS}
_RESOURCE_TABLES = frozenset(_MODEL_BY_TABLE)
_CONFIG_STATE_FIELDS = (
    "name",
    "map_type",
    "description",
    "default_center_x",
    "default_center_y",
    "default_zoom",
    "grid_width",
    "grid_height",
    "hex_size",
    "parent_map_id",
    "parent_entity_id",
    "sort_order",
)


def _json_value(value: Any) -> Any:
    if isinstance(value, (uuid.UUID, datetime)):
        return value.isoformat() if isinstance(value, datetime) else str(value)
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _row_state(row: Any) -> dict[str, Any]:
    return {
        column.name: _json_value(getattr(row, column.name))
        for column in row.__table__.columns
        if column.name not in {"created_at", "updated_at"}
    }


def _resource_index(state: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    indexed: dict[tuple[str, str], dict[str, Any]] = {}
    for table, rows in state.get("resources", {}).items():
        for row in rows:
            indexed[(table, str(row["id"]))] = row
    indexed[("map_configs", str(state["map"]["id"]))] = state["map"]
    return indexed


def _changes(
    before: dict[str, Any],
    after: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    before_rows = _resource_index(before)
    after_rows = _resource_index(after)
    forward: list[dict[str, Any]] = []
    for key in sorted(set(before_rows) | set(after_rows)):
        old = before_rows.get(key)
        new = after_rows.get(key)
        if old == new:
            continue
        operation = "create" if old is None else "delete" if new is None else "update"
        forward.append(
            {
                "resource_type": key[0],
                "resource_id": key[1],
                "operation": operation,
                "before": old,
                "after": new,
            }
        )
    reverse_operation = {"create": "delete", "delete": "create", "update": "update"}
    reverse = [
        {
            **item,
            "operation": reverse_operation[item["operation"]],
            "before": item["after"],
            "after": item["before"],
        }
        for item in reversed(forward)
    ]
    return forward, reverse


class MapRevisionService:
    """Serialize visual writes, record history, and restore committed states."""

    def __init__(self, config_repo: MapConfigRepository | None = None) -> None:
        self._config_repo = config_repo or MapConfigRepository()
        self._ctx = MapContext()

    async def lock_visual_write(self, db: AsyncSession, map_id: str) -> None:
        """Use one lock order for legacy writes and atomic editor batches."""
        if db.get_bind().dialect.name != "postgresql":
            return
        await db.execute(
            select(func.pg_advisory_xact_lock(func.hashtextextended(map_id, 1)))
        )

    async def _snapshot(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        config: MapConfig,
    ) -> dict[str, Any]:
        resources: dict[str, list[dict[str, Any]]] = {}
        for model in _RESOURCE_MODELS:
            rows = list(
                (
                    await db.execute(
                        select(model).where(
                            model.novel_id == novel_id,
                            model.map_id == config.id,
                        )
                    )
                )
                .scalars()
                .all()
            )
            resources[model.__tablename__] = [
                _row_state(row) for row in sorted(rows, key=lambda item: str(item.id))
            ]
        return {
            "schema_version": 1,
            "map": {
                "id": str(config.id),
                "novel_id": str(config.novel_id),
                **{
                    field: _json_value(getattr(config, field))
                    for field in _CONFIG_STATE_FIELDS
                },
            },
            "resources": resources,
        }

    async def _capture_baseline(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        config: MapConfig,
    ) -> None:
        baselines = db.sync_session.info.setdefault(_BASELINE_KEY, {})
        key = (str(novel_id), str(config.id))
        baselines[key] = await self._snapshot(db, novel_id, config)

    async def lock_active(
        self,
        db: AsyncSession,
        novel_id: str,
        map_id: str,
        *,
        expected_revision: int | None = None,
    ) -> MapConfig:
        await self.lock_visual_write(db, map_id)
        nid = parse_uuid(novel_id, "novel_id")
        mid = parse_uuid(map_id, "map_id")
        config = await self._config_repo.get_in_novel(
            db,
            nid,
            mid,
            status="active",
            for_update=True,
        )
        if config is None:
            raise NotFoundError(f"地图 {map_id} 不存在", code="map_not_found")
        if expected_revision is not None and config.editor_revision != expected_revision:
            raise ConflictError(
                "地图已被其他编辑会话更新，请刷新后重新应用",
                code="map_editor_revision_conflict",
                context={
                    "expected_revision": expected_revision,
                    "current_revision": config.editor_revision,
                    "map_id": map_id,
                },
            )
        await self._capture_baseline(db, nid, config)
        return config

    async def bump(
        self,
        db: AsyncSession,
        novel_id: str,
        map_id: str,
        *,
        locked_config: MapConfig | None = None,
        operation: str = "legacy_edit",
        restored_from_revision: int | None = None,
    ) -> int:
        config = locked_config or await self.lock_active(db, novel_id, map_id)
        nid = parse_uuid(novel_id, "novel_id")
        baselines = db.sync_session.info.setdefault(_BASELINE_KEY, {})
        key = (str(nid), str(config.id))
        before = baselines.get(key)
        if before is None:
            raise RuntimeError("map visual revision baseline was not captured")
        await db.flush()
        after = await self._snapshot(db, nid, config)
        forward, reverse = _changes(before, after)
        existing_baseline = (
            await db.execute(
                select(MapVisualRevision.id).where(
                    MapVisualRevision.novel_id == nid,
                    MapVisualRevision.map_id == config.id,
                    MapVisualRevision.revision_number == config.editor_revision,
                )
            )
        ).scalar_one_or_none()
        if existing_baseline is None:
            db.add(
                MapVisualRevision(
                    novel_id=nid,
                    map_id=config.id,
                    revision_number=config.editor_revision,
                    operation="baseline",
                    restored_from_revision=None,
                    forward_changes=[],
                    reverse_changes=[],
                    state_json=before,
                )
            )
            await db.flush()
        revision_number = await self._config_repo.bump_revision(db, config)
        db.add(
            MapVisualRevision(
                novel_id=nid,
                map_id=config.id,
                revision_number=revision_number,
                operation=operation,
                restored_from_revision=restored_from_revision,
                forward_changes=forward,
                reverse_changes=reverse,
                state_json=after,
            )
        )
        await db.flush()
        baselines.pop(key, None)
        return revision_number

    async def list_revisions(
        self,
        db: AsyncSession,
        novel_id: str,
        map_id: str,
        *,
        skip: int = 0,
        limit: int = 50,
    ) -> MapVisualRevisionListResponse:
        config = await self._ctx.require_map(db, novel_id, map_id)
        nid = parse_uuid(novel_id, "novel_id")
        count = int(
            (
                await db.execute(
                    select(func.count(MapVisualRevision.id)).where(
                        MapVisualRevision.novel_id == nid,
                        MapVisualRevision.map_id == config.id,
                    )
                )
            ).scalar()
            or 0
        )
        rows = list(
            (
                await db.execute(
                    select(MapVisualRevision)
                    .where(
                        MapVisualRevision.novel_id == nid,
                        MapVisualRevision.map_id == config.id,
                    )
                    .order_by(MapVisualRevision.revision_number.desc())
                    .offset(skip)
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        return MapVisualRevisionListResponse(
            items=[MapVisualRevisionResponse.model_validate(row) for row in rows],
            total=count,
        )

    @staticmethod
    def _column_value(model: type, field: str, value: Any) -> Any:
        if value is None:
            return None
        column = model.__table__.columns[field]
        if isinstance(column.type, PG_UUID):
            return uuid.UUID(str(value))
        if isinstance(column.type, DateTime) and isinstance(value, str):
            return datetime.fromisoformat(value)
        return value

    async def _validate_restore_dependencies(
        self,
        db: AsyncSession,
        novel_id: str,
        config: MapConfig,
        state: dict[str, Any],
    ) -> None:
        resources = state.get("resources")
        if (
            state.get("schema_version") != 1
            or not isinstance(resources, dict)
            or set(resources) != _RESOURCE_TABLES
        ):
            raise ConflictError(
                "该地图历史版本格式已无法恢复",
                code="map_revision_schema_unsupported",
            )
        map_state = state.get("map") or {}
        canonical_novel_id = str(parse_uuid(novel_id, "novel_id"))
        if (
            not isinstance(map_state, dict)
            or set(map_state) != {"id", "novel_id", *_CONFIG_STATE_FIELDS}
            or map_state.get("id") != str(config.id)
            or map_state.get("novel_id") != canonical_novel_id
        ):
            raise ConflictError(
                "地图历史版本不属于当前项目或地图",
                code="map_revision_dependency_conflict",
            )
        for table, rows in resources.items():
            model = _MODEL_BY_TABLE[table]
            column_names = {
                column.name
                for column in model.__table__.columns
                if column.name not in {"created_at", "updated_at"}
            }
            if not isinstance(rows, list):
                raise ConflictError(
                    "地图历史版本的资源格式已损坏",
                    code="map_revision_dependency_conflict",
                )
            seen_ids: set[str] = set()
            for row in rows:
                if (
                    not isinstance(row, dict)
                    or not {"id", "novel_id", "map_id"}.issubset(row)
                    or set(row) != column_names
                    or str(row["novel_id"]) != canonical_novel_id
                    or str(row["map_id"]) != str(config.id)
                ):
                    raise ConflictError(
                        "地图历史版本包含越界或损坏的资源",
                        code="map_revision_dependency_conflict",
                    )
                try:
                    resource_id = str(uuid.UUID(str(row["id"])))
                except (TypeError, ValueError, AttributeError) as exc:
                    raise ConflictError(
                        "地图历史版本包含损坏的资源 ID",
                        code="map_revision_dependency_conflict",
                    ) from exc
                if resource_id in seen_ids:
                    raise ConflictError(
                        "地图历史版本包含重复资源",
                        code="map_revision_dependency_conflict",
                    )
                seen_ids.add(resource_id)

        nid = parse_uuid(novel_id, "novel_id")
        try:
            parent_map_id = (
                parse_uuid(map_state["parent_map_id"], "parent_map_id")
                if map_state.get("parent_map_id")
                else None
            )
        except ValidationError as exc:
            raise ConflictError(
                "恢复版本的父地图引用已损坏",
                code="map_revision_dependency_conflict",
            ) from exc
        if parent_map_id == config.id:
            raise ConflictError(
                "恢复版本会让地图成为自己的父级",
                code="map_revision_dependency_conflict",
            )
        if parent_map_id is not None:
            parent = await self._config_repo.get_in_novel(
                db,
                nid,
                parent_map_id,
                status="active",
                for_update=True,
            )
            subtree = await self._config_repo.lock_subtree(db, nid, config.id)
            if parent is None or parent_map_id in {item.id for item in subtree}:
                raise ConflictError(
                    "恢复版本的父地图已不可用或会形成循环",
                    code="map_revision_dependency_conflict",
                )
        if map_state.get("parent_entity_id"):
            try:
                await self._ctx.require_canonical_entity(
                    db,
                    novel_id,
                    str(map_state["parent_entity_id"]),
                    allowed_types={"location"},
                )
            except (NotFoundError, ValidationError) as exc:
                raise ConflictError(
                    "恢复版本的父地点已不可用",
                    code="map_revision_dependency_conflict",
                ) from exc
        same_name = await self._config_repo.get_by_name(
            db,
            nid,
            name=str(map_state.get("name") or config.name),
            parent_map_id=parent_map_id,
        )
        if same_name is not None and same_name.id != config.id:
            raise ConflictError(
                "恢复版本的地图名称已被同层级地图使用",
                code="map_revision_dependency_conflict",
            )

        terrain_layer_ids = {
            row["id"] for row in resources.get("map_terrain_layers", [])
        }
        path_layer_ids = {row["id"] for row in resources.get("map_path_layers", [])}
        terrain_regions = {
            row["id"]: row for row in resources.get("map_terrain_regions", [])
        }
        path_ids = {row["id"] for row in resources.get("map_paths", [])}
        for row in terrain_regions.values():
            if row["layer_id"] not in terrain_layer_ids:
                raise ConflictError(
                    "恢复版本引用的地形图层已损坏",
                    code="map_revision_dependency_conflict",
                )
        for row in resources.get("map_paths", []):
            if row["path_layer_id"] not in path_layer_ids:
                raise ConflictError(
                    "恢复版本引用的线路图层已损坏",
                    code="map_revision_dependency_conflict",
                )
        for row in resources.get("map_path_nodes", []):
            if row["path_id"] not in path_ids:
                raise ConflictError(
                    "恢复版本引用的线路节点已损坏",
                    code="map_revision_dependency_conflict",
                )
        for row in resources.get("map_terrain_patches", []):
            region = terrain_regions.get(row["region_id"])
            if region is None or row["layer_id"] != region["layer_id"]:
                raise ConflictError(
                    "恢复版本引用的地形块已损坏",
                    code="map_revision_dependency_conflict",
                )
        for row in resources.get("map_terrain_bindings", []):
            if row["region_id"] not in terrain_regions:
                raise ConflictError(
                    "恢复版本引用的地形绑定已损坏",
                    code="map_revision_dependency_conflict",
                )
        for row in resources.get("map_layer_nodes", []):
            terrain_id = row.get("terrain_layer_id")
            path_id = row.get("path_layer_id")
            if (terrain_id and terrain_id not in terrain_layer_ids) or (
                path_id and path_id not in path_layer_ids
            ):
                raise ConflictError(
                    "恢复版本引用的图层树已损坏",
                    code="map_revision_dependency_conflict",
                )

        entity_requirements: dict[str, set[str]] = {}
        for row in resources.get("map_location_bindings", []):
            entity_requirements.setdefault(row["location_entity_id"], set()).add(
                "location"
            )
        for row in resources.get("map_location_layouts", []):
            entity_requirements.setdefault(row["location_entity_id"], set()).add(
                "location"
            )
        for row in resources.get("map_terrain_bindings", []):
            entity_requirements.setdefault(row["location_entity_id"], set()).add(
                "location"
            )
        for row in resources.get("map_paths", []):
            if row.get("status", "active") != "active":
                continue
            for field in ("start_location_entity_id", "end_location_entity_id"):
                if row.get(field):
                    entity_requirements.setdefault(row[field], set()).add("location")
        for row in resources.get("map_markers", []):
            if row.get("status", "active") == "active":
                marker_types = {
                    "character": {"character"},
                    "event": {"event"},
                    "item": {"item"},
                }
                allowed_types = marker_types.get(row.get("marker_type"))
                if allowed_types is None:
                    raise ConflictError(
                        "恢复版本包含未知标记类型",
                        code="map_revision_dependency_conflict",
                    )
                entity_requirements.setdefault(row["entity_id"], set()).update(
                    allowed_types
                )
        for row in resources.get("map_territory_tiles", []):
            entity_requirements.setdefault(row["faction_entity_id"], set()).add(
                "organization"
            )
        try:
            for entity_id, allowed_types in entity_requirements.items():
                await self._ctx.require_canonical_entity(
                    db,
                    novel_id,
                    entity_id,
                    allowed_types=allowed_types or None,
                )
            from modules.outline.facade import get_scene_contract

            scene_ids = {
                row[field]
                for row in resources.get("map_markers", [])
                if row.get("status", "active") == "active"
                for field in ("start_scene_id", "end_scene_id")
                if row.get(field)
            }
            for scene_id in scene_ids:
                if await get_scene_contract(db, novel_id, scene_id) is None:
                    raise NotFoundError("Scene 不存在", code="scene_not_found")
        except (NotFoundError, ValidationError) as exc:
            raise ConflictError(
                "恢复版本依赖的对象或 Scene 已不可用",
                code="map_revision_dependency_conflict",
            ) from exc

        width = int(map_state.get("grid_width", config.grid_width))
        height = int(map_state.get("grid_height", config.grid_height))
        for table, q_field, r_field in (
            ("map_tiles", "hex_q", "hex_r"),
            ("map_location_bindings", "hex_q", "hex_r"),
            ("map_location_layouts", "center_hex_q", "center_hex_r"),
            ("map_terrain_patches", "hex_q", "hex_r"),
            ("map_markers", "hex_q", "hex_r"),
            ("map_territory_tiles", "hex_q", "hex_r"),
            ("map_path_nodes", "q", "r"),
        ):
            for row in resources.get(table, []):
                if not (0 <= row[q_field] < width and 0 <= row[r_field] < height):
                    raise ConflictError(
                        "恢复版本包含越界地图坐标",
                        code="map_revision_dependency_conflict",
                    )

    async def _apply_state(
        self,
        db: AsyncSession,
        config: MapConfig,
        state: dict[str, Any],
    ) -> None:
        resources = state["resources"]
        current: dict[str, dict[str, Any]] = {}
        for model in _RESOURCE_MODELS:
            current[model.__tablename__] = {
                str(row.id): row
                for row in (
                    (
                        await db.execute(
                            select(model).where(
                                model.novel_id == config.novel_id,
                                model.map_id == config.id,
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
            }

        desired = {
            table: {str(row["id"]): row for row in rows}
            for table, rows in resources.items()
            if table in _MODEL_BY_TABLE
        }
        retained_layer_ids = set(current["map_terrain_layers"]) - set(
            desired.get("map_terrain_layers", {})
        )
        retained_path_ids = set(current["map_paths"]) - set(desired.get("map_paths", {}))
        retained_region_ids = {
            str(row.id)
            for row in current["map_terrain_regions"].values()
            if str(row.layer_id) in retained_layer_ids
        }

        for table, rows in current.items():
            target_ids = set(desired.get(table, {}))
            for row_id, row in rows.items():
                if row_id in target_ids:
                    continue
                keep = (
                    table == "map_terrain_layers"
                    or table == "map_paths"
                    or table == "map_markers"
                    or (
                        table == "map_layer_nodes"
                        and (
                            str(row.terrain_layer_id) in retained_layer_ids
                            or str(row.path_layer_id)
                            in {
                                str(current["map_paths"][path_id].path_layer_id)
                                for path_id in retained_path_ids
                            }
                        )
                    )
                    or (
                        table in {"map_terrain_regions", "map_terrain_patches"}
                        and (
                            str(getattr(row, "layer_id", "")) in retained_layer_ids
                            or str(getattr(row, "region_id", "")) in retained_region_ids
                        )
                    )
                    or (
                        table == "map_terrain_bindings"
                        and str(row.region_id) in retained_region_ids
                    )
                    or (
                        table == "map_path_nodes"
                        and str(row.path_id) in retained_path_ids
                    )
                )
                if keep:
                    if table in {"map_terrain_layers", "map_paths", "map_markers"}:
                        row.status = "archived"
                        row.archived_at = datetime.now(UTC)
                    continue
                await db.delete(row)
        await db.flush()

        for model in _RESOURCE_MODELS:
            table = model.__tablename__
            for row_id, values in desired.get(table, {}).items():
                row = current[table].get(row_id)
                converted = {
                    field: self._column_value(model, field, value)
                    for field, value in values.items()
                    if field not in {"created_at", "updated_at"}
                }
                if row is None:
                    db.add(model(**converted))
                    continue
                for field, value in converted.items():
                    if field not in {"id", "novel_id", "map_id"}:
                        setattr(row, field, value)
        for field in _CONFIG_STATE_FIELDS:
            if field in state["map"]:
                setattr(
                    config,
                    field,
                    self._column_value(MapConfig, field, state["map"][field]),
                )
        await db.flush()

    async def restore_revision(
        self,
        db: AsyncSession,
        novel_id: str,
        map_id: str,
        revision_number: int,
        *,
        expected_revision: int,
    ) -> MapVisualRevisionRestoreResponse:
        async with db.begin_nested():
            await self._config_repo.lock_hierarchy(
                db,
                parse_uuid(novel_id, "novel_id"),
            )
            config = await self.lock_active(
                db,
                novel_id,
                map_id,
                expected_revision=expected_revision,
            )
            nid = parse_uuid(novel_id, "novel_id")
            target = (
                await db.execute(
                    select(MapVisualRevision).where(
                        MapVisualRevision.novel_id == nid,
                        MapVisualRevision.map_id == config.id,
                        MapVisualRevision.revision_number == revision_number,
                    )
                )
            ).scalar_one_or_none()
            if target is None:
                raise NotFoundError(
                    "地图视觉历史版本不存在",
                    code="map_visual_revision_not_found",
                )
            await self._validate_restore_dependencies(
                db,
                novel_id,
                config,
                target.state_json,
            )
            await self._apply_state(db, config, target.state_json)
            next_revision = await self.bump(
                db,
                novel_id,
                map_id,
                locked_config=config,
                operation="revision_restore",
                restored_from_revision=revision_number,
            )
            return MapVisualRevisionRestoreResponse(
                map_id=map_id,
                editor_revision=next_revision,
                restored_from_revision=revision_number,
            )
