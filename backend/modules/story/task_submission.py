"""Shared confirmed-task submission path for Story HTTP and Assistant entry points."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

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

    await require_fresh_confirmation(
        db,
        novel_id=data.novel_id,
        action=action,
        confirmation_id=data.context_confirmation_id,
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
