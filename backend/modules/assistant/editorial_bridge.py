"""BR-4 流程 3 桥接：作者选中的审读意见 → Writing 批注修订。

审读意见始终保留 ``editorial_suggestion`` 身份：本模块只把意见的唯一
准确引文（首条原文依据）定位为选区，连同意见文本与作者处置交给
Writing 既有批注修订（只返回选区替换、治理复审、候选采用门禁不变），
并在桥接候选采用后经既有 ``request_recheck`` 机制请求改后复核。
不把意见转换成语义审查 finding，不做多意见自动融合，也不写 Writing
的独立复核。
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from core.errors import ConflictError, NotFoundError, ValidationError
from modules.assistant.editorial import _append_decision, _enabled, _require_review
from modules.assistant.editorial_contracts import (
    IssueRevisionRequest,
    RecheckRequest,
)
from modules.assistant.editorial_models import EditorialIssue
from modules.assistant.forecast.context import authorize
from modules.writing.contracts import CommentRevisionSelectionContract
from modules.writing.facade import submit_comment_revision

_REVIEW_DECISION_DISPOSITION = "prepare"


def _issue_text(row: EditorialIssue) -> str:
    finding = row.finding_json or {}
    parts = [str(finding.get("judgment") or "").strip()]
    impact = str(finding.get("reader_impact") or "").strip()
    if impact:
        parts.append(f"读者可能的感受：{impact}")
    return "\n".join(part for part in parts if part)


async def _locked_issues(db, novel_id: str, issue_ids: list[uuid.UUID]):
    rows = (
        await db.scalars(
            select(EditorialIssue)
            .where(
                EditorialIssue.novel_id == uuid.UUID(novel_id),
                EditorialIssue.id.in_(issue_ids),
            )
            .with_for_update()
        )
    ).all()
    by_id = {row.id: row for row in rows}
    missing = [str(value) for value in issue_ids if value not in by_id]
    if missing:
        raise NotFoundError("编辑意见不可访问")
    return by_id


async def submit_issue_revision(db, data: IssueRevisionRequest) -> dict:
    """作者选中的一批意见 → 每条按唯一准确引文定位为选区 → 批注修订。

    冻结正文 hash 与当前工作稿不一致时整体失败关闭（Writing 入口抛出
    冲突，提示重新审读）；单条引文已不在当前稿时不为该条生成候选，
    逐条说明且不影响其余意见。成功进入修订的意见记录一条作者处置
    （准备处理 + 处置说明），与既有决定历史一致。
    """
    _enabled()
    novel_id = str(data.novel_id)
    await authorize(db, novel_id)
    issue_ids = [item.issue_id for item in data.items]
    rows = await _locked_issues(db, novel_id, issue_ids)
    operation_key = str(data.operation_id)
    for item in data.items:
        row = rows[item.issue_id]
        if row.row_version == item.expected_version:
            continue
        # 客户端重放：row_version 只因本请求此前的批注处置而前进时不算冲突，
        # 后面按任务回执幂等返回，不重复创建任务或决定。
        last = row.decision_json[-1] if row.decision_json else None
        if (
            row.row_version == item.expected_version + 1
            and last
            and last.get("bridge_operation_id") == operation_key
        ):
            continue
        raise ConflictError("这条意见已有新决定，请刷新后重试")
    selections: list[CommentRevisionSelectionContract] = []
    unsupported: dict[str, str] = {}
    for item in data.items:
        row = rows[item.issue_id]
        evidence = list(row.finding_json.get("evidence") or [])
        primary = evidence[0] if evidence else None
        quote = str((primary or {}).get("quote") or "")
        if primary is None or not quote:
            unsupported[str(row.id)] = "这条意见没有可定位的原文引文，无法发起修订"
            continue
        selections.append(
            CommentRevisionSelectionContract(
                chapter_index=int(primary["chapter_index"]),
                quote=quote,
                frozen_content_hash=str(primary.get("content_hash") or ""),
                body=_issue_text(row),
                instruction=item.instruction,
                ref=str(row.id),
            )
        )
    receipt = await submit_comment_revision(
        db,
        novel_id,
        operation_id=str(data.operation_id),
        selections=selections,
    )
    queued: dict[str, object] = {}
    replayed: set[str] = set()
    for task in receipt.tasks:
        for ref in task.refs:
            queued[ref] = task
            if task.replayed:
                replayed.add(ref)
    items = []
    for item in data.items:
        issue_id = str(item.issue_id)
        task = queued.get(issue_id)
        if task is not None:
            items.append(
                {
                    "issue_id": issue_id,
                    "status": "queued",
                    "task_id": task.task_id,
                    "chapter_index": task.chapter_index,
                }
            )
            continue
        reason = next(
            (entry.reason for entry in receipt.unlocated if entry.ref == issue_id),
            None,
        ) or unsupported.get(issue_id) or "这条意见未能发起修订"
        chapter_index = next(
            (
                entry.chapter_index
                for entry in receipt.unlocated
                if entry.ref == issue_id
            ),
            None,
        )
        items.append(
            {
                "issue_id": issue_id,
                "status": "unlocatable",
                "chapter_index": chapter_index,
                "reason": reason,
            }
        )
    reviews: dict[uuid.UUID, object] = {}
    for item in data.items:
        issue_id = str(item.issue_id)
        task = queued.get(issue_id)
        if task is None or issue_id in replayed:
            continue
        row = rows[item.issue_id]
        review = reviews.get(row.review_id)
        if review is None:
            review = await _require_review(db, novel_id, row.review_id)
            reviews[row.review_id] = review
        _append_decision(
            db,
            row,
            review,
            disposition=_REVIEW_DECISION_DISPOSITION,
            note=f"已发起批注修订：{item.instruction}",
            operation_id=operation_key,
        )
    await db.flush()
    return {"operation_id": str(data.operation_id), "items": items}


async def trigger_post_adoption_rechecks(
    db,
    *,
    novel_id: str,
    issue_ids: list[str],
    adopted_draft_id: str,
) -> list[dict]:
    """桥接候选采用后，为每条相关意见按既有机制请求一次改后复核。

    复核是既有付费任务：无法成立（审读依据已变化、上一轮复核用量未
    确认、编辑约定变化等）时逐条跳过并说明原因，不阻塞采用，也不重复
    排队。请求标识由（意见、采用稿）确定，同一候选的重复采用重放只会
    命中同一轮复核。
    """
    from modules.assistant import editorial

    results = []
    for raw in issue_ids:
        issue_id = uuid.UUID(str(raw))
        row = await db.scalar(
            select(EditorialIssue)
            .where(
                EditorialIssue.novel_id == uuid.UUID(novel_id),
                EditorialIssue.id == issue_id,
            )
            .with_for_update()
        )
        if row is None:
            results.append(
                {"issue_id": str(raw), "status": "skipped", "reason": "意见已不可访问"}
            )
            continue
        operation_id = uuid.uuid5(
            issue_id, f"editorial-bridge-recheck:{adopted_draft_id}"
        )
        try:
            entry = await editorial.request_recheck(
                db,
                issue_id,
                RecheckRequest(
                    novel_id=uuid.UUID(novel_id),
                    operation_id=operation_id,
                    expected_version=row.row_version,
                ),
            )
        except (ConflictError, ValidationError) as exc:
            results.append(
                {"issue_id": str(raw), "status": "skipped", "reason": str(exc)}
            )
            continue
        results.append(
            {
                "issue_id": str(raw),
                "status": str(entry.get("status") or "queued"),
                "task_id": str(entry["task_id"]) if entry.get("task_id") else None,
            }
        )
    return results
