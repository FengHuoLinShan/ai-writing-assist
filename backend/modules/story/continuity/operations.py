"""Pure Assistant directory entry for the factual Story event timeline."""

from __future__ import annotations

from modules.story.continuity.facade import list_fact_timeline
from modules.story.continuity.schemas import StoryFactTimelineQuery


async def _read_fact_timeline(db, novel_id, args, *, context=None):
    del context
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
