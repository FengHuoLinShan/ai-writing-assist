"""Project-owned author preference ORM model."""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from core.base import Base, TimestampMixin, UUIDMixin


class ProjectAuthorPreferences(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "project_author_preferences"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    daily_goal: Mapped[int | None] = mapped_column(Integer, nullable=True)
    editor_font: Mapped[str | None] = mapped_column(String(32), nullable=True)
    default_focus_mode: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
