"""Task-owned story streaming and asynchronous overview refresh."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.llm.capabilities import (
    capability_from_execution_settings,
    capability_from_execution_snapshot,
)
from infrastructure.llm.errors import (
    LLMAuthError,
    LLMConnectionError,
    LLMContentFilterError,
    LLMQuotaError,
    LLMRateLimitError,
    LLMTimeoutError,
)
from infrastructure.llm.schemas import LLMCallRequest, LLMMessage
from infrastructure.tasks.facade import (
    enqueue_coalesced_task,
    enqueue_task,
    require_task_checkpoint_session,
)
from modules.evidence.facade import compile_interaction_story_context
from modules.interaction.models import (
    InteractionGenerationAttempt,
    InteractionJourney,
    InteractionMessageNode,
    InteractionOverviewRevision,
    InteractionSummarySegment,
)
from modules.interaction.prompts import (
    STORY_PROMPT_VERSION,
    SUMMARY_PROMPT_VERSION,
    SUMMARY_SCHEMA_VERSION,
    compile_story_messages,
    estimate_input_tokens,
    render_overview_sections,
    summary_system_prompt,
)
from modules.interaction.repositories import InteractionRepository
from modules.interaction.schemas import (
    InteractionOverviewSections,
    InteractionResponseMetadata,
    InteractionSummaryOutput,
)
from modules.interaction.services import (
    InteractionService,
    _summary_compressible_prefix_end,
    estimate_story_tokens,
    path_hash,
)
from modules.project.contracts import ProjectLLMConfigurationError
from modules.project.facade import (
    require_interaction_project,
    restore_project_llm_execution_settings,
)


@dataclass(frozen=True)
class PreparedStoryGeneration:
    novel_id: str
    journey_id: str
    attempt_id: str
    request_kind: str
    messages: list[LLMMessage]
    executable_settings: dict[str, Any]
    existing_visible_text: str
    see_sea_step: bool = False


@dataclass(frozen=True)
class PreparedSummaryGeneration:
    novel_id: str
    journey_id: str
    path_hash: str
    node_ids: list[str]
    segment_node_ids: list[str]
    started_overview_epoch: int
    messages: list[LLMMessage]
    executable_settings: dict[str, Any]
    estimated_input_tokens: int = 0
    segment_path_hash: str | None = None
    protected_node_ids: list[str] = field(default_factory=list)
    compaction_source_tokens: int = 0
    origin_attempt_id: str | None = None
    origin_task_id: str | None = None


class InteractionContextBudgetError(RuntimeError):
    """Fail closed when the selected path cannot be compiled without loss.

    ``kind`` selects the attempt ``error_kind``; ``user_message`` overrides the
    kind's default copy when the raise site already holds a user-facing reason
    (e.g. a compiled source-context blocker).  Internal English diagnostics must
    stay on ``str(error)`` only.
    """

    def __init__(
        self,
        message: str,
        *,
        kind: str = "context_budget",
        user_message: str | None = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.user_message = user_message


_SOURCE_QUERY_MAX_CHARS = 4_000
_SUMMARY_MIN_SAVINGS_TOKENS = 128


def _clip_query_text(value: str, limit: int) -> str:
    text = value.strip()
    if len(text) <= limit:
        return text
    half = (limit - 1) // 2
    return f"{text[:half]}…{text[-half:]}"


def _source_retrieval_query(
    *,
    latest_input: str,
    overview_sections: InteractionOverviewSections | dict | None,
    path: list[InteractionMessageNode],
) -> str:
    sections = InteractionOverviewSections.model_validate(overview_sections or {})
    seeds = [
        ("当前输入", _clip_query_text(latest_input, 800)),
        ("当前局面", _clip_query_text(sections.current_situation, 500)),
        (
            "相关人物与势力",
            _clip_query_text(sections.important_people_and_factions, 500),
        ),
        ("未决事项", _clip_query_text(sections.open_threads, 500)),
        ("必须记住", _clip_query_text(sections.must_remember, 400)),
    ]
    seeds.extend(
        (
            "近期发展",
            _clip_query_text(node.content, 320),
        )
        for node in path[-3:]
    )
    seen: set[str] = set()
    blocks: list[str] = []
    for label, value in seeds:
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        blocks.append(f"{label}：{normalized}")
    return _clip_query_text("\n".join(blocks), _SOURCE_QUERY_MAX_CHARS)


class InteractionGenerationWorkflow:
    def __init__(
        self,
        repo: InteractionRepository | None = None,
        service: InteractionService | None = None,
    ) -> None:
        self._repo = repo or InteractionRepository()
        self._service = service or InteractionService(self._repo)

    async def prepare_story_task(
        self,
        db: AsyncSession,
        *,
        task: Any,
    ) -> PreparedStoryGeneration | PreparedSummaryGeneration:
        require_task_checkpoint_session(db)
        novel_id, journey_id, attempt_id = self._task_ids(task)
        await require_interaction_project(db, novel_id)
        journey = await self._repo.get_journey_for_task(
            db,
            journey_id=journey_id,
            novel_id=uuid.UUID(novel_id),
            for_update=True,
        )
        if journey is None:
            raise RuntimeError("interaction journey is not active")
        attempt = await self._repo.get_attempt_for_task(
            db,
            journey=journey,
            attempt_id=attempt_id,
            task_id=uuid.UUID(str(task.id)),
            for_update=True,
        )
        if attempt is None or attempt.status != "pending":
            raise RuntimeError("interaction attempt is not pending for this task")
        task_snapshot = dict((task.meta or {}).get("llm_execution_snapshot") or {})
        if task_snapshot != dict(attempt.llm_execution_snapshot or {}):
            raise RuntimeError("interaction LLM snapshot mismatch")
        capability = capability_from_execution_snapshot(task_snapshot)

        response_to = await self._repo.get_node(
            db,
            journey=journey,
            node_id=attempt.response_to_node_id,
        )
        if response_to is None:
            raise RuntimeError("interaction response target is unavailable")
        nodes = await self._repo.get_ancestry(
            db,
            journey=journey,
            node=response_to,
        )
        if journey.selection_epoch != attempt.started_selection_epoch:
            raise RuntimeError("interaction context selection epoch mismatch")
        self._validate_context_chain(nodes, attempt)
        overview = await self._service._best_overview_for_path(
            db,
            journey=journey,
            path=nodes,
        )
        overview_content = None
        overview_anchor = None
        overview_sections = None
        if (
            overview is not None
            and self._service._overview_matches_path(overview, nodes)
            and self._service._overview_coverage_matches_path(overview, nodes)
        ):
            overview_content = render_overview_sections(overview.sections)
            overview_sections = overview.sections
            overview_anchor = str(self._service._overview_coverage_anchor(overview))
        references: list[str] = []
        reference_ids = self._parse_node_ids(
            attempt.reference_node_ids,
            allow_empty=True,
        )
        if reference_ids:
            reference_nodes = await self._repo.get_nodes_in_order(
                db,
                journey=journey,
                node_ids=reference_ids,
            )
            references = [
                (
                    node.content
                    if index == 0
                    else (
                        node.branch_hint or self._service._branch_hint(node.content) or ""
                    )
                )
                for index, node in enumerate(reference_nodes)
            ]
        is_see_sea_step = self._attempt_is_see_sea_step(attempt)
        source_context = None
        if attempt.source_revision_id is not None:
            if (
                journey.source_revision_id != attempt.source_revision_id
                or journey.source_context_epoch != attempt.started_source_context_epoch
            ):
                raise RuntimeError("interaction source context epoch mismatch")
            revision = await self._service._sources.require_ready_revision(
                db,
                attempt.source_revision_id,
            )
            compiled_source = await compile_interaction_story_context(
                db,
                source_novel_id=str(revision.source_novel_id),
                consumer_novel_id=str(journey.novel_id),
                source_revision_id=str(revision.id),
                source_manifest=list(revision.source_manifest or []),
                anchor=dict(journey.source_anchor or {}),
                player_identity=dict(journey.player_identity or {}),
                reference_manifest=list(revision.reference_manifest or []),
                ambiguities=list(revision.ambiguities or []),
                resolutions=dict(revision.resolutions or {}),
                reference_policy=dict(journey.reference_policy or {}),
                query=_source_retrieval_query(
                    latest_input=response_to.content,
                    overview_sections=overview_sections,
                    path=nodes,
                ),
                task_id=str(task.id),
                model=str((task_snapshot.get("profile") or {}).get("model") or ""),
            )
            if compiled_source.blockers:
                raise InteractionContextBudgetError(
                    compiled_source.blockers[0],
                    kind="source_context_blocked",
                    user_message=compiled_source.blockers[0],
                )
            if not compiled_source.rendered_context:
                # Blockers are the only legal way to compile an empty packet;
                # never let a source-bound attempt fall back to model knowledge.
                raise InteractionContextBudgetError(
                    "source context compiled without rendered content",
                    kind="source_context_blocked",
                    user_message="作品资料暂时无法安全引用，请查看作品资料调整后重试。",
                )
            source_context = compiled_source.rendered_context
            attempt.source_context_snapshot_id = (
                uuid.UUID(compiled_source.snapshot_id)
                if compiled_source.snapshot_id
                else None
            )
            attempt.source_context_fingerprint = compiled_source.fingerprint
            attempt.reference_trace = list(compiled_source.included_refs)
        messages = compile_story_messages(
            path=nodes,
            overview=overview_content,
            overview_anchor_node_id=overview_anchor,
            # The attempt freezes the agency contract for this beat.  The
            # journey flag only authorizes creation of a successor, so turning
            # it off while pending must not rewrite the current prompt.
            see_sea_enabled=is_see_sea_step,
            action_options_enabled=journey.action_options_enabled,
            request_kind=attempt.request_kind,
            rejected_variants=references,
            continuation_text=(
                attempt.visible_text
                if attempt.request_kind in {"continue", "see_sea_continue"}
                else None
            ),
            source_context=source_context,
        )
        estimated_input_tokens = estimate_input_tokens(
            messages,
            model=capability.model,
        )
        if estimated_input_tokens > capability.compact_trigger_tokens:
            prepared_summary = await self._prepare_summary_generation(
                db,
                journey=journey,
                current_path=nodes,
                expected_path_hash=attempt.context_path_hash,
                started_epoch=journey.overview_epoch,
                snapshot=task_snapshot,
                origin_attempt_id=str(attempt.id),
                origin_task_id=str(task.id),
            )
            if prepared_summary is None:
                raise InteractionContextBudgetError(
                    "interaction context could not produce a summary tail"
                )
            if prepared_summary.estimated_input_tokens > capability.hard_input_tokens:
                raise InteractionContextBudgetError(
                    "interaction summary source exceeds hard input budget"
                )
            attempt.status = "preparing_context"
            attempt.usage = {
                **dict(attempt.usage or {}),
                "context_tier": "emergency_summary",
                "estimated_input_tokens": estimated_input_tokens,
                "prompt_version": STORY_PROMPT_VERSION,
            }
            task.update_progress(0.04)
            await db.commit()
            if db.in_transaction():
                raise RuntimeError(
                    "interaction context preparation must close transaction"
                )
            db.expire_all()
            return prepared_summary
        if estimated_input_tokens > capability.hard_input_tokens:
            raise InteractionContextBudgetError(
                "selected interaction path exceeds hard input budget"
            )
        executable = await restore_project_llm_execution_settings(
            db,
            novel_id,
            task_snapshot,
        )
        attempt.status = "running"
        attempt.usage = {
            **dict(attempt.usage or {}),
            "context_tier": (
                "extended"
                if estimated_input_tokens > capability.normal_input_tokens
                else "normal"
            ),
            "estimated_input_tokens": estimated_input_tokens,
            "prompt_version": STORY_PROMPT_VERSION,
        }
        attempt.last_checkpoint_at = datetime.now(UTC)
        prepared_journey_id = str(journey.id)
        prepared_attempt_id = str(attempt.id)
        prepared_request_kind = attempt.request_kind
        prepared_visible_text = attempt.visible_text
        prepared_see_sea_step = is_see_sea_step
        task.update_progress(0.02)
        await db.commit()
        if db.in_transaction():
            raise RuntimeError("interaction prepare checkpoint must close transaction")
        db.expire_all()
        return PreparedStoryGeneration(
            novel_id=novel_id,
            journey_id=prepared_journey_id,
            attempt_id=prepared_attempt_id,
            request_kind=prepared_request_kind,
            messages=messages,
            executable_settings=executable,
            existing_visible_text=prepared_visible_text,
            see_sea_step=prepared_see_sea_step,
        )

    async def checkpoint_story_task(
        self,
        db: AsyncSession,
        *,
        task: Any,
        visible_delta: str,
        metadata_text: str | None = None,
        usage: dict[str, int] | None = None,
        progress: float | None = None,
    ) -> int:
        require_task_checkpoint_session(db)
        novel_id, journey_id, attempt_id = self._task_ids(task)
        await require_interaction_project(db, novel_id)
        journey = await self._repo.get_journey_for_task(
            db,
            journey_id=journey_id,
            novel_id=uuid.UUID(novel_id),
            for_update=False,
        )
        if journey is None:
            raise RuntimeError("interaction journey is not active")
        attempt = await self._repo.get_attempt_for_task(
            db,
            journey=journey,
            attempt_id=attempt_id,
            task_id=uuid.UUID(str(task.id)),
            for_update=True,
        )
        if attempt is None or attempt.status != "running":
            raise RuntimeError("interaction attempt no longer accepts stream chunks")
        if (
            journey.source_revision_id != attempt.source_revision_id
            or journey.source_context_epoch != attempt.started_source_context_epoch
        ):
            raise RuntimeError("interaction source context changed during generation")
        if visible_delta:
            attempt.visible_text += visible_delta
            attempt.visible_offset = len(attempt.visible_text)
        if metadata_text is not None:
            attempt.metadata_text = metadata_text[:8192]
        if usage:
            previous = dict(attempt.usage or {})
            continuation_keys = previous.get("continuation_keys", [])
            totals = {
                key: value
                for key, value in previous.items()
                if key
                not in {
                    "prompt_tokens",
                    "completion_tokens",
                    "total_tokens",
                    "continuation_keys",
                }
            }
            totals.update(
                {
                    "prompt_tokens": int(previous.get("prompt_tokens", 0))
                    + int(usage.get("prompt_tokens", 0)),
                    "completion_tokens": int(previous.get("completion_tokens", 0))
                    + int(usage.get("completion_tokens", 0)),
                    "total_tokens": int(previous.get("total_tokens", 0))
                    + int(usage.get("total_tokens", 0)),
                }
            )
            if continuation_keys:
                totals["continuation_keys"] = continuation_keys
            attempt.usage = totals
        attempt.last_checkpoint_at = datetime.now(UTC)
        visible_offset = attempt.visible_offset
        if progress is not None:
            task.update_progress(max(0.02, min(0.94, progress)))
        await db.commit()
        if db.in_transaction():
            raise RuntimeError("interaction stream checkpoint must close transaction")
        db.expire_all()
        return visible_offset

    async def finalize_story_task(
        self,
        db: AsyncSession,
        *,
        task: Any,
        finish_reason: str,
        metadata: InteractionResponseMetadata | None,
    ) -> dict[str, Any]:
        require_task_checkpoint_session(db)
        novel_id, journey_id, attempt_id = self._task_ids(task)
        await require_interaction_project(db, novel_id)
        journey = await self._repo.get_journey_for_task(
            db,
            journey_id=journey_id,
            novel_id=uuid.UUID(novel_id),
            for_update=True,
        )
        if journey is None:
            raise RuntimeError("interaction journey is not active")
        attempt = await self._repo.get_attempt_for_task(
            db,
            journey=journey,
            attempt_id=attempt_id,
            task_id=uuid.UUID(str(task.id)),
            for_update=True,
        )
        if attempt is None:
            raise RuntimeError("interaction attempt not found")
        if attempt.result_node_id is not None:
            task.update_progress(1.0)
            return {
                "attempt_id": str(attempt.id),
                "node_id": str(attempt.result_node_id),
                "status": attempt.status,
            }
        if attempt.status != "running":
            raise RuntimeError("interaction attempt cannot be finalized")
        if (
            journey.source_revision_id != attempt.source_revision_id
            or journey.source_context_epoch != attempt.started_source_context_epoch
        ):
            attempt.status = "failed"
            attempt.error_kind = "source_context_stale"
            attempt.error_message = "作品资料已变化，请重新生成"
            attempt.metadata_text = ""
            task.update_progress(1.0)
            await db.flush()
            return {"attempt_id": str(attempt.id), "status": "failed"}
        attempt.finish_reason = finish_reason or "stop"
        is_see_sea_step = self._attempt_is_see_sea_step(attempt)
        selection_is_current = journey.selection_epoch == attempt.started_selection_epoch
        completion_state = "complete"
        terminal_status = "completed"
        if finish_reason == "content_filter":
            attempt.status = "failed"
            attempt.error_kind = "content_filter"
            attempt.error_message = "这次内容未能生成，请换一种说法后重试"
            attempt.metadata_text = ""
            if is_see_sea_step:
                journey.see_sea_enabled = False
                journey.see_sea_last_heartbeat_at = None
            task.update_progress(1.0)
            await db.flush()
            return {
                "attempt_id": str(attempt.id),
                "status": "failed",
            }
        if not attempt.visible_text.strip():
            attempt.status = "failed"
            attempt.error_kind = "empty_response"
            attempt.error_message = "这次没有生成故事内容，请重新生成"
            attempt.metadata_text = ""
            if is_see_sea_step:
                journey.see_sea_enabled = False
                journey.see_sea_last_heartbeat_at = None
            task.update_progress(1.0)
            await db.flush()
            return {
                "attempt_id": str(attempt.id),
                "status": "failed",
            }
        if finish_reason == "length":
            if not selection_is_current:
                # A sibling already won this branch epoch. Preserve the late
                # visible result as an unselected partial variant, but never
                # leave an invisible awaiting_continue record that blocks the
                # current path.
                completion_state = "partial"
                terminal_status = "stopped"
                metadata = None
            elif attempt.continuation_count >= 1:
                # One continuation is the hard cost and recovery boundary for
                # both manual and see-sea flows. A second length cutoff keeps
                # all visible text as a selected partial node instead of
                # reopening the same attempt for another provider call.
                completion_state = "partial"
                terminal_status = "stopped"
                metadata = None
                if is_see_sea_step:
                    journey.see_sea_enabled = False
                    journey.see_sea_last_heartbeat_at = None
            elif is_see_sea_step:
                attempt.status = "pending"
                attempt.request_kind = "see_sea_continue"
                attempt.continuation_count += 1
                attempt.metadata_text = ""
                next_task_id = enqueue_task(
                    db,
                    "interaction_story_generate",
                    meta=self._service._story_task_meta(journey, attempt),
                    novel_id=str(journey.novel_id),
                )
                attempt.task_id = uuid.UUID(next_task_id)
                task.update_progress(1.0)
                await db.flush()
                return {
                    "attempt_id": str(attempt.id),
                    "status": "pending",
                    "visible_offset": attempt.visible_offset,
                    "continuation_task_id": next_task_id,
                }
            else:
                attempt.status = "awaiting_continue"
                attempt.metadata_text = ""
                task.update_progress(1.0)
                await db.flush()
                return {
                    "attempt_id": str(attempt.id),
                    "status": "awaiting_continue",
                    "visible_offset": attempt.visible_offset,
                }
        is_clarification = bool(
            attempt.request_kind == "opening"
            and metadata is not None
            and metadata.response_kind == "clarification"
            and not journey.setup_clarification_used
        )
        suggestions = []
        if (
            metadata is not None
            and journey.action_options_enabled
            and not is_see_sea_step
            and not is_clarification
        ):
            suggestions = [
                suggestion.model_dump() for suggestion in metadata.action_suggestions[:3]
            ]
        node = InteractionMessageNode(
            novel_id=journey.novel_id,
            journey_id=journey.id,
            parent_node_id=attempt.response_to_node_id,
            role="assistant",
            message_kind="setup" if is_clarification else "story",
            content=attempt.visible_text,
            completion_state=completion_state,
            end_reason=finish_reason or "stop",
            branch_hint=(
                metadata.branch_hint[:40]
                if metadata is not None and metadata.branch_hint
                else self._service._branch_hint(attempt.visible_text)
            ),
            story_ended=(
                bool(metadata.story_ended)
                if metadata is not None and not is_clarification
                else False
            ),
            action_suggestions=suggestions,
            token_estimate=estimate_story_tokens(attempt.visible_text),
            origin_attempt_id=attempt.id,
        )
        db.add(node)
        await db.flush()
        attempt.result_node_id = node.id
        attempt.status = terminal_status
        attempt.metadata_text = ""
        selected = selection_is_current
        if selected:
            await self._repo.set_selected_child(
                db,
                journey=journey,
                parent_node_id=attempt.response_to_node_id,
                child_node_id=node.id,
            )
            journey.selected_leaf_node_id = node.id
            journey.selection_epoch += 1
            if is_clarification:
                journey.setup_clarification_used = True
        if (
            selected
            and not is_clarification
            and attempt.request_kind in {"opening", "setup_continue"}
            and metadata is not None
            and metadata.suggested_title
            and journey.title_source == "fallback"
        ):
            journey.title = metadata.suggested_title[:255]
            journey.title_source = "model"
        if selected and node.story_ended:
            journey.see_sea_enabled = False
            journey.see_sea_last_heartbeat_at = None
        if is_see_sea_step and not self._service._see_sea_is_authorized(journey):
            # Leaving the page or choosing "stop after this beat" revokes
            # authorization without cancelling the in-flight text.  Once that
            # beat is formalized, persist the loop as closed so returning to
            # the journey cannot resume it implicitly.
            journey.see_sea_enabled = False
            journey.see_sea_last_heartbeat_at = None
        self._repo.touch(journey)

        summary_task_id = None
        next_attempt_id = None
        if selected and not is_clarification:
            current_path = await self._repo.get_selected_path(db, journey=journey)
            await self._service._activate_best_overview_head(
                db,
                journey=journey,
                path=current_path,
            )
            if await self._summary_is_due(db, journey, current_path):
                summary_task_id = await self._enqueue_summary(
                    db,
                    journey=journey,
                    path=current_path,
                    snapshot=attempt.llm_execution_snapshot,
                )
            # Leave an explicit beat boundary after formalization. The
            # foreground heartbeat may create the successor, while a manual
            # send/regenerate/retry can claim the newly free path first.
        task.update_progress(1.0)
        await db.flush()
        return {
            "attempt_id": str(attempt.id),
            "node_id": str(node.id),
            "status": terminal_status,
            "selected": selected,
            "summary_task_id": summary_task_id,
            "next_attempt_id": next_attempt_id,
        }

    async def fail_story_task(
        self,
        db: AsyncSession,
        *,
        task: Any,
        error: Exception,
    ) -> None:
        require_task_checkpoint_session(db)
        novel_id, journey_id, attempt_id = self._task_ids(task)
        try:
            await require_interaction_project(db, novel_id)
            journey = await self._repo.get_journey_for_task(
                db,
                journey_id=journey_id,
                novel_id=uuid.UUID(novel_id),
                for_update=True,
            )
            if journey is None:
                await db.rollback()
                return
            attempt = await self._repo.get_attempt_for_task(
                db,
                journey=journey,
                attempt_id=attempt_id,
                task_id=uuid.UUID(str(task.id)),
                for_update=True,
            )
            if attempt is None or attempt.status not in {
                "pending",
                "preparing_context",
                "running",
            }:
                await db.rollback()
                return
            kind, message = self._safe_story_error(error)
            attempt.status = "failed"
            attempt.error_kind = kind
            attempt.error_message = message
            attempt.finish_reason = "provider_error"
            attempt.metadata_text = ""
            if self._attempt_is_see_sea_step(attempt):
                journey.see_sea_enabled = False
                journey.see_sea_last_heartbeat_at = None
            await db.commit()
            db.expire_all()
        except Exception:
            await db.rollback()

    async def prepare_summary_task(
        self,
        db: AsyncSession,
        *,
        task: Any,
    ) -> PreparedSummaryGeneration | None:
        require_task_checkpoint_session(db)
        meta = dict(task.meta or {})
        novel_id = str(meta.get("novel_id") or "")
        journey_id = uuid.UUID(str(meta.get("journey_id") or ""))
        expected_path_hash = str(meta.get("path_hash") or "")
        legacy_node_ids = [str(value) for value in (meta.get("node_ids") or [])]
        selected_leaf_node_id = str(
            meta.get("selected_leaf_node_id")
            or (legacy_node_ids[-1] if legacy_node_ids else "")
        )
        started_epoch = int(meta.get("started_overview_epoch", -1))
        if (
            not novel_id
            or not expected_path_hash
            or not selected_leaf_node_id
            or started_epoch < 0
        ):
            raise RuntimeError("interaction summary task metadata is invalid")
        await require_interaction_project(db, novel_id)
        journey = await self._repo.get_journey_for_task(
            db,
            journey_id=journey_id,
            novel_id=uuid.UUID(novel_id),
            for_update=False,
        )
        if journey is None:
            raise RuntimeError("interaction journey is not active")
        current_path = await self._repo.get_selected_path(db, journey=journey)
        if (
            path_hash(current_path) != expected_path_hash
            or not current_path
            or str(current_path[-1].id) != selected_leaf_node_id
            or journey.overview_epoch != started_epoch
        ):
            if current_path and await self._summary_is_due(db, journey, current_path):
                await self._enqueue_summary(
                    db,
                    journey=journey,
                    path=current_path,
                    snapshot=dict(meta.get("llm_execution_snapshot") or {}),
                )
            task.update_progress(1.0)
            await db.commit()
            db.expire_all()
            return None
        prepared = await self._prepare_summary_generation(
            db,
            journey=journey,
            current_path=current_path,
            expected_path_hash=expected_path_hash,
            started_epoch=started_epoch,
            snapshot=dict(meta.get("llm_execution_snapshot") or {}),
        )
        if prepared is None:
            task.update_progress(1.0)
            await db.commit()
            db.expire_all()
            return None
        task.update_progress(0.1)
        await db.commit()
        db.expire_all()
        return prepared

    async def _prepare_summary_generation(
        self,
        db: AsyncSession,
        *,
        journey: InteractionJourney,
        current_path: list[InteractionMessageNode],
        expected_path_hash: str,
        started_epoch: int,
        snapshot: dict[str, Any],
        origin_attempt_id: str | None = None,
        origin_task_id: str | None = None,
    ) -> PreparedSummaryGeneration | None:
        head = await self._repo.get_overview_head(db, journey=journey)
        best_head = await self._service._best_overview_for_path(
            db,
            journey=journey,
            path=current_path,
        )
        if (head is None) != (best_head is None) or (
            head is not None and best_head is not None and head.id != best_head.id
        ):
            return None
        valid_head = None
        start_index = 0
        if (
            head is not None
            and self._service._overview_matches_path(head, current_path)
            and self._service._overview_coverage_matches_path(
                head,
                current_path,
            )
        ):
            current_ids = [node.id for node in current_path]
            coverage_anchor = self._service._overview_coverage_anchor(head)
            anchor_index = current_ids.index(coverage_anchor)
            start_index = anchor_index + 1
            valid_head = head
        uncovered = current_path[start_index:]
        prefix_end = _summary_compressible_prefix_end(uncovered)
        compressible = uncovered[:prefix_end]
        protected = uncovered[prefix_end:]
        if not compressible:
            return None
        capability = capability_from_execution_snapshot(snapshot)
        overview_text = (
            render_overview_sections(valid_head.sections) if valid_head else ""
        )
        overview_block = (
            f"已有总回顾：\n{overview_text}\n\n"
            if overview_text
            else "已有总回顾：\n（尚未形成）\n\n"
        )
        manual_ancestor = (
            await self._service._overview_manual_ancestor(
                db,
                journey=journey,
                current=valid_head,
            )
            if valid_head is not None
            else None
        )
        manual_guard = (
            "当前回顾沿用户手工修正继续；合并原始故事时不得恢复该修正"
            "删除或改写的旧当前值，后续明确发生的新变化仍可更新。\n\n"
            if manual_ancestor is not None
            else ""
        )
        system_message = LLMMessage(role="system", content=summary_system_prompt())
        working_chunk: list[InteractionMessageNode] = []
        chunk: list[InteractionMessageNode] = []
        messages: list[LLMMessage] = []
        estimated_input_tokens = 0
        for index, node in enumerate(compressible):
            candidate = [*working_chunk, node]
            transcript = "\n\n".join(
                (
                    f"{'开场设定' if item.role == 'user' else '开场说明'}：{item.content}"
                    if item.message_kind == "setup"
                    else f"{'用户' if item.role == 'user' else '故事'}：{item.content}"
                )
                for item in candidate
            )
            prompt = overview_block + manual_guard + f"需要合并的新故事：\n{transcript}"
            candidate_messages = [
                system_message,
                LLMMessage(role="user", content=prompt),
            ]
            candidate_tokens = max(
                estimate_input_tokens(
                    candidate_messages,
                    model=capability.model,
                ),
                len(system_message.content)
                + len(overview_text)
                + sum(max(1, item.token_estimate) for item in candidate)
                + 64,
            )
            if candidate_tokens > capability.summary_input_ceiling_tokens:
                if not chunk:
                    raise InteractionContextBudgetError(
                        "one interaction node or dialogue beat exceeds "
                        "the summary input budget"
                    )
                break
            working_chunk = candidate
            next_node = compressible[index + 1] if index + 1 < len(compressible) else None
            if (
                node.role == "user"
                and next_node is not None
                and next_node.role == "assistant"
            ):
                continue
            chunk = list(working_chunk)
            messages = candidate_messages
            estimated_input_tokens = candidate_tokens
        if not chunk:
            return None
        executable = await restore_project_llm_execution_settings(
            db,
            str(journey.novel_id),
            snapshot,
        )
        current_ids = [node.id for node in current_path]
        chunk_end_index = current_ids.index(chunk[-1].id)
        chunk_path_hash = path_hash(current_path[: chunk_end_index + 1])
        compaction_source_tokens = (
            estimate_story_tokens(overview_text)
            + sum(max(1, node.token_estimate) for node in chunk)
            + 16
        )
        return PreparedSummaryGeneration(
            novel_id=str(journey.novel_id),
            journey_id=str(journey.id),
            path_hash=expected_path_hash,
            node_ids=[str(node.id) for node in current_path],
            segment_node_ids=[str(node.id) for node in chunk],
            started_overview_epoch=started_epoch,
            messages=messages,
            executable_settings=executable,
            estimated_input_tokens=estimated_input_tokens,
            segment_path_hash=chunk_path_hash,
            protected_node_ids=[str(node.id) for node in protected],
            compaction_source_tokens=compaction_source_tokens,
            origin_attempt_id=origin_attempt_id,
            origin_task_id=origin_task_id,
        )

    async def finalize_summary_task(
        self,
        db: AsyncSession,
        *,
        task: Any,
        prepared: PreparedSummaryGeneration,
        output: InteractionSummaryOutput,
        diagnostics: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        require_task_checkpoint_session(db)
        await require_interaction_project(db, prepared.novel_id)
        journey = await self._repo.get_journey_for_task(
            db,
            journey_id=uuid.UUID(prepared.journey_id),
            novel_id=uuid.UUID(prepared.novel_id),
            for_update=True,
        )
        if journey is None:
            raise RuntimeError("interaction journey is not active")
        origin_attempt = None
        if prepared.origin_attempt_id is not None:
            if prepared.origin_task_id != str(task.id):
                raise RuntimeError("interaction urgent summary task fence mismatch")
            origin_attempt = await self._repo.get_attempt_for_task(
                db,
                journey=journey,
                attempt_id=uuid.UUID(prepared.origin_attempt_id),
                task_id=uuid.UUID(prepared.origin_task_id),
                for_update=True,
            )
            if origin_attempt is None or origin_attempt.status != "preparing_context":
                task.update_progress(0.12)
                return {"status": "stale"}
        current_path = await self._repo.get_selected_path(db, journey=journey)
        if (
            path_hash(current_path) != prepared.path_hash
            or [str(node.id) for node in current_path] != prepared.node_ids
            or journey.overview_epoch != prepared.started_overview_epoch
        ):
            if current_path and await self._summary_is_due(db, journey, current_path):
                await self._enqueue_summary(
                    db,
                    journey=journey,
                    path=current_path,
                    snapshot=dict((task.meta or {}).get("llm_execution_snapshot") or {}),
                )
            if origin_attempt is not None:
                origin_attempt.status = "cancelled"
                origin_attempt.finish_reason = "context_changed"
                origin_attempt.error_kind = None
                origin_attempt.error_message = None
                task.update_progress(0.12)
                await db.commit()
                db.expire_all()
            else:
                task.update_progress(1.0)
            return {"status": "stale"}
        segment_ids = self._parse_node_ids(prepared.segment_node_ids)
        by_id = {node.id: node for node in current_path}
        try:
            segment_nodes = [by_id[node_id] for node_id in segment_ids]
        except KeyError as exc:
            raise RuntimeError(
                "interaction summary segment is no longer available"
            ) from exc
        if not segment_nodes:
            raise RuntimeError("interaction summary returned an empty segment")
        current_ids = [node.id for node in current_path]
        segment_positions = [current_ids.index(node.id) for node in segment_nodes]
        if segment_positions != list(
            range(segment_positions[0], segment_positions[-1] + 1)
        ):
            raise RuntimeError("interaction summary segment must be contiguous")
        previous = await self._repo.get_overview_head(db, journey=journey)
        expected_start_index = 0
        if previous is not None:
            if not (
                self._service._overview_matches_path(previous, current_path)
                and self._service._overview_coverage_matches_path(
                    previous,
                    current_path,
                )
            ):
                raise RuntimeError("interaction summary overview is not path-compatible")
            expected_start_index = (
                current_ids.index(self._service._overview_coverage_anchor(previous)) + 1
            )
        if segment_positions[0] != expected_start_index:
            raise RuntimeError(
                "interaction summary segment must start after current overview coverage"
            )
        segment_end_index = segment_positions[-1]
        segment_path_hash = path_hash(current_path[: segment_end_index + 1])
        if segment_path_hash != (prepared.segment_path_hash or prepared.path_hash):
            raise RuntimeError("interaction summary prefix hash mismatch")
        protected_ids = self._parse_node_ids(
            prepared.protected_node_ids,
            allow_empty=True,
        )
        if any(
            node_id not in current_ids or current_ids.index(node_id) <= segment_end_index
            for node_id in protected_ids
        ):
            raise RuntimeError("interaction summary protected suffix mismatch")
        if prepared.compaction_source_tokens:
            output_tokens = (
                estimate_story_tokens(render_overview_sections(output.overview)) + 16
            )
            if output_tokens > (
                prepared.compaction_source_tokens - _SUMMARY_MIN_SAVINGS_TOKENS
            ):
                raise InteractionContextBudgetError(
                    "interaction summary did not reduce the selected prefix"
                )
        if previous is not None:
            previous.promoted = False
        existing_segments = await self._repo.list_summary_segments(
            db,
            journey=journey,
        )
        prefix_hashes = {
            node.id: path_hash(current_path[: index + 1])
            for index, node in enumerate(current_path)
        }
        applicable_segments = [
            segment
            for segment in existing_segments
            if prefix_hashes.get(segment.end_node_id) == segment.path_hash
        ]
        segment = next(
            (
                item
                for item in applicable_segments
                if getattr(item, "id", None) is not None
                and item.end_node_id == segment_nodes[-1].id
                and item.path_hash == segment_path_hash
            ),
            None,
        )
        segment_reused = segment is not None
        ordinal = segment.ordinal if segment is not None else len(applicable_segments) + 1
        producer = self._summary_producer(prepared, diagnostics)
        if segment is not None:
            producer = {
                **producer,
                "summary_segment_reuse": {
                    "segment_id": str(segment.id),
                    "exact_range": segment.start_node_id == segment_nodes[0].id,
                    "folded_range": {
                        "start_node_id": str(segment_nodes[0].id),
                        "end_node_id": str(segment_nodes[-1].id),
                        "path_hash": segment_path_hash,
                    },
                },
            }
        revision_id = uuid.uuid4()
        if segment is None:
            segment = InteractionSummarySegment(
                novel_id=journey.novel_id,
                journey_id=journey.id,
                start_node_id=segment_nodes[0].id,
                end_node_id=segment_nodes[-1].id,
                path_hash=segment_path_hash,
                based_on_overview_revision_id=previous.id if previous else None,
                token_count=sum(node.token_estimate for node in segment_nodes),
                content=output.segment_summary,
                ordinal=ordinal,
                producer=producer,
            )
        revision = InteractionOverviewRevision(
            id=revision_id,
            novel_id=journey.novel_id,
            journey_id=journey.id,
            anchor_node_id=segment_nodes[-1].id,
            path_hash=segment_path_hash,
            coverage_anchor_node_id=segment_nodes[-1].id,
            coverage_path_hash=segment_path_hash,
            sections=output.overview.model_dump(),
            source="automatic",
            based_on_revision_id=previous.id if previous else None,
            started_overview_epoch=prepared.started_overview_epoch,
            promoted=True,
            producer=producer,
        )
        db.add_all([revision] if segment_reused else [segment, revision])
        await db.flush()
        journey.overview_head_revision_id = revision.id
        journey.overview_epoch += 1
        journey.overview_failure = {}
        if origin_attempt is not None:
            origin_attempt.status = "pending"
            origin_attempt.error_kind = None
            origin_attempt.error_message = None
            origin_attempt.finish_reason = None
            task.update_progress(0.12)
        else:
            task.update_progress(1.0)
        await db.flush()
        result = {
            "status": "completed",
            "overview_revision_id": str(revision.id),
            "segment_id": str(segment.id),
        }
        if origin_attempt is not None:
            await db.commit()
            db.expire_all()
            result["story_resume"] = True
        return result

    async def _summary_is_due(
        self,
        db: AsyncSession,
        journey: InteractionJourney,
        current_path: list[InteractionMessageNode],
    ) -> bool:
        return await self._service._overview_refresh_is_due(
            db,
            journey=journey,
            path=current_path,
        )

    async def mark_summary_failed(
        self,
        db: AsyncSession,
        *,
        task: Any,
        prepared: PreparedSummaryGeneration,
    ) -> None:
        require_task_checkpoint_session(db)
        journey = await self._repo.get_journey_for_task(
            db,
            journey_id=uuid.UUID(prepared.journey_id),
            novel_id=uuid.UUID(prepared.novel_id),
            for_update=True,
        )
        if journey is None:
            await db.rollback()
            return
        current_path = await self._repo.get_selected_path(db, journey=journey)
        if (
            path_hash(current_path) == prepared.path_hash
            and [str(node.id) for node in current_path] == prepared.node_ids
            and journey.overview_epoch == prepared.started_overview_epoch
        ):
            journey.overview_failure = {
                "path_hash": prepared.path_hash,
                "anchor_node_id": (prepared.node_ids[-1] if prepared.node_ids else None),
            }
        task.update_progress(1.0)
        await db.commit()
        db.expire_all()

    async def mark_summary_task_failed(
        self,
        db: AsyncSession,
        *,
        task: Any,
    ) -> None:
        """Latch a summary failure even when preparation/client creation failed."""
        require_task_checkpoint_session(db)
        meta = dict(task.meta or {})
        try:
            novel_id = uuid.UUID(str(meta.get("novel_id") or ""))
            journey_id = uuid.UUID(str(meta.get("journey_id") or ""))
            expected_path_hash = str(meta.get("path_hash") or "")
            legacy_node_ids = [str(value) for value in (meta.get("node_ids") or [])]
            selected_leaf_node_id = str(
                meta.get("selected_leaf_node_id")
                or (legacy_node_ids[-1] if legacy_node_ids else "")
            )
            started_epoch = int(meta.get("started_overview_epoch", -1))
        except (TypeError, ValueError):
            return
        if not expected_path_hash or not selected_leaf_node_id or started_epoch < 0:
            return
        journey = await self._repo.get_journey_for_task(
            db,
            journey_id=journey_id,
            novel_id=novel_id,
            for_update=True,
        )
        if journey is None:
            await db.rollback()
            return
        current_path = await self._repo.get_selected_path(
            db,
            journey=journey,
        )
        if (
            current_path
            and str(current_path[-1].id) == selected_leaf_node_id
            and path_hash(current_path) == expected_path_hash
            and journey.overview_epoch == started_epoch
        ):
            journey.overview_failure = {
                "path_hash": expected_path_hash,
                "anchor_node_id": selected_leaf_node_id,
            }
        task.update_progress(1.0)
        await db.commit()
        db.expire_all()

    async def _enqueue_summary(
        self,
        db: AsyncSession,
        *,
        journey: InteractionJourney,
        path: list[InteractionMessageNode],
        snapshot: dict[str, Any],
    ) -> str:
        contract = await enqueue_coalesced_task(
            db,
            task_type="interaction_summary_refresh",
            novel_id=str(journey.novel_id),
            scope=("interaction_summary", str(journey.id)),
            mode="one_pending_follower",
            meta={
                "novel_id": str(journey.novel_id),
                "journey_id": str(journey.id),
                "path_hash": path_hash(path),
                "selected_leaf_node_id": str(path[-1].id),
                "started_overview_epoch": journey.overview_epoch,
                "llm_execution_snapshot": dict(snapshot),
            },
        )
        return contract.task_id

    @staticmethod
    def _task_ids(task: Any) -> tuple[str, uuid.UUID, uuid.UUID]:
        meta = dict(task.meta or {})
        novel_id = str(meta.get("novel_id") or "")
        try:
            journey_id = uuid.UUID(str(meta.get("journey_id") or ""))
            attempt_id = uuid.UUID(str(meta.get("attempt_id") or ""))
        except ValueError as exc:
            raise RuntimeError("interaction story task metadata is invalid") from exc
        if not novel_id:
            raise RuntimeError("interaction story task novel_id is required")
        return novel_id, journey_id, attempt_id

    @staticmethod
    def _parse_node_ids(
        values: list[str],
        *,
        allow_empty: bool = False,
    ) -> list[uuid.UUID]:
        try:
            parsed = [uuid.UUID(str(value)) for value in values]
        except ValueError as exc:
            raise RuntimeError("interaction context node ids are invalid") from exc
        if not parsed and not allow_empty:
            raise RuntimeError("interaction context path is empty")
        if len(set(parsed)) != len(parsed):
            raise RuntimeError("interaction context path contains duplicate nodes")
        return parsed

    @staticmethod
    def _validate_context_chain(
        nodes: list[InteractionMessageNode],
        attempt: InteractionGenerationAttempt,
    ) -> None:
        if not nodes or nodes[-1].id != attempt.response_to_node_id:
            raise RuntimeError("interaction response target is not the context leaf")
        for index, node in enumerate(nodes):
            expected_parent = nodes[index - 1].id if index else None
            if node.parent_node_id != expected_parent:
                raise RuntimeError("interaction context path is not contiguous")
        if path_hash(nodes) != attempt.context_path_hash:
            raise RuntimeError("interaction context path hash mismatch")

    @staticmethod
    def _safe_story_error(error: Exception) -> tuple[str, str]:
        if isinstance(error, InteractionContextBudgetError):
            default_message = (
                "作品资料暂时无法安全引用，请查看作品资料调整后重试"
                if error.kind == "source_context_blocked"
                else "当前故事暂时无法在安全范围内继续，请查看并精简回顾后重试"
            )
            return error.kind, error.user_message or default_message
        if isinstance(error, (LLMAuthError, ProjectLLMConfigurationError)):
            return "configuration", "模型连接不可用，请到账户设置检查 Key"
        if isinstance(error, LLMQuotaError):
            return "quota", "模型额度不足，请在模型服务账户中确认余额后再试"
        if isinstance(error, LLMRateLimitError):
            return "rate_limit", "模型服务当前繁忙，请稍后重新生成"
        if isinstance(error, LLMTimeoutError):
            return "timeout", "这次生成超时，请重新生成"
        if isinstance(error, LLMConnectionError):
            return "connection", "模型连接中断，这段残留内容尚未进入故事"
        if isinstance(error, LLMContentFilterError):
            return "content_filter", "这次内容未能生成，请换一种说法后重试"
        return "generation_failed", "这次生成未完成，请重新生成"

    @staticmethod
    def _attempt_is_see_sea_step(
        attempt: InteractionGenerationAttempt,
    ) -> bool:
        return attempt.request_kind in {
            "see_sea",
            "see_sea_continue",
        } or bool((attempt.usage or {}).get("see_sea_adopted"))

    @staticmethod
    def _summary_producer(
        prepared: PreparedSummaryGeneration,
        diagnostics: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        profile = dict(prepared.executable_settings.get("llm") or {})
        usage_entries = [
            item for item in (diagnostics or []) if item.get("kind") == "structured_usage"
        ]
        return {
            "kind": "model",
            "provider_id": str(profile.get("provider_id") or ""),
            "model": str(profile.get("model") or ""),
            "prompt_version": SUMMARY_PROMPT_VERSION,
            "schema_version": SUMMARY_SCHEMA_VERSION,
            "estimated_input_tokens": prepared.estimated_input_tokens,
            "completion_tokens": sum(
                max(0, int(item.get("completion_tokens") or 0)) for item in usage_entries
            ),
            "call_attempts": len(usage_entries),
        }


def story_request(prepared: PreparedStoryGeneration) -> LLMCallRequest:
    profile = dict(prepared.executable_settings.get("llm") or {})
    capability = capability_from_execution_settings(prepared.executable_settings)
    output_limit = (
        capability.see_sea_output_tokens
        if prepared.see_sea_step
        or prepared.request_kind in {"see_sea", "see_sea_continue"}
        else capability.story_output_tokens
    )
    return LLMCallRequest(
        model=str(profile.get("model") or ""),
        messages=prepared.messages,
        temperature=float(profile.get("temperature", 0.8) or 0.8),
        max_tokens=min(
            int(profile.get("max_tokens") or output_limit),
            output_limit,
        ),
    )


def summary_request(prepared: PreparedSummaryGeneration) -> LLMCallRequest:
    profile = dict(prepared.executable_settings.get("llm") or {})
    capability = capability_from_execution_settings(prepared.executable_settings)
    return LLMCallRequest(
        model=str(profile.get("model") or ""),
        messages=prepared.messages,
        temperature=0.2,
        max_tokens=min(
            int(profile.get("max_tokens") or capability.summary_output_tokens),
            capability.summary_output_tokens,
        ),
        response_format={"type": "json_object"},
    )
