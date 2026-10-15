"""Persisted Story-layer cards and Scene script assets.

The Story module owns author-editable projections used by the Scene workflow.
Canonical characters and Scenes remain owned by ``world`` and ``outline``;
their identifiers are deliberately weak references here and are validated at
the facade/service boundary.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.base import Base, NovelMixin, StatusMixin, TimestampMixin, UUIDMixin, UUIDType


class CharacterCard(Base, UUIDMixin, TimestampMixin, StatusMixin, NovelMixin):
    """One current Story projection for one canonical World character."""

    __tablename__ = "story_character_cards"
    __table_args__ = (
        UniqueConstraint(
            "novel_id",
            "scene_id",
            "character_id",
            name="uq_story_character_card_novel_character",
        ),
        UniqueConstraint("id", "novel_id", name="uq_story_character_card_id_novel"),
        ForeignKeyConstraint(
            ["current_revision_id", "novel_id"],
            [
                "story_character_card_revisions.id",
                "story_character_card_revisions.novel_id",
            ],
            name="fk_story_character_card_current_novel",
            use_alter=True,
        ),
        Index(
            "ix_story_character_cards_novel_status",
            "novel_id",
            "status",
        ),
        {"comment": "Story layer character card head"},
    )

    # This points to world.characters.entity_id, but is intentionally not a
    # cross-module FK: the world facade is the stable validation seam.
    scene_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    character_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    current_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType,
        nullable=True,
    )
    current_version_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    stale: Mapped[bool] = mapped_column(
        nullable=False,
        default=False,
        comment="Whether the current card must be refreshed before execution",
    )
    stale_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)


class CharacterCardRevision(Base, UUIDMixin, TimestampMixin, StatusMixin, NovelMixin):
    """Immutable versioned payload for a Story character card."""

    __tablename__ = "story_character_card_revisions"
    __table_args__ = (
        UniqueConstraint(
            "novel_id",
            "card_id",
            "version_number",
            name="uq_story_character_card_revision_version",
        ),
        Index(
            "ix_story_character_card_revisions_novel_card",
            "novel_id",
            "card_id",
            "version_number",
        ),
        UniqueConstraint(
            "id",
            "novel_id",
            name="uq_story_character_card_revision_id_novel",
        ),
        ForeignKeyConstraint(
            ["card_id", "novel_id"],
            ["story_character_cards.id", "story_character_cards.novel_id"],
            name="fk_story_character_card_revision_card_novel",
            ondelete="CASCADE",
        ),
        {"comment": "Immutable Story character card revision"},
    )

    card_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        nullable=False,
        index=True,
    )
    scene_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    character_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="manual")
    authorization_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_manifest_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    source_task_id: Mapped[uuid.UUID | None] = mapped_column(UUIDType, nullable=True)
    context_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(UUIDType, nullable=True)
    base_revision_id: Mapped[uuid.UUID | None] = mapped_column(UUIDType, nullable=True)
    restored_from_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType,
        nullable=True,
    )


class SceneScriptFile(Base, UUIDMixin, TimestampMixin, StatusMixin, NovelMixin):
    """One named, multi-file script slot for one Outline Scene."""

    __tablename__ = "story_scene_script_files"
    __table_args__ = (
        UniqueConstraint(
            "novel_id",
            "scene_id",
            "file_key",
            name="uq_story_scene_script_file_novel_scene_key",
        ),
        UniqueConstraint("id", "novel_id", name="uq_story_scene_script_file_id_novel"),
        ForeignKeyConstraint(
            ["current_revision_id", "novel_id"],
            ["story_scene_script_revisions.id", "story_scene_script_revisions.novel_id"],
            name="fk_story_scene_script_file_current_novel",
            use_alter=True,
        ),
        ForeignKeyConstraint(
            ["adopted_revision_id", "novel_id"],
            ["story_scene_script_revisions.id", "story_scene_script_revisions.novel_id"],
            name="fk_story_scene_script_file_adopted_novel",
            use_alter=True,
        ),
        Index(
            "ix_story_scene_script_file_novel_scene",
            "novel_id",
            "scene_id",
        ),
        {"comment": "Named Scene script file head"},
    )

    # Outline owns the Scene row; this module uses the outline facade to check
    # that the ID belongs to this novel before reading or writing.
    scene_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    file_key: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    current_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType,
        nullable=True,
    )
    adopted_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType,
        nullable=True,
    )
    adopted_version_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    current_version_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )


class SceneScriptRevision(Base, UUIDMixin, TimestampMixin, StatusMixin, NovelMixin):
    """Immutable revision for a named Scene script file."""

    __tablename__ = "story_scene_script_revisions"
    __table_args__ = (
        UniqueConstraint(
            "novel_id",
            "file_id",
            "version_number",
            name="uq_story_scene_script_revision_version",
        ),
        Index(
            "ix_story_scene_script_revision_novel_file",
            "novel_id",
            "file_id",
            "version_number",
        ),
        UniqueConstraint(
            "id",
            "novel_id",
            name="uq_story_scene_script_revision_id_novel",
        ),
        ForeignKeyConstraint(
            ["file_id", "novel_id"],
            ["story_scene_script_files.id", "story_scene_script_files.novel_id"],
            name="fk_story_scene_script_revision_file_novel",
            ondelete="CASCADE",
        ),
        {"comment": "Immutable Scene script file revision"},
    )

    file_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        nullable=False,
        index=True,
    )
    scene_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    file_key: Mapped[str] = mapped_column(String(64), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_json: Mapped[dict[str, Any] | list[Any] | None] = mapped_column(
        JSON,
        nullable=True,
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="manual")
    authorization_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    provenance_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    source_task_id: Mapped[uuid.UUID | None] = mapped_column(UUIDType, nullable=True)
    context_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(UUIDType, nullable=True)
    base_revision_id: Mapped[uuid.UUID | None] = mapped_column(UUIDType, nullable=True)


class StorySimulationRun(Base, UUIDMixin, TimestampMixin, NovelMixin):
    """A frozen, author-owned rehearsal; it never becomes story truth by itself."""

    __tablename__ = "story_simulation_runs"
    __table_args__ = (
        UniqueConstraint("novel_id", "id", name="uq_story_simulation_run_novel"),
        ForeignKeyConstraint(
            ["novel_id", "parent_id"],
            ["story_simulation_runs.novel_id", "story_simulation_runs.id"],
        ),
    )
    scene_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(UUIDType, nullable=True)
    fork_round: Mapped[int] = mapped_column(Integer, default=0)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_json: Mapped[dict] = mapped_column(JSON, default=dict)
    budget_json: Mapped[dict] = mapped_column(JSON, default=dict)
    result_json: Mapped[dict] = mapped_column(JSON, default=dict)


class StorySimulationStep(Base, UUIDMixin, TimestampMixin, NovelMixin):
    """Append-only completed rounds; branch-local observations and derived state."""

    __tablename__ = "story_simulation_steps"
    __table_args__ = (
        UniqueConstraint(
            "novel_id", "run_id", "round_number", name="uq_story_simulation_step_round"
        ),
        ForeignKeyConstraint(
            ["novel_id", "run_id"],
            ["story_simulation_runs.novel_id", "story_simulation_runs.id"],
            ondelete="CASCADE",
        ),
    )
    run_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False)
    round_number: Mapped[int] = mapped_column(Integer, nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    output_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    intents_json: Mapped[dict] = mapped_column(JSON, default=dict)
    events_json: Mapped[list] = mapped_column(JSON, default=list)
    state_json: Mapped[dict] = mapped_column(JSON, default=dict)


class StorySceneDirectorRoot(Base, UUIDMixin, TimestampMixin, NovelMixin):
    """One author-budgeted director root shared by its immutable branches."""

    __tablename__ = "story_scene_director_roots"
    __table_args__ = (
        UniqueConstraint("novel_id", "id", name="uq_story_scene_director_root_novel"),
        Index("ix_story_scene_director_root_scene", "novel_id", "scene_id", "created_at"),
    )

    scene_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    llm_execution_snapshot_json: Mapped[dict] = mapped_column(
        JSON, nullable=False, default=dict
    )
    run_envelope_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ready")
    current_task_id: Mapped[uuid.UUID | None] = mapped_column(UUIDType, nullable=True)


class StorySceneDirectorBranch(Base, UUIDMixin, TimestampMixin, NovelMixin):
    """A branch starts at a frozen round and only appends its own results."""

    __tablename__ = "story_scene_director_branches"
    __table_args__ = (
        UniqueConstraint("novel_id", "id", name="uq_story_scene_director_branch_novel"),
        ForeignKeyConstraint(
            ["novel_id", "root_id"],
            ["story_scene_director_roots.novel_id", "story_scene_director_roots.id"],
            ondelete="CASCADE",
        ),
        Index("ix_story_scene_director_branch_root", "novel_id", "root_id", "created_at"),
    )

    root_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False)
    parent_round_id: Mapped[uuid.UUID | None] = mapped_column(UUIDType, nullable=True)
    branch_kind: Mapped[str] = mapped_column(String(24), nullable=False, default="start")
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    pending_round_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    name: Mapped[str | None] = mapped_column(String(180), nullable=True)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    starred: Mapped[bool] = mapped_column(nullable=False, default=False)
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    restore_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    current_task_id: Mapped[uuid.UUID | None] = mapped_column(UUIDType, nullable=True)


class StorySceneDirectorRound(Base, UUIDMixin, TimestampMixin, NovelMixin):
    """Frozen director input and output for a single completed round."""

    __tablename__ = "story_scene_director_rounds"
    __table_args__ = (
        UniqueConstraint("novel_id", "id", name="uq_story_scene_director_round_novel"),
        UniqueConstraint(
            "novel_id",
            "branch_id",
            "round_number",
            name="uq_story_scene_director_round_number",
        ),
        ForeignKeyConstraint(
            ["novel_id", "branch_id"],
            [
                "story_scene_director_branches.novel_id",
                "story_scene_director_branches.id",
            ],
            ondelete="CASCADE",
        ),
        Index("ix_story_scene_director_round_root", "novel_id", "root_id", "created_at"),
    )

    root_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False)
    branch_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False)
    round_number: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_round_id: Mapped[uuid.UUID | None] = mapped_column(UUIDType, nullable=True)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    output_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    input_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    output_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    state_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    run_envelope_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    name: Mapped[str | None] = mapped_column(String(180), nullable=True)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    starred: Mapped[bool] = mapped_column(nullable=False, default=False)


class StorySceneDirectorReference(Base, UUIDMixin, TimestampMixin, NovelMixin):
    """Independent content copy for a writing reference, never an adopted script."""

    __tablename__ = "story_scene_director_references"
    __table_args__ = (
        UniqueConstraint(
            "novel_id", "id", name="uq_story_scene_director_reference_novel"
        ),
        Index(
            "ix_story_scene_director_reference_scene",
            "novel_id",
            "scene_id",
            "created_at",
        ),
    )

    root_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False)
    scene_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False)
    source_round_id: Mapped[uuid.UUID | None] = mapped_column(UUIDType, nullable=True)
    source_basis_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_deleted: Mapped[bool] = mapped_column(nullable=False, default=False)
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    content_copy_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    material_ids_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    angle_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    annotation: Mapped[str] = mapped_column(Text, nullable=False, default="")
    origin: Mapped[str] = mapped_column(String(40), nullable=False, default="author_ui")
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    restore_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class StorySceneDirectorCandidateTransfer(Base, UUIDMixin, TimestampMixin, NovelMixin):
    """One author-approved World candidate from an immutable Director event."""

    __tablename__ = "story_scene_director_candidate_transfers"
    __table_args__ = (
        UniqueConstraint(
            "novel_id",
            "round_id",
            "candidate_ref",
            name="uq_story_director_candidate_transfer_source",
        ),
        UniqueConstraint(
            "novel_id",
            "world_candidate_id",
            name="uq_story_director_candidate_transfer_world",
        ),
    )

    # Weak source reference survives author deletion of the Director history.
    round_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False)
    candidate_ref: Mapped[str] = mapped_column(String(120), nullable=False)
    scene_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    output_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    world_candidate_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False)


class StorySceneDirectorPreference(Base, UUIDMixin, TimestampMixin, NovelMixin):
    """Project-local, author-editable anti-cliché phrase list."""

    __tablename__ = "story_scene_director_preferences"
    __table_args__ = (
        UniqueConstraint("novel_id", name="uq_story_scene_director_preference_novel"),
    )

    cliche_phrases_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)


# A model import from ``story.models`` is part of the app's ORM discovery contract.
