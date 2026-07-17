"""Strict internal and HTTP contracts for P20 current-layer outline creation."""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

P20Target = Literal["plot_thread", "outline_arc", "planned_scene"]
P20Mode = Literal["create", "revise"]
P20ResultStatus = Literal["proposed", "no_change", "needs_author_decision"]
P20FieldStatus = Literal["present", "not_applicable", "uncertain"]
P20NarrativeTag = Literal[
    "draft",
    "hook",
    "inciting_incident",
    "rising_action",
    "climax",
    "valley",
    "transition",
    "payoff",
]

RefText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=64),
]
CodeText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=32),
]
ShortText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=4000),
]
TitleText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=255),
]


class P20StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class P20SemanticAudit(P20StrictModel):
    """Internal acceptance audit for a generated current-layer preview."""

    verdict: Literal["pass", "revise"]
    violations: list[ShortText] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_verdict(self) -> P20SemanticAudit:
        if self.verdict == "pass" and self.violations:
            raise ValueError("pass audit cannot include violations")
        if self.verdict == "revise" and not self.violations:
            raise ValueError("revise audit requires at least one violation")
        return self


class OutlineLayerGenerateRequest(P20StrictModel):
    """One page-local P20 generation request."""

    contract_version: Literal["outline_layer_v2"] = "outline_layer_v2"
    novel_id: str
    context_confirmation_id: str
    target: P20Target
    mode: P20Mode
    instruction: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=20000),
    ]
    selected_thread_ids: list[str] = Field(default_factory=list, max_length=100)
    selected_arc_ids: list[str] = Field(default_factory=list, max_length=100)
    selected_scene_ids: list[str] = Field(default_factory=list, max_length=100)
    start_chapter: int | None = Field(default=None, ge=1)
    end_chapter: int | None = Field(default=None, ge=1)

    @field_validator(
        "novel_id",
        "context_confirmation_id",
    )
    @classmethod
    def validate_uuid_field(cls, value: str) -> str:
        return str(uuid.UUID(str(value)))

    @field_validator(
        "selected_thread_ids",
        "selected_arc_ids",
        "selected_scene_ids",
    )
    @classmethod
    def validate_uuid_list(cls, values: list[str]) -> list[str]:
        normalized = [str(uuid.UUID(str(value))) for value in values]
        if len(normalized) != len(set(normalized)):
            raise ValueError("selected IDs must be unique")
        return normalized

    @model_validator(mode="after")
    def validate_target_selection(self) -> OutlineLayerGenerateRequest:
        required = {
            "plot_thread": self.selected_thread_ids,
            "outline_arc": self.selected_arc_ids,
            "planned_scene": self.selected_scene_ids,
        }[self.target]
        if self.mode == "revise" and not required:
            raise ValueError("revise mode requires an explicit current-layer selection")
        if (
            self.start_chapter is not None
            and self.end_chapter is not None
            and self.end_chapter < self.start_chapter
        ):
            raise ValueError("end_chapter must be greater than or equal to start_chapter")
        return self


class P20AuthorDecision(P20StrictModel):
    question: ShortText
    why_it_matters: ShortText
    options: list[ShortText] = Field(default_factory=list)


class P20StoryOutlineConflict(P20StrictModel):
    requested_change: ShortText
    conflict_with_outline: ShortText
    suggested_story_outline_revision: ShortText


class P20ReuseJudgment(P20StrictModel):
    existing_thread_ref: RefText
    judgment: Literal["reuse", "revise", "not_relevant"]
    basis: ShortText


class P20InformationNode(P20StrictModel):
    kind: Literal[
        "seed",
        "reinforce",
        "payoff",
        "partial_reveal",
        "full_reveal",
    ]
    content: ShortText
    chapter_hint: int | None = Field(default=None, ge=1)
    scene_ref: RefText | None = None
    trigger: ShortText | None = None
    effect: ShortText | None = None


class P20InformationMovement(P20StrictModel):
    movement_ref: RefText
    information_subject: ShortText
    surface_understanding: ShortText | None = None
    hidden_content: ShortText | None = None
    target_ref: RefText | None = None
    nodes: list[P20InformationNode] = Field(default_factory=list)
    basis: ShortText
    uncertain_fields: list[
        Literal[
            "information_subject",
            "surface_understanding",
            "hidden_content",
            "target_ref",
            "nodes",
        ]
    ] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_reveal_target(self) -> P20InformationMovement:
        if self.hidden_content is None and "hidden_content" not in self.uncertain_fields:
            # An information movement may organize an unresolved question. Do
            # not force the model to invent a secret merely to satisfy storage.
            self.uncertain_fields.append("hidden_content")
        if any(
            node.kind in {"partial_reveal", "full_reveal"} for node in self.nodes
        ) and not self.target_ref and "target_ref" not in self.uncertain_fields:
            # A missing short reference already proves that the reveal target is
            # unresolved. Normalize that bookkeeping state instead of spending
            # more LLM calls on a marker that does not change the proposal. The
            # apply path keeps the movement and deliberately skips RevealPlan
            # projection until an author or later revision resolves the target.
            self.uncertain_fields.append("target_ref")
        return self


class P20ThreadDraft(P20StrictModel):
    proposal_ref: RefText
    target_thread_ref: RefText | None = None
    name: TitleText
    thread_type: CodeText
    summary: ShortText | None = None
    visible_goal: ShortText | None = None
    hidden_truth: ShortText | None = None
    start_chapter: int | None = Field(default=None, ge=1)
    planned_payoff_chapter: int | None = Field(default=None, ge=1)
    current_stage: CodeText | None = None
    related_character_refs: list[RefText] = Field(default_factory=list)
    related_entity_refs: list[RefText] = Field(default_factory=list)
    reader_known_state: ShortText | None = None
    author_known_state: ShortText | None = None
    information_movements: list[P20InformationMovement] = Field(default_factory=list)
    basis: ShortText
    uncertain_fields: list[
        Literal[
            "name",
            "thread_type",
            "summary",
            "visible_goal",
            "hidden_truth",
            "start_chapter",
            "planned_payoff_chapter",
            "current_stage",
            "related_character_refs",
            "related_entity_refs",
            "reader_known_state",
            "author_known_state",
            "information_movements",
        ]
    ] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)


class P20PlotThreadOutput(P20StrictModel):
    result: P20ResultStatus
    reuse_judgments: list[P20ReuseJudgment] = Field(default_factory=list)
    threads: list[P20ThreadDraft] = Field(default_factory=list)
    story_outline_conflict: P20StoryOutlineConflict | None = None
    author_decisions: list[P20AuthorDecision] = Field(default_factory=list)


class P20ArcDraft(P20StrictModel):
    proposal_ref: RefText
    target_arc_ref: RefText | None = None
    title: TitleText
    arc_index: int | None = Field(default=None, ge=1)
    start_chapter: int | None = Field(default=None, ge=1)
    end_chapter: int | None = Field(default=None, ge=1)
    arc_goal: ShortText | None = None
    core_conflict: ShortText | None = None
    main_opposition: ShortText | None = None
    entry_hook: ShortText | None = None
    midpoint_turn: ShortText | None = None
    climax: ShortText | None = None
    result_state: ShortText | None = None
    next_hook: ShortText | None = None
    related_thread_refs: list[RefText] = Field(default_factory=list)
    related_character_refs: list[RefText] = Field(default_factory=list)
    related_entity_refs: list[RefText] = Field(default_factory=list)
    basis: ShortText
    uncertain_fields: list[
        Literal[
            "title",
            "arc_index",
            "start_chapter",
            "end_chapter",
            "arc_goal",
            "core_conflict",
            "main_opposition",
            "entry_hook",
            "midpoint_turn",
            "climax",
            "result_state",
            "next_hook",
            "related_thread_refs",
            "related_character_refs",
            "related_entity_refs",
        ]
    ] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_range(self) -> P20ArcDraft:
        if (
            self.start_chapter is not None
            and self.end_chapter is not None
            and self.end_chapter < self.start_chapter
        ):
            raise ValueError("arc end_chapter must not precede start_chapter")
        return self


class P20OutlineArcOutput(P20StrictModel):
    result: P20ResultStatus
    arcs: list[P20ArcDraft] = Field(default_factory=list)
    story_outline_conflict: P20StoryOutlineConflict | None = None
    author_decisions: list[P20AuthorDecision] = Field(default_factory=list)


class P20SceneDraft(P20StrictModel):
    proposal_ref: RefText
    target_scene_ref: RefText | None = None
    parent_arc_ref: RefText | None = None
    title: TitleText
    planned_start_chapter: int | None = Field(default=None, ge=1)
    planned_end_chapter: int | None = Field(default=None, ge=1)
    goal: ShortText | None = None
    core_conflict: ShortText | None = None
    core_conflict_status: P20FieldStatus
    emotional_beat: ShortText | None = None
    must_happen: ShortText | None = None
    must_not_happen: ShortText | None = None
    narrative_tag: P20NarrativeTag = "draft"
    narrative_function: ShortText | None = None
    pov_character_ref: RefText | None = None
    related_thread_refs: list[RefText] = Field(default_factory=list)
    related_character_refs: list[RefText] = Field(default_factory=list)
    related_entity_refs: list[RefText] = Field(default_factory=list)
    basis: ShortText
    uncertain_fields: list[
        Literal[
            "title",
            "parent_arc_ref",
            "planned_start_chapter",
            "planned_end_chapter",
            "goal",
            "core_conflict",
            "emotional_beat",
            "must_happen",
            "must_not_happen",
            "narrative_tag",
            "narrative_function",
            "pov_character_ref",
            "related_thread_refs",
            "related_character_refs",
            "related_entity_refs",
        ]
    ] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_scene_semantics(self) -> P20SceneDraft:
        if self.core_conflict_status == "present" and not self.core_conflict:
            raise ValueError("present core_conflict requires content")
        if self.core_conflict_status == "not_applicable" and self.core_conflict:
            raise ValueError("not_applicable core_conflict must be null")
        if (
            self.core_conflict_status == "uncertain"
            and "core_conflict" not in self.uncertain_fields
        ):
            raise ValueError("uncertain core_conflict must be listed in uncertain_fields")
        if (
            self.planned_start_chapter is not None
            and self.planned_end_chapter is not None
            and self.planned_end_chapter < self.planned_start_chapter
        ):
            raise ValueError("planned Scene chapter range is invalid")
        return self

    def semantic_field_statuses(self) -> dict[str, P20FieldStatus]:
        values = {
            "core_conflict": self.core_conflict,
            "emotional_beat": self.emotional_beat,
            "must_happen": self.must_happen,
            "must_not_happen": self.must_not_happen,
            "narrative_tag": (
                None if self.narrative_tag == "draft" else self.narrative_tag
            ),
            "narrative_function": self.narrative_function,
        }
        return {
            field: (
                self.core_conflict_status
                if field == "core_conflict"
                else "uncertain"
                if field in self.uncertain_fields
                else "present"
                if value
                else "not_applicable"
            )
            for field, value in values.items()
        }


class P20PlannedSceneOutput(P20StrictModel):
    result: P20ResultStatus
    scenes: list[P20SceneDraft] = Field(default_factory=list)
    story_outline_conflict: P20StoryOutlineConflict | None = None
    author_decisions: list[P20AuthorDecision] = Field(default_factory=list)


P20_OUTPUT_SCHEMAS = {
    "plot_thread": P20PlotThreadOutput,
    "outline_arc": P20OutlineArcOutput,
    "planned_scene": P20PlannedSceneOutput,
}
