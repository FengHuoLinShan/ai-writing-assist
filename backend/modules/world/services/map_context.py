"""地图子系统共享上下文守卫。

把地图操作中最常见的横切校验收敛到一个可注入的 depth module：
- novel_id 隔离（map / entity 属同 novel）
- hex 坐标在 grid 范围内
- entity 存在且类型符合预期

service 层通过构造注入 MapContext，测试时可替换为 fake。
"""

from __future__ import annotations

from collections.abc import Container
from typing import TYPE_CHECKING

from fastapi import HTTPException
from fastapi import status as http_status
from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.map_repositories import MapConfigRepository
from modules.world.repositories import CoreEntityRepository
from modules.world.services.helpers import parse_uuid

if TYPE_CHECKING:
    from modules.world.map_models import MapConfig
    from modules.world.models import CoreEntity


class MapContext:
    """地图操作上下文守卫。

    接口很小，但把之前散落在各 service 中的重复校验集中到一个 seam 后。
    """

    def __init__(
        self,
        config_repo: MapConfigRepository | None = None,
        entity_repo: CoreEntityRepository | None = None,
    ) -> None:
        self._config_repo = config_repo or MapConfigRepository()
        self._entity_repo = entity_repo or CoreEntityRepository()

    async def require_map(
        self,
        db: AsyncSession,
        novel_id: str,
        map_id: str,
    ) -> MapConfig:
        """校验 map 存在且属于指定 novel，返回 MapConfig；否则 404。"""
        nid = parse_uuid(novel_id, "novel_id")
        mid = parse_uuid(map_id, "map_id")
        config = await self._config_repo.get(db, mid)
        if config is None or config.novel_id != nid:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"地图 {map_id} 不存在",
            )
        return config

    async def require_entity(
        self,
        db: AsyncSession,
        novel_id: str,
        entity_id: str,
        *,
        allowed_types: Container[str] | None = None,
    ) -> CoreEntity:
        """校验 entity 存在、属于指定 novel 且类型符合预期，返回 CoreEntity；否则抛错。"""
        nid = parse_uuid(novel_id, "novel_id")
        eid = parse_uuid(entity_id, "entity_id")
        entity = await self._entity_repo.get(db, eid)
        if entity is None or entity.novel_id != nid:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"实体 {entity_id} 不存在",
            )
        if allowed_types and entity.entity_type not in allowed_types:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"实体 {entity.name} 类型为 {entity.entity_type}，"
                    f"只接受 {','.join(sorted(allowed_types))} 类型"
                ),
            )
        return entity

    def assert_hex_in_bounds(
        self,
        config: MapConfig,
        hex_q: int,
        hex_r: int,
    ) -> None:
        """校验 hex 坐标在 grid 范围内，否则 400。"""
        if not (0 <= hex_q < config.grid_width):
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail=f"hex_q {hex_q} 超出网格宽度 {config.grid_width}",
            )
        if not (0 <= hex_r < config.grid_height):
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail=f"hex_r {hex_r} 超出网格高度 {config.grid_height}",
            )
