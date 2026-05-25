"""
Outline ORM 模型

对应 5 张数据库表：
- plot_threads: 剧情线定义
- outline_arcs: 篇章纲（8-15 章剧情闭环）
- chapter_cards: 章节卡
- foreshadowing_plans: 伏笔计划
- reveal_plans: 信息揭示计划
"""

from __future__ import annotations

import uuid

from sqlalchemy import Integer, String, Text, UniqueConstraint
from sqlalchemy import JSON
from sqlalchemy.orm import Mapped, mapped_column

from core.base import Base, NovelMixin, StatusMixin, TimestampMixin, UUIDMixin


# ============================================================
# PlotThread — 剧情线
# ============================================================

class PlotThread(Base, UUIDMixin, TimestampMixin, StatusMixin, NovelMixin):
    """剧情线定义

    定义小说中的一条剧情线，包括主线、支线、暗线、关系线、反派线、伏笔线。
    每条线有明确的起始和计划收束章节。
    """

    __tablename__ = "plot_threads"
    __table_args__ = {"comment": "剧情线定义"}

    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="剧情线名称",
    )
    thread_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        index=True,
        comment="剧情线类型：main/secondary/hidden/relationship/villain/foreshadowing",
    )
    summary: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="剧情线概要",
    )
    visible_goal: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="对外可见目标（读者已知或可推测的部分）",
    )
    hidden_truth: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="暗线真相（仅作者视角）",
    )
    start_chapter: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="起始章节索引",
    )
    planned_payoff_chapter: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="计划收束章节索引",
    )
    current_stage: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        comment="当前阶段描述",
    )
    related_character_ids: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="关联人物 ID 列表（JSONB）",
    )
    related_entity_ids: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="关联世界对象 ID 列表（JSONB）",
    )
    related_memory_ids: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="关联记忆记录 ID 列表（JSONB）",
    )
    reader_known_state: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="读者已知的状态描述",
    )
    author_known_state: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="作者已知的完整状态描述",
    )

    def __repr__(self) -> str:
        return f"<PlotThread id={self.id} type={self.thread_type} name={self.name!r}>"


# ============================================================
# OutlineArc — 篇章纲
# ============================================================

class OutlineArc(Base, UUIDMixin, TimestampMixin, StatusMixin, NovelMixin):
    """篇章纲（8-15 章的小剧情闭环）

    标准三幕结构：entry_hook → midpoint_turn → climax → result → next_hook。
    每个篇章是一个相对独立的剧情闭环，同时通过 next_hook 衔接后续篇章。
    """

    __tablename__ = "outline_arcs"
    __table_args__ = {"comment": "篇章纲定义"}

    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="篇章标题",
    )
    arc_index: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="篇章序号（用于排序）",
    )
    start_chapter: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="起始章节索引",
    )
    end_chapter: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="结束章节索引",
    )
    arc_goal: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="篇章整体目标",
    )
    core_conflict: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="核心冲突",
    )
    main_opposition: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="主要对抗力量",
    )
    entry_hook: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="开篇钩子（第一幕）",
    )
    midpoint_turn: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="中点转折（第二幕转折点）",
    )
    climax: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="高潮（第三幕）",
    )
    result: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="结果与短时影响",
    )
    next_hook: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="衔接下个篇章的钩子",
    )
    related_thread_ids: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="关联剧情线 ID 列表（JSONB）",
    )
    related_character_ids: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="关联人物 ID 列表（JSONB）",
    )
    related_entity_ids: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="关联世界对象 ID 列表（JSONB）",
    )

    def __repr__(self) -> str:
        return f"<OutlineArc id={self.id} index={self.arc_index} title={self.title!r}>"


# ============================================================
# ChapterCard — 章节卡
# ============================================================

class ChapterCard(Base, UUIDMixin, TimestampMixin, StatusMixin, NovelMixin):
    """章节卡

    每章的核心结构定义。必须包含：
    - 明确的目标（chapter_goal）
    - 明确的主要冲突（main_conflict）
    - 状态变化（visible_progress / hidden_progress / offscreen_progress）
    - 信息推进
    - 情绪点或钩子（emotional_point / ending_hook）

    场景卡（SceneCard）MVP 阶段放在 scene_cards JSONB 字段。
    """

    __tablename__ = "chapter_cards"
    __table_args__ = (
        UniqueConstraint(
            "novel_id",
            "chapter_index",
            name="uq_chapter_cards_novel_chapter",
        ),
        {"comment": "章节卡定义"},
    )

    chapter_index: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="章节序号（从 1 开始，同小说内唯一）",
    )
    title: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="章节标题",
    )
    arc_id: Mapped[uuid.UUID | None] = mapped_column(
        nullable=True,
        index=True,
        comment="所属篇章 ID（UUID，逻辑 FK -> outline_arcs.id）",
    )
    chapter_goal: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="本章核心目标（必须）",
    )
    main_conflict: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="本章主要冲突（必须）",
    )
    emotional_point: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="情绪点或情感基调",
    )
    plot_function: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        comment="剧情功能标签（如 setup/payoff/twist/bridge）",
    )
    must_happen: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="本章必须发生的事件列表（JSONB）",
    )
    must_not_happen: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="本章绝对不能发生的事件列表（JSONB）",
    )
    involved_character_ids: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="出场人物 ID 列表（JSONB）",
    )
    involved_entity_ids: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="涉及世界对象 ID 列表（JSONB）",
    )
    related_thread_ids: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="关联剧情线 ID 列表（JSONB）",
    )
    visible_progress: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="读者可见的剧情进展（JSONB）",
    )
    hidden_progress: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="隐藏的剧情进展（仅作者知，JSONB）",
    )
    offscreen_progress: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="幕外/场景外发生的事（JSONB）",
    )
    foreshadowing_actions: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="伏笔操作（埋设/加强/揭示，JSONB）",
    )
    ending_hook: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="章节尾钩（吸引读者继续阅读）",
    )
    scene_cards: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="场景卡片列表（JSONB，MVP 阶段不拆独立表）",
    )

    def __repr__(self) -> str:
        return (
            f"<ChapterCard id={self.id} "
            f"ch={self.chapter_index} "
            f"title={self.title!r}>"
        )


# ============================================================
# ForeshadowingPlan — 伏笔计划
# ============================================================

class ForeshadowingPlan(Base, UUIDMixin, TimestampMixin, StatusMixin, NovelMixin):
    """伏笔计划

    管理一条伏笔的完整生命周期：计划 → 埋设 → 加强 → 收束。
    包括表面含义（读者所见）和隐藏含义（实际真相）。
    """

    __tablename__ = "foreshadowing_plans"
    __table_args__ = {"comment": "伏笔计划定义"}

    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="伏笔名称",
    )
    summary: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="伏笔概要",
    )
    surface_meaning: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="表面含义（读者看到的内容）",
    )
    hidden_meaning: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="隐藏含义（实际真相）",
    )
    planned_seed_chapter: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="计划埋设章节",
    )
    planned_reinforce_chapters: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="计划加强章节列表（JSONB，可多次加强）",
    )
    planned_payoff_chapter: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="计划收束章节",
    )
    related_entity_ids: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="关联世界对象 ID 列表（JSONB）",
    )
    related_thread_ids: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="关联剧情线 ID 列表（JSONB）",
    )

    def __repr__(self) -> str:
        return f"<ForeshadowingPlan id={self.id} name={self.name!r}>"


# ============================================================
# RevealPlan — 信息揭示计划
# ============================================================

class RevealPlan(Base, UUIDMixin, TimestampMixin, StatusMixin, NovelMixin):
    """信息揭示计划

    管理秘密信息的逐步揭示过程。
    每个揭示计划对应一个目标（世界对象或人物），
    包含多个揭示阶段，控制信息在何时以何种方式透露给读者。
    """

    __tablename__ = "reveal_plans"
    __table_args__ = {"comment": "信息揭示计划定义"}

    target_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        comment="揭示目标类型（world_entity / character / secret）",
    )
    target_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
        index=True,
        comment="揭示目标 ID（UUID hex）",
    )
    secret_summary: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="要揭示的秘密概要",
    )
    reveal_stages: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment=(
            "揭示阶段列表（JSONB），每个阶段包含："
            "{chapter_index, hint_level, content, revealed_to_reader, known_by}"
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<RevealPlan id={self.id} "
            f"target={self.target_type}:{self.target_id}>"
        )
