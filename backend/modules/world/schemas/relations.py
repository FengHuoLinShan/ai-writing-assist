"""实体关系与复核批次 schema。"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from modules.world.schemas._common import (
    OptionalUuidStr,
    RelationKind,
    _optional_uuid_validator,
)

# EntityRelation Schema
# ============================================================


class EntityRelationCreate(BaseModel):
    """创建关系请求"""

    source_id: str = Field(
        ...,
        description="源实体 ID",
    )
    target_id: str = Field(
        ...,
        description="目标实体 ID",
    )
    relation_type: str = Field(
        ...,
        max_length=64,
        description="关系类型（自由字符串）",
    )
    relation_kind: RelationKind | None = Field(
        default=None,
        description="最小语义关系类型",
    )
    description: str | None = Field(
        None,
        description="关系描述",
    )
    strength: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="关系强度 0.0~1.0",
    )
    source_chapter_id: str | None = Field(
        None,
        description="来源章节 ID",
    )
    caused_by_event_id: str | None = Field(
        None,
        description="导致此关系的事件 ID",
    )
    quote: str | None = Field(
        None,
        description="原文依据",
    )
    status: str = Field(
        default="canonical",
        max_length=16,
        description="状态",
    )
    review_meta: dict[str, Any] | None = Field(
        default=None,
        description="来源与人工复核审计元数据",
    )


class EntityRelationUpdate(BaseModel):
    """更新关系请求（所有字段可选）"""

    relation_type: Annotated[str | None, Field(None, max_length=64)]
    relation_kind: RelationKind | None = None
    description: Annotated[str | None, Field(None)]
    strength: Annotated[float | None, Field(None, ge=0.0, le=1.0)]
    status: Annotated[str | None, Field(None, max_length=16)]


class EntityRelationReviewEditRequest(BaseModel):
    """编辑待复核关系并可同步确认。"""

    source_id: Annotated[str | None, Field(None)] = None
    target_id: Annotated[str | None, Field(None)] = None
    relation_type: Annotated[str | None, Field(None, min_length=1, max_length=64)] = None
    relation_kind: RelationKind | None = None
    description: str | None = None
    strength: Annotated[float | None, Field(None, ge=0.0, le=1.0)] = None
    confirm_review: bool = True
    expected_execution_fingerprint: Annotated[
        str | None, Field(None, min_length=64, max_length=64)
    ] = None

    @field_validator("relation_type")
    @classmethod
    def normalize_relation_type(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("relation_type cannot be blank")
        return normalized


class EntityRelationResponse(BaseModel):
    """关系响应"""

    # ``EntityRelation`` already exposes an ORM relationship named ``source``.
    # Read the author-facing provenance from a non-colliding validation alias;
    # the public serialized field remains ``source``.
    model_config = ConfigDict(from_attributes=True)

    id: Annotated[str, BeforeValidator(_optional_uuid_validator)]
    novel_id: Annotated[str, BeforeValidator(_optional_uuid_validator)]
    source_id: Annotated[str, BeforeValidator(_optional_uuid_validator)]
    source_name: str | None = None
    target_id: Annotated[str, BeforeValidator(_optional_uuid_validator)]
    target_name: str | None = None
    relation_type: str
    relation_kind: RelationKind | None = None
    description: str | None = None
    strength: float = 0.5
    source_chapter_id: OptionalUuidStr = None
    caused_by_event_id: OptionalUuidStr = None
    quote: str | None = None
    review_meta: dict | None = None
    status: str = "canonical"
    display_state: Literal["active", "review", "archived"] | None = None
    source: str | None = Field(default=None, validation_alias="author_source")
    attention_reasons: list[str] = Field(default_factory=list)
    suggested_action: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @model_validator(mode="after")
    def derive_author_state(self) -> EntityRelationResponse:
        from modules.world.asset_state import project_relation_state

        projection = project_relation_state(
            status=self.status,
            review_meta=self.review_meta,
        )
        if self.display_state is None:
            self.display_state = projection["display_state"]
        if self.source is None:
            self.source = projection["source"]
        if not self.attention_reasons:
            self.attention_reasons = projection["attention_reasons"]
        if self.suggested_action is None:
            self.suggested_action = projection["suggested_action"]
        return self


class EntityRelationListResponse(BaseModel):
    """关系列表响应"""

    items: list[EntityRelationResponse]
    total: int


class ReviewTypeCatalogItem(BaseModel):
    value: str
    label: str
    category: str
    synonyms: list[str] = Field(default_factory=list)
    default_kind: str | None = None


class ReviewKindCatalogItem(BaseModel):
    value: str
    label: str
    description: str


class ReviewTypeCatalogResponse(BaseModel):
    version: int = 2
    custom_allowed: bool = True
    relation_kinds: list[ReviewKindCatalogItem] = Field(default_factory=list)
    alias_kinds: list[ReviewKindCatalogItem] = Field(default_factory=list)
    relation_types: list[ReviewTypeCatalogItem] = Field(default_factory=list)
    alias_types: list[ReviewTypeCatalogItem] = Field(default_factory=list)


class EntityRelationReviewMember(EntityRelationResponse):
    suggested_relation_type: str | None = None
    type_kind: Literal["recommended", "custom"] = "custom"
    evidence_summary: dict[str, Any] = Field(default_factory=dict)


class EntityRelationReviewGroup(BaseModel):
    group_id: str
    source_id: str
    source_name: str | None = None
    target_id: str
    target_name: str | None = None
    member_count: int
    type_variants: list[str] = Field(default_factory=list)
    evidence_count: int = 0
    scene_indices: list[int] = Field(default_factory=list)
    source_chapter_indices: list[int] = Field(default_factory=list)
    members: list[EntityRelationReviewMember] = Field(default_factory=list)
    canonical_relations: list[EntityRelationResponse] = Field(default_factory=list)
    reverse_candidate_count: int = 0
    reverse_type_variants: list[str] = Field(default_factory=list)
    reverse_canonical_relations: list[EntityRelationResponse] = Field(
        default_factory=list
    )
    execution_fingerprint: str = Field(..., min_length=64, max_length=64)


class EntityRelationReviewGroupListResponse(BaseModel):
    groups: list[EntityRelationReviewGroup] = Field(default_factory=list)
    group_total: int = 0
    item_total: int = 0
    skip: int = 0
    limit: int = 20


class EntityRelationSeparateReviewItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_relation_id: str
    source_id: str
    target_id: str
    relation_type: str = Field(..., min_length=1, max_length=64)
    relation_kind: RelationKind | None = None
    description: str | None = None
    strength: float | None = Field(None, ge=0.0, le=1.0)

    @field_validator("relation_type")
    @classmethod
    def normalize_relation_type(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("relation_type cannot be blank")
        return normalized


class EntityRelationReviewBatchDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_decision_id: str = Field(..., min_length=1, max_length=64)
    action: Literal["accept", "merge", "ignore", "accept_separately"]
    group_id: str = Field(..., min_length=1, max_length=80)
    member_relation_ids: list[str] = Field(..., min_length=1, max_length=50)
    primary_relation_id: str | None = None
    expected_execution_fingerprint: str = Field(..., min_length=64, max_length=64)
    source_id: str | None = None
    target_id: str | None = None
    relation_type: str | None = Field(None, min_length=1, max_length=64)
    relation_kind: RelationKind | None = None
    description: str | None = None
    strength: float | None = Field(None, ge=0.0, le=1.0)
    separate_relations: list[EntityRelationSeparateReviewItem] = Field(
        default_factory=list,
        max_length=50,
    )
    unselected_action: Literal["keep_pending", "ignore"] = "keep_pending"

    @field_validator("relation_type")
    @classmethod
    def normalize_relation_type(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("relation_type cannot be blank")
        return normalized

    @model_validator(mode="after")
    def validate_decision(self) -> EntityRelationReviewBatchDecision:
        member_ids = list(dict.fromkeys(self.member_relation_ids))
        if len(member_ids) != len(self.member_relation_ids):
            raise ValueError("member_relation_ids must be unique")
        if self.action == "accept" and len(member_ids) != 1:
            raise ValueError("accept requires exactly one relation")
        if self.action == "merge" and len(member_ids) < 2:
            raise ValueError("merge requires at least two relations")
        if self.action in {"accept", "merge"}:
            if self.primary_relation_id not in member_ids:
                raise ValueError("primary_relation_id must be selected")
            if not self.source_id or not self.target_id or not self.relation_type:
                raise ValueError("accepted relation fields are required")
        if self.action == "accept_separately":
            if len(member_ids) < 2:
                raise ValueError("accept_separately requires at least two relations")
            separate_ids = [
                item.candidate_relation_id for item in self.separate_relations
            ]
            if len(separate_ids) != len(set(separate_ids)):
                raise ValueError("separate relation candidates must be unique")
            if set(separate_ids) != set(member_ids):
                raise ValueError("separate_relations must define every selected relation")
            final_keys = [
                (item.source_id, item.target_id, item.relation_type)
                for item in self.separate_relations
            ]
            if len(final_keys) != len(set(final_keys)):
                raise ValueError("separate relation final keys must be unique")
        elif self.separate_relations:
            raise ValueError("separate_relations requires accept_separately")
        return self


class EntityRelationReviewBatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmed: bool = False
    decisions: list[EntityRelationReviewBatchDecision] = Field(
        ..., min_length=1, max_length=20
    )

    @model_validator(mode="after")
    def validate_batch(self) -> EntityRelationReviewBatchRequest:
        if not self.confirmed:
            raise ValueError("confirmed=true is required")
        decision_ids = [item.client_decision_id for item in self.decisions]
        if len(decision_ids) != len(set(decision_ids)):
            raise ValueError("client_decision_id must be unique")
        relation_ids = [
            relation_id
            for decision in self.decisions
            for relation_id in decision.member_relation_ids
        ]
        if len(relation_ids) != len(set(relation_ids)):
            raise ValueError("a relation may only appear in one batch decision")
        if len(relation_ids) > 50:
            raise ValueError("a batch may reference at most 50 relations")
        return self


class ReviewBatchItemResult(BaseModel):
    client_decision_id: str
    status: Literal["success", "stale", "failed"]
    action: str
    affected_ids: list[str] = Field(default_factory=list)
    canonical_relation_id: str | None = None
    canonical_relation_ids: list[str] = Field(default_factory=list)
    reused_canonical_relation_ids: list[str] = Field(default_factory=list)
    ignored_relation_ids: list[str] = Field(default_factory=list)
    remaining_candidate_ids: list[str] = Field(default_factory=list)
    archived_relation_ids: list[str] = Field(default_factory=list)
    error_code: str | None = None
    message: str | None = None


class ReviewBatchResponse(BaseModel):
    requested_count: int
    succeeded_count: int
    stale_count: int
    failed_count: int
    results: list[ReviewBatchItemResult] = Field(default_factory=list)
