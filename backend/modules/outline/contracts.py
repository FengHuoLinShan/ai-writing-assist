from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PlotThreadContract:
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
    related_character_ids: list = field(default_factory=list)
    related_entity_ids: list = field(default_factory=list)
    reader_known_state: str | None = None
    author_known_state: str | None = None
    status: str = "draft"


@dataclass
class OutlineArcContract:
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
    related_thread_ids: list = field(default_factory=list)
    related_character_ids: list = field(default_factory=list)
    related_entity_ids: list = field(default_factory=list)
    status: str = "draft"


@dataclass
class SceneContract:
    id: str
    novel_id: str
    scene_index: int
    title: str | None = None
    goal: str | None = None
    core_conflict: str | None = None
    emotional_beat: str | None = None
    must_happen: str | None = None
    must_not_happen: str | None = None
    narrative_tag: str = "draft"
    source: str = "manual"
    scene_chunks: list = field(default_factory=list)
    chapter_ids: list = field(default_factory=list)
    pov_character_id: str | None = None
    status: str = "draft"
