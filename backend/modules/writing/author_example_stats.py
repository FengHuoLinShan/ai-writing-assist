"""作者写作示例的对照统计（观察性诊断，非因果结论）。

同项目、窗口期内带/不带示例的 writing.generate 候选对照：
采纳率（adopted / candidates）与采纳后改动比例（content_hash 变化）。
愿意标注示例的作者本身更投入，这只是方向信号；挂在项目设置
ai-usage 同级的次级诊断入口。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.writing.models import WritingDraft
from modules.writing.repositories import WORKING_DRAFT_STATUSES

# 诊断扫描上限：窗口内草稿超过该数量时截断并在响应中标记，
# 避免把次级诊断入口放大成全表扫描。
_MAX_SCANNED = 500


def _bucket() -> dict[str, Any]:
    return {
        "candidates": 0,
        "adopted": 0,
        "adopted_with_changes": 0,
        "adoption_rate": None,
    }


async def get_author_example_stats(
    db: AsyncSession,
    novel_id: str,
    *,
    days: int = 30,
) -> dict[str, Any]:
    try:
        novel_uuid = UUID(str(novel_id))
    except ValueError as exc:
        from core.errors import ValidationError as DomainValidationError

        raise DomainValidationError("项目编号不合法") from exc
    window_start = datetime.now(UTC) - timedelta(days=days)
    rows = (
        await db.scalars(
            select(WritingDraft)
            .where(
                WritingDraft.novel_id == novel_uuid,
                WritingDraft.created_at >= window_start,
                WritingDraft.provenance_json["source"].as_string() == "writing_generate",
                WritingDraft.provenance_json["context_action"].as_string()
                == "writing.generate",
                WritingDraft.provenance_json["adopted_from_candidate_id"]
                .as_string()
                .is_(None),
                or_(
                    WritingDraft.status == "candidate",
                    WritingDraft.provenance_json["deprecated_from_status"].as_string()
                    == "candidate",
                    WritingDraft.provenance_json["adoption_result_draft_id"]
                    .as_string()
                    .is_not(None),
                ),
            )
            .order_by(WritingDraft.created_at.desc())
            .limit(_MAX_SCANNED + 1)
        )
    ).all()
    truncated = len(rows) > _MAX_SCANNED
    rows = rows[:_MAX_SCANNED]

    candidates = rows
    buckets: dict[str, dict[str, Any]] = {
        "with_examples": _bucket(),
        "without_examples": _bucket(),
    }
    for row in candidates:
        used = (row.provenance_json or {}).get("author_examples_used") is True
        buckets["with_examples" if used else "without_examples"]["candidates"] += 1

    # 采纳链：candidate.provenance.adoption_result_draft_id → 采纳产生的工作稿。
    adopted_keys = {
        str((row.provenance_json or {}).get("adoption_result_draft_id"))
        for row in candidates
        if (row.provenance_json or {}).get("adoption_result_draft_id")
    }
    candidate_by_result_id = {
        str((row.provenance_json or {}).get("adoption_result_draft_id")): row
        for row in candidates
        if (row.provenance_json or {}).get("adoption_result_draft_id")
    }
    adopted_drafts = (
        {
            str(draft.id): draft
            for draft in (
                await db.scalars(
                    select(WritingDraft).where(
                        WritingDraft.novel_id == novel_uuid,
                        WritingDraft.id.in_([UUID(key) for key in adopted_keys]),
                    )
                )
            ).all()
        }
        if adopted_keys
        else {}
    )
    # 各章最新工作稿的 content_hash 一次取回：同章后续新生成的 candidate
    # 不算「采纳后被修改」，只看作者可保存的工作稿/正式正文。
    adopted_chapters = sorted(
        {adopted.chapter_index for adopted in adopted_drafts.values()}
    )
    latest_hash_by_chapter: dict[int, str | None] = {}
    if adopted_chapters:
        latest_rows = (
            await db.execute(
                select(
                    WritingDraft.chapter_index,
                    WritingDraft.version_number,
                    WritingDraft.content_hash,
                )
                .where(
                    WritingDraft.novel_id == novel_uuid,
                    WritingDraft.chapter_index.in_(adopted_chapters),
                    WritingDraft.status.in_(WORKING_DRAFT_STATUSES),
                )
                .order_by(
                    WritingDraft.chapter_index.asc(),
                    WritingDraft.version_number.desc(),
                )
            )
        ).all()
        for chapter_index, _version_number, content_hash in latest_rows:
            latest_hash_by_chapter.setdefault(chapter_index, content_hash)
    for result_id, candidate in candidate_by_result_id.items():
        adopted = adopted_drafts.get(result_id)
        if adopted is None or adopted.novel_id != novel_uuid:
            continue
        used = (candidate.provenance_json or {}).get("author_examples_used") is True
        bucket = buckets["with_examples" if used else "without_examples"]
        bucket["adopted"] += 1
        reference_hash = latest_hash_by_chapter.get(adopted.chapter_index)
        if reference_hash is None:
            reference_hash = adopted.content_hash
        if reference_hash and reference_hash != candidate.content_hash:
            bucket["adopted_with_changes"] += 1

    for bucket in buckets.values():
        if bucket["candidates"]:
            bucket["adoption_rate"] = round(bucket["adopted"] / bucket["candidates"], 4)

    return {
        "window_days": days,
        "scanned": len(rows),
        "scan_truncated": truncated,
        "buckets": buckets,
        "note": (
            "观察性对照：愿意标注示例的作者本身更投入，仅作方向信号，不构成因果结论。"
        ),
    }
