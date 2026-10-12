"""P20 proposals and adoption through the original Story workflow."""

import uuid
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select

from core.errors import ConflictError, NotFoundError
from infrastructure.tasks.facade import get_completed_task_payload, get_operation_task
from modules.evidence.contracts import CompileOptions, ContextConfirmationRequest
from modules.evidence.facade import (
    confirm_context,
    prepare_confirmed_ai_action,
    preview_context_confirmation,
)
from modules.story.outline_state.ai_workflow_service import OutlineAIWorkflowService
from modules.story.outline_state.models import OutlineArc
from modules.story.outline_state.p20_context import stable_hash as fingerprint
from modules.story.outline_state.p20_schemas import (
    OutlineLayerGenerateRequest,
    P20Mode,
    P20Target,
)
from modules.story.outline_state.p20_service import P20GenerationService
from modules.story.outline_state.p20_window import (
    window_bounds,
    window_limit_violation,
)
from modules.story.outline_state.story_outline_service import StoryOutlineService


class PlanStructure(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target: P20Target
    mode: P20Mode = "create"
    instruction: str = Field(min_length=1, max_length=20000)
    selected_thread_ids: list[UUID] = Field(default_factory=list, max_length=100)
    selected_arc_ids: list[UUID] = Field(default_factory=list, max_length=100)
    selected_scene_ids: list[UUID] = Field(default_factory=list, max_length=100)
    start_chapter: int | None = Field(
        default=None,
        ge=1,
        le=2147483647,
        description=(
            "滚动规划窗口的起始章；只传起始章时按当前层默认窗口宽度补足结束章"
            "（篇章/剧情线默认 3 章，Scene 默认 1 章）"
        ),
    )
    end_chapter: int | None = Field(
        default=None,
        ge=1,
        le=2147483647,
        description=(
            "滚动规划窗口的结束章；篇章/剧情线最多覆盖 5 章，Scene 只覆盖紧邻的 1-2 章"
        ),
    )

    @model_validator(mode="after")
    def valid_selection(self):
        selected = {
            "plot_thread": self.selected_thread_ids,
            "outline_arc": self.selected_arc_ids,
            "planned_scene": self.selected_scene_ids,
        }[self.target]
        if self.mode == "revise" and not selected:
            raise ValueError("修订需指定原结构对象")
        if self.end_chapter is not None and self.start_chapter is None:
            raise ValueError("章节窗口需要同时给出起始章")
        if (
            self.start_chapter
            and self.end_chapter
            and self.end_chapter < self.start_chapter
        ):
            raise ValueError("结束章节不能早于开始章节")
        if self.start_chapter is not None:
            bounds = window_bounds(self.target, self.start_chapter)
            assert bounds is not None
            if self.end_chapter is None:
                self.end_chapter = bounds[1]
            violation = window_limit_violation(
                self.target, self.start_chapter, self.end_chapter
            )
            if violation:
                raise ValueError(violation)
        return self


class AdoptStructure(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_id: UUID
    proposal_refs: list[str] = Field(min_length=1, max_length=100)
    draft_structure: dict | None = None
    confirmation_fingerprint: str | None = None


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


async def _resolve_window_args(
    db,
    novel_id,
    args: PlanStructure,
) -> tuple[PlanStructure, dict | None]:
    """滚动推进的层内改写：已有已采用篇章覆盖该窗口时改为修订建议。

    只对篇章层的窗口新建请求生效；覆盖篇章取跨度最小者（更具体），
    并把修订目标显式锁定为该篇章。返回 ``(resolved_args, revision_note)``。
    """
    if (
        args.target != "outline_arc"
        or args.mode != "create"
        or args.start_chapter is None
    ):
        return args, None
    covering = (
        await db.scalars(
            select(OutlineArc).where(
                OutlineArc.novel_id == UUID(novel_id),
                OutlineArc.status != "deprecated",
                OutlineArc.start_chapter.is_not(None),
                OutlineArc.end_chapter.is_not(None),
                OutlineArc.start_chapter <= args.start_chapter,
                OutlineArc.end_chapter >= args.end_chapter,
            )
        )
    ).all()
    if not covering:
        return args, None
    arc = min(
        covering,
        key=lambda item: (
            int(item.end_chapter) - int(item.start_chapter),
            int(item.arc_index or 0),
            str(item.id),
        ),
    )
    resolved = args.model_copy(
        update={
            "mode": "revise",
            "selected_arc_ids": [arc.id],
            "selected_thread_ids": [],
            "selected_scene_ids": [],
        }
    )
    note = {
        "arc_id": str(arc.id),
        "title": arc.title,
        "start_chapter": int(arc.start_chapter),
        "end_chapter": int(arc.end_chapter),
    }
    return resolved, note


def _window_identity(
    novel_id: str,
    args: PlanStructure,
    *,
    preview: dict | None = None,
    operation_id: str | None = None,
) -> dict:
    """滚动推进的确定性请求身份：同一（作品、窗口、层）共享一份回执。"""
    return {
        "capability": "story.plan_structure",
        "arguments": args.model_dump(mode="json"),
        "baseline_hash": fingerprint(preview or {}),
        "flow_operation_id": operation_id,
        "novel_id": str(UUID(novel_id)),
        "target": args.target,
        "mode": args.mode,
        "start_chapter": args.start_chapter,
        "end_chapter": args.end_chapter,
        "selected_thread_ids": [str(value) for value in args.selected_thread_ids],
        "selected_arc_ids": [str(value) for value in args.selected_arc_ids],
        "selected_scene_ids": [str(value) for value in args.selected_scene_ids],
    }


def _window_operation_id(identity: dict) -> str:
    """由身份派生确定性 operation_id（借鉴 forecast compute_key；键含窗口）。

    同一运行步骤与同一输入/来源重试返回原任务；新指令、来源或新运行
    派生新身份，不复用旧窗口任务。
    """
    return str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            "story.plan_structure.v1:" + fingerprint(identity),
        )
    )


async def _prepare(db, novel_id, args, *, context=None):
    _require_scope(context)
    resolved, revision_note = await _resolve_window_args(db, novel_id, args)
    current = await StoryOutlineService().get_current(db, novel_id)
    if not current.revision:
        raise ConflictError("请先保存小说总纲，再细化剧情线、篇章或场景")
    parameters = {
        "task": "结构规划",
        "scope": "full",
        "budget_tokens": 0,
        "include_pending_objects": False,
        "user_note": resolved.instruction,
        "chapter_index": resolved.start_chapter,
        "planning_window_end": resolved.end_chapter,
        "thread_ids": [str(value) for value in resolved.selected_thread_ids],
        "arc_id": (
            str(resolved.selected_arc_ids[0]) if resolved.selected_arc_ids else None
        ),
        "scene_id": (
            str(resolved.selected_scene_ids[0]) if resolved.selected_scene_ids else None
        ),
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
        if resolved.start_chapter is not None and (
            fixed.compile_options.get("chapter_index") != resolved.start_chapter
            or fixed.compile_options.get("planning_window_end") != resolved.end_chapter
        ):
            raise ConflictError(
                "原参考资料确认与本次章节窗口不一致，请从结构规划重新确认资料"
            )
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
    effect = "生成可编辑的结构提案与影响说明，尚不采用或改写正文"
    if revision_note:
        effect = (
            f"已有篇章《{revision_note['title']}》覆盖第 "
            f"{revision_note['start_chapter']} 至 {revision_note['end_chapter']} 章；"
            "本次生成该篇章的修订建议，不重复新建。" + effect
        )
    prepared = {
        "title": "准备结构规划建议",
        "outline_revision_id": str(current.revision.id),
        "context_parameters": parameters,
        "context_fingerprint": context_hash,
        "context_confirmation_id": str(confirmation_id) if confirmation_id else None,
        "after": resolved.model_dump(mode="json"),
        "effect": effect,
    }
    if revision_note:
        prepared["revision_of"] = revision_note
    return prepared


async def _submit(db, novel_id, args, preview, *, context=None):
    _require_scope(context)
    if not context.operation_id:
        raise ConflictError("结构规划需要持久化助手执行回执")
    resolved, _note = await _resolve_window_args(db, novel_id, args)
    if resolved.start_chapter is not None:
        # 滚动推进：回执由（作品、窗口、层、模式与目标）确定，与运行解耦。
        identity = _window_identity(
            novel_id, resolved, preview=preview, operation_id=context.operation_id
        )
        operation_id = _window_operation_id(identity)
    else:
        identity = {
            "capability": "story.plan_structure",
            "arguments": resolved.model_dump(mode="json"),
            "baseline_hash": fingerprint(preview),
        }
        operation_id = context.operation_id
    existing = await get_operation_task(
        db,
        operation_id=operation_id,
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
                ContextConfirmationRequest(
                    novel_id=novel_id,
                    action="outline.generate",
                    **preview["context_parameters"],
                    expected_context_fingerprint=preview["context_fingerprint"],
                ),
            )
            confirmation_id = confirmation.id
        request = OutlineLayerGenerateRequest(
            novel_id=novel_id,
            context_confirmation_id=confirmation_id,
            operation_id=uuid.UUID(operation_id),
            rolling_window=resolved.start_chapter is not None,
            **resolved.model_dump(mode="json"),
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
                "window_validation",
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
    field = {"plot_thread": "threads", "outline_arc": "arcs", "planned_scene": "scenes"}[
        task.result["target"]
    ]
    edited = args.draft_structure or {
        **result["draft_structure"],
        field: [
            item
            for item in result["draft_structure"].get(field, [])
            if item["proposal_ref"] in args.proposal_refs
        ],
    }
    if [item["proposal_ref"] for item in edited.get(field, [])] != args.proposal_refs:
        raise ConflictError("采用内容与选择不一致")
    selection = await OutlineAIWorkflowService().prepare_structure_adoption(
        db,
        novel_id=novel_id,
        confirmation_id=task.context_confirmation_id,
        source_task_id=str(args.task_id),
        draft_structure=edited,
    )
    if (
        args.confirmation_fingerprint
        and args.confirmation_fingerprint != selection["confirmation_fingerprint"]
    ):
        raise ConflictError("采用选择或来源已变化，请重新确认")
    return {
        **selection,
        "target_key": "story:structure_package",
        "title": "采用结构规划",
        "source_fingerprint": task.result["context_fingerprint"],
        "context_confirmation_id": task.context_confirmation_id,
        "after": edited,
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
        confirmation_fingerprint=preview["confirmation_fingerprint"],
    )
    return {
        "type": "outline_generate",
        "id": str(args.task_id),
        "task_id": str(args.task_id),
        "target_kind": result["target"],
        "label": "已采用结构规划",
        "result": result,
    }


# 纯数据声明（AO-5）：不 import assistant 契约；组合根
# app/assistant_operation_registry 按 AssistantOperation 原构造语义物化。
OPERATIONS_SPEC = {
    "story.plan_structure": {
        "label": "规划剧情线、篇章、场景及伏笔推进",
        "schema": PlanStructure,
        "prepare": _prepare,
        "apply": _submit,
        "permission": "suggest",
        "read_result": _read_result,
        # rev3（BR-6）：窗口字段语义入 schema 描述并默认补足；同窗口推进
        # 绑定运行步骤与输入/来源。旧冻结运行按 resolve_operations 失败关闭重提。
        "revision": "3",
    },
    "story.adopt_structure": {
        "label": "采用原结构规划包",
        "schema": AdoptStructure,
        "revision": "2",
        "prepare": _adopt_preview,
        "apply": _adopt,
    },
}
