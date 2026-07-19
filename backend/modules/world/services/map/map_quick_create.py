"""地图快速创建服务。

快速创建是结构化数据编排器，不读取正文、不跑 LLM、不创建世界对象。
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ConflictError, NotFoundError, ValidationError
from modules.world.map_repositories import MapFactRepository
from modules.world.map_schemas import (
    BindingHex,
    MapConfigCreate,
    MapConfigResponse,
    MapLocationBindingCreate,
    MapLocationLayoutItem,
    MapLocationLayoutReplaceRequest,
    MapQuickCreateConfirmRequest,
    MapQuickCreateConfirmResponse,
    MapQuickCreateContextResponse,
    MapQuickCreatePreviewRequest,
    MapQuickCreatePreviewResponse,
)
from modules.world.repositories import CoreEntityRepository, EntityRelationRepository
from modules.world.services.common import parse_uuid
from modules.world.services.map.map_config_service import MapConfigService
from modules.world.services.map.map_location_binding_service import (
    MapLocationBindingService,
)
from modules.world.services.map.map_location_layout import MapLocationLayoutService
from modules.world.services.map.map_revision import MapRevisionService

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

PLACEABLE_LOCATION_STATUSES = ("canonical",)
REVIEW_LOCATION_STATUSES = ("draft", "candidate")
MAP_SCOPE_LABELS = {
    "world": "世界级",
    "region": "区域级",
    "settlement": "城市/聚落",
    "site": "地点/建筑",
    "interior": "室内/地下",
    "nonphysical": "非物理空间",
    "unknown": "尺度待判断",
}
MAP_SCOPE_TARGETS = {
    "world": ["world"],
    "region": ["world"],
    "settlement": ["world", "detail"],
    "site": ["detail", "drilldown"],
    "interior": ["detail", "drilldown"],
    "nonphysical": ["world", "detail"],
    "unknown": ["world", "detail", "drilldown"],
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
        fact_repo: MapFactRepository | None = None,
    ) -> None:
        self._entity_repo = entity_repo or CoreEntityRepository()
        self._relation_repo = relation_repo or EntityRelationRepository()
        self._config_service = config_service or MapConfigService()
        self._binding_service = binding_service or MapLocationBindingService()
        self._layout_service = layout_service or MapLocationLayoutService()
        self._fact_repo = fact_repo or MapFactRepository()
        self._revision = MapRevisionService(self._config_service.repo)

    async def context(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        include_candidates: bool = False,
    ) -> MapQuickCreateContextResponse:
        nid = parse_uuid(novel_id, "novel_id")
        locations = await self._list_locations_for_statuses(
            db, nid, PLACEABLE_LOCATION_STATUSES
        )
        candidate_locations = []
        if include_candidates:
            candidate_locations = await self._list_locations_for_statuses(
                db,
                nid,
                REVIEW_LOCATION_STATUSES,
            )
        relations = await self._list_canonical_relations(db, nid)
        maps = await self._config_service.list(db, novel_id)
        warnings = []
        if not locations and not candidate_locations:
            warnings.append("缺少可用于快速创建的地点对象")
        location_summaries = [self._entity_summary(item) for item in locations]
        candidate_summaries = [self._entity_summary(item) for item in candidate_locations]
        self._enrich_location_context(
            [*location_summaries, *candidate_summaries],
            relations,
            maps.items,
        )
        return MapQuickCreateContextResponse(
            map_targets=[
                {"target": "world", "label": "创建世界地图"},
                {"target": "detail", "label": "为地点创建详图"},
                {"target": "drilldown", "label": "基于当前地点下钻地图"},
            ],
            locations=location_summaries,
            candidate_locations=candidate_summaries,
            existing_maps=maps.items,
            warnings=warnings,
        )

    async def preview(
        self,
        db: AsyncSession,
        novel_id: str,
        data: MapQuickCreatePreviewRequest,
    ) -> MapQuickCreatePreviewResponse:
        map_draft = await self._resolve_map_draft(db, novel_id, data)
        relations = await self._list_canonical_relations(
            db,
            parse_uuid(novel_id, "novel_id"),
        )
        locations = await self._load_locations(db, novel_id, data, relations)
        grid_width = map_draft["grid_width"]
        grid_height = map_draft["grid_height"]
        canonical_location_ids = {
            item["id"] for item in locations if item["status"] == "canonical"
        }
        geo_relations = self._geo_relations(relations, canonical_location_ids)
        canonical_locations = [
            item for item in locations if item["status"] == "canonical"
        ]
        review_locations = [item for item in locations if item["status"] != "canonical"]
        canonical_layouts = self._build_layout(
            canonical_locations,
            grid_width,
            grid_height,
            geo_relations=geo_relations,
        )
        layout_items = [
            *canonical_layouts,
            *self._build_review_layout(
                review_locations,
                grid_width,
                grid_height,
                occupied={
                    (item.center_hex_q, item.center_hex_r) for item in canonical_layouts
                },
            ),
        ]
        warnings = []
        if not locations:
            warnings.append("缺少可用于快速创建的地点对象")
        elif not geo_relations:
            warnings.append("缺少地点方向/距离关系，已生成等间距草稿")
        if data.target == "world":
            local_count = sum(
                1
                for item in locations
                if item.get("map_scope", {}).get("key") in {"site", "interior"}
            )
            if local_count:
                warnings.append(
                    f"检测到 {local_count} 个建筑或室内地点；建议在世界图中取消选择，"
                    "并为其所属城市或建筑创建详图"
                )
        return MapQuickCreatePreviewResponse(
            map=map_draft,
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
        map_name = data.name or map_draft["name"]
        layouts = self._confirm_layouts(data, preview)
        await self._assert_adopted_layouts(db, novel_id, layouts)
        parent_map_id = self._optional_uuid(data.parent_map_id, "parent_map_id")
        named_map = await self._config_service.repo.get_by_name(
            db,
            parse_uuid(novel_id, "novel_id"),
            name=map_name,
            parent_map_id=parent_map_id,
        )
        replacement = await self._get_replacement_map(db, novel_id, data)
        if replacement is None and named_map is not None:
            raise ConflictError(
                "同一层级已存在同名地图，请显式选择替换目标",
                code="map_quick_create_name_conflict",
            )
        if (
            replacement is not None
            and named_map is not None
            and named_map.id != replacement.id
        ):
            raise ConflictError(
                "同名地图与所选替换目标不一致",
                code="map_quick_create_replace_conflict",
            )
        if replacement is None:
            created_map = await self._config_service.create(
                db,
                novel_id,
                MapConfigCreate(
                    name=map_name,
                    map_type=map_draft["map_type"],
                    grid_width=map_draft["grid_width"],
                    grid_height=map_draft["grid_height"],
                    hex_size=map_draft["hex_size"],
                    parent_map_id=data.parent_map_id,
                    parent_entity_id=data.parent_entity_id,
                    template=data.base_template,
                ),
            )
        else:
            if map_name != replacement.name:
                raise ValidationError(
                    "替换已有地图时不能同时修改地图名称",
                    code="invalid_quick_create_replace_name",
                )
            created_map = MapConfigResponse.model_validate(replacement)
        locked_config = await self._revision.lock_active(
            db,
            novel_id,
            created_map.id,
        )
        layout_response = await self._layout_service.replace(
            db,
            novel_id,
            created_map.id,
            MapLocationLayoutReplaceRequest(layouts=layouts),
            bump_revision=False,
        )
        await self._binding_service.clear_map(
            db, novel_id, created_map.id, bump_revision=False
        )
        created_bindings = await self._binding_service.batch_create_many(
            db,
            novel_id,
            created_map.id,
            [
                MapLocationBindingCreate(
                    location_entity_id=layout.location_entity_id,
                    hexes=[
                        BindingHex(
                            hex_q=layout.center_hex_q,
                            hex_r=layout.center_hex_r,
                            is_center=True,
                        )
                    ],
                )
                for layout in layouts
            ],
            bump_revision=False,
        )
        await self._fact_repo.deprecate_quick_create_location_facts(
            db,
            parse_uuid(novel_id, "novel_id"),
            parse_uuid(created_map.id, "map_id"),
            reason="quick_create_replace",
        )
        await self._create_location_facts(
            db,
            novel_id,
            created_map.id,
            layouts,
        )
        await self._revision.bump(
            db,
            novel_id,
            created_map.id,
            locked_config=locked_config,
        )
        fresh_map = await self._config_service.get(db, created_map.id, novel_id=novel_id)
        return MapQuickCreateConfirmResponse(
            map=fresh_map,
            location_layouts=layout_response.items,
            location_bindings=created_bindings,
            markers=[],
            warnings=preview.warnings,
        )

    def _confirm_layouts(
        self,
        data: MapQuickCreateConfirmRequest,
        preview: MapQuickCreatePreviewResponse,
    ) -> list[MapLocationLayoutItem]:
        layouts = data.layouts if data.layouts is not None else preview.location_layouts
        allowed_location_ids = {
            layout.location_entity_id for layout in preview.location_layouts
        }
        invalid_location_ids = [
            layout.location_entity_id
            for layout in layouts
            if layout.location_entity_id not in allowed_location_ids
        ]
        if invalid_location_ids:
            raise ValidationError(
                "快速创建只能提交当前预览中的地点布局",
                code="invalid_quick_create_layout",
            )
        return layouts

    async def _resolve_map_draft(
        self,
        db: AsyncSession,
        novel_id: str,
        data: MapQuickCreatePreviewRequest,
    ) -> dict:
        replacement = await self._get_replacement_map(db, novel_id, data)
        if replacement is not None:
            await self._validate_target(db, novel_id, data, replacement=replacement)
            return {
                "name": replacement.name,
                "map_type": replacement.map_type,
                "grid_width": replacement.grid_width,
                "grid_height": replacement.grid_height,
                "hex_size": replacement.hex_size,
                "parent_map_id": str(replacement.parent_map_id)
                if replacement.parent_map_id
                else None,
                "parent_entity_id": str(replacement.parent_entity_id)
                if replacement.parent_entity_id
                else None,
                "replace_map_id": str(replacement.id),
            }
        await self._validate_target(db, novel_id, data)
        default_width, default_height = self._grid_size(data.target)
        return {
            "name": self._default_name(data.target),
            "map_type": data.map_type
            or ("world" if data.target == "world" else "region"),
            "grid_width": data.grid_width or default_width,
            "grid_height": data.grid_height or default_height,
            "hex_size": 30,
            "parent_map_id": data.parent_map_id,
            "parent_entity_id": data.parent_entity_id,
            "base_template": data.base_template,
        }

    async def _get_replacement_map(
        self,
        db: AsyncSession,
        novel_id: str,
        data: MapQuickCreatePreviewRequest,
    ):
        if not data.replace_map_id:
            return None
        replacement = await self._config_service.repo.get(
            db,
            parse_uuid(data.replace_map_id, "replace_map_id"),
        )
        if (
            replacement is None
            or replacement.status != "active"
            or str(replacement.novel_id) != str(parse_uuid(novel_id, "novel_id"))
        ):
            raise NotFoundError(
                "替换目标地图不存在",
                code="map_quick_create_replace_not_found",
            )
        return replacement

    async def _validate_target(
        self,
        db: AsyncSession,
        novel_id: str,
        data: MapQuickCreatePreviewRequest,
        *,
        replacement=None,
    ) -> None:
        nid = parse_uuid(novel_id, "novel_id")
        if data.target == "world":
            if data.parent_map_id or data.parent_entity_id:
                raise ValidationError(
                    "世界地图不能指定父地图或父地点",
                    code="invalid_quick_create_target",
                )
            if replacement is not None and (
                replacement.parent_map_id is not None
                or replacement.parent_entity_id is not None
            ):
                raise ValidationError(
                    "替换目标不是顶层世界地图",
                    code="invalid_quick_create_replace_target",
                )
            return
        if not data.parent_entity_id:
            raise ValidationError(
                "地点详图必须指定父地点",
                code="invalid_quick_create_target",
            )
        parent_entity = await self._entity_repo.get(
            db,
            parse_uuid(data.parent_entity_id, "parent_entity_id"),
        )
        if (
            parent_entity is None
            or parent_entity.novel_id != nid
            or parent_entity.entity_type != "location"
            or parent_entity.status != "canonical"
        ):
            raise NotFoundError(
                "父地点不存在或尚未采用",
                code="map_quick_create_parent_not_found",
            )
        parent_map = None
        if data.parent_map_id:
            parent_map = await self._config_service.repo.get(
                db,
                parse_uuid(data.parent_map_id, "parent_map_id"),
            )
            if (
                parent_map is None
                or parent_map.novel_id != nid
                or parent_map.status != "active"
            ):
                raise NotFoundError(
                    "父地图不存在",
                    code="map_quick_create_parent_map_not_found",
                )
        if data.target == "drilldown" and parent_map is None:
            raise ValidationError(
                "下钻地图必须指定父地图",
                code="invalid_quick_create_target",
            )
        if replacement is not None:
            expected_parent_map = parent_map.id if parent_map else None
            if (
                replacement.parent_map_id != expected_parent_map
                or replacement.parent_entity_id != parent_entity.id
            ):
                raise ValidationError(
                    "替换地图与所选父层级不一致",
                    code="invalid_quick_create_replace_target",
                )

    async def _load_locations(
        self,
        db: AsyncSession,
        novel_id: str,
        data: MapQuickCreatePreviewRequest,
        relations,
    ) -> list[dict]:
        nid = parse_uuid(novel_id, "novel_id")
        base_locations = await self._list_locations_for_statuses(
            db, nid, PLACEABLE_LOCATION_STATUSES
        )
        candidate_locations = []
        if data.include_candidates:
            candidates = await self._list_locations_for_statuses(
                db,
                nid,
                REVIEW_LOCATION_STATUSES,
            )
            candidate_locations = candidates
        if data.target == "world":
            scoped_ids = {str(item.id) for item in base_locations}
            scoped_ids.update(str(item.id) for item in candidate_locations)
        else:
            parent_id = str(data.parent_entity_id)
            scoped_ids = {parent_id}
            for relation in relations:
                source_id = str(relation.source_id)
                target_id = str(relation.target_id)
                if relation.relation_type == "contains" and source_id == parent_id:
                    scoped_ids.add(target_id)
                elif (
                    relation.relation_type in {"contained_in", "located_in"}
                    and target_id == parent_id
                ):
                    scoped_ids.add(source_id)
        scoped_ids.update(data.location_entity_ids)
        return [
            self._entity_summary(item)
            for item in [*base_locations, *candidate_locations]
            if str(item.id) in scoped_ids
        ]

    async def _assert_adopted_layouts(
        self,
        db: AsyncSession,
        novel_id: str,
        layouts: list[MapLocationLayoutItem],
    ) -> None:
        if not layouts:
            return
        nid = parse_uuid(novel_id, "novel_id")
        location_ids = [
            parse_uuid(layout.location_entity_id, "location_entity_id")
            for layout in layouts
        ]
        entities = await self._entity_repo.get_by_ids(db, nid, location_ids)
        by_id = {entity.id: entity for entity in entities}
        unadopted = [
            str(location_id)
            for location_id in location_ids
            if by_id.get(location_id) is None or by_id[location_id].status != "canonical"
        ]
        if unadopted:
            raise ValidationError(
                "待处理地点只能预览，请先采用对象再创建地图",
                code="unadopted_quick_create_location",
            )

    async def _list_locations_for_statuses(
        self,
        db: AsyncSession,
        novel_id,
        statuses: tuple[str, ...],
    ):
        seen = set()
        locations = []
        for status in statuses:
            skip = 0
            while True:
                rows = await self._entity_repo.list_by_novel(
                    db,
                    novel_id,
                    entity_type="location",
                    status=status,
                    skip=skip,
                    limit=500,
                )
                for row in rows:
                    if row.id in seen:
                        continue
                    seen.add(row.id)
                    locations.append(row)
                if len(rows) < 500:
                    break
                skip += len(rows)
        return locations

    async def _list_canonical_relations(self, db: AsyncSession, novel_id):
        relations = []
        skip = 0
        while True:
            rows = await self._relation_repo.list_by_novel(
                db,
                novel_id,
                status="canonical",
                skip=skip,
                limit=500,
            )
            relations.extend(rows)
            if len(rows) < 500:
                return relations
            skip += len(rows)

    async def _create_location_facts(
        self,
        db: AsyncSession,
        novel_id: str,
        map_id: str,
        layouts: list[MapLocationLayoutItem],
    ) -> None:
        if not layouts:
            return
        nid = parse_uuid(novel_id, "novel_id")
        mid = parse_uuid(map_id, "map_id")
        location_ids = [
            parse_uuid(layout.location_entity_id, "location_entity_id")
            for layout in layouts
        ]
        entities = await self._entity_repo.get_by_ids(db, nid, location_ids)
        by_id = {entity.id: entity for entity in entities}
        facts = []
        for layout in layouts:
            location_id = parse_uuid(layout.location_entity_id, "location_entity_id")
            entity = by_id.get(location_id)
            if entity is None:
                continue
            if entity.status != "canonical":
                raise ValidationError(
                    "快速创建事实只能引用已采用地点",
                    code="unadopted_quick_create_location",
                )
            facts.append(
                {
                    "map_id": mid,
                    "target_entity_id": location_id,
                    "target_entity_type": "location",
                    "target_name": entity.name,
                    "dynamic_type": "location",
                    "time_anchor": {"scope": "project"},
                    "spatial_anchor": {
                        "map_id": str(mid),
                        "hex_q": layout.center_hex_q,
                        "hex_r": layout.center_hex_r,
                    },
                    "value_json": {
                        "placement": "quick_create",
                        "entity_status": entity.status,
                    },
                    "confidence": 1.0,
                    "fact_status": "confirmed",
                    "source_ref": {"source": "map_quick_create"},
                    "evidence_text": "快速创建地图时根据已有地点对象放置。",
                }
            )
        await self._fact_repo.create_many(db, nid, facts)

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

    def _build_review_layout(
        self,
        locations: list[dict],
        grid_width: int,
        grid_height: int,
        *,
        occupied: set[tuple[int, int]],
    ) -> list[MapLocationLayoutItem]:
        """Place read-only review nodes without moving canonical nodes."""
        if not locations:
            return []
        preferred = self._build_layout(locations, grid_width, grid_height)
        result = []
        used = set(occupied)
        cell_count = max(1, grid_width * grid_height)
        for item in preferred:
            start = item.center_hex_r * grid_width + item.center_hex_q
            chosen = (item.center_hex_q, item.center_hex_r)
            for offset in range(cell_count):
                index = (start + offset) % cell_count
                candidate = (index % grid_width, index // grid_width)
                if candidate not in used:
                    chosen = candidate
                    break
            used.add(chosen)
            result.append(
                item.model_copy(
                    update={"center_hex_q": chosen[0], "center_hex_r": chosen[1]}
                )
            )
        return result

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

    def _optional_uuid(self, value: str | None, field_name: str):
        return parse_uuid(value, field_name) if value else None

    def _grid_size(self, target: str) -> tuple[int, int]:
        if target == "world":
            return 40, 30
        return 24, 18

    def _default_name(self, target: str) -> str:
        if target == "world":
            return "快速创建世界地图"
        return "快速创建地点详图"

    def _entity_summary(self, entity) -> dict:
        map_scope = self._infer_map_scope(entity)
        return {
            "id": str(entity.id),
            "name": entity.name,
            "entity_type": entity.entity_type,
            "status": entity.status,
            "summary": entity.summary,
            "map_scope": map_scope,
        }

    def _infer_map_scope(self, entity) -> dict:
        content = dict(getattr(entity, "content_json", None) or {})
        explicit = content.get("map_scope") or content.get("location_scale")
        if isinstance(explicit, dict):
            explicit = explicit.get("key")
        if explicit in MAP_SCOPE_LABELS:
            key = explicit
            basis = "explicit"
        else:
            text = f"{entity.name or ''} {entity.summary or ''}"
            if any(token in text for token in ("灰雾", "梦境", "神秘空间", "精神空间")):
                key = "nonphysical"
            elif any(
                token in text
                for token in (
                    "房间",
                    "会议室",
                    "炼金室",
                    "告解室",
                    "盥洗室",
                    "武器库",
                    "地下室",
                    "地下通道",
                    "走廊",
                    "查尼斯门",
                    "船长室",
                )
            ):
                key = "interior"
            elif any(token in entity.name for token in ("市", "城", "港")) or any(
                token in text for token in ("首都", "城市", "聚落")
            ):
                key = "settlement"
            elif any(
                token in entity.name
                for token in (
                    "世界",
                    "大陆",
                    "王国",
                    "帝国",
                    "国家",
                    "山脉",
                    "海域",
                    "岛屿",
                    "神弃之地",
                )
            ):
                key = "region"
            elif any(
                token in text
                for token in (
                    "街",
                    "公寓",
                    "住所",
                    "公司",
                    "教堂",
                    "大学",
                    "学校",
                    "俱乐部",
                    "别墅",
                    "酒吧",
                    "商店",
                    "餐厅",
                    "面包店",
                )
            ):
                key = "site"
            else:
                key = "unknown"
            basis = "name_summary" if key != "unknown" else "unknown"
        return {
            "key": key,
            "label": MAP_SCOPE_LABELS[key],
            "basis": basis,
            "recommended_targets": MAP_SCOPE_TARGETS[key],
        }

    def _enrich_location_context(self, locations, relations, maps) -> None:
        by_id = {item["id"]: item for item in locations}
        parent_ids: dict[str, set[str]] = {location_id: set() for location_id in by_id}
        child_ids: dict[str, set[str]] = {location_id: set() for location_id in by_id}
        for relation in relations:
            source_id = str(relation.source_id)
            target_id = str(relation.target_id)
            if relation.relation_type == "contains":
                parent_id, child_id = source_id, target_id
            elif relation.relation_type in {"contained_in", "located_in"}:
                parent_id, child_id = target_id, source_id
            else:
                continue
            if parent_id not in by_id or child_id not in by_id:
                continue
            parent_ids[child_id].add(parent_id)
            child_ids[parent_id].add(child_id)
        detail_maps: dict[str, list[dict]] = {location_id: [] for location_id in by_id}
        for map_item in maps:
            parent_entity_id = (
                str(map_item.parent_entity_id) if map_item.parent_entity_id else None
            )
            if parent_entity_id not in detail_maps:
                continue
            detail_maps[parent_entity_id].append(
                {
                    "id": map_item.id,
                    "name": map_item.name,
                    "map_type": map_item.map_type,
                }
            )
        for location_id, item in by_id.items():
            item["parent_locations"] = [
                {"id": parent_id, "name": by_id[parent_id]["name"]}
                for parent_id in sorted(
                    parent_ids[location_id], key=lambda value: by_id[value]["name"]
                )
            ]
            item["child_location_count"] = len(child_ids[location_id])
            item["detail_maps"] = sorted(
                detail_maps[location_id],
                key=lambda value: (value["name"], value["id"]),
            )
            item["has_detail_map"] = bool(item["detail_maps"])
