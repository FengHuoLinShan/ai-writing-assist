"""Read-only forecast feed adapter for the unified author notice list."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid5

from sqlalchemy import select

from core.errors import ConflictError
from infrastructure.stable_hash import stable_hash
from modules.assistant.forecast.contracts import FeedRequest, FocusRequest
from modules.assistant.forecast.models import ForecastCandidate
from modules.assistant.forecast.service import (
    feed,
    legacy_decide_notice,
    require_current_notice,
)
from modules.writing.facade import get_latest_draft_for_chapter

SOURCE_ID = "assistant.forecast"


async def list_forecast_notices(
    db, novel_id: str, scope: dict[str, object]
) -> list[dict[str, Any]]:
    scene_id = UUID(str(scope["scene_id"])) if scope.get("scene_id") else None
    chapter_index = int(scope["chapter_index"]) if scope.get("chapter_index") else None
    draft = None
    if chapter_index is not None:
        draft = await get_latest_draft_for_chapter(db, novel_id, chapter_index)
    focus = FocusRequest(
        client_context_id=uuid5(
            UUID(str(novel_id)),
            f"unified-notices:{scene_id}:{chapter_index}:{draft.id if draft else ''}",
        ),
        focus_seq=0,
        page="writing",
        task_hint="review",
        scene_id=scene_id,
        draft_id=UUID(draft.id) if draft else None,
        expected_source_hash=draft.content_hash if draft else None,
        editor_state="saved" if draft else "not_applicable",
    )
    response = await feed(
        db,
        novel_id,
        FeedRequest(context=focus, max_items=10, include_deferred=False),
    )
    items = []
    for candidate in response.items:
        raw = candidate.model_dump(mode="json")
        basis = stable_hash(
            {
                "candidate_id": str(candidate.candidate_id),
                "assessment_hash": candidate.assessment_hash,
                "context_hash": candidate.context_hash,
                "expires_at": candidate.expires_at.isoformat(),
                "notice_version": candidate.notice_version,
            }
        )
        items.append(
            {
                "notice_key": f"{SOURCE_ID}:{candidate.candidate_id}",
                "source_id": SOURCE_ID,
                "category": "short_term_forecast",
                "severity": {
                    "attention": "high",
                    "next": "medium",
                    "watch": "low",
                }[candidate.tier],
                "target": candidate.navigation
                or {
                    key: str(value)
                    for key, value in (
                        ("scene_id", scene_id),
                        ("chapter_index", chapter_index),
                    )
                    if value is not None
                },
                "summary": f"{candidate.title}：{candidate.why_now}",
                "evidence": [item.model_dump(mode="json") for item in candidate.evidence],
                "basis_fingerprint": basis,
                "stale": candidate.freshness != "valid",
                "status": {
                    "unread": "unread",
                    "read": "read",
                    # Feed excludes deferred cards. A snoozed card returned by
                    # feed has already met its wake condition.
                    "snoozed": "unread",
                    "dismissed": "ignored",
                }.get(candidate.notice_status, "unread"),
                "row_version": int(candidate.notice_version),
                "actions": [item.model_dump(mode="json") for item in candidate.actions],
                "disposition_ref": {
                    "candidate_id": str(candidate.candidate_id),
                    "assessment_hash": candidate.assessment_hash,
                    "notice_version": candidate.notice_version,
                },
                "domain_item": raw,
            }
        )
    if response.next_cursor is not None:
        # The forecast feed is intentionally capped at ten cards. Keep those
        # cards visible and disclose the remainder instead of degrading the
        # entire source as unavailable.
        items.append(
            {
                "notice_key": f"{SOURCE_ID}:more:{scene_id}:{chapter_index}",
                "source_id": SOURCE_ID,
                "category": "short_term_forecast",
                "severity": "info",
                "target": {
                    key: str(value)
                    for key, value in (
                        ("scene_id", scene_id),
                        ("chapter_index", chapter_index),
                    )
                    if value is not None
                },
                "summary": "还有更多下一步建议，请到前瞻列表查看",
                "evidence": [],
                "basis_fingerprint": stable_hash(
                    {
                        "context_hash": response.context_hash,
                        "next_cursor": response.next_cursor,
                    }
                ),
                "stale": False,
                "actions": [
                    {"kind": "navigate", "page": "writing", "label": "查看全部建议"}
                ],
            }
        )
    return items


async def decide_forecast_notice(
    db,
    novel_id: str,
    item: dict[str, Any],
    action: str,
    wake_at: datetime | None,
) -> dict[str, Any]:
    from modules.assistant.schemas import NoticeDecision

    reference = item.get("disposition_ref") or {}
    candidate = await db.scalar(
        select(ForecastCandidate).where(
            ForecastCandidate.novel_id == UUID(str(novel_id)),
            ForecastCandidate.id == UUID(str(reference.get("candidate_id"))),
        )
    )
    if candidate is None or candidate.assessment_hash != reference.get("assessment_hash"):
        raise ConflictError("前瞻建议已变化，请重新读取", code="NOTICE_STALE")
    notice = await require_current_notice(db, candidate)
    if notice is None or notice.row_version != reference.get("notice_version"):
        raise ConflictError("前瞻建议已变化，请重新读取", code="NOTICE_STALE")
    return await legacy_decide_notice(
        db,
        novel_id,
        notice,
        NoticeDecision(
            novel_id=UUID(str(novel_id)),
            action=action,
            until=wake_at if action == "snooze" else None,
        ),
    )


NOTICE_SOURCE_SPEC = {
    "source_id": SOURCE_ID,
    "label": "下一步建议",
    "list_notices": list_forecast_notices,
    "decide": decide_forecast_notice,
    "timeout_seconds": 2.5,
}
