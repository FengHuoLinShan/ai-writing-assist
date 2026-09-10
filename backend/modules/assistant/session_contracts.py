"""Stable discussion wire contracts, including the legacy World entry."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

WorldCocreationAction = Literal["expand", "connect", "pressure", "consolidate"]


class WorldCocreationSourceRef(BaseModel):
    """会话绑定的创作对象：项目 / 资料页 / 世界对象 / 主题目录。"""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["project", "world_bible_page", "core_entity", "world_library_topic"]
    id: str | None = Field(default=None, min_length=1, max_length=64)

    @model_validator(mode="after")
    def validate_id_presence(self) -> WorldCocreationSourceRef:
        if (self.kind == "project") != (self.id is None):
            raise ValueError(
                "source id is required for object bindings and must be empty "
                "for the project binding"
            )
        return self


class WorldCocreationSessionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    novel_id: str
    title: str = Field(default="世界设定共创", min_length=1, max_length=200)
    source: WorldCocreationSourceRef
    workflow_preset: Literal["default", "world_core"] = "world_core"
    target_kind: str | None = Field(default=None, max_length=32)
    source_page_id: str | None = Field(default=None, min_length=1, max_length=64)


class WorldCocreationSessionUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    novel_id: str
    title: str | None = Field(default=None, min_length=1, max_length=200)
    archived: bool | None = None


class WorldCocreationCheckpointAdvanceRequest(BaseModel):
    """推进会话工作区指针；基线漂移返回可识别冲突，提案保留。"""

    model_config = ConfigDict(extra="forbid")

    novel_id: str
    checkpoint_suggestion_id: str = Field(..., min_length=1, max_length=64)
    expected_checkpoint_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=64,
    )
    round_no: int | None = Field(default=None, ge=0, le=100000)
    depth: Literal["seed", "candidate", "instance"] | None = None


class WorldCocreationSessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    novel_id: str
    title: str
    source_kind: str
    source_id: str | None = None
    workflow_preset: str
    target_kind: str | None = None
    source_page_id: str | None = None
    current_checkpoint_id: str | None = None
    checkpoint_round: int
    checkpoint_depth: str
    last_message_at: datetime | None = None
    status: str
    created_at: datetime
    updated_at: datetime | None = None

    @field_validator(
        "id",
        "novel_id",
        "source_id",
        "source_page_id",
        "current_checkpoint_id",
        mode="before",
    )
    @classmethod
    def coerce_session_uuid(cls, v: object) -> str | None:
        return str(v) if v is not None else None


class WorldCocreationSessionListResponse(BaseModel):
    items: list[WorldCocreationSessionResponse]
    total: int


class WorldCocreationMessageResponse(BaseModel):
    assistant_run_id: str | None = None
    """终态会话消息；outcome_state 由成果建议当前状态实时推导。"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    session_id: str
    role: Literal["author", "assistant"]
    kind: Literal["message", "decision"]
    action: WorldCocreationAction | None = None
    content: str
    context_confirmation_id: str | None = None
    task_id: str | None = None
    outcome_suggestion_id: str | None = None
    outcome_kind: str | None = None
    outcome_state: (
        Literal[
            "pending_review",
            "saved_draft",
            "adopted",
            "rejected",
        ]
        | None
    ) = None
    created_at: datetime

    @field_validator(
        "id",
        "session_id",
        "context_confirmation_id",
        "task_id",
        "outcome_suggestion_id",
        mode="before",
    )
    @classmethod
    def coerce_message_uuid(cls, v: object) -> str | None:
        return str(v) if v is not None else None


class WorldCocreationMessageListResponse(BaseModel):
    items: list[WorldCocreationMessageResponse]
    total: int
    offset: int = 0


class WorldCocreationSessionDetailResponse(BaseModel):
    session: WorldCocreationSessionResponse
    messages: list[WorldCocreationMessageResponse]
    message_total: int
    last_operation: dict[str, str] | None = None


class WorldCocreationMessageCreateRequest(BaseModel):
    """追加作者消息或作者决定；模型回复只能由生成端点写入。"""

    model_config = ConfigDict(extra="forbid")

    novel_id: str
    content: str = Field(..., min_length=1, max_length=100000)
    action: WorldCocreationAction | None = None
    kind: Literal["message", "decision"] = "message"
