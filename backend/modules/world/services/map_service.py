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

import random
import uuid
from typing import Any

from fastapi import HTTPException
from fastapi import status as http_status
from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.map_repositories import (
    MapConfigRepository,
    MapLocationBindingRepository,
    MapMarkerRepository,
    MapTerritoryRepository,
    MapTileRepository,
)
from modules.world.map_schemas import (
    MapConfigCreate,
    MapConfigListResponse,
    MapConfigResponse,
    MapConfigUpdate,
    MapLocationBindingCreate,
    MapLocationBindingResponse,
    MapLocationBindingUpdate,
    MapMarkerCreate,
    MapMarkerResponse,
    MapMarkerUpdate,
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

        # 顶层地图重名校验
        # （PostgreSQL NULL 不参与 unique 约束，业务层补；PRD §4.1 同层级唯一）
        existing, _ = await self.repo.get_by_novel(
            db, nid, parent_map_id=parent_map_id_uuid, skip=0, limit=100
        )
        if any(m.name == data.name for m in existing):
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
