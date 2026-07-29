"""Async task handlers for RP story and overview generation."""

from __future__ import annotations

import time

from infrastructure.llm.retry import retry_with_backoff
from infrastructure.tasks.registry import task_handler
from modules.interaction.framing import InteractionStreamFramer
from modules.interaction.generation import (
    InteractionContextBudgetError,
    InteractionGenerationWorkflow,
    PreparedSummaryGeneration,
    story_request,
    summary_request,
)
from modules.interaction.schemas import InteractionSummaryOutput
from modules.project.facade import create_project_snapshot_llm_client

_workflow = InteractionGenerationWorkflow()
_CHECKPOINT_CHARS = 512
_CHECKPOINT_SECONDS = 2.0


@task_handler("interaction_story_generate", recovery_policy="restart_origin")
async def handle_interaction_story_generate(db, task):
    client = None
    framer = InteractionStreamFramer()
    pending_visible = ""
    finish_reason = "stop"
    final_usage: dict[str, int] | None = None
    last_checkpoint = time.monotonic()
    try:
        prepared = await _workflow.prepare_story_task(db, task=task)
        if isinstance(prepared, PreparedSummaryGeneration):
            summary_diagnostics: list[dict] = []
            summary_client = create_project_snapshot_llm_client(
                prepared.executable_settings,
                novel_id=prepared.novel_id,
            )
            try:
                output = await summary_client.generate_structured(
                    summary_request(prepared),
                    InteractionSummaryOutput,
                    max_fix_attempts=1,
                    diagnostics=summary_diagnostics,
                    fix_prompt=(
                        "上一轮回顾没有遵守固定结构。只输出合法 JSON；"
                        "不得添加新剧情或改变已有事实。"
                    ),
                )
            finally:
                await summary_client.close()
            summary_result = await _workflow.finalize_summary_task(
                db,
                task=task,
                prepared=prepared,
                output=output,
                diagnostics=summary_diagnostics,
            )
            if summary_result.get("status") != "completed":
                return summary_result
            prepared = await _workflow.prepare_story_task(db, task=task)
            if isinstance(prepared, PreparedSummaryGeneration):
                raise InteractionContextBudgetError(
                    "urgent summary did not reduce the story context"
                )
        client = create_project_snapshot_llm_client(
            prepared.executable_settings,
            novel_id=prepared.novel_id,
        )
        async for chunk in client.generate_stream(
            story_request(prepared),
            transport_retries=False,
        ):
            visible = framer.feed(chunk.content)
            if visible:
                pending_visible += visible
            if chunk.finish_reason:
                finish_reason = str(chunk.finish_reason)
            if chunk.usage is not None:
                final_usage = chunk.usage.model_dump()
            now = time.monotonic()
            if pending_visible and (
                len(pending_visible) >= _CHECKPOINT_CHARS
                or now - last_checkpoint >= _CHECKPOINT_SECONDS
            ):
                await _workflow.checkpoint_story_task(
                    db,
                    task=task,
                    visible_delta=pending_visible,
                    progress=0.5,
                )
                pending_visible = ""
                last_checkpoint = now
        trailing, metadata, raw_metadata = framer.finish()
        pending_visible += trailing
        await _workflow.checkpoint_story_task(
            db,
            task=task,
            visible_delta=pending_visible,
            metadata_text=raw_metadata,
            usage=final_usage,
            progress=0.95,
        )
        return await _workflow.finalize_story_task(
            db,
            task=task,
            finish_reason=finish_reason,
            metadata=metadata,
        )
    except Exception as exc:
        await _workflow.fail_story_task(db, task=task, error=exc)
        raise
    finally:
        if client is not None:
            await client.close()


@task_handler(
    "interaction_summary_refresh",
    recovery_policy="auto_requeue",
    max_attempts=2,
)
async def handle_interaction_summary_refresh(db, task):
    prepared = None
    client = None
    try:
        prepared = await _workflow.prepare_summary_task(db, task=task)
        if prepared is None:
            return {"status": "stale"}
        client = create_project_snapshot_llm_client(
            prepared.executable_settings,
            novel_id=prepared.novel_id,
        )
        diagnostics: list[dict] = []
        output = await retry_with_backoff(
            lambda: client.generate_structured(
                summary_request(prepared),
                InteractionSummaryOutput,
                max_fix_attempts=1,
                transport_retries=False,
                diagnostics=diagnostics,
                fix_prompt=(
                    "上一轮回顾没有遵守固定结构。只输出合法 JSON；"
                    "不得添加新剧情或改变已有事实。"
                ),
            ),
            max_attempts=2,
        )
    except Exception:
        if prepared is None:
            await _workflow.mark_summary_task_failed(
                db,
                task=task,
            )
        else:
            await _workflow.mark_summary_failed(
                db,
                task=task,
                prepared=prepared,
            )
        raise
    finally:
        if client is not None:
            await client.close()
    assert prepared is not None
    return await _workflow.finalize_summary_task(
        db,
        task=task,
        prepared=prepared,
        output=output,
        diagnostics=diagnostics,
    )
