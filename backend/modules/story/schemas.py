"""Strict request, preview, and response schemas for the Story vertical slice."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

StoryText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=12000)
]
LongStoryText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=200000),
]
StoryKey = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_.-]*$"
    ),
]


class StorySchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CharacterCardContent(StorySchema):
    """Versioned character state used by a Scene, not a replacement World card."""

    version: Literal["character_card.v1"] = "character_card.v1"
    story_time: str | None = Field(default=None, max_length=255)
    story_progress: int | None = Field(default=None, ge=0, le=10_000_000)
    personality: StoryText
    current_goal: StoryText | None = None
    current_state: StoryText | None = None
    current_emotion: StoryText | None = None
    desires: list[StoryText] = Field(default_factory=list, max_length=20)
    fears: list[StoryText] = Field(default_factory=list, max_length=20)
    beliefs: list[StoryText] = Field(default_factory=list, max_length=20)
    knowledge: list[StoryText] = Field(default_factory=list, max_length=100)
    misconceptions: list[StoryText] = Field(default_factory=list, max_length=50)
    voice_style: StoryText | None = None
    behavior_constraints: list[StoryText] = Field(default_factory=list, max_length=30)
    relationship_state: dict[str, StoryText] = Field(default_factory=dict, max_length=50)
    author_notes: str | None = Field(default=None, max_length=12000)


class CardRevisionCreate(StorySchema):
    novel_id: str
    scene_id: str
    character_id: str
    content: CharacterCardContent
    expected_revision_id: uuid.UUID | None = None
    confirmed: Literal[True]
    source_manifest: dict[str, Any] = Field(default_factory=dict, max_length=40)

    source_task_id: uuid.UUID | None = None
    context_snapshot_id: uuid.UUID | None = None

    @field_validator("novel_id", "scene_id", "character_id")
    @classmethod
    def normalize_uuid(cls, value: str) -> str:
        return str(uuid.UUID(str(value)))


class CardRestoreRequest(StorySchema):
    novel_id: str
    revision_id: uuid.UUID
    expected_revision_id: uuid.UUID | None = None
    confirmed: Literal[True]

    @field_validator("novel_id")
    @classmethod
    def normalize_novel_id(cls, value: str) -> str:
        return str(uuid.UUID(str(value)))


class CardArchiveRequest(StorySchema):
    novel_id: str
    expected_revision_id: uuid.UUID | None = None
    confirmed: Literal[True]

    @field_validator("novel_id")
    @classmethod
    def normalize_novel_id(cls, value: str) -> str:
        return str(uuid.UUID(str(value)))


class CharacterCardRevisionResponse(StorySchema):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: uuid.UUID
    card_id: uuid.UUID
    novel_id: uuid.UUID
    character_id: uuid.UUID
    scene_id: uuid.UUID
    version_number: int = Field(ge=1)
    content: CharacterCardContent
    content_hash: str = Field(min_length=64, max_length=64)
    source: str
    status: str
    authorization_ref: str | None = None
    source_manifest: dict[str, Any] = Field(default_factory=dict)
    source_task_id: uuid.UUID | None = None
    context_snapshot_id: uuid.UUID | None = None
    base_revision_id: uuid.UUID | None = None
    restored_from_revision_id: uuid.UUID | None = None
    created_at: datetime
    is_current: bool = False
    is_adopted: bool = False


class CharacterCardResponse(StorySchema):
    id: uuid.UUID
    novel_id: uuid.UUID
    character_id: uuid.UUID
    scene_id: uuid.UUID
    current_revision_id: uuid.UUID | None = None
    current_version_number: int = Field(ge=0)
    status: str
    stale: bool
    stale_reason: str | None = None
    revision: CharacterCardRevisionResponse | None = None
    updated_at: datetime | None = None


class CharacterCardListResponse(StorySchema):
    items: list[CharacterCardResponse]
    total: int


class SceneScriptFileCreate(StorySchema):
    novel_id: str
    scene_id: str
    file_key: StoryKey
    title: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)
    ]
    confirmed: Literal[True]

    @field_validator("novel_id", "scene_id")
    @classmethod
    def normalize_uuid(cls, value: str) -> str:
        return str(uuid.UUID(str(value)))


class SceneScriptRevisionCreate(StorySchema):
    novel_id: str
    scene_id: str
    file_key: StoryKey
    content: LongStoryText
    content_json: dict[str, Any] | list[Any] | None = None
    expected_revision_id: uuid.UUID | None = None
    adopt: bool = False
    confirmed: Literal[True]
    provenance: dict[str, Any] = Field(default_factory=dict, max_length=40)
    source_task_id: uuid.UUID | None = None
    context_snapshot_id: uuid.UUID | None = None

    @field_validator("novel_id", "scene_id")
    @classmethod
    def normalize_uuid(cls, value: str) -> str:
        return str(uuid.UUID(str(value)))


class SceneScriptAdoptRequest(StorySchema):
    novel_id: str
    expected_revision_id: uuid.UUID | None = None
    confirmed: Literal[True]

    @field_validator("novel_id")
    @classmethod
    def normalize_novel_id(cls, value: str) -> str:
        return str(uuid.UUID(str(value)))


class SceneScriptArchiveRequest(StorySchema):
    novel_id: str
    confirmed: Literal[True]

    @field_validator("novel_id")
    @classmethod
    def normalize_novel_id(cls, value: str) -> str:
        return str(uuid.UUID(str(value)))


class SceneScriptUnadoptRequest(StorySchema):
    novel_id: str
    expected_revision_id: uuid.UUID
    confirmed: Literal[True]

    @field_validator("novel_id")
    @classmethod
    def normalize_novel_id(cls, value: str) -> str:
        return str(uuid.UUID(str(value)))


class SceneScriptRevisionResponse(StorySchema):
    id: uuid.UUID
    file_id: uuid.UUID
    novel_id: uuid.UUID
    scene_id: uuid.UUID
    file_key: str
    version_number: int = Field(ge=1)
    content: str
    content_json: dict[str, Any] | list[Any] | None = None
    content_hash: str = Field(min_length=64, max_length=64)
    source: str
    status: str
    authorization_ref: str | None = None
    provenance: dict[str, Any] = Field(default_factory=dict)
    source_task_id: uuid.UUID | None = None
    context_snapshot_id: uuid.UUID | None = None
    base_revision_id: uuid.UUID | None = None
    created_at: datetime
    is_current: bool = False
    is_adopted: bool = False


class SceneScriptFileResponse(StorySchema):
    id: uuid.UUID
    novel_id: uuid.UUID
    scene_id: uuid.UUID
    file_key: str
    title: str
    current_revision_id: uuid.UUID | None = None
    current_version_number: int = Field(ge=0)
    adopted_revision_id: uuid.UUID | None = None
    adopted_version_number: int = Field(ge=0)
    status: str
    revision: SceneScriptRevisionResponse | None = None
    adopted_revision: SceneScriptRevisionResponse | None = None
    updated_at: datetime | None = None


class SceneScriptFileListResponse(StorySchema):
    items: list[SceneScriptFileResponse]
    total: int


class StoryTaskRequest(StorySchema):
    novel_id: str
    scene_id: str
    character_ids: list[str] = Field(default_factory=list, max_length=24)
    context_confirmation_id: str = Field(min_length=1, max_length=128)
    operation_id: uuid.UUID | None = None
    additional_notes: Annotated[
        str | None, StringConstraints(strip_whitespace=True, max_length=4000)
    ] = None
    accepted_reactions: list[ReactionProposal] = Field(
        default_factory=list, max_length=24
    )
    accepted_beats: list[ScriptBeat] = Field(default_factory=list, max_length=100)
    confirmed: Literal[True]

    @field_validator("novel_id", "scene_id")
    @classmethod
    def normalize_uuid(cls, value: str) -> str:
        return str(uuid.UUID(str(value)))

    @field_validator("character_ids")
    @classmethod
    def normalize_character_ids(cls, values: list[str]) -> list[str]:
        normalized = [str(uuid.UUID(str(value))) for value in values]
        if len(normalized) != len(set(normalized)):
            raise ValueError("character_ids must be unique")
        return normalized


class StoryCardTaskRequest(StorySchema):
    novel_id: str
    character_id: str
    scene_id: str
    context_confirmation_id: str = Field(min_length=1, max_length=128)
    operation_id: uuid.UUID | None = None
    additional_notes: Annotated[
        str | None, StringConstraints(strip_whitespace=True, max_length=4000)
    ] = None
    confirmed: Literal[True]

    @field_validator("novel_id", "character_id", "scene_id")
    @classmethod
    def normalize_uuid(cls, value: str) -> str:
        return str(uuid.UUID(str(value)))


class StoryOneClickTaskRequest(StorySchema):
    """One-click simulation consumes one author-reviewed context confirmation."""

    novel_id: str
    scene_id: str
    character_ids: list[str] = Field(default_factory=list, max_length=24)
    context_confirmation_id: str = Field(min_length=1, max_length=128)
    operation_id: uuid.UUID | None = None
    additional_notes: Annotated[
        str | None, StringConstraints(strip_whitespace=True, max_length=4000)
    ] = None
    accepted_reactions: list[ReactionProposal] = Field(
        default_factory=list, max_length=24
    )
    accepted_beats: list[ScriptBeat] = Field(default_factory=list, max_length=100)
    submit_authorized: bool = False

    @field_validator("novel_id", "scene_id")
    @classmethod
    def normalize_uuid(cls, value: str) -> str:
        return str(uuid.UUID(str(value)))

    @field_validator("character_ids")
    @classmethod
    def normalize_character_ids(cls, values: list[str]) -> list[str]:
        normalized = [str(uuid.UUID(str(value))) for value in values]
        if len(normalized) != len(set(normalized)):
            raise ValueError("character_ids must be unique")
        return normalized


class StoryTaskResponse(StorySchema):
    task_id: str
    status: str


class CardPreview(StorySchema):
    character_id: uuid.UUID
    content: CharacterCardContent
    warnings: list[StoryText] = Field(default_factory=list, max_length=20)


class ReactionProposal(StorySchema):
    character_id: uuid.UUID
    known_information: list[StoryText] = Field(default_factory=list, max_length=40)
    subjective_judgment: StoryText | None = None
    goal: StoryText | None = None
    immediate_reaction: StoryText | None = None
    action_choices: list[StoryText] = Field(default_factory=list, max_length=12)
    dialogue_tendency: StoryText | None = None
    conflict: StoryText | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    intended_action: StoryText
    internal_pressure: StoryText
    knowledge_basis: list[StoryText] = Field(default_factory=list, max_length=20)
    alternatives: list[StoryText] = Field(default_factory=list, max_length=8)


class ReactionPreview(StorySchema):
    scene_id: uuid.UUID
    proposals: list[ReactionProposal] = Field(default_factory=list, max_length=24)
    warnings: list[StoryText] = Field(default_factory=list, max_length=20)


class ScriptBeat(StorySchema):
    beat_id: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)
    ]
    purpose: StoryText
    actors: list[uuid.UUID] = Field(default_factory=list, max_length=24)
    action: StoryText
    consequence: StoryText
    hard_anchor: bool = False


class ScriptPreview(StorySchema):
    scene_id: uuid.UUID
    beats: list[ScriptBeat] = Field(default_factory=list, max_length=100)
    script_text: LongStoryText
    narrative_plan: LongStoryText
    unresolved_questions: list[StoryText] = Field(default_factory=list, max_length=20)
    warnings: list[StoryText] = Field(default_factory=list, max_length=20)


class OneClickOutput(StorySchema):
    scene_id: uuid.UUID
    cards: list[CardPreview] = Field(default_factory=list, max_length=24)
    reactions: list[ReactionProposal] = Field(default_factory=list, max_length=24)
    script: ScriptPreview


class OneClickTaskResult(StorySchema):
    preview: OneClickOutput
    context_snapshot_id: uuid.UUID | None = None
    persisted_card_revision_ids: list[uuid.UUID] = Field(
        default_factory=list, max_length=24
    )
    skipped_fresh_character_ids: list[uuid.UUID] = Field(
        default_factory=list, max_length=24
    )
    preview_only_writes: list[str] = Field(default_factory=list)


class StorySceneContextResponse(StorySchema):
    novel_id: uuid.UUID
    scene_id: uuid.UUID
    outline_bundle: dict[str, Any]
    character_cards: list[CharacterCardResponse] = Field(default_factory=list)
    script_files: list[SceneScriptFileResponse] = Field(default_factory=list)
    omissions: list[str] = Field(default_factory=list)
    upstream_manifest: list[dict[str, str]] = Field(default_factory=list)
    context_hash: str = Field(min_length=64, max_length=64)


# The task request is declared before the preview payload classes so the public
# request/response section stays together.  Resolve its strict forward refs at
# module load time rather than weakening accepted reaction/beat validation to
# arbitrary JSON.
StoryTaskRequest.model_rebuild()
StoryOneClickTaskRequest.model_rebuild()
