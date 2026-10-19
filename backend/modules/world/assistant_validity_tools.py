"""Read-only author relation validity at an exact Story Scene cutoff."""

from typing import Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field

from core.container import get
from core.errors import ConflictError, NotFoundError
from core.service_keys import ASSISTANT_REQUIRE_OPERATION_TARGETS
from infrastructure.stable_hash import stable_hash
from modules.project.facade import get_any_project_context, require_active_project
from modules.world.relation_changes import (
    RelationChange,
    apply_change,
    change_history,
    preview_change,
)
from modules.world.schemas import RelationKind
from modules.world.services.core.entity_relation_service import EntityRelationService
from shared.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE


class ReadRelations(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str | None = None
    relation_type: str | None = None
    relation_kind: RelationKind | None = None
    q: str | None = None
    source_chapter_id: UUID | None = None
    as_of_scene_id: UUID | None = None
    strength_min: float | None = Field(default=None, ge=0.0, le=1.0)
    strength_max: float | None = Field(default=None, ge=0.0, le=1.0)
    skip: int = Field(default=0, ge=0)
    limit: int = Field(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)


async def _read(db, novel_id, args, *, context=None):
    await require_active_project(db, novel_id)
    if context is None or not getattr(context, "run_id", None):
        raise ConflictError("关系读取需要绑定当前作者运行")
    project = await get_any_project_context(db, novel_id)
    if (
        project is None
        or project.project_kind != "author"
        or str(project.owner_id) != str(context.owner_id)
    ):
        raise NotFoundError("项目关系不可访问")
    await get(ASSISTANT_REQUIRE_OPERATION_TARGETS)(
        db, novel_id, context, [], aggregate=True
    )
    result = await EntityRelationService().list(
        db,
        novel_id,
        **args.model_dump(mode="json", exclude_none=True),
    )
    return result.model_dump(mode="json")


class MaintainRelation(RelationChange):
    action: Literal["edit", "end", "restore"]


class RemoveRelation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    relation_id: UUID
    action: Literal["remove"] = "remove"


async def _require_relation_scope(db, novel_id, relation_id, before, context):
    if context is not None:
        focus = context.work.focus_ref
        if (
            focus
            and focus.kind == "relation"
            and str(focus.relation_id) != str(relation_id)
        ):
            raise ConflictError("请保持本轮原关系目标，或重新开启另一条关系任务")
        targets = [
            ("core_entity", before["source_id"]),
            ("core_entity", before["target_id"]),
        ]
        if not context.work.selected_entities:
            targets.append(("entity_relation", relation_id))
        await get(ASSISTANT_REQUIRE_OPERATION_TARGETS)(db, novel_id, context, targets)


async def _change_preview(db, novel_id, args, *, context=None):
    preview = await preview_change(db, novel_id, args)
    await _require_relation_scope(
        db, novel_id, args.relation_id, preview["before"], context
    )
    return preview


class ReadRelationHistory(BaseModel):
    model_config = ConfigDict(extra="forbid")
    relation_id: UUID
    skip: int = Field(default=0, ge=0)
    limit: int = Field(default=20, ge=1, le=50)


async def _history_read(db, novel_id, args, *, context=None):
    result = await change_history(
        db, novel_id, args.relation_id, skip=args.skip, limit=args.limit
    )
    await _require_relation_scope(
        db, novel_id, args.relation_id, result["current"], context
    )
    return result


async def _change_apply(db, novel_id, args, preview, *, context=None):
    if context is None:
        raise ConflictError("关系修改需要明确作者任务")
    if await _change_preview(db, novel_id, args, context=context) != preview:
        raise ConflictError("关系或来源已变化，请重新准备")
    operation_id = str(
        uuid5(
            NAMESPACE_URL,
            f"{context.run_id}:relation:{stable_hash(args.model_dump(mode='json'))}",
        )
    )
    return await apply_change(
        db,
        novel_id,
        args,
        operation_id=operation_id,
        expected_preview_hash=stable_hash(preview),
        actor=context.owner_id,
    )


OPERATIONS_SPEC = {
    "world.relation_history": {
        "label": "读取原关系修改回执",
        "schema": ReadRelationHistory,
        "prepare": _history_read,
        "permission": "read",
        "op_version": "1",
        "description": "读取指定关系的实际修改和恢复记录；没有历史快照时如实说明。",
        "risk_level": "R0",
        "fee_category": "free",
        "reversibility": "read_only",
        "preconditions": ("原关系和端点在作者本次范围内",),
        "produces": ("world_relation_history",),
        "target_type": "world_relation",
        "ai_available": True,
        "transaction_mode": "single_transaction",
        "trace_rule": {
            "parameter_fields": ("relation_id", "skip", "limit"),
            "parameter_policy": "schema_safe",
        },
    },
    "world.maintain_relation": {
        "label": "修改、结束或恢复关系",
        "schema": MaintainRelation,
        "prepare": _change_preview,
        "apply": _change_apply,
        "op_version": "1",
        "description": "准备关系修改、结束作者有效期或恢复原快照；"
        "保持方向与来源，不能移除关系。",
        "risk_level": "R3",
        "fee_category": "free",
        "reversibility": "world_relation_change_history",
        "preconditions": (
            "原关系及端点属于当前作品",
            "预览版本有效",
            "有效期锚点属于本作品且顺序正确",
        ),
        "produces": ("world_relation_change_receipt",),
        "target_type": "world_relation",
        "ai_available": True,
        "transaction_mode": "single_transaction",
        "trace_rule": {
            "parameter_fields": ("relation_id", "action", "changes", "end", "history_id"),
            "parameter_policy": "schema_safe",
        },
    },
    "world.remove_relation": {
        "label": "移除关系并保留历史",
        "schema": RemoveRelation,
        "prepare": _change_preview,
        "apply": _change_apply,
        "op_version": "1",
        "description": "作者人工确认移除关系，保留方向、有效期和内容快照；"
        "自动模式不能代批。",
        "risk_level": "R4",
        "fee_category": "free",
        "reversibility": "world_relation_change_history",
        "preconditions": ("作者本人确认移除", "原关系及端点属于当前作品", "预览版本有效"),
        "produces": ("world_relation_change_receipt",),
        "target_type": "world_relation",
        "ai_available": True,
        "transaction_mode": "single_transaction",
        "trace_rule": {
            "parameter_fields": ("relation_id", "action"),
            "parameter_policy": "schema_safe",
        },
    },
    "world.relations.read": {
        "label": "按场景读取作者关系与有效期",
        "schema": ReadRelations,
        "prepare": _read,
        "permission": "read",
        "op_version": "1",
        "description": "读取本项目关系，可按当前 Scene 核对作者有效期与可信 Story 状态。",
        "risk_level": "R0",
        "fee_category": "free",
        "reversibility": "read_only",
        "preconditions": ("作者拥有当前项目", "仅在原确认范围覆盖整体关系时读取"),
        "produces": ("author_relation_validity_projection",),
        "target_type": "world_relation",
        "ai_available": True,
        "transaction_mode": "single_transaction",
        "trace_rule": {
            "parameter_fields": (
                "status",
                "relation_type",
                "relation_kind",
                "q",
                "source_chapter_id",
                "as_of_scene_id",
                "strength_min",
                "strength_max",
                "skip",
                "limit",
            ),
            "mode": "per_call",
            "parameter_policy": "schema_safe",
        },
    },
}
