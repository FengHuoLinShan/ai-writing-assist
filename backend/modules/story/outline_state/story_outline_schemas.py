from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

TitleText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=255),
]
CoreText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=12000),
]
OutlineText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=200000),
]
ListText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=4000),
]
KeyText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=8, max_length=128),
]
ActorText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=128),
]
NoteText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=4000),
]
RefText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=512),
]


class StoryOutlineSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StoryOutlineCreativeCore(StoryOutlineSchema):
    premise: CoreText
    tone_and_reader_promise: CoreText
    story_engine: CoreText
    ending_direction: CoreText | None = None


class StoryOutlineMajorStoryline(StoryOutlineSchema):
    name: TitleText
    narrative_function: CoreText
    trajectory: CoreText
    intersections: list[ListText] = Field(max_length=100)
    resolution_direction: CoreText


class StoryOutlineMacroMovement(StoryOutlineSchema):
    name: TitleText
    story_state_change: CoreText
    advanced_storylines: list[TitleText] = Field(max_length=100)


class StoryOutlineOpenDecision(StoryOutlineSchema):
    question: CoreText
    why_it_matters: CoreText
    options: list[ListText] = Field(max_length=50)


class StoryExecutionProfile(StoryOutlineSchema):
    """Version-bound story-layer constraints for executing one Scene."""

    version: Literal["story_execution_profile.v1"] = "story_execution_profile.v1"
    premise: CoreText
    tone_and_reader_promise: CoreText
    story_engine: CoreText
    ending_direction: CoreText | None = None
    major_storyline_directions: list[ListText] = Field(
        default_factory=list,
        max_length=100,
    )
    macro_state_changes: list[ListText] = Field(default_factory=list, max_length=100)


class StoryOutlineProvenance(StoryOutlineSchema):
    actor: ActorText | None = None
    note: NoteText | None = None
    client_ref: RefText | None = None
    source_refs: list[RefText] = Field(default_factory=list, max_length=100)
    story_execution_profile: StoryExecutionProfile | None = None
    story_execution_profile_hash: str | None = Field(
        default=None,
        min_length=64,
        max_length=64,
    )


class StoryOutlineContent(StoryOutlineSchema):
    title: TitleText
    creative_core: StoryOutlineCreativeCore
    outline_markdown: OutlineText
    major_storylines: list[StoryOutlineMajorStoryline] = Field(max_length=100)
    macro_movements: list[StoryOutlineMacroMovement] = Field(max_length=100)
    open_decisions: list[StoryOutlineOpenDecision] = Field(max_length=100)


class StoryOutlineEvidenceAudit(StoryOutlineSchema):
    """Internal semantic audit for one generated StoryOutline preview."""

    verdict: Literal["pass", "revise"]
    violations: list[ListText] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_verdict(self) -> StoryOutlineEvidenceAudit:
        if self.verdict == "pass" and self.violations:
            raise ValueError("pass audit cannot include violations")
        if self.verdict == "revise" and not self.violations:
            raise ValueError("revise audit requires at least one violation")
        return self


class StoryOutlineGenerateRequest(StoryOutlineSchema):
    novel_id: str
    context_confirmation_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
    )
    author_intent: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=20000),
    ]
    planned_scale: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=4000),
    ]
    coverage: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=4000),
    ]
    selected_character_ids: list[str] = Field(default_factory=list, max_length=12)
    selected_entity_ids: list[str] = Field(default_factory=list, max_length=24)
    include_current_outline: bool = False
    base_revision_id: uuid.UUID | None = None
    operation_id: uuid.UUID | None = None

    @field_validator("novel_id")
    @classmethod
    def validate_novel_id(cls, value: str) -> str:
        return str(uuid.UUID(str(value)))

    @field_validator("selected_character_ids", "selected_entity_ids")
    @classmethod
    def validate_selected_ids(cls, value: list[str]) -> list[str]:
        normalized = [str(uuid.UUID(str(item))) for item in value]
        if len(set(normalized)) != len(normalized):
            raise ValueError("selected IDs must be unique")
        return normalized

    @model_validator(mode="after")
    def validate_outline_source(self) -> StoryOutlineGenerateRequest:
        if self.include_current_outline and self.base_revision_id is not None:
            raise ValueError(
                "include_current_outline and base_revision_id are mutually exclusive"
            )
        return self


class StoryOutlineRevisionCreate(StoryOutlineContent):
    base_revision_id: uuid.UUID | None
    idempotency_key: KeyText
    source: Literal["manual"] = "manual"
    provenance: StoryOutlineProvenance = Field(default_factory=StoryOutlineProvenance)


class StoryOutlineRevisionApply(StoryOutlineSchema):
    base_revision_id: uuid.UUID | None
    idempotency_key: KeyText
    confirmed: Literal[True]
    provenance: StoryOutlineProvenance = Field(default_factory=StoryOutlineProvenance)


class StoryOutlineGeneratedPreviewApply(StoryOutlineContent):
    novel_id: str
    source_task_id: uuid.UUID
    base_revision_id: uuid.UUID | None
    idempotency_key: KeyText
    confirmed: Literal[True]

    @field_validator("novel_id")
    @classmethod
    def validate_novel_id(cls, value: str) -> str:
        return str(uuid.UUID(str(value)))


class StoryOutlineRevisionResponse(StoryOutlineContent):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: uuid.UUID
    novel_id: uuid.UUID
    version_number: int = Field(ge=1)
    source: Literal["manual", "ai_generated", "restored"]
    provenance: StoryOutlineProvenance
    base_revision_id: uuid.UUID | None
    restored_from_revision_id: uuid.UUID | None
    content_hash: str = Field(min_length=64, max_length=64)
    created_at: datetime
    is_current: bool


class StoryOutlineCurrentResponse(StoryOutlineSchema):
    current_revision_id: uuid.UUID | None
    revision: StoryOutlineRevisionResponse | None


class StoryOutlineRevisionListResponse(StoryOutlineSchema):
    items: list[StoryOutlineRevisionResponse]
    total: int = Field(ge=0)
    skip: int = Field(ge=0)
    limit: int = Field(ge=1)
