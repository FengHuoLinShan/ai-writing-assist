"""Candidate revision/adoption and working-version recovery owned by Writing."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from core.errors import ConflictError, NotFoundError
from infrastructure.tasks.facade import get_completed_task_payload
from modules.assistant.contracts import AssistantOperation
from modules.assistant.facade import require_operation_targets
from modules.evidence.facade import request_chapter_index
from modules.writing.facade import (
    get_draft,
    get_latest_draft_for_chapter,
    lock_chapter_versions_for_revalidation,
)
from modules.writing.schemas import WritingDraftCreate, WritingTargetedRevisionRequest
from modules.writing.semantic_review import (
    WritingSemanticWorkflowService,
    validate_candidate_upstream,
)
from modules.writing.services import WritingDraftService


class SelectDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    draft_id: UUID


class ReviseCandidate(SelectDraft):
    review_task_id: UUID
    finding_ids: list[str] = Field(min_length=1, max_length=100)
    instruction: str | None = Field(default=None, max_length=20000)


async def _revision_preview(db, novel_id, args, *, context=None):
    await require_operation_targets(
        db, novel_id, context, [("writing_draft", args.draft_id)]
    )
    plan = await WritingSemanticWorkflowService().prepare_targeted_revision(
        db,
        novel_id=novel_id,
        draft_id=str(args.draft_id),
        review_task_id=str(args.review_task_id),
        finding_ids=args.finding_ids,
    )
    base = plan["base"]
    if context.work.context_confirmation_id and str(
        context.work.context_confirmation_id
    ) != str(
        (base.provenance_json or {}).get("context_confirmation_id")
        or (base.provenance_json or {}).get("source_confirmation_id")
    ):
        raise ConflictError("返修需使用候选原参考资料，不能替换为另一份确认")
    return {
        "title": "按审稿问题返修候选",
        "target_key": f"writing_revision:{base.id}",
        "source_hash": base.content_hash,
        "context_fingerprint": plan["expected_context_fingerprint"],
        "before": [item["message"] for item in plan["selected"]],
        "after": args.instruction or "只修复所选问题，并保留指定内容",
        "chapter_index": base.chapter_index,
        "effect": "另存返修候选；原稿与范围外正文保持，返修后仍需独立审稿才能采用",
    }


async def _revise(db, novel_id, args, preview, *, context=None):
    if await _revision_preview(db, novel_id, args, context=context) != preview:
        raise ConflictError("正文或审稿依据已变化")
    result = await WritingSemanticWorkflowService().submit_targeted_revision(
        db,
        WritingTargetedRevisionRequest(
            novel_id=novel_id,
            operation_id=context.operation_id,
            **args.model_dump(mode="json"),
        ),
        internal_meta=context.internal_meta,
        llm_execution_snapshot=context.llm_snapshot,
    )
    return {
        "type": "writing_targeted_revision",
        "id": result["task_id"],
        "task_id": result["task_id"],
        "task_type": "writing_targeted_revision",
        "label": "定向返修候选",
    }


async def _revision_result(db, novel_id, reference):
    task = await get_completed_task_payload(
        db,
        novel_id=novel_id,
        task_id=reference["task_id"],
        task_type="writing_targeted_revision",
    )
    if task is None:
        return {
            "status": "incomplete",
            "omissions": ["返修尚未完整完成，请查看原任务回执"],
        }
    draft = await get_draft(db, novel_id, str(task.result["draft_id"]))
    if draft is None:
        return {"status": "stale", "omissions": ["返修候选已不可访问"]}
    return {
        "status": "completed",
        "candidate": {
            "type": "writing_candidate",
            "id": draft.id,
            "title": draft.title,
            "chapter_index": draft.chapter_index,
            "source_hash": draft.content_hash,
        },
        "authority": "返修完成不代表通过审稿，原候选未被覆盖",
    }


async def _version_preview(db, novel_id, args, *, context=None, adopt=False):
    await require_operation_targets(
        db, novel_id, context, [("writing_draft", args.draft_id)]
    )
    draft = await get_draft(db, novel_id, str(args.draft_id))
    if draft is None:
        raise NotFoundError("正文版本不存在")
    if adopt:
        if draft.status != "candidate":
            raise ConflictError("此版本不是待采用候选")
        if context.work.context_confirmation_id and str(
            context.work.context_confirmation_id
        ) != str(
            (draft.provenance_json or {}).get("context_confirmation_id")
            or (draft.provenance_json or {}).get("source_confirmation_id")
        ):
            raise ConflictError("采用需沿用候选原参考资料")
        await validate_candidate_upstream(db, draft)
    elif draft.status not in {"draft", "published"}:
        raise ConflictError("只能从已采用的历史正文继续写；候选需使用专门的采用入口")
    current = await get_latest_draft_for_chapter(db, novel_id, draft.chapter_index)
    return {
        "target_key": f"writing:{draft.chapter_index}",
        "title": "采用候选" if adopt else "从历史版本继续写",
        "chapter_index": draft.chapter_index,
        "draft_title": draft.title,
        "source_hash": draft.content_hash,
        "working_base": {"draft_id": current.id, "source_hash": current.content_hash}
        if current
        else None,
        "before": current.content if current else "",
        "after": draft.content,
        "effect": "保存为新的工作稿，保留原版本；不会直接发布",
    }


async def _adopt_preview(db, novel_id, args, *, context=None):
    return await _version_preview(db, novel_id, args, context=context, adopt=True)


async def _apply_version(db, novel_id, args, preview, *, context, adopt):
    await lock_chapter_versions_for_revalidation(db, novel_id, [preview["chapter_index"]])
    if (
        await _version_preview(db, novel_id, args, context=context, adopt=adopt)
        != preview
    ):
        raise ConflictError("当前工作稿、候选或历史版本已变化，请重新准备采用方案")
    service = WritingDraftService()
    if adopt:
        draft = await service.adopt_candidate_to_working_contract(
            db, str(args.draft_id), novel_id, adopted_by=context.owner_id
        )
    else:
        source = await get_draft(db, novel_id, str(args.draft_id))
        provenance = dict(source.provenance_json or {})
        provenance.update(
            {
                "context_origin": provenance.get("context_origin")
                or provenance.get("source")
                or "manual",
                "source": "assistant_revision",
                "workflow": "assistant.restore.v1",
                "version_origin": "manual",
                "restored_from_draft_id": source.id,
                "restored_from_hash": source.content_hash,
                "assistant_run_id": context.run_id,
                "approved_by": context.owner_id,
                "independent_review": None,
                "review_required": True,
            }
        )
        draft = await service.create_draft_contract(
            db,
            WritingDraftCreate(
                novel_id=novel_id,
                chapter_index=source.chapter_index,
                title=source.title,
                content=source.content,
                provenance_json=provenance,
            ),
        )
    await request_chapter_index(db, novel_id, draft.chapter_index, content_mode="working")
    return {
        "type": "writing_draft",
        "id": draft.id,
        "chapter_index": draft.chapter_index,
        "source_hash": draft.content_hash,
        "replaces_draft_id": str(context.work.draft_id)
        if str(context.work.draft_id)
        in {str(args.draft_id), str((preview.get("working_base") or {}).get("draft_id"))}
        else None,
        "label": "已保存为新的工作稿",
    }


async def _adopt(db, novel_id, args, preview, *, context=None):
    return await _apply_version(db, novel_id, args, preview, context=context, adopt=True)


async def _restore(db, novel_id, args, preview, *, context=None):
    return await _apply_version(db, novel_id, args, preview, context=context, adopt=False)


OPERATIONS = {
    "writing.targeted_revision": AssistantOperation(
        "按已选审稿问题返修",
        ReviseCandidate,
        _revision_preview,
        _revise,
        permission="suggest",
        read_result=_revision_result,
    ),
    "writing.adopt_candidate": AssistantOperation(
        "采用经过审查的正文候选", SelectDraft, _adopt_preview, _adopt
    ),
    "writing.restore_version": AssistantOperation(
        "从已采用的历史版本继续写", SelectDraft, _version_preview, _restore
    ),
}
