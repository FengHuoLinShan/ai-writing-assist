"""
World 动态地图业务服务 — PRD docs/PRD-动态地图功能.md

- MapConfigService: 继承 CrudService（CRUD + create 生成初始 tile
  + get_state 聚合 + generate 快速生成）
- MapTileService: 批量地形编辑（构造注入 repo）
- MapLocationBindingService: 地点绑定 + 中心点唯一性
  （构造注入 repo + CoreEntityRepository）

约定（与 world/services/ 一致）：
- 5 verb 走 CrudService 基类，特例方法留子类
- novel_id 隔离由基类 _assert_found_in_novel 保证
- 跨表校验用构造注入第二 repo
"""

from __future__ import annotations

import logging
import random
import uuid
from typing import Any

from fastapi import HTTPException
from fastapi import status as http_status
from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.map_repositories import (
    MapConfigRepository,
    MapFactRepository,
    MapLocationBindingRepository,
    MapMarkerRepository,
    MapObservationRepository,
    MapTerritoryRepository,
    MapTileRepository,
)
from modules.world.map_schemas import (
    MapConfigCreate,
    MapConfigListResponse,
    MapConfigResponse,
    MapConfigUpdate,
    MapDashboardBatchGroup,
    MapDashboardInspector,
    MapDashboardQueueItem,
    MapDashboardResponse,
    MapFactListResponse,
    MapFactResponse,
    MapFactStatusUpdate,
    MapLocationBindingCreate,
    MapLocationBindingResponse,
    MapLocationBindingUpdate,
    MapMarkerCreate,
    MapMarkerResponse,
    MapMarkerUpdate,
    MapObservationBatchReviewRequest,
    MapObservationBatchReviewResponse,
    MapObservationCreate,
    MapObservationListResponse,
    MapObservationResponse,
    MapObservationReviewUpdate,
    MapPlaybackEvent,
    MapPlaybackResponse,
    MapPlaybackTrack,
    MapStateResponse,
    MapTerritoryCreate,
    MapTerritoryResponse,
    MapTerritoryUpdate,
    MapTileBatchUpdate,
    MapTileResponse,
)
from modules.world.repositories import CoreEntityRepository
from modules.world.services.base import CrudService
from modules.world.services.helpers import parse_uuid
from modules.world.services.map_context import MapContext
from modules.world.services.map_state_assembler import MapStateAssembler

logger = logging.getLogger(__name__)

# ============================================================
# 地形模板生成器（初始化世界地图用）
# ============================================================

# 默认地形
_BLANK_TERRAIN = "grassland"


def _generate_blank_tiles(width: int, height: int) -> list[dict[str, Any]]:
    """空白模板：全 grassland。"""
    return [
        {"hex_q": q, "hex_r": r, "terrain_type": _BLANK_TERRAIN, "elevation": 0}
        for q in range(width)
        for r in range(height)
    ]


def _generate_continent_tiles(width: int, height: int) -> list[dict[str, Any]]:
    """大陆模板：中心陆地 + 边缘水。

    简化算法：用到中心的距离判断，内部随机 grassland/forest，边缘 water。
    确定性（seed 固定）避免每次创建结果不同。
    """
    rng = random.Random(42)
    cx, cy = width / 2, height / 2
    max_dist = (width**2 + height**2) ** 0.5 / 2
    tiles: list[dict[str, Any]] = []
    for q in range(width):
        for r in range(height):
            dist = ((q - cx) ** 2 + (r - cy) ** 2) ** 0.5 / max_dist
            if dist > 0.85:
                terrain = "water"
            elif dist > 0.7:
                terrain = rng.choice(["water", "desert", "grassland"])
            elif dist < 0.2:
                terrain = rng.choice(["mountain", "forest"])
            else:
                terrain = rng.choice(["grassland", "forest", "grassland"])
            tiles.append(
                {"hex_q": q, "hex_r": r, "terrain_type": terrain, "elevation": 0}
            )
    return tiles


def _generate_islands_tiles(width: int, height: int) -> list[dict[str, Any]]:
    """群岛模板：散布小岛 + 大量水。"""
    rng = random.Random(7)
    tiles: list[dict[str, Any]] = []
    for q in range(width):
        for r in range(height):
            # 约 25% 陆地，散布成岛
            if rng.random() < 0.25:
                terrain = rng.choice(["grassland", "forest", "mountain"])
            else:
                terrain = "water"
            tiles.append(
                {"hex_q": q, "hex_r": r, "terrain_type": terrain, "elevation": 0}
            )
    return tiles


_TEMPLATES = {
    "blank": _generate_blank_tiles,
    "continent": _generate_continent_tiles,
    "islands": _generate_islands_tiles,
}


def generate_template_tiles(
    width: int,
    height: int,
    template: str | None,
) -> list[dict[str, Any]]:
    """按模板生成初始 tile。未知模板回退 blank。"""
    if template and template in _TEMPLATES:
        return _TEMPLATES[template](width, height)
    return _generate_blank_tiles(width, height)


# ============================================================
# 详图快速生成（PRD §路径 3）
# ============================================================


def generate_detail_tiles(width: int, height: int) -> list[dict[str, Any]]:
    """详图快速生成：中心 3 圈 city + 外 1 圈 road + 其余随机 grassland/forest。

    以网格中心为圆心，用六边形距离（近似欧氏距离足够 P0）。
    """
    rng = random.Random(123)
    cx, cy = width / 2, height / 2
    city_radius = min(width, height) * 0.18  # 约 3 圈
    road_radius = city_radius * 1.4
    tiles: list[dict[str, Any]] = []
    for q in range(width):
        for r in range(height):
            dist = ((q - cx) ** 2 + (r - cy) ** 2) ** 0.5
            if dist <= city_radius:
                terrain = "city"
            elif dist <= road_radius:
                terrain = "road"
            else:
                terrain = rng.choice(["grassland", "forest"])
            tiles.append(
                {"hex_q": q, "hex_r": r, "terrain_type": terrain, "elevation": 0}
            )
    return tiles


# ============================================================
# MapConfigService（继承 CrudService）
# ============================================================


class MapConfigService(
    CrudService[Any, MapConfigCreate, MapConfigUpdate, MapConfigResponse],
):
    """地图配置业务服务。

    5 verb 继承 base；create 时据模板生成初始 tile；
    get_state 聚合 map + 面包屑 + tiles + bindings。
    """

    repo = MapConfigRepository()
    response = MapConfigResponse
    list_response = MapConfigListResponse
    label = "MapConfig"
    id_param = "map_id"

    def __init__(self) -> None:
        self._tile_repo = MapTileRepository()
        self._binding_repo = MapLocationBindingRepository()
        self._territory_repo = MapTerritoryRepository()
        self._entity_repo = CoreEntityRepository()
        self._ctx = MapContext()
        self._state_assembler = MapStateAssembler(
            config_repo=self.repo,
            tile_repo=self._tile_repo,
            binding_repo=self._binding_repo,
            territory_repo=self._territory_repo,
            ctx=self._ctx,
        )

    # Override: list 加 parent_map_id 过滤 + 返 ListResponse 包装
    async def list(  # type: ignore[override]
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        parent_map_id: str | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> MapConfigListResponse:
        nid = parse_uuid(novel_id, "novel_id")
        pid = parse_uuid(parent_map_id, "parent_map_id") if parent_map_id else None
        items, total = await self.repo.get_by_novel(
            db, nid, parent_map_id=pid, skip=skip, limit=limit
        )
        return MapConfigListResponse(
            items=[MapConfigResponse.model_validate(m) for m in items],
            total=total,
        )

    # Override: create 后生成初始 tile
    async def create(
        self,
        db: AsyncSession,
        novel_id: str,
        data: MapConfigCreate,
    ) -> MapConfigResponse:
        nid = parse_uuid(novel_id, "novel_id")

        # 校验 parent_map_id 属同 novel
        parent_map_id_uuid: Any = None
        if data.parent_map_id:
            pid = parse_uuid(data.parent_map_id, "parent_map_id")
            parent = await self.repo.get(db, pid)
            if parent is None or parent.novel_id != nid:
                raise HTTPException(
                    status_code=http_status.HTTP_400_BAD_REQUEST,
                    detail="parent_map_id 不存在或不属于该项目",
                )
            parent_map_id_uuid = pid

        # 校验 parent_entity_id 属同 novel 且 entity_type=location（PRD §4.1/§4.3）
        if data.parent_entity_id:
            eid = parse_uuid(data.parent_entity_id, "parent_entity_id")
            entity = await self._entity_repo.get(db, eid)
            if entity is None or entity.novel_id != nid:
                raise HTTPException(
                    status_code=http_status.HTTP_404_NOT_FOUND,
                    detail=f"实体 {data.parent_entity_id} 不存在",
                )
            if entity.entity_type != "location":
                raise HTTPException(
                    status_code=http_status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"实体 {entity.name} 类型为 {entity.entity_type}，"
                        "parent_entity_id 必须为 location 类型"
                    ),
                )

        # PostgreSQL NULL 不参与 unique 约束，业务层按同父级精确查重。
        existing = await self.repo.get_by_name(
            db,
            nid,
            name=data.name,
            parent_map_id=parent_map_id_uuid,
        )
        if existing is not None:
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail=f"同层级已存在名为 {data.name!r} 的地图",
            )

        values: dict[str, Any] = {
            "name": data.name,
            "map_type": data.map_type,
            "description": data.description,
            "grid_width": data.grid_width,
            "grid_height": data.grid_height,
            "hex_size": data.hex_size,
            "parent_map_id": parent_map_id_uuid,
            "parent_entity_id": (
                parse_uuid(data.parent_entity_id, "parent_entity_id")
                if data.parent_entity_id
                else None
            ),
        }
        config = await self.repo.create(db, nid, values)

        # 生成初始 tile
        template = data.template if data.map_type == "world" else "blank"
        tiles = generate_template_tiles(data.grid_width, data.grid_height, template)
        await self._tile_repo.bulk_create(db, nid, config.id, tiles)

        # 刷新 config 以拿到完整字段
        fresh = await self.repo.get(db, config.id)
        assert fresh is not None
        return MapConfigResponse.model_validate(fresh)

    # Override: update 构造 plain dict 后交给 repo
    async def update(  # type: ignore[override]
        self,
        db: AsyncSession,
        map_id: str,
        data: MapConfigUpdate,
        *,
        novel_id: str,
    ) -> MapConfigResponse:
        nid = parse_uuid(novel_id, "novel_id")
        mid = parse_uuid(map_id, self.id_param)
        existing = await self.repo.get(db, mid)
        self._assert_found_in_novel(existing, map_id, nid)

        values: dict[str, Any] = {}
        for field in (
            "name",
            "description",
            "default_center_x",
            "default_center_y",
            "default_zoom",
            "sort_order",
        ):
            value = getattr(data, field, None)
            if value is not None:
                values[field] = value

        obj = await self.repo.update(db, mid, values)
        self._assert_found_in_novel(obj, map_id, nid)
        return self._to_response(obj)

    # 新增: 聚合状态
    async def get_state(
        self,
        db: AsyncSession,
        novel_id: str,
        map_id: str,
        *,
        filter_types: str = "all",
        scene_id: str | None = None,
    ) -> MapStateResponse:
        """聚合 map + 面包屑 + tiles + bindings + markers（P1）+ scene（P1）。

        filter_types（PRD §路径4）：
        - "all"：地点中心标签
        - "location"：中心标签 + 地点绑定区域边界
        P0 阶段后端返回全量数据，区域边界显隐由前端渲染层决定
        （showBoundary 标志，mapView._redraw）。参数被消费但不触发后端过滤，
        避免 P1/P2 接入 markers/territories 时改动此契约。
        """
        return await self._state_assembler.assemble(
            db,
            novel_id,
            map_id,
            filter_types=filter_types,
            scene_id=scene_id,
        )

    # 新增: 快速生成详图地形（PRD §路径 3）
    async def generate(
        self,
        db: AsyncSession,
        novel_id: str,
        map_id: str,
    ) -> MapStateResponse:
        """清空并重新生成详图地形（中心 city + 外 road + 随机 grassland/forest）。"""
        config = await self._ctx.require_map(db, novel_id, map_id)
        nid = parse_uuid(novel_id, "novel_id")
        mid = parse_uuid(map_id, "map_id")

        # PRD §路径3：快速生成是详图（city/region/dungeon）功能，禁止对 world 地图调用
        if config.map_type == "world":
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail="快速生成仅用于详图（city/region/dungeon），世界地图请用模板创建",
            )

        # 清空现有 tile 再生成（demo 阶段允许直接重建）
        await self._tile_repo.delete_by_map(db, nid, mid)
        changes = generate_detail_tiles(config.grid_width, config.grid_height)
        await self._tile_repo.bulk_create(db, nid, mid, changes)
        return await self.get_state(db, novel_id, map_id)


# ============================================================
# MapTileService（不继承，构造注入 repo）
# ============================================================


class MapTileService:
    """地形批量编辑服务。"""

    def __init__(
        self,
        tile_repo: MapTileRepository | None = None,
        context: MapContext | None = None,
    ) -> None:
        self._tile_repo = tile_repo or MapTileRepository()
        self._ctx = context or MapContext()

    async def batch_update(
        self,
        db: AsyncSession,
        novel_id: str,
        map_id: str,
        data: MapTileBatchUpdate,
    ) -> list[MapTileResponse]:
        config = await self._ctx.require_map(db, novel_id, map_id)
        for change in data.changes:
            self._ctx.assert_hex_in_bounds(config, change.hex_q, change.hex_r)

        nid = parse_uuid(novel_id, "novel_id")
        mid = parse_uuid(map_id, "map_id")
        changes = [
            {
                "hex_q": c.hex_q,
                "hex_r": c.hex_r,
                "terrain_type": c.terrain_type,
                "elevation": c.elevation,
            }
            for c in data.changes
        ]
        await self._tile_repo.bulk_upsert(db, nid, mid, changes)
        tiles = await self._tile_repo.get_by_map(db, nid, mid)
        return [MapTileResponse.model_validate(t) for t in tiles]


# ============================================================
# MapLocationBindingService（不继承，构造注入 repo）
# ============================================================


class MapLocationBindingService:
    """地点绑定服务：批量创建 + 中心点唯一性 + 单条 CRUD。"""

    def __init__(
        self,
        binding_repo: MapLocationBindingRepository | None = None,
        entity_repo: CoreEntityRepository | None = None,
        context: MapContext | None = None,
    ) -> None:
        self._binding_repo = binding_repo or MapLocationBindingRepository()
        self._entity_repo = entity_repo or CoreEntityRepository()
        self._ctx = context or MapContext()

    async def batch_create(
        self,
        db: AsyncSession,
        novel_id: str,
        map_id: str,
        data: MapLocationBindingCreate,
    ) -> list[MapLocationBindingResponse]:
        config = await self._ctx.require_map(db, novel_id, map_id)
        await self._ctx.require_entity(
            db, novel_id, data.location_entity_id, allowed_types={"location"}
        )
        for h in data.hexes:
            self._ctx.assert_hex_in_bounds(config, h.hex_q, h.hex_r)

        eid = parse_uuid(data.location_entity_id, "location_entity_id")
        mid = parse_uuid(map_id, "map_id")
        nid = parse_uuid(novel_id, "novel_id")

        # 中心点冲突：若新增含 is_center=true，先清旧中心
        has_new_center = any(h.is_center for h in data.hexes)
        if has_new_center:
            await self._binding_repo.clear_center(db, mid, eid)

        hexes = [
            {
                "hex_q": h.hex_q,
                "hex_r": h.hex_r,
                "is_center": h.is_center,
                "label_override": h.label_override,
                "style_override": h.style_override or {},
            }
            for h in data.hexes
        ]
        objs = await self._binding_repo.bulk_create(db, nid, mid, eid, hexes)
        return [MapLocationBindingResponse.model_validate(o) for o in objs]

    async def update(
        self,
        db: AsyncSession,
        novel_id: str,
        binding_id: str,
        data: MapLocationBindingUpdate,
    ) -> MapLocationBindingResponse:
        nid = parse_uuid(novel_id, "novel_id")
        bid = parse_uuid(binding_id, "binding_id")

        binding = await self._binding_repo.get(db, bid)
        if binding is None or binding.novel_id != nid:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"MapLocationBinding {binding_id} not found",
            )

        # 切换中心点：清同 location 的其他中心
        if data.is_center is True and not binding.is_center:
            await self._binding_repo.clear_center(
                db, binding.map_id, binding.location_entity_id
            )

        values: dict[str, Any] = {}
        for field in ("is_center", "label_override", "style_override"):
            value = getattr(data, field, None)
            if value is not None:
                values[field] = value

        updated = await self._binding_repo.update(db, bid, values)
        assert updated is not None
        return MapLocationBindingResponse.model_validate(updated)

    async def delete(
        self,
        db: AsyncSession,
        novel_id: str,
        binding_id: str,
    ) -> None:
        nid = parse_uuid(novel_id, "novel_id")
        bid = parse_uuid(binding_id, "binding_id")

        binding = await self._binding_repo.get(db, bid)
        if binding is None or binding.novel_id != nid:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"MapLocationBinding {binding_id} not found",
            )
        await self._binding_repo.delete(db, bid)


# ============================================================
# MapMarkerService（P1）
# ============================================================


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
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"MapMarker {marker_id} not found",
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

        updated = await self.repo.update(db, mkid, values)
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
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"MapMarker {marker_id} not found",
            )
        await self.repo.delete(db, mkid)


# ============================================================
# MapTerritoryService（P2）
# ============================================================


class MapTerritoryService:
    """势力范围服务（P2）。"""

    def __init__(
        self,
        territory_repo: MapTerritoryRepository | None = None,
        context: MapContext | None = None,
    ) -> None:
        self.repo = territory_repo or MapTerritoryRepository()
        self._ctx = context or MapContext()

    async def list(
        self,
        db: AsyncSession,
        novel_id: str,
        map_id: str,
    ) -> list[MapTerritoryResponse]:
        await self._ctx.require_map(db, novel_id, map_id)
        nid = parse_uuid(novel_id, "novel_id")
        mid = parse_uuid(map_id, "map_id")

        territories = await self.repo.get_by_map(db, nid, mid)
        return [MapTerritoryResponse.model_validate(t) for t in territories]

    async def create(
        self,
        db: AsyncSession,
        novel_id: str,
        map_id: str,
        data: MapTerritoryCreate,
    ) -> list[MapTerritoryResponse]:
        config = await self._ctx.require_map(db, novel_id, map_id)
        await self._ctx.require_entity(
            db, novel_id, data.faction_entity_id, allowed_types={"organization"}
        )
        for h in data.hexes:
            self._ctx.assert_hex_in_bounds(config, h.hex_q, h.hex_r)

        nid = parse_uuid(novel_id, "novel_id")
        mid = parse_uuid(map_id, "map_id")
        fid = parse_uuid(data.faction_entity_id, "faction_entity_id")
        hexes = [
            {
                "hex_q": h.hex_q,
                "hex_r": h.hex_r,
                "style_override": h.style_override or {},
            }
            for h in data.hexes
        ]
        tiles = await self.repo.create_batch(db, nid, mid, fid, hexes)
        return [MapTerritoryResponse.model_validate(t) for t in tiles]

    async def update(
        self,
        db: AsyncSession,
        novel_id: str,
        territory_id: str,
        data: MapTerritoryUpdate,
    ) -> MapTerritoryResponse:
        nid = parse_uuid(novel_id, "novel_id")
        tid = parse_uuid(territory_id, "territory_id")

        territory = await self.repo.get(db, tid)
        if territory is None or territory.novel_id != nid:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"MapTerritoryTile {territory_id} not found",
            )

        values: dict[str, Any] = {}
        if data.style_override is not None:
            values["style_override"] = data.style_override

        updated = await self.repo.update(db, tid, values)
        assert updated is not None
        return MapTerritoryResponse.model_validate(updated)

    async def delete(
        self,
        db: AsyncSession,
        novel_id: str,
        territory_id: str,
    ) -> None:
        nid = parse_uuid(novel_id, "novel_id")
        tid = parse_uuid(territory_id, "territory_id")

        territory = await self.repo.get(db, tid)
        if territory is None or territory.novel_id != nid:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"MapTerritoryTile {territory_id} not found",
            )
        await self.repo.delete(db, tid)

    async def delete_by_faction(
        self,
        db: AsyncSession,
        novel_id: str,
        map_id: str,
        faction_entity_id: str,
    ) -> int:
        await self._ctx.require_map(db, novel_id, map_id)
        nid = parse_uuid(novel_id, "novel_id")
        mid = parse_uuid(map_id, "map_id")
        fid = parse_uuid(faction_entity_id, "faction_entity_id")

        return await self.repo.delete_by_faction(db, nid, mid, fid)


# ============================================================
# MapDynamicFactService（世界动态 P0）
# ============================================================


class MapDynamicFactService:
    """地图观察事实与正式事实服务。

    P0 只负责可信事实底座：来源、置信度、审查状态，以及
    Observation -> MapFact 的确认流转。
    """

    def __init__(
        self,
        observation_repo: MapObservationRepository | None = None,
        fact_repo: MapFactRepository | None = None,
        context: MapContext | None = None,
        entity_repo: CoreEntityRepository | None = None,
    ) -> None:
        self._observation_repo = observation_repo or MapObservationRepository()
        self._fact_repo = fact_repo or MapFactRepository()
        self._ctx = context or MapContext()
        self._entity_repo = entity_repo or CoreEntityRepository()

    async def list_observations(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        map_id: str | None = None,
        review_state: str | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> MapObservationListResponse:
        mid = None
        if map_id:
            await self._ctx.require_map(db, novel_id, map_id)
            mid = parse_uuid(map_id, "map_id")
        nid = parse_uuid(novel_id, "novel_id")
        items, total = await self._observation_repo.list(
            db,
            nid,
            map_id=mid,
            review_state=review_state,
            skip=skip,
            limit=limit,
        )
        return MapObservationListResponse(
            items=[MapObservationResponse.model_validate(item) for item in items],
            total=total,
        )

    async def create_observation(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        map_id: str,
        data: MapObservationCreate,
    ) -> MapObservationResponse:
        config = await self._ctx.require_map(db, novel_id, map_id)
        if data.target_entity_id:
            await self._ctx.require_entity(db, novel_id, data.target_entity_id)
        self._assert_spatial_anchor_in_bounds(config, data.spatial_anchor or {})

        nid = parse_uuid(novel_id, "novel_id")
        mid = parse_uuid(map_id, "map_id")
        values = self._observation_values(data, map_id=mid)
        observation = await self._observation_repo.create(db, nid, values)
        return MapObservationResponse.model_validate(observation)

    async def update_observation_review(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        map_id: str,
        observation_id: str,
        data: MapObservationReviewUpdate,
    ) -> MapObservationResponse:
        nid = parse_uuid(novel_id, "novel_id")
        mid = parse_uuid(map_id, "map_id")
        await self._ctx.require_map(db, novel_id, map_id)
        oid = parse_uuid(observation_id, "observation_id")
        observation = await self._observation_repo.get(db, oid)
        self._assert_observation_in_novel(observation, observation_id, nid)
        assert observation is not None
        self._assert_observation_in_map(observation, observation_id, mid)
        updated = await self._observation_repo.update_review_state(
            db, oid, data.review_state
        )
        assert updated is not None
        return MapObservationResponse.model_validate(updated)

    async def ignore_observation(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        map_id: str,
        observation_id: str,
    ) -> MapObservationResponse:
        return await self.update_observation_review(
            db,
            novel_id,
            map_id=map_id,
            observation_id=observation_id,
            data=MapObservationReviewUpdate(review_state="ignored"),
        )

    async def confirm_observation(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        map_id: str,
        observation_id: str,
    ) -> MapFactResponse:
        await self._ctx.require_map(db, novel_id, map_id)
        nid = parse_uuid(novel_id, "novel_id")
        mid = parse_uuid(map_id, "map_id")
        oid = parse_uuid(observation_id, "observation_id")

        observation = await self._observation_repo.get(db, oid)
        self._assert_observation_in_novel(observation, observation_id, nid)
        assert observation is not None
        self._assert_observation_in_map(observation, observation_id, mid)

        existing = await self._fact_repo.get_by_observation(db, oid)
        if existing is not None:
            await self._observation_repo.update_review_state(db, oid, "confirmed")
            return MapFactResponse.model_validate(existing)

        fact = await self._fact_repo.create(
            db,
            nid,
            {
                "observation_id": oid,
                "map_id": observation.map_id or mid,
                "target_entity_id": observation.target_entity_id,
                "target_entity_type": observation.target_entity_type,
                "target_name": observation.target_name,
                "dynamic_type": observation.dynamic_type,
                "time_anchor": observation.time_anchor or {},
                "spatial_anchor": observation.spatial_anchor or {},
                "value_json": observation.value_json or {},
                "confidence": observation.confidence,
                "fact_status": "confirmed",
                "source_ref": observation.source_ref or {},
                "evidence_text": observation.evidence_text,
                "scene_id": observation.scene_id,
                "scene_index": observation.scene_index,
                "source_chapter_index": observation.source_chapter_index,
            },
        )
        await self._observation_repo.update_review_state(db, oid, "confirmed")
        return MapFactResponse.model_validate(fact)

    async def batch_review_observations(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        map_id: str,
        data: MapObservationBatchReviewRequest,
    ) -> MapObservationBatchReviewResponse:
        await self._ctx.require_map(db, novel_id, map_id)
        nid = parse_uuid(novel_id, "novel_id")
        mid = parse_uuid(map_id, "map_id")
        observations = []
        for observation_id in data.observation_ids:
            oid = parse_uuid(observation_id, "observation_id")
            observation = await self._observation_repo.get(db, oid)
            self._assert_observation_in_novel(observation, observation_id, nid)
            assert observation is not None
            self._assert_observation_in_map(observation, observation_id, mid)
            observations.append(observation)

        updated_observations = []
        facts = []
        created_fact_count = 0
        if data.action == "confirm":
            for observation in observations:
                existing = await self._fact_repo.get_by_observation(db, observation.id)
                fact = await self.confirm_observation(
                    db,
                    novel_id,
                    map_id=map_id,
                    observation_id=str(observation.id),
                )
                if existing is None:
                    created_fact_count += 1
                facts.append(fact)
                refreshed = await self._observation_repo.get(db, observation.id)
                if refreshed is not None:
                    updated_observations.append(
                        MapObservationResponse.model_validate(refreshed)
                    )
        else:
            next_state = "ignored" if data.action == "ignore" else "conflicted"
            for observation in observations:
                updated = await self._observation_repo.update_review_state(
                    db,
                    observation.id,
                    next_state,
                )
                assert updated is not None
                updated_observations.append(
                    MapObservationResponse.model_validate(updated)
                )

        return MapObservationBatchReviewResponse(
            action=data.action,
            requested_count=len(data.observation_ids),
            updated_count=len(updated_observations),
            created_fact_count=created_fact_count,
            observations=updated_observations,
            facts=facts,
        )

    async def list_facts(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        map_id: str | None = None,
        fact_status: str | None = "confirmed",
        skip: int = 0,
        limit: int = 100,
    ) -> MapFactListResponse:
        mid = None
        if map_id:
            await self._ctx.require_map(db, novel_id, map_id)
            mid = parse_uuid(map_id, "map_id")
        nid = parse_uuid(novel_id, "novel_id")
        items, total = await self._fact_repo.list(
            db,
            nid,
            map_id=mid,
            fact_status=fact_status,
            skip=skip,
            limit=limit,
        )
        return MapFactListResponse(
            items=[MapFactResponse.model_validate(item) for item in items],
            total=total,
        )

    async def update_fact_status(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        map_id: str,
        fact_id: str,
        data: MapFactStatusUpdate,
    ) -> MapFactResponse:
        await self._ctx.require_map(db, novel_id, map_id)
        nid = parse_uuid(novel_id, "novel_id")
        mid = parse_uuid(map_id, "map_id")
        fid = parse_uuid(fact_id, "fact_id")
        fact = await self._fact_repo.get(db, fid)
        self._assert_fact_access(fact, fact_id, nid, mid)
        updated = await self._fact_repo.update_status(db, fid, data.fact_status)
        assert updated is not None
        return MapFactResponse.model_validate(updated)

    async def get_dashboard(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        map_id: str,
        scene_id: str | None = None,
        focus_entity_id: str | None = None,
    ) -> MapDashboardResponse:
        """构建世界动态总控台派生视图。"""
        await self._ctx.require_map(db, novel_id, map_id)
        nid = parse_uuid(novel_id, "novel_id")
        mid = parse_uuid(map_id, "map_id")
        focus_id = (
            parse_uuid(focus_entity_id, "focus_entity_id")
            if focus_entity_id
            else None
        )

        observations = await self._observation_repo.list_for_dashboard(
            db,
            nid,
            map_id=mid,
            limit=120,
        )
        facts, _ = await self._fact_repo.list(
            db,
            nid,
            map_id=mid,
            fact_status="confirmed",
            limit=120,
        )
        active_observations = [
            item
            for item in observations
            if item.review_state in {"candidate", "conflicted"}
        ]
        queue = [
            *(self._queue_item_from_observation(item) for item in active_observations),
            *(self._queue_item_from_fact(item) for item in facts),
        ]
        queue.sort(key=lambda item: (-item.priority, item.time_label, item.title))
        queue = queue[:80]
        dashboard_queue = (
            self._filter_queue_for_focus(queue, str(focus_id))
            if focus_id
            else queue
        )

        inspector = self._build_dashboard_inspector(
            dashboard_queue,
            focus_entity_id=str(focus_id) if focus_id else None,
        )
        risk_summary = self._build_risk_summary(dashboard_queue)
        return MapDashboardResponse(
            map_id=map_id,
            first_visual_layer=self._build_first_visual_layer(
                dashboard_queue,
                scene_id=scene_id,
                risk_summary=risk_summary,
            ),
            dynamic_queue=dashboard_queue,
            inspector=inspector,
            batch_groups=self._build_batch_groups(dashboard_queue),
            risk_summary=risk_summary,
        )

    async def get_playback(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        map_id: str,
        scene_id: str | None = None,
        focus_entity_id: str | None = None,
        include_candidates: bool = True,
    ) -> MapPlaybackResponse:
        """构建只读电影化播放事件流。"""
        await self._ctx.require_map(db, novel_id, map_id)
        nid = parse_uuid(novel_id, "novel_id")
        mid = parse_uuid(map_id, "map_id")
        focus_id = (
            parse_uuid(focus_entity_id, "focus_entity_id")
            if focus_entity_id
            else None
        )

        observations = await self._observation_repo.list_for_dashboard(
            db,
            nid,
            map_id=mid,
            limit=160,
        )
        facts, _ = await self._fact_repo.list(
            db,
            nid,
            map_id=mid,
            fact_status="confirmed",
            limit=160,
        )
        items: list[tuple[str, Any]] = [("fact", fact) for fact in facts]
        if include_candidates:
            items.extend(
                ("observation", obs)
                for obs in observations
                if obs.review_state in {"candidate", "conflicted"}
            )
        if scene_id:
            scene_uuid = self._safe_uuid(scene_id)
            items = [
                (kind, item)
                for kind, item in items
                if getattr(item, "scene_id", None) in {None, scene_uuid}
                or str(getattr(item, "scene_id", "")) == scene_id
            ]
        if focus_id:
            items = [
                (kind, item)
                for kind, item in items
                if getattr(item, "target_entity_id", None) in {None, focus_id}
            ]

        events: list[MapPlaybackEvent] = []
        for kind, item in items:
            event = self._playback_event_from_item(kind, item)
            if event is not None:
                events.append(event)
        events.sort(
            key=lambda event: (
                event.scene_index is None,
                event.scene_index if event.scene_index is not None else 10**6,
                event.source_chapter_index
                if event.source_chapter_index is not None
                else 10**6,
                event.time_label,
                event.title,
            )
        )
        return MapPlaybackResponse(
            map_id=map_id,
            events=events[:120],
            tracks=self._build_playback_tracks(events),
            low_motion_recommended=len(events) > 40,
        )

    async def create_observation_from_delta_event(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        event: dict[str, Any],
        scene_index: int,
        context_snapshot_id: str | None = None,
        delta_log_id: str | None = None,
    ) -> MapObservationResponse:
        """将 deep import 的通用 delta_event 接入地图候选流。

        该方法宽容处理不完整 LLM 输出：缺失地图、实体或空间锚点时仍保留候选
        观察，但不会写入可疑跨 novel_id 的实体引用。
        """

        nid = parse_uuid(novel_id, "novel_id")
        meta = event.get("meta") or {}
        map_uuid = await self._safe_map_uuid(db, novel_id, meta.get("map_id"))
        target_uuid = await self._safe_entity_uuid(
            db, nid, meta.get("target_entity_id") or meta.get("entity_id")
        )
        dynamic_type = self._normalize_dynamic_type(
            meta.get("dynamic_type")
            or meta.get("map_dynamic_type")
            or event.get("category")
            or "delta_event"
        )
        confidence = self._clamp_confidence(meta.get("confidence", 0.5))
        source_ref = {
            "source": "deep_import_delta_event",
            "delta_log_id": delta_log_id,
            "context_snapshot_id": context_snapshot_id,
            **(meta.get("source_ref") or {}),
        }
        values = {
            "map_id": map_uuid,
            "target_entity_id": target_uuid,
            "target_entity_type": meta.get("target_entity_type")
            or meta.get("entity_type"),
            "target_name": meta.get("target_name")
            or meta.get("entity_name")
            or meta.get("object_name"),
            "dynamic_type": dynamic_type,
            "time_anchor": {
                "scene_index": scene_index,
                **(meta.get("time_anchor") or {}),
            },
            "spatial_anchor": meta.get("spatial_anchor") or {},
            "value_json": {
                "category": event.get("category"),
                "field": event.get("field"),
                "old": event.get("old"),
                "new": event.get("new"),
            },
            "confidence": confidence,
            "review_state": "candidate",
            "source_ref": source_ref,
            "evidence_text": meta.get("evidence_text")
            or meta.get("quote")
            or meta.get("source_text"),
            "scene_id": self._safe_uuid(meta.get("scene_id")),
            "scene_index": scene_index,
            "source_chapter_index": meta.get("source_chapter_index"),
        }
        observation = await self._observation_repo.create(db, nid, values)
        return MapObservationResponse.model_validate(observation)

    def _queue_item_from_observation(self, item: Any) -> MapDashboardQueueItem:
        title = item.target_name or item.target_entity_type or item.dynamic_type
        status_label = self._status_label(item.review_state)
        risk_level = self._risk_level(
            dynamic_type=item.dynamic_type,
            status=item.review_state,
            confidence=item.confidence,
        )
        return MapDashboardQueueItem(
            item_id=str(item.id),
            item_kind="observation",
            title=title,
            target_entity_id=(
                str(item.target_entity_id) if item.target_entity_id else None
            ),
            object_type=item.target_entity_type,
            dynamic_type=item.dynamic_type,
            time_label=self._time_label(item),
            status_label=status_label,
            source_summary=self._source_summary(item),
            priority=self._priority_score(
                dynamic_type=item.dynamic_type,
                status=item.review_state,
                confidence=item.confidence,
                scene_index=item.scene_index,
            ),
            risk_level=risk_level,
            confidence=item.confidence,
            review_state=item.review_state,
        )

    def _queue_item_from_fact(self, item: Any) -> MapDashboardQueueItem:
        title = item.target_name or item.target_entity_type or item.dynamic_type
        return MapDashboardQueueItem(
            item_id=str(item.id),
            item_kind="fact",
            title=title,
            target_entity_id=(
                str(item.target_entity_id) if item.target_entity_id else None
            ),
            object_type=item.target_entity_type,
            dynamic_type=item.dynamic_type,
            time_label=self._time_label(item),
            status_label=self._status_label(item.fact_status),
            source_summary=self._source_summary(item),
            priority=self._priority_score(
                dynamic_type=item.dynamic_type,
                status=item.fact_status,
                confidence=item.confidence,
                scene_index=item.scene_index,
            ),
            risk_level=self._risk_level(
                dynamic_type=item.dynamic_type,
                status=item.fact_status,
                confidence=item.confidence,
            ),
            confidence=item.confidence,
            fact_status=item.fact_status,
        )

    def _build_dashboard_inspector(
        self,
        queue: list[MapDashboardQueueItem],
        *,
        focus_entity_id: str | None,
    ) -> MapDashboardInspector:
        primary = queue[0] if queue else None
        candidates = [
            item
            for item in queue
            if item.item_kind == "observation" and item.review_state == "candidate"
        ]
        facts = [item for item in queue if item.item_kind == "fact"]
        conflicts = [
            item
            for item in queue
            if item.risk_level == "danger" or item.review_state == "conflicted"
        ]
        evidence = []
        for item in queue:
            if item.source_summary and item.source_summary not in evidence:
                evidence.append(item.source_summary)
            if len(evidence) >= 5:
                break
        available_actions = []
        if candidates:
            available_actions.extend(["confirm", "ignore", "conflict"])
        if facts:
            available_actions.extend(["rollback", "deprecated"])
        return MapDashboardInspector(
            title=primary.title if primary else "暂无世界动态",
            status_label=primary.status_label if primary else "等待地图事实",
            summary=(
                "右侧检查器汇总候选映射、正式事实、冲突风险和来源证据。"
                if queue
                else "暂无可检查的地图事实。"
            ),
            focus_entity_id=focus_entity_id,
            object_type=primary.object_type if primary else None,
            object_name=primary.title if primary else None,
            timeline=sorted(queue, key=lambda item: (item.time_label, item.title))[:12],
            available_actions=available_actions,
            map_facts=facts[:5],
            ai_candidates=candidates[:5],
            conflicts=conflicts[:5],
            source_evidence=evidence,
            related_dynamics=queue[:8],
        )

    def _build_first_visual_layer(
        self,
        queue: list[MapDashboardQueueItem],
        *,
        scene_id: str | None,
        risk_summary: list[str],
    ) -> dict[str, Any]:
        crisis = next((item for item in queue if item.dynamic_type == "crisis"), None)
        characters = [
            item.title
            for item in queue
            if item.object_type == "character"
        ][:5]
        scene_events = [
            item.title
            for item in queue
            if scene_id and item.time_label.startswith("Scene")
        ][:5]
        return {
            "current_storyline": self._storyline_label(queue, scene_id=scene_id),
            "main_crisis": crisis.title if crisis else "暂无主线危机",
            "main_characters": characters,
            "current_scene_events": scene_events,
            "top_risks": risk_summary[:3],
        }

    def _build_batch_groups(
        self,
        queue: list[MapDashboardQueueItem],
    ) -> list[MapDashboardBatchGroup]:
        groups: dict[str, dict[str, Any]] = {}
        for item in queue:
            key = item.object_type or item.dynamic_type or "unknown"
            group = groups.setdefault(
                key,
                {
                    "count": 0,
                    "candidate_count": 0,
                    "confirmed_count": 0,
                    "first_joined_label": item.time_label,
                },
            )
            group["count"] += 1
            if item.item_kind == "observation" and item.review_state == "candidate":
                group["candidate_count"] += 1
            if item.item_kind == "fact":
                group["confirmed_count"] += 1
        result = []
        for key, group in groups.items():
            result.append(
                MapDashboardBatchGroup(
                    group_key=key,
                    group_label=self._object_type_label(key),
                    count=group["count"],
                    candidate_count=group["candidate_count"],
                    confirmed_count=group["confirmed_count"],
                    first_joined_label=group["first_joined_label"],
                )
            )
        return sorted(result, key=lambda item: (-item.count, item.group_label))[:12]

    def _build_risk_summary(self, queue: list[MapDashboardQueueItem]) -> list[str]:
        risks = []
        for item in queue:
            if item.risk_level in {"warning", "danger"}:
                risks.append(f"{item.title}：{item.status_label}")
            if len(risks) >= 5:
                break
        return risks

    def _filter_queue_for_focus(
        self,
        queue: list[MapDashboardQueueItem],
        focus_entity_id: str,
    ) -> list[MapDashboardQueueItem]:
        return [
            item
            for item in queue
            if item.target_entity_id == focus_entity_id
        ]

    def _storyline_label(
        self,
        queue: list[MapDashboardQueueItem],
        *,
        scene_id: str | None,
    ) -> str:
        if scene_id:
            return "当前 Scene 相关动态"
        if queue:
            return f"围绕 {queue[0].time_label} 的地图动态"
        return "暂无当前剧情线"

    def _playback_event_from_item(
        self,
        kind: str,
        item: Any,
    ) -> MapPlaybackEvent | None:
        status = getattr(item, "review_state", None) or getattr(item, "fact_status", None)
        if status == "ignored":
            return None
        dynamic_type = self._normalize_dynamic_type(item.dynamic_type)
        return MapPlaybackEvent(
            event_id=str(item.id),
            event_kind="observation" if kind == "observation" else "fact",
            typed_observation=dynamic_type,
            track=self._playback_track(dynamic_type),
            title=item.target_name or item.target_entity_type or dynamic_type,
            time_label=self._time_label(item),
            status_label=self._status_label(status),
            change_summary=self._change_summary(item),
            source_summary=self._source_summary(item),
            spatial_anchor=item.spatial_anchor or {},
            scene_index=item.scene_index,
            source_chapter_index=item.source_chapter_index,
            risk_level=self._risk_level(
                dynamic_type=dynamic_type,
                status=status,
                confidence=item.confidence,
            ),
            confidence=item.confidence,
        )

    def _build_playback_tracks(
        self,
        events: list[MapPlaybackEvent],
    ) -> list[MapPlaybackTrack]:
        groups: dict[str, MapPlaybackTrack] = {}
        for event in events:
            if event.track not in groups:
                groups[event.track] = MapPlaybackTrack(
                    track=event.track,
                    label=self._playback_track_label(event.track),
                    count=0,
                    first_time_label=event.time_label,
                )
            groups[event.track].count += 1
        order = ["journey", "territory", "crisis", "resource", "status", "world"]
        return sorted(groups.values(), key=lambda track: order.index(track.track))

    def _change_summary(self, item: Any) -> str:
        value = item.value_json or {}
        old_value = value.get("old")
        new_value = value.get("new")
        field = value.get("field") or value.get("category") or item.dynamic_type
        if old_value not in {None, ""} and new_value not in {None, ""}:
            return f"{field}：{old_value} → {new_value}"
        if new_value not in {None, ""}:
            return f"{field}：{new_value}"
        if item.evidence_text:
            return item.evidence_text
        return "状态变化待确认"

    def _playback_track(self, dynamic_type: str) -> str:
        if dynamic_type in {"location", "position_change", "movement"}:
            return "journey"
        if dynamic_type in {"boundary", "boundary_change", "territory"}:
            return "territory"
        if dynamic_type in {"crisis", "crisis_spread", "risk", "conflict"}:
            return "crisis"
        if dynamic_type in {"resource", "resource_control", "resource_control_change"}:
            return "resource"
        if dynamic_type in {"status", "status_change"}:
            return "status"
        return "world"

    def _playback_track_label(self, track: str) -> str:
        return {
            "journey": "人物旅程",
            "territory": "势力变化",
            "crisis": "危机推进",
            "resource": "资源控制",
            "status": "状态变化",
            "world": "世界状态",
        }.get(track, track)

    def _priority_score(
        self,
        *,
        dynamic_type: str,
        status: str,
        confidence: float | None,
        scene_index: int | None,
    ) -> int:
        score = 10
        if status == "conflicted":
            score += 100
        if status == "candidate":
            score += 70
        if dynamic_type in {"crisis", "risk", "conflict"}:
            score += 60
        if dynamic_type in {"location", "status", "boundary"}:
            score += 30
        if scene_index is not None:
            score += min(scene_index, 30)
        if confidence is not None and confidence < 0.45:
            score += 20
        return score

    def _risk_level(
        self,
        *,
        dynamic_type: str,
        status: str,
        confidence: float | None,
    ) -> str:
        if status == "conflicted" or dynamic_type in {"crisis", "risk", "conflict"}:
            return "danger"
        if status == "candidate" or (confidence is not None and confidence < 0.5):
            return "warning"
        return "info"

    def _time_label(self, item: Any) -> str:
        time_anchor = item.time_anchor or {}
        scene_index = getattr(item, "scene_index", None) or time_anchor.get("scene_index")
        if scene_index is not None:
            return f"Scene {scene_index}"
        chapter_index = getattr(item, "source_chapter_index", None) or time_anchor.get(
            "chapter_index"
        )
        if chapter_index is not None:
            return f"第 {chapter_index} 章"
        return "时间待确认"

    def _status_label(self, status: str | None) -> str:
        return {
            "candidate": "待确认",
            "confirmed": "已确认",
            "ignored": "已忽略",
            "conflicted": "有冲突",
            "rolled_back": "已回滚",
            "deprecated": "已废弃",
        }.get(status or "", "待判断")

    def _source_summary(self, item: Any) -> str:
        source_ref = item.source_ref or {}
        source = source_ref.get("source") or source_ref.get("operation") or "来源待确认"
        evidence = item.evidence_text or ""
        if evidence:
            return f"{source} · {evidence}"
        return str(source)

    def _object_type_label(self, key: str) -> str:
        return {
            "character": "人物",
            "location": "地点",
            "organization": "组织",
            "event": "事件",
            "item": "物品",
            "resource": "资源",
            "crisis": "危机",
            "status": "状态",
            "boundary": "边界",
            "semantic": "语义",
        }.get(key, key)

    def _observation_values(
        self,
        data: MapObservationCreate,
        *,
        map_id: uuid.UUID | None,
    ) -> dict[str, Any]:
        return {
            "map_id": map_id,
            "target_entity_id": (
                parse_uuid(data.target_entity_id, "target_entity_id")
                if data.target_entity_id
                else None
            ),
            "target_entity_type": data.target_entity_type,
            "target_name": data.target_name,
            "dynamic_type": self._normalize_dynamic_type(data.dynamic_type),
            "time_anchor": data.time_anchor or {},
            "spatial_anchor": data.spatial_anchor or {},
            "value_json": data.value_json or {},
            "confidence": data.confidence,
            "review_state": data.review_state,
            "source_ref": data.source_ref or {},
            "evidence_text": data.evidence_text,
            "scene_id": parse_uuid(data.scene_id, "scene_id") if data.scene_id else None,
            "scene_index": data.scene_index,
            "source_chapter_index": data.source_chapter_index,
        }

    def _assert_observation_in_novel(
        self,
        observation: Any,
        observation_id: str,
        novel_id: uuid.UUID,
    ) -> None:
        if observation is None or observation.novel_id != novel_id:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"MapObservation {observation_id} not found",
            )

    def _assert_observation_in_map(
        self,
        observation: Any,
        observation_id: str,
        map_id: uuid.UUID,
    ) -> None:
        if observation.map_id is not None and observation.map_id != map_id:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"MapObservation {observation_id} not found",
            )

    def _assert_fact_access(
        self,
        fact: Any,
        fact_id: str,
        novel_id: uuid.UUID,
        map_id: uuid.UUID,
    ) -> None:
        if fact is None or fact.novel_id != novel_id or fact.map_id != map_id:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"MapFact {fact_id} not found",
            )

    def _assert_spatial_anchor_in_bounds(self, config: Any, spatial_anchor: dict) -> None:
        if "hex_q" not in spatial_anchor or "hex_r" not in spatial_anchor:
            return
        self._ctx.assert_hex_in_bounds(
            config,
            int(spatial_anchor["hex_q"]),
            int(spatial_anchor["hex_r"]),
        )

    async def _safe_map_uuid(
        self,
        db: AsyncSession,
        novel_id: str,
        raw_map_id: Any,
    ) -> uuid.UUID | None:
        if not raw_map_id:
            return None
        try:
            config = await self._ctx.require_map(db, novel_id, str(raw_map_id))
            return config.id
        except (HTTPException, TypeError, ValueError):
            logger.warning("Ignoring invalid map_id in map observation: %r", raw_map_id)
            return None

    async def _safe_entity_uuid(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        raw_entity_id: Any,
    ) -> uuid.UUID | None:
        entity_id = self._safe_uuid(raw_entity_id)
        if entity_id is None:
            return None
        entity = await self._entity_repo.get(db, entity_id)
        if entity is None or entity.novel_id != novel_id:
            logger.warning(
                "Ignoring invalid target_entity_id in map observation: %r",
                raw_entity_id,
            )
            return None
        return entity_id

    @staticmethod
    def _safe_uuid(raw_value: Any) -> uuid.UUID | None:
        if not raw_value:
            return None
        try:
            return uuid.UUID(str(raw_value))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _clamp_confidence(raw_value: Any) -> float:
        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            return 0.5
        return min(max(value, 0.0), 1.0)

    @staticmethod
    def _normalize_dynamic_type(raw_value: Any) -> str:
        value = str(raw_value or "delta_event").strip().lower()
        return value[:64] or "delta_event"
