"""Assistant operations that launch source-bound Story preview generation."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from core.container import get
from core.errors import ConflictError
from core.service_keys import ASSISTANT_REQUIRE_OPERATION_TARGETS
from infrastructure.tasks.facade import get_completed_task_payload
from modules.evidence.contracts import CompileOptions, ContextConfirmationRequest
from modules.evidence.facade import (
    confirm_context,
    prepare_confirmed_ai_action,
    preview_context_confirmation,
)
from modules.story.facade import (
    STORY_CARD_TASK,
    STORY_CHARACTER_CARD_ACTION,
    STORY_REACTION_ACTION,
    STORY_REACTION_TASK,
    enqueue_confirmed_story_task,
)
from modules.story.schemas import StoryCardTaskRequest, StoryTaskRequest


class GenerateCharacterCard(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scene_id: UUID
    character_id: UUID
    additional_notes: str | None = Field(default=None, max_length=4000)


class GenerateCharacterReactions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scene_id: UUID
    character_ids: list[UUID] = Field(min_length=1, max_length=24)
    additional_notes: str | None = Field(default=None, max_length=4000)


def _execution_snapshot(context):
    snapshot = getattr(context, "llm_snapshot", None)
    if snapshot is None:
        raise ConflictError("Story 生成需要沿用当前助手运行的模型快照")
    return snapshot


async def _prepare_generation(
    db,
    novel_id,
    args,
    *,
    context,
    action: str,
    task: str,
    character_ids: list[str],
    viewpoint_character_id: str | None,
):
    if (
        context is None
        or not getattr(context, "run_id", None)
        or not getattr(context, "owner_id", None)
    ):
        raise ConflictError("Story 生成需要当前助手运行的作者范围")
    work = getattr(context, "work", None)
    if work is None:
        raise ConflictError("Story 生成需要当前作者工作范围")
    scene_id = str(args.scene_id)
    selected_scene = str(getattr(work, "scene_id", "") or "")
    if selected_scene and selected_scene != scene_id:
        raise ConflictError("目标场景与当前作者工作范围不一致")
    confirmation_id = getattr(work, "context_confirmation_id", None)
    if getattr(work, "excluded_targets", None) and not confirmation_id:
        raise ConflictError("请先在写作入口确认排除范围，不会扩大资料范围")

    required_targets = [("outline_scene", UUID(scene_id))]
    required_targets.extend(("core_entity", UUID(item)) for item in character_ids)
    await get(ASSISTANT_REQUIRE_OPERATION_TARGETS)(
        db,
        novel_id,
        context,
        required_targets,
        aggregate=True,
    )

    purpose = (
        "story_character_card"
        if action == STORY_CHARACTER_CARD_ACTION
        else "story_character_reaction"
    )
    parameters = {
        "task": task,
        "scope": "scene",
        "scene_id": scene_id,
        "budget_tokens": 6000,
        "character_ids": character_ids,
        "reveal_mode": "character" if viewpoint_character_id else "author_safe",
        "viewpoint_character_id": viewpoint_character_id,
        "visible_until_scene_id": scene_id,
        "consumer_action": action,
        "retrieval_purpose": purpose,
        "context_mode": "canonical",
        "content_mode": "canonical",
        "include_pending_objects": False,
    }
    if confirmation_id:
        if getattr(work, "context_confirmation_action", None) != action:
            raise ConflictError("当前资料确认用于另一项工作，请重新确认本场景")
        fixed = await prepare_confirmed_ai_action(
            db,
            novel_id=novel_id,
            action=action,
            confirmation_id=str(confirmation_id),
            consumer_action=action,
        )
        fixed_options = dict(fixed.compile_options or {})
        from modules.story.task_submission import (
            validate_story_generation_confirmation,
        )

        validate_story_generation_confirmation(
            fixed_options,
            action=action,
            scene_id=scene_id,
            character_ids=character_ids,
        )
        if str(fixed_options.get("scene_id") or "") != scene_id:
            raise ConflictError("原资料确认不属于本场景")
        fixed_characters = {
            str(value) for value in fixed_options.get("character_ids") or []
        }
        if not set(character_ids).issubset(fixed_characters):
            raise ConflictError("原资料确认没有覆盖本次目标人物")
        if viewpoint_character_id and (
            fixed_options.get("reveal_mode") != "character"
            or str(fixed_options.get("viewpoint_character_id") or "")
            != viewpoint_character_id
        ):
            raise ConflictError("人物卡需要该 POV 人物的专属资料确认")
        return {
            "title": task,
            "scene_id": scene_id,
            "character_ids": character_ids,
            "context_confirmation_id": str(confirmation_id),
            "context_fingerprint": fixed.confirmation.context_fingerprint,
            "context_parameters": fixed_options,
            "effect": "生成可编辑的人物预览，不直接保存或采用",
        }

    if getattr(work, "excluded_targets", None):
        raise ConflictError("当前排除项未绑定到可复用的资料确认")
    material = await preview_context_confirmation(
        db,
        CompileOptions(novel_id=novel_id, **parameters),
    )
    if material.get("blockers"):
        raise ConflictError("本场景资料需要先处理确认提示")
    return {
        "title": task,
        "scene_id": scene_id,
        "character_ids": character_ids,
        "context_confirmation_id": None,
        "context_fingerprint": material["context_fingerprint"],
        "context_parameters": parameters,
        "effect": "生成可编辑的人物预览，不直接保存或采用",
    }


async def _prepare_card(db, novel_id, args, *, context=None):
    return await _prepare_generation(
        db,
        novel_id,
        args,
        context=context,
        action=STORY_CHARACTER_CARD_ACTION,
        task="生成人物卡预览",
        character_ids=[str(args.character_id)],
        viewpoint_character_id=str(args.character_id),
    )


async def _prepare_reactions(db, novel_id, args, *, context=None):
    character_ids = [str(item) for item in args.character_ids]
    if len(set(character_ids)) != len(character_ids):
        raise ValueError("character_ids must be unique")
    return await _prepare_generation(
        db,
        novel_id,
        args,
        context=context,
        action=STORY_REACTION_ACTION,
        task="提出人物反应预览",
        character_ids=character_ids,
        viewpoint_character_id=None,
    )


async def _submit_preview(
    db, novel_id, args, preview, *, context, prepare, action, task_type
):
    internal_meta = getattr(context, "internal_meta", None) or {}
    if (
        not getattr(context, "operation_id", None)
        or internal_meta.get("_execution_mode") != "inline_only"
        or not internal_meta.get("_parent_task_id")
    ):
        raise ConflictError("Story 生成只能在当前助手任务预算内执行")
    snapshot = _execution_snapshot(context)
    if await prepare(db, novel_id, args, context=context) != preview:
        raise ConflictError("场景或资料确认已变化，请重新查看预览")
    confirmation_id = preview["context_confirmation_id"]
    if not confirmation_id:
        confirmation_parameters = dict(preview["context_parameters"])
        confirmation_parameters.pop("consumer_action", None)
        confirmation = await confirm_context(
            db,
            ContextConfirmationRequest(
                novel_id=novel_id,
                action=action,
                **confirmation_parameters,
                expected_context_fingerprint=preview["context_fingerprint"],
            ),
        )
        confirmation_id = confirmation.id

    operation_id = UUID(str(context.operation_id))
    if task_type == STORY_CARD_TASK:
        request = StoryCardTaskRequest(
            novel_id=novel_id,
            scene_id=preview["scene_id"],
            character_id=preview["character_ids"][0],
            context_confirmation_id=str(confirmation_id),
            operation_id=operation_id,
            additional_notes=args.additional_notes,
            confirmed=True,
        )
    else:
        request = StoryTaskRequest(
            novel_id=novel_id,
            scene_id=preview["scene_id"],
            character_ids=preview["character_ids"],
            context_confirmation_id=str(confirmation_id),
            operation_id=operation_id,
            additional_notes=args.additional_notes,
            confirmed=True,
        )
    receipt = await enqueue_confirmed_story_task(
        db,
        request,
        action=action,
        task_type=task_type,
        extra_meta=internal_meta,
        llm_execution_snapshot=snapshot,
    )
    return {
        "task_id": str(receipt.task_id),
        "task_type": task_type,
        "status": receipt.status,
        "target": {"type": "outline_scene", "id": preview["scene_id"]},
    }


async def _submit_card(db, novel_id, args, preview, *, context=None):
    return await _submit_preview(
        db,
        novel_id,
        args,
        preview,
        context=context,
        prepare=_prepare_card,
        action=STORY_CHARACTER_CARD_ACTION,
        task_type=STORY_CARD_TASK,
    )


async def _submit_reactions(db, novel_id, args, preview, *, context=None):
    return await _submit_preview(
        db,
        novel_id,
        args,
        preview,
        context=context,
        prepare=_prepare_reactions,
        action=STORY_REACTION_ACTION,
        task_type=STORY_REACTION_TASK,
    )


async def _read_preview_result(db, novel_id, reference, *, task_type, label):
    task = await get_completed_task_payload(
        db,
        novel_id=novel_id,
        task_id=reference["task_id"],
        task_type=task_type,
    )
    if task is None:
        return {
            "status": "incomplete",
            "omissions": [f"{label}尚未完成；请查看原任务进度"],
        }
    result = task.result or {}
    return {
        "status": "completed",
        "preview": result.get("preview"),
        "context_snapshot_id": result.get("context_snapshot_id"),
        "preview_only": True,
        "authority": "这是带来源的候选预览；未写入 Story 或 World 正史",
    }


async def _read_card_result(db, novel_id, reference):
    return await _read_preview_result(
        db,
        novel_id,
        reference,
        task_type=STORY_CARD_TASK,
        label="人物卡预览",
    )


async def _read_reaction_result(db, novel_id, reference):
    return await _read_preview_result(
        db,
        novel_id,
        reference,
        task_type=STORY_REACTION_TASK,
        label="人物反应预览",
    )


def _metadata(*, description, produces, target_type, trace_fields, op_version="1"):
    return {
        "op_version": op_version,
        "description": description,
        "risk_level": "R1",
        "fee_category": "possible_model_charge",
        "reversibility": "preview_only",
        "preconditions": (
            "active_author_project",
            "scene_in_project",
            "fresh_context_confirmation",
        ),
        "produces": (produces,),
        "target_type": target_type,
        "ai_available": True,
        "transaction_mode": "multi_stage",
        "trace_rule": {
            "parameter_fields": trace_fields,
            "mode": "per_call",
            "parameter_policy": "schema_safe",
        },
        "permission": "suggest",
    }


OPERATIONS_SPEC = {
    "story.character_card.generate": {
        "label": "生成带来源的人物卡预览",
        "schema": GenerateCharacterCard,
        "prepare": _prepare_card,
        "apply": _submit_card,
        "read_result": _read_card_result,
        **_metadata(
            description=(
                "按该 POV 人物的确认资料生成可编辑的 v2 人物卡；"
                "事实由服务端固定，模型仅输出带来源的解释。"
            ),
            produces="preview_only_character_card_v2",
            target_type="story_character_card",
            trace_fields=("scene_id", "character_id", "additional_notes"),
        ),
    },
    "story.reaction.generate": {
        "label": "生成带来源的人物反应预览",
        "schema": GenerateCharacterReactions,
        "prepare": _prepare_reactions,
        "apply": _submit_reactions,
        "read_result": _read_reaction_result,
        **_metadata(
            op_version="2",
            description=(
                "按各人物独立 POV 资料生成 2–4 种不同动机与完整表演卡；"
                "每种动机均引用当前确认范围中的来源 ID。"
            ),
            produces="preview_only_sourced_character_reactions",
            target_type="story_character_reaction",
            trace_fields=("scene_id", "character_ids", "additional_notes"),
        ),
    },
}


__all__ = ["OPERATIONS_SPEC"]
