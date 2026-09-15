"""Async task handlers for RP story and overview generation."""

from __future__ import annotations

import time
import uuid

from sqlalchemy import select

from infrastructure.llm.agent_runtime import run_project_agent
from infrastructure.llm.agent_step_harness import run_managed_structured
from infrastructure.llm.capabilities import capability_from_execution_settings
from infrastructure.llm.retry import retry_with_backoff
from infrastructure.llm.schemas import (
    AI_RUN_ENVELOPE_KEY,
    AIRunStatus,
    read_ai_run_envelope,
)
from infrastructure.llm.workflow_budget import AIRunCheckpointError
from infrastructure.tasks.registry import task_handler
from modules.interaction.agent_runtime import InteractionAgentRun
from modules.interaction.framing import InteractionStreamFramer
from modules.interaction.generation import (
    InteractionContextBudgetError,
    InteractionGenerationWorkflow,
    PreparedSummaryGeneration,
    rp_timeout_seconds,
    story_request,
    story_stream_step_scope,
    summary_request,
)
from modules.interaction.runtime_policy import (
    AGENT_STORY_TASK,
    agent_story_enabled,
    interaction_story_run_id,
    interaction_story_run_request_limit,
)
from modules.interaction.schemas import InteractionSummaryOutput
from modules.project.facade import create_project_snapshot_llm_client

_workflow = InteractionGenerationWorkflow()
_CHECKPOINT_CHARS = 512
_CHECKPOINT_SECONDS = 2.0
_MAX_URGENT_SUMMARY_PASSES = 4


async def checkpoint_interaction_run_envelope(session, task, envelope: dict) -> None:
    """Mirror the queue receipt into the owning InteractionGenerationAttempt."""
    from modules.interaction.models import InteractionGenerationAttempt

    try:
        payload = read_ai_run_envelope(envelope)
        attempt_id = uuid.UUID(str((task.meta or {}).get("attempt_id") or ""))
        novel_id = uuid.UUID(str((task.meta or {}).get("novel_id") or ""))
        task_id = uuid.UUID(str(task.id))
    except (TypeError, ValueError) as exc:
        raise AIRunCheckpointError(
            "interaction run envelope target is invalid",
            run_id=str(envelope.get("run_id") or ""),
        ) from exc
    if payload is None:
        raise AIRunCheckpointError("interaction run envelope is missing")
    attempt = (
        await session.execute(
            select(InteractionGenerationAttempt)
            .where(
                InteractionGenerationAttempt.id == attempt_id,
                InteractionGenerationAttempt.novel_id == novel_id,
            )
            .with_for_update(skip_locked=True)
        )
    ).scalar_one_or_none()
    if attempt is None:
        exists = (
            await session.execute(
                select(InteractionGenerationAttempt.id).where(
                    InteractionGenerationAttempt.id == attempt_id,
                    InteractionGenerationAttempt.novel_id == novel_id,
                )
            )
        ).scalar_one_or_none()
        if exists is not None and payload.status is not AIRunStatus.running:
            # A domain stop/archive transaction owns attempt -> task order. A
            # terminal task must release its task lock instead of waiting back
            # on that attempt; the domain transaction owns the terminal state.
            return
        raise AIRunCheckpointError(
            "interaction run envelope target is unavailable",
            run_id=payload.run_id,
        )
    if (
        payload.run_id != str(attempt.id)
        or payload.operation_id != str(attempt.id)
        or payload.novel_id != str(attempt.novel_id)
        or payload.root_capability_id != "interaction.story_generate"
    ):
        raise AIRunCheckpointError(
            "interaction run envelope identity is invalid",
            run_id=payload.run_id,
        )
    if attempt.task_id != task_id:
        # A length handler may atomically enqueue its successor before the old
        # queue row reaches terminal state. The old lease remains valid for its
        # own row but must not overwrite the successor's run projection.
        successor = read_ai_run_envelope(
            dict(attempt.agent_checkpoint_json or {}).get(AI_RUN_ENVELOPE_KEY)
        )
        if not (
            attempt.status in {"pending", "preparing_context", "running"}
            and int(attempt.continuation_count or 0) > 0
            and successor is not None
            and successor.run_id == str(attempt.id)
            and successor.novel_id == str(attempt.novel_id)
            and successor.authorization_revision
            > payload.authorization_revision
        ):
            raise AIRunCheckpointError(
                "interaction run envelope owner is stale",
                run_id=payload.run_id,
            )
        return
    checkpoint = dict(attempt.agent_checkpoint_json or {})
    checkpoint[AI_RUN_ENVELOPE_KEY] = dict(envelope)
    attempt.agent_checkpoint_json = checkpoint
    await session.flush()
@task_handler(
    "interaction_continuity_review",
    recovery_policy="manual_resume",
    # A = 1 次结构化审查（1 + max_fix_attempts=2 次格式修复）× transport R3 = 9。
    # 180s 是单 provider timeout，不是整条 structured 链的既有总时限。
    root_capability_id="interaction.continuity_review",
    run_request_limit=9,
    run_deadline_seconds=None,
)
async def handle_interaction_continuity_review(db, task):
    from modules.interaction.proactive import handle_continuity_review

    return await handle_continuity_review(db, task)


@task_handler(
    "interaction_story_generate",
    recovery_policy="restart_origin",
    root_capability_id="interaction.story_generate",
    run_request_limit=interaction_story_run_request_limit,
    run_id=interaction_story_run_id,
    run_envelope_checkpoint=checkpoint_interaction_run_envelope,
)
@task_handler(
    "interaction_agent_story_generate",
    recovery_policy="restart_origin",
    root_capability_id="interaction.story_generate",
    run_request_limit=interaction_story_run_request_limit,
    run_id=interaction_story_run_id,
    run_envelope_checkpoint=checkpoint_interaction_run_envelope,
)
async def handle_interaction_story_generate(db, task):
    client = None
    framer = InteractionStreamFramer()
    pending_visible = ""
    finish_reason = "stop"
    final_usage: dict[str, int] | None = None
    last_checkpoint = time.monotonic()
    agent_run = None
    try:
        agent_enabled = agent_story_enabled(
            dict((task.meta or {}).get("llm_execution_snapshot") or {})
        )
        if agent_enabled != (task.task_type == AGENT_STORY_TASK):
            raise RuntimeError("RP runtime dispatch does not match its frozen snapshot")
        if agent_enabled:
            agent_run = InteractionAgentRun(db, task, _workflow)
            await agent_run.load()
        prepared = await _workflow.prepare_story_task(db, task=task)
        summary_passes = 0
        while isinstance(prepared, PreparedSummaryGeneration):
            summary_passes += 1
            if summary_passes > _MAX_URGENT_SUMMARY_PASSES:
                raise InteractionContextBudgetError(
                    "urgent summary pass budget was exhausted"
                )
            summary_diagnostics: list[dict] = []
            summary_client = create_project_snapshot_llm_client(
                prepared.executable_settings,
                novel_id=prepared.novel_id,
                timeout_override=rp_timeout_seconds(prepared),
            )
            try:
                if agent_run is not None:
                    summary_output = await run_project_agent(
                        summary_client,
                        summary_request(prepared),
                        tools=[],
                        deps=None,
                        output_type=InteractionSummaryOutput,
                        budget=agent_run.budget,
                        input_limit=capability_from_execution_settings(
                            prepared.executable_settings
                        ).hard_input_tokens,
                        checkpoint=agent_run.checkpoint,
                        future_requests=2,
                        # 活动 run 的 root capability；信封据此把本 Agent 循环
                        # 归入 interaction.story_generate（非 root 会被拒绝）。
                        capability_id="interaction.story_generate",
                    )
                    output = summary_output.output
                else:
                    output = await run_managed_structured(
                        summary_client,
                        summary_request(prepared),
                        InteractionSummaryOutput,
                        step_name="interaction.summary.generate",
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
        client = create_project_snapshot_llm_client(
            prepared.executable_settings,
            novel_id=prepared.novel_id,
            timeout_override=rp_timeout_seconds(prepared),
        )
        stream = (
            agent_run.stream(client, prepared)
            if agent_run is not None
            else story_stream_step_scope(
                client,
                client.generate_stream(story_request(prepared), transport_retries=False),
            )
        )
        async for chunk in stream:
            visible = framer.feed(chunk.content)
            if visible:
                pending_visible += visible
            if chunk.finish_reason:
                finish_reason = str(chunk.finish_reason)
            if chunk.usage is not None and agent_run is None:
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
        pending_visible = ""
        # ADR-0025 held release：审查通过前正文留在私有 hold，不写 visible_text。
        governed = await _workflow.govern_held_story(
            db,
            task=task,
            client=client,
            prepared=prepared,
        )
        if governed["status"] == "passed":
            await _workflow.release_story_task(
                db,
                task=task,
                text=governed["text"],
                review=governed.get("review"),
            )
        else:
            return await _workflow.fail_knowledge_hold(
                db,
                task=task,
                review=governed.get("review") or {},
            )
        return await _workflow.finalize_story_task(
            db,
            task=task,
            finish_reason=finish_reason,
            metadata=metadata,
        )
    except Exception as exc:
        trailing, _, _ = framer.finish()
        await _workflow.fail_story_task(
            db, task=task, error=exc, visible_delta=pending_visible + trailing
        )
        raise
    finally:
        if client is not None:
            await client.close()


@task_handler(
    "interaction_summary_refresh",
    recovery_policy="auto_requeue",
    max_attempts=2,
    # A = 2 次 task attempt × [2 次内层重试 ×（1 主请求 + 1 次格式修复）]
    # = 8；900s 是单 provider timeout，整条重试/requeue 链没有既有总时限。
    root_capability_id="interaction.summary_refresh",
    run_request_limit=8,
    run_deadline_seconds=None,
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
            timeout_override=rp_timeout_seconds(prepared),
        )
        diagnostics: list[dict] = []
        output = await retry_with_backoff(
            lambda: run_managed_structured(
                client,
                summary_request(prepared),
                InteractionSummaryOutput,
                step_name="interaction.summary.generate",
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
    try:
        return await _workflow.finalize_summary_task(
            db,
            task=task,
            prepared=prepared,
            output=output,
            diagnostics=diagnostics,
        )
    except Exception:
        await _workflow.mark_summary_failed(
            db,
            task=task,
            prepared=prepared,
        )
        raise
