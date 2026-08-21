from __future__ import annotations

import uuid

from sqlalchemy import (
    JSON,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.base import Base, NovelMixin, StatusMixin, TimestampMixin, UUIDMixin, UUIDType


class StoryOutlineRevision(Base, UUIDMixin, TimestampMixin, NovelMixin):
    """Immutable, author-adopted revision of the novel-level story outline."""

    __tablename__ = "story_outline_revisions"
    __table_args__ = (
        UniqueConstraint(
            "novel_id",
            "version_number",
            name="uq_story_outline_revision_version",
        ),
        UniqueConstraint(
            "novel_id",
            "idempotency_key",
            name="uq_story_outline_revision_idempotency",
        ),
        UniqueConstraint(
            "id",
            "novel_id",
            name="uq_story_outline_revision_id_novel",
        ),
        ForeignKeyConstraint(
            ["base_revision_id", "novel_id"],
            ["story_outline_revisions.id", "story_outline_revisions.novel_id"],
            name="fk_story_outline_revision_base_novel",
        ),
        ForeignKeyConstraint(
            ["restored_from_revision_id", "novel_id"],
            ["story_outline_revisions.id", "story_outline_revisions.novel_id"],
            name="fk_story_outline_revision_restored_novel",
        ),
        Index(
            "ix_story_outline_revisions_novel_version",
            "novel_id",
            "version_number",
        ),
        {"comment": "小说总纲不可变修订"},
    )

    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    creative_core_json: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    outline_markdown: Mapped[str] = mapped_column(Text, nullable=False)
    major_storylines_json: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    macro_movements_json: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    open_decisions_json: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    provenance_json: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    base_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType,
        nullable=True,
    )
    restored_from_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType,
        nullable=True,
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class StoryOutlineHead(Base, UUIDMixin, TimestampMixin, NovelMixin):
    """One novel-scoped pointer to the current StoryOutline revision."""

    __tablename__ = "story_outline_heads"
    __table_args__ = (
        UniqueConstraint("novel_id", name="uq_story_outline_head_novel"),
        ForeignKeyConstraint(
            ["current_revision_id", "novel_id"],
            ["story_outline_revisions.id", "story_outline_revisions.novel_id"],
            name="fk_story_outline_head_current_novel",
        ),
        {"comment": "小说总纲当前修订指针"},
    )

    current_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType,
        nullable=True,
    )


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
    provenance_meta: Mapped[dict] = mapped_column(JSON, nullable=True, default=dict)


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
    provenance_meta: Mapped[dict] = mapped_column(JSON, nullable=True, default=dict)


class Scene(Base, UUIDMixin, TimestampMixin, StatusMixin, NovelMixin):
    """Scene 卡 — 叙事结构的最小可编辑单元"""

    __tablename__ = "scenes"
    __table_args__ = {"comment": "Scene 卡"}

    scene_index: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        index=True,
        comment="Scene 逻辑顺序索引（从 0 开始）",
    )
    title: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="Scene 标题",
    )
    goal: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Scene 目标（此 Scene 要完成什么）",
    )
    core_conflict: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="核心冲突",
    )
    emotional_beat: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="情感节奏（读者的情感走向）",
    )
    must_happen: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="必须发生的事件",
    )
    must_not_happen: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="禁止发生的事件",
    )
    narrative_tag: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="draft",
        comment="叙事标签（NarrativeTag 枚举值）",
    )
    source: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="manual",
        comment="来源（manual / deep_import / ai_generated）",
    )
    scene_chunks: Mapped[list] = mapped_column(
        JSON,
        nullable=True,
        default=list,
        comment="物理映射：Scene → Chapter 物理位置区间",
    )
    chapter_ids: Mapped[list] = mapped_column(
        JSON,
        nullable=True,
        default=list,
        comment="关联 Chapter ID 列表",
    )
    pov_character_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
        comment="POV 人物 ID（可选，指向 core_entities）",
    )
    structure_meta: Mapped[dict] = mapped_column(
        JSON,
        nullable=True,
        default=dict,
        comment="Scene 结构整理元信息",
    )

    def __repr__(self) -> str:
        return (
            f"<Scene id={self.id} novel={self.novel_id} "
            f"idx={self.scene_index} tag={self.narrative_tag}>"
        )


class SceneSpan(Base, UUIDMixin, TimestampMixin, NovelMixin):
    """Derived Scene → chapter text span read model."""

    __tablename__ = "scene_spans"
    __table_args__ = (
        UniqueConstraint(
            "novel_id",
            "scene_id",
            "content_mode",
            "part_no",
            name="uq_scene_spans_novel_scene_part",
        ),
        Index(
            "ix_scene_spans_novel_chapter",
            "novel_id",
            "chapter_index",
            "part_no",
        ),
        Index(
            "ix_scene_spans_scene",
            "scene_id",
        ),
        {"comment": "Scene 到正文物理片段的派生查询索引"},
    )

    scene_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("scenes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chapter_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content_mode: Mapped[str] = mapped_column(
        String(16), nullable=False, default="canonical"
    )
    source_draft_id: Mapped[uuid.UUID | None] = mapped_column(UUIDType, nullable=True)
    source_content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    start_offset: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_offset: Mapped[int | None] = mapped_column(Integer, nullable=True)
    start_paragraph: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_paragraph: Mapped[int | None] = mapped_column(Integer, nullable=True)
    part_no: Mapped[int] = mapped_column(Integer, nullable=False)
    mapping_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="chapter_only"
    )
    anchor_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    anchor_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="manual")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")


class SceneFusionSuggestion(Base, UUIDMixin, TimestampMixin, NovelMixin):
    """Author-visible, durable Scene fusion suggestion."""

    __tablename__ = "scene_fusion_suggestions"
    __table_args__ = (
        UniqueConstraint(
            "novel_id",
            "suggestion_key",
            name="uq_scene_fusion_suggestion_key",
        ),
        Index(
            "ix_scene_fusion_suggestions_queue",
            "novel_id",
            "status",
            "created_at",
        ),
        {"comment": "Phase 1c 产生的持久 Scene 融合建议"},
    )

    source_workflow_id: Mapped[str] = mapped_column(String(64), nullable=False)
    suggestion_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    proposed_action: Mapped[str] = mapped_column(String(32), nullable=False)
    suggestion_key: Mapped[str] = mapped_column(String(64), nullable=False)
    source_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    source_scene_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    chapter_span: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    proposed_scene: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    scan_trace: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    result_scene_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType,
        ForeignKey("scenes.id", ondelete="SET NULL"),
        nullable=True,
    )
    result_scene_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)


class SceneSummaryCheckpoint(Base, UUIDMixin, TimestampMixin, NovelMixin):
    """Derived, source-backed Scene summary as of one visible cursor."""

    __tablename__ = "scene_summary_checkpoints"
    __table_args__ = (
        UniqueConstraint(
            "novel_id",
            "scene_id",
            "content_mode",
            "through_chapter",
            "through_offset",
            name="uq_scene_summary_checkpoint_cursor",
        ),
        Index(
            "ix_scene_summary_checkpoints_lookup",
            "novel_id",
            "scene_id",
            "content_mode",
            "through_chapter",
        ),
        {"comment": "Scene 按可见截止位置派生的防剧透摘要"},
    )

    scene_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("scenes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    content_mode: Mapped[str] = mapped_column(
        String(16), nullable=False, default="canonical"
    )
    through_chapter: Mapped[int] = mapped_column(Integer, nullable=False)
    through_offset: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=-1,
        comment="-1 表示截止章完整可见",
    )
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    source_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    based_on_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="derived")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ready")


class SceneChapterLink(Base, UUIDMixin, TimestampMixin, NovelMixin):
    """Query index for Scene → chapter membership."""

    __tablename__ = "scene_chapter_links"
    __table_args__ = (
        UniqueConstraint(
            "novel_id",
            "scene_id",
            "chapter_index",
            name="uq_scene_chapter_links_novel_scene_chapter",
        ),
        Index(
            "ix_scene_chapter_links_novel_chapter",
            "novel_id",
            "chapter_index",
        ),
        {"comment": "Scene 与章节编号的查询索引"},
    )

    scene_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("scenes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chapter_index: Mapped[int] = mapped_column(Integer, nullable=False)


class ForeshadowingPlan(Base, UUIDMixin, TimestampMixin, StatusMixin, NovelMixin):
    """伏笔计划 — 贯穿多章的伏笔链"""

    __tablename__ = "foreshadowing_plans"
    __table_args__ = {"comment": "伏笔计划"}

    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="伏笔名称",
    )
    summary: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="伏笔概述",
    )
    surface_meaning: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="表面含义",
    )
    hidden_meaning: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="隐藏含义",
    )
    planned_seed_chapter: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="埋下伏笔的章节",
    )
    planned_reinforce_chapters: Mapped[list] = mapped_column(
        JSON,
        nullable=True,
        default=list,
        comment="强化章节列表",
    )
    planned_payoff_chapter: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="兑现章节",
    )
    planned_payoff_scene: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="兑现 Scene 索引（scene-centric 编译使用）",
    )
    related_entity_ids: Mapped[list] = mapped_column(
        JSON,
        nullable=True,
        default=list,
        comment="关联实体 ID",
    )
    related_thread_ids: Mapped[list] = mapped_column(
        JSON,
        nullable=True,
        default=list,
        comment="关联剧情线 ID",
    )
    provenance_meta: Mapped[dict] = mapped_column(
        JSON,
        nullable=True,
        default=dict,
        comment="结构资产来源元信息",
    )

    def __repr__(self) -> str:
        return f"<ForeshadowingPlan id={self.id} name={self.name} status={self.status}>"


class RevealPlan(Base, UUIDMixin, TimestampMixin, NovelMixin):
    """信息揭示计划 — 分层逐步披露秘密"""

    __tablename__ = "reveal_plans"
    __table_args__ = {"comment": "信息揭示计划"}

    target_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        comment="目标类型",
    )
    target_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        nullable=False,
        comment="目标实体/人物 ID",
    )
    secret_summary: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="被隐藏的秘密",
    )
    reveal_stages: Mapped[list] = mapped_column(
        JSON,
        nullable=True,
        default=list,
        comment=(
            "揭示阶段 [{stage_index, chapter_index, reveal_content, trigger, effect}]"
        ),
    )
    related_thread_ids: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="关联剧情线 ID；允许多条，空数组表示尚未归类",
    )
    provenance_meta: Mapped[dict] = mapped_column(
        JSON,
        nullable=True,
        default=dict,
        comment="结构资产来源元信息",
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="draft",
        comment="状态",
    )

    def __repr__(self) -> str:
        return (
            f"<RevealPlan id={self.id} target_type={self.target_type} "
            f"target_id={self.target_id} status={self.status}>"
        )
