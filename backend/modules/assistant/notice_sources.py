"""Assistant-owned read bridge for existing proactive notice decisions."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select

from core.errors import ConflictError
from infrastructure.stable_hash import stable_hash
from modules.assistant.models import AssistantNotice
from modules.assistant.proactive import list_notices

SOURCE_ID = "assistant.proactive"


def _matches_scope(item: dict[str, Any], scope: dict[str, object]) -> bool:
    source = item.get("source") if isinstance(item.get("source"), dict) else {}
    target = source.get("target") if isinstance(source.get("target"), dict) else {}
    location = source.get("location") if isinstance(source.get("location"), dict) else {}
    chapter_index = scope.get("chapter_index")
    scene_id = str(scope.get("scene_id") or "")
    item_chapter = target.get("chapter_index") or location.get("chapter_index")
    item_scene = str(target.get("scene_id") or location.get("scene_id") or "")
    if chapter_index is not None and item_chapter is not None:
        try:
            if int(item_chapter) != int(chapter_index):
                return False
        except (TypeError, ValueError):
            return False
    if scene_id and item_scene and item_scene != scene_id:
        return False
    return True


async def list_assistant_notices(
    db, novel_id: str, scope: dict[str, object]
) -> list[dict[str, Any]]:
    result = await list_notices(db, novel_id)
    public_items = result.get("items") or []
    ids = [
        UUID(str(item["id"]))
        for item in public_items
        if item.get("id") and _matches_scope(item, scope)
    ]
    if not ids:
        return []
    rows = (
        await db.scalars(
            select(AssistantNotice).where(
                AssistantNotice.novel_id == UUID(str(novel_id)),
                AssistantNotice.id.in_(ids),
            )
        )
    ).all()
    by_id = {str(row.id): row for row in rows}
    notices = []
    for item in public_items:
        row = by_id.get(str(item.get("id")))
        if row is None or not _matches_scope(item, scope):
            continue
        reference = row.result_ref_json or {}
        category = str(reference.get("type") or row.kind)
        basis = stable_hash(
            {
                "notice_id": str(row.id),
                "title": item.get("title"),
                "summary": item.get("summary"),
                "sources": item.get("sources") or [],
                "source": item.get("source") or {},
                "needs_recheck": bool(item.get("needs_recheck")),
                "domain_status": row.status,
                "domain_version": row.row_version,
            }
        )
        notices.append(
            {
                "notice_key": f"{SOURCE_ID}:{row.id}",
                "source_id": SOURCE_ID,
                "category": category,
                "severity": "medium" if row.kind == "reminder" else "low",
                "target": {
                    key: value
                    for key, value in (
                        ("scene_id", scope.get("scene_id")),
                        ("chapter_index", scope.get("chapter_index")),
                    )
                    if value is not None
                },
                "summary": str(
                    item.get("summary") or item.get("title") or "有一项提醒待查看"
                ),
                "evidence": [
                    value
                    for value in (item.get("sources") or [])
                    if isinstance(value, dict)
                ][:20],
                "basis_fingerprint": basis,
                "stale": bool(item.get("needs_recheck")),
                "status": {
                    "unread": "unread",
                    "read": "read",
                    "snoozed": "snoozed",
                    "dismissed": "ignored",
                }.get(str(row.status), "unread"),
                "row_version": int(row.row_version),
                "wake_at": row.wake_at,
                "actions": [
                    {
                        "op_id": "assistant.notice.set_disposition",
                        "label": "处理提醒",
                        "notice_key": f"{SOURCE_ID}:{row.id}",
                    }
                ],
                "disposition_ref": {
                    "notice_id": str(row.id),
                    "row_version": int(row.row_version),
                },
            }
        )
    return notices


async def decide_assistant_notice(
    db,
    novel_id: str,
    item: dict[str, Any],
    action: str,
    wake_at: datetime | None,
) -> dict[str, Any]:
    from modules.assistant.proactive import decide_notice
    from modules.assistant.schemas import NoticeDecision

    reference = item.get("disposition_ref") or {}
    notice_id = str(reference.get("notice_id") or "")
    row = await db.scalar(
        select(AssistantNotice)
        .where(
            AssistantNotice.novel_id == UUID(str(novel_id)),
            AssistantNotice.id == UUID(notice_id),
        )
        .with_for_update()
    )
    if row is None or row.row_version != reference.get("row_version"):
        raise ConflictError("提醒已变化，请重新读取", code="NOTICE_STALE")
    return await decide_notice(
        db,
        notice_id,
        NoticeDecision(
            novel_id=UUID(str(novel_id)),
            action=action,
            until=wake_at if action == "snooze" else None,
        ),
    )


NOTICE_SOURCE_SPEC = {
    "source_id": SOURCE_ID,
    "label": "助手提醒",
    "list_notices": list_assistant_notices,
    "decide": decide_assistant_notice,
}
