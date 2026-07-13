"""
Writing Pydantic Schema 定义

用于 API 请求/响应校验和 Facade 输出。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def project_writing_draft_state(
    status: str | None,
    provenance_json: dict[str, Any] | None,
) -> dict[str, Any]:
    """Project compatibility statuses into the author-facing draft state."""
    normalized_status = str(status or "draft").strip().lower()
    provenance = dict(provenance_json or {})

    if normalized_status == "candidate":
        display_state = "review"
    elif normalized_status == "deprecated":
        display_state = "archived"
    else:
        display_state = "active"

    raw_source = str(provenance.get("source") or "").strip().lower()
    if raw_source in {"writing_generate", "ai", "llm"}:
        source = "ai_generated"
    elif raw_source:
        source = raw_source
    else:
        source = "manual"

    attention_reasons: list[str] = []
    pov_validation = provenance.get("pov_validation")
    if isinstance(pov_validation, dict):
        validation_status = str(pov_validation.get("status") or "").lower()
        if validation_status not in {"", "ok", "passed", "not_applicable"}:
            attention_reasons.append("pov_risk")
        if pov_validation.get("warnings"):
            attention_reasons.append("parse_warning")
        if pov_validation.get("findings"):
            attention_reasons.append("fact_risk")

    return {
        "display_state": display_state,
        "source": source,
        "attention_reasons": list(dict.fromkeys(attention_reasons)),
    }


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
    provenance_json: dict[str, Any] | None = Field(
        None,
        description="草稿来源追踪信息",
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


class WritingDraftCheckpoint(WritingDraftUpdate):
    """显式保存一个未发布版本。"""

    force: bool = Field(
        False,
        description="正文无实质变化时，用户二次确认后强制留版",
    )


class WritingPublishRequest(WritingDraftCreate):
    """发布当前工作版本，兼容未传 draft_id 的旧调用方。"""

    draft_id: str | None = Field(None, description="当前工作版本 ID")
    expected_version: int | None = Field(None, ge=1)
    expected_updated_at: datetime | None = None
    restore_source_version: int | None = Field(None, ge=1)


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
    content_hash: str = ""
    version_number: int = 1
    status: str = "draft"
    conflict_check_snapshot_json: dict | None = None
    provenance_json: dict[str, Any] | None = None
    display_state: Literal["active", "review", "archived"] | None = None
    source: str | None = None
    attention_reasons: list[str] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @model_validator(mode="after")
    def derive_author_state(self) -> WritingDraftResponse:
        projection = project_writing_draft_state(self.status, self.provenance_json)
        if self.display_state is None:
            self.display_state = projection["display_state"]
        if self.source is None:
            self.source = projection["source"]
        if not self.attention_reasons:
            self.attention_reasons = projection["attention_reasons"]
        return self

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

    @field_validator("conflict_check_snapshot_json", "provenance_json", mode="before")
    @classmethod
    def coerce_json_dict(cls, v: object) -> dict | None:
        if v is None or isinstance(v, dict):
            return v
        return None

    @field_validator("display_state", mode="before")
    @classmethod
    def coerce_display_state(cls, v: object) -> str | None:
        if isinstance(v, str) and v in {"active", "review", "archived"}:
            return v
        return None

    @field_validator("source", mode="before")
    @classmethod
    def coerce_source(cls, v: object) -> str | None:
        return v if isinstance(v, str) else None

    @field_validator("attention_reasons", mode="before")
    @classmethod
    def coerce_attention_reasons(cls, v: object) -> list[str]:
        if isinstance(v, list):
            return [str(item) for item in v]
        return []


class DraftListItem(BaseModel):
    """草稿版本列表项"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    version_number: int
    title: str | None = None
    status: str = "draft"
    display_state: Literal["active", "review", "archived"] = "active"
    deprecated_from_status: str | None = None
    version_origin: Literal["auto", "manual", "legacy"] = "legacy"
    word_count: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @model_validator(mode="before")
    @classmethod
    def derive_version_origin(cls, value: object) -> object:
        if isinstance(value, dict):
            data = dict(value)
            provenance = data.get("provenance_json")
        else:
            data = {
                "id": getattr(value, "id", None),
                "version_number": getattr(value, "version_number", 1),
                "title": getattr(value, "title", None),
                "status": getattr(value, "status", "draft"),
                "provenance_json": getattr(value, "provenance_json", None),
                "created_at": getattr(value, "created_at", None),
                "updated_at": getattr(value, "updated_at", None),
            }
            provenance = getattr(value, "provenance_json", None)
        projection = project_writing_draft_state(data.get("status"), provenance)
        data["display_state"] = projection["display_state"]
        if not data.get("deprecated_from_status") and isinstance(provenance, dict):
            data["deprecated_from_status"] = provenance.get("deprecated_from_status")
        if not data.get("version_origin"):
            raw_origin = (
                (provenance or {}).get("version_origin")
                if isinstance(provenance, dict)
                else None
            )
            data["version_origin"] = (
                raw_origin if raw_origin in {"auto", "manual"} else "legacy"
            )
        return data

    @field_validator("id", mode="before")
    @classmethod
    def coerce_id_to_str(cls, v: object) -> str:
        if isinstance(v, uuid.UUID):
            return str(v)
        if isinstance(v, str):
            return v
        return str(v)


class ChapterSummaryItem(BaseModel):
    """章节列表摘要项（每章最新版本）"""

    id: str
    chapter_index: int
    title: str | None = None
    word_count: int = 0
    version_number: int = 1
    status: str = "draft"
    updated_at: datetime | None = None


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
    """AI 正文建议生成请求。"""

    novel_id: str = Field(..., description="小说项目 ID")
    chapter_index: int = Field(..., ge=1, description="章节索引")
    title: str | None = Field(None, max_length=500, description="正文建议标题")
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


class WritingConflictAiReviewTaskResponse(BaseModel):
    """AI 软冲突复核入队响应。"""

    task_id: str
    status: str = "pending"
    check: WritingConflictCheckResponse


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
