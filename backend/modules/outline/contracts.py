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
    structure_meta: dict = field(default_factory=dict)
    status: str = "draft"


@dataclass
class SceneSpanContract:
    id: str
    novel_id: str
    scene_id: str
    chapter_index: int
    content_mode: str = "canonical"
    source_draft_id: str | None = None
    source_content_hash: str | None = None
    start_offset: int | None = None
    end_offset: int | None = None
    start_paragraph: int | None = None
    end_paragraph: int | None = None
    part_no: int = 0
    mapping_status: str = "chapter_only"
    anchor_hash: str | None = None
    source: str = "manual"
    status: str = "draft"


@dataclass(frozen=True)
class SceneSpanCoverageContract:
    """Project/content-mode SceneSpan location coverage summary."""

    novel_id: str
    content_mode: str
    scene_count: int = 0
    scene_with_span_count: int = 0
    scene_without_span_count: int = 0
    total_span_count: int = 0
    exact_count: int = 0
    reanchored_count: int = 0
    chapter_only_count: int = 0
    unresolved_count: int = 0
    precise_span_count: int = 0
    imprecise_span_count: int = 0
    precise_span_rate: float | None = None
    precise_spans: list[SceneSpanContract] = field(default_factory=list)


@dataclass
class SceneSummaryCheckpointContract:
    id: str
    novel_id: str
    scene_id: str
    content_mode: str
    through_chapter: int
    through_offset: int | None
    summary: str
    source_refs: list[dict] = field(default_factory=list)
    based_on_hash: str = ""
    source: str = "derived"
    status: str = "ready"


@dataclass
class NeighborSceneBriefContract:
    """A spoiler-safe prior Scene summary for context activation."""

    scene_id: str
    novel_id: str
    scene_index: int
    title: str | None = None
    goal: str | None = None
    core_conflict: str | None = None
    emotional_beat: str | None = None
    chapter_indices: list[int] = field(default_factory=list)
    scene_chunks: list[dict] = field(default_factory=list)


@dataclass
class SceneContextWindowContract:
    """Current Scene plus prior-only metadata exposed at the outline seam."""

    novel_id: str
    scene: SceneContract
    scene_spans: list[SceneSpanContract] = field(default_factory=list)
    previous_briefs: list[NeighborSceneBriefContract] = field(default_factory=list)


@dataclass(frozen=True)
class ReaderRevealDecisionContract:
    """Reader-visible state for one target at a conservative chapter cursor."""

    target_type: str
    target_id: str
    has_policy: bool = False
    revealed: bool = True
    reveal_chapter: int | None = None
    reveal_content: str | None = None
