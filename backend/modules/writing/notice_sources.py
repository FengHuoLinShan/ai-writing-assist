"""Writing-owned notice sources and their existing disposition adapters."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select

from core.errors import ConflictError
from infrastructure.stable_hash import stable_hash
from modules.writing.conflict_check_service import WritingConflictCheckService
from modules.writing.facade import get_latest_draft_for_chapter
from modules.writing.models import (
    WritingConflictCheck,
    WritingConflictItem,
)
from modules.writing.recompute import WritingRecomputeService
from modules.writing.schemas import WritingConflictItemUpdate

CONFLICT_SOURCE_ID = "writing.conflict"
INVALIDATION_SOURCE_ID = "writing.invalidation"


def _fingerprint_conflict(
    check: WritingConflictCheck,
    item: WritingConflictItem | None,
    *,
    stale: bool,
    current_draft: Any,
    map_staleness: dict[str, Any] | None,
) -> str:
    return stable_hash(
        {
            "check_id": str(check.id),
            "check_updated_at": check.updated_at.isoformat()
            if check.updated_at
            else None,
            "check_status": check.status,
            "check_scope": check.scope or {},
            "check_summary": check.summary_json or {},
            "item_id": str(item.id) if item else None,
            "item_status": item.status if item else None,
            "item_updated_at": item.updated_at.isoformat()
            if item and item.updated_at
            else None,
            "item_severity": item.severity if item else None,
            "item_summary": item.evidence_summary if item else None,
            "stale": stale,
            "current_draft_id": str(current_draft.id) if current_draft else None,
            "current_draft_hash": current_draft.content_hash if current_draft else None,
            "map_staleness": map_staleness,
        }
    )


async def _current_check(
    db, novel_id: str, scope: dict[str, object]
) -> tuple[WritingConflictCheck | None, dict[str, Any] | None, Any]:
    chapter_index = int(scope["chapter_index"]) if scope.get("chapter_index") else None
    scene_id = UUID(str(scope["scene_id"])) if scope.get("scene_id") else None
    if chapter_index is None and scene_id is None:
        return None, None, None
    conditions = [WritingConflictCheck.novel_id == UUID(str(novel_id))]
    if chapter_index is not None:
        conditions.append(WritingConflictCheck.chapter_index == chapter_index)
    if scene_id:
        conditions.append(WritingConflictCheck.scene_id == scene_id)
    check = await db.scalar(
        select(WritingConflictCheck)
        .where(*conditions)
        .order_by(WritingConflictCheck.created_at.desc(), WritingConflictCheck.id.desc())
        .limit(1)
    )
    if check is None:
        return None, None, None
    current_draft = await get_latest_draft_for_chapter(db, novel_id, check.chapter_index)
    current = await WritingConflictCheckService().get_check(
        db, novel_id=novel_id, check_id=str(check.id)
    )
    return check, current.model_dump(mode="json"), current_draft


async def list_conflict_notices(
    db, novel_id: str, scope: dict[str, object]
) -> list[dict[str, Any]]:
    chapter_index = int(scope["chapter_index"]) if scope.get("chapter_index") else None
    scene_id = str(scope.get("scene_id") or "")
    check, current, latest_draft = await _current_check(db, novel_id, scope)
    if chapter_index is None and not scene_id:
        return []
    if check is None or current is None:
        identity = scene_id or f"chapter:{chapter_index}"
        return [
            {
                "notice_key": f"{CONFLICT_SOURCE_ID}:missing:{identity}",
                "source_id": CONFLICT_SOURCE_ID,
                "category": "conflict_check",
                "severity": "info",
                "target": {"scene_id": scene_id or None, "chapter_index": chapter_index},
                "summary": "当前场景尚无规则检查记录",
                "evidence": [],
                "basis_fingerprint": stable_hash(
                    {"novel_id": novel_id, "identity": identity, "check": None}
                ),
                "stale": False,
                "actions": [
                    {
                        "kind": "navigate",
                        "page": "writing",
                        "scene_id": scene_id or None,
                        "chapter_index": chapter_index,
                        "label": "运行规则检查",
                    }
                ],
                "disposition_ref": None,
            }
        ]

    check_items = await db.scalars(
        select(WritingConflictItem)
        .where(
            WritingConflictItem.novel_id == UUID(str(novel_id)),
            WritingConflictItem.check_id == check.id,
        )
        .order_by(WritingConflictItem.created_at, WritingConflictItem.id)
    )
    items = list(check_items.all())
    stale = bool(
        latest_draft is not None
        and (
            check.draft_id != UUID(str(latest_draft.id))
            or check.version_number != latest_draft.version_number
            or (check.scope or {}).get("content_hash") != latest_draft.content_hash
        )
    ) or (latest_draft is None and check.draft_id is not None)
    map_staleness = current.get("map_staleness")
    notices: list[dict[str, Any]] = []
    check_target = {
        "scene_id": str(check.scene_id) if check.scene_id else None,
        "chapter_index": check.chapter_index,
    }

    if stale:
        notices.append(
            {
                "notice_key": f"{CONFLICT_SOURCE_ID}:stale:{check.id}",
                "source_id": CONFLICT_SOURCE_ID,
                "category": "conflict_check",
                "severity": "medium",
                "target": check_target,
                "summary": "正文保存版本已更新，最近一次规则检查已过期",
                "evidence": [],
                "basis_fingerprint": _fingerprint_conflict(
                    check,
                    None,
                    stale=True,
                    current_draft=latest_draft,
                    map_staleness=map_staleness,
                ),
                "stale": True,
                "actions": [
                    {
                        "kind": "navigate",
                        "page": "writing",
                        "scene_id": check_target["scene_id"],
                        "label": "重新运行检查",
                    }
                ],
                "disposition_ref": None,
            }
        )
    if isinstance(map_staleness, dict) and map_staleness.get("changed") is True:
        notices.append(
            {
                "notice_key": f"{CONFLICT_SOURCE_ID}:map-stale:{check.id}",
                "source_id": CONFLICT_SOURCE_ID,
                "category": "map_baseline",
                "severity": "medium",
                "target": check_target,
                "summary": "检查结果基于旧版地图，建议重新检查",
                "evidence": list(map_staleness.get("nodes") or [])[:20],
                "basis_fingerprint": _fingerprint_conflict(
                    check,
                    None,
                    stale=stale,
                    current_draft=latest_draft,
                    map_staleness=map_staleness,
                ),
                "stale": True,
                "actions": [
                    {
                        "kind": "navigate",
                        "page": "writing",
                        "scene_id": check_target["scene_id"],
                        "label": "重新运行检查",
                    }
                ],
                "disposition_ref": None,
            }
        )

    open_items = [item for item in items if item.status == "open"]
    for item in open_items:
        notices.append(
            {
                "notice_key": f"{CONFLICT_SOURCE_ID}:item:{item.id}",
                "source_id": CONFLICT_SOURCE_ID,
                "category": "conflict_check",
                "severity": item.severity
                if item.severity in {"high", "medium", "low", "info"}
                else "low",
                "target": {**check_target, "item_id": str(item.id)},
                "summary": item.evidence_summary,
                "evidence": [
                    {
                        "kind": item.kind,
                        "source_module": item.source_module,
                        "source_type": item.source_type,
                        "source_id": item.source_id,
                        "location": item.location_json,
                        "is_ai_judgment": item.is_ai_judgment,
                        "needs_review": item.needs_review,
                    }
                ],
                "basis_fingerprint": _fingerprint_conflict(
                    check,
                    item,
                    stale=stale,
                    current_draft=latest_draft,
                    map_staleness=map_staleness,
                ),
                "stale": stale,
                "actions": [
                    {
                        "kind": "navigate",
                        "page": "writing",
                        "scene_id": check_target["scene_id"],
                        "check_id": str(check.id),
                        "item_id": str(item.id),
                        "label": "查看检查详情",
                    },
                    {
                        "op_id": "assistant.notice.set_disposition",
                        "label": "处理提醒",
                    },
                ],
                "disposition_ref": {
                    "kind": "writing_conflict_item",
                    "item_id": str(item.id),
                    "check_id": str(check.id),
                    "updated_at": item.updated_at.isoformat()
                    if item.updated_at
                    else None,
                },
            }
        )

    ai_status = str(current.get("ai_review_status") or "not_requested")
    ai_notice = {
        "failed": ("medium", "AI 深度校验失败，可在检查详情中重试"),
        "running": ("info", "AI 深度校验仍在运行"),
        "partial": ("low", "AI 深度校验仅完成部分结果"),
    }.get(ai_status)
    if ai_notice:
        severity, summary = ai_notice
        notices.append(
            {
                "notice_key": f"{CONFLICT_SOURCE_ID}:ai:{check.id}:{ai_status}",
                "source_id": CONFLICT_SOURCE_ID,
                "category": "conflict_check",
                "severity": severity,
                "target": check_target,
                "summary": summary,
                "evidence": [],
                "basis_fingerprint": stable_hash(
                    {
                        "check": str(check.id),
                        "ai_status": ai_status,
                        "updated_at": check.updated_at.isoformat()
                        if check.updated_at
                        else None,
                    }
                ),
                "stale": False,
                "actions": [
                    {
                        "kind": "navigate",
                        "page": "writing",
                        "scene_id": check_target["scene_id"],
                        "check_id": str(check.id),
                        "label": "查看检查详情",
                    }
                ],
                "disposition_ref": None,
            }
        )
    if current.get("status") == "degraded":
        notices.append(
            {
                "notice_key": f"{CONFLICT_SOURCE_ID}:degraded:{check.id}",
                "source_id": CONFLICT_SOURCE_ID,
                "category": "conflict_check",
                "severity": "low",
                "target": check_target,
                "summary": "最近一次规则检查有部分资料未能核对",
                "evidence": [],
                "basis_fingerprint": stable_hash(
                    {
                        "check": str(check.id),
                        "status": "degraded",
                        "summary": check.summary_json or {},
                    }
                ),
                "stale": False,
                "actions": [
                    {
                        "kind": "navigate",
                        "page": "writing",
                        "scene_id": check_target["scene_id"],
                        "check_id": str(check.id),
                        "label": "查看检查详情",
                    }
                ],
                "disposition_ref": None,
            }
        )
    if (
        not open_items
        and not stale
        and not (isinstance(map_staleness, dict) and map_staleness.get("changed"))
    ):
        notices.append(
            {
                "notice_key": f"{CONFLICT_SOURCE_ID}:clear:{check.id}",
                "source_id": CONFLICT_SOURCE_ID,
                "category": "conflict_check",
                "severity": "info",
                "target": check_target,
                "summary": "最近一次规则检查没有未处理项",
                "evidence": [],
                "basis_fingerprint": _fingerprint_conflict(
                    check,
                    None,
                    stale=False,
                    current_draft=latest_draft,
                    map_staleness=map_staleness,
                ),
                "stale": False,
                "actions": [
                    {
                        "kind": "navigate",
                        "page": "writing",
                        "scene_id": check_target["scene_id"],
                        "check_id": str(check.id),
                        "label": "查看检查详情",
                    }
                ],
                "disposition_ref": None,
            }
        )
    return notices


async def decide_conflict_notice(
    db,
    novel_id: str,
    notice: dict[str, Any],
    action: str,
    _wake_at: datetime | None,
) -> dict[str, Any] | None:
    if action not in {"snooze", "ignore"}:
        return None
    reference = notice.get("disposition_ref") or {}
    if reference.get("kind") != "writing_conflict_item":
        return None
    row = await db.scalar(
        select(WritingConflictItem)
        .where(
            WritingConflictItem.novel_id == UUID(str(novel_id)),
            WritingConflictItem.id == UUID(str(reference.get("item_id"))),
        )
        .with_for_update()
    )
    if (
        row is None
        or row.status != "open"
        or (row.updated_at.isoformat() if row.updated_at else None)
        != reference.get("updated_at")
    ):
        raise ConflictError("检查项已变化，请重新读取", code="NOTICE_STALE")
    status = "later" if action == "snooze" else "ignored"
    updated = await WritingConflictCheckService().update_item(
        db,
        novel_id=novel_id,
        item_id=str(row.id),
        data=WritingConflictItemUpdate(status=status),
    )
    return updated.model_dump(mode="json")


async def list_invalidation_notices(
    db, novel_id: str, scope: dict[str, object]
) -> list[dict[str, Any]]:
    chapter_index = int(scope["chapter_index"]) if scope.get("chapter_index") else None
    if chapter_index is None:
        return []
    service = WritingRecomputeService()
    pending = await service.list_pending_notices(
        db, novel_id, chapter_index=chapter_index, limit=101
    )
    if len(pending) > 100:
        raise RuntimeError("待重算提醒超过单次读取上限")
    notices = []
    for value in pending:
        receipt_id = str(value.get("receipt_id") or "")
        if not receipt_id:
            continue
        basis = stable_hash(value)
        notices.append(
            {
                "notice_key": f"{INVALIDATION_SOURCE_ID}:{receipt_id}",
                "source_id": INVALIDATION_SOURCE_ID,
                "category": "source_invalidation",
                "severity": "medium",
                "target": {"chapter_index": chapter_index},
                "summary": str(
                    value.get("summary")
                    or value.get("title")
                    or "正文变化后，有资料需要重新计算"
                ),
                "evidence": [
                    item
                    for item in (value.get("affected") or [])
                    if isinstance(item, dict)
                ][:20],
                "basis_fingerprint": basis,
                "stale": False,
                "actions": [
                    {
                        "kind": "navigate",
                        "page": "writing",
                        "chapter_index": chapter_index,
                        "label": "查看重算选项",
                    }
                ],
                "disposition_ref": None,
            }
        )
    return notices


NOTICE_SOURCE_SPECS = [
    {
        "source_id": CONFLICT_SOURCE_ID,
        "label": "规则检查",
        "list_notices": list_conflict_notices,
        "decide": decide_conflict_notice,
    },
    {
        "source_id": INVALIDATION_SOURCE_ID,
        "label": "来源与重算",
        "list_notices": list_invalidation_notices,
    },
]
