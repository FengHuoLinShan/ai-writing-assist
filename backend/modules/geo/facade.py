"""
Geo Facade — 对外入口

GeoLocation 以 entity_id 为 PK (= core_entities.id)，仅管理地理扩展字段。
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from modules.geo.contracts import (
    GeoContextBundle as GeoContextContract,
    GeoEdgeContract,
    GeoEraContract,
    GeoLocationContract,
    RouteCalculationResult,
    TravelConstraintContract,
)
from modules.geo.schemas import GeoContextBundle, LocationNode, TravelConstraintResult
from modules.geo.services import GeoQueryService, GeoTopologyService

_query_service = GeoQueryService()
_topology_service = GeoTopologyService()


async def create_location_extension(
    db: AsyncSession,
    entity_id: str,
    novel_id: str,
    **kwargs,
):
    """创建地点扩展记录 — 供 world 模块在创建 location 类型后调用"""
    from modules.geo.schemas import GeoLocationCreate
    from modules.geo.repositories import GeoLocationRepository

    data = GeoLocationCreate(
        entity_id=entity_id,
        novel_id=novel_id,
        **{k: v for k, v in kwargs.items() if v is not None},
    )
    return await GeoLocationRepository().create(db, data)


async def get_location_context(
    db: AsyncSession, novel_id: str, location_id: str, depth: int = 1,
) -> GeoContextBundle:
    return await _query_service.get_location_context(db, novel_id, location_id, depth)


async def get_locations_context_batch(
    db: AsyncSession, novel_id: str, location_ids: list[str], depth: int = 1,
) -> list[GeoContextBundle]:
    import asyncio
    tasks = [_query_service.get_location_context(db, novel_id, lid, depth) for lid in location_ids]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return [r for r in results if isinstance(r, GeoContextBundle) and r.location is not None]


async def get_location_tree(db: AsyncSession, novel_id: str) -> list[dict]:
    return await _query_service.get_location_tree(db, novel_id)


async def get_travel_constraints(
    db: AsyncSession, novel_id: str, source_location_id: str, target_location_id: str,
) -> TravelConstraintResult:
    return await _query_service.get_travel_constraints(db, novel_id, source_location_id, target_location_id)


async def get_geo_history_context(
    db: AsyncSession, novel_id: str,
    era_id: str | None = None, location_ids: list[str] | None = None,
) -> dict:
    return await _query_service.get_geo_history_context(db, novel_id, era_id, location_ids)


async def calculate_route(
    db: AsyncSession, novel_id: str,
    source_location_id: str, target_location_id: str, chapter_index: int,
) -> RouteCalculationResult:
    return await _topology_service.calculate_route(
        db, novel_id, source_location_id, target_location_id, chapter_index,
    )
