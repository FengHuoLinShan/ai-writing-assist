"""
Geo Facade — 对外入口

其他模块只能从 facade 导入。
Facade 不写复杂业务逻辑，只做稳定的对外代理。
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from modules.geo.contracts import (
    RouteCalculationResult,
)
from modules.geo.schemas import GeoContextBundle, TravelConstraintResult
from modules.geo.services import GeoQueryService, GeoTopologyService

_query_service = GeoQueryService()
_topology_service = GeoTopologyService()


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
        db,
        novel_id,
        location_id,
        depth,
    )


async def get_locations_context_batch(
    db: AsyncSession,
    novel_id: str,
    location_ids: list[str],
    depth: int = 1,
) -> list[GeoContextBundle]:
    """批量获取地点上下文

    并行查询多个地点，避免 N+1 循环。每个地点独立执行，异常不影响其他。

    Args:
        db: 数据库 session
        novel_id: 项目 ID
        location_ids: 地点 ID 列表
        depth: 递归深度

    Returns:
        list[GeoContextBundle]: 地点上下文列表（不存在的 ID 跳过）
    """
    import asyncio

    tasks = [
        _query_service.get_location_context(db, novel_id, lid, depth)
        for lid in location_ids
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return [
        r for r in results if isinstance(r, GeoContextBundle) and r.location is not None
    ]


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
        db,
        novel_id,
        source_location_id,
        target_location_id,
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
        db,
        novel_id,
        era_id,
        location_ids,
    )


async def calculate_route(
    db: AsyncSession,
    novel_id: str,
    source_location_id: str,
    target_location_id: str,
    chapter_index: int,
) -> RouteCalculationResult:
    """计算两地之间的最短旅行路径

    基于当前章节的动态地理拓扑（静态边 + 时间线事件覆写），
    使用 Dijkstra 算法计算最短可达路径与旅行耗时。

    Args:
        db: 数据库 session
        novel_id: 项目 ID
        source_location_id: 起点地点 ID
        target_location_id: 终点地点 ID
        chapter_index: 截止章节索引

    Returns:
        RouteCalculationResult: 路径计算结果
    """
    return await _topology_service.calculate_route(
        db,
        novel_id,
        source_location_id,
        target_location_id,
        chapter_index,
    )
