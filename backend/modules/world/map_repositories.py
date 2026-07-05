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
from typing import Any, ClassVar

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.map_models import (
    MapConfig,
    MapFact,
    MapLocationBinding,
    MapLocationLayout,
    MapMarker,
    MapObservation,
    MapTerrainBinding,
    MapTerrainLayer,
    MapTerrainPatch,
    MapTerrainRegion,
    MapTerritoryTile,
    MapTile,
)
from modules.world.models import CoreEntity

logger = logging.getLogger(__name__)

# ============================================================
# MapEntityRepository — 放置型地图实体泛型基类
# ============================================================


class MapEntityRepository[ModelT]:
    """放置型地图实体（Binding / Marker / Territory）的通用 CRUD 基类。

    Invariants:
      - 所有查询强制 novel_id 隔离。
      - 方法只接受离散参数或 plain dict，不依赖 Pydantic schema。
      - 子类通过 ClassVar ``model_class`` 绑定具体 ORM 模型。
      - 特殊查询（scene 过滤、中心点、批量创建等）在子类中扩展。
    """

    model_class: ClassVar[type[ModelT]]

    async def create(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        map_id: uuid.UUID,
        values: dict[str, Any],
    ) -> ModelT:
        entity = self.model_class(novel_id=novel_id, map_id=map_id, **values)
        db.add(entity)
        await db.flush()
        return entity

    async def get(
        self,
        db: AsyncSession,
        entity_id: uuid.UUID,
    ) -> ModelT | None:
        stmt = select(self.model_class).where(self.model_class.id == entity_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_map(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        map_id: uuid.UUID,
    ) -> list[ModelT]:
        stmt = select(self.model_class).where(
            self.model_class.novel_id == novel_id,
            self.model_class.map_id == map_id,
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def update(
        self,
        db: AsyncSession,
        entity_or_id: ModelT | uuid.UUID,
        values: dict[str, Any],
    ) -> ModelT | None:
        entity = (
            await self.get(db, entity_or_id)
            if isinstance(entity_or_id, uuid.UUID)
            else entity_or_id
        )
        if entity is None:
            return None
        if values:
            for field, value in values.items():
                setattr(entity, field, value)
            db.add(entity)
            await db.flush()
        return entity

    async def delete(
        self,
        db: AsyncSession,
        entity_id: uuid.UUID,
    ) -> bool:
        stmt = delete(self.model_class).where(self.model_class.id == entity_id)
        result = await db.execute(stmt)
        await db.flush()
        return result.rowcount > 0


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
            .order_by(MapConfig.sort_order, MapConfig.created_at, MapConfig.id)
            .offset(skip)
            .limit(limit)
        )
        items = (await db.execute(stmt)).scalars().all()
        return list(items), total

    async def first_by_novel(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        parent_map_id: uuid.UUID | None = None,
    ) -> MapConfig | None:
        """返回当前排序下的第一张地图，不执行分页总数查询。"""
        conditions: list[Any] = [MapConfig.novel_id == novel_id]
        if parent_map_id is not None:
            conditions.append(MapConfig.parent_map_id == parent_map_id)

        stmt = (
            select(MapConfig)
            .where(*conditions)
            .order_by(MapConfig.sort_order, MapConfig.created_at, MapConfig.id)
            .limit(1)
        )
        return (await db.execute(stmt)).scalar_one_or_none()

    async def get_by_name(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        name: str,
        parent_map_id: uuid.UUID | None = None,
    ) -> MapConfig | None:
        """按同一父地图和名称精确查找地图。"""
        conditions: list[Any] = [MapConfig.novel_id == novel_id, MapConfig.name == name]
        if parent_map_id is None:
            conditions.append(MapConfig.parent_map_id.is_(None))
        else:
            conditions.append(MapConfig.parent_map_id == parent_map_id)
        stmt = select(MapConfig).where(*conditions).limit(1)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def create(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        values: dict[str, Any],
    ) -> MapConfig:
        """使用已构造的 plain dict 创建地图配置。"""
        config = MapConfig(novel_id=novel_id, **values)
        db.add(config)
        await db.flush()
        return config

    async def update(
        self,
        db: AsyncSession,
        config_or_id: MapConfig | uuid.UUID,
        values: dict[str, Any],
    ) -> MapConfig | None:
        config = (
            await self.get(db, config_or_id)
            if isinstance(config_or_id, uuid.UUID)
            else config_or_id
        )
        if config is None:
            return None
        if values:
            for field, value in values.items():
                setattr(config, field, value)
            db.add(config)
            await db.flush()
        return config

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
        tiles: list[dict[str, Any]],
    ) -> int:
        """批量创建 tile（用于初始化地图）。

        ``tiles`` 为 service 层构造的 plain dict 列表，
        已含 hex_q / hex_r / terrain_type / elevation。
        """
        objs = [
            MapTile(
                novel_id=novel_id,
                map_id=map_id,
                hex_q=t["hex_q"],
                hex_r=t["hex_r"],
                terrain_type=t["terrain_type"],
                elevation=t.get("elevation") or 0,
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
        changes: list[dict[str, Any]],
    ) -> int:
        """批量 upsert 地形（编辑模式"应用"）。

        按运行时 dialect 选择 insert 实现：
        - PostgreSQL: postgresql.insert().on_conflict_do_update()
        - SQLite（测试）: sqlite.insert().on_conflict_do_update()
        """
        from sqlalchemy.dialects import postgresql as pg_dialect

        dialect_name = db.bind.dialect.name if db.bind else "sqlite"
        insert_fn = pg_dialect.insert if dialect_name == "postgresql" else sqlite_insert
        count = 0
        for change in changes:
            stmt = (
                insert_fn(MapTile)
                .values(
                    novel_id=novel_id,
                    map_id=map_id,
                    hex_q=change["hex_q"],
                    hex_r=change["hex_r"],
                    terrain_type=change["terrain_type"],
                    elevation=change.get("elevation") or 0,
                )
                .on_conflict_do_update(
                    index_elements=["map_id", "hex_q", "hex_r"],
                    set_={
                        "terrain_type": change["terrain_type"],
                        "elevation": change.get("elevation") or 0,
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


class MapLocationBindingRepository(MapEntityRepository[MapLocationBinding]):
    """地点绑定数据访问。"""

    model_class = MapLocationBinding

    async def get_by_map_for_entity_statuses(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        map_id: uuid.UUID,
        *,
        statuses: list[str],
    ) -> list[MapLocationBinding]:
        stmt = (
            select(MapLocationBinding)
            .join(CoreEntity, CoreEntity.id == MapLocationBinding.location_entity_id)
            .where(
                MapLocationBinding.novel_id == novel_id,
                MapLocationBinding.map_id == map_id,
                CoreEntity.novel_id == novel_id,
                CoreEntity.status.in_(statuses),
            )
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def get_by_hexes_for_entity_statuses(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        map_id: uuid.UUID,
        hexes: list[tuple[int, int]],
        *,
        statuses: list[str],
    ) -> list[MapLocationBinding]:
        unique_hexes = list(dict.fromkeys(hexes))
        if not unique_hexes:
            return []
        stmt = (
            select(MapLocationBinding)
            .join(CoreEntity, CoreEntity.id == MapLocationBinding.location_entity_id)
            .where(
                MapLocationBinding.novel_id == novel_id,
                MapLocationBinding.map_id == map_id,
                CoreEntity.novel_id == novel_id,
                CoreEntity.status.in_(statuses),
                or_(
                    *[
                        (MapLocationBinding.hex_q == hex_q)
                        & (MapLocationBinding.hex_r == hex_r)
                        for hex_q, hex_r in unique_hexes
                    ]
                ),
            )
            .order_by(MapLocationBinding.created_at, MapLocationBinding.id)
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

    async def find_any_for_entity(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        location_entity_id: uuid.UUID,
    ) -> MapLocationBinding | None:
        """查询地点在任意地图中的代表绑定。"""
        stmt = (
            select(MapLocationBinding)
            .where(
                MapLocationBinding.novel_id == novel_id,
                MapLocationBinding.location_entity_id == location_entity_id,
            )
            .order_by(
                MapLocationBinding.is_center.desc(),
                MapLocationBinding.created_at,
                MapLocationBinding.id,
            )
            .limit(1)
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

    async def clear_centers(
        self,
        db: AsyncSession,
        map_id: uuid.UUID,
        location_entity_ids: list[uuid.UUID],
    ) -> int:
        """批量清除多个地点在某地图的中心标记。"""
        unique_ids = list(dict.fromkeys(location_entity_ids))
        if not unique_ids:
            return 0
        stmt = (
            update(MapLocationBinding)
            .where(
                MapLocationBinding.map_id == map_id,
                MapLocationBinding.location_entity_id.in_(unique_ids),
                MapLocationBinding.is_center.is_(True),
            )
            .values(is_center=False)
        )
        result = await db.execute(stmt)
        await db.flush()
        return result.rowcount

    async def delete_for_map(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        map_id: uuid.UUID,
    ) -> int:
        stmt = delete(MapLocationBinding).where(
            MapLocationBinding.novel_id == novel_id,
            MapLocationBinding.map_id == map_id,
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
        hexes: list[dict[str, Any]],
    ) -> list[MapLocationBinding]:
        """使用已构造的 plain dict 列表批量创建地点绑定。"""
        objs = [
            MapLocationBinding(
                novel_id=novel_id,
                map_id=map_id,
                location_entity_id=location_entity_id,
                **h,
            )
            for h in hexes
        ]
        db.add_all(objs)
        await db.flush()
        return objs

    async def bulk_create_many(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        map_id: uuid.UUID,
        bindings: list[dict[str, Any]],
    ) -> list[MapLocationBinding]:
        """批量创建多个地点的绑定，保持输入顺序。"""
        objs = [
            MapLocationBinding(
                novel_id=novel_id,
                map_id=map_id,
                **binding,
            )
            for binding in bindings
        ]
        if not objs:
            return []
        db.add_all(objs)
        await db.flush()
        return objs


# ============================================================
# MapLocationLayoutRepository
# ============================================================


class MapLocationLayoutRepository(MapEntityRepository[MapLocationLayout]):
    """地点布局节点数据访问。"""

    model_class = MapLocationLayout

    async def replace_for_map(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        map_id: uuid.UUID,
        layouts: list[dict[str, Any]],
    ) -> list[MapLocationLayout]:
        stmt = delete(MapLocationLayout).where(
            MapLocationLayout.novel_id == novel_id,
            MapLocationLayout.map_id == map_id,
        )
        await db.execute(stmt)
        objs = [
            MapLocationLayout(novel_id=novel_id, map_id=map_id, **layout)
            for layout in layouts
        ]
        db.add_all(objs)
        await db.flush()
        return objs


# ============================================================
# MapTerrain repositories
# ============================================================


class MapTerrainLayerRepository(MapEntityRepository[MapTerrainLayer]):
    """手绘地形图层数据访问。"""

    model_class = MapTerrainLayer

    async def get_in_map(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        map_id: uuid.UUID,
        layer_id: uuid.UUID,
    ) -> MapTerrainLayer | None:
        stmt = select(MapTerrainLayer).where(
            MapTerrainLayer.novel_id == novel_id,
            MapTerrainLayer.map_id == map_id,
            MapTerrainLayer.id == layer_id,
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()


class MapTerrainRegionRepository(MapEntityRepository[MapTerrainRegion]):
    """手绘地形区域数据访问。"""

    model_class = MapTerrainRegion

    async def upsert(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        map_id: uuid.UUID,
        values: dict[str, Any],
    ) -> MapTerrainRegion:
        region_id = values.get("id")
        if region_id:
            existing = await self.get_in_map(db, novel_id, map_id, region_id)
            if existing is not None:
                for field in ("layer_id", "name", "region_status", "meta"):
                    if field in values:
                        setattr(existing, field, values[field])
                await db.flush()
                return existing
        return await self.create(db, novel_id, map_id, values)

    async def upsert_many(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        map_id: uuid.UUID,
        items: list[dict[str, Any]],
    ) -> list[MapTerrainRegion]:
        """批量 upsert 地形区域，保持输入顺序并只 flush 一次。"""
        if not items:
            return []
        region_ids = [values.get("id") for values in items if values.get("id")]
        existing_by_id: dict[uuid.UUID, MapTerrainRegion] = {}
        if region_ids:
            stmt = select(MapTerrainRegion).where(
                MapTerrainRegion.novel_id == novel_id,
                MapTerrainRegion.map_id == map_id,
                MapTerrainRegion.id.in_(region_ids),
            )
            result = await db.execute(stmt)
            existing_by_id = {
                region.id: region for region in result.scalars().all()
            }

        regions: list[MapTerrainRegion] = []
        for values in items:
            region_id = values.get("id")
            existing = existing_by_id.get(region_id) if region_id else None
            if existing is not None:
                for field in ("layer_id", "name", "region_status", "meta"):
                    if field in values:
                        setattr(existing, field, values[field])
                regions.append(existing)
                continue
            region = MapTerrainRegion(novel_id=novel_id, map_id=map_id, **values)
            db.add(region)
            regions.append(region)
        await db.flush()
        return regions

    async def get_in_map(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        map_id: uuid.UUID,
        region_id: uuid.UUID,
    ) -> MapTerrainRegion | None:
        stmt = select(MapTerrainRegion).where(
            MapTerrainRegion.novel_id == novel_id,
            MapTerrainRegion.map_id == map_id,
            MapTerrainRegion.id == region_id,
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()


class MapTerrainPatchRepository(MapEntityRepository[MapTerrainPatch]):
    """手绘地形 patch 数据访问。"""

    model_class = MapTerrainPatch

    async def replace_for_layer(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        map_id: uuid.UUID,
        layer_id: uuid.UUID,
        patches: list[dict[str, Any]],
    ) -> list[MapTerrainPatch]:
        stmt = delete(MapTerrainPatch).where(
            MapTerrainPatch.novel_id == novel_id,
            MapTerrainPatch.map_id == map_id,
            MapTerrainPatch.layer_id == layer_id,
        )
        await db.execute(stmt)
        objs = [
            MapTerrainPatch(
                novel_id=novel_id,
                map_id=map_id,
                layer_id=layer_id,
                **patch,
            )
            for patch in patches
        ]
        db.add_all(objs)
        await db.flush()
        return objs


class MapTerrainBindingRepository(MapEntityRepository[MapTerrainBinding]):
    """手绘地形与地点绑定数据访问。"""

    model_class = MapTerrainBinding


# ============================================================
# MapMarkerRepository（P1）
# ============================================================


class MapMarkerRepository(MapEntityRepository[MapMarker]):
    """动态标记数据访问（P1）。"""

    model_class = MapMarker

    @staticmethod
    def _scene_window_condition(
        scene_id: uuid.UUID | None,
        scene_index: int | None,
        *,
        include_direct_ids: bool = False,
    ) -> Any | None:
        if scene_id is None:
            return None
        timeless = and_(
            MapMarker.start_scene_id.is_(None),
            MapMarker.end_scene_id.is_(None),
        )
        direct_ids = (
            MapMarker.start_scene_id == scene_id,
            MapMarker.end_scene_id == scene_id,
        )
        if scene_index is None:
            return or_(timeless, *direct_ids)

        index_window = and_(
            MapMarker.start_scene_index.isnot(None),
            MapMarker.start_scene_index <= scene_index,
            or_(
                MapMarker.end_scene_id == scene_id,
                and_(
                    MapMarker.end_scene_index.isnot(None),
                    MapMarker.end_scene_index >= scene_index,
                ),
                and_(
                    MapMarker.end_scene_id.is_(None),
                    MapMarker.end_scene_index.is_(None),
                ),
            ),
        )
        if include_direct_ids:
            return or_(timeless, *direct_ids, index_window)
        return or_(timeless, index_window)

    async def get_by_map_and_scene_for_entity_statuses(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        map_id: uuid.UUID,
        *,
        statuses: list[str],
        scene_id: uuid.UUID | None = None,
        scene_index: int | None = None,
    ) -> list[MapMarker]:
        conditions: list[Any] = [
            MapMarker.novel_id == novel_id,
            MapMarker.map_id == map_id,
            CoreEntity.novel_id == novel_id,
            CoreEntity.status.in_(statuses),
        ]
        scene_window = self._scene_window_condition(scene_id, scene_index)
        if scene_window is not None:
            conditions.append(scene_window)
        stmt = (
            select(MapMarker)
            .join(CoreEntity, CoreEntity.id == MapMarker.entity_id)
            .where(*conditions)
            .order_by(
                MapMarker.start_scene_index.nulls_last(),
                MapMarker.created_at,
                MapMarker.id,
            )
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def get_by_map_and_scene(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        map_id: uuid.UUID,
        *,
        scene_id: uuid.UUID | None = None,
        scene_index: int | None = None,
    ) -> list[MapMarker]:
        """按地图 + Scene 时间范围查询标记。"""
        conditions: list[Any] = [
            MapMarker.novel_id == novel_id,
            MapMarker.map_id == map_id,
        ]
        scene_window = self._scene_window_condition(scene_id, scene_index)
        if scene_window is not None:
            conditions.append(scene_window)
        stmt = (
            select(MapMarker)
            .where(*conditions)
            .order_by(
                MapMarker.start_scene_index.nulls_last(),
                MapMarker.created_at,
                MapMarker.id,
            )
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def get_by_scene(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        scene_id: uuid.UUID,
        scene_index: int | None = None,
    ) -> list[MapMarker]:
        """按 Scene 时间范围跨地图查询可见标记。"""
        conditions: list[Any] = [
            MapMarker.novel_id == novel_id,
            MapMarker.visible.is_(True),
        ]
        conditions.append(
            self._scene_window_condition(
                scene_id,
                scene_index,
                include_direct_ids=True,
            )
        )
        stmt = (
            select(MapMarker)
            .where(*conditions)
            .order_by(
                MapMarker.start_scene_index.nulls_last(),
                MapMarker.created_at,
                MapMarker.id,
            )
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def find_any_for_entity(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        entity_id: uuid.UUID,
    ) -> MapMarker | None:
        """查询实体在任意地图中的代表标记。"""
        stmt = (
            select(MapMarker)
            .where(
                MapMarker.novel_id == novel_id,
                MapMarker.entity_id == entity_id,
                MapMarker.visible.is_(True),
            )
            .order_by(
                MapMarker.start_scene_index.nulls_last(),
                MapMarker.created_at,
                MapMarker.id,
            )
            .limit(1)
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_latest_before_scene_for_entities(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        entity_ids: list[uuid.UUID],
        scene_index: int,
    ) -> dict[uuid.UUID, MapMarker]:
        """返回每个角色在当前 Scene 前最近一次地图标记。"""
        if not entity_ids:
            return {}
        stmt = (
            select(MapMarker)
            .where(
                MapMarker.novel_id == novel_id,
                MapMarker.visible.is_(True),
                MapMarker.marker_type == "character",
                MapMarker.entity_id.in_(entity_ids),
                MapMarker.start_scene_index.isnot(None),
                MapMarker.start_scene_index < scene_index,
            )
            .order_by(
                MapMarker.start_scene_index.desc(),
                MapMarker.created_at.desc(),
                MapMarker.id.desc(),
            )
        )
        result = await db.execute(stmt)
        latest: dict[uuid.UUID, MapMarker] = {}
        for marker in result.scalars().all():
            latest.setdefault(marker.entity_id, marker)
        return latest


# ============================================================
# MapTerritoryRepository（P2）
# ============================================================


class MapTerritoryRepository(MapEntityRepository[MapTerritoryTile]):
    """势力范围数据访问（P2）。"""

    model_class = MapTerritoryTile

    async def get_by_map_for_entity_statuses(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        map_id: uuid.UUID,
        *,
        statuses: list[str],
    ) -> list[MapTerritoryTile]:
        stmt = (
            select(MapTerritoryTile)
            .join(CoreEntity, CoreEntity.id == MapTerritoryTile.faction_entity_id)
            .where(
                MapTerritoryTile.novel_id == novel_id,
                MapTerritoryTile.map_id == map_id,
                CoreEntity.novel_id == novel_id,
                CoreEntity.status.in_(statuses),
            )
            .order_by(MapTerritoryTile.created_at, MapTerritoryTile.id)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def get_by_map_and_faction(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        map_id: uuid.UUID,
        faction_entity_id: uuid.UUID,
    ) -> list[MapTerritoryTile]:
        """按地图 + 组织过滤势力范围。"""
        stmt = select(MapTerritoryTile).where(
            MapTerritoryTile.novel_id == novel_id,
            MapTerritoryTile.map_id == map_id,
            MapTerritoryTile.faction_entity_id == faction_entity_id,
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def get_by_hex(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        map_id: uuid.UUID,
        hex_q: int,
        hex_r: int,
    ) -> list[MapTerritoryTile]:
        stmt = select(MapTerritoryTile).where(
            MapTerritoryTile.novel_id == novel_id,
            MapTerritoryTile.map_id == map_id,
            MapTerritoryTile.hex_q == hex_q,
            MapTerritoryTile.hex_r == hex_r,
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def get_by_hexes(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        map_id: uuid.UUID,
        hexes: list[tuple[int, int]],
    ) -> list[MapTerritoryTile]:
        unique_hexes = list(dict.fromkeys(hexes))
        if not unique_hexes:
            return []
        stmt = (
            select(MapTerritoryTile)
            .where(
                MapTerritoryTile.novel_id == novel_id,
                MapTerritoryTile.map_id == map_id,
                or_(
                    *[
                        (MapTerritoryTile.hex_q == hex_q)
                        & (MapTerritoryTile.hex_r == hex_r)
                        for hex_q, hex_r in unique_hexes
                    ]
                ),
            )
            .order_by(MapTerritoryTile.created_at, MapTerritoryTile.id)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def find_any_for_faction(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        faction_entity_id: uuid.UUID,
    ) -> MapTerritoryTile | None:
        """查询组织在任意地图中的代表势力格。"""
        stmt = (
            select(MapTerritoryTile)
            .where(
                MapTerritoryTile.novel_id == novel_id,
                MapTerritoryTile.faction_entity_id == faction_entity_id,
            )
            .order_by(MapTerritoryTile.created_at, MapTerritoryTile.id)
            .limit(1)
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def create_batch(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        map_id: uuid.UUID,
        faction_entity_id: uuid.UUID,
        hexes: list[dict[str, Any]],
    ) -> list[MapTerritoryTile]:
        """使用已构造的 plain dict 列表批量创建势力范围。"""
        tiles: list[MapTerritoryTile] = []
        for h in hexes:
            tile = MapTerritoryTile(
                novel_id=novel_id,
                map_id=map_id,
                faction_entity_id=faction_entity_id,
                **h,
            )
            tiles.append(tile)
        db.add_all(tiles)
        await db.flush()
        return tiles

    async def delete_by_faction(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        map_id: uuid.UUID,
        faction_entity_id: uuid.UUID,
    ) -> int:
        """删除某组织在某地图上的全部势力范围，返回删除行数。"""
        stmt = delete(MapTerritoryTile).where(
            MapTerritoryTile.novel_id == novel_id,
            MapTerritoryTile.map_id == map_id,
            MapTerritoryTile.faction_entity_id == faction_entity_id,
        )
        result = await db.execute(stmt)
        await db.flush()
        return result.rowcount


# ============================================================
# MapObservationRepository（世界动态 P0）
# ============================================================


class MapObservationRepository:
    """地图观察事实数据访问。"""

    async def get(
        self,
        db: AsyncSession,
        observation_id: uuid.UUID,
    ) -> MapObservation | None:
        stmt = select(MapObservation).where(MapObservation.id == observation_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_many(
        self,
        db: AsyncSession,
        observation_ids: list[uuid.UUID],
    ) -> list[MapObservation]:
        if not observation_ids:
            return []
        unique_ids = list(dict.fromkeys(observation_ids))
        result = await db.execute(
            select(MapObservation).where(MapObservation.id.in_(unique_ids))
        )
        by_id = {observation.id: observation for observation in result.scalars().all()}
        return [
            by_id[observation_id]
            for observation_id in unique_ids
            if observation_id in by_id
        ]

    async def list(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        map_id: uuid.UUID | None = None,
        review_state: str | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> tuple[list[MapObservation], int]:
        conditions: list[Any] = [MapObservation.novel_id == novel_id]
        if map_id is not None:
            conditions.append(MapObservation.map_id == map_id)
        if review_state:
            conditions.append(MapObservation.review_state == review_state)

        count_stmt = select(func.count(MapObservation.id)).where(*conditions)
        total = (await db.execute(count_stmt)).scalar() or 0

        stmt = (
            select(MapObservation)
            .where(*conditions)
            .order_by(
                MapObservation.scene_index.nulls_last(),
                MapObservation.created_at,
                MapObservation.id,
            )
            .offset(skip)
            .limit(limit)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all()), total

    async def list_for_dashboard(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        map_id: uuid.UUID,
        limit: int = 100,
    ) -> list[MapObservation]:
        """列出总控台候选：当前地图 + 尚未归属具体地图的观察事实。"""
        stmt = (
            select(MapObservation)
            .where(
                MapObservation.novel_id == novel_id,
                or_(MapObservation.map_id == map_id, MapObservation.map_id.is_(None)),
                MapObservation.review_state.in_(["candidate", "conflicted"]),
            )
            .order_by(
                MapObservation.review_state,
                MapObservation.scene_index.nulls_last(),
                MapObservation.created_at.desc(),
                MapObservation.id.desc(),
            )
            .limit(limit)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def list_for_scene_summary(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        map_id: uuid.UUID,
        scene_id: uuid.UUID,
        dynamic_types: set[str] | tuple[str, ...],
        limit: int = 100,
    ) -> list[MapObservation]:
        stmt = (
            select(MapObservation)
            .where(
                MapObservation.novel_id == novel_id,
                or_(MapObservation.map_id == map_id, MapObservation.map_id.is_(None)),
                MapObservation.scene_id == scene_id,
                MapObservation.review_state.in_(["candidate", "conflicted"]),
                MapObservation.dynamic_type.in_(tuple(dynamic_types)),
            )
            .order_by(
                MapObservation.review_state,
                MapObservation.scene_index.nulls_last(),
                MapObservation.created_at.desc(),
                MapObservation.id.desc(),
            )
            .limit(limit)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def find_map_for_scene(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        scene_id: uuid.UUID,
    ) -> uuid.UUID | None:
        """Find a map referenced by active observations for a scene."""
        stmt = (
            select(MapObservation.map_id)
            .where(
                MapObservation.novel_id == novel_id,
                MapObservation.scene_id == scene_id,
                MapObservation.map_id.isnot(None),
                MapObservation.review_state.in_(["candidate", "conflicted"]),
            )
            .order_by(
                MapObservation.scene_index.nulls_last(),
                MapObservation.created_at,
                MapObservation.id,
            )
            .limit(1)
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def create(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        values: dict[str, Any],
    ) -> MapObservation:
        observation = MapObservation(novel_id=novel_id, **values)
        db.add(observation)
        await db.flush()
        return observation

    async def update_review_state(
        self,
        db: AsyncSession,
        observation_or_id: MapObservation | uuid.UUID,
        review_state: str,
    ) -> MapObservation | None:
        observation = (
            observation_or_id
            if isinstance(observation_or_id, MapObservation)
            else await self.get(db, observation_or_id)
        )
        if observation is None:
            return None
        observation.review_state = review_state
        db.add(observation)
        await db.flush()
        return observation

    async def update_review_states(
        self,
        db: AsyncSession,
        observation_ids: list[uuid.UUID],
        review_state: str,
    ) -> list[MapObservation]:
        if not observation_ids:
            return []

        unique_ids = list(dict.fromkeys(observation_ids))
        stmt = (
            update(MapObservation)
            .where(MapObservation.id.in_(unique_ids))
            .values(review_state=review_state)
        )
        await db.execute(stmt)
        await db.flush()

        result = await db.execute(
            select(MapObservation).where(MapObservation.id.in_(unique_ids))
        )
        by_id = {observation.id: observation for observation in result.scalars().all()}
        return [
            by_id[observation_id]
            for observation_id in unique_ids
            if observation_id in by_id
        ]

    async def update(
        self,
        db: AsyncSession,
        observation_or_id: MapObservation | uuid.UUID,
        values: dict[str, Any],
    ) -> MapObservation | None:
        observation = (
            observation_or_id
            if isinstance(observation_or_id, MapObservation)
            else await self.get(db, observation_or_id)
        )
        if observation is None:
            return None
        if not values:
            return observation
        for field, value in values.items():
            setattr(observation, field, value)
        db.add(observation)
        await db.flush()
        return observation


# ============================================================
# MapFactRepository（世界动态 P0）
# ============================================================


class MapFactRepository:
    """已确认地图事实数据访问。"""

    async def get(self, db: AsyncSession, fact_id: uuid.UUID) -> MapFact | None:
        stmt = select(MapFact).where(MapFact.id == fact_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_many(
        self,
        db: AsyncSession,
        fact_ids: list[uuid.UUID],
    ) -> list[MapFact]:
        unique_ids = list(dict.fromkeys(fact_ids))
        if not unique_ids:
            return []
        result = await db.execute(select(MapFact).where(MapFact.id.in_(unique_ids)))
        by_id = {fact.id: fact for fact in result.scalars().all()}
        return [by_id[fact_id] for fact_id in unique_ids if fact_id in by_id]

    async def get_by_observation(
        self,
        db: AsyncSession,
        observation_id: uuid.UUID,
    ) -> MapFact | None:
        stmt = select(MapFact).where(MapFact.observation_id == observation_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_observations(
        self,
        db: AsyncSession,
        observation_ids: list[uuid.UUID],
    ) -> list[MapFact]:
        unique_ids = list(dict.fromkeys(observation_ids))
        if not unique_ids:
            return []
        stmt = select(MapFact).where(MapFact.observation_id.in_(unique_ids))
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def list(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        map_id: uuid.UUID | None = None,
        fact_status: str | None = "confirmed",
        skip: int = 0,
        limit: int = 100,
    ) -> tuple[list[MapFact], int]:
        conditions: list[Any] = [MapFact.novel_id == novel_id]
        if map_id is not None:
            conditions.append(MapFact.map_id == map_id)
        if fact_status:
            conditions.append(MapFact.fact_status == fact_status)

        count_stmt = select(func.count(MapFact.id)).where(*conditions)
        total = (await db.execute(count_stmt)).scalar() or 0

        stmt = (
            select(MapFact)
            .where(*conditions)
            .order_by(
                MapFact.scene_index.nulls_last(),
                MapFact.created_at,
                MapFact.id,
            )
            .offset(skip)
            .limit(limit)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all()), total

    async def find_map_for_scene(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        scene_id: uuid.UUID,
        *,
        fact_status: str = "confirmed",
    ) -> uuid.UUID | None:
        stmt = (
            select(MapFact.map_id)
            .where(
                MapFact.novel_id == novel_id,
                MapFact.scene_id == scene_id,
                MapFact.map_id.isnot(None),
                MapFact.fact_status == fact_status,
            )
            .order_by(
                MapFact.scene_index.nulls_last(),
                MapFact.created_at,
                MapFact.id,
            )
            .limit(1)
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_for_scene_summary(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        map_id: uuid.UUID,
        scene_id: uuid.UUID,
        dynamic_types: set[str] | tuple[str, ...],
        fact_status: str = "confirmed",
        limit: int = 100,
    ) -> list[MapFact]:
        stmt = (
            select(MapFact)
            .where(
                MapFact.novel_id == novel_id,
                MapFact.map_id == map_id,
                MapFact.scene_id == scene_id,
                MapFact.fact_status == fact_status,
                MapFact.dynamic_type.in_(tuple(dynamic_types)),
            )
            .order_by(
                MapFact.scene_index.nulls_last(),
                MapFact.created_at,
                MapFact.id,
            )
            .limit(limit)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def create(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        values: dict[str, Any],
    ) -> MapFact:
        fact = MapFact(novel_id=novel_id, **values)
        db.add(fact)
        await db.flush()
        return fact

    async def create_many(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        values_list: list[dict[str, Any]],
    ) -> list[MapFact]:
        if not values_list:
            return []
        facts = [MapFact(novel_id=novel_id, **values) for values in values_list]
        db.add_all(facts)
        await db.flush()
        return facts

    async def delete_quick_create_location_facts(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        map_id: uuid.UUID,
    ) -> int:
        stmt = select(MapFact).where(
            MapFact.novel_id == novel_id,
            MapFact.map_id == map_id,
            MapFact.dynamic_type == "location",
        )
        result = await db.execute(stmt)
        facts = [
            fact
            for fact in result.scalars().all()
            if (fact.source_ref or {}).get("source") == "map_quick_create"
        ]
        for fact in facts:
            await db.delete(fact)
        await db.flush()
        return len(facts)

    async def update_status(
        self,
        db: AsyncSession,
        fact_or_id: MapFact | uuid.UUID,
        fact_status: str,
    ) -> MapFact | None:
        fact = (
            fact_or_id
            if isinstance(fact_or_id, MapFact)
            else await self.get(db, fact_or_id)
        )
        if fact is None:
            return None
        fact.fact_status = fact_status
        db.add(fact)
        await db.flush()
        return fact

    async def update_statuses(
        self,
        db: AsyncSession,
        fact_ids: list[uuid.UUID],
        fact_status: str,
    ) -> list[MapFact]:
        unique_ids = list(dict.fromkeys(fact_ids))
        if not unique_ids:
            return []
        stmt = (
            update(MapFact)
            .where(MapFact.id.in_(unique_ids))
            .values(fact_status=fact_status)
        )
        await db.execute(stmt)
        await db.flush()
        result = await db.execute(select(MapFact).where(MapFact.id.in_(unique_ids)))
        by_id = {fact.id: fact for fact in result.scalars().all()}
        return [by_id[fact_id] for fact_id in unique_ids if fact_id in by_id]
