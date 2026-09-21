"""Evaluate declared author wake conditions without starting analysis."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select

from core.errors import ConflictError
from modules.assistant.models import AssistantNotice
from modules.evidence.facade import get_entity_activity_stats
from modules.story.facade import get_scene_contract
from modules.writing.facade import get_draft


async def freeze_condition(db, novel_id, condition):
    if not condition or condition["kind"] in {"at_time", "manual_reopen"}:
        return condition
    value = dict(condition)
    if value["kind"] == "object_reappears":
        activity = await get_entity_activity_stats(db, novel_id)
        item = next(
            (item for item in activity.items if item.entity_id == value["object_id"]),
            None,
        )
        if not item or item.last_chapter_index is None:
            raise ConflictError(
                "尚无已同步的出场记录，请选择手动重开", code="WAKE_SCOPE_UNAVAILABLE"
            )
        value["baseline_chapter"] = item.last_chapter_index
    elif value["kind"] == "scene_activated":
        if await get_scene_contract(db, novel_id, value["target_id"]) is None:
            raise ConflictError("提醒场景已不可访问", code="WAKE_SCOPE_UNAVAILABLE")
    else:
        draft = await get_draft(db, novel_id, value["target_id"])
        if draft is None or draft.status in {"canonical", "published", "deprecated"}:
            raise ConflictError("请选择尚未完成的当前章稿", code="WAKE_SCOPE_UNAVAILABLE")
        value["baseline_status"] = draft.status
    return value


async def evaluate_conditions(db, novel_id, focus=None):
    rows = (
        await db.scalars(
            select(AssistantNotice)
            .where(
                AssistantNotice.novel_id == UUID(novel_id),
                AssistantNotice.status == "snoozed",
                AssistantNotice.result_ref_json["type"].as_string() == "forecast",
            )
            .with_for_update()
        )
    ).all()
    activity = None
    woken = 0
    for row in rows:
        decision = (row.result_ref_json or {}).get("forecast_v1", {})
        condition = decision.get("wake_condition") or {}
        kind, status = condition.get("kind"), "waiting"
        if kind == "scene_activated":
            scene = await get_scene_contract(db, novel_id, condition["target_id"])
            if scene is None or scene.status in {"archived", "deprecated"}:
                status = "unavailable"
            elif focus and str(focus.scene_id) == condition["target_id"]:
                status = "satisfied"
        elif kind == "chapter_completed":
            draft = await get_draft(db, novel_id, condition["target_id"])
            if draft is None or draft.status == "deprecated":
                status = "unavailable"
            elif condition.get("baseline_status") and draft.status in {
                "canonical",
                "published",
            }:
                status = "satisfied"
        elif kind == "object_reappears":
            if activity is None:
                activity = await get_entity_activity_stats(db, novel_id)
            item = next(
                (
                    item
                    for item in activity.items
                    if item.entity_id == condition["object_id"]
                ),
                None,
            )
            if not item or condition.get("baseline_chapter") is None:
                status = "unavailable"
            elif (
                item.last_chapter_index
                and item.last_chapter_index > condition["baseline_chapter"]
            ):
                # Changes to the same chapter or entity metadata cannot wake this.
                status = "satisfied"
        elif kind == "at_time":
            if datetime.fromisoformat(condition["at"]) <= datetime.now(UTC):
                status = "satisfied"
        if status == "satisfied":
            row.status, row.wake_at = "unread", None
            row.row_version += 1
            woken += 1
        if decision.get("wake_status") != status:
            row.result_ref_json = {
                **row.result_ref_json,
                "forecast_v1": {
                    **decision,
                    "wake_status": status,
                    "wake_explanation": "条件来源不可判定，请手动重开或重新选择。"
                    if status == "unavailable"
                    else None,
                },
            }
    await db.flush()
    return {"woken": woken}
