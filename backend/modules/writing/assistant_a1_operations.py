"""High-frequency Writing operations routed through existing domain services."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from core.container import get
from core.errors import ConflictError, NotFoundError
from core.service_keys import ASSISTANT_REQUIRE_OPERATION_TARGETS
from modules.writing.comments import set_comment_status
from modules.writing.conflict_check_service import WritingConflictCheckService
from modules.writing.models import WritingComment
from modules.writing.repositories import WritingDraftRepository
from modules.writing.schemas import (
    EditorialReadyRequest,
    WritingConflictCheckCreate,
    WritingDraftCheckpoint,
)
from modules.writing.services import WritingDraftService


class RenameChapter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    draft_id: UUID
    title: str = Field(min_length=1, max_length=500)


class MarkEditorialReady(BaseModel):
    model_config = ConfigDict(extra="forbid")

    draft_id: UUID
    expected_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class DisposeComment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    comment_id: UUID
    status: Literal["open", "resolved"]


class CheckChapterConflicts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    draft_id: UUID
    expected_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    scene_id: UUID | None = None


async def _require_draft_target(db, novel_id, context, draft_id):
    await get(ASSISTANT_REQUIRE_OPERATION_TARGETS)(
        db, novel_id, context, [("writing_draft", draft_id)]
    )


async def _latest_draft(db, novel_id, draft_id, context):
    await _require_draft_target(db, novel_id, context, draft_id)
    repo = WritingDraftRepository()
    draft = await repo.get(db, draft_id)
    if draft is None or str(draft.novel_id) != str(novel_id):
        raise NotFoundError("正文版本不存在或不属于当前作品")
    latest = await repo.get_latest_by_chapter(db, draft.novel_id, draft.chapter_index)
    if latest is None or latest.id != draft.id or draft.status == "candidate":
        raise ConflictError("请先打开当前章节工作稿，再进行此操作")
    return draft


async def _rename_preview(db, novel_id, args, *, context=None):
    draft = await _latest_draft(db, novel_id, args.draft_id, context)
    return {
        "target_key": f"writing_chapter:{draft.chapter_index}",
        "title": f"重命名第 {draft.chapter_index} 章",
        "draft_id": str(draft.id),
        "expected_version": draft.version_number,
        "expected_updated_at": draft.updated_at.isoformat() if draft.updated_at else None,
        "expected_content_hash": draft.content_hash,
        "before": draft.title,
        "after": args.title,
        "effect": "保存一个新的可编辑章节版本；原版本继续保留，可从版本历史恢复",
    }


async def _rename_apply(db, novel_id, args, preview, *, context=None):
    if await _rename_preview(db, novel_id, args, context=context) != preview:
        raise ConflictError("章节版本或标题已变化，请重新准备")
    draft = await _latest_draft(db, novel_id, args.draft_id, context)
    result = await WritingDraftService().checkpoint_draft(
        db,
        str(draft.id),
        WritingDraftCheckpoint(
            title=args.title,
            content=draft.content,
            expected_version=preview["expected_version"],
            expected_updated_at=preview["expected_updated_at"],
            force=True,
        ),
        novel_id,
    )
    return {
        "type": "writing_draft",
        "id": str(result.id),
        "chapter_index": result.chapter_index,
        "label": "章节标题已更新",
    }


async def _editorial_ready_preview(db, novel_id, args, *, context=None):
    draft = await _latest_draft(db, novel_id, args.draft_id, context)
    if draft.status != "draft" or not (draft.content or "").strip():
        raise ConflictError("只有已保存的非空工作稿可以标记为可交给编辑查看")
    if draft.content_hash != args.expected_content_hash:
        raise ConflictError("正文已有新版本，请先保存并刷新")
    return {
        "target_key": f"writing_chapter:{draft.chapter_index}",
        "title": f"标记第 {draft.chapter_index} 章可交给编辑查看",
        "draft_id": str(draft.id),
        "expected_content_hash": draft.content_hash,
        "editorial_ready_hash": draft.editorial_ready_hash,
        "effect": "只更新当前正文版本的编辑准备标记；不发布正文或签署知识边界检查",
    }


async def _editorial_ready_apply(db, novel_id, args, preview, *, context=None):
    if await _editorial_ready_preview(db, novel_id, args, context=context) != preview:
        raise ConflictError("正文版本或编辑准备状态已变化，请重新准备")
    result = await WritingDraftService().mark_editorial_ready(
        db,
        str(args.draft_id),
        novel_id,
        EditorialReadyRequest(expected_content_hash=args.expected_content_hash),
    )
    return {
        "type": "writing_draft",
        "id": str(result.id),
        "chapter_index": result.chapter_index,
        "label": "章节已标记为可交给编辑查看",
    }


async def _comment_state(db, novel_id, args, context):
    comment = await db.scalar(
        select(WritingComment)
        .where(
            WritingComment.id == args.comment_id,
            WritingComment.novel_id == UUID(str(novel_id)),
        )
        .with_for_update()
    )
    if comment is None:
        raise NotFoundError("批注不存在或不属于当前作品")
    await _require_draft_target(db, novel_id, context, comment.draft_id)
    repo = WritingDraftRepository()
    draft = await repo.get(db, comment.draft_id)
    latest = (
        await repo.get_latest_by_chapter(db, comment.novel_id, comment.chapter_index)
        if draft is not None
        else None
    )
    if (
        draft is None
        or latest is None
        or draft.id != latest.id
        or comment.draft_id != latest.id
        or comment.source_hash != latest.content_hash
        or comment.start_offset is None
    ):
        raise ConflictError("正文版本已变化或批注无法定位，请重新选择当前批注")
    return comment, draft


async def _comment_preview(db, novel_id, args, *, context=None):
    comment, draft = await _comment_state(db, novel_id, args, context)
    return {
        "target_key": f"writing_comment:{comment.id}",
        "title": f"处置第 {comment.chapter_index} 章批注",
        "chapter_index": comment.chapter_index,
        "draft_id": str(draft.id),
        "source_hash": comment.source_hash,
        "before": comment.status,
        "after": args.status,
        "effect": "只更新仍锚定当前正文版本的批注状态",
    }


async def _comment_apply(db, novel_id, args, preview, *, context=None):
    if await _comment_preview(db, novel_id, args, context=context) != preview:
        raise ConflictError("批注状态或锚定正文已变化，请重新准备")
    result = await set_comment_status(db, novel_id, args.comment_id, args.status)
    return {
        "type": "writing_comment",
        "id": str(args.comment_id),
        "label": "批注状态已更新",
        "status": result["status"],
    }


async def _conflict_preview(db, novel_id, args, *, context=None):
    draft = await _latest_draft(db, novel_id, args.draft_id, context)
    if draft.content_hash != args.expected_content_hash:
        raise ConflictError("正文已有新版本，请先保存并刷新")
    scene_id = args.scene_id or (context.work.scene_id if context else None)
    if scene_id:
        await get(ASSISTANT_REQUIRE_OPERATION_TARGETS)(
            db, novel_id, context, [("outline_scene", scene_id)]
        )
    return {
        "target_key": f"writing_chapter:{draft.chapter_index}",
        "title": f"检查第 {draft.chapter_index} 章的连续性冲突",
        "draft_id": str(draft.id),
        "scene_id": str(scene_id) if scene_id else None,
        "version_number": draft.version_number,
        "content_hash": draft.content_hash,
        "effect": "生成可追溯的检查报告；不会改写或采用正文、场景或世界资料",
    }


async def _conflict_apply(db, novel_id, args, preview, *, context=None):
    from modules.writing.facade import lock_chapter_versions_for_revalidation

    draft = await _latest_draft(db, novel_id, args.draft_id, context)
    await lock_chapter_versions_for_revalidation(db, novel_id, [draft.chapter_index])
    if await _conflict_preview(db, novel_id, args, context=context) != preview:
        raise ConflictError("正文或 Scene 基线已变化，请重新检查")
    draft = await _latest_draft(db, novel_id, args.draft_id, context)
    result = await WritingConflictCheckService().create_check(
        db,
        WritingConflictCheckCreate(
            novel_id=novel_id,
            chapter_index=draft.chapter_index,
            scene_id=preview["scene_id"],
            draft_id=str(draft.id),
            version_number=draft.version_number,
            content=draft.content or "",
        ),
    )
    return {
        "type": "writing_conflict_check",
        "id": str(result.id),
        "chapter_index": result.chapter_index,
        "status": result.status,
        "item_count": len(result.items),
        "label": "连续性检查已完成",
    }


OPERATIONS_SPEC = {
    "writing.chapter.rename": {
        "label": "重命名章节",
        "schema": RenameChapter,
        "prepare": _rename_preview,
        "apply": _rename_apply,
        "permission": "confirm",
        "op_version": "1",
        "description": "为当前章节标题保存一个新工作稿版本；保留已有正文和版本历史。",
        "risk_level": "R2",
        "fee_category": "free",
        "reversibility": "writing_version_restore",
        "preconditions": ("目标为当前章节的最新非候选正文版本",),
        "produces": ("writing_draft",),
        "target_type": "writing_chapter",
        "ai_available": True,
        "transaction_mode": "single_transaction",
        "trace_rule": {
            "parameter_fields": ("draft_id", "title"),
            "mode": "per_call",
            "parameter_policy": "schema_safe",
        },
    },
    "writing.chapter.mark_editorial_ready": {
        "label": "标记章节可交给编辑查看",
        "schema": MarkEditorialReady,
        "prepare": _editorial_ready_preview,
        "apply": _editorial_ready_apply,
        "permission": "confirm",
        "op_version": "1",
        "description": (
            "在当前正文 hash 上记录作者的编辑准备状态；"
            "不代表正文已发布或已完成知识边界检查。"
        ),
        "risk_level": "R2",
        "fee_category": "free",
        "reversibility": "content_change_invalidates_signal",
        "preconditions": ("当前工作稿非空且 hash 未变化",),
        "produces": ("editorial_ready_marker",),
        "target_type": "writing_chapter",
        "ai_available": True,
        "transaction_mode": "single_transaction",
        "trace_rule": {
            "parameter_fields": ("draft_id", "expected_content_hash"),
            "mode": "per_call",
            "parameter_policy": "schema_safe",
        },
    },
    "writing.comment.set_status": {
        "label": "处置正文批注",
        "schema": DisposeComment,
        "prepare": _comment_preview,
        "apply": _comment_apply,
        "permission": "confirm",
        "op_version": "1",
        "description": "将锚定当前正文版本的批注标为待处理或已解决；不提交模型修订任务。",
        "risk_level": "R2",
        "fee_category": "free",
        "reversibility": "comment_status_reopen",
        "preconditions": ("批注仍锚定当前正文版本且定位有效",),
        "produces": ("writing_comment_status",),
        "target_type": "writing_comment",
        "ai_available": True,
        "transaction_mode": "single_transaction",
        "trace_rule": {
            "parameter_fields": ("comment_id", "status"),
            "mode": "per_call",
            "parameter_policy": "schema_safe",
        },
    },
    "writing.conflict_check.create": {
        "label": "检查章节连续性冲突",
        "schema": CheckChapterConflicts,
        "prepare": _conflict_preview,
        "apply": _conflict_apply,
        "permission": "confirm",
        "op_version": "1",
        "description": (
            "对指定的当前正文版本生成确定性连续性检查报告；不会改写正文或启动模型任务。"
        ),
        "risk_level": "R1",
        "fee_category": "free",
        "reversibility": "retained_derived_report",
        "preconditions": ("指定的正文版本为当前最新版本",),
        "produces": ("writing_conflict_check",),
        "target_type": "writing_chapter",
        "ai_available": True,
        "transaction_mode": "single_transaction",
        "trace_rule": {
            "parameter_fields": ("draft_id", "expected_content_hash", "scene_id"),
            "mode": "per_call",
            "parameter_policy": "schema_safe",
        },
    },
}
