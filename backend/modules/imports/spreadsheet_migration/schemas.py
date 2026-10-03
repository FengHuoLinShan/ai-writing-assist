"""表格迁移 HTTP schema（计划 §3.6）— L4 实现路由，L6 消费。

响应不出现 raw JSON 或内部枚举文案；`target_id` 只用于生成跳转链接。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from modules.imports.spreadsheet_migration.constants import ColumnTarget, SheetKind


class _RequestBase(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MappingSheetPayload(_RequestBase):
    sheet_key: str = Field(min_length=1, max_length=32)
    kind: SheetKind
    header_row: int = Field(ge=0, le=32)
    default_entity_type: str | None = Field(None, max_length=64)
    columns: dict[str, ColumnTarget] = Field(default_factory=dict)


class MappingOptionsPayload(_RequestBase):
    written_chapter_policy: Literal["reference_only", "link_scene"] = (
        "reference_only"
    )
    outline_head_policy: Literal["create_if_missing", "replace", "skip"] = (
        "create_if_missing"
    )


class MigrationMappingRequest(_RequestBase):
    novel_id: str = Field(min_length=1)
    expected_revision: int = Field(ge=1)
    sheets: list[MappingSheetPayload] = Field(min_length=1, max_length=100)
    options: MappingOptionsPayload = Field(default_factory=MappingOptionsPayload)


class MigrationDecisionPayload(_RequestBase):
    item_key: str = Field(min_length=1, max_length=64)
    action: str = Field(min_length=1, max_length=64)
    relation_kind: str | None = Field(None, max_length=32)
    accept_ai: bool | None = None


class MigrationDecisionsRequest(_RequestBase):
    novel_id: str = Field(min_length=1)
    expected_revision: int = Field(ge=1)
    decisions: list[MigrationDecisionPayload] = Field(
        default_factory=list,
        max_length=5000,
    )
    relation_kind_groups: dict[str, str] | None = None


class AiCleanupScopePayload(_RequestBase):
    sheet_key: str = Field(min_length=1, max_length=32)
    column_key: str = Field(min_length=1, max_length=16)


class AiRunScopePayload(_RequestBase):
    outline_sheet_keys: list[str] = Field(default_factory=list, max_length=100)
    cleanup: list[AiCleanupScopePayload] = Field(default_factory=list, max_length=200)


class MigrationAiRunRequest(_RequestBase):
    novel_id: str = Field(min_length=1)
    expected_revision: int = Field(ge=1)
    authorization_confirmed: Literal[True]
    operation_id: str = Field(min_length=1, max_length=64)
    scope: AiRunScopePayload = Field(default_factory=AiRunScopePayload)


class MigrationApplyRequest(_RequestBase):
    novel_id: str = Field(min_length=1)
    expected_preview_hash: str = Field(min_length=64, max_length=64)
    confirmed: Literal[True]


class MigrationRollbackRequest(_RequestBase):
    novel_id: str = Field(min_length=1)
    confirmed: Literal[True]


class AiRunResponse(BaseModel):
    task_id: str
    status: str
    reused: bool


class SheetWarningResponse(BaseModel):
    code: str
    message: str


class SheetColumnResponse(BaseModel):
    column_key: str
    header: str
    target: ColumnTarget
    target_suggested: bool


class SheetResponse(BaseModel):
    sheet_key: str
    file_key: str
    name: str
    hidden: bool
    kind: SheetKind
    kind_suggested: bool
    header_row: int
    default_entity_type: str | None = None
    row_count: int
    columns: list[SheetColumnResponse]
    sample_rows: list[list[str]]
    warnings: list[SheetWarningResponse]


class FileResponse(BaseModel):
    file_key: str
    file_name: str
    file_type: str
    size: int


class WorldItemConflictResponse(BaseModel):
    field_label: str
    current_excerpt: str
    incoming_excerpt: str


class SimilarItemResponse(BaseModel):
    label: str


class WorldItemPreviewResponse(BaseModel):
    item_key: str
    decision_scope: Literal["entity", "relation", "story"] = "entity"
    label: str
    type_label: str
    action: str
    target_id: str | None = None
    target_label: str | None = None
    fills: list[str] = Field(default_factory=list)
    conflicts: list[WorldItemConflictResponse] = Field(default_factory=list)
    similar: list[SimilarItemResponse] = Field(default_factory=list)
    source_sheet_name: str
    source_row: int
    decision: str
    ai_available: bool = False
    ai_passed: bool | None = None
    ai_accepted: bool | None = None


class RelationPreviewResponse(BaseModel):
    item_key: str
    decision_scope: Literal["entity", "relation", "story"] = "relation"
    source_label: str
    target_label: str
    relation_type: str
    relation_kind: str | None = None
    kind_guessed: bool = False
    action: str
    reason: str | None = None
    source_sheet_name: str
    source_row: int
    decision: str


class StructurePreviewResponse(BaseModel):
    item_key: str
    decision_scope: Literal["entity", "relation", "story"] = "story"
    kind: str
    label: str
    chapter_label: str | None = None
    action: str
    target_label: str | None = None
    reason: str | None = None
    source_sheet_name: str
    source_row: int
    decision: str
    ai_available: bool = False
    ai_passed: bool | None = None
    ai_accepted: bool | None = None


class OutlinePreviewResponse(BaseModel):
    action: str
    title: str | None = None


class PreviewCountsResponse(BaseModel):
    create: int = 0
    fill: int = 0
    adopt: int = 0
    existing: int = 0
    conflict: int = 0
    skip: int = 0
    relations: int = 0
    structures: int = 0
    reference_only: int = 0


class MigrationPreviewResponse(BaseModel):
    preview_hash: str
    validation_policy_active: bool
    counts: PreviewCountsResponse
    world_items: list[WorldItemPreviewResponse] = Field(default_factory=list)
    relations: list[RelationPreviewResponse] = Field(default_factory=list)
    structures: list[StructurePreviewResponse] = Field(default_factory=list)
    outline: OutlinePreviewResponse | None = None


class AiEstimateResponse(BaseModel):
    rows: int
    chars: int
    requests: int


class AiStateResponse(BaseModel):
    status: str
    task_id: str | None = None
    estimate: AiEstimateResponse | None = None
    blocked_count: int = 0


class ReceiptSummaryResponse(BaseModel):
    created: int
    filled: int
    adopted: int
    relations: int
    structures: int
    outline: bool
    can_rollback: bool


class MigrationErrorStateResponse(BaseModel):
    code: str
    message: str


class MigrationSessionResponse(BaseModel):
    id: str
    status: str
    revision: int
    created_at: str
    applied_at: str | None = None
    rolled_back_at: str | None = None
    files: list[FileResponse]
    sheets: list[SheetResponse]
    options: MappingOptionsPayload
    preview: MigrationPreviewResponse | None = None
    ai: AiStateResponse
    receipt_summary: ReceiptSummaryResponse | None = None
    error: MigrationErrorStateResponse | None = None


class MigrationSessionListItem(BaseModel):
    id: str
    status: str
    file_names: list[str]
    counts: dict[str, int]
    created_at: str
    applied_at: str | None = None
    can_rollback: bool


class MigrationSessionListResponse(BaseModel):
    items: list[MigrationSessionListItem]
    total: int


class MigrationRowsResponse(BaseModel):
    header: list[str]
    rows: list[MigrationRowItem]
    total: int


class MigrationRowItem(BaseModel):
    row: int
    cells: list[str]


class RollbackPreviewKeptItem(BaseModel):
    item_key: str
    label: str
    reason: str


class RollbackRevertibleItem(BaseModel):
    item_key: str
    label: str


class RollbackPreviewResponse(BaseModel):
    revertible: list[RollbackRevertibleItem]
    kept: list[RollbackPreviewKeptItem]


class ApplyResponse(BaseModel):
    status: str
    counts: dict[str, int]
    receipt_summary: ReceiptSummaryResponse


class RollbackResponse(BaseModel):
    status: str
    reverted_count: int
    kept: list[RollbackPreviewKeptItem]


__all__ = [
    "AiCleanupScopePayload",
    "AiEstimateResponse",
    "AiRunResponse",
    "AiRunScopePayload",
    "AiStateResponse",
    "ApplyResponse",
    "FileResponse",
    "MappingOptionsPayload",
    "MappingSheetPayload",
    "MigrationAiRunRequest",
    "MigrationApplyRequest",
    "MigrationDecisionPayload",
    "MigrationDecisionsRequest",
    "MigrationErrorStateResponse",
    "MigrationMappingRequest",
    "MigrationPreviewResponse",
    "MigrationRollbackRequest",
    "MigrationRowItem",
    "MigrationRowsResponse",
    "MigrationSessionListItem",
    "MigrationSessionListResponse",
    "MigrationSessionResponse",
    "OutlinePreviewResponse",
    "PreviewCountsResponse",
    "RelationPreviewResponse",
    "RollbackPreviewKeptItem",
    "RollbackPreviewResponse",
    "RollbackRevertibleItem",
    "RollbackResponse",
    "SheetColumnResponse",
    "SheetResponse",
    "SheetWarningResponse",
    "StructurePreviewResponse",
    "WorldItemConflictResponse",
    "WorldItemPreviewResponse",
]
