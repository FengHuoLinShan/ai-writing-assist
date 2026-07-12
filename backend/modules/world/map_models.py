"""
World 动态地图 ORM 模型 — PRD docs/PRD-动态地图功能.md

地图基础表 + 世界动态 P0 事实底座：
- map_configs: 地图配置（世界地图 / 城市 / 区域 / 地下城，自引用树）
- map_tiles: 六边形地形网格（轴向坐标 q,r）
- map_location_bindings: 地点绑定（core_entities.entity_type=location → hex）
- map_markers: 动态标记（P1 预留，character/event/item，按 Scene 时间层显隐）
- map_observations: 地图观察事实候选（来源证据、置信度、审查状态）
- map_facts: 已确认的时间化地图事实

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
# MapLocationLayout — 地点布局节点
# ============================================================


class MapLocationLayout(Base, UUIDMixin, TimestampMixin, NovelMixin):
    """地点布局节点。

    与 MapLocationBinding 分离：binding 表达地点绑定到哪些 hex，layout 表达
    快速创建/拖拽后的节点中心、占用半径和锁定状态。
    """

    __tablename__ = "map_location_layouts"
    __table_args__ = (
        Index(
            "uq_map_location_layout_map_entity",
            "map_id",
            "location_entity_id",
            unique=True,
        ),
        {"comment": "地图地点布局节点"},
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
        comment="地点实体",
    )
    center_hex_q: Mapped[int] = mapped_column(Integer, nullable=False)
    center_hex_r: Mapped[int] = mapped_column(Integer, nullable=False)
    occupy_radius: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    layout_source: Mapped[str] = mapped_column(
        String(32), nullable=False, default="quick_create"
    )
    layout_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    sync_geo_setting: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    meta: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=dict)


# ============================================================
# MapTerrain — 手绘地形图层/区域/patch/绑定
# ============================================================


class MapTerrainLayer(Base, UUIDMixin, TimestampMixin, NovelMixin):
    """手绘地形图层。一个图层对应一种素材/语义类型。"""

    __tablename__ = "map_terrain_layers"
    __table_args__ = ({"comment": "地图手绘地形图层"},)

    map_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("map_configs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    terrain_asset_key: Mapped[str] = mapped_column(String(64), nullable=False)
    opacity: Mapped[float] = mapped_column(Float, nullable=False, default=0.45)
    z_index: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    visible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    meta: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=dict)


class MapTerrainRegion(Base, UUIDMixin, TimestampMixin, NovelMixin):
    """一次连续手绘或一个可命名地形区域。"""

    __tablename__ = "map_terrain_regions"
    __table_args__ = ({"comment": "地图手绘地形区域"},)

    map_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("map_configs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    layer_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("map_terrain_layers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    region_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="active"
    )
    meta: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=dict)


class MapTerrainPatch(Base, UUIDMixin, TimestampMixin, NovelMixin):
    """地形区域覆盖的离散 hex patch。"""

    __tablename__ = "map_terrain_patches"
    __table_args__ = (
        Index(
            "uq_map_terrain_patch_map_layer_region_qr",
            "map_id",
            "layer_id",
            "region_id",
            "hex_q",
            "hex_r",
            unique=True,
        ),
        {"comment": "地图手绘地形 patch"},
    )

    map_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("map_configs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    layer_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("map_terrain_layers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    region_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("map_terrain_regions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    hex_q: Mapped[int] = mapped_column(Integer, nullable=False)
    hex_r: Mapped[int] = mapped_column(Integer, nullable=False)
    strength: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    brush_source: Mapped[str] = mapped_column(String(32), nullable=False, default="brush")


class MapTerrainBinding(Base, UUIDMixin, TimestampMixin, NovelMixin):
    """手绘地形区域与地点实体的用户确认绑定。"""

    __tablename__ = "map_terrain_bindings"
    __table_args__ = (
        Index(
            "uq_map_terrain_binding_region_location_type",
            "region_id",
            "location_entity_id",
            "binding_type",
            unique=True,
        ),
        {"comment": "地图手绘地形绑定"},
    )

    map_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("map_configs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    region_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("map_terrain_regions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    location_entity_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("core_entities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    binding_type: Mapped[str] = mapped_column(String(32), nullable=False)
    review_state: Mapped[str] = mapped_column(
        String(32), nullable=False, default="confirmed"
    )
    source: Mapped[str] = mapped_column(
        String(64), nullable=False, default="user_confirmed"
    )
    meta: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=dict)


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


# ============================================================
# MapTerritoryTile — 势力范围（P2）
# ============================================================


class MapTerritoryTile(Base, UUIDMixin, TimestampMixin, NovelMixin):
    """势力范围格 — 组织控制区域

    与地点绑定、标记可叠加；地点颜色和标签优先于势力半透明覆盖。
    faction_entity_id 对应 core_entities.entity_type = "organization"。
    """

    __tablename__ = "map_territory_tiles"
    __table_args__ = (
        Index(
            "uq_map_territory_map_faction_qr",
            "map_id",
            "faction_entity_id",
            "hex_q",
            "hex_r",
            unique=True,
        ),
        {"comment": "势力范围（P2）"},
    )

    map_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("map_configs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属地图",
    )
    faction_entity_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("core_entities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="组织实体（entity_type=organization）",
    )
    hex_q: Mapped[int] = mapped_column(Integer, nullable=False, comment="范围格 q")
    hex_r: Mapped[int] = mapped_column(Integer, nullable=False, comment="范围格 r")
    style_override: Mapped[dict | None] = mapped_column(
        JSON, nullable=True, default=dict, comment="样式覆盖（颜色/透明度）"
    )

    def __repr__(self) -> str:
        return (
            f"<MapTerritoryTile map={self.map_id} "
            f"faction={self.faction_entity_id} q={self.hex_q} r={self.hex_r}>"
        )


# ============================================================
# MapObservation — 地图观察事实候选（世界动态 P0）
# ============================================================


class MapObservation(Base, UUIDMixin, TimestampMixin, NovelMixin):
    """地图观察事实。

    Observation 是 deep import、即时分析或人工编辑提供的证据层。它默认
    进入 candidate review_state，不直接污染正式地图事实；用户确认后再生成
    MapFact。
    """

    __tablename__ = "map_observations"
    __table_args__ = (
        Index("ix_map_observation_map_review", "map_id", "review_state"),
        Index("ix_map_observation_target", "target_entity_id", "dynamic_type"),
        Index("ix_map_observation_scene", "scene_id", "scene_index"),
        {"comment": "地图观察事实候选"},
    )

    map_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("map_configs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="关联地图；未解析空间时可为空",
    )
    target_entity_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("core_entities.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="目标实体；候选未消歧时可为空",
    )
    target_entity_type: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="目标实体类型文案"
    )
    target_name: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="目标对象名称（作者界面优先显示）"
    )
    dynamic_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
        comment="动态类型：location/status/boundary/crisis/resource/semantic/delta_event",
    )
    time_anchor: Mapped[dict | None] = mapped_column(
        JSON, nullable=True, default=dict, comment="章节/Scene/时间范围锚点"
    )
    spatial_anchor: Mapped[dict | None] = mapped_column(
        JSON, nullable=True, default=dict, comment="地图/hex/地点/文本空间锚点"
    )
    value_json: Mapped[dict | None] = mapped_column(
        JSON, nullable=True, default=dict, comment="观察到的状态或候选值"
    )
    confidence: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.5, comment="来源置信度 0~1"
    )
    review_state: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="candidate",
        index=True,
        comment="candidate / confirmed / ignored / conflicted",
    )
    source_ref: Mapped[dict | None] = mapped_column(
        JSON, nullable=True, default=dict, comment="来源引用：snapshot/delta/source ids"
    )
    evidence_text: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="可读来源证据摘要"
    )
    scene_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True, index=True, comment="来源 Scene ID"
    )
    scene_index: Mapped[int | None] = mapped_column(
        Integer, nullable=True, index=True, comment="来源 Scene 序号"
    )
    source_chapter_index: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="来源章节序号"
    )

    def __repr__(self) -> str:
        return (
            f"<MapObservation type={self.dynamic_type} target={self.target_name!r} "
            f"state={self.review_state}>"
        )


# ============================================================
# MapFact — 已确认时间化地图事实（世界动态 P0）
# ============================================================


class MapFact(Base, UUIDMixin, TimestampMixin, NovelMixin):
    """已确认地图事实。

    Fact 是 Observation 经用户确认或可信流水线确认后的正式地图动态底座。
    """

    __tablename__ = "map_facts"
    __table_args__ = (
        Index("ix_map_fact_map_status", "map_id", "fact_status"),
        Index("ix_map_fact_target", "target_entity_id", "dynamic_type"),
        Index("ix_map_fact_scene", "scene_id", "scene_index"),
        {"comment": "已确认时间化地图事实"},
    )

    observation_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("map_observations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="来源观察事实",
    )
    map_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("map_configs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="关联地图",
    )
    target_entity_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("core_entities.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="目标实体",
    )
    target_entity_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    target_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    dynamic_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    time_anchor: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=dict)
    spatial_anchor: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=dict)
    value_json: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=dict)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    fact_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="confirmed",
        index=True,
        comment="confirmed / rolled_back / deprecated",
    )
    source_ref: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=dict)
    evidence_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    scene_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    scene_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_chapter_index: Mapped[int | None] = mapped_column(Integer, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<MapFact type={self.dynamic_type} target={self.target_name!r} "
            f"status={self.fact_status}>"
        )
