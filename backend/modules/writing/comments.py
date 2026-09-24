"""Version-bound manuscript comments and their queued revision workflow."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from core.errors import ConflictError, NotFoundError, ValidationError
from modules.project.facade import (
    build_project_llm_execution_snapshot,
    require_active_project,
)
from modules.writing.models import WritingComment
from modules.writing.repositories import WritingDraftRepository
from modules.writing.schemas import WritingCommentCreate, WritingCommentRunRequest
from modules.writing.source_hashing import hash_text


def _public_comment(
    row: WritingComment, current_hash: str, current_draft_id=None
) -> dict:
    return {
        "id": str(row.id),
        "draft_id": str(row.draft_id),
        "chapter_index": row.chapter_index,
        "version_number": row.version_number,
        "source_hash": row.source_hash,
        "start_offset": row.start_offset,
        "end_offset": row.end_offset,
        "excerpt": row.excerpt,
        "body": row.body,
        "origin": row.origin,
        "severity": row.severity,
        "status": "stale"
        if current_hash != row.source_hash
        or (current_draft_id is not None and row.draft_id != current_draft_id)
        or row.start_offset is None
        else row.status,
        "review_task_id": str(row.review_task_id) if row.review_task_id else None,
        "finding_id": row.finding_id,
        "last_run_task_id": str(row.last_run_task_id) if row.last_run_task_id else None,
        "created_at": row.created_at,
    }


async def _draft(db, novel_id: str, draft_id: uuid.UUID):
    await require_active_project(db, novel_id)
    draft = await WritingDraftRepository().get(db, draft_id)
    if draft is None or str(draft.novel_id) != novel_id:
        raise NotFoundError("正文不存在")
    return draft


async def _current_draft(db, novel_id: str, draft_id: uuid.UUID):
    draft = await _draft(db, novel_id, draft_id)
    latest = await WritingDraftRepository().get_latest_by_chapter(
        db, draft.novel_id, draft.chapter_index
    )
    if latest is None or latest.id != draft.id or draft.status == "candidate":
        raise ConflictError("请先打开并保存当前工作稿")
    return draft


async def list_comments(db, novel_id: str, draft_id: uuid.UUID) -> list[dict]:
    draft = await _draft(db, novel_id, draft_id)
    rows = (
        await db.scalars(
            select(WritingComment)
            .where(
                WritingComment.novel_id == draft.novel_id,
                WritingComment.chapter_index == draft.chapter_index,
            )
            .order_by(WritingComment.created_at.desc())
            .limit(200)
        )
    ).all()
    return [_public_comment(row, draft.content_hash, draft.id) for row in rows]


async def create_comment(db, draft_id: uuid.UUID, data: WritingCommentCreate) -> dict:
    draft = await _current_draft(db, data.novel_id, draft_id)
    content = draft.content or ""
    if (
        data.source_hash != draft.content_hash
        or content[data.start_offset : data.end_offset] != data.excerpt
    ):
        raise ConflictError("正文或选区已变化，请重新选择原文")
    body = data.body.strip()
    if not body:
        raise ValidationError("批注内容不能为空")
    row = WritingComment(
        novel_id=draft.novel_id,
        draft_id=draft.id,
        chapter_index=draft.chapter_index,
        version_number=draft.version_number,
        source_hash=draft.content_hash,
        range_hash=hash_text(data.excerpt),
        start_offset=data.start_offset,
        end_offset=data.end_offset,
        excerpt=data.excerpt,
        body=body,
        origin="author",
        status="open",
    )
    db.add(row)
    await db.flush()
    return _public_comment(row, draft.content_hash)


async def set_comment_status(
    db, novel_id: str, comment_id: uuid.UUID, status: str
) -> dict:
    await require_active_project(db, novel_id)
    row = await db.scalar(
        select(WritingComment)
        .where(
            WritingComment.id == comment_id,
            WritingComment.novel_id == uuid.UUID(novel_id),
        )
        .with_for_update()
    )
    if row is None:
        raise NotFoundError("批注不存在")
    draft = await _draft(db, novel_id, row.draft_id)
    if row.source_hash != draft.content_hash:
        raise ConflictError("正文已变化，请重新定位批注")
    row.status = status
    await db.flush()
    return _public_comment(row, draft.content_hash)


async def submit_comment_run(db, data: WritingCommentRunRequest) -> dict:
    from infrastructure.tasks.facade import (
        enqueue_task_with_optional_operation,
        get_operation_task,
    )

    novel_id = data.novel_id
    await require_active_project(db, novel_id)
    request_payload = {
        "novel_id": novel_id,
        "draft_id": str(data.draft_id),
        "comment_ids": [str(value) for value in data.comment_ids],
        "include_ai_review": data.include_ai_review,
    }
    existing = await get_operation_task(
        db,
        operation_id=str(data.operation_id),
        task_type="writing_comment_run",
        novel_id=novel_id,
        request_payload=request_payload,
    )
    if existing is not None:
        return {"task_id": existing.task_id, "status": existing.status}
    draft = await _current_draft(db, novel_id, data.draft_id)
    rows = (
        await db.scalars(
            select(WritingComment).where(
                WritingComment.novel_id == draft.novel_id,
                WritingComment.draft_id == draft.id,
                WritingComment.id.in_(data.comment_ids),
            )
        )
    ).all()
    if len(rows) != len(data.comment_ids):
        raise NotFoundError("所选批注不存在")
    if any(
        row.status != "open"
        or row.source_hash != draft.content_hash
        or row.start_offset is None
        for row in rows
    ):
        raise ConflictError("所选批注已处理或正文已变化")
    snapshot = await build_project_llm_execution_snapshot(db, novel_id)
    receipt = await enqueue_task_with_optional_operation(
        db,
        operation_id=str(data.operation_id),
        task_type="writing_comment_run",
        novel_id=novel_id,
        request_payload=request_payload,
        meta={
            **request_payload,
            "source_hash": draft.content_hash,
            "llm_execution_snapshot": snapshot,
        },
    )
    await db.flush()
    return {"task_id": receipt.task_id, "status": receipt.status}
