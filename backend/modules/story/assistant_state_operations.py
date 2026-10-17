"""Author-confirmed Story state operations over exact World-owned identities."""

from core.container import get
from core.errors import ConflictError
from core.service_keys import (
    ASSISTANT_REQUIRE_OPERATION_TARGETS,
    WORLD_REQUIRE_CUSTOM_TEXT_STATE_FIELD,
    WORLD_REQUIRE_MAP_DECLARATION_STATE,
)
from modules.project.facade import require_active_project
from modules.story.continuity.facade import (
    confirm_custom_text_state,
    confirm_map_declaration_state,
)
from modules.story.continuity.schemas import (
    CustomTextStateUpdateRequest,
    MapDeclarationStateUpdateRequest,
)


async def _scope(db, novel_id, context, targets):
    await require_active_project(db, novel_id)
    if context is None or not getattr(context, "run_id", None):
        raise ConflictError("已确认的状态修改需要当前作者运行")
    await get(ASSISTANT_REQUIRE_OPERATION_TARGETS)(db, novel_id, context, targets)


async def _custom_preview(db, novel_id, args, *, context=None):
    await _scope(
        db,
        novel_id,
        context,
        [("outline_scene", args.scene_id), ("core_entity", args.entity_id)],
    )
    field = await get(WORLD_REQUIRE_CUSTOM_TEXT_STATE_FIELD)(
        db,
        novel_id,
        str(args.entity_id),
        args.field_key,
        args.expected_template_version_number,
    )
    return {
        "scene_id": str(args.scene_id),
        "entity_id": str(args.entity_id),
        "field_key": args.field_key,
        "value": args.value,
        "template_id": str(field["template_id"]),
        "template_version_number": field["template_version_number"],
    }


async def _custom_apply(db, novel_id, args, preview, *, context=None):
    if await _custom_preview(db, novel_id, args, context=context) != preview:
        raise ConflictError("文字状态或模板已变化，请重新确认")
    result = await confirm_custom_text_state(
        db,
        novel_id,
        scene_id=str(args.scene_id),
        entity_id=str(args.entity_id),
        field_key=args.field_key,
        value=args.value,
        expected_template_version_number=args.expected_template_version_number,
        idempotency_key=args.idempotency_key,
    )
    return {**result, "event": result["event"].model_dump(mode="json")}


async def _map_preview(db, novel_id, args, *, context=None):
    await _scope(
        db,
        novel_id,
        context,
        [("outline_scene", args.scene_id), ("map_node", args.node_id)],
    )
    binding = await get(WORLD_REQUIRE_MAP_DECLARATION_STATE)(
        db,
        novel_id,
        node_id=str(args.node_id),
        revision_id=str(args.revision_id),
        declaration_kind=args.declaration_kind,
        declaration_id=args.declaration_id,
    )
    return {
        "scene_id": str(args.scene_id),
        "node_id": str(args.node_id),
        "revision_id": str(args.revision_id),
        "declaration_kind": args.declaration_kind,
        "declaration_id": args.declaration_id,
        "status": args.status,
        "subject_id": binding["subject_id"],
    }


async def _map_apply(db, novel_id, args, preview, *, context=None):
    if await _map_preview(db, novel_id, args, context=context) != preview:
        raise ConflictError("地图声明或 Scene 已变化，请重新确认")
    result = await confirm_map_declaration_state(
        db,
        novel_id,
        scene_id=str(args.scene_id),
        node_id=str(args.node_id),
        revision_id=str(args.revision_id),
        declaration_kind=args.declaration_kind,
        declaration_id=args.declaration_id,
        status=args.status,
        idempotency_key=args.idempotency_key,
    )
    return {**result, "event": result["event"].model_dump(mode="json")}


OPERATIONS_SPEC = {
    "story.custom_text_state.confirm": {
        "label": "确认对象文字状态",
        "schema": CustomTextStateUpdateRequest,
        "prepare": _custom_preview,
        "apply": _custom_apply,
        "permission": "confirm",
        "revision": "1",
        "op_version": "1",
        "description": "确认一个当前 Scene 中属于已采用对象与模板字段的文字状态。",
        "risk_level": "R3",
        "fee_category": "free",
        "reversibility": "append_only_supersession",
        "preconditions": ("作者拥有作品", "模板版本、对象、Scene 与字段精确匹配"),
        "produces": ("author_confirmed_story_state",),
        "target_type": "story_state_field",
        "ai_available": True,
        "transaction_mode": "single_transaction",
        "trace_rule": {
            "parameter_fields": (
                "scene_id",
                "entity_id",
                "field_key",
                "value",
                "expected_template_version_number",
                "idempotency_key",
                "confirmed",
            ),
            "mode": "per_call",
            "parameter_policy": "schema_safe",
        },
    },
    "story.map_declaration_state.confirm": {
        "label": "确认地图声明在本场的状态",
        "schema": MapDeclarationStateUpdateRequest,
        "prepare": _map_preview,
        "apply": _map_apply,
        "permission": "confirm",
        "revision": "1",
        "op_version": "1",
        "description": "以当前已采用地图的精确声明身份记录作者确认的 Story 状态。",
        "risk_level": "R3",
        "fee_category": "free",
        "reversibility": "append_only_supersession",
        "preconditions": ("作者拥有作品", "地图当前保存修订、声明、Scene 均有效"),
        "produces": ("author_confirmed_map_story_state",),
        "target_type": "map_declaration",
        "ai_available": True,
        "transaction_mode": "single_transaction",
        "trace_rule": {
            "parameter_fields": (
                "scene_id",
                "node_id",
                "revision_id",
                "declaration_kind",
                "declaration_id",
                "status",
                "idempotency_key",
                "confirmed",
            ),
            "mode": "per_call",
            "parameter_policy": "schema_safe",
        },
    },
}
