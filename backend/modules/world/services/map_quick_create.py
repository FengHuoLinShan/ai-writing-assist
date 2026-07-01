"""地图快速创建服务。

快速创建是结构化数据编排器，不读取正文、不跑 LLM、不创建世界对象。
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.map_schemas import (
    BindingHex,
    MapConfigCreate,
    MapLocationBindingCreate,
    MapLocationBindingResponse,
    MapLocationLayoutItem,
    MapLocationLayoutReplaceRequest,
    MapQuickCreateConfirmRequest,
    MapQuickCreateConfirmResponse,
    MapQuickCreateContextResponse,
    MapQuickCreatePreviewRequest,
    MapQuickCreatePreviewResponse,
)
from modules.world.repositories import CoreEntityRepository, EntityRelationRepository
from modules.world.services.helpers import parse_uuid
from modules.world.services.map_location_layout import MapLocationLayoutService
from modules.world.services.map_service import (
    MapConfigService,
    MapLocationBindingService,
)

GEO_RELATION_TYPES = {
    "contains",
    "contained_in",
    "located_in",
    "adjacent_to",
    "east_of",
    "west_of",
    "north_of",
    "south_of",
    "near",
    "far_from",
    "controls",
}


@dataclass(frozen=True)
class GeoRelation:
    source_id: str
    target_id: str
    relation_type: str


class MapQuickCreateService:
    """从已有结构化数据生成一张可编辑地图草稿。"""

    def __init__(
        self,
        *,
        entity_repo: CoreEntityRepository | None = None,
        relation_repo: EntityRelationRepository | None = None,
        config_service: MapConfigService | None = None,
        binding_service: MapLocationBindingService | None = None,
        layout_service: MapLocationLayoutService | None = None,
    ) -> None:
        self._entity_repo = entity_repo or CoreEntityRepository()
        self._relation_repo = relation_repo or EntityRelationRepository()
        self._config_service = config_service or MapConfigService()
        self._binding_service = binding_service or MapLocationBindingService()
        self._layout_service = layout_service or MapLocationLayoutService()

    async def context(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        include_candidates: bool = False,
    ) -> MapQuickCreateContextResponse:
        nid = parse_uuid(novel_id, "novel_id")
        canonical_locations, _ = await self._entity_repo.get_by_novel(
            db, nid, entity_type="location", status="canonical", limit=500
        )
        candidate_locations = []
        if include_candidates:
            candidate_locations, _ = await self._entity_repo.get_by_novel(
                db, nid, entity_type="location", status="candidate", limit=500
            )
        maps = await self._config_service.list(db, novel_id)
        warnings = []
        if not canonical_locations and not candidate_locations:
            warnings.append("缺少可用于快速创建的地点对象")
        return MapQuickCreateContextResponse(
            map_targets=[
                {"target": "world", "label": "创建世界地图"},
                {"target": "detail", "label": "为地点创建详图"},
                {"target": "drilldown", "label": "基于当前地点下钻地图"},
            ],
            locations=[self._entity_summary(item) for item in canonical_locations],
            candidate_locations=[
                self._entity_summary(item) for item in candidate_locations
            ],
            existing_maps=maps.items,
            warnings=warnings,
        )

    async def preview(
        self,
        db: AsyncSession,
        novel_id: str,
        data: MapQuickCreatePreviewRequest,
    ) -> MapQuickCreatePreviewResponse:
        locations = await self._load_locations(db, novel_id, data.include_candidates)
        grid_width, grid_height = self._grid_size(data.target)
        relations, _ = await self._relation_repo.get_by_novel(
            db, parse_uuid(novel_id, "novel_id"), limit=500
        )
        geo_relations = self._geo_relations(relations, {item["id"] for item in locations})
        layout_items = self._build_layout(
            locations,
            grid_width,
            grid_height,
            geo_relations=geo_relations,
        )
        warnings = []
        if not locations:
            warnings.append("缺少地点方向/距离关系，可在地点详情补充")
        elif not geo_relations:
            warnings.append("缺少地点方向/距离关系，已生成等间距草稿")
        return MapQuickCreatePreviewResponse(
            map={
                "name": self._default_name(data.target),
                "map_type": "world" if data.target == "world" else "region",
                "grid_width": grid_width,
                "grid_height": grid_height,
                "hex_size": 30,
                "parent_map_id": data.parent_map_id,
                "parent_entity_id": data.parent_entity_id,
            },
            location_layouts=layout_items,
            location_bindings=[
                {
                    "location_entity_id": item.location_entity_id,
                    "hex_q": item.center_hex_q,
                    "hex_r": item.center_hex_r,
                    "is_center": True,
                }
                for item in layout_items
            ],
            markers=[] if data.include_markers else [],
            unlocated_objects=[],
            warnings=warnings,
        )

    async def confirm(
        self,
        db: AsyncSession,
        novel_id: str,
        data: MapQuickCreateConfirmRequest,
    ) -> MapQuickCreateConfirmResponse:
        preview = await self.preview(db, novel_id, data)
        map_draft = preview.map
        created_map = await self._config_service.create(
            db,
            novel_id,
            MapConfigCreate(
                name=data.name or map_draft["name"],
                map_type=map_draft["map_type"],
                grid_width=map_draft["grid_width"],
                grid_height=map_draft["grid_height"],
                hex_size=map_draft["hex_size"],
                parent_map_id=data.parent_map_id,
                parent_entity_id=data.parent_entity_id,
                template="blank",
            ),
        )
        layouts = data.layouts or preview.location_layouts
        layout_response = await self._layout_service.replace(
            db,
            novel_id,
            created_map.id,
            MapLocationLayoutReplaceRequest(layouts=layouts),
        )
        created_bindings: list[MapLocationBindingResponse] = []
        for layout in layouts:
            bindings = await self._binding_service.batch_create(
                db,
                novel_id,
                created_map.id,
                MapLocationBindingCreate(
                    location_entity_id=layout.location_entity_id,
                    hexes=[
                        BindingHex(
                            hex_q=layout.center_hex_q,
                            hex_r=layout.center_hex_r,
                            is_center=True,
                        )
                    ],
                ),
            )
            created_bindings.extend(bindings)
        return MapQuickCreateConfirmResponse(
            map=created_map,
            location_layouts=layout_response.items,
            location_bindings=created_bindings,
            markers=[],
            warnings=preview.warnings,
        )

    async def _load_locations(
        self,
        db: AsyncSession,
        novel_id: str,
        include_candidates: bool,
    ) -> list[dict]:
        nid = parse_uuid(novel_id, "novel_id")
        canonical, _ = await self._entity_repo.get_by_novel(
            db, nid, entity_type="location", status="canonical", limit=500
        )
        locations = [self._entity_summary(item) for item in canonical]
        if include_candidates:
            candidates, _ = await self._entity_repo.get_by_novel(
                db, nid, entity_type="location", status="candidate", limit=500
            )
            locations.extend(self._entity_summary(item) for item in candidates)
        return locations

    def _build_layout(
        self,
        locations: list[dict],
        grid_width: int,
        grid_height: int,
        *,
        geo_relations: list[GeoRelation] | None = None,
    ) -> list[MapLocationLayoutItem]:
        if not locations:
            return []
        columns = max(1, min(6, int(len(locations) ** 0.5) + 1))
        step_q = max(2, grid_width // (columns + 1))
        rows = max(1, (len(locations) + columns - 1) // columns)
        step_r = max(2, grid_height // (rows + 1))
        layouts = []
        for index, location in enumerate(locations):
            col = index % columns
            row = index // columns
            layouts.append(
                MapLocationLayoutItem(
                    location_entity_id=location["id"],
                    center_hex_q=min(grid_width - 1, (col + 1) * step_q),
                    center_hex_r=min(grid_height - 1, (row + 1) * step_r),
                    occupy_radius=1,
                    locked=False,
                    layout_source="quick_create",
                    meta={"entity_status": location["status"]},
                )
            )
        return self._apply_geo_relations(
            layouts,
            geo_relations or [],
            grid_width,
            grid_height,
            step_q,
            step_r,
        )

    def _geo_relations(self, relations, location_ids: set[str]) -> list[GeoRelation]:
        result = []
        for rel in relations:
            source_id = str(rel.source_id)
            target_id = str(rel.target_id)
            if (
                rel.relation_type in GEO_RELATION_TYPES
                and source_id in location_ids
                and target_id in location_ids
            ):
                result.append(
                    GeoRelation(
                        source_id=source_id,
                        target_id=target_id,
                        relation_type=rel.relation_type,
                    )
                )
        return sorted(
            result,
            key=lambda rel: (rel.relation_type, rel.source_id, rel.target_id),
        )

    def _apply_geo_relations(
        self,
        layouts: list[MapLocationLayoutItem],
        relations: list[GeoRelation],
        grid_width: int,
        grid_height: int,
        step_q: int,
        step_r: int,
    ) -> list[MapLocationLayoutItem]:
        if not relations:
            return layouts
        by_id = {layout.location_entity_id: layout for layout in layouts}
        for relation in relations:
            source = by_id.get(relation.source_id)
            target = by_id.get(relation.target_id)
            if source is None or target is None:
                continue
            moving_id, desired = self._desired_position(
                relation,
                source,
                target,
                max(2, step_q),
                max(2, step_r),
            )
            if desired is None:
                continue
            occupied = {
                (layout.center_hex_q, layout.center_hex_r): layout.location_entity_id
                for layout in by_id.values()
                if layout.location_entity_id != moving_id
            }
            q, r = self._nearest_free_hex(
                desired[0],
                desired[1],
                grid_width,
                grid_height,
                occupied,
            )
            current = by_id[moving_id]
            meta = dict(current.meta or {})
            meta["geo_relation"] = relation.relation_type
            by_id[moving_id] = current.model_copy(
                update={
                    "center_hex_q": q,
                    "center_hex_r": r,
                    "layout_source": "quick_create_geo",
                    "meta": meta,
                }
            )
        return [by_id[layout.location_entity_id] for layout in layouts]

    def _desired_position(
        self,
        relation: GeoRelation,
        source: MapLocationLayoutItem,
        target: MapLocationLayoutItem,
        step_q: int,
        step_r: int,
    ) -> tuple[str, tuple[int, int] | None]:
        match relation.relation_type:
            case "east_of":
                return (
                    relation.source_id,
                    (target.center_hex_q + step_q, target.center_hex_r),
                )
            case "west_of":
                return (
                    relation.source_id,
                    (target.center_hex_q - step_q, target.center_hex_r),
                )
            case "north_of":
                return (
                    relation.source_id,
                    (target.center_hex_q, target.center_hex_r - step_r),
                )
            case "south_of":
                return (
                    relation.source_id,
                    (target.center_hex_q, target.center_hex_r + step_r),
                )
            case "far_from":
                return (
                    relation.source_id,
                    (target.center_hex_q + step_q * 2, target.center_hex_r + step_r),
                )
            case "contains" | "controls":
                return relation.target_id, (source.center_hex_q + 2, source.center_hex_r)
            case "contained_in" | "located_in":
                return relation.source_id, (target.center_hex_q + 2, target.center_hex_r)
            case "adjacent_to" | "near":
                return relation.source_id, (target.center_hex_q + 2, target.center_hex_r)
            case _:
                return relation.source_id, None

    def _nearest_free_hex(
        self,
        q: int,
        r: int,
        grid_width: int,
        grid_height: int,
        occupied: dict[tuple[int, int], str],
    ) -> tuple[int, int]:
        desired_q = self._clamp(q, 0, grid_width - 1)
        desired_r = self._clamp(r, 0, grid_height - 1)
        for ring in range(max(grid_width, grid_height) + 1):
            for dq in range(-ring, ring + 1):
                for dr in range(-ring, ring + 1):
                    candidate = (
                        self._clamp(desired_q + dq, 0, grid_width - 1),
                        self._clamp(desired_r + dr, 0, grid_height - 1),
                    )
                    if candidate not in occupied:
                        return candidate
        return desired_q, desired_r

    def _clamp(self, value: int, minimum: int, maximum: int) -> int:
        return max(minimum, min(maximum, value))

    def _grid_size(self, target: str) -> tuple[int, int]:
        if target == "world":
            return 40, 30
        return 24, 18

    def _default_name(self, target: str) -> str:
        if target == "world":
            return "快速创建世界地图"
        return "快速创建地点详图"

    def _entity_summary(self, entity) -> dict:
        return {
            "id": str(entity.id),
            "name": entity.name,
            "entity_type": entity.entity_type,
            "status": entity.status,
            "summary": entity.summary,
        }
