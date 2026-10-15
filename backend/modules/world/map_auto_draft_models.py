"""Durable progress for resumable deterministic spatial draft builds."""

from __future__ import annotations

from sqlalchemy import CheckConstraint, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from core.base import Base, NovelMixin, TimestampMixin, UUIDMixin
from modules.world.models.common import JSON


class MapAutoDraftBatchRecord(Base, UUIDMixin, TimestampMixin, NovelMixin):
    """A frozen aggregate build and its committed shard cursor/results."""

    __tablename__ = "map_auto_draft_batches"
    __table_args__ = (
        UniqueConstraint(
            "novel_id",
            "run_id",
            "build_key",
            "through_scene_id",
            name="uq_map_auto_draft_batch_identity",
        ),
        CheckConstraint(
            "status IN ('running', 'completed', 'stale')",
            name="ck_map_auto_draft_batches_status",
        ),
        CheckConstraint(
            "through_scene_index >= 0 AND cursor >= 0",
            name="ck_map_auto_draft_batches_progress",
        ),
        Index(
            "ix_map_auto_draft_batches_novel_status_created",
            "novel_id",
            "status",
            "created_at",
        ),
    )

    run_id: Mapped[str] = mapped_column(String(120), nullable=False)
    build_key: Mapped[str] = mapped_column(String(120), nullable=False)
    through_scene_id: Mapped[str] = mapped_column(String(128), nullable=False)
    through_scene_index: Mapped[int] = mapped_column(Integer, nullable=False)
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    method_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="running")
    cursor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    plan_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    result_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    tray_items: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    conflicts: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    stale_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


__all__ = ["MapAutoDraftBatchRecord"]
