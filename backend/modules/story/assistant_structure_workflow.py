"""P20 proposals and adoption through the original Story workflow."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.errors import ConflictError, NotFoundError
from infrastructure.tasks.facade import get_completed_task_payload, get_operation_task
from modules.assistant.contracts import AssistantOperation
from modules.evidence.contracts import CompileOptions
from modules.evidence.facade import (
    confirm_context,
    prepare_confirmed_ai_action,
    preview_context_confirmation,
)
from modules.story.outline_state.ai_workflow_service import OutlineAIWorkflowService
from modules.story.outline_state.p20_context import stable_hash as fingerprint
from modules.story.outline_state.p20_schemas import (
    OutlineLayerGenerateRequest,
    P20Mode,
    P20Target,
)
from modules.story.outline_state.p20_service import P20GenerationService
from modules.story.outline_state.story_outline_service import StoryOutlineService


class PlanStructure(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target: P20Target
    mode: P20Mode = "create"
    instruction: str = Field(min_length=1, max_length=20000)
    selected_thread_ids: list[UUID] = Field(default_factory=list, max_length=100)
    selected_arc_ids: list[UUID] = Field(default_factory=list, max_length=100)
    selected_scene_ids: list[UUID] = Field(default_factory=list, max_length=100)
    start_chapter: int | None = Field(default=None, ge=1, le=2147483647)
    end_chapter: int | None = Field(default=None, ge=1, le=2147483647)

    @model_validator(mode="after")
    def valid_selection(self):
        selected = {
            "plot_thread": self.selected_thread_ids,
            "outline_arc": self.selected_arc_ids,
            "planned_scene": self.selected_scene_ids,
        }[self.target]
        if self.mode == "revise" and not selected:
            raise ValueError("修订需指定原结构对象")
        if (
            self.start_chapter
            and self.end_chapter
            and self.end_chapter < self.start_chapter
        ):
            raise ValueError("结束章节不能早于开始章节")
        return self


class AdoptStructure(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_id: UUID


def _require_scope(context):
    if (
        context is None
        or context.work.excluded_targets
        or (
            context.work.scope == "current"
            and (context.work.chapter_index or context.work.scene_id)
        )
    ):
        raise ConflictError(
            "整层结构规划需要完整结构范围，请在结构工作台确认资料；不会扩大当前范围"
        )
    if (
        context.work.context_confirmation_id
        and context.work.context_confirmation_action != "outline.generate"
    ):
        raise ConflictError("当前确认用于另一项工作，请从结构规划的原参考资料继续")


async def _prepare(db, novel_id, args, *, context=None):
    _require_scope(context)
    current = await StoryOutlineService().get_current(db, novel_id)
    if not current.revision:
        raise ConflictError("请先保存小说总纲，再细化剧情线、篇章或场景")
    parameters = {
        "task": "结构规划",
        "scope": "full",
        "budget_tokens": 0,
        "include_pending_objects": False,
        "user_note": args.instruction,
        "chapter_index": args.start_chapter,
        "thread_ids": [str(value) for value in args.selected_thread_ids],
        "arc_id": str(args.selected_arc_ids[0]) if args.selected_arc_ids else None,
        "scene_id": str(args.selected_scene_ids[0]) if args.selected_scene_ids else None,
    }
    confirmation_id = context.work.context_confirmation_id
    if confirmation_id:
        fixed = await prepare_confirmed_ai_action(
            db,
            novel_id=novel_id,
            action="outline.generate",
            confirmation_id=str(confirmation_id),
        )
        if fixed.compile_options.get("budget_tokens") != 0 or any(
            fixed.confirmation.excluded_asset_ids.values()
        ):
            raise ConflictError("原结构资料有排除或裁剪，请从原结构工作台核对后继续")
        context_hash = fixed.confirmation.context_fingerprint
    else:
        material = await preview_context_confirmation(
            db,
            CompileOptions(
                novel_id=novel_id, consumer_action="outline.generate", **parameters
            ),
        )
        if material["blockers"]:
            raise ConflictError("结构资料尚不能完整物化，请在结构工作台处理提示")
        context_hash = material["context_fingerprint"]
    return {
        "title": "准备结构规划建议",
        "outline_revision_id": str(current.revision.id),
        "context_parameters": parameters,
        "context_fingerprint": context_hash,
        "context_confirmation_id": str(confirmation_id) if confirmation_id else None,
        "after": args.model_dump(mode="json"),
        "effect": "生成可编辑的结构提案与影响说明，尚不采用或改写正文",
    }


async def _submit(db, novel_id, args, preview, *, context=None):
    _require_scope(context)
    identity = {
        "capability": "story.plan_structure",
        "arguments": args.model_dump(mode="json"),
        "baseline_hash": fingerprint(preview),
    }
    if not context.operation_id:
        raise ConflictError("结构规划需要持久化助手执行回执")
    existing = await get_operation_task(
        db,
        operation_id=context.operation_id,
        task_type="outline_generate",
        novel_id=novel_id,
        request_payload=identity,
    )
    if existing:
        task_id = existing.task_id
    else:
        if await _prepare(db, novel_id, args, context=context) != preview:
            raise ConflictError("规划资料已变化，请重新查看范围")
        confirmation_id = preview["context_confirmation_id"]
        if not confirmation_id:
            confirmation = await confirm_context(
                db,
                novel_id=novel_id,
                action="outline.generate",
                **preview["context_parameters"],
                expected_context_fingerprint=preview["context_fingerprint"],
            )
            confirmation_id = confirmation.id
        request = OutlineLayerGenerateRequest(
            novel_id=novel_id,
            context_confirmation_id=confirmation_id,
            operation_id=context.operation_id,
            **args.model_dump(mode="json"),
        )
        submitted = await OutlineAIWorkflowService().submit_layer_generation(
            db,
            request,
            llm_snapshot=context.llm_snapshot,
            internal_meta=context.internal_meta,
            operation_payload=identity,
        )
        task_id = submitted.task_id
    return {
        "type": "outline_generate",
        "id": task_id,
        "task_id": task_id,
        "task_type": "outline_generate",
        "label": "结构规划提案",
        "target_kind": args.target,
    }


async def _read_result(db, novel_id, reference):
    task = await get_completed_task_payload(
        db, task_id=reference["task_id"], task_type="outline_generate", novel_id=novel_id
    )
    if task is None:
        return {
            "status": "incomplete",
            "omissions": ["结构提案尚未完成，可查看原任务回执"],
        }
    result = task.result
    if result.get("apply_status") != "applied":
        fresh = await P20GenerationService().prepare(
            db, OutlineLayerGenerateRequest.model_validate(result["_request"])
        )
        if fresh.source_fingerprint != result.get("context_fingerprint"):
            return {"status": "stale", "omissions": ["结构或参考资料已变化，请重新规划"]}
    return {
        "status": "completed",
        "authority": "未采用的规划不代表故事已经发生",
        **{
            key: result[key]
            for key in (
                "draft_structure",
                "requires_apply",
                "apply_status",
                "applied_result",
            )
            if key in result
        },
        "requires_apply": bool(
            result.get("requires_apply")
            and result.get("draft_structure", {}).get("result") == "proposed"
        ),
    }


async def _adopt_preview(db, novel_id, args, *, context=None):
    _require_scope(context)
    task = await get_completed_task_payload(
        db, task_id=str(args.task_id), task_type="outline_generate", novel_id=novel_id
    )
    if task is None or task.result.get("contract_version") != "outline_layer_v2":
        raise NotFoundError("本项目没有这份已完成的结构提案")
    if (
        context.work.context_confirmation_id
        and str(context.work.context_confirmation_id) != task.context_confirmation_id
    ):
        raise ConflictError("采用必须沿用提案原参考资料")
    result = await _read_result(db, novel_id, {"task_id": str(args.task_id)})
    if result["status"] != "completed" or not result.get("requires_apply"):
        raise ConflictError("这份提案不可直接采用，请从原结构工作台查看结果")
    return {
        "target_key": "story:structure_package",
        "title": "采用结构规划",
        "source_fingerprint": task.result["context_fingerprint"],
        "context_confirmation_id": task.context_confirmation_id,
        "after": result["draft_structure"],
        "effect": "按原结构采用包保存所列内容，保留原版本与正文映射；不改写正文",
    }


async def _adopt(db, novel_id, args, preview, *, context=None):
    if await _adopt_preview(db, novel_id, args, context=context) != preview:
        raise ConflictError("结构提案或采用依据已变化")
    result = await OutlineAIWorkflowService().apply_structure_preview(
        db,
        novel_id=novel_id,
        confirmation_id=preview["context_confirmation_id"],
        source_task_id=str(args.task_id),
        draft_structure=preview["after"],
        confirmed=True,
    )
    return {
        "type": "outline_generate",
        "id": str(args.task_id),
        "task_id": str(args.task_id),
        "target_kind": result["target"],
        "label": "已采用结构规划",
        "result": result,
    }


OPERATIONS = {
    "story.plan_structure": AssistantOperation(
        "规划剧情线、篇章、场景及伏笔推进",
        PlanStructure,
        _prepare,
        _submit,
        permission="suggest",
        read_result=_read_result,
    ),
    "story.adopt_structure": AssistantOperation(
        "采用原结构规划包", AdoptStructure, _adopt_preview, _adopt
    ),
}
