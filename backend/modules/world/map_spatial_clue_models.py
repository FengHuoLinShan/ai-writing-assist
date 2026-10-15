"""Author-reviewed spatial clue candidates from Evolution discovery."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.base import Base, NovelMixin, TimestampMixin, UUIDMixin, UUIDType
from modules.world.models.common import JSON


class MapSpatialClueRecord(Base, UUIDMixin, TimestampMixin, NovelMixin):
    """One immutable discovery proposal and its append-only author decision state."""

    __tablename__ = "map_spatial_clues"
    __table_args__ = (
        UniqueConstraint("novel_id", "id", name="uq_map_spatial_clues_novel_id"),
        CheckConstraint(
            "status IN ('pending_review', 'pending_verification', 'adopted', "
            "'rejected', 'superseded')",
            name="ck_map_spatial_clues_status",
        ),
        CheckConstraint(
            "source_content_mode IN ('canonical', 'working')",
            name="ck_map_spatial_clues_source_content_mode",
        ),
        CheckConstraint("scene_index >= 0", name="ck_map_spatial_clues_scene_index"),
        UniqueConstraint(
            "novel_id",
            "run_id",
            "attempt_id",
            "clue_key",
            name="uq_map_spatial_clues_attempt_key",
        ),
        ForeignKeyConstraint(
            ["novel_id", "merged_into_id"],
            ["map_spatial_clues.novel_id", "map_spatial_clues.id"],
            name="fk_map_spatial_clues_merge_same_novel",
        ),
        Index(
            "ix_map_spatial_clues_novel_status_scene",
            "novel_id",
            "status",
            "scene_index",
            "id",
        ),
        Index(
            "ix_map_spatial_clues_novel_scene",
            "novel_id",
            "scene_index",
            "id",
        ),
    )

    run_id: Mapped[str] = mapped_column(String(120), nullable=False)
    attempt_id: Mapped[str] = mapped_column(String(120), nullable=False)
    scene_id: Mapped[str] = mapped_column(String(128), nullable=False)
    scene_index: Mapped[int] = mapped_column(Integer, nullable=False)
    clue_key: Mapped[str] = mapped_column(String(64), nullable=False)
    source_manifest_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    method_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    source_content_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    source_binding: Mapped[dict] = mapped_column(JSON, nullable=False)
    clue_payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="pending_review", index=True
    )
    verification_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    merged_into_id: Mapped[uuid.UUID | None] = mapped_column(UUIDType, nullable=True)
    decision_action: Mapped[str | None] = mapped_column(String(16), nullable=True)
    decision_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    decided_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
