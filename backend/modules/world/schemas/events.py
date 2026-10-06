"""事件 schema。"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from modules.world.schemas._common import UuidStr

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

    # 与 modules.local_agent.api.EventUpdate 短名冲突；钉住定义模块路径，
    # 保持拆包前 FastAPI/pydantic 生成的 OpenAPI 组件名不变。
    __module__ = "modules.world.schemas"

    source_chapter_id: Annotated[str | None, Field(None)]
    location_entity_id: Annotated[str | None, Field(None)]
    timeline_order: Annotated[int | None, Field(None, ge=0)]
    occurrence_time_label: Annotated[str | None, Field(None, max_length=100)]


class EventResponse(BaseModel):
    """事件响应"""

    model_config = ConfigDict(from_attributes=True)

    entity_id: UuidStr
    novel_id: UuidStr
    source_chapter_id: UuidStr
    location_entity_id: UuidStr
    timeline_order: int
    occurrence_time_label: str | None = None


class EventListResponse(BaseModel):
    """事件列表响应"""

    # 与 modules.story.continuity.schemas.EventListResponse 短名冲突，同上。
    __module__ = "modules.world.schemas"

    items: list[EventResponse]
    total: int
