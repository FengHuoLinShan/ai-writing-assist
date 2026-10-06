"""实体别名 schema（含向后兼容别名分组）。"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from modules.world.schemas._common import AliasKind
from modules.world.schemas.entities import (
    CoreEntityCreate,
    CoreEntityListResponse,
    CoreEntityResponse,
    CoreEntityUpdate,
)

# 向后兼容 Schema（从旧 schema 迁出）
# ============================================================


class DuplicateSuggestionResult(BaseModel):
    """去重建议结果 — 向后兼容"""

    candidate_id: str = ""
    candidate_name: str = ""
    existing_entity_id: str = ""
    existing_entity_name: str = ""
    similarity_score: float = 0.0
    match_method: str = ""
    action: str = ""


# ============================================================
# 向后兼容别名（供其他模块引用）
# ============================================================

WorldEntityResponse = CoreEntityResponse
WorldEntityListResponse = CoreEntityListResponse
WorldEntityCreate = CoreEntityCreate
WorldEntityUpdate = CoreEntityUpdate


class EntityAliasCreate(BaseModel):
    """创建 core_entities.content_json.aliases 中的别名。"""

    entity_id: str = Field(..., description="所属核心实体 ID")
    alias: str = Field(..., min_length=1, max_length=255, description="别名文本")
    alias_type: str = Field(
        default="name", min_length=1, max_length=20, description="别名类型"
    )
    alias_kind: AliasKind | None = Field(default=None, description="最小语义别名类型")
    source_chapter_index: int | None = Field(None, ge=0, description="首次出现的章节索引")
    confidence: float = Field(default=0.8, ge=0.0, le=1.0, description="确认置信度")
    status: str = Field(default="confirmed", max_length=32, description="状态")


class EntityAliasUpdate(BaseModel):
    """更新 core_entities.content_json.aliases 中单个别名的复核元数据。"""

    status: Annotated[str | None, Field(None, max_length=32)]
    alias_kind: AliasKind | None = None
    needs_review: bool | None = None
    reviewed_at: Annotated[str | None, Field(None, max_length=64)]
    reviewed_by: Annotated[str | None, Field(None, max_length=64)]
    reviewed_from: Annotated[str | None, Field(None, max_length=64)]


class EntityAliasEditRequest(BaseModel):
    """编辑或移动 core_entities.content_json.aliases 中单个别名。"""

    target_entity_id: Annotated[str | None, Field(None)] = None
    alias: Annotated[str | None, Field(None, min_length=1, max_length=255)] = None
    alias_type: Annotated[str | None, Field(None, min_length=1, max_length=20)] = None
    alias_kind: AliasKind | None = None
    confirm_review: bool = True


class EntityAliasReviewItem(BaseModel):
    entity_id: str
    entity_name: str | None = None
    alias: str
    alias_type: str
    alias_kind: AliasKind | None = None
    status: str | None = None
    source: str | None = None
    workflow_id: str | None = None
    scene_id: str | None = None
    scene_index: int | None = None
    source_chapter_index: int | None = None
    confidence: float | None = None
    needs_review: bool | None = None
    quote: str | None = None
    evidence_refs: list[dict[str, Any]] = Field(default_factory=list)
    suggested_alias_type: str | None = None
    type_kind: Literal["recommended", "custom"] = "custom"
    display_state: Literal["active", "review", "archived"] | None = None
    managed_by_suggestion: bool = False
    suggestion_id: str | None = None
    execution_fingerprint: str = Field(..., min_length=64, max_length=64)


class EntityAliasReviewGroup(BaseModel):
    group_id: str
    entity_id: str
    entity_name: str | None = None
    member_count: int
    members: list[EntityAliasReviewItem] = Field(default_factory=list)


class EntityAliasReviewGroupListResponse(BaseModel):
    groups: list[EntityAliasReviewGroup] = Field(default_factory=list)
    group_total: int = 0
    item_total: int = 0
    skip: int = 0
    limit: int = 20


class EntityAliasReviewBatchDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_decision_id: str = Field(..., min_length=1, max_length=64)
    action: Literal["accept", "ignore"]
    entity_id: str
    original_alias: str = Field(..., min_length=1, max_length=255)
    expected_execution_fingerprint: str = Field(..., min_length=64, max_length=64)
    target_entity_id: str | None = None
    alias: str | None = Field(None, min_length=1, max_length=255)
    alias_type: str | None = Field(None, min_length=1, max_length=20)
    alias_kind: AliasKind | None = None

    @field_validator("alias_type")
    @classmethod
    def normalize_alias_type(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("alias_type cannot be blank")
        return normalized


class EntityAliasReviewBatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmed: bool = False
    decisions: list[EntityAliasReviewBatchDecision] = Field(
        ..., min_length=1, max_length=50
    )

    @model_validator(mode="after")
    def validate_batch(self) -> EntityAliasReviewBatchRequest:
        if not self.confirmed:
            raise ValueError("confirmed=true is required")
        decision_ids = [item.client_decision_id for item in self.decisions]
        if len(decision_ids) != len(set(decision_ids)):
            raise ValueError("client_decision_id must be unique")
        alias_keys = [
            (item.entity_id, item.original_alias.casefold()) for item in self.decisions
        ]
        if len(alias_keys) != len(set(alias_keys)):
            raise ValueError("an alias may only appear once in a batch")
        return self


class EntityResolveAsAliasRequest(BaseModel):
    """将候选实体确认为已有对象的别名。"""

    target_entity_id: str = Field(..., description="目标核心实体 ID")
    alias: str = Field(..., min_length=1, max_length=255, description="别名文本")
    alias_type: str = Field(
        default="alias", min_length=1, max_length=20, description="别名类型"
    )
    alias_kind: AliasKind | None = None
