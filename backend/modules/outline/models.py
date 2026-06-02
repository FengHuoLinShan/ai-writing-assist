from __future__ import annotations

from sqlalchemy import JSON, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from core.base import Base, NovelMixin, StatusMixin, TimestampMixin, UUIDMixin


class PlotThread(Base, UUIDMixin, TimestampMixin, StatusMixin, NovelMixin):
    __tablename__ = "plot_threads"
    __table_args__ = {"comment": "剧情线"}

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    thread_type: Mapped[str] = mapped_column(String(32), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    visible_goal: Mapped[str | None] = mapped_column(Text, nullable=True)
    hidden_truth: Mapped[str | None] = mapped_column(Text, nullable=True)
    start_chapter: Mapped[int | None] = mapped_column(Integer, nullable=True)
    planned_payoff_chapter: Mapped[int | None] = mapped_column(Integer, nullable=True)
    current_stage: Mapped[str | None] = mapped_column(String(32), nullable=True)
    related_character_ids: Mapped[list] = mapped_column(JSON, nullable=True, default=list)
    related_entity_ids: Mapped[list] = mapped_column(JSON, nullable=True, default=list)
    related_memory_ids: Mapped[list] = mapped_column(JSON, nullable=True, default=list)
    reader_known_state: Mapped[str | None] = mapped_column(Text, nullable=True)
    author_known_state: Mapped[str | None] = mapped_column(Text, nullable=True)


class OutlineArc(Base, UUIDMixin, TimestampMixin, StatusMixin, NovelMixin):
    __tablename__ = "outline_arcs"
    __table_args__ = {"comment": "篇章纲"}

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    arc_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    start_chapter: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_chapter: Mapped[int | None] = mapped_column(Integer, nullable=True)
    arc_goal: Mapped[str | None] = mapped_column(Text, nullable=True)
    core_conflict: Mapped[str | None] = mapped_column(Text, nullable=True)
    main_opposition: Mapped[str | None] = mapped_column(Text, nullable=True)
    entry_hook: Mapped[str | None] = mapped_column(Text, nullable=True)
    midpoint_turn: Mapped[str | None] = mapped_column(Text, nullable=True)
    climax: Mapped[str | None] = mapped_column(Text, nullable=True)
    result: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_hook: Mapped[str | None] = mapped_column(Text, nullable=True)
    related_thread_ids: Mapped[list] = mapped_column(JSON, nullable=True, default=list)
    related_character_ids: Mapped[list] = mapped_column(JSON, nullable=True, default=list)
    related_entity_ids: Mapped[list] = mapped_column(JSON, nullable=True, default=list)
