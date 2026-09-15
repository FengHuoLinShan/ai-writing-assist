"""Owner-scoped persisted SSE projection for interaction attempts."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from time import monotonic

from sqlalchemy import select

from core.database import get_manager
from infrastructure.llm.agent_step_harness import run_managed_structured
from modules.account.context import bind_principal, reset_principal
from modules.account.contracts import AccountPrincipal
from modules.interaction.framing import InteractionStreamFramer
from modules.interaction.generation import (
    InlineStoryTask,
    InteractionClientDisconnectedError,
    InteractionGenerationWorkflow,
    PreparedStoryGeneration,
    PreparedSummaryGeneration,
    story_request,
    story_stream_step_scope,
    summary_request,
)
from modules.interaction.models import (
    InteractionGenerationAttempt,
    InteractionJourney,
)
from modules.interaction.runtime_policy import (
    anonymous_rp_execution_settings,
    is_anonymous_rp_snapshot,
)
from modules.interaction.schemas import InteractionSummaryOutput
from modules.project.facade import create_project_snapshot_llm_client

TERMINAL_ATTEMPT_STATUSES = {
    "awaiting_continue",
    "completed",
    "failed",
    "cancelled",
    "stopped",
}

_inline_workflow = InteractionGenerationWorkflow()


def _event(
    event: str,
    data: dict,
    *,
    event_id: int | None = None,
) -> str:
    parts = []
    if event_id is not None:
        parts.append(f"id: {event_id}")
    parts.append(f"event: {event}")
    parts.append(
        "data: "
        + json.dumps(
            data,
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )
    return "\n".join(parts) + "\n\n"


async def stream_attempt_events(
    *,
    owner_id: uuid.UUID,
    journey_id: uuid.UUID,
    attempt_id: uuid.UUID,
    offset: int,
) -> AsyncIterator[str]:
    current_offset = max(0, offset)
    last_status: str | None = None
    last_keepalive = monotonic()
    while True:
        async with get_manager().session_factory() as db:
            row = (
                await db.execute(
                    select(
                        InteractionGenerationAttempt.visible_text,
                        InteractionGenerationAttempt.visible_offset,
                        InteractionGenerationAttempt.status,
                        InteractionGenerationAttempt.finish_reason,
                        InteractionGenerationAttempt.error_kind,
                        InteractionGenerationAttempt.error_message,
                        InteractionGenerationAttempt.result_node_id,
                    )
                    .join(
                        InteractionJourney,
                        InteractionJourney.id == InteractionGenerationAttempt.journey_id,
                    )
                    .where(
                        InteractionJourney.id == journey_id,
                        InteractionJourney.owner_id == owner_id,
                        InteractionJourney.novel_id
                        == InteractionGenerationAttempt.novel_id,
                        InteractionGenerationAttempt.id == attempt_id,
                        InteractionGenerationAttempt.journey_id == journey_id,
                        InteractionGenerationAttempt.owner_id == owner_id,
                    )
                )
            ).one_or_none()
        if row is None:
            yield _event("error", {"code": "not_found"})
            return
        visible_text = str(row.visible_text or "")
        persisted_offset = int(row.visible_offset or 0)
        if current_offset > persisted_offset:
            current_offset = 0
            yield _event("reset", {"offset": 0})
        if persisted_offset > current_offset:
            text = visible_text[current_offset:persisted_offset]
            current_offset = persisted_offset
            yield _event(
                "chunk",
                {"offset": current_offset, "text": text},
                event_id=current_offset,
            )
        status = str(row.status)
        if status != last_status:
            last_status = status
            yield _event(
                "status",
                {
                    "status": status,
                    "offset": persisted_offset,
                    "finish_reason": row.finish_reason,
                    "error_kind": row.error_kind,
                    "error_message": row.error_message,
                    "result_node_id": (
                        str(row.result_node_id) if row.result_node_id else None
                    ),
                },
                event_id=current_offset,
            )
        if status in TERMINAL_ATTEMPT_STATUSES:
            yield _event(
                "done",
                {
                    "status": status,
                    "offset": persisted_offset,
                    "result_node_id": (
                        str(row.result_node_id) if row.result_node_id else None
                    ),
                },
                event_id=current_offset,
            )
            return
        now = monotonic()
        if now - last_keepalive >= 15:
            yield ": keep-alive\n\n"
            last_keepalive = now
        await asyncio.sleep(0.35)


def _attempt_status(attempt: InteractionGenerationAttempt) -> dict:
    return {
        "status": attempt.status,
        "offset": int(attempt.visible_offset or 0),
        "finish_reason": attempt.finish_reason,
        "error_kind": attempt.error_kind,
        "error_message": attempt.error_message,
        "result_node_id": (
            str(attempt.result_node_id) if attempt.result_node_id else None
        ),
    }


async def _fail_inline_attempt(
    *,
    principal: AccountPrincipal,
    task: InlineStoryTask,
    error: Exception,
) -> InteractionGenerationAttempt | None:
    async with get_manager().session_factory() as db:
        await _inline_workflow.fail_story_task(db, task=task, error=error)
        journey_id = uuid.UUID(str(task.meta["journey_id"]))
        attempt_id = uuid.UUID(str(task.meta["attempt_id"]))
        journey = await _inline_workflow._repo.get_journey(  # noqa: SLF001
            db,
            journey_id=journey_id,
            owner_id=principal.account_id,
            status="active",
        )
        return (
            await _inline_workflow._repo.get_attempt(  # noqa: SLF001
                db,
                journey=journey,
                attempt_id=attempt_id,
                for_update=False,
            )
            if journey is not None
            else None
        )


async def stream_anonymous_rp_attempt(
    *,
    request,
    principal: AccountPrincipal,
    journey_id: uuid.UUID,
    attempt_id: uuid.UUID,
    api_key: str,
    execution_id: str,
) -> AsyncIterator[str]:
    """Run one anonymous RP attempt inside its SSE request, never a worker."""
    context_token = bind_principal(principal)
    client = None
    task = None
    try:
        async with get_manager().session_factory() as db:
            journey = await _inline_workflow._repo.get_journey(  # noqa: SLF001
                db,
                journey_id=journey_id,
                owner_id=principal.account_id,
                status="active",
            )
            if journey is None:
                yield _event("error", {"code": "not_found"})
                return
            attempt = await _inline_workflow._repo.get_attempt(  # noqa: SLF001
                db,
                journey=journey,
                attempt_id=attempt_id,
                for_update=False,
            )
            if (
                attempt is None
                or attempt.task_id is not None
                or not is_anonymous_rp_snapshot(
                    dict(attempt.llm_execution_snapshot or {})
                )
            ):
                yield _event("error", {"code": "not_found"})
                return
            task = InlineStoryTask(
                meta={
                    "novel_id": str(journey.novel_id),
                    "journey_id": str(journey.id),
                    "attempt_id": str(attempt.id),
                    "llm_execution_snapshot": dict(attempt.llm_execution_snapshot or {}),
                },
                executable_settings=anonymous_rp_execution_settings(
                    dict(attempt.llm_execution_snapshot or {})
                ),
                execution_id=execution_id,
            )
            if await request.is_disconnected():
                raise InteractionClientDisconnectedError()
            prepared = await _inline_workflow.prepare_story_task(db, task=task)
            summary_passes = 0
            while isinstance(prepared, PreparedSummaryGeneration):
                summary_passes += 1
                if summary_passes > 4:
                    raise RuntimeError("anonymous RP summary pass budget was exhausted")
                if await request.is_disconnected():
                    raise InteractionClientDisconnectedError()
                summary_settings = {
                    **prepared.executable_settings,
                    "llm": {
                        **dict(prepared.executable_settings.get("llm") or {}),
                        "api_key": api_key,
                    },
                }
                summary_client = create_project_snapshot_llm_client(
                    summary_settings,
                    novel_id=prepared.novel_id,
                )
                try:
                    output = await run_managed_structured(
                        summary_client,
                        summary_request(prepared),
                        InteractionSummaryOutput,
                        step_name="interaction.summary.generate",
                        max_fix_attempts=1,
                        diagnostics=[],
                        fix_prompt=(
                            "上一轮回顾没有遵守固定结构。只输出合法 JSON；"
                            "不得添加新剧情或改变已有事实。"
                        ),
                    )
                finally:
                    await summary_client.close()
                await _inline_workflow.finalize_summary_task(
                    db,
                    task=task,
                    prepared=prepared,
                    output=output,
                    diagnostics=[],
                )
                prepared = await _inline_workflow.prepare_story_task(db, task=task)
            if not isinstance(prepared, PreparedStoryGeneration):
                raise RuntimeError("anonymous RP preparation is invalid")
            client_settings = {
                **prepared.executable_settings,
                "llm": {
                    **dict(prepared.executable_settings.get("llm") or {}),
                    "api_key": api_key,
                },
            }
            client = create_project_snapshot_llm_client(
                client_settings,
                novel_id=prepared.novel_id,
            )
            yield _event("status", {"status": "running", "offset": 0})
            framer = InteractionStreamFramer()
            finish_reason = "stop"
            final_usage: dict[str, int] | None = None
            # ADR-0025 held release：匿名演示同样不得在审查通过前输出正文；
            # chunk 只入私有 hold，PASS 后一次性发放全文。
            async for chunk in story_stream_step_scope(
                client,
                client.generate_stream(
                    story_request(prepared),
                    transport_retries=False,
                ),
            ):
                if await request.is_disconnected():
                    raise InteractionClientDisconnectedError()
                visible = framer.feed(chunk.content)
                if visible:
                    await _inline_workflow.checkpoint_story_task(
                        db,
                        task=task,
                        visible_delta=visible,
                    )
                if chunk.finish_reason:
                    finish_reason = str(chunk.finish_reason)
                if chunk.usage is not None:
                    final_usage = chunk.usage.model_dump()
            trailing, metadata, raw_metadata = framer.finish()
            await _inline_workflow.checkpoint_story_task(
                db,
                task=task,
                visible_delta=trailing,
                metadata_text=raw_metadata,
                usage=final_usage,
                progress=0.95,
            )
            governed = await _inline_workflow.govern_held_story(
                db,
                task=task,
                client=client,
                prepared=prepared,
            )
            if governed["status"] != "passed":
                await _inline_workflow.fail_knowledge_hold(
                    db,
                    task=task,
                    review=governed.get("review") or {},
                )
                yield _event(
                    "status",
                    {
                        "status": "failed",
                        "offset": 0,
                        "finish_reason": "knowledge_review_blocked",
                        "error_kind": "knowledge_review_blocked",
                        "error_message": (
                            "这段内容未通过知识边界审查；请重新生成或换个说法"
                        ),
                        "result_node_id": None,
                    },
                )
                yield _event(
                    "done",
                    {"status": "failed", "offset": 0, "result_node_id": None},
                )
                return
            await _inline_workflow.release_story_task(
                db,
                task=task,
                text=governed["text"],
                review=governed.get("review"),
            )
            yield _event(
                "chunk",
                {"offset": len(governed["text"]), "text": governed["text"]},
                event_id=len(governed["text"]),
            )
            result = await _inline_workflow.finalize_story_task(
                db,
                task=task,
                finish_reason=finish_reason,
                metadata=metadata,
            )
            await db.commit()
            db.expire_all()
            settled = await _inline_workflow._repo.get_attempt(  # noqa: SLF001
                db,
                journey=journey,
                attempt_id=attempt_id,
                for_update=False,
            )
            if settled is None:
                yield _event("error", {"code": "not_found"})
                return
            yield _event(
                "status",
                _attempt_status(settled),
                event_id=settled.visible_offset,
            )
            yield _event(
                "done",
                {
                    "status": result.get("status", settled.status),
                    "offset": settled.visible_offset,
                    "result_node_id": (
                        str(settled.result_node_id) if settled.result_node_id else None
                    ),
                },
                event_id=settled.visible_offset,
            )
    except InteractionClientDisconnectedError:
        if task is not None:
            await _fail_inline_attempt(
                principal=principal,
                task=task,
                error=InteractionClientDisconnectedError(),
            )
        return
    except asyncio.CancelledError:
        if task is not None:
            await _fail_inline_attempt(
                principal=principal,
                task=task,
                error=InteractionClientDisconnectedError(),
            )
        raise
    except Exception as error:
        if task is not None:
            attempt = await _fail_inline_attempt(
                principal=principal,
                task=task,
                error=error,
            )
            if attempt is not None:
                yield _event(
                    "status",
                    _attempt_status(attempt),
                    event_id=attempt.visible_offset,
                )
                yield _event(
                    "done",
                    {
                        "status": attempt.status,
                        "offset": attempt.visible_offset,
                        "result_node_id": None,
                    },
                    event_id=attempt.visible_offset,
                )
                return
        yield _event("error", {"code": "generation_failed"})
    finally:
        if client is not None:
            await client.close()
        reset_principal(context_token)
