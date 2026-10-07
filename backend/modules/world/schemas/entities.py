"""核心实体与自动入库批次 schema。"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from modules.world.schemas._common import UuidStr, _normalize_author_entity_type


class CoreEntityCreate(BaseModel):
    """创建核心实体请求"""

    entity_type: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="受支持实体类型",
    )
    name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="实体名称",
    )
    summary: str | None = Field(
        None,
        max_length=5000,
        description="概要",
    )
    public_info: str | None = Field(
        None,
        description="对外公开信息",
    )
    hidden_truth: str | None = Field(
        None,
        description="隐藏真相（仅作者视角）",
    )
    content_json: dict | None = Field(
        default=None,
        description="扩展信息 JSON",
    )
    importance: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="重要性 0.0~1.0",
    )
    importance_level: str = Field(
        default="normal",
        max_length=16,
        description="重要性级别：core/important/normal/temporary",
    )
    reveal_level: str = Field(
        default="author_only",
        max_length=16,
        description="揭示层级：author_only/hinted/revealed/fully_known",
    )
    status: str = Field(
        default="canonical",
        max_length=32,
        description="状态",
    )
    created_by: str | None = Field(
        None,
        max_length=64,
        description="创建者标识",
    )
    approved_by: str | None = Field(
        None,
        max_length=64,
        description="采用者标识；已采用对象默认与创建者一致",
    )
    force_create: bool = Field(
        default=False,
        description="强制创建，跳过去重检查（当前 create 不主动去重）",
    )

    @field_validator("entity_type")
    @classmethod
    def normalize_entity_type_field(cls, v: str) -> str:
        return _normalize_author_entity_type(v)


class CoreEntityUpdate(BaseModel):
    """更新核心实体请求（所有字段可选）"""

    entity_type: Annotated[
        str | None,
        Field(None, min_length=1, max_length=64, description="受支持实体类型"),
    ]
    name: Annotated[str | None, Field(None, min_length=1, max_length=255)]
    summary: Annotated[str | None, Field(None)]
    public_info: Annotated[str | None, Field(None)]
    hidden_truth: Annotated[str | None, Field(None)]
    content_json: Annotated[dict | None, Field(None)]
    importance: Annotated[float | None, Field(None, ge=0.0, le=1.0)]
    importance_level: Annotated[str | None, Field(None, max_length=16)]
    reveal_level: Annotated[str | None, Field(None, max_length=16)]
    status: Annotated[str | None, Field(None, max_length=32)]
    approved_by: Annotated[str | None, Field(None, max_length=64)]
    expected_updated_at: Annotated[
        datetime | None,
        Field(None, description="编辑基线；缺失或过期返回 409，不接受无条件覆盖"),
    ]

    @field_validator("entity_type")
    @classmethod
    def normalize_entity_type_field(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return _normalize_author_entity_type(v)


class EntityRankingResponse(BaseModel):
    semantic_importance: float = Field(ge=0.0, le=1.0)
    recent_heat: float = Field(ge=0.0, le=1.0)
    combined_score: float = Field(ge=0.0, le=1.0)
    labels: list[Literal["important", "hot"]] = Field(default_factory=list)
    last_appearance_chapter: int | None = Field(default=None, ge=1)
    recent_12_chapter_occurrences: int = Field(default=0, ge=0)


class EntityTypeFacet(BaseModel):
    entity_type: str
    count: int = Field(ge=0)


class EntityRankingFacets(BaseModel):
    important: int = Field(default=0, ge=0)
    hot: int = Field(default=0, ge=0)
    other: int = Field(default=0, ge=0)
    by_type: list[EntityTypeFacet] = Field(default_factory=list)


class EntityRankingContext(BaseModel):
    version: Literal["importance_recent_v1"] = "importance_recent_v1"
    status: Literal["ready", "partial", "unavailable"] = "unavailable"
    as_of_chapter: int | None = Field(default=None, ge=1)
    covered_chapters: int = Field(default=0, ge=0)
    total_chapters: int = Field(default=0, ge=0)
    half_life_chapters: int = 6
    importance_weight: float = 0.65
    heat_weight: float = 0.35


class CoreEntityResponse(BaseModel):
    """核心实体响应"""

    model_config = ConfigDict(
        from_attributes=True,
        json_encoders={uuid.UUID: str},
    )

    id: UuidStr
    novel_id: UuidStr
    entity_type: str
    name: str
    summary: str | None = None
    public_info: str | None = None
    hidden_truth: str | None = None
    content_json: dict | None = None
    importance: float = 0.5
    importance_level: str = "normal"
    reveal_level: str = "author_only"
    status: str = "canonical"
    display_state: Literal["active", "review", "archived"] | None = None
    source: str | None = None
    attention_reasons: list[str] = Field(default_factory=list)
    suggested_action: str | None = None
    embedding_text: str | None = None
    created_by: str | None = None
    approved_by: str | None = None
    has_image: bool = False
    image_version: uuid.UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    ranking: EntityRankingResponse | None = None

    @model_validator(mode="after")
    def derive_author_state(self) -> CoreEntityResponse:
        from modules.world.asset_state import project_entity_state

        projection = project_entity_state(
            status=self.status,
            content_json=self.content_json,
            created_by=self.created_by,
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


class CoreEntityListResponse(BaseModel):
    """核心实体列表响应"""

    items: list[CoreEntityResponse]
    total: int
    facets: EntityRankingFacets | None = None
    ranking_context: EntityRankingContext | None = None


class EntityTypeOption(BaseModel):
    value: str
    label: str
    kind: Literal["system", "custom"]


class EntityTypeCatalogResponse(BaseModel):
    items: list[EntityTypeOption]


class EntityPromoteRequest(BaseModel):
    """采用兼容 draft/candidate 实体的请求。

    可选编辑字段与采用在同一事务中完成，供作者在采用前微调待处理对象。
    """

    approved_by: str | None = Field(
        default="manual",
        max_length=64,
        description="确认者标识",
    )
    entity_type: str | None = Field(default=None, min_length=1, max_length=64)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    summary: str | None = Field(default=None, max_length=5000)

    @field_validator("entity_type")
    @classmethod
    def normalize_optional_entity_type(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _normalize_author_entity_type(value)


class EntityPromoteResponse(BaseModel):
    """实体提升响应"""

    model_config = ConfigDict(
        from_attributes=True,
        json_encoders={uuid.UUID: str},
    )

    entity_id: UuidStr
    status: str
    approved_by: str | None = None


# ============================================================
# Auto-Ingest Batch Schema
# ============================================================


class AutoIngestBatchItem(BaseModel):
    """自动入库批次内的实体概要"""

    id: str
    name: str
    entity_type: str


class AutoIngestBatchResponse(BaseModel):
    """自动入库批次分组响应"""

    batch_id: str
    ingested_at: str = ""
    entity_count: int = 0
    entities: list[AutoIngestBatchItem] = []
