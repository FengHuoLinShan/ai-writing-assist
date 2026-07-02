"""Entity extraction phases for deep import workflows."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.imports.service_phase_artifacts import (
    add_phase_artifact,
    phase2_checkpoint_summary,
    phase2_repair_summary,
)
from modules.imports.workflow_schemas import DeepImportProgress, DeepImportStep


class EntityExtractionPhaseRunner:
    """Runs Phase 2 in full-pipeline and stage-only modes."""

    def __init__(self, workflow: Any) -> None:
        self.workflow = workflow

    async def run_full_pipeline_phase(
        self,
        db: AsyncSession,
        novel_id: str,
        progress: DeepImportProgress,
        *,
        workflow_id: str | None,
        total_scenes: int,
        on_progress: Callable[[DeepImportProgress, float], Awaitable[None]] | None,
    ) -> dict[str, Any]:
        workflow = self.workflow
        progress.current_step = DeepImportStep.entity_extraction
        progress.current_phase = "entity_extraction"
        progress.current_operation = "scene_entity_extraction"
        progress.message = "正在按 Scene 提取世界对象..."
        workflow._start_phase(
            progress,
            "entity_extraction",
            item={"kind": "scene", "completed": 0, "total": total_scenes},
        )
        await workflow._emit_progress(progress, 0.4, on_progress)

        async def _on_scene_progress(completed: int, total: int) -> None:
            progress.phase2_total_scenes = total
            progress.phase2_completed_scenes = completed
            progress.current_item = {
                "kind": "scene",
                "completed": completed,
                "total": total,
            }
            value = 0.4 + 0.4 * (completed / total) if total else 0.4
            await workflow._emit_progress(progress, value, on_progress)

        phase2_failed = False
        repair_summary: dict[str, Any] | None = None
        try:
            phase2_result = await workflow._extract_entities_by_scene(
                db,
                novel_id,
                workflow_id=workflow_id,
                on_scene_progress=_on_scene_progress,
                existing_checkpoints=progress.checkpoints,
            )
            workflow._merge_checkpoints(progress, phase2_result)
            phase2_result, repair_summary = await self._maybe_repair_phase2a(
                db,
                novel_id,
                progress,
                phase2_result,
                workflow_id=workflow_id,
                on_scene_progress=_on_scene_progress,
            )
            workflow._mark_step_completed(progress, DeepImportStep.entity_extraction)
            workflow._merge_audit_summary(progress, phase2_result)
            workflow._merge_snapshot_health_summary(progress, phase2_result)
            progress.quality_stats["phase2"] = phase2_quality_stats(phase2_result)
            await workflow._refresh_snapshot_health_summary(
                db,
                novel_id,
                workflow_id or progress.workflow_id,
                progress,
            )
            progress.message = (
                "实体提取完成，共创建 "
                f"{phase2_result.get('total_created', 0)} 个实体，"
                f"{phase2_result.get('total_relations', 0)} 条关系，"
                f"记录 {phase2_result.get('total_deltas', 0)} 条变更。"
            )
            if phase2_result.get("degraded"):
                progress.degraded = True
                skipped_scenes = phase2_result.get("skipped_scenes", 0)
                failed_scenes = phase2_result.get("failed_scene_indices", [])
                details = []
                if failed_scenes:
                    details.append(f"失败 Scene: {failed_scenes}")
                if skipped_scenes:
                    details.append(f"跳过 {skipped_scenes} 个 Scene")
                error_message = (
                    phase2_result.get("error_message") or "实体提取部分降级"
                )
                if details:
                    error_message = f"{error_message}（{'；'.join(details)}）"
                progress.phase_errors.append(
                    {
                        "phase": DeepImportStep.entity_extraction.value,
                        "error_kind": phase2_result.get("error_kind", "degraded"),
                        "message": error_message[:300],
                    }
                )
            workflow._finish_phase(
                progress,
                "entity_extraction",
                status="degraded" if phase2_result.get("degraded") else "completed",
                details=progress.quality_stats["phase2"],
                error_kind=phase2_result.get("error_kind")
                if phase2_result.get("degraded")
                else None,
                error_message=phase2_result.get("error_message")
                if phase2_result.get("degraded")
                else None,
            )
        except Exception as exc:
            phase2_failed = True
            await workflow._rollback_after_phase_failure(db, "entity_extraction", exc)
            phase2_result = {
                "total_created": 0,
                "total_relations": 0,
                "total_deltas": 0,
                "completed_scenes": 0,
                "skipped_scenes": 0,
                "failed_scene_indices": [],
                "fallback_created": 0,
                "error_kind": "phase_failed",
                "error_message": str(exc)[:300],
            }
            progress.quality_stats["phase2"] = phase2_quality_stats(phase2_result)
            progress.degraded = True
            progress.phase_errors.append(
                {
                    "phase": DeepImportStep.entity_extraction.value,
                    "error_kind": "phase_failed",
                    "message": f"实体提取阶段失败，已继续后续阶段：{str(exc)[:180]}",
                }
            )
            progress.message = "实体提取阶段失败，已降级继续结构分析。"
            workflow._finish_phase(
                progress,
                "entity_extraction",
                status="failed",
                details=progress.quality_stats["phase2"],
                error_kind="phase_failed",
                error_message=str(exc),
            )
            repair_summary = phase2_repair_summary(phase2_result)
        if (
            not phase2_failed
            and total_scenes > 0
            and phase2_result.get("total_created", 0) <= 0
        ):
            progress.degraded = True
            progress.phase_errors.append(
                {
                    "phase": DeepImportStep.entity_extraction.value,
                    "error_kind": phase2_result.get("error_kind", "empty_output"),
                    "message": "实体提取阶段未生成任何实体",
                }
            )
            workflow._finish_phase(
                progress,
                "entity_extraction",
                status="degraded",
                details=progress.quality_stats["phase2"],
                error_kind=phase2_result.get("error_kind", "empty_output"),
                error_message="实体提取阶段未生成任何实体",
            )
        phase2_degraded = (
            bool(phase2_result.get("degraded"))
            or (
                not phase2_failed
                and total_scenes > 0
                and int(phase2_result.get("total_created", 0) or 0) <= 0
            )
        )
        add_phase_artifact(
            progress,
            "entity_extraction",
            start_chapter=0,
            end_chapter=0,
            status="failed"
            if phase2_failed
            else ("degraded" if phase2_degraded else "completed"),
            quality_status="failed"
            if phase2_failed
            else ("partial" if phase2_degraded else "complete"),
            quality_stats=progress.quality_stats["phase2"],
            counts=_phase2_counts(phase2_result),
            repair_summary=repair_summary,
            checkpoint_summary=phase2_checkpoint_summary(progress.checkpoints),
            errors=[
                error
                for error in progress.phase_errors
                if error.get("phase") == DeepImportStep.entity_extraction.value
            ],
        )
        return phase2_result

    async def run_stage_only(
        self,
        db: AsyncSession,
        novel_id: str,
        start_chapter: int,
        end_chapter: int,
        progress: DeepImportProgress,
        *,
        workflow_id: str | None = None,
        on_progress: Callable[[DeepImportProgress, float], Awaitable[None]] | None = None,
    ) -> DeepImportProgress:
        """Run Phase 2a/2b against already committed Scenes."""

        workflow = self.workflow
        progress.phase = "running"
        progress.current_step = DeepImportStep.entity_extraction
        progress.current_phase = "entity_extraction"
        progress.current_operation = "scene_entity_extraction"
        progress.message = "正在按 Scene 提取世界对象与别名/关系..."
        workflow._start_phase(
            progress,
            "entity_extraction",
            item={
                "kind": "chapter_range",
                "start_chapter": start_chapter,
                "end_chapter": end_chapter,
            },
        )
        await workflow._emit_progress(progress, 0.05, on_progress)

        if workflow._is_llm_health_required():
            health = await workflow._check_llm_health(db, novel_id)
            progress.llm_health = health.model_dump()
            if not health.ok:
                return await workflow._fail_preflight(progress, health, on_progress)

        if not await workflow._has_scenes_in_range(
            db,
            novel_id,
            start_chapter,
            end_chapter,
        ):
            progress.phase = "failed"
            progress.quality_status = "failed"
            progress.current_step = None
            progress.degraded = True
            progress.degraded_reason = "missing_scene_prerequisite"
            progress.message = "请先执行场景（scene）自动提取"
            progress.phase_errors.append(
                {
                    "phase": DeepImportStep.entity_extraction.value,
                    "error_kind": "missing_scene_prerequisite",
                    "message": progress.message,
                }
            )
            workflow._finish_phase(
                progress,
                "entity_extraction",
                status="failed",
                error_kind="missing_scene_prerequisite",
                error_message=progress.message,
            )
            add_phase_artifact(
                progress,
                "entity_extraction",
                start_chapter=start_chapter,
                end_chapter=end_chapter,
                status="failed",
                quality_status="failed",
                quality_stats={},
                counts={},
                repair_summary=phase2_repair_summary({"total_scenes": 0}),
                errors=[
                    error
                    for error in progress.phase_errors
                    if error.get("phase") == DeepImportStep.entity_extraction.value
                ],
            )
            await workflow._emit_progress(progress, 1.0, on_progress)
            return progress

        async def _on_scene_progress(completed: int, total: int) -> None:
            progress.phase2_total_scenes = total
            progress.phase2_completed_scenes = completed
            progress.current_item = {
                "kind": "scene",
                "completed": completed,
                "total": total,
            }
            value = 0.1 + 0.85 * (completed / total) if total else 0.1
            await workflow._emit_progress(progress, value, on_progress)

        phase2_result = await workflow._extract_entities_by_scene(
            db,
            novel_id,
            workflow_id=workflow_id,
            on_scene_progress=_on_scene_progress,
            existing_checkpoints=progress.checkpoints,
            start_chapter=start_chapter,
            end_chapter=end_chapter,
        )
        workflow._merge_checkpoints(progress, phase2_result)
        phase2_result, repair_summary = await self._maybe_repair_phase2a(
            db,
            novel_id,
            progress,
            phase2_result,
            workflow_id=workflow_id,
            on_scene_progress=_on_scene_progress,
            start_chapter=start_chapter,
            end_chapter=end_chapter,
        )
        workflow._merge_audit_summary(progress, phase2_result)
        workflow._merge_snapshot_health_summary(progress, phase2_result)
        progress.quality_stats["phase2"] = phase2_quality_stats(phase2_result)
        await workflow._refresh_snapshot_health_summary(
            db,
            novel_id,
            workflow_id or progress.workflow_id,
            progress,
        )
        if phase2_result.get("total_scenes", 0) <= 0:
            progress.phase = "failed"
            progress.quality_status = "failed"
            progress.degraded = True
            progress.degraded_reason = "missing_scene_prerequisite"
            progress.phase_errors.append(
                {
                    "phase": DeepImportStep.entity_extraction.value,
                    "error_kind": "missing_scene_prerequisite",
                    "message": "请先执行场景（scene）自动提取",
                }
            )
        else:
            phase2a_failed = _has_phase2a_failures(phase2_result)
            if not phase2a_failed:
                workflow._mark_step_completed(
                    progress,
                    DeepImportStep.entity_extraction,
                )
                progress.phase = "done"
                progress.quality_status = (
                    "partial"
                    if phase2_result.get("degraded")
                    or int(phase2_result.get("total_created", 0) or 0) <= 0
                    else "complete"
                )
            if phase2_result.get("degraded"):
                progress.degraded = True
                progress.phase_errors.append(
                    {
                        "phase": DeepImportStep.entity_extraction.value,
                        "error_kind": phase2_result.get("error_kind", "degraded"),
                        "message": (
                            phase2_result.get("error_message")
                            or "世界对象与别名/关系提取部分降级"
                        )[:300],
                    }
                )
            if phase2a_failed:
                progress.phase = "failed"
                progress.quality_status = "failed"
                progress.degraded = True
                progress.degraded_reason = "phase2a_failed"
                progress.phase_errors.append(
                    {
                        "phase": DeepImportStep.entity_extraction.value,
                        "error_kind": "phase2a_failed",
                        "message": "Phase2a 世界对象抽取仍有失败 Scene 或 batch。",
                    }
                )
            progress.message = (
                "世界对象与别名/关系自动提取完成，共创建 "
                f"{phase2_result.get('total_created', 0)} 个实体，"
                f"{phase2_result.get('total_aliases', 0)} 个别名，"
                f"{phase2_result.get('total_relations', 0)} 条关系。"
            )

        progress.current_step = None
        workflow._finish_phase(
            progress,
            "entity_extraction",
            status="degraded" if progress.degraded else "completed",
            details=progress.quality_stats.get("phase2"),
            error_kind=progress.degraded_reason,
            error_message=progress.message if progress.phase == "failed" else None,
        )
        add_phase_artifact(
            progress,
            "entity_extraction",
            start_chapter=start_chapter,
            end_chapter=end_chapter,
            status="failed"
            if progress.phase == "failed"
            else ("degraded" if progress.degraded else "completed"),
            quality_status=progress.quality_status,
            quality_stats=progress.quality_stats.get("phase2") or {},
            counts=_phase2_counts(phase2_result),
            repair_summary=repair_summary,
            checkpoint_summary=phase2_checkpoint_summary(progress.checkpoints),
            errors=[
                error
                for error in progress.phase_errors
                if error.get("phase") == DeepImportStep.entity_extraction.value
            ],
        )
        await workflow._emit_progress(progress, 1.0, on_progress)
        return progress

    async def _maybe_repair_phase2a(
        self,
        db: AsyncSession,
        novel_id: str,
        progress: DeepImportProgress,
        phase2_result: dict[str, Any],
        *,
        workflow_id: str | None,
        on_scene_progress: Callable[[int, int], Awaitable[None]] | None,
        start_chapter: int | None = None,
        end_chapter: int | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        repair_summary = phase2_repair_summary(phase2_result)
        if not repair_summary["within_policy"]:
            return phase2_result, repair_summary
        if not _has_phase2a_failures(phase2_result):
            return phase2_result, repair_summary

        workflow = self.workflow
        repair_result = await workflow._extract_entities_by_scene(
            db,
            novel_id,
            workflow_id=workflow_id,
            on_scene_progress=on_scene_progress,
            existing_checkpoints=progress.checkpoints,
            start_chapter=start_chapter,
            end_chapter=end_chapter,
        )
        workflow._merge_checkpoints(progress, repair_result)
        merged = _merge_phase2_repair_result(phase2_result, repair_result)
        repair_summary = phase2_repair_summary(
            repair_result,
            attempted=True,
            reason="checkpoint_failed_units",
        )
        repair_summary["source_failed_scene_indices"] = phase2_result.get(
            "failed_scene_indices",
            [],
        )
        repair_summary["source_failed_batches"] = phase2_result.get(
            "phase2_failed_batches",
            [],
        )
        return merged, repair_summary


def phase2_quality_stats(phase2_result: dict[str, Any]) -> dict[str, Any]:
    failed_scenes = phase2_result.get("failed_scene_indices") or []
    checkpoints = (phase2_result.get("checkpoints") or {}).get("phase2", {}).get(
        "scenes",
        [],
    )
    status_counts: dict[str, int] = {}
    if isinstance(checkpoints, list):
        for checkpoint in checkpoints:
            if not isinstance(checkpoint, dict):
                continue
            status = str(checkpoint.get("status") or "unknown")
            status_counts[status] = status_counts.get(status, 0) + 1
    return {
        "total_created": int(phase2_result.get("total_created", 0) or 0),
        "total_relations": int(phase2_result.get("total_relations", 0) or 0),
        "total_aliases": int(phase2_result.get("total_aliases", 0) or 0),
        "total_deltas": int(phase2_result.get("total_deltas", 0) or 0),
        "total_scenes": int(phase2_result.get("total_scenes", 0) or 0),
        "completed_scenes": int(phase2_result.get("completed_scenes", 0) or 0),
        "alias_relation_scenes": int(
            phase2_result.get("alias_relation_scenes", 0) or 0
        ),
        "alias_relation_failed_scenes": phase2_result.get(
            "alias_relation_failed_scenes",
            [],
        ),
        "alias_relation_elapsed_s": phase2_result.get("alias_relation_elapsed_s"),
        "alias_relation_total_timeout_s": phase2_result.get(
            "alias_relation_total_timeout_s"
        ),
        "alias_relation_concurrency": phase2_result.get("alias_relation_concurrency"),
        "skipped_scenes": int(phase2_result.get("skipped_scenes", 0) or 0),
        "rerun_scenes": int(phase2_result.get("rerun_scenes", 0) or 0),
        "failed_scene_count": len(failed_scenes)
        if isinstance(failed_scenes, list)
        else 0,
        "supplemental_llm_created": int(
            phase2_result.get("supplemental_llm_created", 0) or 0
        ),
        "fallback_created": int(phase2_result.get("fallback_created", 0) or 0),
        "supplemental_error_kind": phase2_result.get("supplemental_error_kind"),
        "parallel_llm_fallback": bool(phase2_result.get("parallel_llm_fallback")),
        "bulk_error_kind": phase2_result.get("bulk_error_kind"),
        "phase2_batches_total": int(
            phase2_result.get("phase2_batches_total", 0) or 0
        ),
        "phase2_batches_completed": int(
            phase2_result.get("phase2_batches_completed", 0) or 0
        ),
        "phase2_batch_size_scenes": int(
            phase2_result.get("phase2_batch_size_scenes", 0) or 0
        ),
        "phase2_batch_concurrency": int(
            phase2_result.get("phase2_batch_concurrency", 0) or 0
        ),
        "phase2_boundary_windows_total": int(
            phase2_result.get("phase2_boundary_windows_total", 0) or 0
        ),
        "phase2_boundary_windows_completed": int(
            phase2_result.get("phase2_boundary_windows_completed", 0) or 0
        ),
        "phase2_action_counts": phase2_result.get("phase2_action_counts") or {},
        "phase2_dedup_counts": phase2_result.get("phase2_dedup_counts") or {},
        "phase2_boundary_supplement_counts": (
            phase2_result.get("phase2_boundary_supplement_counts") or {}
        ),
        "phase2_failed_batches": phase2_result.get("phase2_failed_batches") or [],
        "phase2_degraded_batches": phase2_result.get("phase2_degraded_batches") or [],
        "phase2_linked_to_existing": int(
            phase2_result.get("phase2_linked_to_existing", 0) or 0
        ),
        "phase2_ignored": int(phase2_result.get("phase2_ignored", 0) or 0),
        "phase2_temporary_only": int(
            phase2_result.get("phase2_temporary_only", 0) or 0
        ),
        "phase2_low_confidence": int(
            phase2_result.get("phase2_low_confidence", 0) or 0
        ),
        "degraded": bool(phase2_result.get("degraded")),
        "error_kind": phase2_result.get("error_kind"),
        "checkpoint_status_counts": status_counts,
    }


def _phase2_counts(phase2_result: dict[str, Any]) -> dict[str, Any]:
    return {
        "total_scenes": int(phase2_result.get("total_scenes", 0) or 0),
        "completed_scenes": int(phase2_result.get("completed_scenes", 0) or 0),
        "total_created": int(phase2_result.get("total_created", 0) or 0),
        "total_aliases": int(phase2_result.get("total_aliases", 0) or 0),
        "total_relations": int(phase2_result.get("total_relations", 0) or 0),
        "total_deltas": int(phase2_result.get("total_deltas", 0) or 0),
        "failed_scene_count": len(phase2_result.get("failed_scene_indices") or []),
        "failed_batch_count": len(phase2_result.get("phase2_failed_batches") or []),
        "alias_relation_failed_scene_count": len(
            phase2_result.get("alias_relation_failed_scenes") or []
        ),
        "alias_relation_fallback_scene_count": len(
            phase2_result.get("alias_relation_fallback_scenes") or []
        ),
    }


def _has_phase2a_failures(phase2_result: dict[str, Any]) -> bool:
    return bool(
        phase2_result.get("failed_scene_indices")
        or phase2_result.get("phase2_failed_batches")
    )


def _merge_phase2_repair_result(
    source: dict[str, Any],
    repair: dict[str, Any],
) -> dict[str, Any]:
    merged = {**source, **repair}
    for key in (
        "total_created",
        "total_aliases",
        "total_relations",
        "total_deltas",
        "supplemental_llm_created",
        "fallback_created",
    ):
        merged[key] = int(source.get(key, 0) or 0) + int(repair.get(key, 0) or 0)
    merged["completed_scenes"] = max(
        int(source.get("completed_scenes", 0) or 0),
        int(repair.get("completed_scenes", 0) or 0),
    )
    merged["failed_scene_indices"] = repair.get("failed_scene_indices") or []
    merged["phase2_failed_batches"] = repair.get("phase2_failed_batches") or []
    merged["degraded"] = bool(
        repair.get("degraded")
        or repair.get("alias_relation_failed_scenes")
        or repair.get("alias_relation_fallback_scenes")
    )
    if not merged["failed_scene_indices"] and not merged["phase2_failed_batches"]:
        merged["error_kind"] = repair.get("error_kind")
        merged["error_message"] = repair.get("error_message")
    return merged
