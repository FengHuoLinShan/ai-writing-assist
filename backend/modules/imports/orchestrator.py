"""Deep import orchestration policy.

Owns duplicate detection, replacement/deprecation policy, task submission, and
task progress shaping for the user-confirmed deep import pipeline.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.llm.redaction import redact_diagnostic
from modules.imports.adoption_policy import (
    DEFAULT_ADOPTION_POLICY,
    SUPPORTED_ADOPTION_POLICIES,
    build_asset_summary,
    build_authorization_snapshot,
    empty_asset_summary,
)
from modules.imports.contracts import TaskNotFoundError
from modules.imports.service_progress_limits import trim_progress_diagnostics
from modules.imports.workflow import DeepImportWorkflow
from modules.imports.workflow_runs import (
    ImportWorkflowAttempt,
    ImportWorkflowOwnerToken,
    ImportWorkflowRun,
    ImportWorkflowRunService,
)
from modules.imports.workflow_schemas import DeepImportProgress, DeepImportStep

ProgressObserver = Callable[[DeepImportProgress, float, Any], Awaitable[None]]
TaskProjectionCallback = Callable[[dict[str, Any], float], Awaitable[None]]
SnapshotBuilder = Callable[[AsyncSession, str], Awaitable[dict[str, Any]]]
SnapshotRestorer = Callable[
    [AsyncSession, str, dict[str, Any]],
    Awaitable[dict[str, Any] | None],
]

STAGE_TASK_TYPES = {
    "scenes": "scene_auto_extraction",
    "world_objects": "world_object_auto_extraction",
    "plot_structure": "plot_structure_auto_extraction",
}
IMPORT_TASK_TYPES = {"deep_import", *STAGE_TASK_TYPES.values()}

# Scene stage progress is an elapsed-time estimate based on the two most recent
# 1-60 chapter runs of the current pipeline. Phase 0 is intentionally excluded:
# it completed in under 0.1 seconds in both runs.
SCENE_STAGE_PHASE1A_WEIGHT = 0.59
SCENE_STAGE_PHASE1B_WEIGHT = 0.40
SCENE_STAGE_COMMIT_START = 0.99
SCENE_STAGE_TASK_PREPARE_VERSION = "scene-stage-prepare-v2"
SCENE_STAGE_TASK_PREPARE_KEY = "scene_stage_prepare"


class DeepImportWorkflowFailedError(RuntimeError):
    """A persisted workflow failure that must become a failed async task."""


class SceneStageInputDriftError(RuntimeError):
    """Frozen Scene-stage business inputs changed before formal persistence."""


@dataclass(frozen=True)
class _WorkflowEnqueueResult:
    task_id: str
    reused: bool


class _WorkflowTaskView:
    """Local compatibility view; never exposes the queue ORM to the orchestrator."""

    def __init__(
        self,
        attempt: ImportWorkflowAttempt,
        project: TaskProjectionCallback,
    ) -> None:
        self.id = attempt.task_id
        self.task_type = attempt.workflow_type
        self.status = "running"
        self.attempt = attempt.owner.attempt
        self.lease_id = attempt.owner.lease_id
        self.meta = attempt.meta_projection()
        self.result = attempt.progress_projection()
        self.progress = 0.0
        self.workflow_owner = attempt.owner
        self.project = project

    def update_progress(self, value: float) -> None:
        self.progress = min(1.0, max(float(self.progress or 0.0), float(value)))


class DeepImportOrchestrator:
    """Stable implementation behind imports facade and task handler."""

    def __init__(
        self,
        workflow: DeepImportWorkflow | None = None,
        *,
        progress_observer: ProgressObserver | None = None,
        snapshot_builder: SnapshotBuilder | None = None,
        snapshot_restorer: SnapshotRestorer | None = None,
        phase1a_context_builder: Any | None = None,
    ) -> None:
        self.workflow = workflow or DeepImportWorkflow()
        self.progress_observer = progress_observer
        self._snapshot_builder = snapshot_builder
        self._snapshot_restorer = snapshot_restorer
        self._phase1a_context_builder = phase1a_context_builder
        self._runs = ImportWorkflowRunService()

    async def run_attempt(
        self,
        db: AsyncSession,
        attempt: ImportWorkflowAttempt,
        *,
        project: TaskProjectionCallback,
    ) -> dict[str, Any]:
        """Run one immutable owner attempt and leave terminal CAS to worker commit."""
        task = _WorkflowTaskView(attempt, project)
        if attempt.stage is None and attempt.workflow_type == "deep_import":
            result = await self.run_task(db, task)
        else:
            if attempt.stage not in STAGE_TASK_TYPES:
                raise ValueError(f"unsupported deep import stage: {attempt.stage}")
            result = await self.run_stage_task(db, task, stage=str(attempt.stage))
        await self._runs.complete(
            db,
            owner=attempt.owner,
            progress=result,
        )
        await project(result, 1.0)
        return result

    async def _checkpoint_owned_task(
        self,
        db: AsyncSession,
        task: Any,
    ) -> None:
        owner = getattr(task, "workflow_owner", None)
        if not isinstance(owner, ImportWorkflowOwnerToken):
            return
        result = dict(task.result or {})
        await self._runs.checkpoint(
            db,
            owner=owner,
            progress=result,
            prepare_checkpoint=dict(task.meta or {}),
            checkpoints=dict(result.get("checkpoints") or {}),
        )
        await task.project(result, self._task_progress_value(task))

    async def start(
        self,
        db: AsyncSession,
        novel_id: str,
        start_chapter: int,
        end_chapter: int,
        force: bool = False,
        high_quality: bool = False,
        adoption_policy: str = DEFAULT_ADOPTION_POLICY,
        authorization_confirmed: bool = False,
    ) -> dict[str, Any]:
        authorization_snapshot = build_authorization_snapshot(
            novel_id=novel_id,
            start_chapter=start_chapter,
            end_chapter=end_chapter,
            adoption_policy=adoption_policy,
            authorization_confirmed=authorization_confirmed,
        )
        active_task = await self._find_active_import_task(db, novel_id)
        if active_task is not None:
            return self._existing_task_response(active_task, authorization_snapshot)
        llm_execution_snapshot = await self._build_llm_execution_snapshot(
            db,
            novel_id,
        )
        warning = await self._check_duplicate_import(
            db, novel_id, start_chapter, end_chapter
        )
        if warning and not force:
            return {
                "workflow_id": None,
                "task_id": None,
                "status": "requires_confirmation",
                "requires_confirmation": True,
                "warning": warning,
                "message": warning,
            }

        task_id = self._enqueue_deep_import(
            db,
            novel_id,
            start_chapter,
            end_chapter,
            context_mode="working",
            include_pending_objects=True,
            high_quality=high_quality,
            replace_existing=force,
            authorization_snapshot=authorization_snapshot,
            llm_execution_snapshot=llm_execution_snapshot,
        )
        if inspect.isawaitable(task_id):
            task_id = await task_id
        if isinstance(task_id, _WorkflowEnqueueResult):
            enqueue_result = task_id
            task_id = enqueue_result.task_id
            if enqueue_result.reused:
                submitted_run = await self._runs.get_by_task(
                    db,
                    task_id=str(task_id),
                )
                if submitted_run is not None:
                    return self._existing_task_response(
                        submitted_run,
                        authorization_snapshot,
                    )
        await db.flush()
        return {
            "workflow_id": str(task_id),
            "task_id": str(task_id),
            "status": "pending",
            "requires_confirmation": False,
            "adoption_policy": adoption_policy,
            "authorization_snapshot": authorization_snapshot,
            "message": f"深度导入任务已提交（第{start_chapter}-{end_chapter}章）",
        }

    async def start_stage(
        self,
        db: AsyncSession,
        novel_id: str,
        start_chapter: int,
        end_chapter: int,
        *,
        stage: str,
        force: bool = False,
        high_quality: bool = False,
        adoption_policy: str = DEFAULT_ADOPTION_POLICY,
        authorization_confirmed: bool = False,
    ) -> dict[str, Any]:
        if stage not in STAGE_TASK_TYPES:
            raise ValueError(f"unsupported deep import stage: {stage}")
        authorization_snapshot = build_authorization_snapshot(
            novel_id=novel_id,
            start_chapter=start_chapter,
            end_chapter=end_chapter,
            adoption_policy=adoption_policy,
            authorization_confirmed=authorization_confirmed,
            stage=stage,
        )
        active_task = await self._find_active_import_task(db, novel_id)
        if active_task is not None:
            return self._existing_task_response(active_task, authorization_snapshot)
        llm_execution_snapshot = await self._build_llm_execution_snapshot(
            db,
            novel_id,
        )

        if stage == "scenes":
            warning = await self._check_duplicate_import(
                db, novel_id, start_chapter, end_chapter
            )
            if warning and not force:
                return {
                    "workflow_id": None,
                    "task_id": None,
                    "status": "requires_confirmation",
                    "requires_confirmation": True,
                    "warning": warning,
                    "message": warning,
                }
        task_id = self._enqueue_stage_task(
            db,
            task_type=STAGE_TASK_TYPES[stage],
            novel_id=novel_id,
            start_chapter=start_chapter,
            end_chapter=end_chapter,
            stage=stage,
            context_mode="working",
            include_pending_objects=True,
            high_quality=high_quality,
            replace_existing=force if stage == "scenes" else False,
            authorization_snapshot=authorization_snapshot,
            llm_execution_snapshot=llm_execution_snapshot,
        )
        if inspect.isawaitable(task_id):
            task_id = await task_id
        if isinstance(task_id, _WorkflowEnqueueResult):
            enqueue_result = task_id
            task_id = enqueue_result.task_id
            if enqueue_result.reused:
                submitted_run = await self._runs.get_by_task(
                    db,
                    task_id=str(task_id),
                )
                if submitted_run is not None:
                    return self._existing_task_response(
                        submitted_run,
                        authorization_snapshot,
                    )
        await db.flush()
        return {
            "workflow_id": str(task_id),
            "task_id": str(task_id),
            "status": "pending",
            "requires_confirmation": False,
            "workflow_type": STAGE_TASK_TYPES[stage],
            "stage": stage,
            "adoption_policy": adoption_policy,
            "authorization_snapshot": authorization_snapshot,
            "message": self._stage_pending_message(stage, start_chapter, end_chapter),
        }

    async def run_task(self, db: AsyncSession, task: Any) -> dict[str, Any]:
        meta = task.meta or {}
        novel_id = meta.get("novel_id", "")
        start_chapter = int(meta.get("start_chapter", 1))
        end_chapter = int(meta.get("end_chapter", 5))
        context_mode = meta.get("context_mode", "working")
        include_pending_objects = bool(meta.get("include_pending_objects", True))
        high_quality = bool(meta.get("high_quality", False))
        replace_existing = bool(meta.get("replace_existing", False))
        if not novel_id:
            raise ValueError("novel_id is required for deep_import")

        progress = self._progress_from_task(task)
        self._hydrate_authorization(progress, meta)
        project_settings = await self._restore_llm_execution_snapshot(
            db,
            task,
            progress,
            meta,
        )

        async def _record_progress(
            updated: DeepImportProgress,
            progress_value: float,
        ) -> None:
            updated.asset_summary = build_asset_summary(updated.quality_stats)
            task.result = updated.model_dump(mode="json")
            persisted_value = self._update_task_progress(task, progress_value)
            await self._checkpoint_owned_task(db, task)
            await db.commit()
            if self.progress_observer is not None:
                await self.progress_observer(updated, persisted_value, task)

        progress = await self.workflow.run_step(
            db,
            novel_id=novel_id,
            start_chapter=start_chapter,
            end_chapter=end_chapter,
            progress=progress,
            workflow_id=str(task.id),
            context_mode=context_mode,
            include_pending_objects=include_pending_objects,
            high_quality=high_quality,
            replace_existing=replace_existing,
            project_settings=project_settings,
            on_progress=_record_progress,
        )
        self._hydrate_authorization(progress, meta)
        if progress.phase == "failed":
            await _record_progress(progress, self._task_progress_value(task))
            raise DeepImportWorkflowFailedError(
                progress.message or "Deep import workflow failed"
            )
        await self._assemble_post_import_package(
            db, progress, meta, novel_id, str(task.id)
        )
        return self._result_from_progress(progress)

    @staticmethod
    async def _assemble_post_import_package(
        db: AsyncSession,
        progress: DeepImportProgress,
        meta: dict[str, Any],
        novel_id: str,
        workflow_id: str,
    ) -> None:
        """Best-effort review artifact: never changes a completed import outcome."""
        from modules.world.contracts import (
            PostImportSceneSourceContract,
            PostImportWorldAdoptionRequestContract,
        )
        from modules.world.facade import assemble_post_import_adoption_package

        checkpoints = (progress.checkpoints.get("phase2") or {}).get("scenes") or []
        sources = [
            PostImportSceneSourceContract(
                scene_id=str(item["scene_id"]),
                source_hash=str(item["input_fingerprint"]),
                entity_ids=tuple(
                    str(value) for value in item.get("created_entity_ids") or []
                ),
                relation_ids=tuple(
                    str(value) for value in item.get("created_relation_ids") or []
                ),
            )
            for item in checkpoints
            if isinstance(item, dict)
            and item.get("scene_id")
            and item.get("input_fingerprint")
        ]
        if not sources:
            return
        try:
            result = await assemble_post_import_adoption_package(
                db,
                PostImportWorldAdoptionRequestContract(
                    novel_id=novel_id,
                    workflow_id=workflow_id,
                    authorization_ref=str(
                        (meta.get("authorization_snapshot") or {}).get("authorized_at")
                        or ""
                    ),
                    scene_sources=sources,
                ),
            )
            progress.phase_artifacts["post_import_adoption_package"] = {
                "suggestion_id": result.suggestion_id,
                "created": result.created,
            }
        except Exception as exc:
            progress.phase_artifacts["post_import_adoption_package"] = {
                "status": "failed",
                "error": redact_diagnostic(exc, limit=200),
            }

    async def run_stage_task(
        self,
        db: AsyncSession,
        task: Any,
        *,
        stage: str,
    ) -> dict[str, Any]:
        meta = task.meta or {}
        novel_id = meta.get("novel_id", "")
        start_chapter = int(meta.get("start_chapter", 1))
        end_chapter = int(meta.get("end_chapter", 5))
        context_mode = meta.get("context_mode", "working")
        include_pending_objects = bool(meta.get("include_pending_objects", True))
        high_quality = bool(meta.get("high_quality", False))
        replace_existing = bool(meta.get("replace_existing", False))
        if not novel_id:
            raise ValueError(f"novel_id is required for {task.task_type}")
        fenced_session = bool(
            getattr(db, "task_checkpoint_enabled", False) is True
            or getattr(db, "task_inline_execution_enabled", False) is True
        )
        if stage == "scenes" and fenced_session:
            return await self._run_fenced_scene_stage_task(
                db,
                task,
                meta=dict(meta),
                novel_id=str(novel_id),
                start_chapter=start_chapter,
                end_chapter=end_chapter,
                high_quality=high_quality,
                replace_existing=replace_existing,
            )

        progress = self._progress_from_task(task)
        self._hydrate_authorization(progress, meta)
        project_settings = await self._restore_llm_execution_snapshot(
            db,
            task,
            progress,
            meta,
        )
        progress.workflow_type = str(task.task_type)
        progress.stage = stage
        progress.total_steps = 1

        async def _record_progress(
            updated: DeepImportProgress,
            progress_value: float,
        ) -> None:
            updated.workflow_type = str(task.task_type)
            updated.stage = stage
            updated.asset_summary = build_asset_summary(updated.quality_stats)
            task.result = updated.model_dump(mode="json")
            stage_progress = (
                self._scene_stage_progress_value(updated)
                if stage == "scenes"
                else progress_value
            )
            persisted_value = self._update_task_progress(task, stage_progress)
            await self._checkpoint_owned_task(db, task)
            await db.commit()
            if self.progress_observer is not None:
                await self.progress_observer(updated, persisted_value, task)

        if stage == "scenes":
            progress = await self.workflow.run_step(
                db,
                novel_id=novel_id,
                start_chapter=start_chapter,
                end_chapter=end_chapter,
                progress=progress,
                workflow_id=str(task.id),
                context_mode=context_mode,
                include_pending_objects=include_pending_objects,
                high_quality=high_quality,
                replace_existing=replace_existing,
                project_settings=project_settings,
                on_progress=_record_progress,
                stop_after=DeepImportStep.scene_segmentation,
            )
        elif stage == "world_objects":
            progress = await self.workflow.run_entity_extraction_only(
                db,
                novel_id=novel_id,
                start_chapter=start_chapter,
                end_chapter=end_chapter,
                progress=progress,
                workflow_id=str(task.id),
                high_quality=high_quality,
                project_settings=project_settings,
                on_progress=_record_progress,
            )
        elif stage == "plot_structure":
            progress = await self.workflow.run_structure_analysis_only(
                db,
                novel_id=novel_id,
                start_chapter=start_chapter,
                end_chapter=end_chapter,
                progress=progress,
                workflow_id=str(task.id),
                context_mode=context_mode,
                include_pending_objects=include_pending_objects,
                high_quality=high_quality,
                project_settings=project_settings,
                on_progress=_record_progress,
            )
        else:
            raise ValueError(f"unsupported deep import stage: {stage}")
        self._hydrate_authorization(progress, meta)
        if progress.phase == "failed":
            await _record_progress(progress, self._task_progress_value(task))
            raise DeepImportWorkflowFailedError(
                progress.message or f"Deep import stage {stage} failed"
            )
        return self._result_from_progress(progress)

    async def _run_fenced_scene_stage_task(
        self,
        db: AsyncSession,
        task: Any,
        *,
        meta: dict[str, Any],
        novel_id: str,
        start_chapter: int,
        end_chapter: int,
        high_quality: bool,
        replace_existing: bool,
    ) -> dict[str, Any]:
        """Run Scene extraction with one prepare and one atomic asset commit."""
        from infrastructure.tasks.facade import require_task_checkpoint_session

        require_task_checkpoint_session(db)
        self._validate_scene_task_identity(task, meta, novel_id)
        progress = self._progress_from_task(task)
        self._hydrate_authorization(progress, meta)
        progress.workflow_type = "scene_auto_extraction"
        progress.stage = "scenes"
        progress.total_steps = 1

        existing_prepare = meta.get(SCENE_STAGE_TASK_PREPARE_KEY)
        if isinstance(existing_prepare, dict) and progress.phase == "done":
            return self._result_from_progress(progress)
        if (
            isinstance(existing_prepare, dict)
            and existing_prepare.get("version") != SCENE_STAGE_TASK_PREPARE_VERSION
        ):
            raise SceneStageInputDriftError(
                "Legacy Scene-stage v1 prepare cannot use the Phase 1a v2 "
                "context contract; submit a new Scene extraction task"
            )

        (
            project_settings,
            phase0_result,
            project_profile,
            preparation,
        ) = await self._prepare_fenced_scene_stage(
            db,
            task,
            meta=meta,
            novel_id=novel_id,
            start_chapter=start_chapter,
            end_chapter=end_chapter,
            high_quality=high_quality,
            replace_existing=replace_existing,
        )
        task.meta = {
            **dict(task.meta or meta),
            SCENE_STAGE_TASK_PREPARE_KEY: preparation,
        }
        progress.llm_execution_snapshot = dict(
            (task.meta or {}).get("llm_execution_snapshot") or {}
        )
        progress.checkpoints[SCENE_STAGE_TASK_PREPARE_KEY] = (
            self._public_scene_prepare_checkpoint(preparation)
        )
        progress.asset_summary = build_asset_summary(progress.quality_stats)
        task.result = progress.model_dump(mode="json")
        self._update_task_progress(task, 0.0)
        await self._checkpoint_owned_task(db, task)

        # This is the only durable checkpoint before health/provider I/O.  The
        # TaskHandlerSession hook atomically persists detached meta/result and
        # rejects a lost lease before any external call can begin.
        await db.commit()
        db.expire_all()
        if db.in_transaction():
            raise RuntimeError(
                "scene_auto_extraction prepare checkpoint left a transaction open"
            )

        scene_commit_checkpointed = False

        async def _record_progress(
            updated: DeepImportProgress,
            progress_value: float,
        ) -> None:
            nonlocal scene_commit_checkpointed
            updated.workflow_type = "scene_auto_extraction"
            updated.stage = "scenes"
            updated.asset_summary = build_asset_summary(updated.quality_stats)
            task.result = updated.model_dump(mode="json")
            persisted_value = self._update_task_progress(
                task,
                self._scene_stage_progress_value(updated),
            )
            terminal_scene_commit = bool(
                updated.current_phase == "scene_commit" and updated.phase == "done"
            )
            failed_scene_commit = bool(
                updated.current_phase == "scene_commit" and updated.phase == "failed"
            )
            if terminal_scene_commit and not scene_commit_checkpointed:
                # Formal Scene rows, suggestions, RAG enqueue, and this task
                # progress/result become durable under the same worker CAS.
                await self._checkpoint_owned_task(db, task)
                await db.commit()
                scene_commit_checkpointed = True
                db.expire_all()
            elif failed_scene_commit:
                # SceneCommitter may already have deprecated old Scenes or
                # flushed only part of the replacement set.  A failed coverage
                # decision must discard that whole finalizer transaction while
                # preserving the earlier prepare checkpoint.
                if db.in_transaction():
                    await db.rollback()
            elif db.in_transaction():
                raise RuntimeError(
                    "scene_auto_extraction progress opened a provider transaction"
                )
            elif isinstance(
                getattr(task, "workflow_owner", None),
                ImportWorkflowOwnerToken,
            ):
                await self._checkpoint_owned_task(db, task)
                await db.commit()
                db.expire_all()
            elif getattr(db, "task_progress_checkpoint_enabled", False) is True:
                # Provider work intentionally runs without the domain transaction.
                # Persist user-visible progress through the worker's independent,
                # lease-fenced task session without making partial Scene assets
                # durable.
                accepted = await db.checkpoint_task_progress()
                if not accepted:
                    raise asyncio.CancelledError
            if self.progress_observer is not None:
                await self.progress_observer(updated, persisted_value, task)
            if db.in_transaction():
                raise RuntimeError(
                    "scene_auto_extraction observer opened a provider transaction"
                )

        async def _before_scene_commit() -> None:
            await self._revalidate_fenced_scene_stage(
                db,
                task,
                preparation=preparation,
                novel_id=novel_id,
                start_chapter=start_chapter,
                end_chapter=end_chapter,
            )

        progress = await self.workflow.run_step(
            db,
            novel_id=novel_id,
            start_chapter=start_chapter,
            end_chapter=end_chapter,
            progress=progress,
            workflow_id=str(task.id),
            context_mode=str(meta.get("context_mode") or "working"),
            include_pending_objects=bool(meta.get("include_pending_objects", True)),
            high_quality=high_quality,
            replace_existing=replace_existing,
            project_settings=project_settings,
            on_progress=_record_progress,
            stop_after=DeepImportStep.scene_segmentation,
            prepared_scene_phase0_result=phase0_result,
            scene_project_profile=project_profile,
            before_scene_commit=_before_scene_commit,
            require_scene_provider_no_transaction=True,
        )
        self._hydrate_authorization(progress, dict(task.meta or meta))
        if progress.phase == "failed":
            await _record_progress(progress, self._task_progress_value(task))
            raise DeepImportWorkflowFailedError(
                progress.message or "Deep import stage scenes failed"
            )
        if not scene_commit_checkpointed:
            raise RuntimeError(
                "scene_auto_extraction completed without a fenced Scene checkpoint"
            )
        return self._result_from_progress(progress)

    async def _prepare_fenced_scene_stage(
        self,
        db: AsyncSession,
        task: Any,
        *,
        meta: dict[str, Any],
        novel_id: str,
        start_chapter: int,
        end_chapter: int,
        high_quality: bool,
        replace_existing: bool,
    ) -> tuple[dict[str, Any] | None, Any, dict[str, Any], dict[str, Any]]:
        from modules.imports.chapter_loader import load_chapter_range
        from modules.imports.phase1a_context import (
            Phase1aContextBuilder,
            apply_frozen_phase1a_context,
        )
        from modules.imports.scene_planning import build_scene_import_plan
        from modules.project.facade import get_project_context, require_active_project

        await require_active_project(db, novel_id)
        context = await get_project_context(db, novel_id)
        if context is None:
            raise SceneStageInputDriftError("Scene-stage project is no longer active")
        progress = self._progress_from_task(task)
        project_settings = await self._restore_llm_execution_snapshot(
            db,
            task,
            progress,
            meta,
        )
        current_meta = dict(task.meta or meta)
        snapshot = current_meta.get("llm_execution_snapshot")
        if not isinstance(snapshot, dict) or not snapshot:
            raise ValueError("llm_execution_snapshot is required")
        loaded_chapters = await load_chapter_range(
            db,
            novel_id,
            max(1, start_chapter - 1),
            end_chapter,
            include_missing=False,
        )
        chapters = [
            chapter
            for chapter in loaded_chapters
            if int(chapter["chapter_index"]) >= start_chapter
        ]
        project_profile = self._scene_project_profile(context)
        phase0_result = build_scene_import_plan(
            chapters,
            start_chapter=start_chapter,
            end_chapter=end_chapter,
            project_settings=project_settings,
        )
        context_builder = self._phase1a_context_builder or Phase1aContextBuilder()
        phase0_result = await context_builder.compile(
            db,
            novel_id=novel_id,
            plan=phase0_result,
            boundary_chapters=loaded_chapters,
        )
        preparation = self._build_scene_stage_preparation(
            task=task,
            meta=current_meta,
            novel_id=novel_id,
            start_chapter=start_chapter,
            end_chapter=end_chapter,
            high_quality=high_quality,
            replace_existing=replace_existing,
            chapters=chapters,
            project_profile=project_profile,
            llm_execution_snapshot=snapshot,
            phase1a_context=phase0_result.phase1a_context,
        )
        existing = meta.get(SCENE_STAGE_TASK_PREPARE_KEY)
        if isinstance(existing, dict):
            if existing.get("version") != SCENE_STAGE_TASK_PREPARE_VERSION:
                raise SceneStageInputDriftError(
                    "Legacy Scene-stage v1 prepare cannot use the Phase 1a v2 "
                    "context contract; submit a new Scene extraction task"
                )
            if existing.get("input_fingerprint") != preparation["input_fingerprint"]:
                raise SceneStageInputDriftError(
                    "Scene-stage inputs changed after the prepare checkpoint"
                )
            preparation = dict(existing)
            phase0_result = apply_frozen_phase1a_context(
                phase0_result,
                dict(preparation.get("phase1a_context") or {}),
            )
        progress.llm_execution_snapshot = dict(snapshot)
        return project_settings, phase0_result, project_profile, preparation

    async def _revalidate_fenced_scene_stage(
        self,
        db: AsyncSession,
        task: Any,
        *,
        preparation: dict[str, Any],
        novel_id: str,
        start_chapter: int,
        end_chapter: int,
    ) -> None:
        from modules.imports.chapter_loader import load_chapter_range
        from modules.imports.phase1a_context import Phase1aContextBuilder
        from modules.imports.scene_planning import build_scene_import_plan
        from modules.project.facade import get_project_context, require_active_project
        from modules.writing.facade import lock_chapter_versions_for_revalidation

        # Lock order is project -> source/profile -> task.  The project shared
        # lock linearizes this final business write against project deletion.
        await require_active_project(db, novel_id)
        context = await get_project_context(db, novel_id)
        if context is None:
            raise SceneStageInputDriftError("Scene-stage project is no longer active")
        current_profile = self._scene_project_profile(context)
        if self._stable_hash(current_profile) != preparation.get(
            "project_profile_fingerprint"
        ):
            raise SceneStageInputDriftError(
                "Scene-stage project profile changed during generation"
            )

        task_meta = dict(task.meta or {})
        snapshot = task_meta.get("llm_execution_snapshot")
        if not isinstance(snapshot, dict) or not snapshot:
            raise SceneStageInputDriftError("Scene-stage LLM snapshot is missing")
        if self._stable_hash(snapshot) != preparation.get(
            "llm_execution_snapshot_fingerprint"
        ):
            raise SceneStageInputDriftError("Scene-stage LLM snapshot changed")
        # Re-resolve current secrets/endpoint-specific values.  The frozen model
        # and generation settings remain intentionally stable across retries.
        project_settings = await self._restore_snapshot(db, novel_id, snapshot)

        await lock_chapter_versions_for_revalidation(
            db,
            novel_id,
            list(range(max(1, start_chapter - 1), end_chapter + 1)),
        )
        loaded_chapters = await load_chapter_range(
            db,
            novel_id,
            max(1, start_chapter - 1),
            end_chapter,
            include_missing=False,
        )
        chapters = [
            chapter
            for chapter in loaded_chapters
            if int(chapter["chapter_index"]) >= start_chapter
        ]
        if self._chapter_source_vector(chapters) != preparation.get("source_vector"):
            raise SceneStageInputDriftError(
                "Scene-stage chapter sources changed during generation"
            )
        fresh_plan = build_scene_import_plan(
            chapters,
            start_chapter=start_chapter,
            end_chapter=end_chapter,
            project_settings=project_settings,
        )
        context_builder = self._phase1a_context_builder or Phase1aContextBuilder()
        fresh_plan = await context_builder.compile(
            db,
            novel_id=novel_id,
            plan=fresh_plan,
            boundary_chapters=loaded_chapters,
        )
        if fresh_plan.phase1a_context.get("fingerprint") != preparation.get(
            "phase1a_context_fingerprint"
        ):
            raise SceneStageInputDriftError(
                "Scene-stage Phase 1a reference context changed during generation"
            )

        from infrastructure.tasks.facade import require_running_task_attempt

        await require_running_task_attempt(
            db,
            task_id=str(task.id),
            task_type="scene_auto_extraction",
            novel_id=novel_id,
            lease_id=str(task.lease_id or ""),
            attempt=int(task.attempt or 0),
        )
        owner = getattr(task, "workflow_owner", None)
        if isinstance(owner, ImportWorkflowOwnerToken):
            await self._runs.require_owner(db, owner)
        current_task = getattr(db, "current_task", task)
        current_meta = dict(current_task.meta or {})
        current_prepare = current_meta.get(SCENE_STAGE_TASK_PREPARE_KEY)
        current_snapshot = current_meta.get("llm_execution_snapshot")
        fence_valid = bool(
            str(current_task.status or "") == "running"
            and str(current_task.lease_id or "") == str(task.lease_id or "")
            and int(current_task.attempt or 0) == int(task.attempt or 0)
            and current_task.task_type == "scene_auto_extraction"
            and str(current_meta.get("novel_id") or "") == novel_id
            and current_meta.get("stage") == "scenes"
            and int(current_meta.get("start_chapter", 0)) == start_chapter
            and int(current_meta.get("end_chapter", 0)) == end_chapter
            and bool(current_meta.get("high_quality", False))
            == bool(preparation.get("high_quality", False))
            and bool(current_meta.get("replace_existing", False))
            == bool(preparation.get("replace_existing", False))
            and self._stable_hash(current_meta.get("authorization_snapshot"))
            == preparation.get("authorization_fingerprint")
            and isinstance(current_snapshot, dict)
            and self._stable_hash(current_snapshot)
            == preparation.get("llm_execution_snapshot_fingerprint")
            and isinstance(current_prepare, dict)
            and current_prepare.get("version") == SCENE_STAGE_TASK_PREPARE_VERSION
            and current_prepare.get("input_fingerprint")
            == preparation.get("input_fingerprint")
        )
        if not fence_valid:
            raise asyncio.CancelledError

    @staticmethod
    def _validate_scene_task_identity(
        task: Any,
        meta: dict[str, Any],
        novel_id: str,
    ) -> None:
        if str(getattr(task, "task_type", "")) != "scene_auto_extraction":
            raise ValueError("scene stage task_type mismatch")
        if str(meta.get("novel_id") or "") != novel_id:
            raise ValueError("scene stage novel_id mismatch")
        if meta.get("stage") != "scenes":
            raise ValueError("scene stage scope mismatch")

    @classmethod
    def _build_scene_stage_preparation(
        cls,
        *,
        task: Any,
        meta: dict[str, Any],
        novel_id: str,
        start_chapter: int,
        end_chapter: int,
        high_quality: bool,
        replace_existing: bool,
        chapters: list[dict[str, Any]],
        project_profile: dict[str, Any],
        llm_execution_snapshot: dict[str, Any],
        phase1a_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        authorization = meta.get("authorization_snapshot")
        frozen_phase1a_context = dict(phase1a_context or {})
        semantic_inputs = {
            "task_id": str(task.id),
            "task_type": "scene_auto_extraction",
            "novel_id": novel_id,
            "start_chapter": start_chapter,
            "end_chapter": end_chapter,
            "high_quality": bool(high_quality),
            "replace_existing": bool(replace_existing),
            "authorization_fingerprint": cls._stable_hash(authorization),
            "source_vector": cls._chapter_source_vector(chapters),
            "project_profile": project_profile,
            "project_profile_fingerprint": cls._stable_hash(project_profile),
            "llm_execution_snapshot_fingerprint": cls._stable_hash(
                llm_execution_snapshot
            ),
            "phase1a_context": frozen_phase1a_context,
            "phase1a_context_contract_version": frozen_phase1a_context.get(
                "contract_version"
            ),
            "phase1a_context_fingerprint": frozen_phase1a_context.get("fingerprint"),
        }
        return {
            "version": SCENE_STAGE_TASK_PREPARE_VERSION,
            **semantic_inputs,
            "input_fingerprint": cls._stable_hash(semantic_inputs),
        }

    @staticmethod
    def _scene_project_profile(context: Any) -> dict[str, Any]:
        return {
            "title": str(getattr(context, "title", "") or ""),
            "genre": str(getattr(context, "genre", "") or ""),
            "tone": str(getattr(context, "tone", "") or ""),
        }

    @classmethod
    def _chapter_source_vector(
        cls,
        chapters: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        return [
            {
                "chapter_index": int(chapter["chapter_index"]),
                "source_draft_id": str(chapter.get("source_draft_id") or ""),
                "content_hash": hashlib.sha256(
                    str(chapter.get("content") or "").encode("utf-8")
                ).hexdigest(),
            }
            for chapter in sorted(
                chapters,
                key=lambda item: int(item["chapter_index"]),
            )
        ]

    @staticmethod
    def _stable_hash(value: Any) -> str:
        payload = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _public_scene_prepare_checkpoint(
        preparation: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            key: preparation.get(key)
            for key in (
                "version",
                "input_fingerprint",
                "source_vector",
                "project_profile_fingerprint",
                "llm_execution_snapshot_fingerprint",
                "authorization_fingerprint",
                "phase1a_context_contract_version",
                "phase1a_context_fingerprint",
                "start_chapter",
                "end_chapter",
                "high_quality",
                "replace_existing",
            )
        }

    async def run_submitted_stage_inline(
        self,
        db: AsyncSession,
        task_id: str,
        *,
        stage: str,
    ) -> dict[str, Any]:
        """Execute one already-authorized stage through the worker lifecycle."""
        if stage not in STAGE_TASK_TYPES:
            raise ValueError(f"unsupported deep import stage: {stage}")
        expected_type = STAGE_TASK_TYPES[stage]
        from infrastructure.tasks.facade import run_task_inline

        result = await run_task_inline(
            db,
            task_id=task_id,
            expected_task_type=expected_type,
        )
        if result is None:
            raise TaskNotFoundError(task_id)
        return result

    def _progress_from_task(self, task: Any) -> DeepImportProgress:
        result_data = task.result if isinstance(task.result, dict) else {}
        if not result_data:
            return DeepImportProgress(
                workflow_id=str(task.id),
                workflow_type=str(getattr(task, "task_type", "deep_import")),
                stage=(task.meta or {}).get("stage") if task.meta else None,
            )

        try:
            progress = DeepImportProgress.model_validate(result_data)
        except Exception:
            progress = DeepImportProgress(workflow_id=str(task.id))

        progress.workflow_id = progress.workflow_id or str(task.id)
        progress.workflow_type = progress.workflow_type or str(
            getattr(task, "task_type", "deep_import")
        )
        progress.stage = progress.stage or (
            (task.meta or {}).get("stage") if getattr(task, "meta", None) else None
        )
        progress.interrupted = False
        progress.recoverable = False
        progress.recovery_required = False
        if progress.phase == "running":
            progress.phase = "pending"
        return progress

    @staticmethod
    def _hydrate_authorization(
        progress: DeepImportProgress,
        meta: dict[str, Any],
    ) -> None:
        snapshot = meta.get("authorization_snapshot")
        if not isinstance(snapshot, dict):
            raise ValueError("authorization_snapshot is required")
        if snapshot.get("authorization_confirmed") is not True:
            raise ValueError(
                "authorization_snapshot.authorization_confirmed must be true"
            )
        adoption_policy = snapshot.get("adoption_policy")
        if adoption_policy not in SUPPORTED_ADOPTION_POLICIES:
            raise ValueError(
                f"unsupported authorization snapshot policy: {adoption_policy}"
            )
        if not snapshot.get("authorized_at"):
            raise ValueError("authorization_snapshot.authorized_at is required")
        scope = snapshot.get("scope")
        if not isinstance(scope, dict):
            raise ValueError("authorization_snapshot.scope is required")
        expected_scope = {
            "novel_id": meta.get("novel_id"),
            "start_chapter": int(meta.get("start_chapter", 1)),
            "end_chapter": int(meta.get("end_chapter", 5)),
            "stage": meta.get("stage"),
        }
        if any(scope.get(key) != value for key, value in expected_scope.items()):
            raise ValueError("authorization_snapshot scope does not match task meta")
        progress.adoption_policy = str(adoption_policy)
        progress.authorization_snapshot = dict(snapshot)
        progress.asset_summary = build_asset_summary(progress.quality_stats)

    async def _restore_llm_execution_snapshot(
        self,
        db: AsyncSession,
        task: Any,
        progress: DeepImportProgress,
        meta: dict[str, Any],
    ) -> dict[str, Any] | None:
        snapshot = meta.get("llm_execution_snapshot")
        if not isinstance(snapshot, dict) or not snapshot:
            # Compatibility for already-created local tasks. New production
            # submissions always persist the snapshot.
            snapshot = await self._build_snapshot(db, str(meta.get("novel_id") or ""))
            next_meta = dict(meta)
            next_meta["llm_execution_snapshot"] = snapshot
            task.meta = next_meta
        progress.llm_execution_snapshot = dict(snapshot)
        return await self._restore_snapshot(
            db,
            str(meta.get("novel_id") or ""),
            snapshot,
        )

    async def _build_llm_execution_snapshot(
        self,
        db: AsyncSession,
        novel_id: str,
    ) -> dict[str, Any]:
        snapshot = await self._build_snapshot(db, novel_id)
        await self._restore_snapshot(db, novel_id, snapshot)
        return snapshot

    async def _build_snapshot(
        self,
        db: AsyncSession,
        novel_id: str,
    ) -> dict[str, Any]:
        if self._snapshot_builder is not None:
            return await self._snapshot_builder(db, novel_id)
        from modules.project.facade import build_project_llm_execution_snapshot

        return await build_project_llm_execution_snapshot(db, novel_id)

    async def _restore_snapshot(
        self,
        db: AsyncSession,
        novel_id: str,
        snapshot: dict[str, Any],
    ) -> dict[str, Any] | None:
        if self._snapshot_restorer is not None:
            return await self._snapshot_restorer(db, novel_id, snapshot)
        from modules.project.facade import restore_project_llm_execution_settings

        return await restore_project_llm_execution_settings(db, novel_id, snapshot)

    @staticmethod
    def _task_progress_value(task: Any) -> float:
        try:
            return float(getattr(task, "progress", 0.0) or 0.0)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _scene_stage_progress_value(progress: DeepImportProgress) -> float:
        """Map Scene sub-phases to an elapsed-time-based stage estimate."""
        if progress.phase == "done":
            return 1.0

        current_phase = progress.current_phase
        current_item = progress.current_item or {}
        completed = current_item.get("completed")
        total = current_item.get("total")
        try:
            fraction = min(1.0, max(0.0, float(completed) / float(total)))
        except (TypeError, ValueError, ZeroDivisionError):
            fraction = 0.0

        if current_phase == "phase1a_scene_slicing":
            return SCENE_STAGE_PHASE1A_WEIGHT * fraction
        if current_phase == "phase1b_enrichment":
            return SCENE_STAGE_PHASE1A_WEIGHT + SCENE_STAGE_PHASE1B_WEIGHT * fraction
        if current_phase == "phase1c_scene_fusion":
            return SCENE_STAGE_COMMIT_START
        if current_phase == "scene_commit":
            return SCENE_STAGE_COMMIT_START
        return 0.0

    @classmethod
    def _update_task_progress(cls, task: Any, progress_value: float) -> float:
        bounded = min(1.0, max(0.0, float(progress_value)))
        persisted = max(cls._task_progress_value(task), bounded)
        task.update_progress(persisted)
        return persisted

    async def resume_interrupted(
        self,
        db: AsyncSession,
        task_id: str,
    ) -> dict[str, Any]:
        from infrastructure.tasks.facade import (
            resume_manual_task,
            update_task_projection,
        )

        run = await self._get_recoverable_deep_import_run(db, task_id)
        result_data = dict(run.progress or {})
        for payload in (result_data,):
            payload["interrupted"] = False
            payload["recovery_required"] = False
            payload["recoverable"] = False
        lifecycle = dict(result_data.get("lifecycle") or {})
        lifecycle["reason"] = "manual_resume"
        lifecycle["recovery_required"] = False
        result_data["lifecycle"] = lifecycle

        run.progress = result_data
        resumed = await resume_manual_task(
            db,
            task_id=task_id,
            task_types=IMPORT_TASK_TYPES,
            novel_id=str(run.novel_id),
        )
        await self._runs.resume(db, task_id=task_id)
        await update_task_projection(
            db,
            task_id=task_id,
            task_type=str(run.workflow_type),
            novel_id=str(run.novel_id),
            result=result_data,
            meta_patch={
                "interrupted": False,
                "recovery_required": False,
                "recoverable": False,
            },
        )

        return {
            "workflow_id": str(run.id),
            "task_id": str(run.task_id),
            "status": resumed.status,
            "message": "深度导入恢复任务已重新入队",
        }

    async def abandon_recovery(
        self,
        db: AsyncSession,
        task_id: str,
    ) -> dict[str, Any]:
        from infrastructure.tasks.facade import cancel_recoverable_task

        run = await self._get_recoverable_deep_import_run(db, task_id)
        novel_id = str(run.novel_id)
        workflow_id = str(run.id)

        cleanup_summary = await self.cleanup_workflow_assets(db, novel_id, workflow_id)
        await cancel_recoverable_task(
            db,
            task_id=task_id,
            task_types=IMPORT_TASK_TYPES,
            novel_id=novel_id,
        )
        await self._runs.abandon(db, task_id=task_id)

        return {
            "workflow_id": workflow_id,
            "task_id": str(run.task_id),
            "status": "cancelled",
            "cleanup_summary": cleanup_summary,
            "message": "深度导入恢复已放弃",
        }

    async def cleanup_workflow_assets(
        self,
        db: AsyncSession,
        novel_id: str,
        workflow_id: str,
    ) -> dict[str, Any]:
        """Soft-deprecate business assets written by an abandoned workflow."""
        from modules.memory.facade import (
            rollback_deep_import_delta_logs_by_workflow,
        )
        from modules.outline.facade import (
            deprecate_deep_import_scenes_by_workflow,
            deprecate_deep_import_structure_assets_by_workflow,
        )
        from modules.world.facade import (
            deprecate_deep_import_entities_by_workflow,
            rollback_deep_import_aliases_by_workflow,
            rollback_deep_import_relations_by_workflow,
        )

        deprecated_scenes = await deprecate_deep_import_scenes_by_workflow(
            db,
            novel_id,
            workflow_id,
        )
        deprecated_entities = await deprecate_deep_import_entities_by_workflow(
            db,
            novel_id,
            workflow_id,
        )
        deprecated_structure_assets = (
            await deprecate_deep_import_structure_assets_by_workflow(
                db,
                novel_id,
                workflow_id,
            )
        )
        rolled_back_delta_logs = await rollback_deep_import_delta_logs_by_workflow(
            db,
            novel_id,
            workflow_id,
        )
        rolled_back_aliases = await rollback_deep_import_aliases_by_workflow(
            db,
            novel_id,
            workflow_id,
        )
        rolled_back_relations = await rollback_deep_import_relations_by_workflow(
            db,
            novel_id,
            workflow_id,
        )
        return {
            "deprecated_scenes": deprecated_scenes,
            "deprecated_entities": deprecated_entities,
            "deprecated_structure_assets": deprecated_structure_assets,
            "hard_deleted_assets": 0,
            "cleanup_mode": "soft_deprecate",
            "rolled_back_delta_logs": rolled_back_delta_logs,
            "rolled_back_aliases": rolled_back_aliases,
            "rolled_back_relations": rolled_back_relations,
            # Deprecated wire aliases retained during the compatibility window.
            "skipped_delta_logs": 0,
            "cleanup_todo": None,
        }

    async def _get_recoverable_deep_import_run(
        self,
        db: AsyncSession,
        task_id: str,
    ) -> ImportWorkflowRun:
        # Lazy convergence closes the small window between TaskWorker terminal
        # finalization and the next startup reconciliation pass.
        await self._runs.reconcile_scoped_task_owners(
            db,
            task_id=task_id,
        )
        run = await self._runs.get_by_task(db, task_id=task_id, for_update=True)
        if run is None:
            from infrastructure.tasks.facade import (
                get_task_owner,
                list_task_lifecycle_contracts,
            )

            owner = await get_task_owner(db, task_id=task_id)
            if owner is not None:
                contracts = await list_task_lifecycle_contracts(
                    db,
                    task_ids=[task_id],
                    novel_id=owner.novel_id,
                    max_heartbeat_gap=0.0,
                )
                contract = contracts.get(task_id)
                if contract is not None and contract.task_type not in IMPORT_TASK_TYPES:
                    raise ValueError(
                        "task_id must reference a deep_import or deep import stage task"
                    )
            raise TaskNotFoundError(task_id)
        if run.workflow_type not in IMPORT_TASK_TYPES:
            raise ValueError(
                "task_id must reference a deep_import or deep import stage task"
            )
        if run.status != "failed":
            raise ValueError("only failed interrupted deep import tasks can recover")
        if not run.recovery_required:
            raise ValueError("deep import task does not require recovery")
        return run

    async def _check_duplicate_import(
        self,
        db: AsyncSession,
        novel_id: str,
        start_chapter: int,
        end_chapter: int,
    ) -> str | None:
        """检查指定章节范围内是否已有派生 Scene 或实体数据。"""
        from modules.outline.facade import get_scenes_by_novel
        from modules.world.facade import list_auto_ingested_entities

        scenes = await get_scenes_by_novel(
            db, novel_id, status_filter=["candidate", "draft", "canonical"]
        )
        overlapping_scenes = [
            s for s in scenes if self._scene_overlaps_range(s, start_chapter, end_chapter)
        ]
        replaceable_scenes = [
            scene
            for scene in overlapping_scenes
            if self._is_workflow_owned_deep_import_scene(scene)
            and scene.get("status") in {"candidate", "draft"}
            and (scene.get("structure_meta") or {}).get("user_edited") is not True
        ]
        protected_scenes = [
            scene for scene in overlapping_scenes if scene not in replaceable_scenes
        ]
        overlapping_entities = await list_auto_ingested_entities(
            db,
            novel_id,
            start_chapter=start_chapter,
            end_chapter=end_chapter,
        )

        if overlapping_scenes or overlapping_entities:
            return (
                f"第 {start_chapter}-{end_chapter} 章已有 "
                f"{len(replaceable_scenes)} 个可替换 Scene、"
                f"{len(protected_scenes)} 个已采用/受保护 Scene、"
                f"{len(overlapping_entities)} 个实体。"
                "重新提取会替换未确认 Scene；受保护 Scene 只生成比较建议，"
                "不会直接覆盖，实体也不会在入队时清理。是否继续？"
            )
        return None

    @staticmethod
    async def _find_active_import_task(
        db: AsyncSession,
        novel_id: str,
    ) -> ImportWorkflowRun | None:
        """Return the imports-owned run that still owns this project pipeline."""
        service = ImportWorkflowRunService()
        await service.reconcile_scoped_task_owners(
            db,
            novel_id=novel_id,
        )
        return await service.get_active_for_novel(
            db,
            novel_id=novel_id,
        )

    @staticmethod
    def _existing_task_response(
        task: ImportWorkflowRun,
        fallback_authorization_snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        meta = getattr(task, "meta", None)
        meta = meta if isinstance(meta, dict) else {}
        authorization_snapshot = getattr(task, "authorization_snapshot", None)
        if not isinstance(authorization_snapshot, dict):
            authorization_snapshot = meta.get("authorization_snapshot")
        if not isinstance(authorization_snapshot, dict):
            authorization_snapshot = fallback_authorization_snapshot
        task_id = str(getattr(task, "task_id", None) or task.id)
        return {
            "workflow_id": str(task.id),
            "task_id": task_id,
            "status": str(task.status or "pending"),
            "requires_confirmation": False,
            "reused_task": True,
            "workflow_type": str(
                getattr(task, "workflow_type", None)
                or getattr(task, "task_type", "deep_import")
            ),
            "stage": getattr(task, "stage", None) or meta.get("stage"),
            "adoption_policy": authorization_snapshot.get(
                "adoption_policy",
                DEFAULT_ADOPTION_POLICY,
            ),
            "authorization_snapshot": authorization_snapshot,
            "message": "已有自动提取任务仍在执行或等待恢复，已连接到原任务",
        }

    async def _enqueue_deep_import(
        self,
        db: AsyncSession,
        novel_id: str,
        start_chapter: int,
        end_chapter: int,
        *,
        context_mode: str = "working",
        include_pending_objects: bool = True,
        high_quality: bool = False,
        replace_existing: bool = False,
        authorization_snapshot: dict[str, Any],
        llm_execution_snapshot: dict[str, Any] | None = None,
    ) -> _WorkflowEnqueueResult:
        return await self._enqueue_workflow(
            db,
            task_type="deep_import",
            stage=None,
            novel_id=novel_id,
            start_chapter=start_chapter,
            end_chapter=end_chapter,
            context_mode=context_mode,
            include_pending_objects=include_pending_objects,
            high_quality=high_quality,
            replace_existing=replace_existing,
            authorization_snapshot=authorization_snapshot,
            llm_execution_snapshot=llm_execution_snapshot or {},
        )

    async def _enqueue_workflow(
        self,
        db: AsyncSession,
        *,
        task_type: str,
        novel_id: str,
        start_chapter: int,
        end_chapter: int,
        stage: str | None,
        context_mode: str,
        include_pending_objects: bool,
        high_quality: bool,
        replace_existing: bool,
        authorization_snapshot: dict[str, Any],
        llm_execution_snapshot: dict[str, Any],
    ) -> _WorkflowEnqueueResult:
        from infrastructure.tasks.facade import (
            enqueue_coalesced_task,
            update_task_projection,
        )
        from modules.project.facade import require_active_project_exclusive

        # All imports task types share one project-owned pipeline even though
        # their queue coalescing keys include task_type. Recheck under the
        # project row lock so direct facade/internal callers cannot race a
        # different task type into an orphan queue row.
        await require_active_project_exclusive(db, novel_id)
        await self._runs.reconcile_scoped_task_owners(
            db,
            novel_id=novel_id,
        )
        active = await self._runs.get_active_for_novel(
            db,
            novel_id=novel_id,
            for_update=True,
        )
        if active is not None:
            return _WorkflowEnqueueResult(
                task_id=str(active.task_id),
                reused=True,
            )

        task_meta = {
            "novel_id": novel_id,
            "start_chapter": start_chapter,
            "end_chapter": end_chapter,
            "stage": stage,
            "context_mode": context_mode,
            "include_pending_objects": include_pending_objects,
            "high_quality": high_quality,
            "replace_existing": replace_existing,
            "adoption_policy": authorization_snapshot["adoption_policy"],
            "authorization_confirmed": authorization_snapshot["authorization_confirmed"],
            "authorization_snapshot": authorization_snapshot,
            "llm_execution_snapshot": llm_execution_snapshot,
        }
        queued = await enqueue_coalesced_task(
            db,
            task_type=task_type,
            novel_id=novel_id,
            scope=("imports_pipeline",),
            meta=task_meta,
            mode="reuse_active",
        )
        existing = await self._runs.get_by_task(db, task_id=queued.task_id)
        initial_result = {
            "workflow_type": task_type,
            "stage": stage,
            "adoption_policy": authorization_snapshot["adoption_policy"],
            "authorization_snapshot": authorization_snapshot,
            "llm_execution_snapshot": llm_execution_snapshot,
            "asset_summary": empty_asset_summary(),
        }
        if existing is None:
            await self._runs.create_pending(
                db,
                task_id=queued.task_id,
                novel_id=novel_id,
                workflow_type=task_type,
                stage=stage,
                start_chapter=start_chapter,
                end_chapter=end_chapter,
                authorization_snapshot=authorization_snapshot,
                llm_execution_snapshot=llm_execution_snapshot,
                context_mode=context_mode,
                include_pending_objects=include_pending_objects,
                high_quality=high_quality,
                replace_existing=replace_existing,
                initial_progress=initial_result,
            )
            await update_task_projection(
                db,
                task_id=queued.task_id,
                task_type=task_type,
                novel_id=novel_id,
                result=initial_result,
            )
        return _WorkflowEnqueueResult(
            task_id=queued.task_id,
            reused=bool(queued.reused or existing is not None),
        )

    async def _enqueue_stage_task(
        self,
        db: AsyncSession,
        *,
        task_type: str,
        novel_id: str,
        start_chapter: int,
        end_chapter: int,
        stage: str,
        context_mode: str = "working",
        include_pending_objects: bool = True,
        high_quality: bool = False,
        replace_existing: bool = False,
        authorization_snapshot: dict[str, Any],
        llm_execution_snapshot: dict[str, Any] | None = None,
    ) -> _WorkflowEnqueueResult:
        return await self._enqueue_workflow(
            db,
            task_type=task_type,
            novel_id=novel_id,
            start_chapter=start_chapter,
            end_chapter=end_chapter,
            stage=stage,
            context_mode=context_mode,
            include_pending_objects=include_pending_objects,
            high_quality=high_quality,
            replace_existing=replace_existing,
            authorization_snapshot=authorization_snapshot,
            llm_execution_snapshot=llm_execution_snapshot or {},
        )

    @staticmethod
    def _stage_pending_message(stage: str, start_chapter: int, end_chapter: int) -> str:
        labels = {
            "scenes": "从正文提取 Scene",
            "world_objects": "世界对象与别名/关系自动提取",
            "plot_structure": "剧情线自动提取",
        }
        return (
            f"{labels.get(stage, '自动提取')}任务已提交"
            f"（第{start_chapter}-{end_chapter}章）"
        )

    @staticmethod
    def _scene_overlaps_range(scene: dict[str, Any], start: int, end: int) -> bool:
        chapter_ids = scene.get("chapter_ids") or []
        try:
            indices = [int(x) for x in chapter_ids if x is not None]
        except (ValueError, TypeError):
            return False
        if not indices:
            return False
        return any(start <= idx <= end for idx in indices)

    @staticmethod
    def _is_workflow_owned_deep_import_scene(scene: dict[str, Any]) -> bool:
        if str(scene.get("source") or "") != "deep_import":
            return False
        structure_meta = scene.get("structure_meta")
        if not isinstance(structure_meta, dict):
            return False
        return bool(structure_meta.get("workflow_id")) or (
            structure_meta.get("auto_ingested") is True
        )

    @staticmethod
    def _result_from_progress(progress: DeepImportProgress) -> dict[str, Any]:
        trim_progress_diagnostics(progress)
        progress.asset_summary = build_asset_summary(progress.quality_stats)
        return {
            "workflow_type": progress.workflow_type,
            "stage": progress.stage,
            "adoption_policy": progress.adoption_policy,
            "authorization_snapshot": progress.authorization_snapshot,
            "llm_execution_snapshot": progress.llm_execution_snapshot,
            "asset_summary": progress.asset_summary,
            "phase": progress.phase,
            "current_step": (
                progress.current_step.value if progress.current_step else None
            ),
            "completed_steps": progress.completed_steps,
            "message": progress.message,
            "current_phase": progress.current_phase,
            "current_round": progress.current_round,
            "current_chapter_range": progress.current_chapter_range,
            "current_chapter": progress.current_chapter,
            "current_scene_candidate_id": progress.current_scene_candidate_id,
            "current_window": progress.current_window,
            "current_operation": progress.current_operation,
            "current_item": progress.current_item,
            "phase_timeline": progress.phase_timeline,
            "progress_events": progress.progress_events,
            "acceptance_checks": progress.acceptance_checks,
            "diagnostic_counts": progress.diagnostic_counts,
            "last_error": progress.last_error,
            "quality_stats": progress.quality_stats,
            "phase_artifacts": progress.phase_artifacts,
            "checkpoints": progress.checkpoints,
            "recovery_summary": progress.recovery_summary,
            "interrupted": progress.interrupted,
            "recoverable": progress.recoverable,
            "recovery_required": progress.recovery_required,
            "interrupted_at": progress.interrupted_at,
            "last_heartbeat_at": progress.last_heartbeat_at,
            "degraded": progress.degraded,
            "degraded_reason": progress.degraded_reason,
            "phase1a_fallback": progress.phase1a_fallback,
            "degraded_batches": progress.degraded_batches,
            "quality_status": progress.quality_status,
            "phase_errors": progress.phase_errors,
            "llm_health": progress.llm_health,
            "snapshot_health_summary": progress.snapshot_health_summary,
            "audit_summary": progress.audit_summary,
        }
