"""
Geo ORM 模型

对应数据库表：
- geo_locations：地理地点（地点层级、相对坐标、地形气候）
- geo_edges：地点之间的通行/关系边
- geo_eras：宏观历史时期
"""

from __future__ import annotations

import uuid

from sqlalchemy import JSON, Float, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.base import Base, TimestampMixin


class GeoLocation(Base, TimestampMixin):
    """地理地点 — 小说世界的空间位置

    地点本体属于 world_entities（entity_type = location），
    此表仅提供地理扩展信息：层级、坐标、地形气候等。

    支持父子层级（self-referential FK via parent_location_id）。
    """

    __tablename__ = "geo_locations"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    novel_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    world_entity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("world_entities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="对应的世界对象 ID（entity_type = location）",
    )
    location_level: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        index=True,
        comment="地点层级：continent/country/region/city/district/landmark/building/room",
    )
    parent_location_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("geo_locations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="父地点 ID（自引用外键，构建地点树）",
    )
    x: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        comment="简易相对坐标 X",
    )
    y: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        comment="简易相对坐标 Y",
    )
    position_label: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
        comment="方位标签，如「王国北部」「大陆东岸」",
    )
    scale_label: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        comment="规模标签，如「数十公里」「步行一日」",
    )
    terrain: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        comment="地形（平原/山地/沙漠/森林/水域/城市）",
    )
    climate: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        comment="气候（温带/热带/极地/干旱/湿润）",
    )
    access_level: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="normal",
        comment="访问级别：normal/restricted/dangerous/forbidden/secret",
    )
    summary: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="地点概述",
    )
    content_json: Mapped[dict] = mapped_column(
        JSON(none_as_null=True),
        nullable=False,
        default=dict,
        comment="扩展信息，可包含 era_states 历史时期状态",
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="canonical",
        index=True,
        comment="状态：draft/candidate/canonical/deprecated",
    )

    # ORM 关系
    parent_location: Mapped[GeoLocation | None] = relationship(
        "GeoLocation",
        remote_side="GeoLocation.id",
        back_populates="child_locations",
        foreign_keys=[parent_location_id],
    )
    child_locations: Mapped[list[GeoLocation]] = relationship(
        "GeoLocation",
        back_populates="parent_location",
        foreign_keys=[parent_location_id],
    )

    def __repr__(self) -> str:
        return (
            f"<GeoLocation id={self.id} level={self.location_level} "
            f"x={self.x} y={self.y}>"
        )


class GeoEdge(Base, TimestampMixin):
    """地理关系边 — 地点间的通行/方位关系

    关系类型包括：道路连接、水路连接、位于内部、方向关系、
    附近、隐藏通道、阻断路径、接壤等。
    """

    __tablename__ = "geo_edges"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    novel_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_location_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("geo_locations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="起点地点 ID",
    )
    target_location_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("geo_locations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="终点地点 ID",
    )
    relation_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        index=True,
        comment="关系类型：road_to/river_to/inside/north_of/south_of/"
        "east_of/west_of/near/hidden_path/blocked_path/borders",
    )
    direction_label: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        comment="方向描述，如「沿河而下」「翻越山脉」",
    )
    distance_label: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        comment="距离描述，如「三日路程」「五百里」",
    )
    travel_time: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        comment="通行时间，如「步行三日」「快马一日」",
    )
    difficulty: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
        comment="通行难度：easy/normal/hard/very_hard/impassable",
    )
    visibility: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="public",
        comment="可见性：public/restricted/secret",
    )
    condition_text: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="通行条件，如「需通关文牒」「冬季封路」",
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="canonical",
        index=True,
    )

    def __repr__(self) -> str:
        return (
            f"<GeoEdge id={self.id} "
            f"{self.source_location_id} --[{self.relation_type}]--> "
            f"{self.target_location_id}>"
        )


class GeoEra(Base, TimestampMixin):
    """宏观历史时期 — 小说世界的历史阶段

    用于表示不同历史时期下地理和社会状态的变化，
    如王朝兴衰、迁都、战争时期、和平时期等。

    start_event_id / end_event_id 可关联 timeline_events。
    """

    __tablename__ = "geo_eras"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    novel_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        comment="历史时期名称，如「古王朝时期」「焚城前」「主线开始时」",
    )
    order_index: Mapped[int] = mapped_column(
        nullable=False,
        index=True,
        comment="时间顺序索引（小→大表示从古至今）",
    )
    summary: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="时期概述",
    )
    start_event_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        nullable=True,
        comment="起始事件 ID（关联 timeline_events）",
    )
    end_event_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        nullable=True,
        comment="结束事件 ID（关联 timeline_events）",
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="canonical",
        index=True,
    )

    def __repr__(self) -> str:
        return f"<GeoEra id={self.id} name={self.name!r} order_index={self.order_index}>"
