"""
World 动态地图数据访问层 — PRD docs/PRD-动态地图功能.md

每张表一个 *Repository 类，参照 CoreEntityRepository 模式：
- db: AsyncSession 首参、novel_id 必填
- flush() 而非 commit
- novel_id 隔离查询
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.map_models import (
    MapConfig,
    MapLocationBinding,
    MapMarker,
    MapTile,
)
from modules.world.map_schemas import (
    BindingHex,
    MapConfigCreate,
    MapConfigUpdate,
    MapLocationBindingUpdate,
    MapMarkerCreate,
    MapMarkerUpdate,
    MapTileChange,
)

logger = logging.getLogger(__name__)

# ============================================================
# MapConfigRepository
# ============================================================


class MapConfigRepository:
    """地图配置数据访问。"""

    async def get(self, db: AsyncSession, map_id: uuid.UUID) -> MapConfig | None:
        stmt = select(MapConfig).where(MapConfig.id == map_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_novel(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        parent_map_id: uuid.UUID | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> tuple[list[MapConfig], int]:
        """列出地图，可按 parent_map_id 过滤（None 表顶层）。"""
        conditions: list[Any] = [MapConfig.novel_id == novel_id]
        if parent_map_id is not None:
            conditions.append(MapConfig.parent_map_id == parent_map_id)

        count_stmt = select(func.count(MapConfig.id)).where(*conditions)
        total = (await db.execute(count_stmt)).scalar() or 0

        stmt = (
            select(MapConfig)
            .where(*conditions)
            .order_by(MapConfig.sort_order, MapConfig.created_at)
            .offset(skip)
            .limit(limit)
        )
        items = (await db.execute(stmt)).scalars().all()
        return list(items), total

    async def create(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        data: MapConfigCreate,
    ) -> MapConfig:
        config = MapConfig(
            novel_id=novel_id,
            name=data.name,
            map_type=data.map_type,
            description=data.description,
            grid_width=data.grid_width,
            grid_height=data.grid_height,
            hex_size=data.hex_size,
            parent_map_id=uuid.UUID(data.parent_map_id) if data.parent_map_id else None,
            parent_entity_id=(
                uuid.UUID(data.parent_entity_id) if data.parent_entity_id else None
            ),
        )
        db.add(config)
        await db.flush()
        return config

    async def update(
        self,
        db: AsyncSession,
        map_id: uuid.UUID,
        data: MapConfigUpdate,
    ) -> MapConfig | None:
        values: dict[str, Any] = {}
        for field in (
            "name",
            "description",
            "default_center_x",
            "default_center_y",
            "default_zoom",
            "sort_order",
        ):
            value = getattr(data, field, None)
            if value is not None:
                values[field] = value
        if values:
            stmt = update(MapConfig).where(MapConfig.id == map_id).values(**values)
            await db.execute(stmt)
            await db.flush()
        return await self.get(db, map_id)

    async def delete(self, db: AsyncSession, map_id: uuid.UUID) -> bool:
        stmt = delete(MapConfig).where(MapConfig.id == map_id)
        result = await db.execute(stmt)
        await db.flush()
        return result.rowcount > 0

    async def get_breadcrumbs(
        self,
        db: AsyncSession,
        map_id: uuid.UUID,
    ) -> list[MapConfig]:
        """从当前地图向上遍历 parent_map_id 到顶层（含当前）。"""
        chain: list[MapConfig] = []
        current = await self.get(db, map_id)
        visited: set[uuid.UUID] = set()
        while current is not None and current.id not in visited:
            visited.add(current.id)
            chain.append(current)
            if current.parent_map_id is None:
                break
            current = await self.get(db, current.parent_map_id)
        chain.reverse()  # 顶层在前，当前在尾
        return chain


# ============================================================
# MapTileRepository
# ============================================================


class MapTileRepository:
    """六边形地形数据访问。"""

    async def get_by_map(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        map_id: uuid.UUID,
    ) -> list[MapTile]:
        stmt = select(MapTile).where(
            MapTile.novel_id == novel_id,
            MapTile.map_id == map_id,
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def bulk_create(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        map_id: uuid.UUID,
        tiles: list[MapTileChange],
    ) -> int:
        """批量创建 tile（用于初始化地图）。"""
        objs = [
            MapTile(
                novel_id=novel_id,
                map_id=map_id,
                hex_q=t.hex_q,
                hex_r=t.hex_r,
                terrain_type=t.terrain_type,
                elevation=t.elevation or 0,
            )
            for t in tiles
        ]
        db.add_all(objs)
        await db.flush()
        return len(objs)

    async def bulk_upsert(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        map_id: uuid.UUID,
        changes: list[MapTileChange],
    ) -> int:
        """批量 upsert 地形（编辑模式"应用"）。

        按运行时 dialect 选择 insert 实现：
        - PostgreSQL: postgresql.insert().on_conflict_do_update()
        - SQLite（测试）: sqlite.insert().on_conflict_do_update()
        """
        from sqlalchemy.dialects import postgresql as pg_dialect

        dialect_name = db.bind.dialect.name if db.bind else "sqlite"
        insert_fn = (
            pg_dialect.insert if dialect_name == "postgresql" else sqlite_insert
        )
        count = 0
        for change in changes:
            stmt = (
                insert_fn(MapTile)
                .values(
                    novel_id=novel_id,
                    map_id=map_id,
                    hex_q=change.hex_q,
                    hex_r=change.hex_r,
                    terrain_type=change.terrain_type,
                    elevation=change.elevation or 0,
                )
                .on_conflict_do_update(
                    index_elements=["map_id", "hex_q", "hex_r"],
                    set_={
                        "terrain_type": change.terrain_type,
                        "elevation": change.elevation or 0,
                    },
                )
            )
            await db.execute(stmt)
            count += 1
        await db.flush()
        return count

    async def delete_by_map(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        map_id: uuid.UUID,
    ) -> int:
        stmt = delete(MapTile).where(
            MapTile.novel_id == novel_id,
            MapTile.map_id == map_id,
        )
        result = await db.execute(stmt)
        await db.flush()
        return result.rowcount


# ============================================================
# MapLocationBindingRepository
# ============================================================


class MapLocationBindingRepository:
    """地点绑定数据访问。"""

    async def get(
        self,
        db: AsyncSession,
        binding_id: uuid.UUID,
    ) -> MapLocationBinding | None:
        stmt = select(MapLocationBinding).where(MapLocationBinding.id == binding_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_map(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        map_id: uuid.UUID,
    ) -> list[MapLocationBinding]:
        stmt = select(MapLocationBinding).where(
            MapLocationBinding.novel_id == novel_id,
            MapLocationBinding.map_id == map_id,
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def get_centers(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        map_id: uuid.UUID,
    ) -> list[MapLocationBinding]:
        stmt = select(MapLocationBinding).where(
            MapLocationBinding.novel_id == novel_id,
            MapLocationBinding.map_id == map_id,
            MapLocationBinding.is_center.is_(True),
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def find_center_for_entity(
        self,
        db: AsyncSession,
        map_id: uuid.UUID,
        location_entity_id: uuid.UUID,
    ) -> MapLocationBinding | None:
        """查询某地点在某地图的现有中心点。"""
        stmt = select(MapLocationBinding).where(
            MapLocationBinding.map_id == map_id,
            MapLocationBinding.location_entity_id == location_entity_id,
            MapLocationBinding.is_center.is_(True),
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def clear_center(
        self,
        db: AsyncSession,
        map_id: uuid.UUID,
        location_entity_id: uuid.UUID,
    ) -> int:
        """清除某地点在某地图的全部中心标记（用于切换中心点）。"""
        stmt = (
            update(MapLocationBinding)
            .where(
                MapLocationBinding.map_id == map_id,
                MapLocationBinding.location_entity_id == location_entity_id,
                MapLocationBinding.is_center.is_(True),
            )
            .values(is_center=False)
        )
        result = await db.execute(stmt)
        await db.flush()
        return result.rowcount

    async def bulk_create(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        map_id: uuid.UUID,
        location_entity_id: uuid.UUID,
        hexes: list[BindingHex],
    ) -> list[MapLocationBinding]:
        objs = [
            MapLocationBinding(
                novel_id=novel_id,
                map_id=map_id,
                location_entity_id=location_entity_id,
                hex_q=h.hex_q,
                hex_r=h.hex_r,
                is_center=h.is_center,
                label_override=h.label_override,
                style_override=h.style_override or {},
            )
            for h in hexes
        ]
        db.add_all(objs)
        await db.flush()
        return objs

    async def update(
        self,
        db: AsyncSession,
        binding_id: uuid.UUID,
        data: MapLocationBindingUpdate,
    ) -> MapLocationBinding | None:
        values: dict[str, Any] = {}
        for field in ("is_center", "label_override", "style_override"):
            value = getattr(data, field, None)
            if value is not None:
                values[field] = value
        if values:
            stmt = (
                update(MapLocationBinding)
                .where(MapLocationBinding.id == binding_id)
                .values(**values)
            )
            await db.execute(stmt)
            await db.flush()
        return await self.get(db, binding_id)

    async def delete(self, db: AsyncSession, binding_id: uuid.UUID) -> bool:
        stmt = delete(MapLocationBinding).where(MapLocationBinding.id == binding_id)
        result = await db.execute(stmt)
        await db.flush()
        return result.rowcount > 0


# ============================================================
# MapMarkerRepository（P1）
# ============================================================


class MapMarkerRepository:
    """动态标记数据访问（P1）。"""

    async def get(self, db: AsyncSession, marker_id: uuid.UUID) -> MapMarker | None:
        stmt = select(MapMarker).where(MapMarker.id == marker_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_map(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        map_id: uuid.UUID,
        scene_id: uuid.UUID | None = None,
        scene_index: int | None = None,
    ) -> list[MapMarker]:
        conditions: list[Any] = [
            MapMarker.novel_id == novel_id,
            MapMarker.map_id == map_id,
        ]
        if scene_id is not None:
            conditions.append(
                or_(
                    and_(
                        MapMarker.start_scene_id.is_(None),
                        MapMarker.end_scene_id.is_(None),
                    ),
                    MapMarker.start_scene_id == scene_id,
                    MapMarker.end_scene_id == scene_id,
                )
            )
            if scene_index is not None:
                idx = scene_index
                conditions[-1] = or_(
                    and_(
                        MapMarker.start_scene_id.is_(None),
                        MapMarker.end_scene_id.is_(None),
                    ),
                    and_(
                        MapMarker.start_scene_index.isnot(None),
                        MapMarker.start_scene_index <= idx,
                        or_(
                            MapMarker.end_scene_id == scene_id,
                            and_(
                                MapMarker.end_scene_index.isnot(None),
                                MapMarker.end_scene_index >= idx,
                            ),
                            and_(
                                MapMarker.end_scene_id.is_(None),
                                MapMarker.end_scene_index.is_(None),
                            ),
                        ),
                    ),
                )
        stmt = (
            select(MapMarker)
            .where(*conditions)
            .order_by(MapMarker.start_scene_index.nulls_last(), MapMarker.created_at)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def create(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        map_id: uuid.UUID,
        data: MapMarkerCreate,
    ) -> MapMarker:
        marker = MapMarker(
            novel_id=novel_id,
            map_id=map_id,
            entity_id=uuid.UUID(data.entity_id),
            marker_type=data.marker_type,
            hex_q=data.hex_q,
            hex_r=data.hex_r,
            offset_x=data.offset_x,
            offset_y=data.offset_y,
            label=data.label,
            style_json=data.style_json or {},
            start_scene_id=(
                uuid.UUID(data.start_scene_id) if data.start_scene_id else None
            ),
            start_scene_index=data.start_scene_index,
            end_scene_id=(
                uuid.UUID(data.end_scene_id) if data.end_scene_id else None
            ),
            end_scene_index=data.end_scene_index,
            visible=data.visible,
        )
        db.add(marker)
        await db.flush()
        return marker

    async def update(
        self,
        db: AsyncSession,
        marker_id: uuid.UUID,
        data: MapMarkerUpdate,
    ) -> MapMarker | None:
        values: dict[str, Any] = {}
        for field in (
            "hex_q",
            "hex_r",
            "offset_x",
            "offset_y",
            "label",
            "style_json",
            "start_scene_index",
            "end_scene_index",
            "visible",
        ):
            value = getattr(data, field, None)
            if value is not None:
                values[field] = value
        if data.start_scene_id is not None:
            values["start_scene_id"] = uuid.UUID(data.start_scene_id)
        if data.end_scene_id is not None:
            values["end_scene_id"] = uuid.UUID(data.end_scene_id)
        if values:
            stmt = update(MapMarker).where(MapMarker.id == marker_id).values(**values)
            await db.execute(stmt)
            await db.flush()
        return await self.get(db, marker_id)

    async def delete(self, db: AsyncSession, marker_id: uuid.UUID) -> bool:
        stmt = delete(MapMarker).where(MapMarker.id == marker_id)
        result = await db.execute(stmt)
        await db.flush()
        return result.rowcount > 0
