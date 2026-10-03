"""World 关系域 Pydantic Schema — 关系建议、分组视角与成员批量操作。

自 schemas.py 拆出（P8 文件行数门禁：schemas.py 超限只许下降），
依赖方向单向：本模块可引用 schemas.py 的基元与类型，反向禁止。
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from modules.world.schemas import (
    RelationKind,
    WorldBibleSourceRef,
    _optional_uuid_validator,
)


class EntityRelationSuggestionPayload(BaseModel):
    """待处理关系建议；确认后由 world 创建已采用关系。"""

    source_id: str
    target_id: str
    relation_type: str = Field(..., min_length=1, max_length=64)
    relation_kind: RelationKind | None = None
    description: str | None = None
    strength: float = Field(default=0.5, ge=0.0, le=1.0)
    source_chapter_id: str | None = None
    quote: str | None = None
    source_refs: list[WorldBibleSourceRef] = Field(default_factory=list)
    knowledge_review: dict[str, Any] | None = None

    @field_validator("source_id", "target_id", "source_chapter_id")
    @classmethod
    def coerce_optional_relation_uuid(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return str(uuid.UUID(value))


class WorldRelationGroupRelationOption(BaseModel):
    """视角内一条可添加／可匹配的详细关系。"""

    relation_type: str
    label: str
    relation_kind: str
    group_side: Literal["source", "target"]


class WorldRelationGroupViewInfo(BaseModel):
    """分组查询响应中的视角描述（预设；custom 由请求参数即时表达）。"""

    key: str
    title: str
    description: str = ""
    group_types: list[str] = Field(default_factory=list)
    member_types: list[str] | None = None
    match_relations: list[WorldRelationGroupRelationOption] = Field(
        default_factory=list
    )
    default_relation: WorldRelationGroupRelationOption
    custom: bool = False


class WorldRelationGroupItem(BaseModel):
    """视角下的一个分组（组对象）及其去重成员数。"""

    id: Annotated[str, BeforeValidator(_optional_uuid_validator)]
    name: str
    entity_type: str
    member_count: int = 0


class WorldRelationGroupListResponse(BaseModel):
    """GET /world/library/relation-groups 响应。"""

    views: list[WorldRelationGroupViewInfo] = Field(default_factory=list)
    items: list[WorldRelationGroupItem] = Field(default_factory=list)
    total: int = 0
    unlinked_total: int = 0
    skip: int = 0
    limit: int = 50


class WorldRelationMembershipRef(BaseModel):
    """移出清单中的一条关系引用及其期望执行指纹。"""

    id: Annotated[str, BeforeValidator(_optional_uuid_validator)]
    expected_execution_fingerprint: str = Field(
        ...,
        min_length=64,
        max_length=64,
        description="读取该关系时返回的 execution_fingerprint",
    )


class WorldRelationMembershipBatchRequest(BaseModel):
    """POST /world/relations/membership-batch 请求（单个与批量共用入口）。"""

    model_config = ConfigDict(extra="forbid")

    novel_id: str
    action: Literal["add", "remove"]
    group_view: str = Field(..., min_length=1, max_length=32)
    group_id: str = Field(..., min_length=1, max_length=64)
    member_ids: Annotated[list[str], Field(..., min_length=1, max_length=50)]
    confirmed: Literal[True] = Field(
        ...,
        description="必须显式确认为 true 才执行",
    )
    group_type: Annotated[str | None, Field(None, min_length=1, max_length=64)] = None
    member_type: Annotated[str | None, Field(None, min_length=1, max_length=64)] = None
    relation_type: Annotated[
        str | None, Field(None, min_length=1, max_length=64)
    ] = None
    relation_kind: RelationKind | None = None
    group_side: Literal["source", "target"] | None = None
    relation_refs: list[WorldRelationMembershipRef] | None = Field(
        None,
        min_length=1,
        max_length=50,
        description="remove 时必须提供完整清单；add 时必须省略",
    )

    @field_validator("member_ids")
    @classmethod
    def dedupe_member_ids(cls, value: list[str]) -> list[str]:
        seen: set[str] = set()
        deduped: list[str] = []
        for item in value:
            if item not in seen:
                seen.add(item)
                deduped.append(item)
        return deduped

    @model_validator(mode="after")
    def check_action_fields(self) -> WorldRelationMembershipBatchRequest:
        if self.action == "add":
            if self.relation_refs is not None:
                raise ValueError("add 请求不能携带 relation_refs")
            if self.group_view == "custom":
                missing = [
                    name
                    for name, present in (
                        ("relation_type", self.relation_type),
                        ("relation_kind", self.relation_kind),
                        ("group_side", self.group_side),
                    )
                    if present is None
                ]
                if missing:
                    raise ValueError(
                        f"custom 视角 add 必须显式指定：{', '.join(missing)}"
                    )
            return self
        if self.relation_refs is None:
            raise ValueError("remove 请求必须携带 relation_refs 完整清单")
        return self


class WorldRelationMembershipBatchResponse(BaseModel):
    """POST /world/relations/membership-batch 成功响应（无部分写入）。"""

    added_count: int = 0
    reused_count: int = 0
    removed_count: int = 0
    affected_relation_ids: list[str] = Field(default_factory=list)
