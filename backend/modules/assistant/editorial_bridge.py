"""BR-4 流程 3 桥接：作者选中的审读意见 → Writing 批注修订。

审读意见始终保留 editorial_suggestion 身份：本模块只把作者明确选择的一处或多处
准确引文定位为选区，连同意见文本与作者处置交给 Writing 既有批注修订。选中的证据
可跨章节；Writing 按章创建独立任务，并仍只替换被选中的局部范围，沿用治理复审与
候选采用门禁。作者未选择的依据不进入批次。
不把意见转换成语义审查 finding，不做多意见自动融合，也不写 Writing 的独立复核。
"""

from __future__ import annotations

import hashlib
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
        indices = item.evidence_indices
        if indices is None:
            if len(evidence) > 1:
                raise ValidationError("这条意见有多处依据，请明确选择需要修改的位置")
            indices = [0] if evidence else []
        if len(indices) != len(set(indices)) or any(
            index < 0 or index >= len(evidence) for index in indices
        ):
            raise ValidationError("证据选择包含未知或重复位置")
        overrides = {entry.evidence_index: entry for entry in item.ranges}
        if len(overrides) != len(item.ranges) or not set(overrides).issubset(indices):
            raise ValidationError("手动选区必须属于本次选定的证据基稿")
        for index in indices:
            primary = evidence[index]
            manual = overrides.get(index)
            quote = manual.quote if manual else str(primary.get("quote") or "")
            if not quote:
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
                    draft_id=str(primary["draft_id"])
                    if primary.get("draft_id")
                    else None,
                    start=manual.start if manual else primary.get("start"),
                    end=manual.end if manual else primary.get("end"),
                    range_hash=manual.range_hash
                    if manual
                    else hashlib.sha256(quote.encode("utf-8")).hexdigest(),
                    overlap_confirmed=data.overlap_confirmed,
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
        accepted = [task for task in receipt.tasks if issue_id in task.refs]
        if accepted:
            items.extend(
                {
                    "issue_id": issue_id,
                    "status": "queued",
                    "task_id": task.task_id,
                    "chapter_index": task.chapter_index,
                }
                for task in accepted
            )
        for entry in receipt.unlocated:
            if entry.ref == issue_id:
                items.append(
                    {
                        "issue_id": issue_id,
                        "status": "unlocatable",
                        "chapter_index": entry.chapter_index,
                        "reason": entry.reason,
                    }
                )
        if not accepted and not any(entry.ref == issue_id for entry in receipt.unlocated):
            items.append(
                {
                    "issue_id": issue_id,
                    "status": "unlocatable",
                    "chapter_index": None,
                    "reason": unsupported.get(issue_id) or "这条意见未能发起修订",
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
