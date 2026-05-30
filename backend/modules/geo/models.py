"""
Geo ORM 模型

数据库表：
- geo_locations：地理地点扩展表（entity_id PK+FK → core_entities）
- geo_edges：地点之间的通行/关系边
- geo_eras：宏观历史时期
"""

from __future__ import annotations

import uuid

from sqlalchemy import Float, ForeignKey, JSON, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.base import Base, TimestampMixin


class GeoLocation(Base, TimestampMixin):
    """地理地点扩展表 — 仅存储地理特有字段，公共字段在 core_entities"""

    __tablename__ = "geo_locations"

    entity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("core_entities.id", ondelete="CASCADE"),
        primary_key=True,
        comment="地点 entity_id = core_entities.id",
    )
    novel_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    location_level: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        index=True,
        comment="地点层级：continent/country/region/city/district/landmark/building/room",
    )
    parent_location_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("core_entities.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="父地点的 entity_id（自引用，指向 core_entities）",
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
    content_json: Mapped[dict] = mapped_column(
        JSON(none_as_null=True),
        nullable=False,
        default=dict,
        comment="扩展信息，可包含 era_states 历史时期状态",
    )
    # ORM 关系
    core_entity: Mapped["CoreEntity"] = relationship(
        "CoreEntity", back_populates="geo_location",
        primaryjoin="foreign(GeoLocation.entity_id) == CoreEntity.id",
    )
    parent_location: Mapped["GeoLocation | None"] = relationship(
        "GeoLocation",
        primaryjoin="foreign(GeoLocation.parent_location_id) == remote(GeoLocation.entity_id)",
        remote_side="GeoLocation.entity_id",
        back_populates="child_locations",
        foreign_keys=[parent_location_id],
    )
    child_locations: Mapped[list["GeoLocation"]] = relationship(
        "GeoLocation",
        primaryjoin="GeoLocation.entity_id == foreign(GeoLocation.parent_location_id)",
        back_populates="parent_location",
        foreign_keys=[parent_location_id],
    )

    def __repr__(self) -> str:
        return (
            f"<GeoLocation entity_id={self.entity_id} level={self.location_level} "
            f"x={self.x} y={self.y}>"
        )


class GeoEdge(Base, TimestampMixin):
    """地理关系边 — 地点间的通行/方位关系"""

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
        ForeignKey("core_entities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="起点地点的 entity_id",
    )
    target_location_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("core_entities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="终点地点的 entity_id",
    )
    relation_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        index=True,
        comment="关系类型：road_to/river_to/inside/north_of等",
    )
    direction_label: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        comment="方向描述",
    )
    distance_label: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        comment="距离描述",
    )
    travel_time: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        comment="通行时间",
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
        comment="通行条件",
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
    """宏观历史时期"""

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
        comment="历史时期名称",
    )
    order_index: Mapped[int] = mapped_column(
        nullable=False,
        index=True,
        comment="时间顺序索引",
    )
    summary: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="时期概述",
    )
    start_event_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        nullable=True,
        comment="起始事件 ID",
    )
    end_event_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        nullable=True,
        comment="结束事件 ID",
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="canonical",
        index=True,
    )

    def __repr__(self) -> str:
        return (
            f"<GeoEra id={self.id} name={self.name!r} "
            f"order_index={self.order_index}>"
        )


# 延迟导入避免循环引用
from modules.world.models import CoreEntity  # noqa: E402, F401
