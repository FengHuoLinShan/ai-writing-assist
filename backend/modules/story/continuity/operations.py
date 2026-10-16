"""Pure Assistant directory entry for the factual Story event timeline."""

from __future__ import annotations

from core.container import get
from core.errors import ConflictError
from core.service_keys import ASSISTANT_REQUIRE_OPERATION_TARGETS
from modules.story.continuity.facade import list_fact_timeline
from modules.story.continuity.schemas import StoryFactTimelineQuery


async def _read_fact_timeline(db, novel_id, args, *, context=None):
    if context is not None:
        work = context.work
        if work.scope == "current":
            if work.scene_id is None:
                raise ConflictError(
                    "事实时间线需要当前 Scene 截止点，请在场景或工作台查看"
                )
            if args.cutoff_scene_id not in (None, work.scene_id):
                raise ConflictError("事实时间线截止点超出当前 Scene")
            args = args.model_copy(update={"cutoff_scene_id": work.scene_id})
            targets = [("outline_scene", work.scene_id)]
            if args.entity_id is not None:
                targets.append(("core_entity", args.entity_id))
            await get(ASSISTANT_REQUIRE_OPERATION_TARGETS)(
                db, novel_id, context, targets, aggregate=True
            )
        else:
            await get(ASSISTANT_REQUIRE_OPERATION_TARGETS)(
                db, novel_id, context, [], aggregate=True
            )
    result = await list_fact_timeline(db, novel_id, args)
    return result.model_dump(mode="json")


OPERATIONS_SPEC = {
    "story.fact_timeline.read": {
        "label": "读取已发生事实时间线",
        "schema": StoryFactTimelineQuery,
        "prepare": _read_fact_timeline,
        "apply": None,
        "permission": "read",
        "op_version": "1",
        "description": (
            "按 Scene 时间、截止 Scene、对象、来源、状态和分页读取作者可见的"
            "MemoryEvent 事实；不读取伏笔或揭示计划作为已发生事实。"
        ),
        "risk_level": "R0",
        "fee_category": "free",
        "reversibility": "not_applicable",
        "preconditions": ("novel_id 必须属于当前作者项目",),
        "produces": ("story_fact_timeline",),
        "target_type": "story_fact_timeline",
        "ai_available": True,
        "transaction_mode": "single_transaction",
        "trace_rule": {
            "parameter_fields": (
                "entity_id",
                "cutoff_scene_id",
                "source",
                "status",
                "skip",
                "limit",
            ),
            "mode": "per_call",
            "parameter_policy": "schema_safe",
        },
    }
}
