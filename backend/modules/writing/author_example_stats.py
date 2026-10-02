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

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.writing.models import WritingDraft

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
            )
            .order_by(WritingDraft.created_at.desc())
            .limit(_MAX_SCANNED + 1)
        )
    ).all()
    truncated = len(rows) > _MAX_SCANNED
    rows = rows[:_MAX_SCANNED]

    candidates = [
        row
        for row in rows
        if (row.provenance_json or {}).get("source") == "writing_generate"
        and (row.provenance_json or {}).get("context_action") == "writing.generate"
    ]
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
    for result_id, candidate in candidate_by_result_id.items():
        adopted = adopted_drafts.get(result_id)
        if adopted is None or adopted.novel_id != novel_uuid:
            continue
        used = (candidate.provenance_json or {}).get("author_examples_used") is True
        bucket = buckets["with_examples" if used else "without_examples"]
        bucket["adopted"] += 1
        latest = (
            await db.scalars(
                select(WritingDraft)
                .where(
                    WritingDraft.novel_id == novel_uuid,
                    WritingDraft.chapter_index == adopted.chapter_index,
                    # 只看作者可保存的工作稿/正式正文；同章后续新生成的
                    # candidate 不算「采纳后被修改」。
                    WritingDraft.status.in_(["draft", "published"]),
                )
                .order_by(WritingDraft.version_number.desc())
                .limit(1)
            )
        ).first()
        reference = latest or adopted
        if reference.content_hash and reference.content_hash != candidate.content_hash:
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
            "观察性对照：愿意标注示例的作者本身更投入，仅作方向信号，"
            "不构成因果结论。"
        ),
    }
