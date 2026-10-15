"""Strict author contracts for Story's candidate world-progression engine."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _uuid(value: object) -> str:
    return str(uuid.UUID(str(value)))


class ProgressionModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ProgressionTarget(ProgressionModel):
    kind: Literal["outline_arc", "plot_thread", "planned_scene"]
    id: str
    must_reach: bool = False

    @field_validator("id")
    @classmethod
    def valid_id(cls, value: str) -> str:
        return _uuid(value)


class ProgressionParticipant(ProgressionModel):
    id: str
    kind: Literal["character", "group"] = "character"

    @field_validator("id")
    @classmethod
    def valid_id(cls, value: str) -> str:
        return _uuid(value)


class ProgressionLocationTarget(ProgressionModel):
    kind: Literal["object", "map_node"]
    id: str

    @field_validator("id")
    @classmethod
    def valid_id(cls, value: str) -> str:
        return _uuid(value)


class ProgressionStatusUpdate(ProgressionModel):
    actor_id: str
    field: Literal["condition", "goal", "commitment", "presence"]
    value: str = Field(min_length=1, max_length=1200)
    basis_ids: list[str] = Field(min_length=1)

    @field_validator("actor_id")
    @classmethod
    def valid_actor(cls, value: str) -> str:
        return _uuid(value)


class ProgressionAttitudeUpdate(ProgressionModel):
    subject_id: str
    target_id: str
    stance: Literal["trust", "distrust", "hostile", "friendly", "neutral", "uncertain"]
    degree: int = Field(ge=-3, le=3)
    basis_ids: list[str] = Field(min_length=1)

    @field_validator("subject_id", "target_id")
    @classmethod
    def valid_endpoint(cls, value: str) -> str:
        return _uuid(value)


class ProgressionResourceUpdate(ProgressionModel):
    resource_key: str = Field(min_length=1, max_length=160)
    holder_id: str | None = None
    basis_ids: list[str] = Field(min_length=1)

    @field_validator("holder_id")
    @classmethod
    def valid_holder(cls, value: str | None) -> str | None:
        return _uuid(value) if value else None


class ProgressionKnowledgeUpdate(ProgressionModel):
    receiver_id: str
    subject_key: str = Field(min_length=1, max_length=160)
    statement: str = Field(min_length=1, max_length=1200)
    modality: Literal["direct_observation", "reported_claim", "uncertain"]
    source_actor_id: str | None = None
    source_event_id: str | None = None

    @field_validator("receiver_id", "source_actor_id")
    @classmethod
    def valid_knowledge_actor(cls, value: str | None) -> str | None:
        return _uuid(value) if value else None

    @model_validator(mode="after")
    def reported_claim_needs_actor(self):
        if self.modality == "reported_claim" and not (
            self.source_actor_id and self.source_event_id
        ):
            raise ValueError("传闻必须绑定说法来源人物与当前可见事件")
        if self.modality == "direct_observation" and not self.source_event_id:
            raise ValueError("直接观察必须绑定当前或既有可见事件")
        return self


class ProgressionHookCandidate(ProgressionModel):
    title: str = Field(min_length=1, max_length=255)
    summary: str = Field(min_length=1, max_length=4000)
    basis_ids: list[str] = Field(min_length=1)
    actor_ids: list[str] = Field(default_factory=list)
    start_chapter: int | None = Field(default=None, ge=1)
    end_chapter: int | None = Field(default=None, ge=1)

    @field_validator("actor_ids")
    @classmethod
    def valid_hook_actors(cls, values: list[str]) -> list[str]:
        return [_uuid(value) for value in values]


class ProgressionIntersectionOutcome(ProgressionModel):
    intersection_id: str = Field(min_length=1, max_length=64)
    actor_ids: list[str] = Field(min_length=2)
    outcome: Literal["succeeded", "failed", "uncertain"]
    description: str = Field(min_length=1, max_length=1600)

    @field_validator("actor_ids")
    @classmethod
    def valid_intersection_actors(cls, values: list[str]) -> list[str]:
        return [_uuid(value) for value in values]


class ProgressionTargetOutcome(ProgressionModel):
    target_id: str
    status: Literal["completed", "blocked", "in_progress", "uncertain"]
    reason: str = Field(min_length=1, max_length=1200)

    @field_validator("target_id")
    @classmethod
    def valid_target_id(cls, value: str) -> str:
        return _uuid(value)


class ProgressionTargetPath(ProgressionModel):
    target_id: str
    actor_ids: list[str] = Field(default_factory=list)
    basis_ids: list[str] = Field(min_length=1)
    rationale: str = Field(min_length=1, max_length=1600)

    @field_validator("target_id")
    @classmethod
    def valid_target(cls, value: str) -> str:
        return _uuid(value)

    @field_validator("actor_ids")
    @classmethod
    def valid_path_actors(cls, values: list[str]) -> list[str]:
        return [_uuid(value) for value in values]


class ProgressionBudgetPreviewRequest(ProgressionModel):
    novel_id: str
    scene_id: str | None = None
    request_limit: int = Field(ge=1)
    token_limit: int = Field(ge=1)
    time_budget_seconds: int = Field(ge=1)
    participants: list[ProgressionParticipant] = Field(min_length=1)
    mode: Literal["free", "directed"] = "free"
    step_length: Literal[
        "auto", "day", "week", "month", "season", "year", "next_beat"
    ] = "auto"
    run_policy: Literal["one_step", "n_steps", "until_goal", "until_budget"] = "one_step"
    steps: int | None = Field(default=None, ge=1)
    stop_at_goal: bool = True
    targets: list[ProgressionTarget] = Field(default_factory=list)
    instructions: str = Field(default="", max_length=6000)
    retained_constraints: list[str] = Field(default_factory=list)

    @field_validator("novel_id", "scene_id")
    @classmethod
    def valid_ids(cls, value: str | None) -> str | None:
        return _uuid(value) if value is not None else None

    @model_validator(mode="after")
    def valid_policy(self):
        ids = [item.id for item in self.participants]
        if len(ids) != len(set(ids)):
            raise ValueError("参与者不能重复")
        if self.mode == "directed" and not (self.instructions.strip() or self.targets):
            raise ValueError("导向推进需要作者文字或已有结构目标")
        if self.run_policy == "one_step" and self.steps not in (None, 1):
            raise ValueError("单步推进只运行一步")
        if self.run_policy == "n_steps" and self.steps is None:
            raise ValueError("连续步数模式需要作者填写步数")
        if self.run_policy != "n_steps" and self.steps is not None:
            raise ValueError("只有连续步数模式接受步数")
        if self.run_policy == "until_goal" and not self.targets:
            raise ValueError("到达目标模式需要至少一个目标节点")
        return self


class ProgressionStartRequest(ProgressionBudgetPreviewRequest):
    operation_id: uuid.UUID
    context_confirmation_id: str = Field(min_length=1, max_length=128)
    budget_preview_hash: str = Field(pattern="^[a-f0-9]{64}$")


class ProgressionAdvanceRequest(ProgressionModel):
    novel_id: str
    root_id: uuid.UUID
    branch_id: uuid.UUID
    parent_step_id: uuid.UUID
    basis_choice: Literal["current", "frozen"]
    context_confirmation_id: str = Field(min_length=1, max_length=128)
    step_length: (
        Literal["auto", "day", "week", "month", "season", "year", "next_beat"] | None
    ) = None
    operation_id: uuid.UUID

    @field_validator("novel_id")
    @classmethod
    def valid_project(cls, value: str) -> str:
        return _uuid(value)


class ProgressionHistoryRequest(ProgressionModel):
    novel_id: str
    scene_id: str | None = None
    root_id: uuid.UUID | None = None

    @field_validator("novel_id", "scene_id")
    @classmethod
    def valid_identity(cls, value: str | None) -> str | None:
        return _uuid(value) if value is not None else None


class ProgressionCompareRequest(ProgressionModel):
    novel_id: str
    first_step_id: uuid.UUID
    second_step_id: uuid.UUID

    @field_validator("novel_id")
    @classmethod
    def valid_project(cls, value: str) -> str:
        return _uuid(value)


class ProgressionMetadataRequest(ProgressionModel):
    novel_id: str
    name: str | None = Field(default=None, max_length=180)
    note: str | None = Field(default=None, max_length=4000)
    starred: bool | None = None
    expected_updated_at: str

    @field_validator("novel_id")
    @classmethod
    def valid_project(cls, value: str) -> str:
        return _uuid(value)


class ProgressionDeleteRequest(ProgressionModel):
    novel_id: str
    confirm: bool = False

    @field_validator("novel_id")
    @classmethod
    def valid_project(cls, value: str) -> str:
        return _uuid(value)


class ProgressionHookPreviewRequest(ProgressionModel):
    novel_id: str
    root_id: uuid.UUID
    step_id: uuid.UUID
    hook_id: str
    asset_type: Literal["plot_thread", "outline_arc", "planned_scene"]
    operation_id: uuid.UUID
    context_confirmation_id: str = Field(min_length=1, max_length=128)
    start_chapter: int | None = Field(default=None, ge=1)
    end_chapter: int | None = Field(default=None, ge=1)
    draft: dict = Field(default_factory=dict)

    @field_validator("novel_id")
    @classmethod
    def valid_project(cls, value: str) -> str:
        return _uuid(value)


class ProgressionHookAdoptRequest(ProgressionHookPreviewRequest):
    preview_hash: str = Field(pattern="^[a-f0-9]{64}$")
    context_confirmation_id: str = Field(min_length=1, max_length=128)


class ProgressionContinuousAuthorizationRequest(ProgressionModel):
    novel_id: str
    enabled: bool
    participant_ids: list[str] = Field(default_factory=list)
    every_new_chapters: int = Field(default=3, ge=1)
    context_confirmation_id: str | None = Field(
        default=None, min_length=1, max_length=128
    )
    expected_revision: int | None = Field(default=None, ge=0)

    @field_validator("novel_id")
    @classmethod
    def valid_project(cls, value: str) -> str:
        return _uuid(value)

    @field_validator("participant_ids")
    @classmethod
    def valid_participants(cls, values: list[str]) -> list[str]:
        result = [_uuid(value) for value in values]
        if len(result) != len(set(result)):
            raise ValueError("参与者不能重复")
        return result

    @model_validator(mode="after")
    def enabled_requires_scope(self):
        if self.enabled and (
            not self.participant_ids or not self.context_confirmation_id
        ):
            raise ValueError("开启持续推进需要选择参与者并确认资料")
        return self


class ProgressionActorIntent(ProgressionModel):
    actor_id: str
    kind: Literal["action", "speak"] = "action"
    action: str = Field(min_length=1, max_length=2400)
    reason: str = Field(default="", max_length=1200)
    basis_ids: list[str] = Field(min_length=1)
    location_target: ProgressionLocationTarget | None = None
    target_object_id: str | None = None
    resource_key: str | None = Field(default=None, max_length=160)
    journey_route_ids: list[str] = Field(default_factory=list)
    information_recipient_ids: list[str] = Field(default_factory=list)
    information_summary_key: str | None = Field(default=None, max_length=160)
    effect: Literal["none", "move", "leave", "resource_transfer"] = "none"
    visibility: Literal["public", "private", "whisper"] = "public"

    @field_validator("actor_id", "target_object_id")
    @classmethod
    def valid_optional_ids(cls, value: str | None) -> str | None:
        return _uuid(value) if value is not None else None

    @field_validator("journey_route_ids")
    @classmethod
    def valid_route_refs(cls, values: list[str]) -> list[str]:
        if any(
            len(value) != 64 or any(char not in "0123456789abcdef" for char in value)
            for value in values
        ):
            raise ValueError("行程交汇只能引用当前资料中的结构化路线身份")
        return values

    @field_validator("information_recipient_ids")
    @classmethod
    def valid_recipient_ids(cls, values: list[str]) -> list[str]:
        return [_uuid(value) for value in values]

    @model_validator(mode="after")
    def effect_references(self):
        if self.effect == "move" and self.location_target is None:
            raise ValueError("移动意图需要结构化地点或地图节点 ID")
        if self.effect == "resource_transfer" and not self.resource_key:
            raise ValueError("资源转移需要已有 resource_key")
        if self.effect == "resource_transfer" and not self.target_object_id:
            raise ValueError("资源转移需要结构化接收对象 ID")
        return self


class ProgressionActorDraft(ProgressionModel):
    intent: ProgressionActorIntent


class ProgressionStepResolution(ProgressionModel):
    story_time_text: str = Field(min_length=1, max_length=240)
    narrative_summary: str = Field(min_length=1, max_length=4000)
    outcomes: dict[str, Literal["succeeded", "failed", "uncertain"]]
    status_updates: list[ProgressionStatusUpdate] = Field(default_factory=list)
    attitude_updates: list[ProgressionAttitudeUpdate] = Field(default_factory=list)
    resource_updates: list[ProgressionResourceUpdate] = Field(default_factory=list)
    knowledge_updates: list[ProgressionKnowledgeUpdate] = Field(default_factory=list)
    intersections: list[ProgressionIntersectionOutcome] = Field(default_factory=list)
    goal_outcomes: list[ProgressionTargetOutcome] = Field(default_factory=list)
    plot_hooks: list[ProgressionHookCandidate] = Field(default_factory=list)
    target_paths: list[ProgressionTargetPath] = Field(default_factory=list)
    setup_needed: list[str] = Field(default_factory=list)
    unnatural_points: list[str] = Field(default_factory=list)
    subplots: list[dict] = Field(default_factory=list)
    rationale: str = Field(default="", max_length=6000)

    @field_validator("subplots")
    @classmethod
    def bounded_subplots(cls, values: list[dict]) -> list[dict]:
        if len(values) > 40:
            raise ValueError("副线候选过多，请分步推进")
        return values


class ProgressionHookAdoptionPreview(ProgressionModel):
    hook_id: str
    title: str = Field(min_length=1, max_length=255)
    summary: str = Field(default="", max_length=4000)
    start_chapter: int | None = Field(default=None, ge=1)
    end_chapter: int | None = Field(default=None, ge=1)
    related_character_ids: list[str] = Field(default_factory=list)
