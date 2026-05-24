"""
Geo 业务逻辑层

调用 repository 完成 Geo 模块的业务操作。
服务层包含业务规则，但不直接操作数据库。
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException
from fastapi import status as http_status
from sqlalchemy.ext.asyncio import AsyncSession

from modules.geo.contracts import (
    GeoContextBundle as GeoContextContract,
    GeoEdgeContract,
    GeoEraContract,
    GeoLocationContract,
    TravelConstraintContract,
)
from modules.geo.repositories import (
    GeoEdgeRepository,
    GeoEraRepository,
    GeoLocationRepository,
)
from modules.geo.schemas import (
    GeoContextBundle,
    GeoEdgeCreate,
    GeoEdgeResponse,
    GeoEdgeUpdate,
    GeoEraCreate,
    GeoEraResponse,
    GeoEraUpdate,
    GeoLocationCreate,
    GeoLocationResponse,
    GeoLocationUpdate,
    LocationNode,
    TravelConstraintResult,
)
from shared.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE


# ============================================================
# GeoLocation 服务
# ============================================================

class GeoLocationService:
    """地理地点业务服务"""

    def __init__(self) -> None:
        self._repo = GeoLocationRepository()
        self._edge_repo = GeoEdgeRepository()
        self._era_repo = GeoEraRepository()

    @staticmethod
    def _parse_uuid(value: str) -> uuid.UUID:
        """将字符串 ID 解析为 UUID，格式错误时抛出 422"""
        try:
            return uuid.UUID(hex=value)
        except ValueError:
            raise HTTPException(
                status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Invalid ID: {value}",
            )

    async def create_location(
        self,
        db: AsyncSession,
        data: GeoLocationCreate,
    ) -> GeoLocationResponse:
        """创建地理地点"""
        location = await self._repo.create(db, data)
        return GeoLocationResponse.model_validate(location)

    async def get_location(
        self,
        db: AsyncSession,
        location_id: str,
    ) -> GeoLocationResponse:
        """获取地点详情"""
        lid = self._parse_uuid(location_id)
        location = await self._repo.get(db, lid)
        if location is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"GeoLocation {location_id} not found",
            )
        return GeoLocationResponse.model_validate(location)

    async def list_locations(
        self,
        db: AsyncSession,
        novel_id: str,
        skip: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
        location_level: str | None = None,
    ) -> tuple[list[GeoLocationResponse], int]:
        """获取地点列表"""
        nid = self._parse_uuid(novel_id)
        limit = min(limit, MAX_PAGE_SIZE)
        items, total = await self._repo.get_multi(
            db, nid, skip=skip, limit=limit, location_level=location_level,
        )
        return [GeoLocationResponse.model_validate(loc) for loc in items], total

    async def get_location_tree(
        self,
        db: AsyncSession,
        novel_id: str,
    ) -> list[LocationNode]:
        """递归构建地点层级树"""
        nid = self._parse_uuid(novel_id)
        roots = await self._repo.get_tree(db, nid, parent_id=None)
        return [await self._build_tree_node(db, loc) for loc in roots]

    async def _build_tree_node(
        self,
        db: AsyncSession,
        location: Any,
    ) -> LocationNode:
        """递归构建地点树节点"""
        children_models = await self._repo.get_children(db, location.id)
        children = [
            await self._build_tree_node(db, child) for child in children_models
        ]
        return LocationNode(
            id=str(location.id),
            location_level=location.location_level,
            position_label=location.position_label,
            x=location.x,
            y=location.y,
            access_level=location.access_level,
            summary=location.summary,
            children=children,
        )

    async def update_location(
        self,
        db: AsyncSession,
        location_id: str,
        data: GeoLocationUpdate,
    ) -> GeoLocationResponse:
        """更新地点"""
        lid = self._parse_uuid(location_id)
        location = await self._repo.update(db, lid, data)
        if location is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"GeoLocation {location_id} not found",
            )
        return GeoLocationResponse.model_validate(location)

    async def delete_location(
        self,
        db: AsyncSession,
        location_id: str,
    ) -> None:
        """删除地点"""
        lid = self._parse_uuid(location_id)
        deleted = await self._repo.delete(db, lid)
        if not deleted:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"GeoLocation {location_id} not found",
            )


# ============================================================
# GeoEdge 服务
# ============================================================

class GeoEdgeService:
    """地理关系边业务服务"""

    def __init__(self) -> None:
        self._repo = GeoEdgeRepository()

    async def create_edge(
        self,
        db: AsyncSession,
        data: GeoEdgeCreate,
    ) -> GeoEdgeResponse:
        """创建关系边"""
        edge = await self._repo.create(db, data)
        return GeoEdgeResponse.model_validate(edge)

    async def get_edge(
        self,
        db: AsyncSession,
        edge_id: str,
    ) -> GeoEdgeResponse:
        """获取关系边详情"""
        eid = self._parse_uuid(edge_id)
        edge = await self._repo.get(db, eid)
        if edge is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"GeoEdge {edge_id} not found",
            )
        return GeoEdgeResponse.model_validate(edge)

    async def list_edges(
        self,
        db: AsyncSession,
        novel_id: str,
        skip: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> tuple[list[GeoEdgeResponse], int]:
        """获取关系边列表"""
        nid = self._parse_uuid(novel_id)
        limit = min(limit, MAX_PAGE_SIZE)
        items, total = await self._repo.get_multi(db, nid, skip=skip, limit=limit)
        return [GeoEdgeResponse.model_validate(e) for e in items], total

    async def get_edges_by_location(
        self,
        db: AsyncSession,
        novel_id: str,
        location_id: str,
    ) -> list[GeoEdgeResponse]:
        """获取某个地点的所有关联边"""
        nid = self._parse_uuid(novel_id)
        lid = self._parse_uuid(location_id)
        edges = await self._repo.get_by_location(db, nid, lid)
        return [GeoEdgeResponse.model_validate(e) for e in edges]

    async def update_edge(
        self,
        db: AsyncSession,
        edge_id: str,
        data: GeoEdgeUpdate,
    ) -> GeoEdgeResponse:
        """更新关系边"""
        eid = self._parse_uuid(edge_id)
        edge = await self._repo.update(db, eid, data)
        if edge is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"GeoEdge {edge_id} not found",
            )
        return GeoEdgeResponse.model_validate(edge)

    async def delete_edge(
        self,
        db: AsyncSession,
        edge_id: str,
    ) -> None:
        """删除关系边"""
        eid = self._parse_uuid(edge_id)
        deleted = await self._repo.delete(db, eid)
        if not deleted:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"GeoEdge {edge_id} not found",
            )

    @staticmethod
    def _parse_uuid(value: str) -> uuid.UUID:
        """将字符串 ID 解析为 UUID，格式错误时抛出 422"""
        try:
            return uuid.UUID(hex=value)
        except ValueError:
            raise HTTPException(
                status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Invalid ID: {value}",
            )


# ============================================================
# GeoEra 服务
# ============================================================

class GeoEraService:
    """历史时期业务服务"""

    def __init__(self) -> None:
        self._repo = GeoEraRepository()

    async def create_era(
        self,
        db: AsyncSession,
        data: GeoEraCreate,
    ) -> GeoEraResponse:
        """创建历史时期"""
        era = await self._repo.create(db, data)
        return GeoEraResponse.model_validate(era)

    async def get_era(
        self,
        db: AsyncSession,
        era_id: str,
    ) -> GeoEraResponse:
        """获取历史时期详情"""
        eid = self._parse_uuid(era_id)
        era = await self._repo.get(db, eid)
        if era is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"GeoEra {era_id} not found",
            )
        return GeoEraResponse.model_validate(era)

    async def list_eras(
        self,
        db: AsyncSession,
        novel_id: str,
        skip: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> tuple[list[GeoEraResponse], int]:
        """获取历史时期列表"""
        nid = self._parse_uuid(novel_id)
        limit = min(limit, MAX_PAGE_SIZE)
        items, total = await self._repo.get_multi(db, nid, skip=skip, limit=limit)
        return [GeoEraResponse.model_validate(e) for e in items], total

    async def update_era(
        self,
        db: AsyncSession,
        era_id: str,
        data: GeoEraUpdate,
    ) -> GeoEraResponse:
        """更新历史时期"""
        eid = self._parse_uuid(era_id)
        era = await self._repo.update(db, eid, data)
        if era is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"GeoEra {era_id} not found",
            )
        return GeoEraResponse.model_validate(era)

    async def delete_era(
        self,
        db: AsyncSession,
        era_id: str,
    ) -> None:
        """删除历史时期"""
        eid = self._parse_uuid(era_id)
        deleted = await self._repo.delete(db, eid)
        if not deleted:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"GeoEra {era_id} not found",
            )

    @staticmethod
    def _parse_uuid(value: str) -> uuid.UUID:
        """将字符串 ID 解析为 UUID，格式错误时抛出 422"""
        try:
            return uuid.UUID(hex=value)
        except ValueError:
            raise HTTPException(
                status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Invalid ID: {value}",
            )


# ============================================================
# 复合查询服务
# ============================================================

class GeoQueryService:
    """地理复合查询服务 — 处理跨表查询和上下文构建"""

    def __init__(self) -> None:
        self._loc_repo = GeoLocationRepository()
        self._edge_repo = GeoEdgeRepository()
        self._era_repo = GeoEraRepository()

    async def get_location_context(
        self,
        db: AsyncSession,
        novel_id: str,
        location_id: str,
        depth: int = 1,
    ) -> GeoContextBundle:
        """获取地点上下文（含父级、子级、边、历史时期）"""
        nid = self._parse_uuid(novel_id)
        lid = self._parse_uuid(location_id)

        location = await self._loc_repo.get(db, lid)
        if location is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"GeoLocation {location_id} not found",
            )

        # 父级地点链
        ancestors = await self._loc_repo.get_ancestors(db, lid)
        # ancestors 包含 location 自身 + 父级链
        parent_locations: list[GeoLocationResponse] = []
        for anc in ancestors:
            if anc.id != lid:  # 排除自身
                parent_locations.append(GeoLocationResponse.model_validate(anc))

        # 子地点
        children = await self._loc_repo.get_children(db, lid)
        child_responses = [
            GeoLocationResponse.model_validate(c) for c in children
        ]

        # 关联边
        edges = await self._edge_repo.get_by_location(db, nid, lid)
        edge_responses = [GeoEdgeResponse.model_validate(e) for e in edges]

        # 历史时期
        eras = await self._era_repo.get_all_sorted(db, nid)
        era_states: list[dict] = []
        current_era_response = None
        content_json = location.content_json or {}
        era_states_data = content_json.get("era_states", [])

        for era in eras:
            era_state = None
            if isinstance(era_states_data, list):
                for es in era_states_data:
                    if isinstance(es, dict) and str(era.id) in (
                        es.get("era_id"),
                        str(era.id),
                    ):
                        era_state = es
                        break

            state_entry = {
                "era_id": str(era.id),
                "era_name": era.name,
                "era_order_index": era.order_index,
                "summary": era.summary,
                "location_state": era_state or {},
            }
            era_states.append(state_entry)

            # 取最后一个 era 作为当前时期
            current_era_response = GeoEraResponse.model_validate(era)

        return GeoContextBundle(
            location=GeoLocationResponse.model_validate(location)
            if location
            else None,
            parent_locations=parent_locations,
            child_locations=child_responses,
            edges=edge_responses,
            current_era=current_era_response,
            era_states=era_states,  # type: ignore[arg-type]
        )

    async def get_location_tree(
        self,
        db: AsyncSession,
        novel_id: str,
    ) -> list[dict]:
        """获取地点层级树（递归构建）"""
        nid = self._parse_uuid(novel_id)
        roots = await self._loc_repo.get_tree(db, nid, parent_id=None)
        tree = []
        for root in roots:
            node = await self._build_tree_dict(db, root)
            tree.append(node)
        return tree

    async def _build_tree_dict(
        self,
        db: AsyncSession,
        location: Any,
    ) -> dict:
        """递归构建地点树字典"""
        children_models = await self._loc_repo.get_children(db, location.id)
        children = [
            await self._build_tree_dict(db, child) for child in children_models
        ]
        return {
            "id": str(location.id),
            "location_level": location.location_level,
            "position_label": location.position_label,
            "x": location.x,
            "y": location.y,
            "access_level": location.access_level,
            "summary": location.summary,
            "children": children,
        }

    async def get_travel_constraints(
        self,
        db: AsyncSession,
        novel_id: str,
        source_location_id: str,
        target_location_id: str,
    ) -> TravelConstraintResult:
        """查询两地之间的通行约束"""
        nid = self._parse_uuid(novel_id)
        src_id = self._parse_uuid(source_location_id)
        tgt_id = self._parse_uuid(target_location_id)

        edges = await self._edge_repo.get_by_locations(db, nid, src_id, tgt_id)

        if not edges:
            return TravelConstraintResult(
                source_id=source_location_id,
                target_id=target_location_id,
                has_direct_route=False,
                blocked=True,
                blocked_reason="两地之间没有直接通行关系",
            )

        # 优先取 blocked_path
        blocked_edges = [e for e in edges if e.relation_type == "blocked_path"]
        if blocked_edges:
            first = blocked_edges[0]
            return TravelConstraintResult(
                source_id=source_location_id,
                target_id=target_location_id,
                has_direct_route=True,
                route_type=first.relation_type,
                direction_label=first.direction_label,
                distance_label=first.distance_label,
                travel_time=first.travel_time,
                difficulty=first.difficulty,
                visibility=first.visibility,
                condition_text=first.condition_text,
                blocked=True,
                blocked_reason=first.condition_text or "路径已被阻断",
            )

        # 取第一条可通行关系
        first = edges[0]
        return TravelConstraintResult(
            source_id=source_location_id,
            target_id=target_location_id,
            has_direct_route=True,
            route_type=first.relation_type,
            direction_label=first.direction_label,
            distance_label=first.distance_label,
            travel_time=first.travel_time,
            difficulty=first.difficulty,
            visibility=first.visibility,
            condition_text=first.condition_text,
            blocked=False,
        )

    async def get_geo_history_context(
        self,
        db: AsyncSession,
        novel_id: str,
        era_id: str | None = None,
        location_ids: list[str] | None = None,
    ) -> dict:
        """获取地理历史上下文

        Args:
            db: 数据库 session
            novel_id: 项目 ID
            era_id: 指定历史时期 ID（可选，不指定则返回所有时期）
            location_ids: 指定地点 ID 列表（可选，不指定则返回所有地点）

        Returns:
            dict: 包含历史时期摘要和各地在各时期的状态变化
        """
        nid = self._parse_uuid(novel_id)

        # 获取历史时期
        if era_id:
            eid = self._parse_uuid(era_id)
            era = await self._era_repo.get(db, eid)
            if era is None:
                raise HTTPException(
                    status_code=http_status.HTTP_404_NOT_FOUND,
                    detail=f"GeoEra {era_id} not found",
                )
            eras = [era]
        else:
            eras = await self._era_repo.get_all_sorted(db, nid)

        # 获取地点
        if location_ids:
            locations = []
            for loc_id in location_ids:
                lid = self._parse_uuid(loc_id)
                loc = await self._loc_repo.get(db, lid)
                if loc:
                    locations.append(loc)
        else:
            # 获取该项目的所有地点（无分页）
            loc_items, _ = await self._loc_repo.get_multi(db, nid, skip=0, limit=1000)
            locations = loc_items

        # 构建历史上下文
        era_summaries = []
        for era in eras:
            entry = {
                "era_id": str(era.id),
                "era_name": era.name,
                "order_index": era.order_index,
                "summary": era.summary,
                "locations": [],
            }

            for loc in locations:
                content_json = loc.content_json or {}
                era_states = content_json.get("era_states", [])
                loc_era_state = None
                if isinstance(era_states, list):
                    for es in era_states:
                        if isinstance(es, dict) and str(era.id) in (
                            es.get("era_id"),
                            str(era.id),
                        ):
                            loc_era_state = es
                            break

                entry["locations"].append({
                    "location_id": str(loc.id),
                    "location_name": loc.summary or str(loc.id),
                    "location_level": loc.location_level,
                    "era_state": loc_era_state or {},
                })

            era_summaries.append(entry)

        return {
            "novel_id": novel_id,
            "era_count": len(eras),
            "location_count": len(locations),
            "eras": era_summaries,
        }

    # ============================================================
    # 内部工具
    # ============================================================

    @staticmethod
    def _parse_uuid(value: str) -> uuid.UUID:
        """将字符串 ID 解析为 UUID，格式错误时抛出 422"""
        try:
            return uuid.UUID(hex=value)
        except ValueError:
            raise HTTPException(
                status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Invalid ID: {value}",
            )
