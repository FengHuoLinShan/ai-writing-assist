"""Shared confirmed-task submission path for Story HTTP and Assistant entry points."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ConflictError
from infrastructure.tasks.facade import (
    enqueue_task_with_optional_operation,
    get_operation_task,
)
from modules.evidence.facade import attach_result_ref, require_fresh_confirmation
from modules.project.facade import build_project_llm_execution_snapshot
from modules.story.schemas import (
    StoryCardTaskRequest,
    StoryOneClickTaskRequest,
    StoryTaskRequest,
    StoryTaskResponse,
)

_CHARACTER_CARD_ACTION = "story.character_card.generate"
_REACTION_ACTION = "story.reaction.generate"
_STORY_GENERATION_BUDGET_TOKENS = 6000


def validate_story_generation_confirmation(
    compile_options: dict[str, Any],
    *,
    action: str,
    scene_id: str,
    character_ids: list[str],
) -> None:
    """Reject old or widened confirmations before a card/reaction task is queued."""
    expected_purpose = {
        _CHARACTER_CARD_ACTION: "story_character_card",
        _REACTION_ACTION: "story_character_reaction",
    }.get(action)
    if expected_purpose is None:
        return

    if (
        compile_options.get("consumer_action") != action
        or compile_options.get("retrieval_purpose") != expected_purpose
        or compile_options.get("scope") != "scene"
        or str(compile_options.get("scene_id") or "") != scene_id
        or str(compile_options.get("visible_until_scene_id") or "") != scene_id
        or compile_options.get("chapter_index") is not None
        or compile_options.get("visible_until_chapter") is not None
        or compile_options.get("visible_until_offset") is not None
        or compile_options.get("content_mode") != "canonical"
        or compile_options.get("context_mode") != "canonical"
        or compile_options.get("include_pending_objects") is not False
        or not 0
        < int(compile_options.get("budget_tokens") or 0)
        <= _STORY_GENERATION_BUDGET_TOKENS
    ):
        raise ConflictError(
            "原资料确认与当前 Story 操作或 Scene 截止范围不一致，请重新确认"
        )

    confirmed_characters = {
        str(value) for value in compile_options.get("character_ids") or []
    }
    if confirmed_characters != set(character_ids):
        raise ConflictError("原资料确认没有精确覆盖本次人物范围")

    if action == _CHARACTER_CARD_ACTION:
        if (
            compile_options.get("reveal_mode") != "character"
            or str(compile_options.get("viewpoint_character_id") or "")
            != character_ids[0]
        ):
            raise ConflictError("人物卡确认必须绑定目标人物 POV")
    elif (
        compile_options.get("reveal_mode") != "author_safe"
        or compile_options.get("viewpoint_character_id") is not None
    ):
        raise ConflictError("反应提案确认必须使用作者安全视角")


async def enqueue_confirmed_story_task(
    db: AsyncSession,
    data: StoryTaskRequest | StoryCardTaskRequest | StoryOneClickTaskRequest,
    *,
    action: str,
    task_type: str,
    extra_meta: dict | None = None,
    llm_execution_snapshot: Any | None = None,
) -> StoryTaskResponse:
    """Idempotently enqueue a task after checking its exact confirmation."""
    request_payload = data.model_dump(
        mode="json",
        exclude_none=True,
        exclude={"operation_id"},
    )
    if (
        isinstance(data, StoryOneClickTaskRequest)
        and data.simulation_protocol == "legacy"
    ):
        for key in ("simulation_protocol", "rehearsal_rounds", "fork_round"):
            request_payload.pop(key, None)
        if not data.use_round_candidates:
            request_payload.pop("use_round_candidates", None)

    existing = await get_operation_task(
        db,
        operation_id=str(data.operation_id) if data.operation_id else None,
        task_type=task_type,
        novel_id=data.novel_id,
        request_payload=request_payload,
    )
    if existing is not None:
        return StoryTaskResponse(task_id=existing.task_id, status=existing.status)

    confirmation = await require_fresh_confirmation(
        db,
        novel_id=data.novel_id,
        action=action,
        confirmation_id=data.context_confirmation_id,
    )
    if action in {_CHARACTER_CARD_ACTION, _REACTION_ACTION}:
        characters = (
            [str(data.character_id)]
            if isinstance(data, StoryCardTaskRequest)
            else [str(value) for value in data.character_ids]
        )
        validate_story_generation_confirmation(
            dict(confirmation.compile_options or {}),
            action=action,
            scene_id=str(data.scene_id),
            character_ids=characters,
        )
    snapshot = llm_execution_snapshot
    if snapshot is None:
        snapshot = await build_project_llm_execution_snapshot(db, data.novel_id)
    else:
        dump = getattr(snapshot, "model_dump", None)
        if callable(dump):
            snapshot = dump(mode="json")
        else:
            snapshot = dict(snapshot)
        if str(snapshot.get("novel_id") or "") != str(data.novel_id):
            raise ValueError("llm_execution_snapshot novel_id mismatch")

    meta = {
        "meta_version": 1,
        "request": request_payload,
        "action": action,
        **(extra_meta or {}),
        "llm_execution_snapshot": snapshot,
    }
    receipt = await enqueue_task_with_optional_operation(
        db,
        operation_id=str(data.operation_id) if data.operation_id else None,
        task_type=task_type,
        novel_id=data.novel_id,
        request_payload=request_payload,
        meta=meta,
    )
    if not receipt.reused:
        await attach_result_ref(
            db,
            novel_id=data.novel_id,
            confirmation_id=data.context_confirmation_id,
            result_type="task",
            result_id=receipt.task_id,
            status="running",
        )
    await db.flush()
    return StoryTaskResponse(task_id=receipt.task_id, status=receipt.status)
