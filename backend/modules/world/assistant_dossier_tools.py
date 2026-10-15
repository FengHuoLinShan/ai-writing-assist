"""Read and preview/confirm operations for author-owned object dossiers."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from core.container import get
from core.errors import ConflictError, NotFoundError
from core.service_keys import ASSISTANT_REQUIRE_OPERATION_TARGETS
from modules.project.facade import get_any_project_context
from modules.world.facade import (
    create_world_object_dossier_entry,
    edit_world_object_dossier_entry,
    get_world_object_dossier_template,
    preview_world_object_dossier_entry_create,
    preview_world_object_dossier_entry_edit,
    preview_world_object_dossier_entry_restore,
    preview_world_object_dossier_template,
    read_world_object_dossier,
    read_world_object_dossier_history,
    read_world_object_dossier_template_history,
    restore_world_object_dossier_entry,
    save_world_object_dossier_template,
)
from modules.world.schemas.dossier import (
    DossierEntryCreate,
    DossierEntryRestore,
    DossierEntryUpdate,
    DossierTemplateUpsert,
)


class ReadDossier(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entity_id: UUID
    as_of_scene_id: UUID | None = None
    limit: int = Field(default=100, ge=1, le=250)
    offset: int = Field(default=0, ge=0)


class ReadDossierHistory(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entity_id: UUID
    entry_group_id: UUID | None = None
    limit: int = Field(default=100, ge=1, le=500)
    offset: int = Field(default=0, ge=0)


class ReadDossierTemplate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profile_type: str = Field(min_length=1, max_length=64)


class CreateDossierEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entity_id: UUID
    entry: DossierEntryCreate


class EditDossierEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entity_id: UUID
    revision_id: UUID
    update: DossierEntryUpdate


class RestoreDossierEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entity_id: UUID
    entry_group_id: UUID
    restore: DossierEntryRestore


class EditDossierTemplate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profile_type: str = Field(min_length=1, max_length=64)
    update: DossierTemplateUpsert


async def _scope(db, novel_id, context, *, entity_id=None, aggregate=False):
    if context is None or not getattr(context, "run_id", None):
        raise ConflictError("对象档案操作需要绑定当前作者运行")
    project = await get_any_project_context(db, novel_id)
    if (
        project is None
        or project.project_kind != "author"
        or str(project.owner_id) != str(getattr(context, "owner_id", ""))
    ):
        raise NotFoundError("对象档案不可访问")
    targets = [("core_entity", entity_id)] if entity_id is not None else []
    await get(ASSISTANT_REQUIRE_OPERATION_TARGETS)(
        db, novel_id, context, targets, aggregate=aggregate
    )
    return project


async def _read_dossier(db, novel_id, args, *, context=None):
    await _scope(db, novel_id, context, entity_id=args.entity_id)
    result = await read_world_object_dossier(
        db,
        novel_id,
        str(args.entity_id),
        as_of_scene_id=str(args.as_of_scene_id) if args.as_of_scene_id else None,
        limit=args.limit,
        offset=args.offset,
    )
    return result.model_dump(mode="json")


async def _read_history(db, novel_id, args, *, context=None):
    await _scope(db, novel_id, context, entity_id=args.entity_id)
    result = await read_world_object_dossier_history(
        db,
        novel_id,
        str(args.entity_id),
        entry_group_id=str(args.entry_group_id) if args.entry_group_id else None,
        limit=args.limit,
        offset=args.offset,
    )
    return result.model_dump(mode="json")


async def _read_template(db, novel_id, args, *, context=None):
    await _scope(db, novel_id, context, aggregate=True)
    result = await get_world_object_dossier_template(db, novel_id, args.profile_type)
    return result.model_dump(mode="json")


async def _create_preview(db, novel_id, args, *, context=None):
    await _scope(db, novel_id, context, entity_id=args.entity_id)
    return await preview_world_object_dossier_entry_create(
        db, novel_id, str(args.entity_id), args.entry
    )


async def _create_apply(db, novel_id, args, preview, *, context=None):
    current = await _create_preview(db, novel_id, args, context=context)
    if current != preview:
        raise ConflictError("档案创建预览已变化，请重新确认")
    result = await create_world_object_dossier_entry(
        db,
        novel_id,
        str(args.entity_id),
        args.entry,
        source="author_assistant",
    )
    return {
        "type": "world_object_dossier_entry",
        "id": str(result.id),
        "entry_group_id": str(result.entry_group_id),
        "revision_number": result.revision_number,
        "label": result.facing_label,
    }


async def _edit_preview(db, novel_id, args, *, context=None):
    await _scope(db, novel_id, context, entity_id=args.entity_id)
    return await preview_world_object_dossier_entry_edit(
        db,
        novel_id,
        str(args.entity_id),
        str(args.revision_id),
        args.update,
    )


async def _edit_apply(db, novel_id, args, preview, *, context=None):
    current = await _edit_preview(db, novel_id, args, context=context)
    if current != preview:
        raise ConflictError("档案编辑预览已变化，请重新确认")
    result = await edit_world_object_dossier_entry(
        db,
        novel_id,
        str(args.entity_id),
        str(args.revision_id),
        args.update,
        source="author_assistant",
    )
    return {
        "type": "world_object_dossier_entry",
        "id": str(result.id),
        "entry_group_id": str(result.entry_group_id),
        "revision_number": result.revision_number,
        "label": result.facing_label,
    }


async def _restore_preview(db, novel_id, args, *, context=None):
    await _scope(db, novel_id, context, entity_id=args.entity_id)
    return await preview_world_object_dossier_entry_restore(
        db,
        novel_id,
        str(args.entity_id),
        str(args.entry_group_id),
        args.restore,
    )


async def _restore_apply(db, novel_id, args, preview, *, context=None):
    current = await _restore_preview(db, novel_id, args, context=context)
    if current != preview:
        raise ConflictError("档案恢复预览已变化，请重新确认")
    result = await restore_world_object_dossier_entry(
        db,
        novel_id,
        str(args.entity_id),
        str(args.entry_group_id),
        args.restore,
        source="author_assistant",
    )
    return {
        "type": "world_object_dossier_entry",
        "id": str(result.id),
        "entry_group_id": str(result.entry_group_id),
        "revision_number": result.revision_number,
        "label": result.facing_label,
    }


async def _template_edit_preview(db, novel_id, args, *, context=None):
    await _scope(db, novel_id, context, aggregate=True)
    if context.work.scope == "current" and (
        context.work.chapter_index or context.work.scene_id
    ):
        raise ConflictError("档案模板属于全书范围，请切换到项目资料范围后再修改")
    return await preview_world_object_dossier_template(
        db, novel_id, args.profile_type, args.update
    )


async def _template_edit_apply(db, novel_id, args, preview, *, context=None):
    current = await _template_edit_preview(db, novel_id, args, context=context)
    if current != preview:
        raise ConflictError("档案模板预览已变化，请重新确认")
    result = await save_world_object_dossier_template(
        db, novel_id, args.profile_type, args.update, source="author_assistant"
    )
    return {
        "type": "world_object_dossier_template",
        "id": str(result.template_id),
        "revision_id": str(result.revision_id),
        "version_number": result.version_number,
        "label": result.profile_type,
    }


async def _template_history(db, novel_id, args, *, context=None):
    await _scope(db, novel_id, context, aggregate=True)
    result = await read_world_object_dossier_template_history(
        db, novel_id, args.profile_type
    )
    return result.model_dump(mode="json")


def _trace(parameter_fields: tuple[str, ...]) -> dict:
    return {
        "parameter_fields": parameter_fields,
        "mode": "per_call",
        "parameter_policy": "schema_safe",
    }


def _read_metadata(
    parameter_fields: tuple[str, ...], description: str, target_type: str
) -> dict:
    return {
        "op_version": "1",
        "description": description,
        "risk_level": "R0",
        "fee_category": "free",
        "reversibility": "read_only",
        "preconditions": ("作者拥有当前项目", "目标对象位于本项目"),
        "produces": ("author_safe_dossier_projection",),
        "target_type": target_type,
        "ai_available": True,
        "transaction_mode": "single_transaction",
        "trace_rule": _trace(parameter_fields),
        "permission": "read",
    }


def _write_metadata(
    parameter_fields: tuple[str, ...], description: str, target_type: str
) -> dict:
    return {
        "op_version": "1",
        "description": description,
        "risk_level": "R2",
        "fee_category": "free",
        "reversibility": "restorable_append_only",
        "preconditions": (
            "作者拥有当前项目",
            "目标对象已采用",
            "作者确认当前预览和修订基线",
        ),
        "produces": ("author_confirmed_world_dossier_revision",),
        "target_type": target_type,
        "ai_available": True,
        "transaction_mode": "single_transaction",
        "trace_rule": _trace(parameter_fields),
        "permission": "confirm",
    }


OPERATIONS_SPEC = {
    "world.dossier.read": {
        "label": "读取对象档案",
        "schema": ReadDossier,
        "prepare": _read_dossier,
        **_read_metadata(
            ("entity_id", "as_of_scene_id", "limit", "offset"),
            "读取本项目对象的 World 设定层档案。",
            "core_entity",
        ),
    },
    "world.dossier.history.read": {
        "label": "读取对象档案历史",
        "schema": ReadDossierHistory,
        "prepare": _read_history,
        **_read_metadata(
            ("entity_id", "entry_group_id", "limit", "offset"),
            "读取本项目对象的可恢复档案修订历史。",
            "core_entity",
        ),
    },
    "world.dossier.template.read": {
        "label": "读取对象档案模板",
        "schema": ReadDossierTemplate,
        "prepare": _read_template,
        **_read_metadata(
            ("profile_type",),
            "读取本项目对象类型使用的面向模板。",
            "world_dossier_template",
        ),
    },
    "world.dossier.entry.create": {
        "label": "新增对象档案条目",
        "schema": CreateDossierEntry,
        "prepare": _create_preview,
        "apply": _create_apply,
        **_write_metadata(
            ("entity_id", "entry"),
            "预览并在作者确认后新增一条对象档案。",
            "core_entity",
        ),
    },
    "world.dossier.entry.edit": {
        "label": "修订对象档案条目",
        "schema": EditDossierEntry,
        "prepare": _edit_preview,
        "apply": _edit_apply,
        **_write_metadata(
            ("entity_id", "revision_id", "update"),
            "预览并在作者确认后追加对象档案修订。",
            "core_entity",
        ),
    },
    "world.dossier.entry.restore": {
        "label": "恢复对象档案历史版本",
        "schema": RestoreDossierEntry,
        "prepare": _restore_preview,
        "apply": _restore_apply,
        **_write_metadata(
            ("entity_id", "entry_group_id", "restore"),
            "预览并在作者确认后把历史内容恢复为新修订。",
            "core_entity",
        ),
    },
    "world.dossier.template.edit": {
        "label": "修订对象档案模板",
        "schema": EditDossierTemplate,
        "prepare": _template_edit_preview,
        "apply": _template_edit_apply,
        "revision": "2",
        **_write_metadata(
            ("profile_type", "update"),
            "预览并在作者确认后追加对象档案模板修订。",
            "world_dossier_template",
        ),
        "op_version": "2",
    },
}


__all__ = ["OPERATIONS_SPEC"]
