"""Version-bound manuscript comments and their queued revision workflow."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from core.errors import ConflictError, NotFoundError, ValidationError
from modules.project.facade import (
    build_project_llm_execution_snapshot,
    require_active_project,
)
from modules.writing.contracts import (
    CommentRevisionReceiptContract,
    CommentRevisionSelectionContract,
    CommentRevisionTaskReceiptContract,
    CommentRevisionUnlocatedContract,
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


_MAX_BRIDGE_SELECTIONS = 20
_QUOTE_MAX_CHARS = 240
_BODY_MAX_CHARS = 4000
_INSTRUCTION_MAX_CHARS = 2000


def _bridge_comment_body(selection: CommentRevisionSelectionContract) -> str:
    body = selection.body.strip()
    instruction = selection.instruction.strip()
    if instruction:
        body = f"{body}\n作者处置：{instruction}"
    return body


def _validate_bridge_selection(selection: CommentRevisionSelectionContract) -> None:
    if not selection.ref or len(selection.ref) > 80:
        raise ValidationError("意见标识缺失或过长")
    if not selection.quote.strip() or len(selection.quote) > _QUOTE_MAX_CHARS:
        raise ValidationError("意见引文为空或超出长度限制")
    if not selection.body.strip() or len(selection.body) > _BODY_MAX_CHARS:
        raise ValidationError("意见文本为空或超出长度限制")
    if not selection.instruction.strip():
        raise ValidationError("请先填写这条意见的处置说明")
    if len(selection.instruction) > _INSTRUCTION_MAX_CHARS:
        raise ValidationError("处置说明过长，请精简后再提交")
    if not selection.frozen_content_hash:
        raise ValidationError("意见缺少审读时的正文 hash，无法安全定位")


async def submit_comment_revision(
    db,
    novel_id: str,
    *,
    operation_id: str,
    selections: list[CommentRevisionSelectionContract],
) -> CommentRevisionReceiptContract:
    """按外部定位选区启动既有批注修订（BR-4 流程 3 的 Writing 稳定入口）。

    供 Assistant 桥接审读意见调用：冻结正文 hash 与当前工作稿不一致时
    整体失败关闭（提示重新审读）；引文无法在当前稿中唯一定位的选区
    逐条跳过并说明，不影响其余选区。复用 ``writing_comment_run`` 的
    选区替换、治理复审与候选采用门禁，不新增模型能力。同一请求标识
    幂等：重放返回既有任务，不重复创建批注。
    """
    from infrastructure.tasks.facade import (
        enqueue_task_with_optional_operation,
        get_operation_task,
    )

    if not selections:
        raise ValidationError("请至少选择一条意见")
    if len(selections) > _MAX_BRIDGE_SELECTIONS:
        raise ValidationError(f"一次最多提交 {_MAX_BRIDGE_SELECTIONS} 条意见的修订")
    request_operation = uuid.UUID(str(operation_id))
    await require_active_project(db, novel_id)
    for selection in selections:
        _validate_bridge_selection(selection)
    grouped: dict[int, list[CommentRevisionSelectionContract]] = {}
    for selection in selections:
        grouped.setdefault(int(selection.chapter_index), []).append(selection)
    snapshot = await build_project_llm_execution_snapshot(db, novel_id)
    tasks: list[CommentRevisionTaskReceiptContract] = []
    unlocated: list[CommentRevisionUnlocatedContract] = []
    for chapter_index in sorted(grouped):
        items = grouped[chapter_index]
        latest = await WritingDraftRepository().get_latest_by_chapter(
            db, uuid.UUID(novel_id), chapter_index
        )
        if latest is None:
            raise ConflictError(f"第 {chapter_index} 章还没有可修订的工作稿")
        if any(
            selection.frozen_content_hash != latest.content_hash
            or (selection.draft_id is not None and selection.draft_id != str(latest.id))
            for selection in items
        ):
            raise ConflictError("审读依据的正文已变化，请重新审读", code="SOURCE_STALE")
        content = latest.content or ""
        located: list[tuple[CommentRevisionSelectionContract, int, int]] = []
        for selection in items:
            if content.count(selection.quote) == 0:
                unlocated.append(
                    CommentRevisionUnlocatedContract(
                        ref=selection.ref,
                        chapter_index=chapter_index,
                        reason="意见引文已不在当前稿中，无法定位；这条不会生成替换候选",
                    )
                )
                continue
            if selection.start is not None:
                if (
                    selection.end is None
                    or selection.start < 0
                    or selection.end <= selection.start
                    or selection.end > len(content)
                    or content[selection.start : selection.end] != selection.quote
                    or selection.range_hash != hash_text(selection.quote)
                ):
                    raise ConflictError(
                        "选区与冻结原文不一致，请重新选择", code="SOURCE_STALE"
                    )
                located.append((selection, selection.start, selection.end))
            elif content.count(selection.quote) == 1:
                start = content.find(selection.quote)
                located.append((selection, start, start + len(selection.quote)))
            else:
                unlocated.append(
                    CommentRevisionUnlocatedContract(
                        ref=selection.ref,
                        chapter_index=chapter_index,
                        reason="意见引文已不在当前稿中，无法定位；这条不会生成替换候选",
                    )
                )
        if not located:
            continue
        ordered = sorted(located, key=lambda entry: (entry[1], entry[2]))
        overlaps = any(
            right[1] < max(entry[2] for entry in ordered[:index])
            for index, right in enumerate(ordered[1:], 1)
        )
        if overlaps and not all(
            selection.overlap_confirmed for selection, _, _ in located
        ):
            raise ConflictError(
                "所选片段重叠，请查看合并范围并确认后再生成",
                code="OVERLAP_CONFIRMATION_REQUIRED",
            )
        chapter_operation = str(uuid.uuid5(request_operation, f"chapter:{chapter_index}"))
        refs = [selection.ref for selection, _start, _end in located]
        request_payload = {
            "novel_id": novel_id,
            "draft_id": str(latest.id),
            "bridge": "editorial",
            "selections": [
                {
                    "chapter_index": selection.chapter_index,
                    "quote": selection.quote,
                    "ref": selection.ref,
                    "instruction": selection.instruction,
                    "body": selection.body,
                    "source_hash": selection.frozen_content_hash,
                    "start": start,
                    "end": end,
                    "overlap_confirmed": selection.overlap_confirmed,
                }
                for selection, start, end in located
            ],
        }
        existing = await get_operation_task(
            db,
            operation_id=chapter_operation,
            task_type="writing_comment_run",
            novel_id=novel_id,
            request_payload=request_payload,
        )
        if existing is not None:
            tasks.append(
                CommentRevisionTaskReceiptContract(
                    chapter_index=chapter_index,
                    task_id=existing.task_id,
                    status=existing.status,
                    replayed=True,
                    refs=refs,
                )
            )
            continue
        editorial_refs: dict[str, str] = {}
        for selection, start, end in located:
            row = WritingComment(
                novel_id=latest.novel_id,
                draft_id=latest.id,
                chapter_index=latest.chapter_index,
                version_number=latest.version_number,
                source_hash=latest.content_hash,
                range_hash=hash_text(selection.quote),
                start_offset=start,
                end_offset=end,
                excerpt=selection.quote,
                body=_bridge_comment_body(selection),
                origin="ai",
                status="open",
            )
            db.add(row)
            await db.flush()
            editorial_refs[str(row.id)] = selection.ref
        receipt = await enqueue_task_with_optional_operation(
            db,
            operation_id=chapter_operation,
            task_type="writing_comment_run",
            novel_id=novel_id,
            request_payload=request_payload,
            meta={
                "novel_id": novel_id,
                "draft_id": str(latest.id),
                "comment_ids": list(editorial_refs),
                "include_ai_review": False,
                "source_hash": latest.content_hash,
                "llm_execution_snapshot": snapshot,
                "editorial_refs": editorial_refs,
            },
        )
        tasks.append(
            CommentRevisionTaskReceiptContract(
                chapter_index=chapter_index,
                task_id=receipt.task_id,
                status=receipt.status,
                replayed=False,
                refs=refs,
            )
        )
    await db.flush()
    return CommentRevisionReceiptContract(tasks=tasks, unlocated=unlocated)
