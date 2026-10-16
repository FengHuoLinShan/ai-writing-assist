"""Assistant directory entries for author-confirmed chapter ordering."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from core.container import get
from core.errors import ConflictError, ValidationError
from core.service_keys import ASSISTANT_REQUIRE_OPERATION_TARGETS
from modules.writing.facade import (
    confirm_chapter_order,
    list_chapter_order_history,
    preview_chapter_order,
    preview_chapter_order_restore,
    restore_chapter_order,
)
from modules.writing.schemas import (
    ChapterOrderConfirmedRequest,
    ChapterOrderPreviewRequest,
    ChapterOrderRestoreConfirmedRequest,
)


class ChapterOrderOperationArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chapter_indices: list[int] | None = Field(
        default=None,
        min_length=1,
        max_length=2000,
        description="按希望正文出现顺序提交当前章节号",
    )
    expected_preview_hash: str | None = Field(
        default=None,
        pattern=r"^[a-f0-9]{64}$",
    )
    confirmed: bool | None = None


class ChapterOrderRestoreOperationArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    receipt_id: UUID
    expected_preview_hash: str | None = Field(
        default=None,
        pattern=r"^[a-f0-9]{64}$",
    )
    confirmed: bool | None = None


class ChapterOrderHistoryArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limit: int = Field(default=20, ge=1, le=100)


async def _require_whole_novel_scope(db, novel_id, context):
    if context is None:
        return
    if context.work.scope != "project":
        raise ConflictError("章节重排涉及整部作品，请在项目范围或写作工作台核对")
    await get(ASSISTANT_REQUIRE_OPERATION_TARGETS)(
        db, novel_id, context, [], aggregate=True
    )


async def _reorder_prepare(db, novel_id, args, *, context=None):
    await _require_whole_novel_scope(db, novel_id, context)
    if not args.chapter_indices:
        raise ValidationError("请提交章节的目标顺序")
    result = await preview_chapter_order(
        db,
        novel_id,
        ChapterOrderPreviewRequest(chapter_indices=args.chapter_indices),
    )
    return result.model_dump(mode="json")


async def _reorder_apply(db, novel_id, args, preview, *, context=None):
    await _require_whole_novel_scope(db, novel_id, context)
    if (
        args.expected_preview_hash
        and args.expected_preview_hash != preview["preview_hash"]
    ):
        raise ConflictError("章节顺序预览已变化，请重新准备")
    result = await confirm_chapter_order(
        db,
        novel_id,
        preview["receipt_id"],
        ChapterOrderConfirmedRequest(
            expected_preview_hash=preview["preview_hash"],
            confirmed=True,
        ),
    )
    return result.model_dump(mode="json")


async def _restore_prepare(db, novel_id, args, *, context=None):
    await _require_whole_novel_scope(db, novel_id, context)
    return (
        await preview_chapter_order_restore(db, novel_id, str(args.receipt_id))
    ).model_dump(mode="json")


async def _restore_apply(db, novel_id, args, preview, *, context=None):
    await _require_whole_novel_scope(db, novel_id, context)
    if not preview.get("can_restore"):
        raise ConflictError("恢复预览存在冲突，请先处理章节来源变化")
    if (
        args.expected_preview_hash
        and args.expected_preview_hash != preview["restore_preview_hash"]
    ):
        raise ConflictError("恢复预览已变化，请重新准备")
    result = await restore_chapter_order(
        db,
        novel_id,
        str(args.receipt_id),
        request=ChapterOrderRestoreConfirmedRequest(
            expected_preview_hash=preview["restore_preview_hash"],
            confirmed=True,
        ),
    )
    return result.model_dump(mode="json")


async def _history_read(db, novel_id, args, *, context=None):
    await _require_whole_novel_scope(db, novel_id, context)
    result = await list_chapter_order_history(db, novel_id, limit=args.limit)
    return result.model_dump(mode="json")


OPERATIONS_SPEC = {
    "writing.chapter.reorder": {
        "label": "重排正文中的章节",
        "schema": ChapterOrderOperationArgs,
        "prepare": _reorder_prepare,
        "apply": _reorder_apply,
        "permission": "confirm",
        "op_version": "1",
        "description": (
            "按作者给出的完整章节顺序重排 Writing 草稿。预览会列出全部版本、批注、"
            "Scene 来源和计划锚点影响；发布正文或正史顺序变化按 R3 逐次确认。"
        ),
        "risk_level": "R3",
        "fee_category": "free",
        "reversibility": "writing_chapter_reorder_restore",
        "preconditions": (
            "章节顺序必须覆盖当前全部正文章节且不重复",
            "Story 的精确来源与计划区间不得存在无法迁移的冲突",
        ),
        "produces": ("writing_chapter_order_receipt",),
        "target_type": "writing_chapter_order",
        "ai_available": True,
        "transaction_mode": "single_transaction",
        "trace_rule": {
            "parameter_fields": (
                "chapter_indices",
                "expected_preview_hash",
                "confirmed",
            ),
            "mode": "per_call",
            "parameter_policy": "schema_safe",
        },
    },
    "writing.chapter.reorder.restore": {
        "label": "恢复章节顺序",
        "schema": ChapterOrderRestoreOperationArgs,
        "prepare": _restore_prepare,
        "apply": _restore_apply,
        "permission": "confirm",
        "op_version": "1",
        "description": (
            "在 Writing 正文、批注和 Story 来源仍匹配重排回执时恢复原顺序；"
            "发现作者后续编辑或绑定变化时停止并要求重新核对。"
        ),
        "risk_level": "R3",
        "fee_category": "free",
        "reversibility": "repeat_chapter_order_restore",
        "preconditions": ("存在尚未恢复且来源未漂移的重排回执",),
        "produces": ("writing_chapter_order_restore_receipt",),
        "target_type": "writing_chapter_order",
        "ai_available": True,
        "transaction_mode": "single_transaction",
        "trace_rule": {
            "parameter_fields": (
                "receipt_id",
                "expected_preview_hash",
                "confirmed",
            ),
            "mode": "per_call",
            "parameter_policy": "schema_safe",
        },
    },
    "writing.chapter.order.history.read": {
        "label": "读取章节顺序操作历史",
        "schema": ChapterOrderHistoryArgs,
        "prepare": _history_read,
        "apply": None,
        "permission": "read",
        "op_version": "1",
        "description": "读取当前作品章节重排的预览、执行和恢复回执。",
        "risk_level": "R0",
        "fee_category": "free",
        "reversibility": "not_applicable",
        "preconditions": (),
        "produces": ("writing_chapter_order_history",),
        "target_type": "writing_chapter_order",
        "ai_available": True,
        "transaction_mode": "single_transaction",
        "trace_rule": {
            "parameter_fields": ("limit",),
            "mode": "per_call",
            "parameter_policy": "schema_safe",
        },
    },
}
