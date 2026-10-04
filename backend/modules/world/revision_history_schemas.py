"""World 修订历史 Pydantic Schema — 编辑历史元数据（路线图阶段 0）。

自 schemas.py 拆出（P8 文件行数门禁：schemas.py 超限只许下降），
依赖方向与 relation_schemas.py 相同：本模块可引用 schemas.py 的基元与类型，
反向禁止。``EntityRevisionListResponse`` 自 schemas.py 迁入后，
schemas.py 中的旧定义由路由接线包（P2）移除并统一改引本模块。

合同来源：.agent/tasks/2026/T-20261004-world-edit-history/TASK.md §6.2。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    field_validator,
)

RevisionTargetKind = Literal["entity", "page", "map"]

EntityRevisionField = Literal[
    "entity_type",
    "name",
    "summary",
    "public_info",
    "hidden_truth",
    "aliases",
    "content",
    "importance",
    "reveal_level",
    "status",
]

REVISION_NOTE_MAX_LENGTH = 500


def _revision_uuid_validator(value: Any) -> Any:
    """宽松校验：字符串必须能解析为 UUID，uuid 对象原样通过。"""
    if isinstance(value, uuid.UUID):
        return value
    if isinstance(value, str):
        return str(uuid.UUID(hex=value))
    return value


RevisionIdStr = Annotated[str, BeforeValidator(_revision_uuid_validator)]


class EntityRevisionSnapshotView(BaseModel):
    """带类型的实体快照视图；``content_json`` 已去掉内部来源标记，别名单独拆出。"""

    model_config = ConfigDict(extra="ignore")

    entity_type: str
    name: str
    summary: str | None = None
    public_info: str | None = None
    hidden_truth: str | None = None
    aliases: list[str] = Field(default_factory=list)
    content_json: dict[str, Any] = Field(default_factory=dict)
    importance: float | None = None
    importance_level: str | None = None
    reveal_level: str | None = None
    status: str


class EntityRevisionItem(BaseModel):
    """实体历史中的一条改动记录。"""

    revision_id: str
    entity_id: str
    revision_reason: str
    created_at: datetime
    writing_chapter_index: int | None = None
    change_note: str | None = None
    changed_fields: list[EntityRevisionField] | None = None
    changed_fields_exact: bool = False
    restored_from_revision_id: str | None = None
    snapshot: EntityRevisionSnapshotView
    can_restore: bool = False


class EntityRevisionListResponse(BaseModel):
    """实体历史列表响应（自 schemas.py 迁入并扩展强类型条目）。"""

    items: list[EntityRevisionItem] = Field(default_factory=list)
    total: int
    skip: int = 0
    limit: int = 20
    current_updated_at: datetime | None = None


class EntityRevisionRollbackRequest(BaseModel):
    """按修订恢复实体的请求体；基线过期由服务返回 409。"""

    model_config = ConfigDict(extra="forbid")

    revision_id: str
    expected_updated_at: datetime


class RevisionNoteUpdateRequest(BaseModel):
    """修订备注补写/修改/删除请求；空串表示删除。"""

    model_config = ConfigDict(extra="forbid")

    target_kind: RevisionTargetKind
    revision_id: str
    note: Annotated[
        str,
        BeforeValidator(lambda value: value.strip() if isinstance(value, str) else value),
        Field(max_length=REVISION_NOTE_MAX_LENGTH),
    ]

    @field_validator("revision_id")
    @classmethod
    def _validate_revision_id(cls, value: str) -> str:
        try:
            return str(uuid.UUID(hex=value))
        except (ValueError, TypeError) as exc:
            raise ValueError("revision_id 必须是合法 UUID") from exc


class RevisionNoteResponse(BaseModel):
    """修订备注写入结果；``note`` 为空表示该修订当前没有备注。"""

    target_kind: RevisionTargetKind
    revision_id: RevisionIdStr
    note: str | None = None
    updated_at: datetime


class WorldChangeHistoryItem(BaseModel):
    """世界改动记录时间线中的一条（实体/页面/地图三类合并）。"""

    kind: RevisionTargetKind
    revision_id: str
    target_id: str
    target_title: str
    target_state: Literal["active", "removed"]
    reason: str | None = None
    created_at: datetime
    writing_chapter_index: int | None = None
    version_number: int | None = None
    changed_fields: list[str] | None = None
    change_note: str | None = None


class WorldChangeHistoryResponse(BaseModel):
    """世界改动记录分页响应；``next_cursor`` 为空表示没有更多。"""

    items: list[WorldChangeHistoryItem] = Field(default_factory=list)
    next_cursor: str | None = None
