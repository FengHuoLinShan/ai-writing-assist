"""
World 动态地图 ORM 模型 — PRD docs/PRD-动态地图功能.md

4 张表（P0 实现 3 张 + P1 数据层预留 1 张）：
- map_configs: 地图配置（世界地图 / 城市 / 区域 / 地下城，自引用树）
- map_tiles: 六边形地形网格（轴向坐标 q,r）
- map_location_bindings: 地点绑定（core_entities.entity_type=location → hex）
- map_markers: 动态标记（P1 预留，character/event/item，按 Scene 时间层显隐）

约定（与 world/models.py 一致）：
- Base + UUIDMixin + TimestampMixin + NovelMixin
  （地图无 draft/candidate，不用 StatusMixin）
- JSON 字段用通用 JSON（PostgreSQL 渲染 JSONB，
  SQLite 测试回退 TEXT）
- hex 坐标只存 (q, r)；第三坐标 s = -q - r 由前端计算
  （PRD §4.2 的 GENERATED 列不在 ORM 声明，
  参照 search_text 惯例；如需后端按 s 查询再补 Alembic 原始 SQL）
"""

from __future__ import annotations

import uuid

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.base import Base, NovelMixin, TimestampMixin, UUIDMixin

# ============================================================
# MapConfig — 地图配置（自引用树）
# ============================================================


class MapConfig(Base, UUIDMixin, TimestampMixin, NovelMixin):
    """动态地图配置 — 世界地图 / 城市详图 / 区域 / 地下城

    通过 parent_map_id 自引用形成层级（世界 → 城市 → 皇宫）。
    """

    __tablename__ = "map_configs"
    __table_args__ = (
        # 同一 novel 下、同一父层级内，地图名唯一
        Index(
            "uq_map_config_novel_parent_name",
            "novel_id",
            "parent_map_id",
            "name",
            unique=True,
        ),
        {"comment": "动态地图配置"},
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False, comment="地图名称")
    map_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        index=True,
        comment="地图类型：world / city / region / dungeon",
    )
    description: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="地图描述"
    )

    # 视口默认参数（[0,1] 归一化中心 + zoom 层级）
    default_center_x: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.5, comment="默认视口中心 x（归一化 0~1）"
    )
    default_center_y: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.5, comment="默认视口中心 y（归一化 0~1）"
    )
    default_zoom: Mapped[float] = mapped_column(
        Float, nullable=False, default=0, comment="默认缩放层级"
    )

    # 网格规格
    grid_width: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="网格宽度（六边形数）"
    )
    grid_height: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="网格高度（六边形数）"
    )
    hex_size: Mapped[int] = mapped_column(
        Integer, nullable=False, default=30, comment="六边形像素半径（渲染用）"
    )

    # 层级关系（自引用）
    parent_map_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("map_configs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="父地图 ID（NULL = 顶层世界地图）",
    )
    parent_entity_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("core_entities.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="该详图对应的父地点实体（core_entities.entity_type=location）",
    )

    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="同层级排序"
    )

    # 自引用 relationship（需 foreign_keys 消歧）
    parent_map: Mapped[MapConfig | None] = relationship(
        "MapConfig",
        remote_side="MapConfig.id",
        foreign_keys="MapConfig.parent_map_id",
        back_populates="child_maps",
    )
    child_maps: Mapped[list[MapConfig]] = relationship(
        "MapConfig",
        back_populates="parent_map",
        foreign_keys="MapConfig.parent_map_id",
    )

    def __repr__(self) -> str:
        return f"<MapConfig id={self.id} type={self.map_type} name={self.name!r}>"


# ============================================================
# MapTile — 六边形地形网格
# ============================================================


class MapTile(Base, UUIDMixin, TimestampMixin, NovelMixin):
    """六边形地形格 — 轴向坐标 (q, r)

    第三坐标 s = -q - r 由前端计算，后端不存（PRD §4.2 GENERATED 列不在 ORM 声明）。
    """

    __tablename__ = "map_tiles"
    __table_args__ = (
        # 同一地图内 (q, r) 唯一
        Index("uq_map_tile_map_qr", "map_id", "hex_q", "hex_r", unique=True),
        {"comment": "六边形地形网格"},
    )

    map_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("map_configs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属地图",
    )
    hex_q: Mapped[int] = mapped_column(Integer, nullable=False, comment="轴向坐标 q")
    hex_r: Mapped[int] = mapped_column(Integer, nullable=False, comment="轴向坐标 r")
    terrain_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        comment="地形：grassland/forest/desert/mountain/water/city/road/ruin/secret/danger",
    )
    elevation: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="海拔（渲染用）"
    )
    style_override: Mapped[dict | None] = mapped_column(
        JSON, nullable=True, default=dict, comment="样式覆盖（颜色等）"
    )

    def __repr__(self) -> str:
        return (
            f"<MapTile map={self.map_id} q={self.hex_q} "
            f"r={self.hex_r} terrain={self.terrain_type}>"
        )


# ============================================================
# MapLocationBinding — 地点绑定
# ============================================================


class MapLocationBinding(Base, UUIDMixin, TimestampMixin, NovelMixin):
    """地点绑定 — 把 core_entities.entity_type=location 的实体绑到一个或多个六边形

    约束：
    - 同一地点在同一地图上最多一个 is_center=true 的中心点
      （DB 层用 PG 部分唯一索引保证；SQLite 测试由业务层校验）
    - 一个六边形可同时拥有地形、地点绑定、后续势力范围
    - 业务层校验 location_entity_id 的 entity_type=location 且 novel_id 匹配
    """

    __tablename__ = "map_location_bindings"
    __table_args__ = (
        # 防止同一地点重复绑定同一格
        Index(
            "uq_map_binding_map_entity_qr",
            "map_id",
            "location_entity_id",
            "hex_q",
            "hex_r",
            unique=True,
        ),
        # 注：PG 部分唯一索引（同一地点最多一个中心点）不在 ORM 声明。
        # 原因：SQLAlchemy 的 Index(unique=True, postgresql_where=...) 在非 PG dialect
        # 上仍会生成无 WHERE 的 unique index，破坏 SQLite 测试。
        # 改由业务层 MapLocationBindingService.clear_center 保证唯一性（已实现）。
        # 如需 DB 层强约束，在 Alembic 迁移里用 op.execute 原始 SQL 建 partial index。
        {"comment": "地点绑定"},
    )

    map_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("map_configs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属地图",
    )
    location_entity_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("core_entities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="绑定的地点实体（entity_type=location）",
    )
    hex_q: Mapped[int] = mapped_column(Integer, nullable=False, comment="绑定格 q")
    hex_r: Mapped[int] = mapped_column(Integer, nullable=False, comment="绑定格 r")
    is_center: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="是否为中心点（显示标签 + 下钻入口）",
    )
    label_override: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="标签覆盖（默认用实体名）"
    )
    style_override: Mapped[dict | None] = mapped_column(
        JSON, nullable=True, default=dict, comment="样式覆盖"
    )

    def __repr__(self) -> str:
        return (
            f"<MapLocationBinding map={self.map_id} "
            f"entity={self.location_entity_id} q={self.hex_q} r={self.hex_r} "
            f"center={self.is_center}>"
        )


# ============================================================
# MapMarker — 动态标记（P1 数据层预留，P0 不实现 service/API）
# ============================================================


class MapMarker(Base, UUIDMixin, TimestampMixin, NovelMixin):
    """动态标记 — P1 Scene 时间层使用

    marker_type:
    - character: 人物位置（按 Scene 显隐）
    - event: 事件发生地
    - item: 物品位置

    start_scene_id / end_scene_id 是稳定锚点；scene_index 是排序冗余。
    不建 FK 到 outline.scenes（PRD §7.2 跨模块不强耦合），由业务层校验。
    """

    __tablename__ = "map_markers"
    __table_args__ = (
        Index("ix_map_marker_map_scene", "map_id", "marker_type"),
        {"comment": "动态标记（P1 预留）"},
    )

    map_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("map_configs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属地图",
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("core_entities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="标记关联实体",
    )
    marker_type: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        comment="标记类型：character / event / item",
    )
    hex_q: Mapped[int] = mapped_column(Integer, nullable=False, comment="标记格 q")
    hex_r: Mapped[int] = mapped_column(Integer, nullable=False, comment="标记格 r")
    offset_x: Mapped[float] = mapped_column(
        Float, nullable=False, default=0, comment="标记 x 偏移（避免同格重叠）"
    )
    offset_y: Mapped[float] = mapped_column(
        Float, nullable=False, default=0, comment="标记 y 偏移"
    )
    label: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="标记标签"
    )
    style_json: Mapped[dict | None] = mapped_column(
        JSON, nullable=True, default=dict, comment="标记样式"
    )

    # Scene 时间层（P1）
    start_scene_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True, comment="起始 Scene（P1）"
    )
    start_scene_index: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="起始 Scene 序号（排序冗余）"
    )
    end_scene_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True, comment="结束 Scene（P1）"
    )
    end_scene_index: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="结束 Scene 序号"
    )
    visible: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, comment="是否可见"
    )

    def __repr__(self) -> str:
        return (
            f"<MapMarker map={self.map_id} type={self.marker_type} "
            f"q={self.hex_q} r={self.hex_r}>"
        )
