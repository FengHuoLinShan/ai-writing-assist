from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from core.crud import CrudService
from core.errors import ConflictError, NotFoundError, ValidationError
from modules.world.map_repositories import (
    MapConfigRepository,
    MapLocationBindingRepository,
    MapTerritoryRepository,
    MapTileRepository,
)
from modules.world.map_schemas import (
    MapConfigCreate,
    MapConfigListResponse,
    MapConfigResponse,
    MapConfigUpdate,
    MapDynamicStateResponse,
    MapStateResponse,
)
from modules.world.repositories import CoreEntityRepository
from modules.world.services.common import parse_uuid
from modules.world.services.map.map_context import MapContext
from modules.world.services.map.map_state_assembler import MapStateAssembler
from modules.world.services.map.map_templates import (
    generate_detail_tiles,
    generate_template_tiles,
)

logger = logging.getLogger(__name__)


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

    def _raise_404(self, id: str) -> None:
        raise NotFoundError(f"{self.label} {id} not found", code="map_not_found")

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
                raise ValidationError(
                    "parent_map_id 不存在或不属于该项目",
                    code="invalid_parent_map",
                )
            parent_map_id_uuid = pid

        # 校验 parent_entity_id 属同 novel 且 entity_type=location（PRD §4.1/§4.3）
        if data.parent_entity_id:
            eid = parse_uuid(data.parent_entity_id, "parent_entity_id")
            entity = await self._entity_repo.get(db, eid)
            if entity is None or entity.novel_id != nid:
                raise NotFoundError(
                    f"实体 {data.parent_entity_id} 不存在",
                    code="entity_not_found",
                )
            if entity.entity_type != "location":
                raise ValidationError(
                    f"实体 {entity.name} 类型为 {entity.entity_type}，"
                    "parent_entity_id 必须为 location 类型",
                    code="invalid_parent_entity_type",
                )

        # PostgreSQL NULL 不参与 unique 约束，业务层按同父级精确查重。
        existing = await self.repo.get_by_name(
            db,
            nid,
            name=data.name,
            parent_map_id=parent_map_id_uuid,
        )
        if existing is not None:
            raise ConflictError(
                f"同层级已存在名为 {data.name!r} 的地图",
                code="duplicate_map_name",
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

        obj = await self.repo.update(db, existing, values)
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

    async def get_dynamic_state(
        self,
        db: AsyncSession,
        novel_id: str,
        map_id: str,
        *,
        scene_id: str | None = None,
    ) -> MapDynamicStateResponse:
        """聚合 Scene 相关动态层，避免切换 Scene 时重取静态地图数据。"""
        return await self._state_assembler.assemble_dynamic(
            db,
            novel_id,
            map_id,
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
            raise ValidationError(
                "快速生成仅用于详图（city/region/dungeon），世界地图请用模板创建",
                code="invalid_map_generation_target",
            )

        # 清空现有 tile 再生成（demo 阶段允许直接重建）
        await self._tile_repo.delete_by_map(db, nid, mid)
        changes = generate_detail_tiles(config.grid_width, config.grid_height)
        await self._tile_repo.bulk_create(db, nid, mid, changes)
        return await self.get_state(db, novel_id, map_id)
