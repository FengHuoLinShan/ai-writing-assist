"""Bind author generation intent to the existing confirmed candidate workflow."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from core.errors import ConflictError
from infrastructure.tasks.facade import get_completed_task_payload, get_operation_task
from modules.assistant.contracts import AssistantOperation
from modules.evidence.contracts import CompileOptions
from modules.evidence.facade import (
    confirm_context,
    prepare_confirmed_ai_action,
    preview_context_confirmation,
)
from modules.writing.facade import get_draft, get_latest_draft_for_chapter
from modules.writing.schemas import WritingGenerateRequest
from modules.writing.semantic_review import _stable_hash
from modules.writing.services import WritingGenerationService


class GenerateCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    chapter_index: int = Field(ge=1, le=2147483647)
    title: str | None = Field(default=None, max_length=500)
    instruction: str | None = Field(default=None, max_length=4000)
    generation_mode: Literal["draft", "continue"] = "draft"


async def _prepare(db, novel_id, args, *, context=None):
    if context is None or context.work.excluded_targets:
        raise ConflictError(
            "请在写作入口沿用排除范围确认资料，再交给助手生成；不会扩大范围"
        )
    work = context.work
    base = None
    if args.generation_mode == "continue":
        base = (
            await get_draft(db, novel_id, str(work.draft_id))
            if work.draft_id
            else await get_latest_draft_for_chapter(db, novel_id, args.chapter_index)
        )
        if (
            base is None
            or base.chapter_index != args.chapter_index
            or base.status not in {"draft", "published"}
        ):
            raise ConflictError("续写需要当前章已采用的工作稿")
    parameters = {
        "task": "生成正文候选",
        "scope": "chapter",
        "chapter_index": args.chapter_index,
        "scene_id": str(work.scene_id) if work.scene_id else None,
        "visible_until_chapter": work.chapter_index if work.scope == "current" else None,
        "visible_until_scene_id": str(work.scene_id)
        if work.scope == "current" and work.scene_id
        else None,
        "budget_tokens": 12000,
        "content_mode": "working",
        "context_mode": "canonical",
        "user_note": args.instruction,
        "include_pending_objects": False,
    }
    confirmation_id = work.context_confirmation_id
    if confirmation_id:
        if work.context_confirmation_action != "writing.generate":
            raise ConflictError("当前资料确认用于另一项工作，请在写作入口确认本章资料")
        fixed = await prepare_confirmed_ai_action(
            db,
            novel_id=novel_id,
            action="writing.generate",
            confirmation_id=str(confirmation_id),
        )
        if (
            fixed.compile_options.get(
                "requested_chapter_index", fixed.compile_options.get("chapter_index")
            )
            != args.chapter_index
        ):
            raise ConflictError("原确认不属于本次目标章节")
        context_hash = fixed.confirmation.context_fingerprint
    else:
        material = await preview_context_confirmation(
            db,
            CompileOptions(
                novel_id=novel_id, consumer_action="writing.generate", **parameters
            ),
        )
        if material["blockers"]:
            raise ConflictError("本章资料需要在写作入口先处理确认提示")
        context_hash = material["context_fingerprint"]
    return {
        "title": "续写正文候选" if base else "生成正文候选",
        "after": args.model_dump(mode="json"),
        "context_parameters": parameters,
        "context_fingerprint": context_hash,
        "context_confirmation_id": str(confirmation_id) if confirmation_id else None,
        "base_draft_id": base.id if base else None,
        "base_source_hash": base.content_hash if base else None,
        "effect": "生成未采用候选，保留原工作稿；审稿和采用继续使用本次原参考资料",
    }


async def _submit(db, novel_id, args, preview, *, context=None):
    if not context or not context.operation_id:
        raise ConflictError("正文生成需要原助手执行回执")
    identity = {
        "capability": "writing.generate_candidate",
        "arguments": args.model_dump(mode="json"),
        "baseline_hash": _stable_hash(preview),
    }
    existing = await get_operation_task(
        db,
        operation_id=context.operation_id,
        task_type="writing_generate",
        novel_id=novel_id,
        request_payload=identity,
    )
    if existing:
        task_id = existing.task_id
    else:
        if await _prepare(db, novel_id, args, context=context) != preview:
            raise ConflictError("生成资料或续写基线已变化")
        confirmation_id = preview["context_confirmation_id"]
        if not confirmation_id:
            confirmation = await confirm_context(
                db,
                novel_id=novel_id,
                action="writing.generate",
                **preview["context_parameters"],
                expected_context_fingerprint=preview["context_fingerprint"],
            )
            confirmation_id = confirmation.id
        result = await WritingGenerationService().submit_generation(
            db,
            WritingGenerateRequest(
                novel_id=novel_id,
                context_confirmation_id=confirmation_id,
                operation_id=context.operation_id,
                base_draft_id=preview["base_draft_id"],
                **args.model_dump(),
            ),
            llm_execution_snapshot=context.llm_snapshot,
            internal_meta=context.internal_meta,
            operation_payload=identity,
        )
        task_id = result["task_id"]
    return {
        "type": "writing_generate",
        "id": task_id,
        "task_id": task_id,
        "task_type": "writing_generate",
        "label": "正文生成候选",
    }


async def _read_result(db, novel_id, reference):
    task = await get_completed_task_payload(
        db, novel_id=novel_id, task_id=reference["task_id"], task_type="writing_generate"
    )
    if task is None:
        return {
            "status": "incomplete",
            "omissions": ["正文候选尚未完整生成，可查看原任务进度"],
        }
    draft = await get_draft(db, novel_id, task.result["draft_id"])
    if draft is None:
        return {"status": "stale", "omissions": ["生成候选已不可访问"]}
    return {
        "status": "completed",
        "candidate": {
            "type": "writing_candidate",
            "id": draft.id,
            "chapter_index": draft.chapter_index,
            "title": draft.title,
            "source_hash": draft.content_hash,
        },
        "authority": "这份正文尚未采用，需核对原参考资料并审稿后决定",
    }


OPERATIONS = {
    "writing.generate_candidate": AssistantOperation(
        "生成或续写正文候选",
        GenerateCandidate,
        _prepare,
        _submit,
        permission="suggest",
        read_result=_read_result,
    ),
}
