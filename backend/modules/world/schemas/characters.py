"""人物与人物知识 schema。"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

from modules.world.schemas._common import (
    OptionalUuidStr,
    UuidStr,
    _optional_uuid_validator,
)

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
    expected_updated_at: Annotated[
        datetime | None,
        Field(None, description="编辑基线；缺失或过期返回 409，不接受无条件覆盖"),
    ]


class CharacterResponse(BaseModel):
    """人物响应 — 从 ORM 转换"""

    model_config = ConfigDict(
        from_attributes=True,
        json_encoders={uuid.UUID: str},
    )

    entity_id: UuidStr
    novel_id: UuidStr
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


class CharacterListResponse(BaseModel):
    """人物列表响应"""

    items: list[CharacterResponse]
    total: int


def _require_misconception_for_false_belief_or_misunderstood(
    model: BaseModel,
) -> BaseModel:
    """shared model_validator: false_belief/misunderstood 必须提供 misconception。"""
    if getattr(model, "knowledge_level") in {
        "false_belief",
        "misunderstood",
    } and not getattr(model, "misconception"):
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
    is_public_baseline: bool = Field(
        default=False,
        description="无来源章节时，是否为人物从开场就已知的公开基线",
    )
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
    is_public_baseline: bool | None = None
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

    id: Annotated[str, BeforeValidator(_optional_uuid_validator)]
    novel_id: Annotated[str, BeforeValidator(_optional_uuid_validator)]
    character_id: Annotated[str, BeforeValidator(_optional_uuid_validator)]
    target_type: str
    target_id: Annotated[str, BeforeValidator(_optional_uuid_validator)]
    target_name: str | None = None
    target_entity_type: str | None = None
    knowledge_level: str
    known_content: str | None = None
    misconception: str | None = None
    source_chapter_index: int | None = None
    is_public_baseline: bool = False
    source_memory_id: OptionalUuidStr = None
    status: str = "canonical"
    created_at: datetime | None = None
    updated_at: datetime | None = None


class CharacterKnowledgeListResponse(BaseModel):
    """人物知识列表响应"""

    items: list[CharacterKnowledgeResponse]
    total: int
