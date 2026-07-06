"""Deep import orchestration policy.

Owns duplicate detection, replacement/deprecation policy, task submission, and
task progress shaping for the user-confirmed deep import pipeline.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.tasks.models import AsyncTask
from modules.imports.contracts import TaskNotFoundError
from modules.imports.workflow import DeepImportWorkflow
from modules.imports.workflow_schemas import DeepImportProgress, DeepImportStep
from shared.utils import parse_uuid as _parse_uuid

ProgressObserver = Callable[[DeepImportProgress, float, Any], Awaitable[None]]

STAGE_TASK_TYPES = {
    "scenes": "scene_auto_extraction",
    "world_objects": "world_object_auto_extraction",
    "plot_structure": "plot_structure_auto_extraction",
}


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
    ) -> dict[str, Any]:
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

        if force:
            await self._deprecate_derived_data(db, novel_id, start_chapter, end_chapter)

        task_id = self._enqueue_deep_import(
            db,
            novel_id,
            start_chapter,
            end_chapter,
            context_mode="working",
            include_pending_objects=True,
            high_quality=high_quality,
        )
        await db.flush()
        return {
            "workflow_id": str(task_id),
            "task_id": str(task_id),
            "status": "pending",
            "requires_confirmation": False,
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
    ) -> dict[str, Any]:
        if stage not in STAGE_TASK_TYPES:
            raise ValueError(f"unsupported deep import stage: {stage}")

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
            if force:
                await self._deprecate_derived_data(
                    db, novel_id, start_chapter, end_chapter
                )

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
        )
        await db.flush()
        return {
            "workflow_id": str(task_id),
            "task_id": str(task_id),
            "status": "pending",
            "requires_confirmation": False,
            "workflow_type": STAGE_TASK_TYPES[stage],
            "stage": stage,
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
        if not novel_id:
            raise ValueError("novel_id is required for deep_import")

        progress = self._progress_from_task(task)

        async def _record_progress(
            updated: DeepImportProgress,
            progress_value: float,
        ) -> None:
            task.result = updated.model_dump(mode="json")
            task.update_progress(progress_value)
            await db.commit()
            if self.progress_observer is not None:
                await self.progress_observer(updated, progress_value, task)

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
            on_progress=_record_progress,
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
        if not novel_id:
            raise ValueError(f"novel_id is required for {task.task_type}")

        progress = self._progress_from_task(task)
        progress.workflow_type = str(task.task_type)
        progress.stage = stage
        progress.total_steps = 1

        async def _record_progress(
            updated: DeepImportProgress,
            progress_value: float,
        ) -> None:
            updated.workflow_type = str(task.task_type)
            updated.stage = stage
            task.result = updated.model_dump(mode="json")
            task.update_progress(progress_value)
            await db.commit()
            if self.progress_observer is not None:
                await self.progress_observer(updated, progress_value, task)

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
                on_progress=_record_progress,
            )
        else:
            raise ValueError(f"unsupported deep import stage: {stage}")
        return self._result_from_progress(progress)

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

        task.result = result_data
        task.meta = meta_data
        task.status = "pending"
        task.finished_at = None
        task.error_message = None
        await db.flush()

        return {
            "workflow_id": str(task.id),
            "task_id": str(task.id),
            "status": "pending",
            "message": "深度导入恢复任务已重新入队",
        }

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
        from modules.memory.facade import count_deep_import_delta_logs_by_workflow
        from modules.outline.facade import (
            deprecate_deep_import_scenes_by_workflow,
            deprecate_deep_import_structure_assets_by_workflow,
        )
        from modules.world.facade import (
            count_deep_import_map_observations_by_workflow,
            deprecate_deep_import_entities_by_workflow,
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
        skipped_delta_logs = await count_deep_import_delta_logs_by_workflow(
            db,
            novel_id,
            workflow_id,
        )
        skipped_map_observations = (
            await count_deep_import_map_observations_by_workflow(
                db,
                novel_id,
                workflow_id,
            )
        )
        cleanup_todo = None
        if skipped_delta_logs or skipped_map_observations:
            cleanup_todo = (
                "delta logs and candidate map observations are counted but not "
                "mutated until their owning modules expose an abandon-cleanup policy"
            )
        return {
            "deprecated_scenes": deprecated_scenes,
            "deprecated_entities": deprecated_entities,
            "deprecated_structure_assets": deprecated_structure_assets,
            "hard_deleted_assets": 0,
            "cleanup_mode": "soft_deprecate",
            "skipped_delta_logs": skipped_delta_logs,
            "skipped_map_observations": skipped_map_observations,
            "cleanup_todo": cleanup_todo,
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
            db, novel_id, status_filter=["draft", "canonical"]
        )
        overlapping_scenes = [
            s for s in scenes if self._scene_overlaps_range(s, start_chapter, end_chapter)
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
                f"{len(overlapping_scenes)} 个 Scene、"
                f"{len(overlapping_entities)} 个实体。"
                f"重新导入将覆盖/刷新该范围数据。是否继续？"
            )
        return None

    async def _deprecate_derived_data(
        self,
        db: AsyncSession,
        novel_id: str,
        start_chapter: int,
        end_chapter: int,
    ) -> dict[str, int]:
        """将指定章节范围内的旧派生 Scene 和自动实体标记为 deprecated。"""
        from modules.outline.facade import get_scenes_by_novel, update_scene
        from modules.world.facade import list_auto_ingested_entities, update_entity

        deprecated_scenes = 0
        scenes = await get_scenes_by_novel(
            db, novel_id, status_filter=["draft", "canonical"]
        )
        for scene in scenes:
            if self._scene_overlaps_range(scene, start_chapter, end_chapter):
                await update_scene(db, novel_id, scene["id"], {"status": "deprecated"})
                deprecated_scenes += 1

        deprecated_entities = 0
        entities = await list_auto_ingested_entities(
            db,
            novel_id,
            start_chapter=start_chapter,
            end_chapter=end_chapter,
        )
        for entity in entities:
            await update_entity(db, novel_id, entity["id"], {"status": "deprecated"})
            deprecated_entities += 1

        return {
            "deprecated_scenes": deprecated_scenes,
            "deprecated_entities": deprecated_entities,
        }

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
    def _result_from_progress(progress: DeepImportProgress) -> dict[str, Any]:
        return {
            "workflow_type": progress.workflow_type,
            "stage": progress.stage,
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
