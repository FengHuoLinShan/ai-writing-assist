"""
Outline Pydantic Schema 定义

用于 API 请求/响应校验和 Facade 输出。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ============================================================
# 内部工具
# ============================================================


def _uuid_validator(v: object) -> str:
    """将 UUID 原始值转为字符串"""
    if isinstance(v, uuid.UUID):
        return str(v)
    if isinstance(v, str):
        return v
    return str(v)


# ============================================================
# PlotThread Schema
# ============================================================


class PlotThreadCreate(BaseModel):
    """创建剧情线请求"""

    name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="剧情线名称",
    )
    thread_type: str = Field(
        ...,
        max_length=32,
        pattern="^(main|secondary|hidden|relationship|villain|foreshadowing)$",
        description="剧情线类型：main/secondary/hidden/relationship/villain/foreshadowing",
    )
    summary: str | None = Field(
        None,
        description="概要",
    )
    visible_goal: str | None = Field(
        None,
        description="对外可见目标",
    )
    hidden_truth: str | None = Field(
        None,
        description="暗线真相（仅作者视角）",
    )
    start_chapter: int | None = Field(
        None,
        ge=1,
        description="起始章节索引",
    )
    planned_payoff_chapter: int | None = Field(
        None,
        ge=1,
        description="计划收束章节",
    )
    current_stage: str | None = Field(
        None,
        max_length=64,
        description="当前阶段描述",
    )
    related_character_ids: list[str] = Field(
        default_factory=list,
        description="关联人物 ID 列表",
    )
    related_entity_ids: list[str] = Field(
        default_factory=list,
        description="关联世界对象 ID 列表",
    )
    related_memory_ids: list[str] = Field(
        default_factory=list,
        description="关联记忆记录 ID 列表",
    )
    reader_known_state: str | None = Field(
        None,
        description="读者已知的状态",
    )
    author_known_state: str | None = Field(
        None,
        description="作者已知的完整状态",
    )
    status: str = Field(
        default="draft",
        max_length=32,
        description="状态",
    )


class PlotThreadUpdate(BaseModel):
    """更新剧情线请求（所有字段可选）"""

    name: Annotated[str | None, Field(None, min_length=1, max_length=255)]
    thread_type: Annotated[str | None, Field(None, max_length=32)]
    summary: Annotated[str | None, Field(None)]
    visible_goal: Annotated[str | None, Field(None)]
    hidden_truth: Annotated[str | None, Field(None)]
    start_chapter: Annotated[int | None, Field(None, ge=1)]
    planned_payoff_chapter: Annotated[int | None, Field(None, ge=1)]
    current_stage: Annotated[str | None, Field(None, max_length=64)]
    related_character_ids: Annotated[list[str] | None, Field(None)]
    related_entity_ids: Annotated[list[str] | None, Field(None)]
    related_memory_ids: Annotated[list[str] | None, Field(None)]
    reader_known_state: Annotated[str | None, Field(None)]
    author_known_state: Annotated[str | None, Field(None)]
    status: Annotated[str | None, Field(None, max_length=32)]


class PlotThreadResponse(BaseModel):
    """剧情线响应"""

    model_config = ConfigDict(
        from_attributes=True,
        json_encoders={uuid.UUID: str},
    )

    id: str
    novel_id: str
    name: str
    thread_type: str
    summary: str | None = None
    visible_goal: str | None = None
    hidden_truth: str | None = None
    start_chapter: int | None = None
    planned_payoff_chapter: int | None = None
    current_stage: str | None = None
    related_character_ids: list[str] = []
    related_entity_ids: list[str] = []
    related_memory_ids: list[str] = []
    reader_known_state: str | None = None
    author_known_state: str | None = None
    status: str = "draft"
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("id", "novel_id", mode="before")
    @classmethod
    def coerce_uuid(cls, v: object) -> str:
        return _uuid_validator(v)


class PlotThreadListResponse(BaseModel):
    """剧情线列表响应"""

    items: list[PlotThreadResponse]
    total: int


# ============================================================
# OutlineArc Schema
# ============================================================


class OutlineArcCreate(BaseModel):
    """创建篇章纲请求"""

    title: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="篇章标题",
    )
    arc_index: int | None = Field(
        None,
        ge=1,
        description="篇章序号",
    )
    start_chapter: int | None = Field(
        None,
        ge=1,
        description="起始章节索引",
    )
    end_chapter: int | None = Field(
        None,
        ge=1,
        description="结束章节索引",
    )
    arc_goal: str = Field(
        ...,
        description="篇章目标",
    )
    core_conflict: str = Field(
        ...,
        description="核心冲突",
    )
    main_opposition: str | None = Field(
        None,
        description="主要对抗力量",
    )
    entry_hook: str | None = Field(
        None,
        description="开篇钩子",
    )
    midpoint_turn: str | None = Field(
        None,
        description="中点转折",
    )
    climax: str = Field(
        ...,
        description="高潮",
    )
    result: str = Field(
        ...,
        description="结果",
    )
    next_hook: str | None = Field(
        None,
        description="下篇衔接钩子",
    )
    related_thread_ids: list[str] = Field(
        default_factory=list,
        description="关联剧情线 ID",
    )
    related_character_ids: list[str] = Field(
        default_factory=list,
        description="关联人物 ID",
    )
    related_entity_ids: list[str] = Field(
        default_factory=list,
        description="关联世界对象 ID",
    )
    status: str = Field(
        default="draft",
        max_length=32,
        description="状态",
    )


class OutlineArcUpdate(BaseModel):
    """更新篇章纲请求（所有字段可选）"""

    title: Annotated[str | None, Field(None, min_length=1, max_length=255)]
    arc_index: Annotated[int | None, Field(None, ge=1)]
    start_chapter: Annotated[int | None, Field(None, ge=1)]
    end_chapter: Annotated[int | None, Field(None, ge=1)]
    arc_goal: Annotated[str | None, Field(None)]
    core_conflict: Annotated[str | None, Field(None)]
    main_opposition: Annotated[str | None, Field(None)]
    entry_hook: Annotated[str | None, Field(None)]
    midpoint_turn: Annotated[str | None, Field(None)]
    climax: Annotated[str | None, Field(None)]
    result: Annotated[str | None, Field(None)]
    next_hook: Annotated[str | None, Field(None)]
    related_thread_ids: Annotated[list[str] | None, Field(None)]
    related_character_ids: Annotated[list[str] | None, Field(None)]
    related_entity_ids: Annotated[list[str] | None, Field(None)]
    status: Annotated[str | None, Field(None, max_length=32)]


class OutlineArcResponse(BaseModel):
    """篇章纲响应"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    novel_id: str
    title: str
    arc_index: int | None = None
    start_chapter: int | None = None
    end_chapter: int | None = None
    arc_goal: str | None = None
    core_conflict: str | None = None
    main_opposition: str | None = None
    entry_hook: str | None = None
    midpoint_turn: str | None = None
    climax: str | None = None
    result: str | None = None
    next_hook: str | None = None
    related_thread_ids: list[str] = []
    related_character_ids: list[str] = []
    related_entity_ids: list[str] = []
    status: str = "draft"
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("id", "novel_id", mode="before")
    @classmethod
    def coerce_uuid(cls, v: object) -> str:
        return _uuid_validator(v)


class OutlineArcListResponse(BaseModel):
    """篇章纲列表响应"""

    items: list[OutlineArcResponse]
    total: int


# ============================================================
# ChapterCard Schema
# ============================================================


class ChapterCardCreate(BaseModel):
    """创建章节卡请求"""

    chapter_index: int = Field(
        ...,
        ge=1,
        description="章节序号",
    )
    title: str | None = Field(
        None,
        max_length=255,
        description="章节标题",
    )
    arc_id: str | None = Field(
        None,
        description="所属篇章 ID",
    )
    chapter_goal: str = Field(
        ...,
        description="本章核心目标",
    )
    main_conflict: str = Field(
        ...,
        description="本章主要冲突",
    )
    emotional_point: str | None = Field(
        None,
        description="情绪点",
    )
    plot_function: str | None = Field(
        None,
        max_length=64,
        description="剧情功能标签",
    )
    must_happen: list[str] = Field(
        default_factory=list,
        max_length=20,
        description="必须发生的事件（最多 20 条）",
    )
    must_not_happen: list[str] = Field(
        default_factory=list,
        description="绝对不能发生的事件",
    )
    involved_character_ids: list[str] = Field(
        default_factory=list,
        description="出场人物 ID",
    )
    involved_entity_ids: list[str] = Field(
        default_factory=list,
        description="涉及对象 ID",
    )
    related_thread_ids: list[str] = Field(
        default_factory=list,
        description="关联剧情线 ID",
    )
    visible_progress: list[str] = Field(
        default_factory=list,
        description="读者可见进展",
    )
    hidden_progress: list[str] = Field(
        default_factory=list,
        description="隐藏进展",
    )
    offscreen_progress: list[str] = Field(
        default_factory=list,
        description="幕外进展",
    )
    foreshadowing_actions: list[dict] = Field(
        default_factory=list,
        description="伏笔操作列表",
    )
    ending_hook: str | None = Field(
        None,
        description="章节尾钩",
    )
    scene_cards: list[dict] = Field(
        default_factory=list,
        description="场景卡片（JSONB）",
    )
    status: str = Field(
        default="draft",
        max_length=32,
        description="状态",
    )


class ChapterCardUpdate(BaseModel):
    """更新章节卡请求（所有字段可选）"""

    chapter_index: Annotated[int | None, Field(None, ge=1)]
    title: Annotated[str | None, Field(None, max_length=255)]
    arc_id: Annotated[str | None, Field(None)]
    chapter_goal: Annotated[str | None, Field(None)]
    main_conflict: Annotated[str | None, Field(None)]
    emotional_point: Annotated[str | None, Field(None)]
    plot_function: Annotated[str | None, Field(None, max_length=64)]
    must_happen: Annotated[list[str] | None, Field(None)]
    must_not_happen: Annotated[list[str] | None, Field(None)]
    involved_character_ids: Annotated[list[str] | None, Field(None)]
    involved_entity_ids: Annotated[list[str] | None, Field(None)]
    related_thread_ids: Annotated[list[str] | None, Field(None)]
    visible_progress: Annotated[list[str] | None, Field(None)]
    hidden_progress: Annotated[list[str] | None, Field(None)]
    offscreen_progress: Annotated[list[str] | None, Field(None)]
    foreshadowing_actions: Annotated[list[dict] | None, Field(None)]
    ending_hook: Annotated[str | None, Field(None)]
    scene_cards: Annotated[list[dict] | None, Field(None)]
    status: Annotated[str | None, Field(None, max_length=32)]


class ChapterCardResponse(BaseModel):
    """章节卡响应"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    novel_id: str
    chapter_index: int
    title: str | None = None
    arc_id: str | None = None
    chapter_goal: str
    main_conflict: str
    emotional_point: str | None = None
    plot_function: str | None = None
    must_happen: list[str] = []
    must_not_happen: list[str] = []
    involved_character_ids: list[str] = []
    involved_entity_ids: list[str] = []
    related_thread_ids: list[str] = []
    visible_progress: list[str] = []
    hidden_progress: list[str] = []
    offscreen_progress: list[str] = []
    foreshadowing_actions: list[dict] = []
    ending_hook: str | None = None
    scene_cards: list[dict] = []
    status: str = "draft"
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("id", "novel_id", "arc_id", mode="before")
    @classmethod
    def coerce_uuid(cls, v: object) -> str:
        return _uuid_validator(v)


class ChapterCardListResponse(BaseModel):
    """章节卡列表响应"""

    items: list[ChapterCardResponse]
    total: int


# ============================================================
# ForeshadowingPlan Schema
# ============================================================


class ForeshadowingPlanCreate(BaseModel):
    """创建伏笔计划请求"""

    name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="伏笔名称",
    )
    summary: str | None = Field(
        None,
        description="概要",
    )
    surface_meaning: str | None = Field(
        None,
        description="表面含义",
    )
    hidden_meaning: str | None = Field(
        None,
        description="隐藏含义",
    )
    planned_seed_chapter: int | None = Field(
        None,
        ge=1,
        description="计划埋设章节",
    )
    planned_reinforce_chapters: list[int] = Field(
        default_factory=list,
        description="计划加强章节列表",
    )
    planned_payoff_chapter: int | None = Field(
        None,
        ge=1,
        description="计划收束章节",
    )
    related_entity_ids: list[str] = Field(
        default_factory=list,
        description="关联世界对象 ID",
    )
    related_thread_ids: list[str] = Field(
        default_factory=list,
        description="关联剧情线 ID",
    )
    status: str = Field(
        default="draft",
        max_length=32,
        description="状态",
    )


class ForeshadowingPlanUpdate(BaseModel):
    """更新伏笔计划请求（所有字段可选）"""

    name: Annotated[str | None, Field(None, min_length=1, max_length=255)]
    summary: Annotated[str | None, Field(None)]
    surface_meaning: Annotated[str | None, Field(None)]
    hidden_meaning: Annotated[str | None, Field(None)]
    planned_seed_chapter: Annotated[int | None, Field(None, ge=1)]
    planned_reinforce_chapters: Annotated[list[int] | None, Field(None)]
    planned_payoff_chapter: Annotated[int | None, Field(None, ge=1)]
    related_entity_ids: Annotated[list[str] | None, Field(None)]
    related_thread_ids: Annotated[list[str] | None, Field(None)]
    status: Annotated[str | None, Field(None, max_length=32)]


class ForeshadowingPlanResponse(BaseModel):
    """伏笔计划响应"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    novel_id: str
    name: str
    summary: str | None = None
    surface_meaning: str | None = None
    hidden_meaning: str | None = None
    planned_seed_chapter: int | None = None
    planned_reinforce_chapters: list[int] = []
    planned_payoff_chapter: int | None = None
    related_entity_ids: list[str] = []
    related_thread_ids: list[str] = []
    status: str = "draft"
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("id", "novel_id", mode="before")
    @classmethod
    def coerce_uuid(cls, v: object) -> str:
        return _uuid_validator(v)


class ForeshadowingPlanListResponse(BaseModel):
    """伏笔计划列表响应"""

    items: list[ForeshadowingPlanResponse]
    total: int


# ============================================================
# RevealPlan Schema
# ============================================================


class RevealPlanCreate(BaseModel):
    """创建揭示计划请求"""

    target_type: str = Field(
        ...,
        max_length=32,
        description="揭示目标类型",
    )
    target_id: str = Field(
        ...,
        description="揭示目标 ID",
    )
    secret_summary: str = Field(
        ...,
        description="秘密概要",
    )
    reveal_stages: list[dict] = Field(
        default_factory=list,
        description=(
            "揭示阶段列表，每个阶段格式："
            '{"chapter_index": int, "hint_level": str, '
            '"content": str, "revealed_to_reader": bool}'
        ),
    )
    status: str = Field(
        default="draft",
        max_length=32,
        description="状态",
    )


class RevealPlanUpdate(BaseModel):
    """更新揭示计划请求（所有字段可选）"""

    target_type: Annotated[str | None, Field(None, max_length=32)]
    target_id: Annotated[str | None, Field(None)]
    secret_summary: Annotated[str | None, Field(None)]
    reveal_stages: Annotated[list[dict] | None, Field(None)]
    status: Annotated[str | None, Field(None, max_length=32)]


class RevealPlanResponse(BaseModel):
    """揭示计划响应"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    novel_id: str
    target_type: str
    target_id: str
    secret_summary: str
    reveal_stages: list[dict] = []
    status: str = "draft"
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("id", "novel_id", "target_id", mode="before")
    @classmethod
    def coerce_uuid(cls, v: object) -> str:
        return _uuid_validator(v)


class RevealPlanListResponse(BaseModel):
    """揭示计划列表响应"""

    items: list[RevealPlanResponse]
    total: int


# ============================================================
# 候选批量创建章节卡
# ============================================================


class ChapterCardCandidateItem(BaseModel):
    """候选章节卡单项"""

    chapter_index: int = Field(..., ge=1)
    title: str | None = None
    arc_id: str | None = None
    chapter_goal: str
    main_conflict: str
    emotional_point: str | None = None
    plot_function: str | None = None
    must_happen: list[str] = []
    must_not_happen: list[str] = []
    involved_character_ids: list[str] = []
    involved_entity_ids: list[str] = []
    related_thread_ids: list[str] = []
    visible_progress: list[str] = []
    hidden_progress: list[str] = []
    offscreen_progress: list[str] = []
    foreshadowing_actions: list[dict] = []
    ending_hook: str | None = None
    scene_cards: list[dict] = []


class ChapterCardFromCandidateRequest(BaseModel):
    """从候选批量创建章节卡请求"""

    novel_id: str = Field(..., description="项目 ID")
    cards: list[ChapterCardCandidateItem] = Field(
        ...,
        min_length=1,
        max_length=20,
        description="候选章节卡列表（最多 20 张）",
    )


# ============================================================
# Facade 输出 Schema
# ============================================================


class ChapterCardContext(BaseModel):
    """章节卡上下文 — 供其他模块读取"""

    model_config = ConfigDict(from_attributes=True)

    card_id: str
    chapter_index: int
    title: str | None = None
    arc_id: str | None = None
    chapter_goal: str
    main_conflict: str
    emotional_point: str | None = None
    plot_function: str | None = None
    must_happen: list[str] = []
    must_not_happen: list[str] = []
    involved_character_ids: list[str] = []
    involved_entity_ids: list[str] = []
    related_thread_ids: list[str] = []
    visible_progress: list[str] = []
    hidden_progress: list[str] = []
    offscreen_progress: list[str] = []
    foreshadowing_actions: list[dict] = []
    ending_hook: str | None = None
    scene_cards: list[dict] = []
    status: str = "draft"

    @field_validator("card_id", mode="before")
    @classmethod
    def coerce_card_id(cls, v: object) -> str:
        return _uuid_validator(v)


class PlotThreadContext(BaseModel):
    """剧情线上下文 — 供其他模块读取"""

    model_config = ConfigDict(from_attributes=True)

    thread_id: str
    name: str
    thread_type: str
    summary: str | None = None
    visible_goal: str | None = None
    current_stage: str | None = None
    start_chapter: int | None = None
    planned_payoff_chapter: int | None = None
    related_character_ids: list[str] = []
    related_entity_ids: list[str] = []
    status: str = "draft"

    @field_validator("thread_id", mode="before")
    @classmethod
    def coerce_thread_id(cls, v: object) -> str:
        return _uuid_validator(v)


class OutlineArcContext(BaseModel):
    """篇章纲上下文 — 供其他模块读取"""

    model_config = ConfigDict(from_attributes=True)

    arc_id: str
    title: str
    arc_index: int | None = None
    start_chapter: int | None = None
    end_chapter: int | None = None
    arc_goal: str | None = None
    core_conflict: str | None = None
    main_opposition: str | None = None
    entry_hook: str | None = None
    midpoint_turn: str | None = None
    climax: str | None = None
    result: str | None = None
    next_hook: str | None = None
    related_thread_ids: list[str] = []
    related_character_ids: list[str] = []
    related_entity_ids: list[str] = []
    status: str = "draft"

    @field_validator("arc_id", mode="before")
    @classmethod
    def coerce_arc_id(cls, v: object) -> str:
        return _uuid_validator(v)
