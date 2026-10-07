"""World library 资料库 schema。"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

from modules.world.schemas._common import OptionalUuidStr, _optional_uuid_validator
from modules.world.schemas.relations import EntityRelationResponse

# World library: unified list, topics, author workspace
# ============================================================


class WorldLibraryItemResponse(BaseModel):
    """统一资料列表条目：正式页合并其工作稿后只显示一项。"""

    model_config = ConfigDict(from_attributes=True)

    kind: Literal["page", "draft", "entity"]
    id: Annotated[str, BeforeValidator(_optional_uuid_validator)]
    title: str = "未命名资料"
    summary: str = ""
    state: Literal["active", "review", "archived"] = "review"
    working: bool = False
    draft_id: OptionalUuidStr = None
    item_type: str = ""
    status: str = ""
    is_favorite: bool = False
    last_opened_at: datetime | None = None
    updated_at: datetime | None = None
    created_at: datetime | None = None
    relation_refs: list[WorldLibraryRelationRef] = Field(default_factory=list)


class WorldLibraryRelationRef(BaseModel):
    """成员在当前视角下的一条匹配关系及其执行指纹。"""

    relation: EntityRelationResponse
    execution_fingerprint: str = Field(..., min_length=64, max_length=64)


class WorldLibraryListResponse(BaseModel):
    items: list[WorldLibraryItemResponse]
    total: int


class WorldLibraryTopicNode(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: Annotated[str, BeforeValidator(_optional_uuid_validator)]
    name: str
    description: str | None = None
    status: str = "active"
    sort_order: int = 100
    parent_id: OptionalUuidStr = None
    member_count: int = 0
    children: list[WorldLibraryTopicNode] = Field(default_factory=list)


class WorldLibraryTopicTreeResponse(BaseModel):
    topics: list[WorldLibraryTopicNode]


class WorldLibraryTopicCreate(BaseModel):
    novel_id: str
    parent_id: str | None = Field(default=None, min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=1000)


class WorldLibraryTopicUpdate(BaseModel):
    novel_id: str
    name: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=1000)
    expected_updated_at: datetime | None = None

    @model_validator(mode="after")
    def reject_null_required_fields(self) -> WorldLibraryTopicUpdate:
        for field_name in {"name", "description"}:
            if field_name in self.model_fields_set and getattr(self, field_name) is None:
                raise ValueError(f"{field_name} cannot be null")
        return self


class WorldLibraryTopicMoveRequest(BaseModel):
    novel_id: str
    parent_id: str | None = Field(default=None, min_length=1, max_length=64)
    position: Literal["start", "end"] = "end"
    expected_updated_at: datetime | None = None


class WorldLibraryTopicReorderRequest(BaseModel):
    novel_id: str
    parent_id: str | None = Field(default=None, min_length=1, max_length=64)
    ordered_ids: list[str] = Field(..., min_length=1, max_length=200)


class WorldLibraryTopicArchiveRequest(BaseModel):
    novel_id: str
    archived: bool


class WorldLibraryMemberRequest(BaseModel):
    novel_id: str
    target_kind: Literal["page", "draft", "entity"]
    target_id: str = Field(..., min_length=1, max_length=64)


class WorldLibraryMembershipsResponse(BaseModel):
    topic_ids: list[str] = Field(default_factory=list)


class WorldLibraryMemberResponse(BaseModel):
    topic_id: str
    target_kind: str
    target_id: str
    added: bool = True


class WorldLibraryRecentRequest(BaseModel):
    novel_id: str
    target_kind: Literal["page", "draft", "entity"]
    target_id: str = Field(..., min_length=1, max_length=64)


class WorldLibraryFavoriteRequest(BaseModel):
    novel_id: str
    target_kind: Literal["page", "draft", "entity"]
    target_id: str = Field(..., min_length=1, max_length=64)


class WorldLibraryFavoriteResponse(BaseModel):
    target_kind: str
    target_id: str
    favorited: bool


class WorldLibraryViewPrefsResponse(BaseModel):
    view_prefs: dict[str, Any] = Field(default_factory=dict)


class WorldLibraryViewPrefsUpdate(BaseModel):
    novel_id: str
    view_prefs: dict[str, Any] = Field(default_factory=dict)


class WorldLibraryOverviewResponse(BaseModel):
    topics: list[WorldLibraryTopicNode] = Field(default_factory=list)
    totals: dict[str, int] = Field(default_factory=dict)
    type_facets: list[dict[str, Any]] = Field(default_factory=list)
    recent_items: list[WorldLibraryItemResponse] = Field(default_factory=list)
    favorite_items: list[WorldLibraryItemResponse] = Field(default_factory=list)
    working_items: list[WorldLibraryItemResponse] = Field(default_factory=list)
