"""AI 实体/关系抽取契约。"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field, field_validator

from modules.world.schemas._common import RelationKind, _normalize_system_entity_type


class ExtractedEntity(BaseModel):
    """AI 提取的实体"""

    # 与 modules.imports.llm_schemas.ExtractedEntity 短名冲突；按 events.py
    # 的先例钉住定义模块路径，保持拆包前 FastAPI/pydantic 生成的 OpenAPI
    # 组件名不变。
    __module__ = "modules.world.schemas"

    entity_type: str = Field(
        ...,
        description="受支持实体类型（如 character/faction/item）",
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

    @field_validator("entity_type")
    @classmethod
    def normalize_entity_type_field(cls, v: str) -> str:
        return _normalize_system_entity_type(v)


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
    relation_kind: RelationKind | None = None
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


class WorldAliasRelationExtractRequest(BaseModel):
    """手动别名/关系补抽请求。"""

    novel_id: str
    context_confirmation_id: str
    start_chapter: int = Field(..., ge=1)
    end_chapter: int = Field(..., ge=1)
    scene_ids: list[str] | None = Field(default=None, min_length=1, max_length=10_000)
    operation_id: uuid.UUID | None = None

    @field_validator("scene_ids")
    @classmethod
    def require_unique_scene_ids(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        normalized = [item.strip() for item in value]
        if any(not item for item in normalized) or len(normalized) != len(
            set(normalized)
        ):
            raise ValueError("scene_ids must contain unique non-empty ids")
        return normalized


class WorldAliasRelationExtractResponse(BaseModel):
    """手动别名/关系补抽入队响应。"""

    task_id: str
    status: str = "pending"
