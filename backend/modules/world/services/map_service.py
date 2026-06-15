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
from typing import Any

from fastapi import HTTPException
from fastapi import status as http_status
from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.map_models import MapConfig
from modules.world.map_repositories import (
    MapConfigRepository,
    MapLocationBindingRepository,
    MapMarkerRepository,
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
    MapTileBatchUpdate,
    MapTileChange,
    MapTileResponse,
)
from modules.world.repositories import CoreEntityRepository
from modules.world.services.base import CrudService
from modules.world.services.helpers import parse_uuid

# ============================================================
# 地形模板生成器（初始化世界地图用）
# ============================================================

# 默认地形
_BLANK_TERRAIN = "grassland"


def _generate_blank_tiles(width: int, height: int) -> list[MapTileChange]:
    """空白模板：全 grassland。"""
    return [
        MapTileChange(hex_q=q, hex_r=r, terrain_type=_BLANK_TERRAIN)
        for q in range(width)
        for r in range(height)
    ]


def _generate_continent_tiles(width: int, height: int) -> list[MapTileChange]:
    """大陆模板：中心陆地 + 边缘水。

    简化算法：用到中心的距离判断，内部随机 grassland/forest，边缘 water。
    确定性（seed 固定）避免每次创建结果不同。
    """
    rng = random.Random(42)
    cx, cy = width / 2, height / 2
    max_dist = (width**2 + height**2) ** 0.5 / 2
    tiles: list[MapTileChange] = []
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
            tiles.append(MapTileChange(hex_q=q, hex_r=r, terrain_type=terrain))
    return tiles


def _generate_islands_tiles(width: int, height: int) -> list[MapTileChange]:
    """群岛模板：散布小岛 + 大量水。"""
    rng = random.Random(7)
    tiles: list[MapTileChange] = []
    for q in range(width):
        for r in range(height):
            # 约 25% 陆地，散布成岛
            if rng.random() < 0.25:
                terrain = rng.choice(["grassland", "forest", "mountain"])
            else:
                terrain = "water"
            tiles.append(MapTileChange(hex_q=q, hex_r=r, terrain_type=terrain))
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
) -> list[MapTileChange]:
    """按模板生成初始 tile。未知模板回退 blank。"""
    if template and template in _TEMPLATES:
        return _TEMPLATES[template](width, height)
    return _generate_blank_tiles(width, height)


# ============================================================
# 详图快速生成（PRD §路径 3）
# ============================================================


def generate_detail_tiles(width: int, height: int) -> list[MapTileChange]:
    """详图快速生成：中心 3 圈 city + 外 1 圈 road + 其余随机 grassland/forest。

    以网格中心为圆心，用六边形距离（近似欧氏距离足够 P0）。
    """
    rng = random.Random(123)
    cx, cy = width / 2, height / 2
    city_radius = min(width, height) * 0.18  # 约 3 圈
    road_radius = city_radius * 1.4
    tiles: list[MapTileChange] = []
    for q in range(width):
        for r in range(height):
            dist = ((q - cx) ** 2 + (r - cy) ** 2) ** 0.5
            if dist <= city_radius:
                terrain = "city"
            elif dist <= road_radius:
                terrain = "road"
            else:
                terrain = rng.choice(["grassland", "forest"])
            tiles.append(MapTileChange(hex_q=q, hex_r=r, terrain_type=terrain))
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
        self._entity_repo = CoreEntityRepository()

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
                    detail=f"CoreEntity {data.parent_entity_id} not found",
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

        config = await self.repo.create(db, nid, data)

        # 生成初始 tile
        template = data.template if data.map_type == "world" else "blank"
        tiles = generate_template_tiles(data.grid_width, data.grid_height, template)
        await self._tile_repo.bulk_create(db, nid, config.id, tiles)

        # 刷新 config 以拿到完整字段
        fresh = await self.repo.get(db, config.id)
        assert fresh is not None
        return MapConfigResponse.model_validate(fresh)

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
        nid = parse_uuid(novel_id, "novel_id")
        mid = parse_uuid(map_id, "map_id")
        config = await self.repo.get(db, mid)
        self._assert_found_in_novel(config, map_id, nid)
        assert config is not None

        breadcrumbs = await self.repo.get_breadcrumbs(db, mid)
        tiles = await self._tile_repo.get_by_map(db, nid, mid)
        bindings = await self._binding_repo.get_by_map(db, nid, mid)

        marker_repo = MapMarkerRepository()
        sid = parse_uuid(scene_id, "scene_id") if scene_id else None
        markers = await marker_repo.get_by_map(db, nid, mid, scene_id=sid)
        markers_list = [MapMarkerResponse.model_validate(m) for m in markers]

        scene_info = None
        if scene_id:
            from modules.outline.services import SceneService

            scene_svc = SceneService()
            try:
                scene = await scene_svc.get(db, scene_id, novel_id=novel_id)
                scene_info = {
                    "id": str(scene.id),
                    "index": scene.scene_index,
                    "title": scene.title,
                    "chapter_title": None,
                }
            except HTTPException:
                scene_info = None

        return MapStateResponse(
            map=MapConfigResponse.model_validate(config),
            breadcrumbs=[MapConfigResponse.model_validate(b) for b in breadcrumbs],
            tiles=[MapTileResponse.model_validate(t) for t in tiles],
            location_bindings=[
                MapLocationBindingResponse.model_validate(b) for b in bindings
            ],
            markers=markers_list,
            scene=scene_info,
        )

    # 新增: 快速生成详图地形（PRD §路径 3）
    async def generate(
        self,
        db: AsyncSession,
        novel_id: str,
        map_id: str,
    ) -> MapStateResponse:
        """清空并重新生成详图地形（中心 city + 外 road + 随机 grassland/forest）。"""
        nid = parse_uuid(novel_id, "novel_id")
        mid = parse_uuid(map_id, "map_id")
        config = await self.repo.get(db, mid)
        self._assert_found_in_novel(config, map_id, nid)
        assert config is not None

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

    def __init__(self, tile_repo: MapTileRepository | None = None) -> None:
        self._tile_repo = tile_repo or MapTileRepository()

    async def batch_update(
        self,
        db: AsyncSession,
        novel_id: str,
        map_id: str,
        data: MapTileBatchUpdate,
    ) -> list[MapTileResponse]:
        nid = parse_uuid(novel_id, "novel_id")
        mid = parse_uuid(map_id, "map_id")

        # 校验 map 属 novel + 取 grid 尺寸
        from modules.world.map_repositories import MapConfigRepository

        config = await MapConfigRepository().get(db, mid)
        if config is None or config.novel_id != nid:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"MapConfig {map_id} not found",
            )

        # 校验 hex 在范围内
        for change in data.changes:
            if change.hex_q < 0 or change.hex_q >= config.grid_width:
                raise HTTPException(
                    status_code=http_status.HTTP_400_BAD_REQUEST,
                    detail=f"hex_q {change.hex_q} 超出网格宽度 {config.grid_width}",
                )
            if change.hex_r < 0 or change.hex_r >= config.grid_height:
                raise HTTPException(
                    status_code=http_status.HTTP_400_BAD_REQUEST,
                    detail=f"hex_r {change.hex_r} 超出网格高度 {config.grid_height}",
                )

        await self._tile_repo.bulk_upsert(db, nid, mid, data.changes)
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
        config_repo: MapConfigRepository | None = None,
    ) -> None:
        self._binding_repo = binding_repo or MapLocationBindingRepository()
        self._entity_repo = entity_repo or CoreEntityRepository()
        self._config_repo = config_repo or MapConfigRepository()

    async def _validate_map_and_entity(
        self,
        db: AsyncSession,
        novel_id: str,
        map_id: str,
        location_entity_id: str,
    ) -> tuple[MapConfig, Any]:
        """校验 map 属 novel + entity 属同 novel 且 type=location。

        返回 (config, entity)。
        """
        nid = parse_uuid(novel_id, "novel_id")
        mid = parse_uuid(map_id, "map_id")
        eid = parse_uuid(location_entity_id, "location_entity_id")

        config = await self._config_repo.get(db, mid)
        if config is None or config.novel_id != nid:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"MapConfig {map_id} not found",
            )

        entity = await self._entity_repo.get(db, eid)
        if entity is None or entity.novel_id != nid:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"CoreEntity {location_entity_id} not found",
            )
        if entity.entity_type != "location":
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"实体 {entity.name} 类型为 {entity.entity_type}，"
                    "只能绑定 location 类型实体"
                ),
            )
        return config, entity

    async def batch_create(
        self,
        db: AsyncSession,
        novel_id: str,
        map_id: str,
        data: MapLocationBindingCreate,
    ) -> list[MapLocationBindingResponse]:
        config, _entity = await self._validate_map_and_entity(
            db, novel_id, map_id, data.location_entity_id
        )

        # 校验 hex 范围
        for h in data.hexes:
            if not (0 <= h.hex_q < config.grid_width):
                raise HTTPException(
                    status_code=http_status.HTTP_400_BAD_REQUEST,
                    detail=f"hex_q {h.hex_q} 超出网格宽度 {config.grid_width}",
                )
            if not (0 <= h.hex_r < config.grid_height):
                raise HTTPException(
                    status_code=http_status.HTTP_400_BAD_REQUEST,
                    detail=f"hex_r {h.hex_r} 超出网格高度 {config.grid_height}",
                )

        eid = parse_uuid(data.location_entity_id, "location_entity_id")
        mid = parse_uuid(map_id, "map_id")
        nid = parse_uuid(novel_id, "novel_id")

        # 中心点冲突：若新增含 is_center=true，先清旧中心
        has_new_center = any(h.is_center for h in data.hexes)
        if has_new_center:
            await self._binding_repo.clear_center(db, mid, eid)

        objs = await self._binding_repo.bulk_create(db, nid, mid, eid, data.hexes)
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

        updated = await self._binding_repo.update(db, bid, data)
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

    def __init__(self) -> None:
        self.repo = MapMarkerRepository()
        self._map_repo = MapConfigRepository()

    async def list(
        self,
        db: AsyncSession,
        novel_id: str,
        map_id: str,
        scene_id: str | None = None,
    ) -> list[MapMarkerResponse]:
        nid = parse_uuid(novel_id, "novel_id")
        mid = parse_uuid(map_id, "map_id")
        sid = parse_uuid(scene_id, "scene_id") if scene_id else None

        config = await self._map_repo.get(db, mid)
        if config is None or config.novel_id != nid:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"MapConfig {map_id} not found",
            )

        markers = await self.repo.get_by_map(db, nid, mid, scene_id=sid)
        return [MapMarkerResponse.model_validate(m) for m in markers]

    async def create(
        self,
        db: AsyncSession,
        novel_id: str,
        map_id: str,
        data: MapMarkerCreate,
    ) -> MapMarkerResponse:
        nid = parse_uuid(novel_id, "novel_id")
        mid = parse_uuid(map_id, "map_id")

        config = await self._map_repo.get(db, mid)
        if config is None or config.novel_id != nid:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"MapConfig {map_id} not found",
            )

        if data.hex_q < 0 or data.hex_q >= config.grid_width:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail=f"hex_q {data.hex_q} 超出网格宽度 {config.grid_width}",
            )
        if data.hex_r < 0 or data.hex_r >= config.grid_height:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail=f"hex_r {data.hex_r} 超出网格高度 {config.grid_height}",
            )

        from modules.world.models import CoreEntity

        eid = parse_uuid(data.entity_id, "entity_id")
        from sqlalchemy import select as sa_select

        entity = (
            await db.execute(sa_select(CoreEntity).where(CoreEntity.id == eid))
        ).scalar_one_or_none()
        if entity is None or entity.novel_id != nid:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"CoreEntity {data.entity_id} not found",
            )

        marker = await self.repo.create(db, nid, mid, data)
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

        updated = await self.repo.update(db, mkid, data)
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
