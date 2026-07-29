"""Validated wire and LLM schemas for RP interaction."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


def _clean_required_text(value: str) -> str:
    cleaned = value.replace("\x00", "").strip()
    if not cleaned:
        raise ValueError("内容不能为空")
    return cleaned


class InteractionActionSuggestion(BaseModel):
    label: str = Field(..., min_length=1, max_length=80)
    text: str = Field(..., min_length=1, max_length=1000)

    @field_validator("label", "text")
    @classmethod
    def clean_text(cls, value: str) -> str:
        return _clean_required_text(value)


class InteractionResponseMetadata(BaseModel):
    version: Literal[1] = 1
    response_kind: Literal["story", "clarification"] = "story"
    suggested_title: str | None = Field(default=None, max_length=80)
    branch_hint: str | None = Field(default=None, max_length=40)
    story_ended: bool = False
    action_suggestions: list[InteractionActionSuggestion] = Field(
        default_factory=list,
        max_length=3,
    )

    @field_validator("suggested_title", "branch_hint")
    @classmethod
    def clean_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.replace("\x00", "").strip()
        return cleaned or None


_OVERVIEW_SECTION_FIELDS = (
    "world_and_start",
    "player_character",
    "current_situation",
    "important_people_and_factions",
    "key_turning_points",
    "open_threads",
    "must_remember",
)
MAX_OVERVIEW_ESTIMATED_TOKENS = 24_000


class InteractionOverviewSections(BaseModel):
    """Stable internal sections rendered as ordinary Chinese headings."""

    world_and_start: str = Field(default="", max_length=50_000)
    player_character: str = Field(default="", max_length=50_000)
    current_situation: str = Field(default="", max_length=50_000)
    important_people_and_factions: str = Field(default="", max_length=50_000)
    key_turning_points: str = Field(default="", max_length=50_000)
    open_threads: str = Field(default="", max_length=50_000)
    must_remember: str = Field(default="", max_length=50_000)

    @field_validator(*_OVERVIEW_SECTION_FIELDS)
    @classmethod
    def clean_section(cls, value: str) -> str:
        return value.replace("\x00", "").strip()

    @model_validator(mode="after")
    def enforce_total_budget(self) -> InteractionOverviewSections:
        total_chars = sum(len(getattr(self, field)) for field in _OVERVIEW_SECTION_FIELDS)
        if max(1, (total_chars + 1) // 2) > MAX_OVERVIEW_ESTIMATED_TOKENS:
            raise ValueError("回顾内容过长，请适当精简后保存")
        return self

    def has_content(self) -> bool:
        return any(getattr(self, field) for field in _OVERVIEW_SECTION_FIELDS)


class InteractionSummaryOutput(BaseModel):
    """One model call returns the immutable segment and updated total overview."""

    segment_summary: str = Field(..., min_length=1, max_length=32_000)
    overview: InteractionOverviewSections

    @field_validator("segment_summary")
    @classmethod
    def clean_segment_summary(cls, value: str) -> str:
        return _clean_required_text(value)

    @model_validator(mode="after")
    def require_visible_overview(self) -> InteractionSummaryOutput:
        if not self.overview.has_content():
            raise ValueError("模型回顾不能全部为空")
        return self


class JourneyCreateRequest(BaseModel):
    opening_text: str = Field(..., min_length=1, max_length=100_000)
    idempotency_key: str = Field(..., min_length=8, max_length=128)
    see_sea_enabled: bool = False
    action_options_enabled: bool = True

    @field_validator("opening_text")
    @classmethod
    def clean_opening(cls, value: str) -> str:
        return _clean_required_text(value)


class JourneyModeUpdateRequest(BaseModel):
    see_sea_enabled: bool | None = None
    action_options_enabled: bool | None = None
    expected_selection_epoch: int = Field(..., ge=0)


class JourneyTitleUpdateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)

    @field_validator("title")
    @classmethod
    def clean_title(cls, value: str) -> str:
        return _clean_required_text(value)


class InteractionSendRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=100_000)
    expected_selection_epoch: int = Field(..., ge=0)
    idempotency_key: str = Field(..., min_length=8, max_length=128)

    @field_validator("content")
    @classmethod
    def clean_content(cls, value: str) -> str:
        return _clean_required_text(value)


class InteractionRegenerateRequest(BaseModel):
    expected_selection_epoch: int = Field(..., ge=0)
    idempotency_key: str = Field(..., min_length=8, max_length=128)


class InteractionEditUserRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=100_000)
    expected_selection_epoch: int = Field(..., ge=0)
    idempotency_key: str = Field(..., min_length=8, max_length=128)

    @field_validator("content")
    @classmethod
    def clean_content(cls, value: str) -> str:
        return _clean_required_text(value)


class InteractionSelectRequest(BaseModel):
    expected_selection_epoch: int = Field(..., ge=0)


class InteractionContinueRequest(BaseModel):
    expected_selection_epoch: int = Field(..., ge=0)
    idempotency_key: str = Field(..., min_length=8, max_length=128)


class InteractionStopRequest(BaseModel):
    expected_selection_epoch: int = Field(..., ge=0)


class InteractionArchiveRequest(BaseModel):
    confirmed: bool = False


class InteractionDeleteRequest(BaseModel):
    title_confirmation: str = Field(..., max_length=255)


class InteractionOverviewUpdateRequest(BaseModel):
    sections: InteractionOverviewSections
    expected_overview_epoch: int = Field(..., ge=0)
    expected_selection_epoch: int = Field(..., ge=0)
    base_revision_id: str
    base_selected_leaf_node_id: str
    base_selected_path_hash: str = Field(..., min_length=64, max_length=64)

    @model_validator(mode="after")
    def require_content(self) -> InteractionOverviewUpdateRequest:
        if not self.sections.has_content():
            raise ValueError("回顾内容不能为空")
        return self


class InteractionMessageResponse(BaseModel):
    id: str
    parent_node_id: str | None = None
    role: Literal["user", "assistant"]
    message_kind: Literal["setup", "story"] = "story"
    content: str
    completion_state: Literal["complete", "partial"] = "complete"
    end_reason: str | None = None
    branch_hint: str | None = None
    story_ended: bool = False
    action_suggestions: list[InteractionActionSuggestion] = Field(default_factory=list)
    created_at: datetime


class InteractionMessagePageResponse(BaseModel):
    items: list[InteractionMessageResponse] = Field(default_factory=list)
    has_more: bool = False
    has_older: bool = False
    has_newer: bool = False
    selection_epoch: int = Field(default=0, ge=0)


class InteractionPathIndexItemResponse(BaseModel):
    id: str
    ordinal: int = Field(..., ge=1)
    total: int = Field(..., ge=1)
    excerpt: str
    completion_state: Literal["complete", "partial"] = "complete"


class InteractionPathIndexResponse(BaseModel):
    selection_epoch: int = Field(..., ge=0)
    items: list[InteractionPathIndexItemResponse] = Field(default_factory=list)


class InteractionAttemptResponse(BaseModel):
    id: str
    journey_id: str
    task_id: str | None = None
    response_to_node_id: str
    status: str
    visible_text: str = ""
    visible_offset: int = 0
    finish_reason: str | None = None
    error_kind: str | None = None
    error_message: str | None = None
    result_node_id: str | None = None
    created_at: datetime


class InteractionGenerationRecordListResponse(BaseModel):
    items: list[InteractionAttemptResponse] = Field(default_factory=list)


class JourneySummaryResponse(BaseModel):
    id: str
    title: str
    title_source: str
    opening_excerpt: str
    status: Literal["active", "archived"]
    see_sea_enabled: bool
    action_options_enabled: bool
    selection_epoch: int
    latest_activity_at: datetime
    current_excerpt: str | None = None
    attempt_status: str | None = None
    active_attempt_id: str | None = None


class JourneyListResponse(BaseModel):
    items: list[JourneySummaryResponse]
    total: int


class JourneyDetailResponse(BaseModel):
    id: str
    title: str
    title_source: str
    opening_text: str
    status: Literal["active", "archived"]
    see_sea_enabled: bool
    action_options_enabled: bool
    selection_epoch: int
    overview_epoch: int
    selected_leaf_node_id: str | None = None
    setup_messages: list[InteractionMessageResponse] = Field(default_factory=list)
    messages: list[InteractionMessageResponse] = Field(default_factory=list)
    has_older_messages: bool = False
    active_attempt: InteractionAttemptResponse | None = None


class InteractionMutationResponse(BaseModel):
    journey: JourneyDetailResponse
    attempt: InteractionAttemptResponse | None = None


class InteractionBranchVariantResponse(BaseModel):
    node_id: str
    selected: bool
    ordinal: int
    total: int
    excerpt: str
    created_at: datetime


class InteractionBranchListResponse(BaseModel):
    parent_node_id: str | None = None
    variants: list[InteractionBranchVariantResponse] = Field(default_factory=list)


class InteractionTreeNodeResponse(BaseModel):
    id: str
    parent_node_id: str | None = None
    role: str
    excerpt: str
    selected: bool
    depth: int
    created_at: datetime


class InteractionTreeVariantResponse(BaseModel):
    node_id: str
    selected: bool
    excerpt: str
    continuation_count: int = Field(default=0, ge=0)


class InteractionTreeBranchPointResponse(BaseModel):
    parent_node_id: str | None = None
    label: str
    variants: list[InteractionTreeVariantResponse] = Field(default_factory=list)


class InteractionTreeResponse(BaseModel):
    branch_points: list[InteractionTreeBranchPointResponse] = Field(default_factory=list)


class InteractionOverviewResponse(BaseModel):
    sections: InteractionOverviewSections = Field(
        default_factory=InteractionOverviewSections
    )
    source: str
    overview_epoch: int
    anchor_node_id: str | None = None
    updated_at: datetime | None = None
    is_refreshing: bool = False
    status: Literal["ready", "refreshing", "failed", "forming"] = "forming"
    base_revision_id: str | None = None
    base_selected_leaf_node_id: str | None = None
    base_selected_path_hash: str | None = None


class InteractionStopResponse(BaseModel):
    attempt: InteractionAttemptResponse
    partial_node: InteractionMessageResponse | None = None


class InteractionHeartbeatResponse(BaseModel):
    see_sea_enabled: bool
    accepted: bool
    attempt: InteractionAttemptResponse | None = None


class InteractionExportResponse(BaseModel):
    filename: str
    media_type: str
    content: str


class InteractionPreferencesResponse(BaseModel):
    see_sea_notice_acknowledged: bool = False
