"""
Geo Facade — 对外入口

其他模块只能从 facade 导入。
Facade 不写复杂业务逻辑，只做稳定的对外代理。
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from modules.geo.contracts import (
    GeoContextBundle as GeoContextContract,
    GeoEdgeContract,
    GeoEraContract,
    GeoLocationContract,
    TravelConstraintContract,
)
from modules.geo.schemas import GeoContextBundle, LocationNode, TravelConstraintResult
from modules.geo.services import GeoQueryService

_query_service = GeoQueryService()


async def get_location_context(
    db: AsyncSession,
    novel_id: str,
    location_id: str,
    depth: int = 1,
) -> GeoContextBundle:
    """获取地点上下文

    返回地点信息、上级地点链、子地点、关联边、历史时期上下文。

    Args:
        db: 数据库 session
        novel_id: 项目 ID
        location_id: 地点 ID
        depth: 递归深度（当前版本 depth 参数预留，始终返回完整上下文）

    Returns:
        GeoContextBundle: 地理上下文组合
    """
    return await _query_service.get_location_context(
        db, novel_id, location_id, depth,
    )


async def get_location_tree(
    db: AsyncSession,
    novel_id: str,
) -> list[dict]:
    """获取地点层级树

    Args:
        db: 数据库 session
        novel_id: 项目 ID

    Returns:
        list[dict]: 递归的地点树结构
    """
    return await _query_service.get_location_tree(db, novel_id)


async def get_travel_constraints(
    db: AsyncSession,
    novel_id: str,
    source_location_id: str,
    target_location_id: str,
) -> TravelConstraintResult:
    """查询两地之间的通行约束

    Args:
        db: 数据库 session
        novel_id: 项目 ID
        source_location_id: 起点地点 ID
        target_location_id: 终点地点 ID

    Returns:
        TravelConstraintResult: 通行约束信息
    """
    return await _query_service.get_travel_constraints(
        db, novel_id, source_location_id, target_location_id,
    )


async def get_geo_history_context(
    db: AsyncSession,
    novel_id: str,
    era_id: str | None = None,
    location_ids: list[str] | None = None,
) -> dict:
    """获取地理历史上下文

    返回指定/所有历史时期下，指定/所有地点的状态变化。

    Args:
        db: 数据库 session
        novel_id: 项目 ID
        era_id: 指定历史时期 ID（可选）
        location_ids: 指定地点 ID 列表（可选）

    Returns:
        dict: 地理历史上下文数据
    """
    return await _query_service.get_geo_history_context(
        db, novel_id, era_id, location_ids,
    )
