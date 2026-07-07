"""剧情结构生成器内部使用的 Pydantic 模型。

这些模型只描述 LLM 输出结构，不暴露为跨模块契约。
"""

from __future__ import annotations

from pydantic import BaseModel


class GeneratedThread(BaseModel):
    name: str
    thread_type: str
    summary: str | None = None
    visible_goal: str | None = None
    hidden_truth: str | None = None
    start_chapter: int | None = None
    planned_payoff_chapter: int | None = None
    current_stage: str | None = None
    related_character_names: list[str] = []
    related_entity_names: list[str] = []


class GeneratedArc(BaseModel):
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
    related_character_names: list[str] = []
    related_entity_names: list[str] = []
    related_thread_names: list[str] = []


class ForeshadowingPlan(BaseModel):
    name: str = ""
    summary: str | None = None
    planned_seed_chapter: int | None = None
    planned_payoff_chapter: int | None = None
    status: str = "draft"


class RevealPlan(BaseModel):
    target_name: str = ""
    target_type: str = "world_entity"
    secret_summary: str | None = None
    status: str = "draft"


class OffscreenProgress(BaseModel):
    thread_name: str = ""
    offscreen_description: str | None = None
    importance: str = "medium"


class Risk(BaseModel):
    risk_type: str = "其他"
    description: str | None = None
    severity: str = "medium"


class Question(BaseModel):
    question: str = ""
    context: str | None = None
    suggested_options: list[str] = []


class GeneratedScene(BaseModel):
    title: str
    goal: str | None = None
    core_conflict: str | None = None
    emotional_beat: str | None = None
    must_happen: str | None = None
    must_not_happen: str | None = None
    narrative_tag: str | None = None
    chapter_start: int | None = None
    chapter_end: int | None = None
    scene_chunks: list[dict] = []


class GeneratedOutput(BaseModel):
    plot_threads: list[GeneratedThread] = []
    outline_arcs: list[GeneratedArc] = []
    scenes: list[GeneratedScene] = []
    foreshadowing_plans: list[ForeshadowingPlan] = []
    reveal_plans: list[RevealPlan] = []
    offscreen_progress: list[OffscreenProgress] = []
    risks: list[Risk] = []
    questions_for_user: list[Question] = []


class SimpleSupportedStructureItem(BaseModel):
    title: str = ""
    summary: str = ""
    confidence: float = 0.7
    needs_review: bool = False
    review_reason: str = ""
    supporting_scene_ids: list[str] = []


class SimplePlotThread(SimpleSupportedStructureItem):
    thread_type: str = "main"
    current_stage: str = "active"


class SimpleCharacterArc(SimpleSupportedStructureItem):
    character_name: str = ""


class SimpleStructureOutput(BaseModel):
    plot_threads: list[SimplePlotThread] = []
    arcs: list[SimpleCharacterArc] = []
    foreshadowing: list[SimpleSupportedStructureItem] = []
    reveals: list[SimpleSupportedStructureItem] = []
    turning_points: list[SimpleSupportedStructureItem] = []
    uncertain_items: list[dict] = []
