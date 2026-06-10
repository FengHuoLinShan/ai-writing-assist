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


class Scene(Base, UUIDMixin, TimestampMixin, StatusMixin, NovelMixin):
    """Scene 卡 — 叙事结构的最小可编辑单元"""

    __tablename__ = "scenes"
    __table_args__ = {"comment": "Scene 卡"}

    scene_index: Mapped[int] = mapped_column(
        Integer, nullable=False, index=True,
        comment="Scene 逻辑顺序索引（从 0 开始）",
    )
    title: Mapped[str | None] = mapped_column(
        String(255), nullable=True,
        comment="Scene 标题",
    )
    goal: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="Scene 目标（此 Scene 要完成什么）",
    )
    core_conflict: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="核心冲突",
    )
    emotional_beat: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="情感节奏（读者的情感走向）",
    )
    must_happen: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="必须发生的事件",
    )
    must_not_happen: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="禁止发生的事件",
    )
    narrative_tag: Mapped[str] = mapped_column(
        String(32), nullable=False, default="draft",
        comment="叙事标签（NarrativeTag 枚举值）",
    )
    source: Mapped[str] = mapped_column(
        String(32), nullable=False, default="manual",
        comment="来源（manual / deep_import / ai_generated）",
    )
    scene_chunks: Mapped[list] = mapped_column(
        JSON, nullable=True, default=list,
        comment="物理映射：Scene → Chapter 物理位置区间",
    )
    chapter_ids: Mapped[list] = mapped_column(
        JSON, nullable=True, default=list,
        comment="关联 Chapter ID 列表",
    )
    pov_character_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True,
        comment="POV 人物 ID（可选，指向 core_entities）",
    )

    def __repr__(self) -> str:
        return (
            f"<Scene id={self.id} novel={self.novel_id} "
            f"idx={self.scene_index} tag={self.narrative_tag}>"
        )


class ForeshadowingPlan(Base, UUIDMixin, TimestampMixin, StatusMixin, NovelMixin):
    """伏笔计划 — 贯穿多章的伏笔链"""

    __tablename__ = "foreshadowing_plans"
    __table_args__ = {"comment": "伏笔计划"}

    name: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="伏笔名称",
    )
    summary: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="伏笔概述",
    )
    surface_meaning: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="表面含义",
    )
    hidden_meaning: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="隐藏含义",
    )
    planned_seed_chapter: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="埋下伏笔的章节",
    )
    planned_reinforce_chapters: Mapped[list] = mapped_column(
        JSON, nullable=True, default=list, comment="强化章节列表",
    )
    planned_payoff_chapter: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="兑现章节",
    )
    related_entity_ids: Mapped[list] = mapped_column(
        JSON, nullable=True, default=list, comment="关联实体 ID",
    )
    related_thread_ids: Mapped[list] = mapped_column(
        JSON, nullable=True, default=list, comment="关联剧情线 ID",
    )

    def __repr__(self) -> str:
        return (
            f"<ForeshadowingPlan id={self.id} name={self.name} "
            f"status={self.status}>"
        )
