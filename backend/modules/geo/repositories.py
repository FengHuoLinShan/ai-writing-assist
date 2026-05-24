"""
Geo 数据访问层

封装 geo_locations、geo_edges、geo_eras 三张表的所有数据库操作。
只处理 ORM ↔ DB 的基本 CRUD，不含业务逻辑。
"""

from __future__ import annotations

import uuid
from typing import Any, Sequence

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

# 用于区分「未传」和「显式设为 None」的哨兵对象
_UNSET = object()

from modules.geo.models import GeoEdge, GeoEra, GeoLocation
from modules.geo.schemas import (
    GeoEdgeCreate,
    GeoEdgeUpdate,
    GeoEraCreate,
    GeoEraUpdate,
    GeoLocationCreate,
    GeoLocationUpdate,
)
from shared.constants import DEFAULT_PAGE_SIZE


# ============================================================
# GeoLocation 数据访问
# ============================================================

class GeoLocationRepository:
    """地理地点数据访问"""

    async def create(
        self,
        db: AsyncSession,
        data: GeoLocationCreate,
    ) -> GeoLocation:
        """创建地理地点"""
        location = GeoLocation(
            novel_id=uuid.UUID(hex=data.novel_id),
            world_entity_id=uuid.UUID(hex=data.world_entity_id),
            location_level=data.location_level,
            parent_location_id=(
                uuid.UUID(hex=data.parent_location_id)
                if data.parent_location_id
                else None
            ),
            x=data.x,
            y=data.y,
            position_label=data.position_label,
            scale_label=data.scale_label,
            terrain=data.terrain,
            climate=data.climate,
            access_level=data.access_level or "normal",
            summary=data.summary,
            content_json=data.content_json or {},
            status=data.status or "canonical",
        )
        db.add(location)
        await db.flush()
        return location

    async def get(
        self,
        db: AsyncSession,
        location_id: uuid.UUID,
    ) -> GeoLocation | None:
        """根据 ID 获取地点"""
        stmt = (
            select(GeoLocation)
            .where(GeoLocation.id == location_id)
            .options(selectinload(GeoLocation.parent_location))
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_world_entity_id(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        world_entity_id: uuid.UUID,
    ) -> GeoLocation | None:
        """根据世界对象 ID 获取地点"""
        stmt = select(GeoLocation).where(
            GeoLocation.novel_id == novel_id,
            GeoLocation.world_entity_id == world_entity_id,
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_multi(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        skip: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
        location_level: str | None = None,
    ) -> tuple[list[GeoLocation], int]:
        """获取地点列表（分页、可选按层级筛选），返回 (items, total)"""
        conditions = [GeoLocation.novel_id == novel_id]
        if location_level:
            conditions.append(GeoLocation.location_level == location_level)

        # 总数
        count_stmt = select(func.count(GeoLocation.id)).where(*conditions)
        count_result = await db.execute(count_stmt)
        total = count_result.scalar() or 0

        # 分页
        stmt = (
            select(GeoLocation)
            .where(*conditions)
            .offset(skip)
            .limit(limit)
            .order_by(GeoLocation.location_level, GeoLocation.created_at.desc())
        )
        result = await db.execute(stmt)
        items: Sequence[GeoLocation] = result.scalars().all()
        return list(items), total

    async def get_children(
        self,
        db: AsyncSession,
        location_id: uuid.UUID,
    ) -> list[GeoLocation]:
        """获取直接子地点"""
        stmt = (
            select(GeoLocation)
            .where(GeoLocation.parent_location_id == location_id)
            .order_by(GeoLocation.location_level)
        )
        result = await db.execute(stmt)
        items: Sequence[GeoLocation] = result.scalars().all()
        return list(items)

    async def get_ancestors(
        self,
        db: AsyncSession,
        location_id: uuid.UUID,
    ) -> list[GeoLocation]:
        """获取上级地点链（从父级到根）

        由于 SQLite 不支持递归 CTE，此方法通过逐级查询实现，
        层级深度一般不会超过 8 层。
        """
        ancestors: list[GeoLocation] = []
        current_id = location_id

        for _ in range(16):  # 安全上限
            stmt = select(GeoLocation).where(GeoLocation.id == current_id)
            result = await db.execute(stmt)
            location = result.scalar_one_or_none()
            if location is None:
                break
            if location.parent_location_id:
                ancestors.append(location)
                current_id = location.parent_location_id
            else:
                ancestors.append(location)
                break

        return ancestors  # 从最近父级到最远根

    async def get_tree(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        parent_id: uuid.UUID | None = None,
    ) -> list[GeoLocation]:
        """获取指定父节点下的子地点列表（用于构建地点树）"""
        if parent_id is None:
            # 根节点：parent_location_id IS NULL
            stmt = (
                select(GeoLocation)
                .where(
                    GeoLocation.novel_id == novel_id,
                    GeoLocation.parent_location_id.is_(None),
                )
                .order_by(GeoLocation.location_level)
            )
        else:
            stmt = (
                select(GeoLocation)
                .where(
                    GeoLocation.novel_id == novel_id,
                    GeoLocation.parent_location_id == parent_id,
                )
                .order_by(GeoLocation.location_level)
            )
        result = await db.execute(stmt)
        items: Sequence[GeoLocation] = result.scalars().all()
        return list(items)

    async def update(
        self,
        db: AsyncSession,
        location_id: uuid.UUID,
        data: GeoLocationUpdate,
    ) -> GeoLocation | None:
        """更新地点，返回更新后的对象"""
        location = await self.get(db, location_id)
        if location is None:
            return None

        update_values: dict[str, object] = {}
        for field in (
            "location_level",
            "x",
            "y",
            "position_label",
            "scale_label",
            "terrain",
            "climate",
            "access_level",
            "summary",
            "status",
        ):
            value = getattr(data, field, None)
            if value is not None:
                update_values[field] = value

        # 使用哨兵对象区分「未传」和「显式设为 None」（清空父地点）
        parent_id_sentinel = getattr(data, "parent_location_id", _UNSET)
        if parent_id_sentinel is not _UNSET:
            if parent_id_sentinel is None:
                update_values["parent_location_id"] = None
            else:
                update_values["parent_location_id"] = uuid.UUID(hex=parent_id_sentinel)
        if data.content_json is not None:
            update_values["content_json"] = data.content_json

        if update_values:
            stmt = (
                update(GeoLocation)
                .where(GeoLocation.id == location_id)
                .values(**update_values)
            )
            await db.execute(stmt)
            await db.flush()
            location = await self.get(db, location_id)

        return location

    async def delete(
        self,
        db: AsyncSession,
        location_id: uuid.UUID,
    ) -> bool:
        """删除地点"""
        stmt = delete(GeoLocation).where(GeoLocation.id == location_id)
        result = await db.execute(stmt)
        await db.flush()
        return result.rowcount > 0


# ============================================================
# GeoEdge 数据访问
# ============================================================

class GeoEdgeRepository:
    """地理关系边数据访问"""

    async def create(
        self,
        db: AsyncSession,
        data: GeoEdgeCreate,
    ) -> GeoEdge:
        """创建关系边"""
        edge = GeoEdge(
            novel_id=uuid.UUID(hex=data.novel_id),
            source_location_id=uuid.UUID(hex=data.source_location_id),
            target_location_id=uuid.UUID(hex=data.target_location_id),
            relation_type=data.relation_type,
            direction_label=data.direction_label,
            distance_label=data.distance_label,
            travel_time=data.travel_time,
            difficulty=data.difficulty,
            visibility=data.visibility or "public",
            condition_text=data.condition_text,
            status=data.status or "canonical",
        )
        db.add(edge)
        await db.flush()
        return edge

    async def get(
        self,
        db: AsyncSession,
        edge_id: uuid.UUID,
    ) -> GeoEdge | None:
        """根据 ID 获取关系边"""
        stmt = select(GeoEdge).where(GeoEdge.id == edge_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_locations(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        source_location_id: uuid.UUID,
        target_location_id: uuid.UUID,
    ) -> list[GeoEdge]:
        """获取两个地点之间的所有关系边"""
        stmt = (
            select(GeoEdge)
            .where(
                GeoEdge.novel_id == novel_id,
                or_(
                    and_(
                        GeoEdge.source_location_id == source_location_id,
                        GeoEdge.target_location_id == target_location_id,
                    ),
                    and_(
                        GeoEdge.source_location_id == target_location_id,
                        GeoEdge.target_location_id == source_location_id,
                    ),
                ),
            )
            .order_by(GeoEdge.relation_type)
        )
        result = await db.execute(stmt)
        items: Sequence[GeoEdge] = result.scalars().all()
        return list(items)

    async def get_by_location(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        location_id: uuid.UUID,
    ) -> list[GeoEdge]:
        """获取某个地点的所有关联边"""
        stmt = (
            select(GeoEdge)
            .where(
                GeoEdge.novel_id == novel_id,
                or_(
                    GeoEdge.source_location_id == location_id,
                    GeoEdge.target_location_id == location_id,
                ),
            )
            .order_by(GeoEdge.relation_type)
        )
        result = await db.execute(stmt)
        items: Sequence[GeoEdge] = result.scalars().all()
        return list(items)

    async def get_multi(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        skip: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> tuple[list[GeoEdge], int]:
        """获取关系边列表（分页）"""
        count_stmt = select(func.count(GeoEdge.id)).where(GeoEdge.novel_id == novel_id)
        count_result = await db.execute(count_stmt)
        total = count_result.scalar() or 0

        stmt = (
            select(GeoEdge)
            .where(GeoEdge.novel_id == novel_id)
            .offset(skip)
            .limit(limit)
            .order_by(GeoEdge.relation_type)
        )
        result = await db.execute(stmt)
        items: Sequence[GeoEdge] = result.scalars().all()
        return list(items), total

    async def update(
        self,
        db: AsyncSession,
        edge_id: uuid.UUID,
        data: GeoEdgeUpdate,
    ) -> GeoEdge | None:
        """更新关系边"""
        edge = await self.get(db, edge_id)
        if edge is None:
            return None

        update_values: dict[str, object] = {}
        for field in (
            "relation_type",
            "direction_label",
            "distance_label",
            "travel_time",
            "difficulty",
            "visibility",
            "condition_text",
            "status",
        ):
            value = getattr(data, field, None)
            if value is not None:
                update_values[field] = value

        if update_values:
            stmt = (
                update(GeoEdge)
                .where(GeoEdge.id == edge_id)
                .values(**update_values)
            )
            await db.execute(stmt)
            await db.flush()
            edge = await self.get(db, edge_id)

        return edge

    async def delete(
        self,
        db: AsyncSession,
        edge_id: uuid.UUID,
    ) -> bool:
        """删除关系边"""
        stmt = delete(GeoEdge).where(GeoEdge.id == edge_id)
        result = await db.execute(stmt)
        await db.flush()
        return result.rowcount > 0


# ============================================================
# GeoEra 数据访问
# ============================================================

class GeoEraRepository:
    """历史时期数据访问"""

    async def create(
        self,
        db: AsyncSession,
        data: GeoEraCreate,
    ) -> GeoEra:
        """创建历史时期"""
        era = GeoEra(
            novel_id=uuid.UUID(hex=data.novel_id),
            name=data.name,
            order_index=data.order_index,
            summary=data.summary,
            start_event_id=(
                uuid.UUID(hex=data.start_event_id)
                if data.start_event_id
                else None
            ),
            end_event_id=(
                uuid.UUID(hex=data.end_event_id)
                if data.end_event_id
                else None
            ),
            status=data.status or "canonical",
        )
        db.add(era)
        await db.flush()
        return era

    async def get(
        self,
        db: AsyncSession,
        era_id: uuid.UUID,
    ) -> GeoEra | None:
        """根据 ID 获取历史时期"""
        stmt = select(GeoEra).where(GeoEra.id == era_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_multi(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        skip: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> tuple[list[GeoEra], int]:
        """获取历史时期列表（按 order_index 排序）"""
        count_stmt = select(func.count(GeoEra.id)).where(GeoEra.novel_id == novel_id)
        count_result = await db.execute(count_stmt)
        total = count_result.scalar() or 0

        stmt = (
            select(GeoEra)
            .where(GeoEra.novel_id == novel_id)
            .offset(skip)
            .limit(limit)
            .order_by(GeoEra.order_index)
        )
        result = await db.execute(stmt)
        items: Sequence[GeoEra] = result.scalars().all()
        return list(items), total

    async def get_all_sorted(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
    ) -> list[GeoEra]:
        """获取所有历史时期（按 order_index 排序，无分页）"""
        stmt = (
            select(GeoEra)
            .where(GeoEra.novel_id == novel_id)
            .order_by(GeoEra.order_index)
        )
        result = await db.execute(stmt)
        items: Sequence[GeoEra] = result.scalars().all()
        return list(items)

    async def update(
        self,
        db: AsyncSession,
        era_id: uuid.UUID,
        data: GeoEraUpdate,
    ) -> GeoEra | None:
        """更新历史时期"""
        era = await self.get(db, era_id)
        if era is None:
            return None

        update_values: dict[str, object] = {}
        for field in (
            "name",
            "order_index",
            "summary",
            "status",
        ):
            value = getattr(data, field, None)
            if value is not None:
                update_values[field] = value

        if data.start_event_id is not None:
            update_values["start_event_id"] = uuid.UUID(hex=data.start_event_id)
        if data.end_event_id is not None:
            update_values["end_event_id"] = uuid.UUID(hex=data.end_event_id)

        if update_values:
            stmt = (
                update(GeoEra)
                .where(GeoEra.id == era_id)
                .values(**update_values)
            )
            await db.execute(stmt)
            await db.flush()
            era = await self.get(db, era_id)

        return era

    async def delete(
        self,
        db: AsyncSession,
        era_id: uuid.UUID,
    ) -> bool:
        """删除历史时期"""
        stmt = delete(GeoEra).where(GeoEra.id == era_id)
        result = await db.execute(stmt)
        await db.flush()
        return result.rowcount > 0
