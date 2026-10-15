"""Project-owned object validity switch for the Assistant operation catalog."""

from pydantic import BaseModel, ConfigDict

from core.errors import ConflictError, NotFoundError
from modules.project.facade import get_any_project_context, require_active_project
from modules.project.object_dossier_settings import (
    ObjectDossierSettingsUpdate,
    read_object_dossier_settings,
    update_object_dossier_settings,
)


class ReadObjectValiditySettings(BaseModel):
    model_config = ConfigDict(extra="forbid")


async def _scope(db, novel_id, context):
    await require_active_project(db, novel_id)
    if context is None or not getattr(context, "run_id", None):
        raise ConflictError("项目设置操作需要绑定当前作者运行")
    project = await get_any_project_context(db, novel_id)
    if (
        project is None
        or project.project_kind != "author"
        or str(project.owner_id) != str(context.owner_id)
    ):
        raise NotFoundError("项目设置不可访问")


async def _read(db, novel_id, _args, *, context=None):
    await _scope(db, novel_id, context)
    return await read_object_dossier_settings(db, novel_id)


async def _edit_preview(db, novel_id, args, *, context=None):
    current = await _read(db, novel_id, args, context=context)
    if current["version"] != args.expected_version:
        raise ConflictError("对象有效期设置已变化，请先读取当前设置")
    return {
        "before": current,
        "after": {
            "version": args.expected_version + 1,
            "allow_story_override": args.allow_story_override,
        },
    }


async def _edit_apply(db, novel_id, args, preview, *, context=None):
    if await _edit_preview(db, novel_id, args, context=context) != preview:
        raise ConflictError("项目设置预览已变化，请重新确认")
    return await update_object_dossier_settings(db, novel_id, args)


OPERATIONS_SPEC = {
    "project.object_validity_settings.read": {
        "label": "读取对象有效期策略",
        "schema": ReadObjectValiditySettings,
        "prepare": _read,
        "permission": "read",
        "op_version": "1",
        "description": "读取当前作者项目是否允许可信剧情状态覆盖作者有效期。",
        "risk_level": "R0",
        "fee_category": "free",
        "reversibility": "read_only",
        "preconditions": ("作者拥有当前项目",),
        "produces": ("object_validity_settings",),
        "target_type": "project",
        "ai_available": True,
        "transaction_mode": "single_transaction",
        "trace_rule": {
            "parameter_fields": (),
            "mode": "per_call",
            "parameter_policy": "schema_safe",
        },
    },
    "project.object_validity_settings.edit": {
        "label": "更改对象有效期策略",
        "schema": ObjectDossierSettingsUpdate,
        "prepare": _edit_preview,
        "apply": _edit_apply,
        "permission": "confirm",
        "op_version": "1",
        "description": "按版本基线更改当前作者项目的剧情有效期覆盖开关。",
        "risk_level": "R2",
        "fee_category": "free",
        "reversibility": "editable_setting",
        "preconditions": ("作者拥有当前项目", "设置版本基线未变化"),
        "produces": ("object_validity_settings",),
        "target_type": "project",
        "ai_available": True,
        "transaction_mode": "single_transaction",
        "trace_rule": {
            "parameter_fields": ("expected_version", "allow_story_override"),
            "mode": "per_call",
            "parameter_policy": "schema_safe",
        },
    },
}
