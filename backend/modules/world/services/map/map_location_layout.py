"""地点布局服务。

保存快速创建和用户拖拽后的地图布局节点；默认不修改世界事实。
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ValidationError
from modules.world.map_repositories import (
    MapFactRepository,
    MapLocationBindingRepository,
    MapLocationLayoutRepository,
)
from modules.world.map_schemas import (
    MapLocationLayoutListResponse,
    MapLocationLayoutReplaceRequest,
    MapLocationLayoutResponse,
)
from modules.world.services.common import parse_uuid
from modules.world.services.map.map_context import MapContext
from modules.world.services.map.map_layer_tree import MapLayerTreeService
from modules.world.services.map.map_revision import MapRevisionService


class MapLocationLayoutService:
    """地点布局节点服务。"""

    def __init__(
        self,
        *,
        layout_repo: MapLocationLayoutRepository | None = None,
        binding_repo: MapLocationBindingRepository | None = None,
        fact_repo: MapFactRepository | None = None,
        context: MapContext | None = None,
    ) -> None:
        self._layout_repo = layout_repo or MapLocationLayoutRepository()
        self._binding_repo = binding_repo or MapLocationBindingRepository()
        self._fact_repo = fact_repo or MapFactRepository()
        self._ctx = context or MapContext()
        self._layer_tree = MapLayerTreeService(context=self._ctx)
        self._revision = MapRevisionService()

    async def list(
        self,
        db: AsyncSession,
        novel_id: str,
        map_id: str,
    ) -> MapLocationLayoutListResponse:
        await self._ctx.require_map(db, novel_id, map_id)
        nid = parse_uuid(novel_id, "novel_id")
        mid = parse_uuid(map_id, "map_id")
        layouts = await self._layout_repo.get_by_map_for_entity_statuses(
            db,
            nid,
            mid,
            statuses=["canonical"],
        )
        return MapLocationLayoutListResponse(
            items=[
                MapLocationLayoutResponse.model_validate(layout) for layout in layouts
            ],
            total=len(layouts),
        )

    async def replace(
        self,
        db: AsyncSession,
        novel_id: str,
        map_id: str,
        data: MapLocationLayoutReplaceRequest,
        *,
        bump_revision: bool = True,
    ) -> MapLocationLayoutListResponse:
        locked_config = (
            await self._revision.lock_active(db, novel_id, map_id)
            if bump_revision and db is not None
            else None
        )
        config = await self._ctx.require_map(db, novel_id, map_id)
        if db is not None:
            await self._layer_tree.assert_writable(
                db, novel_id, map_id, layer_key="location"
            )
        nid = parse_uuid(novel_id, "novel_id")
        mid = parse_uuid(map_id, "map_id")
        seen: set[str] = set()
        location_entity_ids: list[str] = []
        values = []
        for item in data.layouts:
            if item.location_entity_id in seen:
                raise ValidationError(
                    "同一地点在同一地图只能有一个布局节点",
                    code="duplicate_location_layout",
                )
            seen.add(item.location_entity_id)
            location_entity_ids.append(item.location_entity_id)
            self._ctx.assert_hex_in_bounds(config, item.center_hex_q, item.center_hex_r)
        await self._ctx.require_canonical_entities(
            db,
            novel_id,
            location_entity_ids,
            allowed_types={"location"},
        )
        binding_values: dict[str, list[dict]] = {}
        moved_location_ids = []
        if data.sync_bindings:
            existing_layouts = await self._layout_repo.get_by_map(db, nid, mid)
            existing_bindings = await self._binding_repo.get_by_map(db, nid, mid)
            old_layout_by_location = {
                str(layout.location_entity_id): layout for layout in existing_layouts
            }
            bindings_by_location: dict[str, list] = {}
            for binding in existing_bindings:
                bindings_by_location.setdefault(
                    str(binding.location_entity_id), []
                ).append(binding)
            for item in data.layouts:
                location_id = item.location_entity_id
                bindings = bindings_by_location.get(location_id, [])
                old_layout = old_layout_by_location.get(location_id)
                old_anchor = self._resolve_anchor(old_layout, bindings)
                new_anchor = (item.center_hex_q, item.center_hex_r)
                if (
                    old_layout is not None
                    and old_layout.locked
                    and item.locked
                    and old_anchor != new_anchor
                ):
                    raise ValidationError(
                        "已锁定的地点需要先解锁再移动",
                        code="locked_location_layout",
                    )
                delta_q = new_anchor[0] - old_anchor[0] if old_anchor else 0
                delta_r = new_anchor[1] - old_anchor[1] if old_anchor else 0
                translated = []
                for binding in bindings:
                    hex_q = binding.hex_q + delta_q
                    hex_r = binding.hex_r + delta_r
                    self._ctx.assert_hex_in_bounds(config, hex_q, hex_r)
                    translated.append(
                        {
                            "location_entity_id": binding.location_entity_id,
                            "hex_q": hex_q,
                            "hex_r": hex_r,
                            "is_center": False,
                            "label_override": binding.label_override,
                            "style_override": binding.style_override,
                        }
                    )
                center_candidates = [
                    value
                    for value in translated
                    if (value["hex_q"], value["hex_r"]) == new_anchor
                ]
                if center_candidates:
                    center_candidates[0]["is_center"] = True
                else:
                    translated.append(
                        {
                            "location_entity_id": parse_uuid(
                                location_id, "location_entity_id"
                            ),
                            "hex_q": new_anchor[0],
                            "hex_r": new_anchor[1],
                            "is_center": True,
                            "label_override": None,
                            "style_override": None,
                        }
                    )
                binding_values[location_id] = translated
                if old_anchor is not None and old_anchor != new_anchor:
                    moved_location_ids.append(
                        parse_uuid(location_id, "location_entity_id")
                    )
        for item in data.layouts:
            values.append(
                {
                    "location_entity_id": parse_uuid(
                        item.location_entity_id, "location_entity_id"
                    ),
                    "center_hex_q": item.center_hex_q,
                    "center_hex_r": item.center_hex_r,
                    "occupy_radius": item.occupy_radius,
                    "locked": item.locked,
                    "layout_source": item.layout_source,
                    "layout_version": item.layout_version,
                    "sync_geo_setting": item.sync_geo_setting,
                    "meta": item.meta or {},
                }
            )
        layouts = await self._layout_repo.replace_for_map(db, nid, mid, values)
        if data.sync_bindings and binding_values:
            affected_ids = [
                parse_uuid(location_id, "location_entity_id")
                for location_id in binding_values
            ]
            await self._binding_repo.delete_for_locations(
                db,
                nid,
                mid,
                affected_ids,
            )
            await self._binding_repo.bulk_create_many(
                db,
                nid,
                mid,
                [
                    value
                    for location_values in binding_values.values()
                    for value in location_values
                ],
            )
        if moved_location_ids:
            await self._fact_repo.deprecate_quick_create_location_facts(
                db,
                nid,
                mid,
                location_entity_ids=moved_location_ids,
                reason="location_layout_edit",
            )
        if bump_revision and db is not None:
            await self._revision.bump(
                db,
                novel_id,
                map_id,
                locked_config=locked_config,
            )
        return MapLocationLayoutListResponse(
            items=[
                MapLocationLayoutResponse.model_validate(layout) for layout in layouts
            ],
            total=len(layouts),
        )

    @staticmethod
    def _resolve_anchor(old_layout, bindings) -> tuple[int, int] | None:
        if old_layout is not None:
            return old_layout.center_hex_q, old_layout.center_hex_r
        if not bindings:
            return None
        centers = sorted(
            (binding for binding in bindings if binding.is_center),
            key=lambda binding: (binding.hex_q, binding.hex_r, str(binding.id)),
        )
        if centers:
            return centers[0].hex_q, centers[0].hex_r
        mean_q = sum(binding.hex_q for binding in bindings) / len(bindings)
        mean_r = sum(binding.hex_r for binding in bindings) / len(bindings)

        def sort_key(binding) -> tuple[float, int, int, str]:
            dq = binding.hex_q - mean_q
            dr = binding.hex_r - mean_r
            distance = max(abs(dq), abs(dr), abs(dq + dr))
            return distance, binding.hex_q, binding.hex_r, str(binding.id)

        representative = min(bindings, key=sort_key)
        return representative.hex_q, representative.hex_r
