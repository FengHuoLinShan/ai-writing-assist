"""Deep import orchestration policy.

Owns duplicate detection, replacement/deprecation policy, task submission, and
task progress shaping for the user-confirmed deep import pipeline.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.tasks.models import AsyncTask
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
from modules.imports.workflow_schemas import DeepImportProgress, DeepImportStep
from shared.constants import TASK_HEARTBEAT_INTERVAL
from shared.utils import parse_uuid as _parse_uuid

ProgressObserver = Callable[[DeepImportProgress, float, Any], Awaitable[None]]

STAGE_TASK_TYPES = {
    "scenes": "scene_auto_extraction",
    "world_objects": "world_object_auto_extraction",
    "plot_structure": "plot_structure_auto_extraction",
}

# Scene stage progress is an elapsed-time estimate based on the two most recent
# 1-60 chapter runs of the current pipeline. Phase 0 is intentionally excluded:
# it completed in under 0.1 seconds in both runs.
SCENE_STAGE_PHASE1A_WEIGHT = 0.59
SCENE_STAGE_PHASE1B_WEIGHT = 0.40
SCENE_STAGE_COMMIT_START = 0.99


class DeepImportWorkflowFailedError(RuntimeError):
    """A persisted workflow failure that must become a failed async task."""


class DeepImportOrchestrator:
    """Stable implementation behind imports facade and task handler."""

    def __init__(
        self,
        workflow: DeepImportWorkflow | None = None,
        *,
        progress_observer: ProgressObserver | None = None,
    ) -> None:
        self.workflow = workflow or DeepImportWorkflow()
        self.progress_observer = progress_observer

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
        await self._initialize_task_result(
            db,
            task_id,
            authorization_snapshot,
            llm_execution_snapshot,
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
        await self._initialize_task_result(
            db,
            task_id,
            authorization_snapshot,
            llm_execution_snapshot,
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
        return self._result_from_progress(progress)

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

    async def run_submitted_stage_inline(
        self,
        db: AsyncSession,
        task_id: str,
        *,
        stage: str,
    ) -> dict[str, Any]:
        """Execute one already-authorized stage task without a worker process.

        This is intended for isolated evaluation/manual harnesses that cannot run
        a background worker. It invokes the registered handler logic and mirrors
        worker status/provenance handling inside the caller's transaction.
        """
        if stage not in STAGE_TASK_TYPES:
            raise ValueError(f"unsupported deep import stage: {stage}")
        task = await db.get(AsyncTask, _parse_uuid(task_id))
        if task is None:
            raise TaskNotFoundError(task_id)
        expected_type = STAGE_TASK_TYPES[stage]
        if task.task_type != expected_type:
            raise ValueError(f"task type {task.task_type} does not match stage {stage}")
        from infrastructure.llm.agent_step_harness import (
            managed_llm_provenance_scope,
            merge_managed_llm_provenance,
        )
        from infrastructure.llm.redaction import redact_diagnostic

        with managed_llm_provenance_scope() as managed_llm_steps:
            heartbeat_task: asyncio.Task[None] | None = None
            try:
                task.mark_running()
                await db.flush()
                heartbeat_task = asyncio.create_task(self._inline_heartbeat_loop(task.id))
                result = await self.run_stage_task(db, task, stage=stage)
                if managed_llm_steps:
                    result = merge_managed_llm_provenance(
                        result,
                        managed_llm_steps,
                    )
                task.mark_done(result)
                await db.flush()
                return result
            except asyncio.CancelledError:
                task.mark_cancelled()
                await db.flush()
                raise
            except Exception as exc:
                task.mark_failed(
                    redact_diagnostic(
                        f"{type(exc).__name__}: {exc}",
                        limit=1000,
                    )
                )
                await db.flush()
                raise
            finally:
                if heartbeat_task is not None:
                    heartbeat_task.cancel()
                    try:
                        await heartbeat_task
                    except asyncio.CancelledError:
                        pass

    @staticmethod
    async def _inline_heartbeat_loop(task_id: Any) -> None:
        """Keep inline eval/manual tasks out of the worker stale-task scanner."""
        from core.database import get_manager

        while True:
            await asyncio.sleep(TASK_HEARTBEAT_INTERVAL)
            try:
                async with get_manager().session_factory() as session:
                    await session.execute(
                        update(AsyncTask)
                        .where(AsyncTask.id == task_id)
                        .values(heartbeat_at=datetime.now(UTC))
                    )
                    await session.commit()
            except Exception:
                # The primary workflow owns the result. A transient heartbeat
                # failure must not mask or cancel that work.
                return

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

    @staticmethod
    async def _restore_llm_execution_snapshot(
        db: AsyncSession,
        task: Any,
        progress: DeepImportProgress,
        meta: dict[str, Any],
    ) -> dict[str, Any] | None:
        snapshot = meta.get("llm_execution_snapshot")
        if not isinstance(snapshot, dict) or not snapshot:
            # Compatibility for already-created local tasks and lightweight unit
            # fakes. New production submissions always persist the snapshot.
            from unittest.mock import Mock

            if isinstance(db, Mock):
                return None
            from modules.project.facade import build_project_llm_execution_snapshot

            snapshot = await build_project_llm_execution_snapshot(
                db,
                str(meta.get("novel_id") or ""),
            )
            next_meta = dict(meta)
            next_meta["llm_execution_snapshot"] = snapshot
            task.meta = next_meta
        progress.llm_execution_snapshot = dict(snapshot)
        from modules.project.facade import restore_project_llm_execution_settings

        return await restore_project_llm_execution_settings(
            db,
            str(meta.get("novel_id") or ""),
            snapshot,
        )

    @staticmethod
    async def _build_llm_execution_snapshot(
        db: AsyncSession,
        novel_id: str,
    ) -> dict[str, Any]:
        from unittest.mock import Mock

        if isinstance(db, Mock):
            return {}
        from modules.project.facade import (
            build_project_llm_execution_snapshot,
            restore_project_llm_execution_settings,
        )

        snapshot = await build_project_llm_execution_snapshot(db, novel_id)
        await restore_project_llm_execution_settings(db, novel_id, snapshot)
        return snapshot

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

    @staticmethod
    async def _initialize_task_result(
        db: AsyncSession,
        task_id: str,
        authorization_snapshot: dict[str, Any],
        llm_execution_snapshot: dict[str, Any] | None = None,
    ) -> None:
        task = await db.get(AsyncTask, _parse_uuid(str(task_id)))
        if task is None:
            return
        task.result = {
            "adoption_policy": authorization_snapshot["adoption_policy"],
            "authorization_snapshot": authorization_snapshot,
            "llm_execution_snapshot": llm_execution_snapshot or {},
            "asset_summary": empty_asset_summary(),
        }

    async def resume_interrupted(
        self,
        db: AsyncSession,
        task_id: str,
    ) -> dict[str, Any]:
        task = await self._get_recoverable_deep_import_task(db, task_id)

        result_data = dict(task.result or {})
        meta_data = dict(task.meta or {})
        for payload in (result_data, meta_data):
            payload["interrupted"] = False
            payload["recovery_required"] = False
            payload["recoverable"] = False
        lifecycle = dict(result_data.get("lifecycle") or {})
        lifecycle["reason"] = "manual_resume"
        lifecycle["recovery_required"] = False
        result_data["lifecycle"] = lifecycle

        task.result = result_data
        task.meta = meta_data
        task.status = "pending"
        task.finished_at = None
        task.heartbeat_at = None
        task.lease_id = None
        task.transition_reason = "manual_resume"
        task.error_message = None
        await db.flush()

        return {
            "workflow_id": str(task.id),
            "task_id": str(task.id),
            "status": "pending",
            "message": "深度导入恢复任务已重新入队",
        }

    async def get_task_novel_id(
        self,
        db: AsyncSession,
        task_id: str,
    ) -> str:
        """Return the task owner after preserving the existing task 404 boundary."""
        stmt = select(AsyncTask).where(AsyncTask.id == _parse_uuid(task_id))
        task = (await db.execute(stmt)).scalar_one_or_none()
        if task is None:
            raise TaskNotFoundError(task_id)
        return str((task.meta or {}).get("novel_id") or "")

    async def abandon_recovery(
        self,
        db: AsyncSession,
        task_id: str,
    ) -> dict[str, Any]:
        task = await self._get_recoverable_deep_import_task(db, task_id)
        meta = task.meta or {}
        novel_id = meta.get("novel_id", "")
        workflow_id = str(task.id)

        cleanup_summary = await self.cleanup_workflow_assets(db, novel_id, workflow_id)
        task.mark_cancelled()
        await db.flush()

        return {
            "workflow_id": workflow_id,
            "task_id": str(task.id),
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
            rollback_deep_import_map_observations_by_workflow,
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
        rolled_back_map_observations = (
            await rollback_deep_import_map_observations_by_workflow(
                db,
                novel_id,
                workflow_id,
            )
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
            "rolled_back_map_observations": rolled_back_map_observations,
            "rolled_back_aliases": rolled_back_aliases,
            "rolled_back_relations": rolled_back_relations,
            # Deprecated wire aliases retained during the compatibility window.
            "skipped_delta_logs": 0,
            "skipped_map_observations": 0,
            "cleanup_todo": None,
        }

    async def _get_recoverable_deep_import_task(
        self,
        db: AsyncSession,
        task_id: str,
    ) -> AsyncTask:
        stmt = select(AsyncTask).where(AsyncTask.id == _parse_uuid(task_id))
        result = await db.execute(stmt)
        task = result.scalar_one_or_none()
        if task is None:
            raise TaskNotFoundError(task_id)
        allowed_task_types = {"deep_import", *STAGE_TASK_TYPES.values()}
        if task.task_type not in allowed_task_types:
            raise ValueError(
                "task_id must reference a deep_import or deep import stage task"
            )
        if task.status != "failed":
            raise ValueError("only failed interrupted deep import tasks can recover")

        result_data = task.result or {}
        meta_data = task.meta or {}
        if not (
            result_data.get("recovery_required") is True
            and meta_data.get("recovery_required") is True
        ):
            raise ValueError("deep import task does not require recovery")
        return task

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
            s
            for s in scenes
            if self._scene_overlaps_range(s, start_chapter, end_chapter)
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
    def _enqueue_deep_import(
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
    ):
        from infrastructure.tasks.enqueuer import enqueue_task

        return enqueue_task(
            db,
            "deep_import",
            meta={
                "novel_id": novel_id,
                "start_chapter": start_chapter,
                "end_chapter": end_chapter,
                "context_mode": context_mode,
                "include_pending_objects": include_pending_objects,
                "high_quality": high_quality,
                "replace_existing": replace_existing,
                "adoption_policy": authorization_snapshot["adoption_policy"],
                "authorization_confirmed": authorization_snapshot[
                    "authorization_confirmed"
                ],
                "authorization_snapshot": authorization_snapshot,
                "llm_execution_snapshot": llm_execution_snapshot or {},
            },
        )

    @staticmethod
    def _enqueue_stage_task(
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
    ):
        from infrastructure.tasks.enqueuer import enqueue_task

        return enqueue_task(
            db,
            task_type,
            meta={
                "novel_id": novel_id,
                "start_chapter": start_chapter,
                "end_chapter": end_chapter,
                "stage": stage,
                "context_mode": context_mode,
                "include_pending_objects": include_pending_objects,
                "high_quality": high_quality,
                "replace_existing": replace_existing,
                "adoption_policy": authorization_snapshot["adoption_policy"],
                "authorization_confirmed": authorization_snapshot[
                    "authorization_confirmed"
                ],
                "authorization_snapshot": authorization_snapshot,
                "llm_execution_snapshot": llm_execution_snapshot or {},
            },
        )

    @staticmethod
    def _stage_pending_message(stage: str, start_chapter: int, end_chapter: int) -> str:
        labels = {
            "scenes": "场景（scene）自动提取",
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
