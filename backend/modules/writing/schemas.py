"""
Writing Pydantic Schema 定义

用于 API 请求/响应校验和 Facade 输出。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ============================================================
# 请求 Schema
# ============================================================


class WritingDraftCreate(BaseModel):
    """创建/发布草稿请求

    每次调用自动递增版本号。
    """

    novel_id: str = Field(
        ...,
        description="小说项目 ID",
    )
    chapter_index: int = Field(
        ...,
        ge=1,
        description="章节索引（从 1 开始）",
    )
    title: str | None = Field(
        None,
        max_length=500,
        description="草稿标题",
    )
    content: str | None = Field(
        None,
        max_length=100000,
        description="草稿正文",
    )
    scene_id: str | None = Field(
        None,
        description="发布时关联的 Scene ID，用于归档最近冲突检查快照",
    )


class WritingDraftUpdate(BaseModel):
    """暂存草稿请求（原地更新最新版本，不递增版本号）"""

    title: str | None = Field(None, description="草稿标题")
    content: str | None = Field(None, description="草稿正文")
    expected_version: int | None = Field(
        None,
        ge=1,
        description="期望的版本号，用于发布后的多 Tab 冲突检测",
    )
    expected_updated_at: datetime | None = Field(
        None,
        description="期望的更新时间戳，用于暂存时的多 Tab 冲突检测",
    )


# ============================================================
# 响应 Schema
# ============================================================


class WritingDraftResponse(BaseModel):
    """草稿响应 — 从 ORM 转换时自动处理 UUID→str"""

    model_config = ConfigDict(
        from_attributes=True,
        json_encoders={uuid.UUID: str},
    )

    id: str
    novel_id: str
    chapter_index: int
    title: str | None = None
    content: str | None = None
    version_number: int = 1
    status: str = "draft"
    conflict_check_snapshot_json: dict | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("created_at", "updated_at", mode="before")
    @classmethod
    def _coerce_datetime_to_utc(cls, v: object) -> datetime | None:
        if v is None:
            return v
        if isinstance(v, datetime):
            if v.tzinfo is None:
                return v.replace(tzinfo=UTC)
            return v
        if isinstance(v, str):
            dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return dt
        return v

    @field_validator("id", "novel_id", mode="before")
    @classmethod
    def coerce_uuid_to_str(cls, v: object) -> str | None:
        """将 UUID 属性的原始值转为字符串"""
        if v is None:
            return None
        if isinstance(v, uuid.UUID):
            return str(v)
        if isinstance(v, str):
            return v
        return str(v)

    @field_validator("conflict_check_snapshot_json", mode="before")
    @classmethod
    def coerce_snapshot(cls, v: object) -> dict | None:
        if v is None or isinstance(v, dict):
            return v
        return None


class DraftListItem(BaseModel):
    """草稿版本列表项"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    version_number: int
    title: str | None = None
    word_count: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("id", mode="before")
    @classmethod
    def coerce_id_to_str(cls, v: object) -> str:
        if isinstance(v, uuid.UUID):
            return str(v)
        if isinstance(v, str):
            return v
        return str(v)


class VersionHistoryResponse(BaseModel):
    """版本历史响应"""

    novel_id: str
    chapter_index: int
    versions: list[DraftListItem]
    total: int


class ChapterSplitRequest(BaseModel):
    split_pos: int = Field(..., ge=1, description="编辑器 offset，必须位于正文中间")
    source_scene_id: str | None = Field(
        None, description="当前 Scene ID，用于同步 scene_chunks"
    )


class WritingGenerateRequest(BaseModel):
    """AI 正文候选草稿生成请求。"""

    novel_id: str = Field(..., description="小说项目 ID")
    chapter_index: int = Field(..., ge=1, description="章节索引")
    title: str | None = Field(None, max_length=500, description="候选草稿标题")
    instruction: str | None = Field(None, max_length=4000, description="生成要求")
    context_confirmation_id: str = Field(..., description="AI 参考资料确认 ID")


class WritingGenerateResponse(BaseModel):
    """AI 正文生成入队响应。"""

    task_id: str
    status: str = "pending"


class WritingDraftAutosaveCreate(BaseModel):
    """检查前的纯草稿暂存请求，不触发发布任务。"""

    novel_id: str = Field(..., description="小说项目 ID")
    chapter_index: int = Field(..., ge=1, description="章节索引")
    title: str | None = Field(None, max_length=500, description="草稿标题")
    content: str | None = Field(None, max_length=100000, description="草稿正文")


class WritingConflictCheckCreate(BaseModel):
    """创建剧情设定冲突检查。"""

    novel_id: str
    chapter_index: int = Field(..., ge=1)
    scene_id: str | None = None
    draft_id: str | None = None
    version_number: int | None = Field(None, ge=1)
    content: str | None = Field("", max_length=100000)
    include_candidates: bool = False


class WritingConflictItemUpdate(BaseModel):
    """更新单条问题处理状态。"""

    status: str = Field(..., pattern="^(open|resolved|ignored|later)$")


class WritingConflictAiReviewRequest(BaseModel):
    """为一次检查追加 AI 软冲突判断。"""

    novel_id: str
    context_confirmation_id: str


class WritingConflictAiSuggestionRequest(BaseModel):
    """为单条问题生成 AI 修复建议。"""

    novel_id: str
    context_confirmation_id: str


class WritingConflictAiReviewRawOutput(BaseModel):
    """LLM 软冲突原始输出；逐条问题另行严格校验以支持部分丢弃。"""

    issues: list[Any] = Field(default_factory=list)


class WritingConflictAiReviewIssue(BaseModel):
    """单条 AI 软冲突判断。"""

    kind: Literal[
        "motivation_gap",
        "emotion_jump",
        "foreshadowing_misfire",
        "premature_reveal",
        "implicit_lore_conflict",
        "voice_or_pov_drift",
        "scene_goal_drift",
        "continuity_soft_risk",
    ]
    severity: Literal["low", "medium", "high"]
    summary: str = Field(..., min_length=1, max_length=1000)
    evidence: str = Field(..., min_length=1, max_length=2000)
    rationale: str = Field(..., min_length=1, max_length=2000)
    location_hint: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(..., ge=0, le=1)
    depends_on_pending_objects: bool = False


class WritingConflictSuggestionPayload(BaseModel):
    """AI 修复建议载荷。"""

    strategy: str = Field(..., min_length=1, max_length=1000)
    suggested_text: str = Field(..., min_length=1, max_length=4000)
    rationale: str = Field(..., min_length=1, max_length=2000)
    constraints: list[str] = Field(default_factory=list)
    risk_notes: list[str] = Field(default_factory=list)


class WritingConflictSuggestionOutput(BaseModel):
    """LLM 修复建议输出。"""

    suggestion: WritingConflictSuggestionPayload


class WritingConflictItemResponse(BaseModel):
    """冲突检查问题响应。"""

    model_config = ConfigDict(from_attributes=True, json_encoders={uuid.UUID: str})

    id: str
    check_id: str
    novel_id: str
    kind: str
    severity: str
    source_module: str
    source_type: str | None = None
    source_id: str | None = None
    evidence_summary: str
    location_json: dict | None = None
    is_ai_judgment: bool = False
    needs_review: bool = False
    status: str = "open"
    confidence: float | None = None
    source_confirmation_id: str | None = None
    llm_rationale: str | None = None
    suggestion_status: str = "not_requested"
    suggestion_confirmation_id: str | None = None
    ai_suggestion: str | None = None
    suggestion_error: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator(
        "id",
        "check_id",
        "novel_id",
        "source_confirmation_id",
        "suggestion_confirmation_id",
        mode="before",
    )
    @classmethod
    def _coerce_uuid(cls, v: object) -> str | None:
        if v is None:
            return None
        return str(v)


class WritingConflictCheckResponse(BaseModel):
    """冲突检查记录响应。"""

    model_config = ConfigDict(from_attributes=True, json_encoders={uuid.UUID: str})

    id: str
    novel_id: str
    chapter_index: int
    scene_id: str | None = None
    draft_id: str | None = None
    version_number: int | None = None
    scope: dict = Field(default_factory=dict)
    include_candidates: bool = False
    status: str = "completed"
    summary_json: dict = Field(default_factory=dict)
    ai_review_enabled: bool = False
    ai_review_status: str = "not_requested"
    ai_review_confirmation_id: str | None = None
    ai_review_model: str | None = None
    ai_review_error: str | None = None
    items: list[WritingConflictItemResponse] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator(
        "id",
        "novel_id",
        "scene_id",
        "draft_id",
        "ai_review_confirmation_id",
        mode="before",
    )
    @classmethod
    def _coerce_uuid(cls, v: object) -> str | None:
        if v is None:
            return None
        return str(v)


class WritingConflictCheckListResponse(BaseModel):
    """冲突检查历史列表。"""

    items: list[WritingConflictCheckResponse]
    total: int


class SceneSplitItem(BaseModel):
    """章节切分后同步更新的 Scene 项"""

    id: str
    novel_id: str
    scene_index: int
    title: str | None = None
    goal: str | None = None
    core_conflict: str | None = None
    emotional_beat: str | None = None
    must_happen: str | None = None
    must_not_happen: str | None = None
    narrative_tag: str | None = None
    source: str | None = None
    scene_chunks: list[dict] = []
    chapter_ids: list[str] = []
    pov_character_id: str | None = None
    status: str | None = None


class ChapterSplitResponse(BaseModel):
    source_chapter_index: int
    new_chapter_index: int
    source_draft: WritingDraftResponse
    new_draft: WritingDraftResponse
    scenes: list[SceneSplitItem] = Field(default_factory=list)
