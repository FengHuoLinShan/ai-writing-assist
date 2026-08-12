"""ORM models for the author-reviewed AI map atlas."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.base import Base, NovelMixin, TimestampMixin, UUIDMixin, UUIDType


class MapAtlasRun(Base, UUIDMixin, TimestampMixin, NovelMixin):
    """One persisted atlas planning and image-generation run."""

    __tablename__ = "map_atlas_runs"
    __table_args__ = (
        CheckConstraint(
            "run_kind IN ('initial', 'update', 'rebuild', 'edit', 'regenerate')",
            name="ck_map_atlas_runs_kind",
        ),
        CheckConstraint(
            "status IN ('planning', 'generating', 'review_ready', 'partial', "
            "'paused', 'failed', 'completed')",
            name="ck_map_atlas_runs_status",
        ),
        Index("ix_map_atlas_runs_novel_created", "novel_id", "created_at"),
    )

    task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType,
        ForeignKey("async_tasks.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    run_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="planning", index=True
    )
    style_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    include_working_drafts: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    include_interiors: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    layout: Mapped[str] = mapped_column(
        String(16), nullable=False, default="landscape"
    )
    quality: Mapped[str] = mapped_column(
        String(16), nullable=False, default="standard"
    )
    page_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=20)
    planned_page_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    completed_page_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    stop_requested: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    context_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    context_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    source_manifest: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    atlas_plan: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    llm_execution_snapshot: Mapped[dict] = mapped_column(
        JSON, nullable=False, default=dict
    )
    image_execution_snapshot: Mapped[dict] = mapped_column(
        JSON, nullable=False, default=dict
    )
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class MapAtlasNode(Base, UUIDMixin, TimestampMixin, NovelMixin):
    """Stable hierarchy node shared by atlas runs."""

    __tablename__ = "map_atlas_nodes"
    __table_args__ = (
        UniqueConstraint(
            "novel_id", "semantic_key", name="uq_map_atlas_nodes_novel_semantic"
        ),
        CheckConstraint(
            "level IN ('cover', 'world', 'region', 'city', 'district', "
            "'street', 'interior')",
            name="ck_map_atlas_nodes_level",
        ),
        CheckConstraint(
            "status IN ('provisional', 'adopted')",
            name="ck_map_atlas_nodes_status",
        ),
        Index(
            "ix_map_atlas_nodes_novel_parent_order",
            "novel_id",
            "parent_id",
            "sort_order",
        ),
    )

    created_by_run_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("map_atlas_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType,
        ForeignKey("map_atlas_nodes.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    location_entity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType,
        ForeignKey("core_entities.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    semantic_key: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    level: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="provisional", index=True
    )
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class MapAtlasPage(Base, UUIDMixin, TimestampMixin, NovelMixin):
    """One immutable generated image and its review state."""

    __tablename__ = "map_atlas_pages"
    __table_args__ = (
        CheckConstraint(
            "generation_status IN ('prepared', 'provider_in_flight', 'uploaded', "
            "'review_ready', 'failed', 'retry_requires_confirmation')",
            name="ck_map_atlas_pages_generation_status",
        ),
        CheckConstraint(
            "review_status IN ('candidate', 'adopted', 'rejected', 'deprecated')",
            name="ck_map_atlas_pages_review_status",
        ),
        Index(
            "ix_map_atlas_pages_novel_node_review",
            "novel_id",
            "node_id",
            "review_status",
        ),
        Index(
            "ix_map_atlas_pages_run_order", "run_id", "sort_order", "created_at"
        ),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("map_atlas_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    node_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("map_atlas_nodes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    derived_from_page_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType,
        ForeignKey("map_atlas_pages.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    generation_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="prepared", index=True
    )
    review_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="candidate", index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    visual_brief: Mapped[str] = mapped_column(Text, nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    edit_instruction: Mapped[str | None] = mapped_column(Text, nullable=True)
    node_proposal: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    evidence: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    source_manifest: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    reference_page_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    object_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    mask_object_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    media_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    byte_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    provider: Mapped[str] = mapped_column(
        String(32), nullable=False, default="openai"
    )
    model: Mapped[str] = mapped_column(
        String(64), nullable=False, default="gpt-image-2"
    )
    provider_request_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    adopted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    rejected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    deprecated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class MapAtlasAnnotation(Base, UUIDMixin, TimestampMixin, NovelMixin):
    """Editable text overlay and optional drill-down target for one page."""

    __tablename__ = "map_atlas_annotations"
    __table_args__ = (
        CheckConstraint(
            "position_x >= 0 AND position_x <= 1 AND "
            "position_y >= 0 AND position_y <= 1",
            name="ck_map_atlas_annotations_position",
        ),
        Index(
            "ix_map_atlas_annotations_page_order", "page_id", "sort_order"
        ),
    )

    page_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("map_atlas_pages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target_node_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType,
        ForeignKey("map_atlas_nodes.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    position_x: Mapped[float] = mapped_column(Float, nullable=False)
    position_y: Mapped[float] = mapped_column(Float, nullable=False)
    source_ref: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
