"""
Geo 对外契约

定义其他模块可以安全依赖的地理接口和数据类。
其他模块只能导入 contracts.py 和 facade.py，禁止直接导入 models/repositories/services。
"""

from __future__ import annotations

from dataclasses import dataclass, field

# facade 返回类型（Pydantic schema），供跨模块导入使用
# 注意：GeoContextBundle 与下方 dataclass 同名但不同类，
# facade.get_location_context 返回的是 schemas.GeoContextBundle（Pydantic 版本）
from modules.geo.schemas import GeoContextBundle as GeoContextResult  # noqa: F401
from modules.geo.schemas import (  # noqa: F401
    RouteQueryResponse,
    TravelConstraintResult,
)


@dataclass(frozen=True)
class GeoLocationContract:
    """地理地点契约

    供 World / Context / Outline 等模块读取地理信息。
    所有字段只读。
    """

    id: str
    """地点 ID"""
    novel_id: str
    """项目 ID"""
    world_entity_id: str
    """对应的世界对象 ID"""
    location_level: str
    """地点层级"""
    parent_location_id: str | None = None
    """父地点 ID"""
    x: float | None = None
    """相对坐标 X"""
    y: float | None = None
    """相对坐标 Y"""
    position_label: str | None = None
    """方位标签"""
    scale_label: str | None = None
    """规模标签"""
    terrain: str | None = None
    """地形"""
    climate: str | None = None
    """气候"""
    access_level: str = "normal"
    """访问级别"""
    summary: str | None = None
    """概述"""


@dataclass(frozen=True)
class GeoEdgeContract:
    """地理关系边契约"""

    id: str
    source_location_id: str
    target_location_id: str
    relation_type: str
    direction_label: str | None = None
    distance_label: str | None = None
    travel_time: str | None = None
    difficulty: str | None = None
    visibility: str = "public"
    condition_text: str | None = None


@dataclass(frozen=True)
class GeoEraContract:
    """历史时期契约"""

    id: str
    novel_id: str
    name: str
    order_index: int
    summary: str | None = None
    start_event_id: str | None = None
    end_event_id: str | None = None


@dataclass(frozen=True)
class TravelConstraintContract:
    """通行约束契约"""

    source_id: str
    target_id: str
    has_direct_route: bool = False
    route_type: str | None = None
    direction_label: str | None = None
    distance_label: str | None = None
    travel_time: str | None = None
    difficulty: str | None = None
    visibility: str | None = None
    condition_text: str | None = None
    blocked: bool = False
    blocked_reason: str | None = None


@dataclass(frozen=True)
class RouteCalculationResult:
    """路径计算结果契约"""

    is_reachable: bool
    """是否可达"""
    total_hours: float
    """总旅行耗时（小时）"""
    path: list[str]
    """途经节点 ID 列表"""
    reason: str | None = None
    """不可达原因"""


@dataclass(frozen=True)
class GeoContextBundle:
    """地理上下文组合 — 供 Context Compiler 读取

    注意：实际运行时使用 schemas.GeoContextBundle（Pydantic），
    此契约版本保留作为模块间通信的接口定义。
    """

    location: GeoLocationContract | None = None
    """当前地点"""
    parent_locations: list[GeoLocationContract] = field(default_factory=list)
    """上级地点链"""
    child_locations: list[GeoLocationContract] = field(default_factory=list)
    """子地点"""
    edges: list[GeoEdgeContract] = field(default_factory=list)
    """关联边"""
    current_era: GeoEraContract | None = None
    """当前历史时期"""
    # era_summaries 已废弃 — 由 schemas.GeoContextBundle.era_states 替代
    # 保留字段以防外部使用，后续版本将移除
    era_summaries: list[tuple[str, str]] = field(default_factory=list)
    """[已废弃] 历史时期摘要列表，使用 schemas.GeoContextBundle.era_states 替代"""
