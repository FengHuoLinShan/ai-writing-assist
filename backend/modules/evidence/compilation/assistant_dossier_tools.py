"""Read-only Assistant operation for the public Evidence object brief."""

from __future__ import annotations

from modules.evidence.compilation.facade import read_object_dossier_brief
from modules.evidence.compilation.object_dossier_schemas import (
    ObjectDossierBriefRequest,
    ObjectDossierBriefResponse,
)


async def _read_object_dossier_brief(db, novel_id, args, *, context=None):
    if str(args.novel_id) != str(novel_id):
        raise ValueError("novel_id must match the active Assistant project")
    result = await read_object_dossier_brief(
        db,
        novel_id=novel_id,
        scene_id=str(args.scene_id),
        entity_ids=[str(item) for item in args.entity_ids],
        reveal_mode=args.reveal_mode,
        viewpoint_character_id=(
            str(args.viewpoint_character_id) if args.viewpoint_character_id else None
        ),
        content_mode=args.content_mode,
        include_patterns=args.include_patterns,
        only_adopted_patterns=args.only_adopted_patterns,
    )
    return ObjectDossierBriefResponse.model_validate(result).model_dump(mode="json")


OPERATIONS_SPEC = {
    "evidence.object_dossier_brief.read": {
        "label": "读取 Scene 对象档案简报",
        "schema": ObjectDossierBriefRequest,
        "prepare": _read_object_dossier_brief,
        "op_version": "1",
        "description": (
            "读取严格绑定 Scene 截止点的 World 档案、Story 可见状态与可选 Evolution "
            "解释；受作者项目和 POV 可见性过滤，不触发模型或写入。"
        ),
        "risk_level": "R0",
        "fee_category": "free",
        "reversibility": "read_only",
        "preconditions": (
            "active_author_project",
            "scene_in_project",
            "entity_ids_in_scope",
        ),
        "produces": ("scene_bounded_object_dossier_projection",),
        "target_type": "evidence_object_dossier_brief",
        "ai_available": True,
        "transaction_mode": "single_transaction",
        "trace_rule": {
            "parameter_fields": tuple(ObjectDossierBriefRequest.model_fields),
            "mode": "per_call",
            "parameter_policy": "schema_safe",
        },
        "permission": "read",
    }
}


__all__ = ["OPERATIONS_SPEC"]
