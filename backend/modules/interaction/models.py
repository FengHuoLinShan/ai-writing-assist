"""ORM models for isolated RP interaction journeys."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.base import Base, TimestampMixin, UUIDMixin, UUIDType


class InteractionSourceRevision(Base, UUIDMixin, TimestampMixin):
    """Immutable same-owner author-project snapshot used by RP journeys."""

    __tablename__ = "interaction_source_revisions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('organizing', 'needs_confirmation', 'ready', 'failed')",
            name="ck_interaction_source_revision_status",
        ),
        CheckConstraint(
            "status != 'ready' OR fingerprint IS NOT NULL",
            name="ck_interaction_source_ready_fingerprint",
        ),
        UniqueConstraint(
            "source_novel_id",
            "version_number",
            name="uq_interaction_source_revision_version",
        ),
        UniqueConstraint(
            "source_novel_id",
            "manifest_hash",
            name="uq_interaction_source_revision_manifest",
        ),
        Index(
            "ix_interaction_source_revision_owner_status",
            "owner_id",
            "status",
            "created_at",
        ),
    )

    source_novel_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    parent_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType,
        ForeignKey("interaction_source_revisions.id", ondelete="SET NULL"),
        nullable=True,
    )
    import_record_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType,
        ForeignKey("import_records.id", ondelete="SET NULL"),
        nullable=True,
    )
    workflow_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType,
        ForeignKey("import_workflow_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType,
        ForeignKey("async_tasks.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="organizing", index=True
    )
    source_manifest: Mapped[list[dict]] = mapped_column(
        JSON, nullable=False, default=list
    )
    anchor_manifest: Mapped[list[dict]] = mapped_column(
        JSON, nullable=False, default=list
    )
    reference_manifest: Mapped[list[dict]] = mapped_column(
        JSON, nullable=False, default=list
    )
    ambiguities: Mapped[list[dict]] = mapped_column(JSON, nullable=False, default=list)
    resolutions: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    readiness_summary: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    manifest_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ready_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class InteractionJourney(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "interaction_journeys"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'archived')",
            name="ck_interaction_journey_status",
        ),
        CheckConstraint(
            "title_source IN ('fallback', 'model', 'manual')",
            name="ck_interaction_journey_title_source",
        ),
        Index(
            "ix_interaction_journey_owner_status_activity",
            "owner_id",
            "status",
            "latest_activity_at",
        ),
    )

    novel_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    title_source: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="fallback",
    )
    opening_text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="active",
    )
    see_sea_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    action_options_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )
    setup_clarification_used: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    see_sea_last_heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    selected_leaf_node_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType,
        nullable=True,
    )
    selection_epoch: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    overview_head_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType,
        nullable=True,
    )
    overview_epoch: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    overview_failure: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    source_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType,
        ForeignKey("interaction_source_revisions.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    source_anchor_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_anchor: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    player_identity: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    reference_policy: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    source_context_epoch: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latest_activity_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )


class InteractionMessageNode(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "interaction_message_nodes"
    __table_args__ = (
        CheckConstraint(
            "role IN ('user', 'assistant')",
            name="ck_interaction_message_role",
        ),
        CheckConstraint(
            "message_kind IN ('setup', 'story')",
            name="ck_interaction_message_kind",
        ),
        CheckConstraint(
            "completion_state IN ('complete', 'partial')",
            name="ck_interaction_message_completion",
        ),
        Index(
            "ix_interaction_message_journey_created",
            "journey_id",
            "created_at",
            "id",
        ),
        Index(
            "ix_interaction_message_parent_created",
            "journey_id",
            "parent_node_id",
            "created_at",
        ),
    )

    novel_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    journey_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("interaction_journeys.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    parent_node_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType,
        ForeignKey("interaction_message_nodes.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    message_kind: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="story",
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    completion_state: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="complete",
    )
    end_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    branch_hint: Mapped[str | None] = mapped_column(String(40), nullable=True)
    story_ended: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    action_suggestions: Mapped[list[dict]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    token_estimate: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    origin_attempt_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType,
        nullable=True,
        unique=True,
    )


class InteractionBranchSelection(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "interaction_branch_selections"
    __table_args__ = (
        UniqueConstraint(
            "journey_id",
            "parent_key",
            name="uq_interaction_selected_child",
        ),
    )

    novel_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    journey_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("interaction_journeys.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    parent_node_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType,
        ForeignKey("interaction_message_nodes.id", ondelete="CASCADE"),
        nullable=True,
    )
    parent_key: Mapped[str] = mapped_column(String(36), nullable=False)
    selected_child_node_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("interaction_message_nodes.id", ondelete="CASCADE"),
        nullable=False,
    )


class InteractionGenerationAttempt(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "interaction_generation_attempts"
    __table_args__ = (
        CheckConstraint(
            "status IN "
            "('pending', 'preparing_context', 'running', "
            "'awaiting_continue', 'completed', "
            "'failed', 'cancelled', 'stopped')",
            name="ck_interaction_attempt_status",
        ),
        UniqueConstraint(
            "owner_id",
            "idempotency_key",
            name="uq_interaction_attempt_idempotency",
        ),
        Index(
            "ix_interaction_attempt_owner_active",
            "owner_id",
            "status",
        ),
        Index(
            "ix_interaction_attempt_journey_created",
            "journey_id",
            "created_at",
        ),
    )

    novel_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    journey_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("interaction_journeys.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    response_to_node_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("interaction_message_nodes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType,
        nullable=True,
        unique=True,
    )
    result_node_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType,
        nullable=True,
        unique=True,
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default="pending",
    )
    started_selection_epoch: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    visible_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    visible_offset: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    metadata_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    finish_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_kind: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(255), nullable=True)
    llm_execution_snapshot: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    context_path_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    context_node_ids: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    reference_node_ids: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    source_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType,
        ForeignKey("interaction_source_revisions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    started_source_context_epoch: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    source_context_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType,
        ForeignKey("context_snapshots.id", ondelete="SET NULL"),
        nullable=True,
    )
    source_context_fingerprint: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    reference_trace: Mapped[list[dict]] = mapped_column(
        JSON, nullable=False, default=list
    )
    continuation_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    usage: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    last_checkpoint_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class InteractionSummarySegment(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "interaction_summary_segments"
    __table_args__ = (
        UniqueConstraint(
            "journey_id",
            "path_hash",
            "end_node_id",
            name="uq_interaction_summary_path_end",
        ),
    )

    novel_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    journey_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("interaction_journeys.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    start_node_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False)
    end_node_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False)
    path_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    based_on_overview_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType,
        nullable=True,
    )
    based_on_checkpoint_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType,
        nullable=True,
    )
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    producer: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class InteractionOverviewRevision(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "interaction_overview_revisions"
    __table_args__ = (
        CheckConstraint(
            "source IN ('automatic', 'manual')",
            name="ck_interaction_overview_source",
        ),
        Index(
            "ix_interaction_overview_journey_created",
            "journey_id",
            "created_at",
        ),
    )

    novel_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    journey_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("interaction_journeys.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    anchor_node_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False)
    path_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    coverage_anchor_node_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType,
        nullable=True,
    )
    coverage_path_hash: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    sections: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    based_on_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType,
        nullable=True,
    )
    started_overview_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    promoted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    producer: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class InteractionAccountPreference(Base, UUIDMixin, TimestampMixin):
    """Account-scoped RP ergonomics that must follow the user across devices."""

    __tablename__ = "interaction_account_preferences"

    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    see_sea_notice_acknowledged: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
