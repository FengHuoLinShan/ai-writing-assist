from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _uuid_validator(v: object) -> str:
    if isinstance(v, uuid.UUID):
        return str(v)
    if isinstance(v, str):
        return v
    return str(v)


def _dict_default(v: object) -> dict[str, Any]:
    if isinstance(v, dict):
        return v
    return {}


# ============================================================
# PlotThread
# ============================================================


class PlotThreadCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    thread_type: str = Field(..., max_length=32)
    summary: str | None = None
    visible_goal: str | None = None
    hidden_truth: str | None = None
    start_chapter: int | None = Field(None, ge=1)
    planned_payoff_chapter: int | None = Field(None, ge=1)
    current_stage: str | None = Field(None, max_length=32)
    related_character_ids: list[str] = []
    related_entity_ids: list[str] = []
    related_memory_ids: list[str] = []
    reader_known_state: str | None = None
    author_known_state: str | None = None
    provenance_meta: dict[str, Any] = {}
    status: str = "draft"


class PlotThreadUpdate(BaseModel):
    name: Annotated[str | None, Field(None, min_length=1, max_length=255)]
    thread_type: Annotated[str | None, Field(None, max_length=32)]
    summary: Annotated[str | None, Field(None)]
    visible_goal: Annotated[str | None, Field(None)]
    hidden_truth: Annotated[str | None, Field(None)]
    start_chapter: Annotated[int | None, Field(None, ge=1)]
    planned_payoff_chapter: Annotated[int | None, Field(None, ge=1)]
    current_stage: Annotated[str | None, Field(None, max_length=32)]
    related_character_ids: Annotated[list[str] | None, Field(None)]
    related_entity_ids: Annotated[list[str] | None, Field(None)]
    related_memory_ids: Annotated[list[str] | None, Field(None)]
    reader_known_state: Annotated[str | None, Field(None)]
    author_known_state: Annotated[str | None, Field(None)]
    provenance_meta: Annotated[dict[str, Any] | None, Field(None)]
    status: Annotated[str | None, Field(None, max_length=32)]


class PlotThreadResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, json_encoders={uuid.UUID: str})

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
    related_character_ids: list = []
    related_entity_ids: list = []
    related_memory_ids: list = []
    reader_known_state: str | None = None
    author_known_state: str | None = None
    provenance_meta: dict[str, Any] = {}
    status: str = "draft"
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("id", "novel_id", mode="before")
    @classmethod
    def coerce_uuid(cls, v: object) -> str:
        return _uuid_validator(v)

    @field_validator("provenance_meta", mode="before")
    @classmethod
    def coerce_provenance_meta(cls, v: object) -> dict[str, Any]:
        return _dict_default(v)


class PlotThreadListResponse(BaseModel):
    items: list[PlotThreadResponse]
    total: int


# ============================================================
# OutlineArc
# ============================================================


class OutlineArcCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    arc_index: int | None = Field(None, ge=1)
    start_chapter: int | None = Field(None, ge=1)
    end_chapter: int | None = Field(None, ge=1)
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
    provenance_meta: dict[str, Any] = {}
    status: str = "draft"


class OutlineArcUpdate(BaseModel):
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
    provenance_meta: Annotated[dict[str, Any] | None, Field(None)]
    status: Annotated[str | None, Field(None, max_length=32)]


class OutlineArcResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, json_encoders={uuid.UUID: str})

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
    related_thread_ids: list = []
    related_character_ids: list = []
    related_entity_ids: list = []
    provenance_meta: dict[str, Any] = {}
    status: str = "draft"
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("id", "novel_id", mode="before")
    @classmethod
    def coerce_uuid(cls, v: object) -> str:
        return _uuid_validator(v)

    @field_validator("provenance_meta", mode="before")
    @classmethod
    def coerce_provenance_meta(cls, v: object) -> dict[str, Any]:
        return _dict_default(v)


class OutlineArcListResponse(BaseModel):
    items: list[OutlineArcResponse]
    total: int


# ============================================================
# Scene
# ============================================================


class SceneCreate(BaseModel):
    scene_index: int = Field(..., ge=0)
    title: str | None = Field(None, max_length=255)
    goal: str | None = None
    core_conflict: str | None = None
    emotional_beat: str | None = None
    must_happen: str | None = None
    must_not_happen: str | None = None
    narrative_tag: Annotated[str, Field("draft", max_length=32)]
    source: str = "manual"
    scene_chunks: list[dict] = []
    chapter_ids: list[str] = []
    pov_character_id: str | None = None
    structure_meta: dict[str, Any] = {}
    status: Literal["draft", "canonical"] = "draft"


class SceneUpdate(BaseModel):
    scene_index: Annotated[int | None, Field(None, ge=0)]
    title: Annotated[str | None, Field(None, max_length=255)]
    goal: Annotated[str | None, Field(None)]
    core_conflict: Annotated[str | None, Field(None)]
    emotional_beat: Annotated[str | None, Field(None)]
    must_happen: Annotated[str | None, Field(None)]
    must_not_happen: Annotated[str | None, Field(None)]
    narrative_tag: Annotated[str | None, Field(None, max_length=32)]
    source: Annotated[str | None, Field(None, max_length=32)]
    scene_chunks: Annotated[list[dict] | None, Field(None)]
    chapter_ids: Annotated[list[str] | None, Field(None)]
    pov_character_id: Annotated[str | None, Field(None)]
    structure_meta: Annotated[dict[str, Any] | None, Field(None)]
    status: Literal["draft", "canonical", "deprecated"] | None = None


class SceneResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, json_encoders={uuid.UUID: str})

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
    scene_chunks: list = []
    chapter_ids: list = []
    pov_character_id: str | None = None
    structure_meta: dict[str, Any] = {}
    status: str = "draft"
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("id", "novel_id", mode="before")
    @classmethod
    def coerce_uuid(cls, v: object) -> str:
        return _uuid_validator(v)


class SceneReorderRequest(BaseModel):
    scene_ids: list[str] = Field(
        ..., min_length=1, description="按新顺序排列的 Scene ID 列表"
    )


class SceneReorderResponse(BaseModel):
    updated: int
    total: int


class SceneListResponse(BaseModel):
    items: list[SceneResponse]
    total: int


class SplitChaptersRequest(BaseModel):
    """断章请求：将章节从当前 Scene 移到目标 Scene"""

    chapter_index: int = Field(..., ge=1, description="从第几章开始断")
    target_scene_id: str | None = Field(
        None, description="目标 Scene ID，为空则新建 Scene"
    )


class SceneHealthSummary(BaseModel):
    key: str
    label: str
    count: int = 0
    breakdown: dict[str, int] = {}


class SceneHealthReason(BaseModel):
    code: str
    label: str
    count: int = 1
    chapter_indices: list[int] = []
    fingerprint: str | None = None
    suggestion_id: str | None = None


class SceneWorkbenchItem(BaseModel):
    kind: str = "scene"
    scene: SceneResponse
    new_scene: SceneResponse | None = None
    health: list[str] = []
    health_details: dict[str, list[SceneHealthReason]] = {}
    chapter_range: str = "未关联章节"
    summary: str | None = None


class SceneFusionSuggestionSummary(BaseModel):
    pending_count: int = 0


class SceneWorkbenchResponse(BaseModel):
    health: dict[str, SceneHealthSummary]
    items: list[SceneWorkbenchItem]
    total: int = 0
    skip: int = 0
    unassigned_chapters: list[int] = []
    selected_scene_id: str | None = None
    fusion_suggestions: SceneFusionSuggestionSummary = (
        SceneFusionSuggestionSummary()
    )


class SceneReviewRequest(BaseModel):
    scene_ids: list[str] = Field(..., min_length=1, max_length=100)
    decision: Literal["review", "reopen"]


class SceneReviewResponse(BaseModel):
    items: list[SceneResponse]


class SceneSourceMappingReviewItem(BaseModel):
    scene_id: str
    expected_fingerprint: str = Field(..., min_length=64, max_length=64)


class SceneSourceMappingReviewRequest(BaseModel):
    items: list[SceneSourceMappingReviewItem] = Field(
        ...,
        min_length=1,
        max_length=100,
    )
    decision: Literal["accept_chapter_only"] = "accept_chapter_only"
    confirmed: bool = False


class SceneSourceMappingReviewResponse(BaseModel):
    items: list[SceneResponse]


class SceneMappingUpdate(BaseModel):
    chapter_ids: list[str] | None = None
    scene_chunks: list[dict] | None = None
    structure_meta: dict[str, Any] | None = None
    status: Literal["draft", "canonical", "deprecated"] | None = None


class SceneMergeRequest(BaseModel):
    target_scene_id: str
    source_scene_ids: list[str] = Field(..., min_length=1)
    confirmed: bool = False


class SceneSplitRequest(BaseModel):
    source_scene_id: str
    split_chapter_index: int = Field(..., ge=1)
    split_pos: int | None = Field(None, ge=1)
    new_scene_title: str | None = Field(None, max_length=255)
    new_scene_status: Literal["draft", "canonical"] = "draft"
    draft_scenes: list[dict[str, Any]] | None = None
    confirmed: bool = False


class SceneImpactPreview(BaseModel):
    operation: str
    chapter_mapping_change: dict[str, Any]
    field_changes: dict[str, Any] = {}
    related_threads: dict[str, Any] = {}
    related_foreshadowing: dict[str, Any] = {}
    related_reveals: dict[str, Any] = {}
    map_summary_impact: dict[str, Any] = {}
    warnings: list[str] = []
    scene: SceneResponse | None = None
    new_scene: dict[str, Any] | None = None
    draft_scene: dict[str, Any] | None = None
    draft_scenes: list[dict[str, Any]] = []
    primary_scene_id: str | None = None
    field_references: dict[str, list[dict[str, Any]]] = {}
    field_sources: dict[str, list[str]] = {}
    source_scene_summaries: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    confidence: float | None = None
    reason: str | None = None


class SceneFusionDraft(BaseModel):
    scene_index: Annotated[int | None, Field(None, ge=0)]
    title: Annotated[str | None, Field(None, max_length=255)]
    goal: str | None = None
    core_conflict: str | None = None
    emotional_beat: str | None = None
    must_happen: str | None = None
    must_not_happen: str | None = None
    narrative_tag: Annotated[str | None, Field(None, max_length=32)]
    source: Annotated[str | None, Field(None, max_length=32)]
    scene_chunks: list[dict] | None = None
    chapter_ids: list[str] | None = None
    pov_character_id: str | None = None
    structure_meta: dict[str, Any] | None = None
    status: Annotated[str | None, Field(None, max_length=32)]


class SceneFieldReference(BaseModel):
    scene_id: str
    title: str | None = None
    value: Any = None
    role: Literal["primary", "source", "draft"] = "source"


class SceneSourceSummary(BaseModel):
    id: str
    title: str | None = None
    chapter_range: str = "未关联章节"
    source: str = "manual"
    status: str = "draft"
    quality_flags: list[str] = []


class SceneDraftConflict(BaseModel):
    field: str
    message: str
    source_scene_ids: list[str] = []


class SceneDraftReviewResponse(BaseModel):
    mode: Literal["fusion", "split", "fusion_suggestion"]
    source_scene_ids: list[str]
    primary_scene_id: str | None = None
    draft_scene: SceneFusionDraft | None = None
    draft_scenes: list[SceneFusionDraft] = []
    field_references: dict[str, list[SceneFieldReference]] = {}
    field_sources: dict[str, list[str]] = {}
    source_scene_summaries: list[SceneSourceSummary] = []
    conflicts: list[SceneDraftConflict] = []
    warnings: list[str] = []
    confidence: float | None = None
    reason: str | None = None


class SceneFusionPreviewRequest(BaseModel):
    source_scene_ids: list[str] = Field(..., min_length=2, max_length=20)
    primary_scene_id: str | None = None


class SceneFusionPreviewResponse(SceneDraftReviewResponse):
    fused_scene: dict[str, Any] | None = None
    preview_scene: dict[str, Any] | None = None


class SceneFusionSaveRequest(SceneFusionPreviewRequest):
    mode: Literal[
        "keep_originals",
        "deprecate_originals",
        "discard",
        "edit_then_save",
    ]
    fused_scene: SceneFusionDraft | None = None
    suggestion_id: str | None = None


class SceneFusionSaveResponse(BaseModel):
    status: Literal["saved", "discarded"]
    source_scene_ids: list[str]
    fused_scene: SceneResponse | None = None
    warnings: list[str] = []


class SceneFusionSuggestionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, json_encoders={uuid.UUID: str})

    id: str
    novel_id: str
    source_workflow_id: str
    suggestion_kind: Literal[
        "intra_chapter",
        "cross_chapter",
        "duplicate_window",
        "replacement",
    ]
    proposed_action: Literal[
        "merge",
        "absorb_left",
        "absorb_right",
        "keep_separate",
        "needs_review",
        "replace",
    ]
    source_scene_ids: list[str] = []
    chapter_span: list[int] = []
    proposed_scene: dict[str, Any] = {}
    scan_trace: list[dict[str, Any]] = []
    confidence: float | None = None
    reason: str | None = None
    status: Literal["pending", "adopted", "dismissed", "stale"]
    result_scene_id: str | None = None
    result_scene_ids: list[str] = []
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator(
        "id",
        "novel_id",
        "result_scene_id",
        mode="before",
    )
    @classmethod
    def coerce_suggestion_uuid(cls, v: object) -> str | None:
        if v is None:
            return None
        return _uuid_validator(v)


class SceneFusionSuggestionListResponse(BaseModel):
    items: list[SceneFusionSuggestionResponse]
    total: int = 0


class SceneFusionSuggestionDismissRequest(BaseModel):
    suggestion_ids: list[str] = Field(..., min_length=1, max_length=100)
    confirmed: bool = False


class SceneFusionSuggestionDismissResponse(BaseModel):
    dismissed: int = 0


class SceneReplacementApplyRequest(BaseModel):
    suggestion_id: str
    decision: Literal["replace", "edit_then_replace"]
    confirmed: bool = False
    draft_scenes: list[dict[str, Any]] | None = None


class SceneReplacementApplyResponse(BaseModel):
    status: Literal["adopted"] = "adopted"
    deprecated_scene_ids: list[str] = []
    result_scene_ids: list[str] = []
    rag_reindex_task_id: str | None = None
    downstream_refresh_required: list[str] = ["world_objects", "plot_structure"]


class PlotStructureGenerateResponse(BaseModel):
    """AI 剧情结构生成接口响应"""

    total_threads: int = 0
    total_arcs: int = 0
    total_scenes: int = 0
    existing_threads_count: int = 0
    existing_arcs_count: int = 0
    threads: list[dict] = []
    arcs: list[dict] = []
    scenes: list[dict] = []
    extra_sections: dict = {}
    warnings: list[str] = []


class OutlineAiTaskRequest(BaseModel):
    """手动大纲 AI 操作请求。"""

    novel_id: str
    context_confirmation_id: str
    start_chapter: int | None = Field(None, ge=1)
    end_chapter: int | None = Field(None, ge=1)
    chapter_index: int | None = Field(None, ge=1)
    instruction: str | None = None


class OutlineAiTaskResponse(BaseModel):
    """手动大纲 AI 操作入队响应。"""

    task_id: str
    status: str = "pending"


class OutlineStructurePreviewApplyRequest(BaseModel):
    """将手动大纲 AI preview 显式采用为工作结构。"""

    novel_id: str
    context_confirmation_id: str
    source_task_id: str
    draft_structure: dict[str, Any]
    confirmed: bool = False


class OutlineStructurePreviewApplyResponse(PlotStructureGenerateResponse):
    status: Literal["applied"] = "applied"


class OutlineScenePreviewApplyRequest(BaseModel):
    """将章节 Scene preview 显式采用为工作 Scene。"""

    novel_id: str
    context_confirmation_id: str
    source_task_id: str
    draft_scenes: list[dict[str, Any]] = Field(..., min_length=1)
    confirmed: bool = False


class OutlineScenePreviewApplyResponse(BaseModel):
    status: Literal["applied"] = "applied"
    scene_ids: list[str] = Field(default_factory=list)
    total_scenes: int = 0


# ============================================================
# ForeshadowingPlan
# ============================================================


class ForeshadowingPlanCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    summary: str | None = None
    surface_meaning: str | None = None
    hidden_meaning: str | None = None
    planned_seed_chapter: int | None = Field(None, ge=1)
    planned_reinforce_chapters: list[Annotated[int, Field(ge=1)]] = []
    planned_payoff_chapter: int | None = Field(None, ge=1)
    planned_payoff_scene: int | None = Field(None, ge=0)
    related_entity_ids: list[str] = []
    related_thread_ids: list[str] = []
    provenance_meta: dict[str, Any] = {}
    status: str = "draft"


class ForeshadowingPlanUpdate(BaseModel):
    name: Annotated[str | None, Field(None, min_length=1, max_length=255)]
    summary: Annotated[str | None, Field(None)]
    surface_meaning: Annotated[str | None, Field(None)]
    hidden_meaning: Annotated[str | None, Field(None)]
    planned_seed_chapter: Annotated[int | None, Field(None, ge=1)]
    planned_reinforce_chapters: Annotated[
        list[Annotated[int, Field(ge=1)]] | None,
        Field(None),
    ]
    planned_payoff_chapter: Annotated[int | None, Field(None, ge=1)]
    planned_payoff_scene: Annotated[int | None, Field(None, ge=0)]
    related_entity_ids: Annotated[list[str] | None, Field(None)]
    related_thread_ids: Annotated[list[str] | None, Field(None)]
    provenance_meta: Annotated[dict[str, Any] | None, Field(None)]
    status: Annotated[str | None, Field(None, max_length=32)]


class ForeshadowingPlanResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, json_encoders={uuid.UUID: str})

    id: str
    novel_id: str
    name: str
    summary: str | None = None
    surface_meaning: str | None = None
    hidden_meaning: str | None = None
    planned_seed_chapter: int | None = None
    planned_reinforce_chapters: list = []
    planned_payoff_chapter: int | None = None
    planned_payoff_scene: int | None = None
    related_entity_ids: list = []
    related_thread_ids: list = []
    provenance_meta: dict[str, Any] = {}
    status: str = "draft"
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("id", "novel_id", mode="before")
    @classmethod
    def coerce_uuid(cls, v: object) -> str:
        return _uuid_validator(v)

    @field_validator("provenance_meta", mode="before")
    @classmethod
    def coerce_provenance_meta(cls, v: object) -> dict[str, Any]:
        return _dict_default(v)


class ForeshadowingPlanListResponse(BaseModel):
    items: list[ForeshadowingPlanResponse]
    total: int


# ============================================================
# RevealPlan
# ============================================================


class RevealStage(BaseModel):
    stage_index: int = Field(..., ge=0)
    chapter_index: int = Field(..., ge=1)
    reveal_content: str | None = None
    trigger: str | None = None
    effect: str | None = None


class RevealPlanCreate(BaseModel):
    target_type: str = Field(..., max_length=32)
    target_id: uuid.UUID = Field(...)
    secret_summary: str = Field(...)
    reveal_stages: list[RevealStage] = []
    provenance_meta: dict[str, Any] = {}
    status: str = "draft"


class RevealPlanUpdate(BaseModel):
    target_type: Annotated[str | None, Field(None, max_length=32)]
    target_id: Annotated[str | None, Field(None)]
    secret_summary: Annotated[str | None, Field(None)]
    reveal_stages: Annotated[list[RevealStage] | None, Field(None)]
    provenance_meta: Annotated[dict[str, Any] | None, Field(None)]
    status: Annotated[str | None, Field(None, max_length=32)]


class RevealPlanResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, json_encoders={uuid.UUID: str})

    id: str
    novel_id: str
    target_type: str
    target_id: str
    secret_summary: str
    reveal_stages: list = []
    provenance_meta: dict[str, Any] = {}
    status: str = "draft"
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("id", "novel_id", "target_id", mode="before")
    @classmethod
    def coerce_uuid(cls, v: object) -> str:
        return _uuid_validator(v)

    @field_validator("provenance_meta", mode="before")
    @classmethod
    def coerce_provenance_meta(cls, v: object) -> dict[str, Any]:
        return _dict_default(v)


class RevealPlanListResponse(BaseModel):
    items: list[RevealPlanResponse]
    total: int
