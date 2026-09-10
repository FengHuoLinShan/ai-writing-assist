"""Writing-owned, confirmed range replacements; original drafts stay intact."""

from __future__ import annotations

import hashlib
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from core.errors import ConflictError, NotFoundError, ValidationError
from modules.assistant.contracts import AssistantOperation
from modules.writing.facade import (
    get_draft,
    get_latest_draft_for_chapter,
    lock_chapter_versions_for_revalidation,
)


class Replacement(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    original: str = Field(max_length=30000)
    replacement: str = Field(max_length=30000)


class ReviseChapter(BaseModel):
    model_config = ConfigDict(extra="forbid")
    draft_id: UUID
    source_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    replacements: list[Replacement] = Field(min_length=1, max_length=20)


class ReviewChapters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    draft_ids: list[UUID] = Field(min_length=1, max_length=200)


class NewChapter(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=500)
    content: str = Field(default="", max_length=100000)


async def _new_preview(db, novel_id, args, *, context=None):
    from modules.writing.facade import list_chapter_indices

    chapters = await list_chapter_indices(db, novel_id)
    return {
        "target_key": "writing:append",
        "title": args.title,
        "chapter_index": max(chapters, default=0) + 1,
        "after": args.model_dump(),
        "effect": "在末尾新建可编辑工作稿；尚未发布，也没有签署人物知识边界检查",
    }


async def _new_apply(db, novel_id, args, preview, *, context=None):
    from modules.project.facade import require_active_project_exclusive
    from modules.writing.schemas import WritingDraftCreate
    from modules.writing.services import WritingDraftService

    await require_active_project_exclusive(db, novel_id)
    if await _new_preview(db, novel_id, args, context=context) != preview:
        raise ConflictError("章节顺序已变化，请重新查看新章方案")
    draft = await WritingDraftService().create_draft_contract(
        db,
        WritingDraftCreate(
            novel_id=novel_id,
            chapter_index=preview["chapter_index"],
            title=args.title,
            content=args.content,
            provenance_json={
                "source": "assistant_revision",
                "context_origin": "manual",
                "workflow": "assistant.new_chapter.v1",
                "assistant_run_id": context.run_id,
                "approved_by": context.owner_id,
                "review_required": True,
                "editable": True,
                "reversible": True,
            },
        ),
    )
    return {
        "type": "writing_draft",
        "id": draft.id,
        "chapter_index": draft.chapter_index,
        "label": "已保存新章工作稿",
    }


async def _review_prepare(db, novel_id, args, *, context=None, manual_world_scope=None):
    if (
        manual_world_scope is None
        and context
        and (context.work.excluded_targets or context.work.context_confirmation_id)
    ):
        raise ConflictError(
            "独立审稿使用正文生成时的原始参考资料；请在该正文的审稿入口核对范围"
        )
    from modules.writing.semantic_review import (
        WritingSemanticWorkflowService,
        _review_set_fingerprint,
    )

    targets, adjacent = await WritingSemanticWorkflowService()._freeze_review_set(
        db,
        novel_id=novel_id,
        draft_ids=[str(value) for value in args.draft_ids],
        manual_world_scope=manual_world_scope,
    )
    return {
        "title": "独立审查正文",
        "target": {
            "type": "writing_draft",
            "id": targets[0]["draft_id"],
            "chapter_index": targets[0]["chapter_index"],
        },
        "source_hash": _review_set_fingerprint([*targets, *adjacent]),
        "after": f"检查 {len(targets)} 份正文及其关联场景和前后文",
        "effect": "生成可追溯的独立审查结果，不自动修改正文",
        **(
            {"world_review_scope": manual_world_scope.model_dump(mode="json")}
            if manual_world_scope is not None
            else {}
        ),
    }


async def _review_apply(
    db, novel_id, args, preview, *, context=None, manual_world_scope=None
):
    from modules.writing.semantic_review import WritingSemanticWorkflowService

    if (
        await _review_prepare(
            db, novel_id, args, context=context, manual_world_scope=manual_world_scope
        )
        != preview
    ):
        raise ConflictError("审查资料已变化", code="assistant_source_stale")
    result = await WritingSemanticWorkflowService().submit_review(
        db,
        novel_id=novel_id,
        draft_ids=[str(value) for value in args.draft_ids],
        operation_id=context.operation_id if context else None,
        internal_meta=context.internal_meta if context else None,
        llm_execution_snapshot=context.llm_snapshot if context else None,
        manual_world_scope=manual_world_scope,
    )
    return {
        "type": "writing_review",
        "id": result["task_id"],
        "task_id": result["task_id"],
        "task_type": "writing_semantic_review",
        "target": preview["target"],
        "label": "已开始独立审查，结果生成后可继续处理",
    }


def _world_scope(context):
    from modules.writing.schemas import WritingWorldReviewScope

    if context is None or context.work.context_confirmation_id:
        raise ConflictError("世界约束审查需要当前明确的资料范围；AI 正文请使用原资料审稿")
    return WritingWorldReviewScope(
        cutoff_chapter=context.work.chapter_index
        if context.work.scope == "current"
        else None,
        scene_id=context.work.scene_id,
        excluded_targets=context.work.excluded_targets,
    )


async def _world_review_prepare(db, novel_id, args, *, context=None):
    return await _review_prepare(
        db, novel_id, args, context=context, manual_world_scope=_world_scope(context)
    )


async def _world_review_apply(db, novel_id, args, preview, *, context=None):
    return await _review_apply(
        db,
        novel_id,
        args,
        preview,
        context=context,
        manual_world_scope=_world_scope(context),
    )


async def _review_result(db, novel_id, reference):
    from infrastructure.tasks.facade import get_completed_task_payload

    payload = await get_completed_task_payload(
        db,
        task_id=reference["task_id"],
        task_type="writing_semantic_review",
        novel_id=novel_id,
    )
    if payload is None:
        return {
            "status": "incomplete",
            "findings": [],
            "not_checked": ["正文复核没有完整完成，不能据此出具通过结论"],
        }
    result = payload.result
    import json

    from modules.evidence.contracts import VisibilityContextContract
    from modules.evidence.facade import inspect_novel_target

    for coverage in (result.get("coverage", {}).get("world_constraints") or {}).values():
        for source in coverage.get("sources", []):
            inspected = await inspect_novel_target(
                db,
                novel_id=novel_id,
                target_ref=source["target_ref"],
                content_mode="working",
                visibility=VisibilityContextContract(
                    mode="author",
                    cutoff_chapter=coverage["chapter_index"],
                    cutoff_scene_id=coverage.get("scene_id"),
                ),
            )
            content = json.dumps(
                inspected.get("item"), ensure_ascii=False, sort_keys=True, default=str
            )
            if (
                not inspected.get("visible")
                or hashlib.sha256(content.encode()).hexdigest() != source["source_hash"]
            ):
                return {
                    "status": "stale",
                    "findings": [],
                    "not_checked": ["审查依赖的世界资料已变化，请重新检查"],
                }
    return {
        "status": "completed",
        **{
            key: value
            for key, value in result.items()
            if key in {"verdict", "coverage", "not_checked", "reviewed_at"}
        },
        "findings": list(result.get("findings") or [])[:30],
    }


async def schedule_proactive_review(db, novel_id, change, internal_meta):
    from modules.writing.schemas import WritingWorldReviewScope
    from modules.writing.semantic_review import (
        WritingSemanticWorkflowService,
        _requires_confirmed_context,
    )

    draft = await get_draft(db, novel_id, change["asset_id"])
    if (
        draft is None
        or draft.status not in {"draft", "published"}
        or not (draft.content or "").strip()
    ):
        return None
    latest = await get_latest_draft_for_chapter(db, novel_id, draft.chapter_index)
    if latest is None or latest.id != draft.id:
        return None
    excluded = (internal_meta.get("_assistant_policy") or {}).get("excluded_targets", [])
    is_candidate = _requires_confirmed_context(draft.provenance_json or {})
    if is_candidate and excluded:
        raise ConflictError("当前排除范围需要在正文审稿入口核对，未扩大后台资料范围")
    result = await WritingSemanticWorkflowService().submit_review(
        db,
        novel_id=novel_id,
        draft_ids=[draft.id],
        internal_meta=internal_meta,
        manual_world_scope=None
        if is_candidate
        else WritingWorldReviewScope(
            cutoff_chapter=draft.chapter_index,
            excluded_targets=excluded,
        ),
    )
    return {
        "task_id": result["task_id"],
        "target": {
            "type": "writing_draft",
            "id": draft.id,
            "chapter_index": draft.chapter_index,
        },
        "label": draft.title or f"第 {draft.chapter_index} 章",
    }


async def _prepare(db, novel_id, args: ReviseChapter, *, context=None):
    from modules.assistant.facade import require_operation_targets

    await require_operation_targets(
        db, novel_id, context, [("writing_draft", args.draft_id)]
    )
    draft = await get_draft(db, novel_id, str(args.draft_id))
    if draft is None:
        raise NotFoundError("正文不存在")
    from modules.writing.semantic_review import (
        WritingSemanticWorkflowService,
        _requires_confirmed_context,
    )

    if _requires_confirmed_context(draft.provenance_json or {}):
        await WritingSemanticWorkflowService()._freeze_draft(
            db, novel_id=novel_id, draft_id=str(args.draft_id), role="target"
        )
    latest = await get_latest_draft_for_chapter(db, novel_id, draft.chapter_index)
    content = draft.content or ""
    if (
        latest is None
        or latest.id != draft.id
        or hashlib.sha256(content.encode()).hexdigest() != args.source_hash
    ):
        raise ConflictError("正文已变化，请重新准备修改", code="assistant_source_stale")
    end = -1
    patches = sorted(args.replacements, key=lambda p: (p.start, p.end))
    for patch in patches:
        if (
            patch.start < end
            or patch.end < patch.start
            or patch.end > len(content)
            or content[patch.start : patch.end] != patch.original
        ):
            raise ValidationError("修改范围重叠、越界或与原文不一致")
        end = patch.end
    revised = content
    for patch in reversed(patches):
        revised = revised[: patch.start] + patch.replacement + revised[patch.end :]
    return {
        "target_key": f"writing:{draft.chapter_index}",
        "title": draft.title or f"第 {draft.chapter_index} 章",
        "chapter_index": draft.chapter_index,
        "source_hash": args.source_hash,
        "before": content,
        "after": revised,
        "effect": "保存为新工作稿，不发布、不覆盖历史版本",
    }


async def _apply(db, novel_id, args, preview, *, context=None):
    from modules.writing.schemas import WritingDraftCreate
    from modules.writing.services import WritingDraftService

    await lock_chapter_versions_for_revalidation(db, novel_id, [preview["chapter_index"]])
    fresh = await _prepare(db, novel_id, args, context=context)
    if fresh != preview:
        raise ConflictError("正文已变化", code="assistant_source_stale")
    original = await get_draft(db, novel_id, str(args.draft_id))
    provenance = dict(original.provenance_json or {})
    context_origin = (
        provenance.get("context_origin") or provenance.get("source") or "manual"
    )
    provenance.pop("independent_review", None)
    provenance.update(
        {
            "source": "assistant_revision",
            "context_origin": context_origin,
            "version_origin": "manual",
            "review_required": True,
            "workflow": "assistant.confirmed_revision.v1",
            "assistant_run_id": context.run_id,
            "approved_by": context.owner_id,
            "base_draft_id": original.id,
            "base_source_hash": args.source_hash,
            "editable": True,
            "reversible": True,
        }
    )
    draft = await WritingDraftService().create_draft_contract(
        db,
        WritingDraftCreate(
            novel_id=novel_id,
            chapter_index=preview["chapter_index"],
            title=preview["title"],
            content=preview["after"],
            provenance_json=provenance,
        ),
    )
    return {
        "type": "writing_draft",
        "id": draft.id,
        "chapter_index": draft.chapter_index,
        "label": "已保存新工作稿",
        "replaces_draft_id": str(args.draft_id),
        "source_hash": draft.content_hash,
    }


OPERATIONS = {
    "writing.review_world": AssistantOperation(
        "核对人工正文与世界设定（不签署人物知识边界）",
        ReviewChapters,
        _world_review_prepare,
        _world_review_apply,
        permission="suggest",
        read_result=_review_result,
    ),
    "writing.new_chapter": AssistantOperation(
        "追加章节工作稿", NewChapter, _new_preview, _new_apply
    ),
    "writing.review": AssistantOperation(
        "独立审查正文",
        ReviewChapters,
        _review_prepare,
        _review_apply,
        permission="suggest",
        read_result=_review_result,
    ),
    "writing.revise": AssistantOperation(
        "按精确范围修订正文", ReviseChapter, _prepare, _apply
    ),
}
