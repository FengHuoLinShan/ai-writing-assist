"""
Geo API 路由

提供地理地点、关系边、历史时期的 REST CRUD API，
以及地点树、通行约束等业务查询接口。

API 层不写复杂业务逻辑，仅做参数校验和路由分发。
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from core.dependencies import DbSession
from modules.geo.schemas import (
    GeoEdgeCreate,
    GeoEdgeListResponse,
    GeoEdgeResponse,
    GeoEdgeUpdate,
    GeoEraCreate,
    GeoEraListResponse,
    GeoEraResponse,
    GeoEraUpdate,
    GeoLocationCreate,
    GeoLocationListResponse,
    GeoLocationResponse,
    GeoLocationUpdate,
    RouteQueryRequest,
    RouteQueryResponse,
    TravelConstraintResult,
)
from modules.geo.services import GeoEdgeService, GeoEraService, GeoLocationService, GeoQueryService, GeoTopologyService
from shared.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE

router = APIRouter(prefix="/api/geo", tags=["geo"])

_location_service = GeoLocationService()
_edge_service = GeoEdgeService()
_era_service = GeoEraService()
_query_service = GeoQueryService()
_topology_service = GeoTopologyService()


# ============================================================
# GeoLocation 路由
# ============================================================

@router.post("/locations", response_model=GeoLocationResponse, status_code=201)
async def create_location(
    db: DbSession,
    data: GeoLocationCreate,
) -> GeoLocationResponse:
    """创建地理地点"""
    return await _location_service.create_location(db, data)


@router.get("/locations", response_model=GeoLocationListResponse)
async def list_locations(
    db: DbSession,
    novel_id: str = Query(..., description="小说项目 ID"),
    skip: int = Query(default=0, ge=0, description="跳过的记录数"),
    limit: int = Query(
        default=DEFAULT_PAGE_SIZE,
        ge=1,
        le=MAX_PAGE_SIZE,
        description="每页条数",
    ),
    location_level: str | None = Query(
        default=None,
        description="按地点层级筛选",
    ),
) -> GeoLocationListResponse:
    """获取地点列表"""
    items, total = await _location_service.list_locations(
        db, novel_id, skip=skip, limit=limit, location_level=location_level,
    )
    return GeoLocationListResponse(items=items, total=total)


@router.get("/locations/tree")
async def get_location_tree(
    db: DbSession,
    novel_id: str = Query(..., description="小说项目 ID"),
) -> list[dict]:
    """获取地点层级树"""
    return await _query_service.get_location_tree(db, novel_id)


@router.get("/locations/{location_id}", response_model=GeoLocationResponse)
async def get_location(
    db: DbSession,
    location_id: str,
    novel_id: str = Query(..., description="小说项目 ID"),
) -> GeoLocationResponse:
    """获取地点详情"""
    return await _location_service.get_location(db, location_id, novel_id=novel_id)


@router.put("/locations/{location_id}", response_model=GeoLocationResponse)
async def update_location(
    db: DbSession,
    location_id: str,
    data: GeoLocationUpdate,
    novel_id: str = Query(..., description="小说项目 ID"),
) -> GeoLocationResponse:
    """更新地点信息"""
    return await _location_service.update_location(db, location_id, data, novel_id=novel_id)


@router.delete("/locations/{location_id}", status_code=204)
async def delete_location(
    db: DbSession,
    location_id: str,
    novel_id: str = Query(..., description="小说项目 ID"),
) -> None:
    """删除地点"""
    await _location_service.delete_location(db, location_id, novel_id=novel_id)


# ============================================================
# GeoEdge 路由
# ============================================================

@router.post("/edges", response_model=GeoEdgeResponse, status_code=201)
async def create_edge(
    db: DbSession,
    data: GeoEdgeCreate,
) -> GeoEdgeResponse:
    """创建地理关系边"""
    return await _edge_service.create_edge(db, data)


@router.get("/edges", response_model=GeoEdgeListResponse)
async def list_edges(
    db: DbSession,
    novel_id: str = Query(..., description="小说项目 ID"),
    skip: int = Query(default=0, ge=0, description="跳过的记录数"),
    limit: int = Query(
        default=DEFAULT_PAGE_SIZE,
        ge=1,
        le=MAX_PAGE_SIZE,
        description="每页条数",
    ),
) -> GeoEdgeListResponse:
    """获取关系边列表"""
    items, total = await _edge_service.list_edges(
        db, novel_id, skip=skip, limit=limit,
    )
    return GeoEdgeListResponse(items=items, total=total)


@router.get("/edges/by-location", response_model=list[GeoEdgeResponse])
async def get_edges_by_location(
    db: DbSession,
    novel_id: str = Query(..., description="小说项目 ID"),
    location_id: str = Query(..., description="地点 ID"),
) -> list[GeoEdgeResponse]:
    """获取某个地点的所有关联边"""
    return await _edge_service.get_edges_by_location(db, novel_id, location_id)


@router.get("/edges/{edge_id}", response_model=GeoEdgeResponse)
async def get_edge(
    db: DbSession,
    edge_id: str,
    novel_id: str = Query(..., description="小说项目 ID"),
) -> GeoEdgeResponse:
    """获取关系边详情"""
    return await _edge_service.get_edge(db, edge_id, novel_id=novel_id)


@router.put("/edges/{edge_id}", response_model=GeoEdgeResponse)
async def update_edge(
    db: DbSession,
    edge_id: str,
    data: GeoEdgeUpdate,
    novel_id: str = Query(..., description="小说项目 ID"),
) -> GeoEdgeResponse:
    """更新关系边"""
    return await _edge_service.update_edge(db, edge_id, data, novel_id=novel_id)


@router.delete("/edges/{edge_id}", status_code=204)
async def delete_edge(
    db: DbSession,
    edge_id: str,
    novel_id: str = Query(..., description="小说项目 ID"),
) -> None:
    """删除关系边"""
    await _edge_service.delete_edge(db, edge_id, novel_id=novel_id)


# ============================================================
# GeoEra 路由
# ============================================================

@router.post("/eras", response_model=GeoEraResponse, status_code=201)
async def create_era(
    db: DbSession,
    data: GeoEraCreate,
) -> GeoEraResponse:
    """创建历史时期"""
    return await _era_service.create_era(db, data)


@router.get("/eras", response_model=GeoEraListResponse)
async def list_eras(
    db: DbSession,
    novel_id: str = Query(..., description="小说项目 ID"),
    skip: int = Query(default=0, ge=0, description="跳过的记录数"),
    limit: int = Query(
        default=DEFAULT_PAGE_SIZE,
        ge=1,
        le=MAX_PAGE_SIZE,
        description="每页条数",
    ),
) -> GeoEraListResponse:
    """获取历史时期列表（按时间顺序排序）"""
    items, total = await _era_service.list_eras(
        db, novel_id, skip=skip, limit=limit,
    )
    return GeoEraListResponse(items=items, total=total)


@router.get("/eras/{era_id}", response_model=GeoEraResponse)
async def get_era(
    db: DbSession,
    era_id: str,
    novel_id: str = Query(..., description="小说项目 ID"),
) -> GeoEraResponse:
    """获取历史时期详情"""
    return await _era_service.get_era(db, era_id, novel_id=novel_id)


@router.put("/eras/{era_id}", response_model=GeoEraResponse)
async def update_era(
    db: DbSession,
    era_id: str,
    data: GeoEraUpdate,
    novel_id: str = Query(..., description="小说项目 ID"),
) -> GeoEraResponse:
    """更新历史时期"""
    return await _era_service.update_era(db, era_id, data, novel_id=novel_id)


@router.delete("/eras/{era_id}", status_code=204)
async def delete_era(
    db: DbSession,
    era_id: str,
    novel_id: str = Query(..., description="小说项目 ID"),
) -> None:
    """删除历史时期"""
    await _era_service.delete_era(db, era_id, novel_id=novel_id)


# ============================================================
# 业务查询路由
# ============================================================

@router.get("/travel-constraints", response_model=TravelConstraintResult)
async def get_travel_constraints(
    db: DbSession,
    novel_id: str = Query(..., description="小说项目 ID"),
    source: str = Query(..., description="起点地点 ID"),
    target: str = Query(..., description="终点地点 ID"),
) -> TravelConstraintResult:
    """查询两地之间的通行约束"""
    return await _query_service.get_travel_constraints(
        db, novel_id, source, target,
    )


@router.get("/history-context")
async def get_geo_history_context(
    db: DbSession,
    novel_id: str = Query(..., description="小说项目 ID"),
    era_id: str | None = Query(default=None, description="指定历史时期 ID"),
    location_ids: str | None = Query(
        default=None,
        description="地点 ID 列表（逗号分隔）",
    ),
) -> dict:
    """获取地理历史上下文

    返回指定/所有历史时期下，指定/所有地点的状态变化。
    location_ids 为逗号分隔的地点 ID 字符串。
    """
    loc_ids: list[str] | None = None
    if location_ids:
        loc_ids = [lid.strip() for lid in location_ids.split(",") if lid.strip()]

    return await _query_service.get_geo_history_context(
        db, novel_id, era_id=era_id, location_ids=loc_ids,
    )


@router.post("/calculate-routing", response_model=RouteQueryResponse)
async def calculate_routing(
    db: DbSession,
    data: RouteQueryRequest,
) -> RouteQueryResponse:
    """计算两地之间的最短旅行路径"""
    result = await _topology_service.calculate_route(
        db,
        data.novel_id,
        data.source_location_id,
        data.target_location_id,
        data.chapter_index,
    )
    return RouteQueryResponse(
        is_reachable=result.is_reachable,
        total_travel_hours=result.total_hours if result.is_reachable else -1.0,
        recommended_path=result.path,
        message=result.reason or "",
    )


@router.get("/location/{location_id}/factions")
async def get_location_factions(
    db: DbSession,
    location_id: str,
    novel_id: str = Query(..., description="小说项目 ID"),
) -> dict:
    factions = await _query_service.get_location_factions(db, novel_id, location_id)
    return {"factions": factions}


@router.get("/location/{location_id}/characters")
async def get_location_characters(
    db: DbSession,
    location_id: str,
    novel_id: str = Query(..., description="小说项目 ID"),
) -> dict:
    characters = await _query_service.get_location_characters(db, novel_id, location_id)
    return {"characters": characters}
