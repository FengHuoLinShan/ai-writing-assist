"""Durable candidate world-progression roots, branches, and immutable steps."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
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


class StoryWorldProgressionRoot(Base, UUIDMixin, TimestampMixin, NovelMixin):
    __tablename__ = "story_world_progression_roots"
    __table_args__ = (
        UniqueConstraint("novel_id", "id", name="uq_story_world_progression_root_novel"),
        Index(
            "ix_story_world_progression_root_scene", "novel_id", "scene_id", "created_at"
        ),
    )

    scene_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    source_snapshot_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    llm_execution_snapshot_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    run_envelope_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    context_confirmation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    current_task_id: Mapped[uuid.UUID | None] = mapped_column(UUIDType, nullable=True)


class StoryWorldProgressionBranch(Base, UUIDMixin, TimestampMixin, NovelMixin):
    __tablename__ = "story_world_progression_branches"
    __table_args__ = (
        UniqueConstraint(
            "novel_id", "id", name="uq_story_world_progression_branch_novel"
        ),
        ForeignKeyConstraint(
            ["novel_id", "root_id"],
            [
                "story_world_progression_roots.novel_id",
                "story_world_progression_roots.id",
            ],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["novel_id", "parent_step_id"],
            [
                "story_world_progression_steps.novel_id",
                "story_world_progression_steps.id",
            ],
            name="fk_story_world_progression_branch_parent_step",
            use_alter=True,
        ),
        Index(
            "ix_story_world_progression_branch_root", "novel_id", "root_id", "created_at"
        ),
    )

    root_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False)
    parent_step_id: Mapped[uuid.UUID | None] = mapped_column(UUIDType, nullable=True)
    branch_kind: Mapped[str] = mapped_column(String(24), nullable=False, default="start")
    basis_choice: Mapped[str] = mapped_column(
        String(16), nullable=False, default="current"
    )
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    source_snapshot_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    pending_step_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    stop_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    name: Mapped[str | None] = mapped_column(String(180), nullable=True)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    starred: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    restore_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    current_task_id: Mapped[uuid.UUID | None] = mapped_column(UUIDType, nullable=True)


class StoryWorldProgressionStep(Base, UUIDMixin, TimestampMixin, NovelMixin):
    __tablename__ = "story_world_progression_steps"
    __table_args__ = (
        UniqueConstraint("novel_id", "id", name="uq_story_world_progression_step_novel"),
        UniqueConstraint(
            "novel_id",
            "branch_id",
            "step_number",
            name="uq_story_world_progression_step_number",
        ),
        ForeignKeyConstraint(
            ["novel_id", "root_id"],
            [
                "story_world_progression_roots.novel_id",
                "story_world_progression_roots.id",
            ],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["novel_id", "branch_id"],
            [
                "story_world_progression_branches.novel_id",
                "story_world_progression_branches.id",
            ],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["novel_id", "parent_step_id"],
            [
                "story_world_progression_steps.novel_id",
                "story_world_progression_steps.id",
            ],
        ),
        Index(
            "ix_story_world_progression_step_branch",
            "novel_id",
            "branch_id",
            "step_number",
        ),
    )

    root_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False)
    branch_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False)
    parent_step_id: Mapped[uuid.UUID | None] = mapped_column(UUIDType, nullable=True)
    step_number: Mapped[int] = mapped_column(Integer, nullable=False)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    output_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    input_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    result_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    state_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    metrics_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    basis_changed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class StoryWorldProgressionAuthorization(Base, UUIDMixin, TimestampMixin, NovelMixin):
    __tablename__ = "story_world_progression_authorizations"
    __table_args__ = (
        UniqueConstraint(
            "novel_id", name="uq_story_world_progression_authorization_novel"
        ),
        ForeignKeyConstraint(
            ["novel_id", "root_id"],
            [
                "story_world_progression_roots.novel_id",
                "story_world_progression_roots.id",
            ],
        ),
        ForeignKeyConstraint(
            ["novel_id", "branch_id"],
            [
                "story_world_progression_branches.novel_id",
                "story_world_progression_branches.id",
            ],
        ),
    )

    root_id: Mapped[uuid.UUID | None] = mapped_column(UUIDType, nullable=True)
    branch_id: Mapped[uuid.UUID | None] = mapped_column(UUIDType, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    participant_ids_json: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list
    )
    every_new_chapters: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    last_seen_chapter: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    counted_read_chapters_json: Mapped[list[int]] = mapped_column(
        JSON, nullable=False, default=list
    )
    last_triggered_read_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    read_count_initialized: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    context_confirmation_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )
    trigger_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
