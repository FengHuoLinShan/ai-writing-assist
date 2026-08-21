"""Persisted Story-layer cards and Scene script assets.

The Story module owns author-editable projections used by the Scene workflow.
Canonical characters and Scenes remain owned by ``world`` and ``outline``;
their identifiers are deliberately weak references here and are validated at
the facade/service boundary.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import (
    JSON,
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
        ),
        Index(
            "ix_story_character_card_novel_status",
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
            "ix_story_character_card_revision_novel_card",
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
        ),
        ForeignKeyConstraint(
            ["adopted_revision_id", "novel_id"],
            ["story_scene_script_revisions.id", "story_scene_script_revisions.novel_id"],
            name="fk_story_scene_script_file_adopted_novel",
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
