"""World 模块测试共享 helper 工厂函数。

非 pytest fixture 的普通 async 工厂，供需要精细控制 setup 的测试直接调用。
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.map_models import MapConfig
from modules.world.map_schemas import MapConfigCreate
from modules.world.services.map_service import MapConfigService
from tests.utils import _create_entity as _create_entity
from tests.utils import _create_project as _create_project


async def _create_location_entity(
    db_session: AsyncSession,
    novel_id: str,
    name: str = "洛阳",
) -> str:
    """创建一个 location 类型的 CoreEntity，返回 id。"""
    entity = await _create_entity(
        db_session,
        novel_id,
        entity_type="location",
        name=name,
        summary=f"{name}地点",
    )
    return str(entity.id)


async def _create_organization(
    db_session: AsyncSession,
    novel_id: str,
    name: str = "天机阁",
) -> str:
    """创建一个 organization 类型的 CoreEntity，返回 id。"""
    entity = await _create_entity(
        db_session,
        novel_id,
        entity_type="organization",
        name=name,
        summary=f"{name}组织",
    )
    return str(entity.id)


async def _create_map_config(
    db_session: AsyncSession,
    novel_id: str,
    *,
    grid_width: int = 10,
    grid_height: int = 10,
) -> MapConfig:
    """直接创建 MapConfig ORM 对象（不生成 tiles），返回对象。"""
    config = MapConfig(
        id=uuid.uuid4(),
        novel_id=uuid.UUID(hex=novel_id),
        name="测试地图",
        map_type="world",
        grid_width=grid_width,
        grid_height=grid_height,
        hex_size=30,
        default_center_x=0.5,
        default_center_y=0.5,
        default_zoom=1.0,
        sort_order=0,
    )
    db_session.add(config)
    await db_session.flush()
    return config


async def _create_default_map(db_session: AsyncSession, novel_id: str):
    """通过 MapConfigService 创建 10x10 world map（生成 tiles）。"""
    svc = MapConfigService()
    return await svc.create(
        db_session,
        novel_id,
        MapConfigCreate(name="m", map_type="world", grid_width=10, grid_height=10),
    )
