"""Read-only notices for map-head sources that no longer match saved prose."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select

from core.container import get
from core.service_keys import WORLD_READ_MAP_CHAPTER_CONSUMERS
from infrastructure.stable_hash import stable_hash
from modules.evolution.models import EvolutionReceiptRecord
from modules.writing.facade import get_manuscript_source_manifest

SOURCE_ID = "world.map_source"
MAP_RECEIPT_LIMIT = 500


def _receipt_indexes_current_head(
    receipts: list[Any], chapter_index: int
) -> dict[tuple[str, str], str]:
    """Return receipts only when they name the exact map head read today."""
    found: dict[tuple[str, str], str] = {}
    for receipt in receipts:
        consumers = (receipt.receipt_json or {}).get("invalidated_consumers", {})
        maps = consumers.get("map_atlas") or {}
        for field in ("maps", "auto_drafts"):
            for value in maps.get(field, []) or []:
                if not isinstance(value, dict):
                    continue
                try:
                    matches_chapter = int(value.get("chapter_index")) == chapter_index
                except (TypeError, ValueError):
                    matches_chapter = False
                node_id = str(value.get("node_id") or "")
                revision_id = str(value.get("revision_id") or "")
                if matches_chapter and node_id and revision_id:
                    found.setdefault((node_id, revision_id), str(receipt.id))
    return found


def _map_notice(
    value: dict[str, Any],
    *,
    novel_id: str,
    chapter_index: int,
    current_draft_id: str | None,
    current_source_hash: str | None,
    matching_receipt_id: str | None,
) -> dict[str, Any]:
    node_id = str(value.get("node_id") or "")
    revision_id = str(value.get("revision_id") or "")
    title = str(value.get("title") or "未命名地图对象")
    is_auto_draft = value.get("map_kind") == "auto_draft"
    summary = (
        f"空间草图“{title}”引用的正文来源已变化，请核对草图依据。"
        if is_auto_draft
        else f"地图“{title}”仍引用第 {chapter_index} 章的旧版正文。"
    )
    evidence = [
        {
            "map_title": title,
            "chapter_index": chapter_index,
            "note": "当前地图修订与已发布正文来源已重新核对",
            **({"receipt_id": matching_receipt_id} if matching_receipt_id else {}),
        }
    ]
    basis = stable_hash(
        {
            "novel_id": novel_id,
            "chapter_index": chapter_index,
            "node_id": node_id,
            "current_head_revision_id": revision_id,
            "current_source_id": current_draft_id,
            "current_source_hash": current_source_hash,
            "kind": "auto_draft" if is_auto_draft else "saved_map",
        }
    )
    return {
        "notice_key": f"{SOURCE_ID}:{chapter_index}:{node_id}:{revision_id}",
        "source_id": SOURCE_ID,
        "category": "map_source",
        "severity": "medium",
        "target": {"chapter_index": chapter_index, "node_id": node_id},
        "summary": summary,
        "evidence": evidence,
        "basis_fingerprint": basis,
        "stale": True,
        "actions": [
            {
                "kind": "navigate",
                "page": "map",
                "node_id": node_id or None,
                "chapter_index": chapter_index,
                "label": "去地图核对",
            }
        ],
        "disposition_ref": None,
    }


def _coverage_notice(
    report: dict[str, Any], *, novel_id: str, chapter_index: int
) -> dict[str, Any] | None:
    incomplete = not bool(report.get("checked", True))
    truncated = bool(report.get("truncated") or report.get("auto_draft_truncated"))
    unverified = int(report.get("unverified_sources") or 0) + int(
        report.get("auto_draft_unverified") or 0
    )
    if not incomplete and not truncated and not unverified:
        return None
    details = []
    if incomplete:
        details.append("来源读取未完成")
    if unverified:
        details.append(f"{unverified} 条来源无法验证")
    if truncated:
        details.append("受读取上限影响，结果已截断")
    note = str(report.get("note") or report.get("coverage") or "").strip()
    summary = "地图来源核对不完整：" + "、".join(details) + "。请到地图核对未覆盖部分。"
    coverage_fingerprint = stable_hash(
        {
            "incomplete": incomplete,
            "truncated": truncated,
            "unverified": unverified,
            "note": note,
        }
    )[:16]
    return {
        "notice_key": f"{SOURCE_ID}:coverage:{chapter_index}:{coverage_fingerprint}",
        "source_id": SOURCE_ID,
        "category": "map_source_coverage",
        "severity": "low",
        "target": {"chapter_index": chapter_index},
        "summary": summary,
        "evidence": (
            [{"chapter_index": chapter_index, "coverage_note": note}] if note else []
        ),
        "basis_fingerprint": stable_hash(
            {
                "novel_id": novel_id,
                "chapter_index": chapter_index,
                "incomplete": incomplete,
                "truncated": truncated,
                "unverified": unverified,
                "note": note,
            }
        ),
        "stale": True,
        "actions": [
            {
                "kind": "navigate",
                "page": "map",
                "chapter_index": chapter_index,
                "label": "去地图核对",
            }
        ],
        "disposition_ref": None,
    }


def _receipt_coverage_notice(*, novel_id: str, chapter_index: int) -> dict[str, Any]:
    note = "历史失效回执查找仅查看最近 500 条；当前地图修订和正文来源仍已独立核对。"
    return {
        "notice_key": f"{SOURCE_ID}:history:{chapter_index}",
        "source_id": SOURCE_ID,
        "category": "map_source_coverage",
        "severity": "info",
        "target": {"chapter_index": chapter_index},
        "summary": note,
        "evidence": [{"chapter_index": chapter_index, "coverage_note": note}],
        "basis_fingerprint": stable_hash(
            {
                "novel_id": novel_id,
                "chapter_index": chapter_index,
                "history_limit": MAP_RECEIPT_LIMIT,
            }
        ),
        "stale": False,
        "actions": [
            {
                "kind": "navigate",
                "page": "map",
                "chapter_index": chapter_index,
                "label": "去地图核对",
            }
        ],
        "disposition_ref": None,
    }


async def list_map_source_notices(
    db, novel_id: str, scope: dict[str, object]
) -> list[dict[str, Any]]:
    raw_chapter = scope.get("chapter_index")
    if raw_chapter is None:
        # A Scene-only scope is not a canonical chapter-source identity.
        return []
    chapter_index = int(raw_chapter)
    current_sources = await get_manuscript_source_manifest(
        db,
        novel_id,
        content_mode="canonical",
        chapter_from=chapter_index,
        chapter_to=chapter_index,
    )
    current = next(
        (
            item
            for item in current_sources
            if int(item.get("chapter_index") or 0) == chapter_index
        ),
        None,
    )
    current_draft_id = str(current["draft_id"]) if current else None
    current_source_hash = str(current["content_hash"]) if current else None
    report = await get(WORLD_READ_MAP_CHAPTER_CONSUMERS)(
        db,
        novel_id,
        chapter_index=chapter_index,
        current_draft_id=current_draft_id,
        current_source_hash=current_source_hash,
        content_mode="canonical",
    )
    values = [
        item
        for item in [*(report.get("maps") or []), *(report.get("auto_drafts") or [])]
        if isinstance(item, dict)
    ]
    receipts = (
        await db.scalars(
            select(EvolutionReceiptRecord)
            .where(
                EvolutionReceiptRecord.novel_id == UUID(str(novel_id)),
                EvolutionReceiptRecord.execution_status == "succeeded",
            )
            .order_by(
                EvolutionReceiptRecord.created_at.desc(), EvolutionReceiptRecord.id.desc()
            )
            .limit(MAP_RECEIPT_LIMIT + 1)
        )
    ).all()
    receipt_truncated = len(receipts) > MAP_RECEIPT_LIMIT
    receipt_ids = _receipt_indexes_current_head(
        receipts[:MAP_RECEIPT_LIMIT], chapter_index
    )
    notices = [
        _map_notice(
            item,
            novel_id=str(novel_id),
            chapter_index=chapter_index,
            current_draft_id=current_draft_id,
            current_source_hash=current_source_hash,
            matching_receipt_id=receipt_ids.get(
                (str(item.get("node_id") or ""), str(item.get("revision_id") or ""))
            ),
        )
        for item in values
    ]
    coverage = _coverage_notice(
        report, novel_id=str(novel_id), chapter_index=chapter_index
    )
    if coverage:
        notices.append(coverage)
    if receipt_truncated:
        notices.append(
            _receipt_coverage_notice(novel_id=str(novel_id), chapter_index=chapter_index)
        )
    return notices


NOTICE_SOURCE_SPEC = {
    "source_id": SOURCE_ID,
    "label": "地图来源核对",
    "list_notices": list_map_source_notices,
}
