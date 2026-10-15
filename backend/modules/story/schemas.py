"""Strict request, preview, and response schemas for the Story vertical slice."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

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


class CharacterCardFact(StorySchema):
    """Deterministic, source-addressable basis for a generated card."""

    fact_id: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True,
            min_length=3,
            max_length=200,
            pattern=r"^[a-z][a-z0-9_.:-]*$",
        ),
    ]
    kind: Literal[
        "character_profile",
        "world_dossier",
        "legacy_profile_field",
        "story_state",
    ]
    layer: Literal["fact", "belief", "observation"]
    subject_id: str = Field(min_length=1, max_length=128)
    dimension: str = Field(min_length=1, max_length=80)
    field: str = Field(min_length=1, max_length=120)
    value: StoryText
    source_refs: list[dict[str, Any]] = Field(default_factory=list, max_length=16)
    entry_id: str | None = Field(default=None, max_length=128)
    revision_id: str | None = Field(default=None, max_length=128)
    checkpoint_id: str | None = Field(default=None, max_length=128)
    checkpoint_source_hash: str | None = Field(default=None, max_length=128)
    as_of_scene_id: str | None = Field(default=None, max_length=128)
    possibly_false: bool = False


class CharacterCardPattern(StorySchema):
    """Author-only Evolution interpretation retained with its evidence refs."""

    pattern_id: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True,
            min_length=3,
            max_length=200,
            pattern=r"^[a-z][a-z0-9_.:-]*$",
        ),
    ]
    statement: StoryText
    modality: StoryText
    evidence_refs: list[dict[str, Any]] = Field(default_factory=list, max_length=24)


class CharacterCardInterpretation(StorySchema):
    """A non-canonical proposal linked to facts and/or reviewed patterns."""

    category: StoryKey
    statement: StoryText
    source_fact_ids: list[str] = Field(default_factory=list, max_length=16)
    source_pattern_ids: list[str] = Field(default_factory=list, max_length=8)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def require_sources(self) -> CharacterCardInterpretation:
        if not (self.source_fact_ids or self.source_pattern_ids):
            raise ValueError("interpretations require at least one source id")
        if len(set(self.source_fact_ids)) != len(self.source_fact_ids):
            raise ValueError("source_fact_ids must be unique")
        if len(set(self.source_pattern_ids)) != len(self.source_pattern_ids):
            raise ValueError("source_pattern_ids must be unique")
        return self


class CharacterCardContent(StorySchema):
    """Versioned character state used by a Scene, not a replacement World card."""

    version: Literal["character_card.v1", "character_card.v2"] = "character_card.v1"
    story_time: str | None = Field(default=None, max_length=255)
    story_progress: int | None = Field(default=None, ge=0, le=10_000_000)
    personality: StoryText | None = None
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
    fact_basis: list[CharacterCardFact] = Field(default_factory=list, max_length=64)
    pattern_basis: list[CharacterCardPattern] = Field(default_factory=list, max_length=24)
    interpretations: list[CharacterCardInterpretation] = Field(
        default_factory=list, max_length=32
    )

    @model_validator(mode="after")
    def validate_versioned_content(self) -> CharacterCardContent:
        if self.version == "character_card.v1":
            if not self.personality:
                raise ValueError("character_card.v1 requires personality")
            if self.fact_basis or self.pattern_basis or self.interpretations:
                raise ValueError("v1 cards cannot contain v2 provenance fields")
            return self

        legacy_content = (
            self.personality,
            self.current_goal,
            self.current_state,
            self.current_emotion,
            self.desires,
            self.fears,
            self.beliefs,
            self.knowledge,
            self.misconceptions,
            self.voice_style,
            self.behavior_constraints,
            self.relationship_state,
            self.author_notes,
        )
        if any(legacy_content):
            raise ValueError("v2 cards keep generated content in interpretations")
        fact_ids = {item.fact_id for item in self.fact_basis}
        pattern_ids = {item.pattern_id for item in self.pattern_basis}
        if len(fact_ids) != len(self.fact_basis):
            raise ValueError("fact_basis ids must be unique")
        if len(pattern_ids) != len(self.pattern_basis):
            raise ValueError("pattern_basis ids must be unique")
        for interpretation in self.interpretations:
            if not set(interpretation.source_fact_ids).issubset(fact_ids):
                raise ValueError("interpretation references an unknown fact id")
            if not set(interpretation.source_pattern_ids).issubset(pattern_ids):
                raise ValueError("interpretation references an unknown pattern id")
        return self


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
    accepted_reactions: list[ReactionProposal | ReactionProposalV2] = Field(
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


from modules.story.observations import SimulationSeed  # noqa: E402
from modules.story.simulation_v3 import (  # noqa: E402
    SimulationReference,
    SimulationV3Context,
)


class StoryOneClickTaskRequest(StorySchema):
    """One-click simulation consumes one author-reviewed context confirmation."""

    novel_id: str
    scene_id: str
    character_ids: list[str] = Field(default_factory=list)
    context_confirmation_id: str = Field(min_length=1, max_length=128)
    operation_id: uuid.UUID | None = None
    additional_notes: Annotated[
        str | None, StringConstraints(strip_whitespace=True, max_length=4000)
    ] = None
    accepted_reactions: list[ReactionProposal | ReactionProposalV2] = Field(
        default_factory=list, max_length=24
    )
    accepted_beats: list[ScriptBeat] = Field(default_factory=list, max_length=100)
    submit_authorized: bool = False
    use_round_candidates: bool = False
    simulation_protocol: Literal[
        "legacy", "rehearsal_v1", "observation_v2", "simulation_v3"
    ] = "legacy"
    simulation_seed: SimulationSeed | SimulationV3Context | None = None
    rehearsal_rounds: int = Field(default=2, ge=1)
    narrator_character_id: uuid.UUID | None = None
    parent_rehearsal_id: uuid.UUID | None = None
    fork_round: int = Field(default=0, ge=0)
    parent_round_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def bounded_rehearsal(self):
        if self.simulation_protocol == "simulation_v3":
            if "rehearsal_rounds" not in self.model_fields_set:
                self.rehearsal_rounds = 1
            if not self.character_ids:
                raise ValueError("simulation_v3 needs at least one selected actor")
            if self.simulation_seed and not isinstance(
                self.simulation_seed, SimulationV3Context
            ):
                raise ValueError("simulation_v3 requires typed simulation references")
            if isinstance(self.simulation_seed, SimulationV3Context):
                selected = {
                    SimulationReference(kind="object", id=value).state_key
                    for value in self.character_ids
                }
                declared = {
                    participant.state_key
                    for participant in self.simulation_seed.participants
                }
                if declared != selected:
                    raise ValueError(
                        "simulation context participants must match selected actors"
                    )
            if (
                self.narrator_character_id
                and str(self.narrator_character_id) not in self.character_ids
            ):
                raise ValueError("叙述视角必须属于本轮人物")
        elif self.simulation_seed and self.simulation_protocol != "observation_v2":
            raise ValueError("旧协议不能重新解释试验初始状态")
        if self.simulation_seed and self.simulation_protocol == "observation_v2":
            from modules.story.observations import seeded_state

            if not isinstance(self.simulation_seed, SimulationSeed):
                raise ValueError("observation_v2 requires its original simulation seed")
            seeded_state(self.simulation_seed, self.character_ids)
        if self.simulation_protocol in {"rehearsal_v1", "observation_v2"}:
            if not 1 <= len(self.character_ids) <= 3:
                raise ValueError("排演每轮需要一至三名人物")
            if self.rehearsal_rounds > 3 or self.fork_round > 100:
                raise ValueError("旧协议保持原有轮次限制")
            if (
                self.narrator_character_id
                and str(self.narrator_character_id) not in self.character_ids
            ):
                raise ValueError("叙述视角必须属于本轮人物")
            if bool(self.parent_rehearsal_id) != bool(self.parent_round_hash) or (
                self.parent_rehearsal_id and self.fork_round < 1
            ):
                raise ValueError("分叉需要原回合及准确来源版本")
        elif self.simulation_protocol == "simulation_v3":
            if bool(self.parent_rehearsal_id) != bool(self.parent_round_hash) or (
                self.parent_rehearsal_id and self.fork_round < 1
            ):
                raise ValueError("分叉需要原回合及准确来源版本")
        elif self.parent_rehearsal_id:
            raise ValueError("旧推演不能携带排演分叉")
        elif self.simulation_protocol == "legacy" and len(self.character_ids) > 24:
            raise ValueError("普通一键操作最多选择二十四名人物")
        return self

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
    knowledge_review: dict[str, Any] | None = None


class ReactionProposal(StorySchema):
    """Legacy reaction payload retained for saved and accepted v1 history."""

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
    motivations: list[CharacterCardInterpretation] = Field(
        default_factory=list, max_length=4
    )

    @model_validator(mode="after")
    def validate_motivation_count(self) -> ReactionProposal:
        if len(self.motivations) == 1:
            raise ValueError("motivations must be omitted or contain 2 to 4 items")
        return self


class ReactionPreview(StorySchema):
    """Legacy v1 result shape retained for reading earlier task payloads."""

    scene_id: uuid.UUID
    proposals: list[ReactionProposal] = Field(default_factory=list, max_length=24)
    warnings: list[StoryText] = Field(default_factory=list, max_length=20)
    knowledge_review: dict[str, Any] | None = None


class ReactionPerformanceOption(StorySchema):
    """One source-bound, fully staged way the character may react."""

    option_id: StoryKey
    motivation: StoryText
    source_fact_ids: list[str] = Field(default_factory=list, max_length=16)
    source_pattern_ids: list[str] = Field(default_factory=list, max_length=8)
    action: StoryText
    facial_expression: StoryText
    body_language: StoryText
    voice_and_dialogue: StoryText
    inner_response: StoryText
    attention: StoryText
    change: StoryText
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def require_unique_sources(self) -> ReactionPerformanceOption:
        if not (self.source_fact_ids or self.source_pattern_ids):
            raise ValueError("reaction options require at least one source id")
        if len(set(self.source_fact_ids)) != len(self.source_fact_ids):
            raise ValueError("source_fact_ids must be unique")
        if len(set(self.source_pattern_ids)) != len(self.source_pattern_ids):
            raise ValueError("source_pattern_ids must be unique")
        return self


class ReactionProposalV2(StorySchema):
    """New source-bound performance-card format; v1 stays readable above."""

    schema_version: Literal["story.reaction.v2"] = "story.reaction.v2"
    character_id: uuid.UUID
    known_information: list[StoryText] = Field(default_factory=list, max_length=40)
    subjective_judgment: StoryText | None = None
    goal: StoryText | None = None
    conflict: StoryText | None = None
    internal_pressure: StoryText
    performances: list[ReactionPerformanceOption] = Field(min_length=2, max_length=4)

    @model_validator(mode="after")
    def require_distinct_performances(self) -> ReactionProposalV2:
        def normalize(value: str) -> str:
            return " ".join(value.casefold().split())

        motivations = [normalize(item.motivation) for item in self.performances]
        if len(set(motivations)) != len(motivations):
            raise ValueError("reaction performances must use distinct motivations")
        signatures = [
            tuple(
                normalize(getattr(item, field))
                for field in (
                    "action",
                    "facial_expression",
                    "body_language",
                    "voice_and_dialogue",
                    "inner_response",
                    "attention",
                    "change",
                )
            )
            for item in self.performances
        ]
        if len(set(signatures)) != len(signatures):
            raise ValueError("reaction performances must be behaviorally distinct")
        option_ids = [item.option_id for item in self.performances]
        if len(set(option_ids)) != len(option_ids):
            raise ValueError("reaction option ids must be unique")
        return self


class ReactionPreviewV2(StorySchema):
    schema_version: Literal["story.reaction.v2"] = "story.reaction.v2"
    scene_id: uuid.UUID
    proposals: list[ReactionProposalV2] = Field(default_factory=list, max_length=24)
    warnings: list[StoryText] = Field(default_factory=list, max_length=20)
    knowledge_review: dict[str, Any] | None = None


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
    knowledge_review: dict[str, Any] | None = None


class OneClickOutput(StorySchema):
    scene_id: uuid.UUID
    cards: list[CardPreview] = Field(default_factory=list, max_length=24)
    reactions: list[ReactionProposal | ReactionProposalV2] = Field(
        default_factory=list, max_length=24
    )
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
