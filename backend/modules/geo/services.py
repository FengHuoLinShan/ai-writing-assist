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
from shared.utils import parse_uuid


# ============================================================
# GeoLocation 服务
# ============================================================

class GeoLocationService:
    """地理地点业务服务"""

    def __init__(self) -> None:
        self._repo = GeoLocationRepository()
        self._edge_repo = GeoEdgeRepository()
        self._era_repo = GeoEraRepository()


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
        novel_id: str | None = None,
    ) -> GeoLocationResponse:
        """获取地点详情"""
        lid = parse_uuid(location_id)
        location = await self._repo.get(db, lid)
        if location is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"GeoLocation {location_id} not found",
            )
        if novel_id and str(location.novel_id) != novel_id:
            raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND)
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
        nid = parse_uuid(novel_id)
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
        """构建地点层级树（内存构建，避免 N+1 查询）"""
        nid = parse_uuid(novel_id)
        # 一次性加载所有地点
        all_locs, _ = await self._repo.get_multi(db, nid, skip=0, limit=10000)
        root_nodes = self._build_tree_in_memory(all_locs, max_depth=20)
        return root_nodes

    @staticmethod
    def _build_tree_in_memory(
        all_locations: list[Any],
        max_depth: int = 20,
    ) -> list[LocationNode]:
        """在内存中构建地点层级树

        Args:
            all_locations: 所有地点 ORM 对象列表
            max_depth: 最大递归深度，防止循环引用导致栈溢出

        Returns:
            根节点列表（顶层地点）
        """
        # 按 parent_id 分组：parent_id → [children]
        children_map: dict[str | None, list[Any]] = {}
        id_map: dict[str, Any] = {}
        for loc in all_locations:
            loc_id = str(loc.id)
            id_map[loc_id] = loc
            pid = str(loc.parent_location_id) if loc.parent_location_id else None
            if pid not in children_map:
                children_map[pid] = []
            children_map[pid].append(loc)

        def _build_node(
            loc: Any,
            depth: int = 0,
        ) -> LocationNode:
            """递归构建单个节点（深度受限防止栈溢出）"""
            children: list[LocationNode] = []
            if depth < max_depth:
                loc_id_str = str(loc.id)
                child_locs = children_map.get(loc_id_str, [])
                for child in child_locs:
                    children.append(_build_node(child, depth + 1))
            return LocationNode(
                id=str(loc.id),
                location_level=loc.location_level,
                position_label=loc.position_label,
                x=loc.x,
                y=loc.y,
                access_level=loc.access_level,
                summary=loc.summary,
                children=children,
            )

        # 根节点 = parent_location_id IS NULL 的地点
        roots = children_map.get(None, [])
        return [_build_node(r) for r in roots]

    async def update_location(
        self,
        db: AsyncSession,
        location_id: str,
        data: GeoLocationUpdate,
        novel_id: str | None = None,
    ) -> GeoLocationResponse:
        """更新地点"""
        lid = parse_uuid(location_id)
        if novel_id:
            existing = await self._repo.get(db, lid)
            if existing is None or str(existing.novel_id) != novel_id:
                raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND)
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
        novel_id: str | None = None,
    ) -> None:
        """删除地点"""
        lid = parse_uuid(location_id)
        if novel_id:
            existing = await self._repo.get(db, lid)
            if existing is None or str(existing.novel_id) != novel_id:
                raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND)
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
        novel_id: str | None = None,
    ) -> GeoEdgeResponse:
        """获取关系边详情"""
        eid = parse_uuid(edge_id)
        edge = await self._repo.get(db, eid)
        if edge is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"GeoEdge {edge_id} not found",
            )
        if novel_id and str(edge.novel_id) != novel_id:
            raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND)
        return GeoEdgeResponse.model_validate(edge)

    async def list_edges(
        self,
        db: AsyncSession,
        novel_id: str,
        skip: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> tuple[list[GeoEdgeResponse], int]:
        """获取关系边列表"""
        nid = parse_uuid(novel_id)
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
        nid = parse_uuid(novel_id)
        lid = parse_uuid(location_id)
        edges = await self._repo.get_by_location(db, nid, lid)
        return [GeoEdgeResponse.model_validate(e) for e in edges]

    async def update_edge(
        self,
        db: AsyncSession,
        edge_id: str,
        data: GeoEdgeUpdate,
        novel_id: str | None = None,
    ) -> GeoEdgeResponse:
        """更新关系边"""
        eid = parse_uuid(edge_id)
        if novel_id:
            existing = await self._repo.get(db, eid)
            if existing is None or str(existing.novel_id) != novel_id:
                raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND)
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
        novel_id: str | None = None,
    ) -> None:
        """删除关系边"""
        eid = parse_uuid(edge_id)
        if novel_id:
            existing = await self._repo.get(db, eid)
            if existing is None or str(existing.novel_id) != novel_id:
                raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND)
        deleted = await self._repo.delete(db, eid)
        if not deleted:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"GeoEdge {edge_id} not found",
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
        novel_id: str | None = None,
    ) -> GeoEraResponse:
        """获取历史时期详情"""
        eid = parse_uuid(era_id)
        era = await self._repo.get(db, eid)
        if era is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"GeoEra {era_id} not found",
            )
        if novel_id and str(era.novel_id) != novel_id:
            raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND)
        return GeoEraResponse.model_validate(era)

    async def list_eras(
        self,
        db: AsyncSession,
        novel_id: str,
        skip: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> tuple[list[GeoEraResponse], int]:
        """获取历史时期列表"""
        nid = parse_uuid(novel_id)
        limit = min(limit, MAX_PAGE_SIZE)
        items, total = await self._repo.get_multi(db, nid, skip=skip, limit=limit)
        return [GeoEraResponse.model_validate(e) for e in items], total

    async def update_era(
        self,
        db: AsyncSession,
        era_id: str,
        data: GeoEraUpdate,
        novel_id: str | None = None,
    ) -> GeoEraResponse:
        """更新历史时期"""
        eid = parse_uuid(era_id)
        if novel_id:
            existing = await self._repo.get(db, eid)
            if existing is None or str(existing.novel_id) != novel_id:
                raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND)
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
        novel_id: str | None = None,
    ) -> None:
        """删除历史时期"""
        eid = parse_uuid(era_id)
        if novel_id:
            existing = await self._repo.get(db, eid)
            if existing is None or str(existing.novel_id) != novel_id:
                raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND)
        deleted = await self._repo.delete(db, eid)
        if not deleted:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"GeoEra {era_id} not found",
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
        nid = parse_uuid(novel_id)
        lid = parse_uuid(location_id)

        # 批量加载所有地点（供父级链内存行走和后续使用）
        all_locs, _ = await self._loc_repo.get_multi(db, nid, skip=0, limit=10000)
        loc_map = {str(loc.id): loc for loc in all_locs}
        location = loc_map.get(str(lid))

        if location is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"GeoLocation {location_id} not found",
            )

        # 并行查询：父级链（内存）、子地点、关联边、历史时期
        import asyncio

        ancestors, children, edges, eras = await asyncio.gather(
            self._loc_repo.get_ancestors(db, lid, all_locations=all_locs),
            self._loc_repo.get_children(db, lid),
            self._edge_repo.get_by_location(db, nid, lid),
            self._era_repo.get_all_sorted(db, nid),
        )

        parent_locations: list[GeoLocationResponse] = []
        for anc in ancestors:
            if anc.id != lid:
                parent_locations.append(GeoLocationResponse.model_validate(anc))

        child_responses = [
            GeoLocationResponse.model_validate(c) for c in children
        ]
        edge_responses = [GeoEdgeResponse.model_validate(e) for e in edges]
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
        """获取地点层级树（内存构建，避免 N+1 查询）"""
        nid = parse_uuid(novel_id)
        all_locs, _ = await self._loc_repo.get_multi(db, nid, skip=0, limit=10000)
        return self._build_tree_dict_in_memory(all_locs, max_depth=20)

    @staticmethod
    def _build_tree_dict_in_memory(
        all_locations: list[Any],
        max_depth: int = 20,
    ) -> list[dict]:
        """在内存中构建地点树字典（深度限制、循环引用保护）"""
        children_map: dict[str | None, list[Any]] = {}
        id_map: dict[str, Any] = {}
        for loc in all_locations:
            loc_id = str(loc.id)
            id_map[loc_id] = loc
            pid = str(loc.parent_location_id) if loc.parent_location_id else None
            if pid not in children_map:
                children_map[pid] = []
            children_map[pid].append(loc)

        def _build(loc: Any, depth: int = 0) -> dict:
            children: list[dict] = []
            if depth < max_depth:
                for child in children_map.get(str(loc.id), []):
                    children.append(_build(child, depth + 1))
            return {
                "id": str(loc.id),
                "location_level": loc.location_level,
                "position_label": loc.position_label,
                "x": loc.x,
                "y": loc.y,
                "access_level": loc.access_level,
                "summary": loc.summary,
                "children": children,
            }

        roots = children_map.get(None, [])
        return [_build(r) for r in roots]

    async def get_travel_constraints(
        self,
        db: AsyncSession,
        novel_id: str,
        source_location_id: str,
        target_location_id: str,
    ) -> TravelConstraintResult:
        """查询两地之间的通行约束"""
        nid = parse_uuid(novel_id)
        src_id = parse_uuid(source_location_id)
        tgt_id = parse_uuid(target_location_id)

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
        nid = parse_uuid(novel_id)

        # 获取历史时期
        if era_id:
            eid = parse_uuid(era_id)
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
                lid = parse_uuid(loc_id)
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

