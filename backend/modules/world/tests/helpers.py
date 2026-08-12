"""World 模块测试共享 helper 工厂函数。

非 pytest fixture 的普通 async 工厂，供需要精细控制 setup 的测试直接调用。
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

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
