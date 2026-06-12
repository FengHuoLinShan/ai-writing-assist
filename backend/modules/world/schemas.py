"""
World Pydantic Schema 定义 — v3 因果时空网

用于 API 请求/响应校验和 Facade 输出。
包含 AI 提取契约、CRUD Schema、Facade 输出 Schema。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# ============================================================
# 内部工具
# ============================================================


def _uuid_validator(v: object) -> str:
    """将 UUID 原始值转为字符串"""
    if isinstance(v, uuid.UUID):
        return str(v)
    if isinstance(v, str):
        return v
    return str(v)


def _optional_uuid_validator(v: object) -> str | None:
    """将可空 UUID 转为字符串"""
    if v is None:
        return None
    return _uuid_validator(v)


# ============================================================
# AI 提取契约
# ============================================================


class ExtractedEntity(BaseModel):
    """AI 提取的实体"""

    entity_type: str = Field(
        ...,
        description="实体类型（自由字符串，如 character/faction/item）",
    )
    name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="实体名称",
    )
    aliases: list[str] = Field(
        default_factory=list,
        description="别名列表",
    )
    summary: str | None = Field(
        None,
        description="概要描述",
    )
    content_json: dict = Field(
        default_factory=dict,
        description="扩展属性 JSON",
    )


class ExtractedRelationship(BaseModel):
    """AI 提取的关系"""

    source_name: str = Field(
        ...,
        min_length=1,
        description="源实体名称",
    )
    target_name: str = Field(
        ...,
        min_length=1,
        description="目标实体名称",
    )
    relation_type: str = Field(
        ...,
        description="关系类型（自由字符串）",
    )
    description: str | None = Field(
        None,
        description="关系描述",
    )
    quote: str = Field(
        ...,
        description="原文依据",
    )


class ExtractionOutput(BaseModel):
    """AI 提取输出"""

    entities: list[ExtractedEntity] = Field(
        default_factory=list,
        description="提取的实体列表",
    )
    relationships: list[ExtractedRelationship] = Field(
        default_factory=list,
        description="提取的关系列表",
    )


# ============================================================
# CoreEntity Schema
# ============================================================


class CoreEntityCreate(BaseModel):
    """创建核心实体请求"""

    entity_type: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="实体类型（自由字符串）",
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
        default="draft",
        max_length=32,
        description="状态",
    )
    created_by: str | None = Field(
        None,
        max_length=64,
        description="创建者标识",
    )
    force_create: bool = Field(
        default=False,
        description="强制创建，跳过去重检查（当前 create 不主动去重）",
    )


class CoreEntityUpdate(BaseModel):
    """更新核心实体请求（所有字段可选）"""

    entity_type: Annotated[str | None, Field(None, min_length=1, max_length=64)]
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


class CoreEntityResponse(BaseModel):
    """核心实体响应"""

    model_config = ConfigDict(
        from_attributes=True,
        json_encoders={uuid.UUID: str},
    )

    id: str
    novel_id: str
    entity_type: str
    name: str
    summary: str | None = None
    public_info: str | None = None
    hidden_truth: str | None = None
    content_json: dict | None = None
    importance: float = 0.5
    importance_level: str = "normal"
    reveal_level: str = "author_only"
    status: str = "draft"
    embedding_text: str | None = None
    created_by: str | None = None
    approved_by: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("id", "novel_id", mode="before")
    @classmethod
    def coerce_uuid(cls, v: object) -> str:
        return _uuid_validator(v)


class CoreEntityListResponse(BaseModel):
    """核心实体列表响应"""

    items: list[CoreEntityResponse]
    total: int


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


# ============================================================
# Event Schema
# ============================================================


class EventCreate(BaseModel):
    """创建事件请求"""

    entity_id: str = Field(
        ...,
        description="事件实体 ID（CoreEntity）",
    )
    source_chapter_id: str = Field(
        ...,
        description="来源章节 ID",
    )
    location_entity_id: str = Field(
        ...,
        description="事件发生地实体 ID",
    )
    timeline_order: int = Field(
        ...,
        ge=0,
        description="时间线顺序",
    )
    occurrence_time_label: str | None = Field(
        None,
        max_length=100,
        description="发生时间标签",
    )


class EventUpdate(BaseModel):
    """更新事件请求（所有字段可选）"""

    source_chapter_id: Annotated[str | None, Field(None)]
    location_entity_id: Annotated[str | None, Field(None)]
    timeline_order: Annotated[int | None, Field(None, ge=0)]
    occurrence_time_label: Annotated[str | None, Field(None, max_length=100)]


class EventResponse(BaseModel):
    """事件响应"""

    model_config = ConfigDict(from_attributes=True)

    entity_id: str
    novel_id: str
    source_chapter_id: str
    location_entity_id: str
    timeline_order: int
    occurrence_time_label: str | None = None

    @field_validator(
        "entity_id",
        "novel_id",
        "source_chapter_id",
        "location_entity_id",
        mode="before",
    )
    @classmethod
    def coerce_uuid(cls, v: object) -> str:
        return _uuid_validator(v)


class EventListResponse(BaseModel):
    """事件列表响应"""

    items: list[EventResponse]
    total: int


# ============================================================
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


class EntityRelationUpdate(BaseModel):
    """更新关系请求（所有字段可选）"""

    relation_type: Annotated[str | None, Field(None, max_length=64)]
    description: Annotated[str | None, Field(None)]
    strength: Annotated[float | None, Field(None, ge=0.0, le=1.0)]
    status: Annotated[str | None, Field(None, max_length=16)]


class EntityRelationResponse(BaseModel):
    """关系响应"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    novel_id: str
    source_id: str
    target_id: str
    relation_type: str
    description: str | None = None
    strength: float = 0.5
    source_chapter_id: str | None = None
    caused_by_event_id: str | None = None
    quote: str | None = None
    status: str = "canonical"
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator(
        "id",
        "novel_id",
        "source_id",
        "target_id",
        "source_chapter_id",
        "caused_by_event_id",
        mode="before",
    )
    @classmethod
    def coerce_uuid(cls, v: object) -> str | None:
        return _optional_uuid_validator(v)


class EntityRelationListResponse(BaseModel):
    """关系列表响应"""

    items: list[EntityRelationResponse]
    total: int


# ============================================================
# EntityRevision Schema
# ============================================================


class RevisionListResponse(BaseModel):
    """版本列表响应"""

    items: list[dict[str, Any]]
    total: int


class RollbackRequest(BaseModel):
    """回滚请求"""

    target_revision_id: str = Field(
        ...,
        description="目标版本 ID",
    )


class EntityRollbackRequest(BaseModel):
    """实体按 Scene 索引回滚请求"""

    target_scene_index: int = Field(
        ...,
        ge=0,
        description="目标 Scene 索引",
    )


class EntityMergeRequest(BaseModel):
    """实体合并请求"""

    target_entity_id: str = Field(
        ...,
        description="合并目标实体 ID",
    )


class EntityMergeResponse(BaseModel):
    """实体合并响应"""

    target_entity_id: str


class EntityRollbackResponse(BaseModel):
    """实体回滚响应"""

    entity_id: str
    target_scene_index: int | None
    restored_fields: list[str]
    warnings: list[str]


class EntityRevisionListResponse(BaseModel):
    """实体版本列表响应"""

    items: list[dict[str, Any]]
    total: int


class TextArchiveSeedRequest(BaseModel):
    """E2E 测试专用：写入 TextArchive 归档请求"""

    novel_id: str
    field_name: str = "summary"
    text_content: str
    scene_index: int = 0


class TextArchiveSeedResponse(BaseModel):
    """E2E 测试专用：写入 TextArchive 归档响应"""

    status: str = "ok"
    entity_id: str
    field_name: str
    archive_id: str


# ============================================================
# Character Schema（从 character 模块迁入）
# ============================================================


class CharacterCreate(BaseModel):
    """创建人物请求。novel_id 由 service 注入 (per ADR-0002),
    Create schema 不再要求, 但保留字段以兼容外部测试 fixture 显式传值。"""

    novel_id: str | None = Field(
        default=None,
        description="小说项目 ID (由 service 注入, 通常不传)",
    )
    entity_id: str = Field(
        ...,
        description="关联的核心实体 ID",
    )
    name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="人物名称",
    )
    aliases: list[dict] = Field(
        default_factory=list,
        description="别名列表 JSONB（[{alias: str, type: str}]）",
    )
    role: str | None = Field(
        None,
        max_length=64,
        description="角色定位",
    )
    appearance: str | None = Field(
        None,
        description="外貌描述",
    )
    personality: str | None = Field(
        None,
        description="性格描述",
    )
    desire: str | None = Field(
        None,
        description="渴望/目标",
    )
    fear: str | None = Field(
        None,
        description="恐惧/软肋",
    )
    secret: str | None = Field(
        None,
        description="秘密（作者视角）",
    )
    weakness: str | None = Field(
        None,
        description="弱点",
    )
    current_goal: str | None = Field(
        None,
        description="当前短期目标",
    )
    current_state: str | None = Field(
        None,
        description="当前状态摘要",
    )
    current_emotion: str | None = Field(
        None,
        max_length=64,
        description="当前情绪",
    )
    stance: str | None = Field(
        None,
        description="人物立场/态度",
    )
    voice_style: str | None = Field(
        None,
        description="语言风格描述",
    )
    behavior_rules: list[dict] = Field(
        default_factory=list,
        max_length=50,
        description="行为规则列表 JSONB（最多 50 条）",
    )
    relationship_summary: str | None = Field(
        None,
        description="人物关系摘要",
    )
    meta: dict = Field(
        default_factory=dict,
        description="扩展元数据",
    )
    status: str = Field(
        default="canonical",
        max_length=32,
        description="状态",
    )


class CharacterUpdate(BaseModel):
    """更新人物请求（所有字段可选）"""

    name: Annotated[str | None, Field(None, min_length=1, max_length=255)]
    aliases: Annotated[list[dict] | None, Field(None)]
    role: Annotated[str | None, Field(None, max_length=64)]
    appearance: Annotated[str | None, Field(None)]
    personality: Annotated[str | None, Field(None)]
    desire: Annotated[str | None, Field(None)]
    fear: Annotated[str | None, Field(None)]
    secret: Annotated[str | None, Field(None)]
    weakness: Annotated[str | None, Field(None)]
    current_goal: Annotated[str | None, Field(None)]
    current_state: Annotated[str | None, Field(None)]
    current_emotion: Annotated[str | None, Field(None, max_length=64)]
    stance: Annotated[str | None, Field(None)]
    voice_style: Annotated[str | None, Field(None)]
    behavior_rules: Annotated[list[dict] | None, Field(None)]
    relationship_summary: Annotated[str | None, Field(None)]
    meta: Annotated[dict | None, Field(None)]
    status: Annotated[str | None, Field(None, max_length=32)]


class CharacterResponse(BaseModel):
    """人物响应 — 从 ORM 转换"""

    model_config = ConfigDict(
        from_attributes=True,
        json_encoders={uuid.UUID: str},
    )

    entity_id: str
    novel_id: str
    name: str

    @property
    def id(self) -> str:
        """向后兼容：旧代码使用 .id 访问人物 ID"""
        return self.entity_id

    aliases: list[dict] = []
    role: str | None = None
    appearance: str | None = None
    personality: str | None = None
    desire: str | None = None
    fear: str | None = None
    secret: str | None = None
    weakness: str | None = None
    current_goal: str | None = None
    current_state: str | None = None
    current_emotion: str | None = None
    stance: str | None = None
    voice_style: str | None = None
    behavior_rules: list[dict] = []
    relationship_summary: str | None = None
    meta: dict = {}
    status: str = "canonical"
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("entity_id", "novel_id", mode="before")
    @classmethod
    def coerce_uuid_to_str(cls, v: object) -> str:
        return _uuid_validator(v)


class CharacterListResponse(BaseModel):
    """人物列表响应"""

    items: list[CharacterResponse]
    total: int


def _require_misconception_for_false_belief_or_misunderstood(
    model: BaseModel,
) -> BaseModel:
    """shared model_validator: false_belief/misunderstood 必须提供 misconception。"""
    if (
        getattr(model, "knowledge_level") in {"false_belief", "misunderstood"}
        and not getattr(model, "misconception")
    ):
        raise ValueError(
            "false_belief/misunderstood knowledge must provide misconception",
        )
    return model


class CharacterKnowledgeCreate(BaseModel):
    """创建人物知识记录请求。novel_id 由 service 注入。"""

    novel_id: str | None = Field(
        default=None,
        description="小说项目 ID (由 service 注入, 通常不传)",
    )
    character_id: str = Field(..., description="人物 ID")
    target_type: str = Field(
        ...,
        max_length=64,
        description="目标类型（entity/character/event/location 等）",
    )
    target_id: str = Field(..., description="目标对象 ID")
    knowledge_level: str = Field(
        ...,
        max_length=32,
        description="了解程度（unknown/rumor/partial/full/false_belief/restricted/misunderstood）",
    )
    known_content: str | None = Field(None, description="角色已知的内容")
    misconception: str | None = Field(
        None,
        description="角色的误解内容（false_belief 或 misunderstood 时使用）",
    )
    source_chapter_index: int | None = Field(None, ge=0, description="信息来源章节")
    source_memory_id: str | None = Field(None, description="关联的 memory 记录 ID")
    status: str = Field(default="canonical", max_length=32, description="状态")

    require_misconception_for_false_belief_or_misunderstood = model_validator(
        mode="after",
    )(_require_misconception_for_false_belief_or_misunderstood)


class CharacterKnowledgeUpdate(BaseModel):
    """更新人物知识记录请求（所有字段可选）"""

    knowledge_level: Annotated[str | None, Field(None, max_length=32)]
    known_content: Annotated[str | None, Field(None)]
    misconception: Annotated[str | None, Field(None)]
    source_chapter_index: Annotated[int | None, Field(None, ge=0)]
    source_memory_id: Annotated[str | None, Field(None)]
    status: Annotated[str | None, Field(None, max_length=32)]

    require_misconception_for_false_belief_or_misunderstood = model_validator(
        mode="after",
    )(_require_misconception_for_false_belief_or_misunderstood)


class CharacterKnowledgeResponse(BaseModel):
    """人物知识响应 — 从 ORM 转换"""

    model_config = ConfigDict(
        from_attributes=True,
        json_encoders={uuid.UUID: str},
    )

    id: str
    novel_id: str
    character_id: str
    target_type: str
    target_id: str
    knowledge_level: str
    known_content: str | None = None
    misconception: str | None = None
    source_chapter_index: int | None = None
    source_memory_id: str | None = None
    status: str = "canonical"
    created_at: datetime | None = None

    @field_validator(
        "id",
        "novel_id",
        "character_id",
        "target_id",
        "source_memory_id",
        mode="before",
    )
    @classmethod
    def coerce_uuid_to_str(cls, v: object) -> str | None:
        return _optional_uuid_validator(v)


class CharacterKnowledgeListResponse(BaseModel):
    """人物知识列表响应"""

    items: list[CharacterKnowledgeResponse]
    total: int


# ============================================================
# Facade 输出 Schema（供其他模块读取/使用）
# ============================================================


class WorldEntityContext(BaseModel):
    """世界对象上下文 — 供其他模块读取的简化对象信息"""

    model_config = ConfigDict(from_attributes=True)

    entity_id: str
    entity_type: str
    name: str
    summary: str | None = None
    public_info: str | None = None
    hidden_truth: str | None = None
    importance: float = 0.5
    importance_level: str = "normal"
    reveal_level: str = "author_only"
    status: str = "draft"
    aliases: list[str] = Field(default_factory=list)
    related_entity_ids: list[str] = Field(default_factory=list)

    @field_validator("entity_id", mode="before")
    @classmethod
    def coerce_entity_id(cls, v: object) -> str:
        return _uuid_validator(v)


class WorldContextBundle(BaseModel):
    """世界上下文组合包 — 供 Context Compiler 或其他模块使用"""

    novel_id: str
    entities: list[WorldEntityContext] = Field(default_factory=list)
    total_count: int = 0
    reveal_mode: str = "author_safe"


class CharacterContextItem(BaseModel):
    """人物上下文中单个人物的信息"""

    model_config = ConfigDict(from_attributes=True)

    character_id: str
    name: str
    role: str | None = None
    appearance: str | None = None
    personality: str | None = None
    desire: str | None = None
    fear: str | None = None
    secret: str | None = None
    weakness: str | None = None
    current_goal: str | None = None
    current_state: str | None = None
    current_emotion: str | None = None
    stance: str | None = None
    voice_style: str | None = None
    behavior_rules: list[dict] = []
    relationship_summary: str | None = None
    meta: dict = {}


class CharacterKnowledgeContext(BaseModel):
    """人物知识上下文 — 单条知识"""

    model_config = ConfigDict(from_attributes=True)

    target_type: str
    target_id: str
    knowledge_level: str
    known_content: str | None = None
    misconception: str | None = None


class CharacterContextBundle(BaseModel):
    """人物上下文聚合 — 返回给其他模块的完整人物信息包"""

    characters: list[CharacterContextItem] = Field(
        ...,
        description="人物列表",
    )
    total: int = Field(..., description="总人物数")
    reveal_mode: str = Field(
        default="author_safe",
        description="使用的揭示模式",
    )


class FilterContextRequest(BaseModel):
    """按人物知识过滤上下文的请求"""

    context_items: list[dict] = Field(
        ...,
        description="待过滤的上下文项列表",
    )


class FilterContextResponse(BaseModel):
    """按人物知识过滤上下文的结果"""

    filtered_items: list[dict] = Field(..., description="过滤后的上下文项列表")
    removed_count: int = Field(..., description="被移除的项数")
    replaced_count: int = Field(..., description="被替换为误解的项数")


class EventContext(BaseModel):
    """事件上下文 — 供其他模块使用"""

    model_config = ConfigDict(from_attributes=True)

    entity_id: str
    entity_name: str
    timeline_order: int
    occurrence_time_label: str | None = None
    location_name: str | None = None


class EventsContextBundle(BaseModel):
    """事件上下文组合包"""

    novel_id: str
    events: list[EventContext] = Field(default_factory=list)
    total_count: int = 0


# ============================================================
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
WorldEntityContext = WorldEntityContext
WorldContextBundle = WorldContextBundle


# alias: EntityAliasResponse — 旧名兼容
class EntityAliasResponse(BaseModel):
    """旧别名响应 — 兼容保留"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    novel_id: str
    entity_id: str
    alias: str
    alias_type: str = "name"
    source_chapter_index: int | None = None
    confidence: float = 0.8
    status: str = "confirmed"
    created_at: datetime | None = None


class EntityAliasListResponse(BaseModel):
    """旧别名列表响应 — 兼容保留"""

    items: list[EntityAliasResponse]
    total: int


class EntityAliasCreate(BaseModel):
    """旧别名创建请求 — 兼容保留"""

    entity_id: str = Field(..., description="所属核心实体 ID")
    alias: str = Field(..., min_length=1, max_length=255, description="别名文本")
    alias_type: str = Field(default="name", max_length=20, description="别名类型")
    source_chapter_index: int | None = Field(None, ge=0, description="首次出现的章节索引")
    confidence: float = Field(default=0.8, ge=0.0, le=1.0, description="确认置信度")
    status: str = Field(default="confirmed", max_length=32, description="状态")


class EntityCandidateCreate(BaseModel):
    """旧候选创建请求 — 兼容保留"""

    name: str = Field(..., description="名称")
    entity_type: str = Field(..., description="类型")
    summary: str | None = Field(None, description="概要")
    source_text: str | None = Field(None, description="来源文本")
    source_chapter_index: int | None = Field(None, ge=0, description="来源章节")
    importance_score: float = Field(default=0.5, ge=0.0, le=1.0, description="重要性")
    confidence: float = Field(default=0.5, ge=0.0, le=1.0, description="置信度")
    candidate_reason: str | None = Field(None, description="推荐理由")
    suggested_action: str = Field(
        default="needs_user_decision", max_length=32, description="建议动作"
    )
    suggested_existing_entity_id: str | None = Field(None, description="建议关联对象 ID")
    status: str = Field(default="pending", max_length=32, description="状态")


class EntityCandidateUpdate(BaseModel):
    """旧候选更新请求 — 兼容保留"""

    name: Annotated[str | None, Field(None)]
    entity_type: Annotated[str | None, Field(None)]
    summary: Annotated[str | None, Field(None)]
    source_text: Annotated[str | None, Field(None)]
    source_chapter_index: Annotated[int | None, Field(None)]
    importance_score: Annotated[float | None, Field(None)]
    confidence: Annotated[float | None, Field(None)]
    candidate_reason: Annotated[str | None, Field(None)]
    suggested_action: Annotated[str | None, Field(None)]
    suggested_existing_entity_id: Annotated[str | None, Field(None)]
    status: Annotated[str | None, Field(None)]


class EntityCandidateResponse(BaseModel):
    """旧候选响应 — 兼容保留"""

    model_config = ConfigDict(from_attributes=True, arbitrary_types_allowed=True)

    id: str = ""
    novel_id: str = ""
    name: str = ""
    entity_type: str = ""
    summary: str | None = None
    source_text: str | None = None
    source_chapter_index: int | None = None
    importance_score: float = 0.5
    confidence: float = 0.5
    candidate_reason: str | None = None
    suggested_action: str = "needs_user_decision"
    suggested_existing_entity_id: str | None = None
    status: str = "pending"
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("id", "novel_id", mode="before")
    @classmethod
    def coerce_uuid(cls, v: object) -> str:
        if isinstance(v, uuid.UUID):
            return str(v)
        if isinstance(v, str):
            return v
        return str(v)


class EntityCandidateListResponse(BaseModel):
    """旧候选列表响应 — 兼容保留"""

    items: list[EntityCandidateResponse]
    total: int


class RelationshipCreate(BaseModel):
    """旧关系创建请求 — 兼容保留"""

    source_type: str = Field(..., max_length=32, description="源类型")
    source_id: str = Field(..., description="源 ID")
    target_type: str = Field(..., max_length=32, description="目标类型")
    target_id: str = Field(..., description="目标 ID")
    relation_type: str = Field(..., max_length=32, description="关系类型")
    description: str | None = None
    visibility: str = "author_only"
    strength: float = 0.5
    status: str = "canonical"


class RelationshipUpdate(BaseModel):
    """旧关系更新请求 — 兼容保留"""

    source_type: Annotated[str | None, Field(None)]
    source_id: Annotated[str | None, Field(None)]
    target_type: Annotated[str | None, Field(None)]
    target_id: Annotated[str | None, Field(None)]
    relation_type: Annotated[str | None, Field(None)]
    description: Annotated[str | None, Field(None)]
    visibility: Annotated[str | None, Field(None)]
    strength: Annotated[float | None, Field(None)]
    status: Annotated[str | None, Field(None)]


class RelationshipResponse(BaseModel):
    """旧关系响应 — 兼容保留"""

    model_config = ConfigDict(from_attributes=True)
    id: str = ""
    novel_id: str = ""
    source_type: str = ""
    source_id: str = ""
    target_type: str = ""
    target_id: str = ""
    relation_type: str = ""
    description: str | None = None
    visibility: str = "author_only"
    strength: float = 0.5
    status: str = "canonical"
    created_at: datetime | None = None
    updated_at: datetime | None = None


class RelationshipListResponse(BaseModel):
    """旧关系列表响应 — 兼容保留"""

    items: list[RelationshipResponse]
    total: int
