"""Scene phases for the deep import workflow director."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from importlib import import_module
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.tasks.enqueuer import enqueue_task
from modules.imports.service_phase_artifacts import (
    add_phase_artifact,
    candidate_chapter_coverage,
    coverage_summary,
    phase_error,
    scene_phase_repair_summary,
)
from modules.imports.workflow_runtime import DeepImportWorkflowRuntime
from modules.imports.workflow_schemas import DeepImportProgress, DeepImportStep

PHASE0_422_RECOMMENDATION = (
    "推荐使用官方api以保障稳定性与质量；"
    "强推 DeepSeek-v4-flash，质量高价格低并发超快。"
)
PHASE1A_SINGLE_CHAPTER_FALLBACK_MAX_MISSING = 12


def _enqueue_rag_reindex_after_scene_commit(
    db: AsyncSession | None,
    novel_id: str,
    start_chapter: int,
    end_chapter: int,
) -> str | None:
    if db is None or inspect.iscoroutinefunction(getattr(db, "add", None)):
        return None
    return enqueue_task(
        db,
        "rag_reindex_novel",
        meta={
            "novel_id": novel_id,
            "start_chapter": start_chapter,
            "end_chapter": end_chapter,
            "source": "deep_import_scene_commit",
        },
    )


def _phase0_422_recommendation() -> str:
    workflow_module = import_module("modules.imports.workflow")
    return str(
        getattr(
            workflow_module,
            "PHASE0_422_RECOMMENDATION",
            PHASE0_422_RECOMMENDATION,
        )
    )


@dataclass(frozen=True)
class ScenePhaseOutcome:
    total_scenes: int
    stopped: bool = False


class ScenePhaseRunner:
    """Runs Phase 0/1a/1b and formal Scene commit."""

    def __init__(self, workflow: DeepImportWorkflowRuntime) -> None:
        self.workflow = workflow

    async def run(
        self,
        db: AsyncSession,
        novel_id: str,
        start_chapter: int,
        end_chapter: int,
        progress: DeepImportProgress,
        *,
        workflow_id: str | None,
        on_progress: Callable[[DeepImportProgress, float], Awaitable[None]] | None,
        stop_after: DeepImportStep | None,
    ) -> ScenePhaseOutcome:
        workflow = self.workflow

        # Phase 0: deterministic Scene import plan.
        progress.current_step = DeepImportStep.scene_segmentation
        progress.current_phase = "phase0_plan"
        progress.current_operation = "scene_plan"
        progress.message = "正在统计章节字数并规划 Scene 切分窗口..."
        workflow._start_phase(
            progress,
            "phase0_plan",
            item={
                "kind": "chapter_range",
                "start_chapter": start_chapter,
                "end_chapter": end_chapter,
            },
        )
        await workflow._emit_progress(progress, 0.0, on_progress)

        phase0_result = await workflow._run_phase0_plan(
            db,
            novel_id,
            start_chapter,
            end_chapter,
        )
        progress.quality_stats["phase0"] = phase0_result.quality_stats
        if phase0_diagnostics := workflow._diagnostic_samples(
            phase0_result.diagnostics
        ):
            progress.quality_stats["phase0_diagnostics"] = phase0_diagnostics
        phase0_coverage = coverage_summary(
            {
                int(chapter["chapter_index"])
                for chapter in phase0_result.chapters
                if chapter.get("chapter_index") is not None
            },
            start_chapter,
            end_chapter,
        )
        progress.phase1_total_batches = int(
            phase0_result.quality_stats.get("total_batches", 0)
        )
        progress.phase1_completed_batches = int(
            phase0_result.quality_stats.get("completed_batches", 0)
        )
        add_phase_artifact(
            progress,
            "phase0_plan",
            start_chapter=start_chapter,
            end_chapter=end_chapter,
            status="blocked" if phase0_result.blocked else "completed",
            quality_status="failed" if phase0_result.blocked else "complete",
            quality_stats=phase0_result.quality_stats,
            counts={
                "window_count": len(phase0_result.windows),
                "chapter_count": len(phase0_result.chapters),
            },
            coverage=phase0_coverage,
            repair_summary={"policy": {}, "attempted": False, "attempts": 0},
        )
        if phase0_result.blocked:
            progress.phase = "failed"
            progress.quality_status = "failed"
            progress.current_step = None
            progress.degraded = True
            progress.degraded_reason = phase0_result.block_reason
            progress.message = (
                "Phase 0 Scene 窗口规划失败，已停止深度导入。"
                f"{phase0_result.block_reason or ''}"
            )
            progress.phase_errors.append(
                {
                    "phase": "phase0_plan",
                    "error_kind": phase0_result.block_reason
                    or "phase0_plan_failed",
                    "message": progress.message[:300],
                }
            )
            workflow._finish_phase(
                progress,
                "phase0_plan",
                status="failed",
                error_kind=progress.degraded_reason,
                error_message=progress.message,
            )
            await workflow._emit_progress(progress, 1.0, on_progress)
            return ScenePhaseOutcome(total_scenes=0, stopped=True)
        workflow._finish_phase(
            progress,
            "phase0_plan",
            status="completed",
            details=phase0_result.quality_stats,
        )

        # Phase 1a: text-backed Scene slicing.
        progress.current_step = DeepImportStep.scene_segmentation
        progress.current_phase = "phase1a_scene_slicing"
        progress.current_operation = "scene_slicing"
        progress.message = "正在按完整窗口切分 Scene 边界..."
        workflow._start_phase(
            progress,
            "phase1a_scene_slicing",
            item={
                "kind": "chapter_range",
                "start_chapter": start_chapter,
                "end_chapter": end_chapter,
            },
            details={
                "phase0_window_count": len(phase0_result.windows),
            },
        )
        await workflow._emit_progress(progress, 0.1, on_progress)

        phase1a_result = await workflow._run_phase1a_scene_slicing(
            db,
            novel_id,
            start_chapter,
            end_chapter,
            phase0_result,
        )
        progress.quality_stats["phase1a"] = phase1a_result.quality_stats
        if phase1a_diagnostics := workflow._diagnostic_samples(
            phase1a_result.diagnostics
        ):
            progress.quality_stats["phase1a_diagnostics"] = phase1a_diagnostics
        phase1a_coverage = candidate_chapter_coverage(
            phase1a_result.candidates,
            start_chapter,
            end_chapter,
        )
        workflow._update_phase1_batch_counts(
            progress,
            phase0_result,
            phase1a_result,
        )
        phase1a_complete = bool(phase1a_coverage["coverage_complete"])
        if phase1a_result.blocked or not phase1a_complete:
            progress.phase = "failed"
            progress.quality_status = "failed"
            progress.current_step = None
            progress.degraded = True
            progress.degraded_reason = (
                phase1a_result.block_reason or "missing_chapter_coverage"
            )
            progress.message = (
                "Phase 1a Scene 切分缺少章节覆盖，已停止深度导入。"
            )
            progress.phase_errors.append(
                {
                    "phase": "phase1a_scene_slicing",
                    "error_kind": progress.degraded_reason,
                    "message": progress.message[:300],
                }
            )
            add_phase_artifact(
                progress,
                "phase1a_scene_slicing",
                start_chapter=start_chapter,
                end_chapter=end_chapter,
                status="blocked",
                quality_status="failed",
                quality_stats=phase1a_result.quality_stats,
                counts={"candidate_count": len(phase1a_result.candidates)},
                coverage=phase1a_coverage,
                repair_summary=scene_phase_repair_summary(
                    phase1a_result.quality_stats,
                    phase="phase1a_scene_slicing",
                ),
                errors=[
                    error
                    for error in progress.phase_errors
                    if error.get("phase") == "phase1a_scene_slicing"
                ],
            )
            workflow._finish_phase(
                progress,
                "phase1a_scene_slicing",
                status="failed",
                details=phase1a_result.quality_stats,
                error_kind=progress.degraded_reason,
                error_message=progress.message,
            )
            await workflow._emit_progress(progress, 1.0, on_progress)
            return ScenePhaseOutcome(total_scenes=0, stopped=True)

        add_phase_artifact(
            progress,
            "phase1a_scene_slicing",
            start_chapter=start_chapter,
            end_chapter=end_chapter,
            status="completed",
            quality_status=(
                "complete" if phase1a_coverage["coverage_complete"] else "partial"
            ),
            quality_stats=phase1a_result.quality_stats,
            counts={"candidate_count": len(phase1a_result.candidates)},
            coverage=phase1a_coverage,
            repair_summary=scene_phase_repair_summary(
                phase1a_result.quality_stats,
                phase="phase1a_scene_slicing",
                repaired=bool(
                    int(phase1a_result.quality_stats.get("fallback_count", 0) or 0)
                ),
                reason="chapter_fallback"
                if int(phase1a_result.quality_stats.get("fallback_count", 0) or 0)
                else None,
            ),
        )
        workflow._finish_phase(
            progress,
            "phase1a_scene_slicing",
            status="completed",
            details={
                **phase1a_result.quality_stats,
                "candidate_count": len(phase1a_result.candidates),
                "missing_chapters": phase1a_coverage["missing_chapters"],
            },
        )

        # Phase 1b: per-Scene enrichment.
        progress.current_phase = "phase1b_enrichment"
        progress.current_operation = "scene_enrichment"
        progress.message = "正在逐 Scene 补充叙事字段..."
        workflow._start_phase(
            progress,
            "phase1b_enrichment",
            item={
                "kind": "chapter_range",
                "start_chapter": start_chapter,
                "end_chapter": end_chapter,
            },
            details={
                "input_candidate_count": len(phase1a_result.candidates),
            },
        )
        await workflow._emit_progress(progress, 0.2, on_progress)

        phase1b_result = await workflow._run_phase1b_enrichment(
            db,
            novel_id,
            phase1a_result.candidates,
            start_chapter=start_chapter,
            end_chapter=end_chapter,
            chapters=phase0_result.chapters,
        )
        progress.quality_stats["phase1b"] = phase1b_result.quality_stats
        if phase1b_diagnostics := workflow._diagnostic_samples(
            phase1b_result.diagnostics
        ):
            progress.quality_stats["phase1b_diagnostics"] = phase1b_diagnostics
        phase1b_coverage = candidate_chapter_coverage(
            phase1b_result.candidates,
            start_chapter,
            end_chapter,
        )
        progress.phase1a_fallback = bool(
            int(phase1a_result.quality_stats.get("fallback_count", 0) or 0)
        )
        workflow._update_phase1_batch_counts(
            progress,
            phase0_result,
            phase1a_result,
            phase1b_result,
        )
        if not phase1b_coverage["coverage_complete"]:
            progress.degraded = True
            progress.degraded_reason = "missing_chapter_coverage"
            progress.phase_errors.append(
                phase_error(
                    phase="phase1b_enrichment",
                    error_kind="missing_chapter_coverage",
                    message=(
                        "Phase 1b Scene enrichment 缺少章节覆盖："
                        f"{phase1b_coverage['missing_chapters']}"
                    ),
                )
            )

        if phase1b_result.degraded:
            progress.degraded = True
            progress.degraded_reason = (
                phase1b_result.block_reason or "phase1b_enrichment_fallback"
            )
            progress.phase_errors.append(
                {
                    "phase": "phase1b_enrichment",
                    "error_kind": progress.degraded_reason,
                    "message": (
                        "Phase 1b Scene enrichment 部分降级，已对失败 Scene "
                        "使用 fallback 字段继续提交。"
                    ),
                }
            )
        add_phase_artifact(
            progress,
            "phase1b_enrichment",
            start_chapter=start_chapter,
            end_chapter=end_chapter,
            status="degraded"
            if phase1b_result.degraded or not phase1b_coverage["coverage_complete"]
            else "completed",
            quality_status=(
                "complete" if phase1b_coverage["coverage_complete"] else "failed"
            ),
            quality_stats=phase1b_result.quality_stats,
            counts={"candidate_count": len(phase1b_result.candidates)},
            coverage=phase1b_coverage,
            errors=[
                error
                for error in progress.phase_errors
                if error.get("phase") == "phase1b_enrichment"
            ],
        )
        if not phase1b_coverage["coverage_complete"]:
            progress.phase = "failed"
            progress.quality_status = "failed"
            progress.current_step = None
            progress.message = (
                "Phase 1b Scene enrichment 缺少章节覆盖，已停止正式 Scene 提交。"
            )
            workflow._finish_phase(
                progress,
                "phase1b_enrichment",
                status="failed",
                details={
                    **phase1b_result.quality_stats,
                    "output_candidate_count": len(phase1b_result.candidates),
                    "missing_chapters": phase1b_coverage["missing_chapters"],
                },
                error_kind="missing_chapter_coverage",
                error_message=progress.message,
            )
            await workflow._emit_progress(progress, 1.0, on_progress)
            return ScenePhaseOutcome(total_scenes=0, stopped=True)
        workflow._finish_phase(
            progress,
            "phase1b_enrichment",
            status="degraded" if phase1b_result.degraded else "completed",
            details={
                **phase1b_result.quality_stats,
                "output_candidate_count": len(phase1b_result.candidates),
            },
            error_kind=progress.degraded_reason if phase1b_result.degraded else None,
            error_message=progress.message if phase1b_result.degraded else None,
        )

        # Scene commit: only this step writes formal Scene rows.
        progress.current_phase = "scene_commit"
        progress.current_operation = "scene_commit"
        progress.message = "正在提交 enriched 正式 Scene..."
        workflow._start_phase(
            progress,
            "scene_commit",
            item={
                "kind": "scene_candidates",
                "count": len(phase1b_result.candidates),
            },
        )
        workflow._update_phase1_batch_counts(
            progress,
            phase0_result,
            phase1a_result,
            phase1b_result,
            commit_started=True,
        )
        await workflow._emit_progress(progress, 0.3, on_progress)

        commit_result = await workflow._commit_fused_scenes(
            db,
            novel_id,
            phase1b_result.candidates,
            workflow_id=workflow_id or progress.workflow_id or "manual",
        )
        workflow._update_phase1_batch_counts(
            progress,
            phase0_result,
            phase1a_result,
            phase1b_result,
            commit_completed=True,
        )
        progress.quality_stats["scene_commit"] = commit_result.model_dump(mode="json")
        total_scenes = commit_result.created_count + commit_result.skipped_count
        scene_commit_coverage = phase1b_coverage
        add_phase_artifact(
            progress,
            "scene_commit",
            start_chapter=start_chapter,
            end_chapter=end_chapter,
            status="completed"
            if total_scenes > 0 and scene_commit_coverage["coverage_complete"]
            else "failed",
            quality_status="complete"
            if total_scenes > 0 and scene_commit_coverage["coverage_complete"]
            else "failed",
            quality_stats=progress.quality_stats["scene_commit"],
            counts={
                "created_count": commit_result.created_count,
                "skipped_count": commit_result.skipped_count,
                "conflict_count": commit_result.conflict_count,
                "total_scenes": total_scenes,
            },
            coverage=scene_commit_coverage,
        )
        if total_scenes > 0 and scene_commit_coverage["coverage_complete"]:
            rag_task_id = _enqueue_rag_reindex_after_scene_commit(
                db,
                novel_id,
                start_chapter,
                end_chapter,
            )
            if rag_task_id is not None:
                progress.quality_stats["scene_commit"][
                    "rag_reindex_task_id"
                ] = rag_task_id
            workflow._mark_step_completed(progress, DeepImportStep.scene_segmentation)
            workflow._finish_phase(
                progress,
                "scene_commit",
                status="completed",
                details=progress.quality_stats["scene_commit"],
            )
        else:
            progress.degraded = True
            progress.phase = "failed"
            progress.quality_status = "failed"
            progress.current_step = None
            progress.degraded_reason = (
                "empty_scene_commit"
                if total_scenes <= 0
                else "missing_chapter_coverage"
            )
            error_message = (
                "Scene 提交阶段未创建或复用任何 Scene"
                if total_scenes <= 0
                else "Scene 提交阶段缺少章节覆盖："
                f"{scene_commit_coverage['missing_chapters']}"
            )
            progress.phase_errors.append(
                {
                    "phase": DeepImportStep.scene_segmentation.value,
                    "error_kind": progress.degraded_reason,
                    "message": error_message,
                }
            )
            progress.message = f"{error_message}，已停止深度导入。"
            workflow._finish_phase(
                progress,
                "scene_commit",
                status="failed",
                details=progress.quality_stats["scene_commit"],
                error_kind=progress.degraded_reason,
                error_message=progress.message,
            )
            await workflow._emit_progress(progress, 1.0, on_progress)
            return ScenePhaseOutcome(total_scenes=0, stopped=True)
        progress.message = (
            "Scene 提交完成，"
            f"新增 {commit_result.created_count} 个，"
            f"复用 {commit_result.skipped_count} 个。"
        )
        if commit_result.conflict_count:
            progress.degraded = True
            progress.phase_errors.append(
                {
                    "phase": "scene_commit",
                    "error_kind": "provenance_conflict",
                    "message": (
                        f"{commit_result.conflict_count} 个 Scene provenance "
                        "存在 deprecated 冲突，已跳过。"
                    ),
                }
            )
        if stop_after == DeepImportStep.scene_segmentation:
            progress.current_step = None
            progress.phase = "done"
            progress.quality_status = "partial" if progress.degraded else "complete"
            progress.message = (
                "场景（scene）自动提取完成，"
                f"新增 {commit_result.created_count} 个，"
                f"复用 {commit_result.skipped_count} 个。"
            )
            await workflow._emit_progress(progress, 1.0, on_progress)
            return ScenePhaseOutcome(total_scenes=total_scenes, stopped=True)

        return ScenePhaseOutcome(total_scenes=total_scenes)


def _merge_phase0_repair_result(source: Any, repair: Any) -> Any:
    from modules.imports.scene_candidates import ScenePrefetchResult

    candidates_by_id = {
        getattr(candidate, "candidate_id", str(index)): candidate
        for index, candidate in enumerate(source.candidates)
    }
    for index, candidate in enumerate(repair.candidates, start=len(candidates_by_id)):
        candidates_by_id[getattr(candidate, "candidate_id", str(index))] = candidate

    quality_stats = {
        **repair.quality_stats,
        "repair_attempts": int(repair.quality_stats.get("repair_attempts", 0) or 0)
        + 1,
        "source_total_batches": int(source.quality_stats.get("total_batches", 0) or 0),
        "source_failed": int(source.quality_stats.get("failed", 0) or 0),
        "source_timeout": int(source.quality_stats.get("timeout", 0) or 0),
        "source_schema_error": int(source.quality_stats.get("schema_error", 0) or 0),
        "source_empty_result": int(source.quality_stats.get("empty_result", 0) or 0),
    }

    return ScenePrefetchResult(
        candidates=list(candidates_by_id.values()),
        quality_stats=quality_stats,
        diagnostics=[*source.diagnostics, *repair.diagnostics],
        blocked=repair.blocked,
        block_reason=repair.block_reason,
    )
