"""
Geo 模块 — 地理关系与宏观历史

提供小说世界的地点层级、通行关系、相对方位、访问限制、
以及历史时期下的地点状态变化管理。
"""

from __future__ import annotations

from modules.geo.contracts import (
    GeoContextBundle as GeoContextBundleContract,
    GeoEdgeContract,
    GeoEraContract,
    GeoLocationContract,
    TravelConstraintContract,
)
from modules.geo.facade import (
    get_geo_history_context,
    get_location_context,
    get_location_tree,
    get_travel_constraints,
)
from modules.geo.schemas import (
    GeoContextBundle,
    TravelConstraintResult,
)

__all__ = [
    # Facade
    "get_location_context",
    "get_location_tree",
    "get_travel_constraints",
    "get_geo_history_context",
    # Contracts
    "GeoLocationContract",
    "GeoEdgeContract",
    "GeoEraContract",
    "TravelConstraintContract",
    "GeoContextBundleContract",
    # Schemas
    "GeoContextBundle",
    "TravelConstraintResult",
]
