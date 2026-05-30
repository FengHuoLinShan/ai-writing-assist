"""
Geo 数据访问层

GeoLocation 以 entity_id 为 PK+FK（→ core_entities.id），仅存储地理扩展字段。
公共字段（name, summary, status）在 core_entities 中。
"""

from __future__ import annotations

import uuid
from typing import Any, Sequence

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

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
# GeoLocation Repository
# ============================================================

class GeoLocationRepository:
    """地理地点扩展表数据访问 — PK 为 entity_id"""

    async def create(
        self,
        db: AsyncSession,
        data: GeoLocationCreate,
    ) -> GeoLocation:
        """创建地理地点扩展记录"""
        location = GeoLocation(
            entity_id=uuid.UUID(hex=data.entity_id),
            novel_id=uuid.UUID(hex=data.novel_id),
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
            content_json=data.content_json or {},
        )
        db.add(location)
        await db.flush()
        return location

    async def get(
        self,
        db: AsyncSession,
        entity_id: uuid.UUID,
    ) -> GeoLocation | None:
        """根据 entity_id 获取地点扩展"""
        stmt = (
            select(GeoLocation)
            .where(GeoLocation.entity_id == entity_id)
            .options(selectinload(GeoLocation.parent_location))
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
        """获取地点扩展列表（分页、可选按层级筛选）"""
        conditions = [GeoLocation.novel_id == novel_id]
        if location_level:
            conditions.append(GeoLocation.location_level == location_level)

        count_stmt = select(func.count(GeoLocation.entity_id)).where(*conditions)
        count_result = await db.execute(count_stmt)
        total = count_result.scalar() or 0

        stmt = (
            select(GeoLocation)
            .where(*conditions)
            .offset(skip)
            .limit(limit)
            .order_by(GeoLocation.location_level, GeoLocation.entity_id)
        )
        result = await db.execute(stmt)
        items: Sequence[GeoLocation] = result.scalars().all()
        return list(items), total

    async def get_children(
        self,
        db: AsyncSession,
        entity_id: uuid.UUID,
    ) -> list[GeoLocation]:
        """获取直接子地点"""
        stmt = (
            select(GeoLocation)
            .where(GeoLocation.parent_location_id == entity_id)
            .order_by(GeoLocation.location_level)
        )
        result = await db.execute(stmt)
        items: Sequence[GeoLocation] = result.scalars().all()
        return list(items)

    async def get_ancestors(
        self,
        db: AsyncSession,
        entity_id: uuid.UUID,
        all_locations: list[GeoLocation] | None = None,
    ) -> list[GeoLocation]:
        """获取上级地点链（从父级到根）"""
        if all_locations is None:
            all_locations = await self._load_novel_locations_for_ancestors(db, entity_id)

        loc_map = {str(loc.entity_id): loc for loc in all_locations}
        ancestors: list[GeoLocation] = []
        current = loc_map.get(str(entity_id))
        while current is not None:
            if current.parent_location_id:
                ancestors.append(current)
                current = loc_map.get(str(current.parent_location_id))
            else:
                ancestors.append(current)
                break
        return ancestors

    async def _load_novel_locations_for_ancestors(
        self,
        db: AsyncSession,
        entity_id: uuid.UUID,
    ) -> list[GeoLocation]:
        """一次性加载祖先链所需的所有地点"""
        anchor_stmt = select(GeoLocation.novel_id).where(
            GeoLocation.entity_id == entity_id,
        )
        anchor_result = await db.execute(anchor_stmt)
        novel_id = anchor_result.scalar_one_or_none()
        if novel_id is None:
            return []

        stmt = select(GeoLocation).where(GeoLocation.novel_id == novel_id)
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def get_tree(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        parent_id: uuid.UUID | None = None,
    ) -> list[GeoLocation]:
        """获取指定父节点下的子地点列表"""
        if parent_id is None:
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
        entity_id: uuid.UUID,
        data: GeoLocationUpdate,
    ) -> GeoLocation | None:
        """更新地点扩展字段"""
        location = await self.get(db, entity_id)
        if location is None:
            return None

        update_values: dict[str, object] = {}
        for field in (
            "location_level", "x", "y", "position_label", "scale_label",
            "terrain", "climate", "access_level",
        ):
            value = getattr(data, field, None)
            if value is not None:
                update_values[field] = value

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
                .where(GeoLocation.entity_id == entity_id)
                .values(**update_values)
            )
            await db.execute(stmt)
            await db.flush()
            location = await self.get(db, entity_id)

        return location

    async def delete(
        self,
        db: AsyncSession,
        entity_id: uuid.UUID,
    ) -> bool:
        """删除地点扩展记录"""
        stmt = delete(GeoLocation).where(GeoLocation.entity_id == entity_id)
        result = await db.execute(stmt)
        await db.flush()
        return result.rowcount > 0


# ============================================================
# GeoEdge Repository (unchanged — references core_entities.id)
# ============================================================

class GeoEdgeRepository:
    """地理关系边数据访问"""

    async def create(self, db: AsyncSession, data: GeoEdgeCreate) -> GeoEdge:
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

    async def get(self, db: AsyncSession, edge_id: uuid.UUID) -> GeoEdge | None:
        stmt = select(GeoEdge).where(GeoEdge.id == edge_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_locations(
        self, db: AsyncSession, novel_id: uuid.UUID,
        source_location_id: uuid.UUID, target_location_id: uuid.UUID,
    ) -> list[GeoEdge]:
        stmt = (
            select(GeoEdge).where(
                GeoEdge.novel_id == novel_id,
                or_(
                    and_(GeoEdge.source_location_id == source_location_id,
                         GeoEdge.target_location_id == target_location_id),
                    and_(GeoEdge.source_location_id == target_location_id,
                         GeoEdge.target_location_id == source_location_id),
                ),
            ).order_by(GeoEdge.relation_type)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def get_by_location(
        self, db: AsyncSession, novel_id: uuid.UUID, location_id: uuid.UUID,
    ) -> list[GeoEdge]:
        stmt = (
            select(GeoEdge).where(
                GeoEdge.novel_id == novel_id,
                or_(GeoEdge.source_location_id == location_id,
                    GeoEdge.target_location_id == location_id),
            ).order_by(GeoEdge.relation_type)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def get_multi(
        self, db: AsyncSession, novel_id: uuid.UUID,
        skip: int = 0, limit: int = DEFAULT_PAGE_SIZE,
    ) -> tuple[list[GeoEdge], int]:
        count_stmt = select(func.count(GeoEdge.id)).where(GeoEdge.novel_id == novel_id)
        count_result = await db.execute(count_stmt)
        total = count_result.scalar() or 0
        stmt = (
            select(GeoEdge).where(GeoEdge.novel_id == novel_id)
            .offset(skip).limit(limit).order_by(GeoEdge.relation_type)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all()), total

    async def update(
        self, db: AsyncSession, edge_id: uuid.UUID, data: GeoEdgeUpdate,
    ) -> GeoEdge | None:
        edge = await self.get(db, edge_id)
        if edge is None:
            return None
        update_values: dict[str, object] = {}
        for field in ("relation_type", "direction_label", "distance_label",
                       "travel_time", "difficulty", "visibility",
                       "condition_text", "status"):
            value = getattr(data, field, None)
            if value is not None:
                update_values[field] = value
        if update_values:
            stmt = update(GeoEdge).where(GeoEdge.id == edge_id).values(**update_values)
            await db.execute(stmt)
            await db.flush()
            edge = await self.get(db, edge_id)
        return edge

    async def delete(self, db: AsyncSession, edge_id: uuid.UUID) -> bool:
        stmt = delete(GeoEdge).where(GeoEdge.id == edge_id)
        result = await db.execute(stmt)
        await db.flush()
        return result.rowcount > 0


# ============================================================
# GeoEra Repository (unchanged)
# ============================================================

class GeoEraRepository:
    """历史时期数据访问"""

    async def create(self, db: AsyncSession, data: GeoEraCreate) -> GeoEra:
        era = GeoEra(
            novel_id=uuid.UUID(hex=data.novel_id), name=data.name,
            order_index=data.order_index, summary=data.summary,
            start_event_id=uuid.UUID(hex=data.start_event_id) if data.start_event_id else None,
            end_event_id=uuid.UUID(hex=data.end_event_id) if data.end_event_id else None,
            status=data.status or "canonical",
        )
        db.add(era)
        await db.flush()
        return era

    async def get(self, db: AsyncSession, era_id: uuid.UUID) -> GeoEra | None:
        stmt = select(GeoEra).where(GeoEra.id == era_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_multi(
        self, db: AsyncSession, novel_id: uuid.UUID,
        skip: int = 0, limit: int = DEFAULT_PAGE_SIZE,
    ) -> tuple[list[GeoEra], int]:
        count_stmt = select(func.count(GeoEra.id)).where(GeoEra.novel_id == novel_id)
        count_result = await db.execute(count_stmt)
        total = count_result.scalar() or 0
        stmt = (
            select(GeoEra).where(GeoEra.novel_id == novel_id)
            .offset(skip).limit(limit).order_by(GeoEra.order_index)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all()), total

    async def get_all_sorted(
        self, db: AsyncSession, novel_id: uuid.UUID,
    ) -> list[GeoEra]:
        stmt = select(GeoEra).where(GeoEra.novel_id == novel_id).order_by(GeoEra.order_index)
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def update(
        self, db: AsyncSession, era_id: uuid.UUID, data: GeoEraUpdate,
    ) -> GeoEra | None:
        era = await self.get(db, era_id)
        if era is None:
            return None
        update_values: dict[str, object] = {}
        for field in ("name", "order_index", "summary", "status"):
            value = getattr(data, field, None)
            if value is not None:
                update_values[field] = value
        if data.start_event_id is not None:
            update_values["start_event_id"] = uuid.UUID(hex=data.start_event_id)
        if data.end_event_id is not None:
            update_values["end_event_id"] = uuid.UUID(hex=data.end_event_id)
        if update_values:
            stmt = update(GeoEra).where(GeoEra.id == era_id).values(**update_values)
            await db.execute(stmt)
            await db.flush()
            era = await self.get(db, era_id)
        return era

    async def delete(self, db: AsyncSession, era_id: uuid.UUID) -> bool:
        stmt = delete(GeoEra).where(GeoEra.id == era_id)
        result = await db.execute(stmt)
        await db.flush()
        return result.rowcount > 0
