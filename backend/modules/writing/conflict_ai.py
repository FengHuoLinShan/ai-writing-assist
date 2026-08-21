"""AI review and suggestion services for writing conflict checks."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import NotFoundError, ValidationError
from infrastructure.llm.agent_step_harness import run_managed_structured
from infrastructure.llm.client import LLMClient
from infrastructure.llm.redaction import redact_diagnostic
from infrastructure.llm.schemas import LLMCallRequest, LLMMessage
from modules.writing.repositories import (
    AI_REVIEW_TASK_OWNER_KEY,
    WritingConflictCheckRepository,
    public_conflict_summary,
)
from modules.writing.schemas import (
    WritingConflictAiReviewIssue,
    WritingConflictAiReviewRawOutput,
    WritingConflictSuggestionOutput,
)
from shared.utils import parse_uuid as _shared_parse_uuid

logger = logging.getLogger(__name__)

AI_REVIEW_ACTION = "writing.conflict_check.ai_review"
AI_SUGGESTION_ACTION = "writing.conflict_check.ai_suggestion"
_TASK_STALE_ERROR = (
    "Conflict review inputs changed while the task was running; discarded stale result"
)


@dataclass(frozen=True)
class _TaskCheckIdentity:
    id: str


@dataclass(frozen=True)
class _ConflictReviewTaskPlan:
    novel_id: str
    check_id: str
    confirmation_id: str
    task_id: str
    prompt: str
    include_pending_objects: bool
    source_fingerprint: str
    check_identity: _TaskCheckIdentity


@dataclass(frozen=True)
class _ConflictSuggestionTaskPlan:
    novel_id: str
    item_id: str
    confirmation_id: str
    prompt: str
    source_fingerprint: str


def _parse_uuid(value: str, field_name: str) -> uuid.UUID:
    return _shared_parse_uuid(value, field_name)


class ConflictCheckAiReviewService:
    """Append LLM soft-conflict judgments to an existing check."""

    def __init__(
        self,
        repo: WritingConflictCheckRepository,
        llm_client: LLMClient | None = None,
    ) -> None:
        self._repo = repo
        self._llm = llm_client

    @asynccontextmanager
    async def _open_task_llm_client(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        llm_execution_snapshot: dict[str, Any],
    ) -> AsyncIterator[LLMClient]:
        if self._llm is not None:
            yield self._llm
            return
        if not isinstance(llm_execution_snapshot, dict) or not llm_execution_snapshot:
            raise ValueError(
                "llm_execution_snapshot is required for conflict review tasks"
            )

        from modules.project.facade import (
            create_project_snapshot_llm_client,
            restore_project_llm_execution_settings,
        )

        settings = await restore_project_llm_execution_settings(
            db,
            novel_id,
            llm_execution_snapshot,
        )
        client = create_project_snapshot_llm_client(settings, novel_id=novel_id)
        try:
            yield client
        finally:
            await client.close()

    async def run(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        check_id: str,
        context_confirmation_id: str,
    ) -> tuple[object, list[object]]:
        from modules.evidence.facade import (
            bind_confirmed_action_result,
            prepare_confirmed_ai_action,
        )

        nid = _parse_uuid(novel_id, "novel_id")
        cid = _parse_uuid(check_id, "check_id")
        confirmation_uuid = _parse_uuid(
            context_confirmation_id,
            "context_confirmation_id",
        )
        # The synchronous endpoint deliberately keeps its historical
        # single-transaction behavior.  Locking the review target up front
        # makes request order deterministic: a later async enqueue cannot bind
        # a new owner and then have this older request erase it from a stale
        # identity-map snapshot.
        existing = await self._repo.get_check_for_ai_review_update(db, cid, nid)
        if existing is None:
            raise NotFoundError("Conflict check not found")
        check, current_items = existing

        try:
            confirmed_context = await prepare_confirmed_ai_action(
                db,
                novel_id=novel_id,
                action=AI_REVIEW_ACTION,
                confirmation_id=context_confirmation_id,
            )
            _validate_confirmation_scope(confirmed_context.confirmation, check)
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc

        if self._llm is None:
            from modules.project.facade import open_project_llm_client

            async with open_project_llm_client(db, novel_id) as client:
                return await ConflictCheckAiReviewService(
                    self._repo,
                    llm_client=client,
                ).run(
                    db,
                    novel_id=novel_id,
                    check_id=check_id,
                    context_confirmation_id=context_confirmation_id,
                )

        await self._repo.update_ai_review(
            db,
            check_id=cid,
            novel_id=nid,
            status="running",
            summary_json=_summary_without_task_runtime(check.summary_json),
            confirmation_id=confirmation_uuid,
            model=getattr(self._llm, "model_name", None),
            error=None,
        )

        try:
            output = await run_managed_structured(
                self._llm,
                LLMCallRequest(
                    model=getattr(self._llm, "model_name", "deepseek-v4-flash"),
                    messages=[
                        LLMMessage(
                            role="system",
                            content=_AI_REVIEW_SYSTEM_PROMPT,
                        ),
                        LLMMessage(
                            role="user",
                            content=_build_ai_review_prompt(
                                check=check,
                                items=current_items,
                                context_markdown=confirmed_context.rendered_markdown,
                            ),
                        ),
                    ],
                    temperature=0.2,
                ),
                WritingConflictAiReviewRawOutput,
                step_name="writing.conflict_check.ai_review.structured",
            )
            ai_items, discarded_count = _ai_review_items(
                output,
                check=check,
                confirmation_id=confirmation_uuid,
                include_pending_objects=(
                    confirmed_context.confirmation.include_pending_objects
                ),
            )
            appended_items: list[object] = []
            if ai_items:
                appended_items = await self._repo.append_items(
                    db,
                    check_id=cid,
                    novel_id=nid,
                    items=ai_items,
                )
            items = _sort_conflict_items([*current_items, *appended_items])
            status = "partial" if discarded_count else "done"
            summary_json = _summary_with_ai_review(
                items,
                check.summary_json or {},
                status=status,
                discarded_count=discarded_count,
            )
            updated = await self._repo.update_ai_review(
                db,
                check_id=cid,
                novel_id=nid,
                status=status,
                summary_json=summary_json,
                confirmation_id=confirmation_uuid,
                model=getattr(self._llm, "model_name", None),
                error=None,
            )
            await bind_confirmed_action_result(
                db,
                novel_id=novel_id,
                confirmation_id=context_confirmation_id,
                result_type="writing_conflict_check",
                result_id=check_id,
                status=status,
            )
            return updated or check, items
        except Exception as exc:  # LLM/context failures degrade AI only.
            safe_error = redact_diagnostic(exc, limit=500)
            logger.warning("AI conflict review failed: %s", safe_error)
            items = await self._repo.list_items(db, cid, nid)
            summary_json = _summary_with_ai_review(
                items,
                check.summary_json or {},
                status="failed",
                discarded_count=0,
            )
            updated = await self._repo.update_ai_review(
                db,
                check_id=cid,
                novel_id=nid,
                status="failed",
                summary_json=summary_json,
                confirmation_id=confirmation_uuid,
                model=getattr(self._llm, "model_name", None),
                error=safe_error,
            )
            try:
                await bind_confirmed_action_result(
                    db,
                    novel_id=novel_id,
                    confirmation_id=context_confirmation_id,
                    result_type="writing_conflict_check",
                    result_id=check_id,
                    status="failed",
                )
            except ValueError:
                logger.warning("Failed to attach AI review result ref")
            return updated or check, items

    async def run_for_task(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        check_id: str,
        context_confirmation_id: str,
        task_id: str,
        llm_execution_snapshot: dict[str, Any],
        allow_unowned_legacy: bool = False,
        finalize_transient_failure: bool = True,
    ) -> tuple[object, list[object]]:
        """Run task review with the provider wait outside any DB transaction."""
        from infrastructure.tasks.facade import require_task_checkpoint_session

        require_task_checkpoint_session(db)
        prepared = await self._prepare_task_review(
            db,
            novel_id=novel_id,
            check_id=check_id,
            context_confirmation_id=context_confirmation_id,
            task_id=task_id,
            allow_unowned_legacy=allow_unowned_legacy,
        )
        if not isinstance(prepared, _ConflictReviewTaskPlan):
            return prepared

        model: str | None = None
        try:
            async with self._open_task_llm_client(
                db,
                novel_id=novel_id,
                llm_execution_snapshot=llm_execution_snapshot,
            ) as client:
                model = getattr(client, "model_name", None)
                await self._checkpoint_before_external_call(db)
                output = await self._execute_task_review(client, prepared)
        except asyncio.CancelledError:
            await self._converge_cancelled_task(
                db,
                plan=prepared,
                model=model,
            )
            raise
        except Exception as exc:
            from infrastructure.llm.retry import is_retryable_llm_error

            if is_retryable_llm_error(exc) and not finalize_transient_failure:
                raise
            safe_error = redact_diagnostic(
                f"{type(exc).__name__}: {exc}",
                limit=500,
            )
            logger.warning("AI conflict review task failed: %s", safe_error)
            return await self._finalize_task_failure(
                db,
                plan=prepared,
                model=model,
                error=safe_error,
            )

        return await self._finalize_task_success(
            db,
            plan=prepared,
            output=output,
            model=model,
        )

    async def _prepare_task_review(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        check_id: str,
        context_confirmation_id: str,
        task_id: str,
        allow_unowned_legacy: bool,
    ) -> _ConflictReviewTaskPlan | tuple[object, list[object]]:
        from modules.evidence.facade import prepare_confirmed_ai_action
        from modules.project.facade import require_active_project

        await require_active_project(db, novel_id)
        try:
            confirmed = await prepare_confirmed_ai_action(
                db,
                novel_id=novel_id,
                action=AI_REVIEW_ACTION,
                confirmation_id=context_confirmation_id,
            )
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc

        nid = _parse_uuid(novel_id, "novel_id")
        cid = _parse_uuid(check_id, "check_id")
        confirmation_uuid = _parse_uuid(
            context_confirmation_id,
            "context_confirmation_id",
        )
        existing = await self._repo.get_check_for_ai_review_update(db, cid, nid)
        if existing is None:
            raise NotFoundError("Conflict check not found")
        check, items = existing
        try:
            _validate_confirmation_scope(confirmed.confirmation, check)
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc

        owner = _task_owner(check.summary_json)
        if (
            owner is None
            and allow_unowned_legacy
            and check.ai_review_status == "running"
            and str(check.ai_review_confirmation_id or "") == str(context_confirmation_id)
        ):
            summary = dict(check.summary_json or {})
            summary[AI_REVIEW_TASK_OWNER_KEY] = str(task_id)
            await self._repo.update_loaded_ai_review(
                db,
                check,
                status="running",
                summary_json=summary,
                confirmation_id=confirmation_uuid,
                model=None,
                error=None,
            )
            owner = str(task_id)
        if owner != str(task_id):
            raise ValidationError("Conflict review task was superseded")

        if check.ai_review_status in {"done", "partial", "failed"} and str(
            check.ai_review_confirmation_id or ""
        ) == str(context_confirmation_id):
            return check, items

        prompt = _build_ai_review_prompt(
            check=check,
            items=items,
            context_markdown=str(confirmed.rendered_markdown),
        )
        return _ConflictReviewTaskPlan(
            novel_id=str(novel_id),
            check_id=str(check_id),
            confirmation_id=str(context_confirmation_id),
            task_id=str(task_id),
            prompt=prompt,
            include_pending_objects=bool(confirmed.confirmation.include_pending_objects),
            source_fingerprint=_task_source_fingerprint(confirmed, check, items),
            check_identity=_TaskCheckIdentity(id=str(check.id)),
        )

    @staticmethod
    async def _checkpoint_before_external_call(db: AsyncSession) -> None:
        await db.commit()
        if db.in_transaction():
            raise RuntimeError(
                "conflict review task LLM execution requires a "
                "transaction-free checkpoint"
            )
        db.expire_all()

    @staticmethod
    async def _execute_task_review(
        client: LLMClient,
        plan: _ConflictReviewTaskPlan,
    ) -> WritingConflictAiReviewRawOutput:
        return await run_managed_structured(
            client,
            LLMCallRequest(
                model=getattr(client, "model_name", "deepseek-v4-flash"),
                messages=[
                    LLMMessage(role="system", content=_AI_REVIEW_SYSTEM_PROMPT),
                    LLMMessage(role="user", content=plan.prompt),
                ],
                temperature=0.2,
            ),
            WritingConflictAiReviewRawOutput,
            step_name="writing.conflict_check.ai_review.structured",
        )

    async def _finalize_task_success(
        self,
        db: AsyncSession,
        *,
        plan: _ConflictReviewTaskPlan,
        output: WritingConflictAiReviewRawOutput,
        model: str | None,
    ) -> tuple[object, list[object]]:
        from modules.evidence.facade import (
            bind_confirmed_action_result,
            prepare_confirmed_ai_action,
        )
        from modules.project.facade import require_active_project

        await require_active_project(db, plan.novel_id)
        try:
            confirmed = await prepare_confirmed_ai_action(
                db,
                novel_id=plan.novel_id,
                action=AI_REVIEW_ACTION,
                confirmation_id=plan.confirmation_id,
            )
        except ValueError as exc:
            return await self._finalize_task_failure(
                db,
                plan=plan,
                model=model,
                error=redact_diagnostic(str(exc), limit=500),
            )

        existing = await self._repo.get_check_for_ai_review_update(
            db,
            _parse_uuid(plan.check_id, "check_id"),
            _parse_uuid(plan.novel_id, "novel_id"),
        )
        if existing is None:
            raise NotFoundError("Conflict check not found")
        check, current_items = existing
        if _task_owner(check.summary_json) != plan.task_id:
            raise ValidationError("Conflict review task was superseded")

        try:
            _validate_confirmation_scope(confirmed.confirmation, check)
        except ValueError:
            return await self._write_task_failure_locked(
                db,
                plan=plan,
                check=check,
                items=current_items,
                model=model,
                error=_TASK_STALE_ERROR,
            )

        current_fingerprint = _task_source_fingerprint(
            confirmed,
            check,
            current_items,
        )
        if current_fingerprint != plan.source_fingerprint:
            return await self._write_task_failure_locked(
                db,
                plan=plan,
                check=check,
                items=current_items,
                model=model,
                error=_TASK_STALE_ERROR,
            )

        confirmation_uuid = _parse_uuid(
            plan.confirmation_id,
            "context_confirmation_id",
        )
        ai_items, discarded_count = _ai_review_items(
            output,
            check=plan.check_identity,
            confirmation_id=confirmation_uuid,
            include_pending_objects=plan.include_pending_objects,
        )
        appended_items: list[object] = []
        if ai_items:
            appended_items = await self._repo.append_items(
                db,
                check_id=_parse_uuid(plan.check_id, "check_id"),
                novel_id=_parse_uuid(plan.novel_id, "novel_id"),
                items=ai_items,
            )
        items = _sort_conflict_items([*current_items, *appended_items])
        status = "partial" if discarded_count else "done"
        summary = _summary_with_ai_review(
            items,
            check.summary_json or {},
            status=status,
            discarded_count=discarded_count,
        )
        updated = await self._repo.update_loaded_ai_review(
            db,
            check,
            status=status,
            summary_json=summary,
            confirmation_id=confirmation_uuid,
            model=model,
            error=None,
        )
        await bind_confirmed_action_result(
            db,
            novel_id=plan.novel_id,
            confirmation_id=plan.confirmation_id,
            result_type="writing_conflict_check",
            result_id=plan.check_id,
            status=status,
        )
        return updated, items

    async def _finalize_task_failure(
        self,
        db: AsyncSession,
        *,
        plan: _ConflictReviewTaskPlan,
        model: str | None,
        error: str,
    ) -> tuple[object, list[object]]:
        from modules.project.facade import require_active_project

        await require_active_project(db, plan.novel_id)
        existing = await self._repo.get_check_for_ai_review_update(
            db,
            _parse_uuid(plan.check_id, "check_id"),
            _parse_uuid(plan.novel_id, "novel_id"),
        )
        if existing is None:
            raise NotFoundError("Conflict check not found")
        check, items = existing
        if _task_owner(check.summary_json) != plan.task_id:
            raise ValidationError("Conflict review task was superseded")
        return await self._write_task_failure_locked(
            db,
            plan=plan,
            check=check,
            items=items,
            model=model,
            error=error,
        )

    async def _write_task_failure_locked(
        self,
        db: AsyncSession,
        *,
        plan: _ConflictReviewTaskPlan,
        check: object,
        items: list[object],
        model: str | None,
        error: str,
    ) -> tuple[object, list[object]]:
        from modules.evidence.facade import bind_confirmed_action_result

        safe_error = redact_diagnostic(error, limit=500)
        summary = _summary_with_ai_review(
            items,
            getattr(check, "summary_json", None) or {},
            status="failed",
            discarded_count=0,
        )
        updated = await self._repo.update_loaded_ai_review(
            db,
            check,
            status="failed",
            summary_json=summary,
            confirmation_id=_parse_uuid(
                plan.confirmation_id,
                "context_confirmation_id",
            ),
            model=model,
            error=safe_error,
        )
        try:
            await bind_confirmed_action_result(
                db,
                novel_id=plan.novel_id,
                confirmation_id=plan.confirmation_id,
                result_type="writing_conflict_check",
                result_id=plan.check_id,
                status="failed",
            )
        except ValueError:
            logger.warning("Failed to attach conflict review task failure result")
        return updated, items

    async def _converge_cancelled_task(
        self,
        db: AsyncSession,
        *,
        plan: _ConflictReviewTaskPlan,
        model: str | None,
    ) -> None:
        async def _persist() -> None:
            try:
                await self._finalize_task_failure(
                    db,
                    plan=plan,
                    model=model,
                    error="Conflict review task was cancelled",
                )
                await db.commit()
            except asyncio.CancelledError:
                raise
            except Exception:
                # Deletion or supersession deliberately wins over stale cleanup.
                await db.rollback()

        try:
            await asyncio.shield(_persist())
        except asyncio.CancelledError:
            pass


class ConflictSuggestionService:
    """Generate and persist manual AI repair suggestions for one item."""

    def __init__(
        self,
        repo: WritingConflictCheckRepository,
        llm_client: LLMClient | None = None,
    ) -> None:
        self._repo = repo
        self._llm = llm_client

    async def generate(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        item_id: str,
        context_confirmation_id: str,
    ) -> object:
        from modules.evidence.facade import (
            bind_confirmed_action_result,
            prepare_confirmed_ai_action,
        )

        nid = _parse_uuid(novel_id, "novel_id")
        iid = _parse_uuid(item_id, "item_id")
        confirmation_uuid = _parse_uuid(
            context_confirmation_id,
            "context_confirmation_id",
        )
        item = await self._repo.get_item(db, iid, nid)
        if item is None:
            raise NotFoundError("Conflict item not found")
        check_result = await self._repo.get_check(db, item.check_id, nid)
        if check_result is None:
            raise NotFoundError("Conflict check not found")
        check, check_items = check_result

        try:
            confirmed_context = await prepare_confirmed_ai_action(
                db,
                novel_id=novel_id,
                action=AI_SUGGESTION_ACTION,
                confirmation_id=context_confirmation_id,
            )
            _validate_confirmation_scope(confirmed_context.confirmation, check)
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc

        if self._llm is None:
            from modules.project.facade import open_project_llm_client

            async with open_project_llm_client(db, novel_id) as client:
                return await ConflictSuggestionService(
                    self._repo,
                    llm_client=client,
                ).generate(
                    db,
                    novel_id=novel_id,
                    item_id=item_id,
                    context_confirmation_id=context_confirmation_id,
                )

        await self._repo.update_loaded_item_suggestion(
            db,
            item,
            status="running",
            confirmation_id=confirmation_uuid,
            error=None,
        )

        try:
            output = await run_managed_structured(
                self._llm,
                LLMCallRequest(
                    model=getattr(self._llm, "model_name", "deepseek-v4-flash"),
                    messages=[
                        LLMMessage(
                            role="system",
                            content=_AI_SUGGESTION_SYSTEM_PROMPT,
                        ),
                        LLMMessage(
                            role="user",
                            content=_build_ai_suggestion_prompt(
                                check=check,
                                item=item,
                                items=check_items,
                                context_markdown=confirmed_context.rendered_markdown,
                            ),
                        ),
                    ],
                    temperature=0.3,
                ),
                WritingConflictSuggestionOutput,
                step_name="writing.conflict_check.ai_suggestion.structured",
            )
            suggestion_text = output.suggestion.model_dump_json(ensure_ascii=False)
            updated = await self._repo.update_loaded_item_suggestion(
                db,
                item,
                status="done",
                confirmation_id=confirmation_uuid,
                ai_suggestion=suggestion_text,
                llm_rationale=output.suggestion.rationale,
                error=None,
            )
            await bind_confirmed_action_result(
                db,
                novel_id=novel_id,
                confirmation_id=context_confirmation_id,
                result_type="writing_conflict_item",
                result_id=item_id,
                status="done",
            )
            return updated or item
        except Exception as exc:
            safe_error = redact_diagnostic(exc, limit=500)
            logger.warning("AI conflict suggestion failed: %s", safe_error)
            updated = await self._repo.update_loaded_item_suggestion(
                db,
                item,
                status="failed",
                confirmation_id=confirmation_uuid,
                error=safe_error,
            )
            try:
                await bind_confirmed_action_result(
                    db,
                    novel_id=novel_id,
                    confirmation_id=context_confirmation_id,
                    result_type="writing_conflict_item",
                    result_id=item_id,
                    status="failed",
                )
            except ValueError:
                logger.warning("Failed to attach AI suggestion result ref")
            return updated or item

    async def validate(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        item_id: str,
        context_confirmation_id: str,
    ) -> None:
        await self._prepare_task(
            db,
            novel_id=novel_id,
            item_id=item_id,
            context_confirmation_id=context_confirmation_id,
        )

    async def run_for_task(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        item_id: str,
        context_confirmation_id: str,
        llm_execution_snapshot: dict[str, Any],
        finalize_transient_failure: bool,
    ) -> object:
        from infrastructure.tasks.facade import require_task_checkpoint_session
        from modules.project.facade import (
            create_project_snapshot_llm_client,
            require_active_project,
            restore_project_llm_execution_settings,
        )

        require_task_checkpoint_session(db)
        plan = await self._prepare_task(
            db,
            novel_id=novel_id,
            item_id=item_id,
            context_confirmation_id=context_confirmation_id,
        )
        await db.commit()
        db.expire_all()
        settings = await restore_project_llm_execution_settings(
            db, novel_id, llm_execution_snapshot
        )
        client = create_project_snapshot_llm_client(settings, novel_id=novel_id)
        await db.commit()
        db.expire_all()
        try:
            output = await run_managed_structured(
                client,
                LLMCallRequest(
                    model=getattr(client, "model_name", "deepseek-v4-flash"),
                    messages=[
                        LLMMessage(role="system", content=_AI_SUGGESTION_SYSTEM_PROMPT),
                        LLMMessage(role="user", content=plan.prompt),
                    ],
                    temperature=0.3,
                ),
                WritingConflictSuggestionOutput,
                step_name="writing.conflict_check.ai_suggestion.structured",
            )
        except Exception as exc:
            from infrastructure.llm.retry import is_retryable_llm_error

            if is_retryable_llm_error(exc) and not finalize_transient_failure:
                raise
            await require_active_project(db, novel_id)
            current = await self._prepare_task(
                db,
                novel_id=novel_id,
                item_id=item_id,
                context_confirmation_id=context_confirmation_id,
                for_update=True,
            )
            if current.source_fingerprint != plan.source_fingerprint:
                await self._mark_drifted_suggestion_failed(
                    db,
                    novel_id=novel_id,
                    item_id=item_id,
                    context_confirmation_id=context_confirmation_id,
                )
                raise ValidationError(
                    "Conflict suggestion source changed while task ran"
                ) from exc
            item = await self._repo.get_item(
                db,
                _parse_uuid(item_id, "item_id"),
                _parse_uuid(novel_id, "novel_id"),
                for_update=True,
            )
            if item is None:
                raise NotFoundError("Conflict item not found") from exc
            return await self._repo.update_loaded_item_suggestion(
                db,
                item,
                status="failed",
                confirmation_id=_parse_uuid(
                    context_confirmation_id, "context_confirmation_id"
                ),
                error=redact_diagnostic(exc, limit=500),
            )
        finally:
            await client.close()

        await require_active_project(db, novel_id)
        current = await self._prepare_task(
            db,
            novel_id=novel_id,
            item_id=item_id,
            context_confirmation_id=context_confirmation_id,
            for_update=True,
        )
        if current.source_fingerprint != plan.source_fingerprint:
            await self._mark_drifted_suggestion_failed(
                db,
                novel_id=novel_id,
                item_id=item_id,
                context_confirmation_id=context_confirmation_id,
            )
            raise ValidationError("Conflict suggestion source changed while task ran")
        item = await self._repo.get_item(
            db,
            _parse_uuid(item_id, "item_id"),
            _parse_uuid(novel_id, "novel_id"),
            for_update=True,
        )
        if item is None:
            raise NotFoundError("Conflict item not found")
        updated = await self._repo.update_loaded_item_suggestion(
            db,
            item,
            status="done",
            confirmation_id=_parse_uuid(
                context_confirmation_id, "context_confirmation_id"
            ),
            ai_suggestion=output.suggestion.model_dump_json(ensure_ascii=False),
            llm_rationale=output.suggestion.rationale,
            error=None,
        )
        from modules.evidence.facade import bind_confirmed_action_result

        await bind_confirmed_action_result(
            db,
            novel_id=novel_id,
            confirmation_id=context_confirmation_id,
            result_type="writing_conflict_item",
            result_id=item_id,
            status="done",
        )
        return updated

    async def _mark_drifted_suggestion_failed(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        item_id: str,
        context_confirmation_id: str,
    ) -> None:
        """指纹漂移时回写失败状态，避免 suggestion_status 永久停在 running。"""
        item = await self._repo.get_item(
            db,
            _parse_uuid(item_id, "item_id"),
            _parse_uuid(novel_id, "novel_id"),
            for_update=True,
        )
        if item is None:
            return
        confirmation = _parse_uuid(context_confirmation_id, "context_confirmation_id")
        if item.suggestion_confirmation_id not in (None, confirmation):
            # 建议已被新任务接管：不覆盖新任务的运行状态
            return
        await self._repo.update_loaded_item_suggestion(
            db,
            item,
            status="failed",
            confirmation_id=confirmation,
            error="建议生成期间源内容已变化，请重新发起检查",
        )

    async def _prepare_task(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        item_id: str,
        context_confirmation_id: str,
        for_update: bool = False,
    ) -> _ConflictSuggestionTaskPlan:
        from modules.evidence.facade import prepare_confirmed_ai_action

        nid = _parse_uuid(novel_id, "novel_id")
        item_uuid = _parse_uuid(item_id, "item_id")
        item = await self._repo.get_item(db, item_uuid, nid)
        if item is None:
            raise NotFoundError("Conflict item not found")
        check_result = (
            await self._repo.get_check_for_ai_review_update(db, item.check_id, nid)
            if for_update
            else await self._repo.get_check(db, item.check_id, nid)
        )
        if check_result is None:
            raise NotFoundError("Conflict check not found")
        check, items = check_result
        if for_update:
            item = next((current for current in items if current.id == item_uuid), None)
            if item is None:
                raise NotFoundError("Conflict item not found")
        try:
            confirmed = await prepare_confirmed_ai_action(
                db,
                novel_id=novel_id,
                action=AI_SUGGESTION_ACTION,
                confirmation_id=context_confirmation_id,
            )
            _validate_confirmation_scope(confirmed.confirmation, check)
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        return _ConflictSuggestionTaskPlan(
            novel_id=novel_id,
            item_id=item_id,
            confirmation_id=context_confirmation_id,
            prompt=_build_ai_suggestion_prompt(
                check=check,
                item=item,
                items=items,
                context_markdown=confirmed.rendered_markdown,
            ),
            source_fingerprint=_task_source_fingerprint(confirmed, check, items),
        )


def _task_owner(summary: dict | None) -> str | None:
    value = (summary or {}).get(AI_REVIEW_TASK_OWNER_KEY)
    return str(value) if value else None


def _summary_without_task_runtime(summary: dict | None) -> dict:
    return public_conflict_summary(summary)


def _stable_fingerprint(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _compiled_context_fingerprint(compiled: object) -> dict[str, Any]:
    sections: list[dict[str, Any]] = []
    for section in getattr(compiled, "sections", []):
        retrieval_metadata = dict(getattr(section, "retrieval_metadata", None) or {})
        retrieval_metadata.pop("latency_metadata", None)
        tier = getattr(section, "tier", 0)
        try:
            tier = int(tier)
        except (TypeError, ValueError):
            tier = str(tier)
        sections.append(
            {
                "key": getattr(section, "key", None),
                "tier": tier,
                "content": getattr(section, "content", None),
                "token_count": getattr(section, "token_count", None),
                "status": getattr(section, "status", None),
                "sources": deepcopy(getattr(section, "sources", None) or []),
                "excluded": bool(getattr(section, "excluded", False)),
                "truncated_reason": getattr(section, "truncated_reason", None),
                "retrieval_metadata": deepcopy(retrieval_metadata),
            }
        )
    budget_events: list[Any] = []
    for event in getattr(compiled, "budget_events", []):
        if hasattr(event, "model_dump"):
            budget_events.append(event.model_dump(mode="json"))
        else:
            budget_events.append(deepcopy(event))
    return {
        "sections": sections,
        "total_tokens": getattr(compiled, "total_tokens", None),
        "budget_tokens": getattr(compiled, "budget_tokens", None),
        "evicted_keys": list(getattr(compiled, "evicted_keys", []) or []),
        "truncated_keys": list(getattr(compiled, "truncated_keys", []) or []),
        "budget_events": budget_events,
        "warnings": list(getattr(compiled, "warnings", []) or []),
    }


def _check_semantic_fingerprint(check: object, items: list[object]) -> dict[str, Any]:
    summary = public_conflict_summary(getattr(check, "summary_json", None))
    summary.pop("ai_review", None)
    item_payloads = [
        {
            "id": str(getattr(item, "id", "")),
            "check_id": str(getattr(item, "check_id", "")),
            "novel_id": str(getattr(item, "novel_id", "")),
            "kind": getattr(item, "kind", None),
            "severity": getattr(item, "severity", None),
            "source_module": getattr(item, "source_module", None),
            "source_type": getattr(item, "source_type", None),
            "source_id": getattr(item, "source_id", None),
            "evidence_summary": getattr(item, "evidence_summary", None),
            "location_json": deepcopy(getattr(item, "location_json", None)),
            "is_ai_judgment": bool(getattr(item, "is_ai_judgment", False)),
            "needs_review": bool(getattr(item, "needs_review", False)),
            "confidence": getattr(item, "confidence", None),
            "source_confirmation_id": str(
                getattr(item, "source_confirmation_id", "") or ""
            ),
            "llm_rationale": getattr(item, "llm_rationale", None),
            "status": getattr(item, "status", None),
            "suggestion_status": getattr(item, "suggestion_status", None),
            "suggestion_confirmation_id": str(
                getattr(item, "suggestion_confirmation_id", "") or ""
            ),
            "ai_suggestion": getattr(item, "ai_suggestion", None),
            "suggestion_error": getattr(item, "suggestion_error", None),
        }
        for item in items
    ]
    item_payloads.sort(key=lambda item: item["id"])
    return {
        "id": str(getattr(check, "id", "")),
        "novel_id": str(getattr(check, "novel_id", "")),
        "chapter_index": getattr(check, "chapter_index", None),
        "scene_id": str(getattr(check, "scene_id", "") or ""),
        "draft_id": str(getattr(check, "draft_id", "") or ""),
        "version_number": getattr(check, "version_number", None),
        "scope": deepcopy(getattr(check, "scope", None) or {}),
        "include_candidates": bool(getattr(check, "include_candidates", False)),
        "status": getattr(check, "status", None),
        "summary_json": summary,
        "items": item_payloads,
    }


def _task_source_fingerprint(
    confirmed: object,
    check: object,
    items: list[object],
) -> str:
    confirmation = getattr(confirmed, "confirmation")
    return _stable_fingerprint(
        {
            "confirmation": {
                "id": str(getattr(confirmation, "id", "")),
                "novel_id": str(getattr(confirmation, "novel_id", "")),
                "action": getattr(confirmation, "action", None),
                "task": getattr(confirmation, "task", None),
                "scope": getattr(confirmation, "scope", None),
                "context_mode": getattr(confirmation, "context_mode", None),
                "include_pending_objects": bool(
                    getattr(confirmation, "include_pending_objects", False)
                ),
                "compile_options": deepcopy(
                    getattr(confirmed, "compile_options", None) or {}
                ),
                "selected_asset_ids": deepcopy(
                    getattr(confirmation, "selected_asset_ids", None) or {}
                ),
                "excluded_asset_ids": deepcopy(
                    getattr(confirmation, "excluded_asset_ids", None) or {}
                ),
                "user_note": getattr(confirmation, "user_note", None),
                "warnings": list(getattr(confirmation, "warnings", []) or []),
                "rendered_markdown": str(getattr(confirmed, "rendered_markdown", "")),
                "compiled": _compiled_context_fingerprint(getattr(confirmed, "compiled")),
            },
            "conflict_check": _check_semantic_fingerprint(check, items),
        }
    )


def _ai_review_items(
    output: WritingConflictAiReviewRawOutput,
    *,
    check: object,
    confirmation_id: uuid.UUID,
    include_pending_objects: bool,
) -> tuple[list[dict], int]:
    items: list[dict] = []
    discarded_count = 0
    for raw in output.issues:
        try:
            issue = WritingConflictAiReviewIssue.model_validate(raw)
        except PydanticValidationError:
            discarded_count += 1
            continue
        items.append(
            {
                "kind": issue.kind,
                "severity": issue.severity,
                "source_module": "ai",
                "source_type": "llm.soft_conflict",
                "source_id": str(getattr(check, "id", "")),
                "evidence_summary": f"{issue.summary}｜证据：{issue.evidence}",
                "location_json": issue.location_hint or {"target": "ai_review"},
                "is_ai_judgment": True,
                "needs_review": (
                    include_pending_objects or issue.depends_on_pending_objects
                ),
                "confidence": issue.confidence,
                "source_confirmation_id": confirmation_id,
                "llm_rationale": issue.rationale,
                "status": "open",
            }
        )
    return items, discarded_count


def _validate_confirmation_scope(confirmation: object, check: object) -> None:
    options = getattr(confirmation, "compile_options", None) or {}
    confirmed_chapter = options.get("chapter_index")
    check_chapter = getattr(check, "chapter_index", None)
    if check_chapter is not None and confirmed_chapter != check_chapter:
        raise ValueError(
            "context confirmation chapter_index does not match conflict check",
        )

    check_scene = getattr(check, "scene_id", None)
    if check_scene:
        confirmed_scene = options.get("scene_id")
        if str(confirmed_scene or "") != str(check_scene):
            raise ValueError(
                "context confirmation scene_id does not match conflict check",
            )


def validate_ai_review_confirmation_scope(confirmation: object, check: object) -> None:
    """Validate that a confirmed AI reference selection matches a conflict check."""
    _validate_confirmation_scope(confirmation, check)


def _summary_with_ai_review(
    items: list[object],
    existing_summary: dict,
    *,
    status: str,
    discarded_count: int,
) -> dict:
    by_severity: dict[str, int] = {}
    open_high = 0
    ai_count = 0
    for item in items:
        severity = getattr(item, "severity", "info")
        by_severity[severity] = by_severity.get(severity, 0) + 1
        if (
            getattr(item, "severity", None) == "high"
            and getattr(item, "status", None) == "open"
        ):
            open_high += 1
        if getattr(item, "is_ai_judgment", False):
            ai_count += 1
    summary = dict(existing_summary or {})
    summary.update(
        {
            "total": len(items),
            "open_high_count": open_high,
            "by_severity": by_severity,
        }
    )
    summary["ai_review"] = {
        "status": status,
        "item_count": ai_count,
        "discarded_count": discarded_count,
    }
    return summary


def _sort_conflict_items(items: list[object]) -> list[object]:
    return sorted(
        items,
        key=lambda item: (
            getattr(item, "severity", ""),
            _created_at_sort_value(getattr(item, "created_at", None)),
        ),
    )


def _created_at_sort_value(value: object) -> float:
    if not isinstance(value, datetime):
        return datetime.min.replace(tzinfo=UTC).timestamp()
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.timestamp()


def _build_ai_review_prompt(
    *,
    check: object,
    items: list[object],
    context_markdown: str,
) -> str:
    rule_summary = "\n".join(
        f"- {getattr(item, 'kind', '')}: {getattr(item, 'evidence_summary', '')}"
        for item in items
        if not getattr(item, "is_ai_judgment", False)
    )
    scope = getattr(check, "scope", None) or {}
    content_excerpt = scope.get("content_excerpt") or ""
    return (
        "请基于当前 Scene 写作目标和 AI 参考资料，补充判断叙事软冲突。"
        "Scene 的 must_happen / must_not_happen 是语义承诺，不要求正文逐字复现；"
        "仅在完整语义上确实遗漏必要承诺或发生被禁止的偏离时报告。\n\n"
        f"检查范围：第 {getattr(check, 'chapter_index', '-')} 章，"
        f"Scene={getattr(check, 'scene_id', None) or '未指定'}。\n\n"
        "当前正文摘录：\n"
        f"{content_excerpt or '- 无正文摘录'}\n\n"
        "规则层已命中问题：\n"
        f"{rule_summary or '- 无'}\n\n"
        "AI 参考资料：\n"
        f"{context_markdown}\n\n"
        "只输出 JSON，不要输出 Markdown 或解释。格式必须是：\n"
        "{\n"
        '  "issues": [\n'
        "    {\n"
        '      "kind": "motivation_gap",\n'
        '      "severity": "medium",\n'
        '      "summary": "一句话概括问题",\n'
        '      "evidence": "正文或上下文中的具体证据",\n'
        '      "rationale": "为什么这构成软冲突",\n'
        '      "location_hint": {"chapter_index": 1, '
        '"text_quote": "可定位短句"},\n'
        '      "confidence": 0.72,\n'
        '      "depends_on_pending_objects": false\n'
        "    }\n"
        "  ]\n"
        "}\n\n"
        "字段取值必须严格使用英文枚举：\n"
        "- kind: motivation_gap, emotion_jump, foreshadowing_misfire, "
        "premature_reveal, implicit_lore_conflict, voice_or_pov_drift, "
        "scene_goal_drift, scene_commitment_missing, "
        "scene_forbidden_deviation, continuity_soft_risk\n"
        "- severity: high, medium, low\n"
        "- confidence: 0 到 1 之间的数字\n"
        "- depends_on_pending_objects: true 或 false\n"
        "最多输出 2 条 issues。\n"
        "summary/evidence/rationale 各限制 1-2 句。\n"
        '不要展开长段解释；无法确定时输出 {"issues": []}。\n'
        '如果没有可报告的软冲突，输出 {"issues": []}。'
    )


def _build_ai_suggestion_prompt(
    *,
    check: object,
    item: object,
    items: list[object],
    context_markdown: str,
) -> str:
    related = "\n".join(
        f"- {getattr(entry, 'kind', '')}: {getattr(entry, 'evidence_summary', '')}"
        for entry in items
    )
    return (
        "请只针对下面这一条写作冲突生成可手动采纳的修复建议。\n\n"
        f"检查范围：第 {getattr(check, 'chapter_index', '-')} 章。\n"
        f"目标问题：{getattr(item, 'kind', '')} - "
        f"{getattr(item, 'evidence_summary', '')}\n\n"
        "同次检查问题摘要：\n"
        f"{related or '- 无'}\n\n"
        "AI 参考资料：\n"
        f"{context_markdown}\n\n"
        '只输出 JSON，格式为 {"suggestion": {"strategy": ..., '
        '"suggested_text": ..., "rationale": ..., '
        '"constraints": [], "risk_notes": []}}。\n'
        "strategy/rationale 各 1-2 句。\n"
        "suggested_text 控制在 300-600 字以内。\n"
        "constraints/risk_notes 每项不超过 3 条。"
    )


_AI_REVIEW_SYSTEM_PROMPT = (
    "你是小说写作软冲突审阅器。只报告与当前 Scene 写作目标相关的动机、"
    "情绪、伏笔、揭示、隐含设定、POV、Scene 目标漂移或 Scene 语义承诺问题。"
    "规则层的 must_happen 和 must_not_happen 结果只是未确认的字面预警；你必须按完整"
    "语义判断，不得要求字面复现。只有确认存在语义问题时，才追加独立的"
    "scene_commitment_missing 或 scene_forbidden_deviation，不要重复或改写字面预警。"
    "没有语义问题就不要输出对应条目。不要把缺少信息当作事实错误。"
    "不要输出正史修改指令或一键应用补丁。每条问题必须给出依据、理由、置信度，"
    "依赖待确认对象时 depends_on_pending_objects=true。"
)

_AI_SUGGESTION_SYSTEM_PROMPT = (
    "你是小说写作修复建议助手。只针对单条问题生成可手动采纳的建议。"
    "尊重 Scene 的必须发生和禁止发生，不提前揭示隐藏真相，不引入新的正史事实。"
    "如建议需要新增事实，必须在风险说明中标记需要作者确认。不得输出自动补丁。"
)
