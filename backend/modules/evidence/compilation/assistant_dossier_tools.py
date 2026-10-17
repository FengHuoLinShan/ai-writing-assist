"""Read-only Assistant operation for the public Evidence object brief."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.container import get
from core.errors import ConflictError, NotFoundError
from core.service_keys import ASSISTANT_REQUIRE_OPERATION_TARGETS
from modules.evidence.compilation.facade import read_object_dossier_brief
from modules.evidence.compilation.object_dossier_schemas import ObjectDossierBriefResponse
from modules.evidence.contracts import VisibilityContextContract
from modules.evidence.facade import inspect_novel_target


class ReadAssistantObjectDossierBrief(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scene_id: UUID
    entity_ids: list[UUID] = Field(min_length=1, max_length=16)
    reveal_mode: Literal["author_safe", "character"] = "author_safe"
    viewpoint_character_id: UUID | None = None
    include_patterns: bool = False
    only_adopted_patterns: bool = False

    @model_validator(mode="after")
    def check_viewpoint(self):
        if (self.reveal_mode == "character") != bool(self.viewpoint_character_id):
            raise ValueError("character view needs one viewpoint character")
        if (
            self.viewpoint_character_id
            and self.viewpoint_character_id not in self.entity_ids
        ):
            raise ValueError("viewpoint character must be in selected entity_ids")
        if self.only_adopted_patterns and not self.include_patterns:
            raise ValueError("only_adopted_patterns requires include_patterns")
        if len(set(self.entity_ids)) != len(self.entity_ids):
            raise ValueError("entity_ids must be unique")
        return self


async def _read_object_dossier_brief(db, novel_id, args, *, context=None):
    if context is None or not getattr(context, "owner_id", None):
        raise NotFoundError("对象参考需要当前作者范围")
    work = getattr(context, "work", None)
    if work is None:
        raise ConflictError("对象参考缺少当前工作范围")
    if getattr(work, "context_confirmation_id", None) or getattr(
        work, "excluded_targets", None
    ):
        raise ConflictError("原资料确认或排除范围不能展开为新的对象简报")
    if getattr(work, "scene_id", None) and str(work.scene_id) != str(args.scene_id):
        raise ConflictError("对象参考不能跨出当前 Scene")
    if getattr(work, "scope", None) == "current" and not getattr(work, "scene_id", None):
        raise ConflictError("当前工作范围没有可核实的 Scene")
    await get(ASSISTANT_REQUIRE_OPERATION_TARGETS)(
        db,
        str(novel_id),
        context,
        [("outline_scene", args.scene_id)]
        + [("core_entity", identifier) for identifier in args.entity_ids],
        aggregate=True,
    )
    for target_type, target_id in [
        ("outline_scene", args.scene_id),
        *(("core_entity", entity_id) for entity_id in args.entity_ids),
    ]:
        inspection = await inspect_novel_target(
            db,
            novel_id=str(novel_id),
            target_ref={"target_type": target_type, "target_id": str(target_id)},
            content_mode="canonical",
            visibility=VisibilityContextContract(mode="author"),
        )
        if not inspection.get("visible"):
            raise NotFoundError("对象或 Scene 不属于当前作品")
    result = await read_object_dossier_brief(
        db,
        novel_id=novel_id,
        scene_id=str(args.scene_id),
        entity_ids=[str(item) for item in args.entity_ids],
        reveal_mode=args.reveal_mode,
        viewpoint_character_id=(
            str(args.viewpoint_character_id) if args.viewpoint_character_id else None
        ),
        content_mode="canonical",
        include_patterns=args.include_patterns,
        only_adopted_patterns=args.only_adopted_patterns,
    )
    return ObjectDossierBriefResponse.model_validate(result).model_dump(mode="json")


OPERATIONS_SPEC = {
    "evidence.object_dossier_brief.read": {
        "label": "读取 Scene 对象档案简报",
        "schema": ReadAssistantObjectDossierBrief,
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
            "parameter_fields": (
                "scene_id",
                "entity_ids",
                "reveal_mode",
                "viewpoint_character_id",
                "include_patterns",
                "only_adopted_patterns",
            ),
            "mode": "per_call",
            "parameter_policy": "schema_safe",
        },
        "permission": "read",
    }
}


__all__ = ["OPERATIONS_SPEC"]
