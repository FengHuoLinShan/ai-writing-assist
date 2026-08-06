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
from modules.imports.workflow_phase_runner import SceneFullPipelineRequest
from modules.imports.workflow_runtime import DeepImportWorkflowRuntime
from modules.imports.workflow_schemas import DeepImportProgress, DeepImportStep

PHASE0_422_RECOMMENDATION = (
    "推荐使用官方api以保障稳定性与质量；强推 DeepSeek-v4-flash，质量高价格低并发超快。"
)
PHASE1A_SINGLE_CHAPTER_FALLBACK_MAX_MISSING = 12


def _accepts_keyword(callable_obj: Any, keyword: str) -> bool:
    try:
        signature = inspect.signature(callable_obj)
    except (TypeError, ValueError):
        return True
    return keyword in signature.parameters or any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    )


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
        novel_id=novel_id,
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
        return await self.run_full_pipeline(
            SceneFullPipelineRequest(
                db=db,
                novel_id=novel_id,
                start_chapter=start_chapter,
                end_chapter=end_chapter,
                progress=progress,
                workflow_id=workflow_id,
                on_progress=on_progress,
                stop_after=stop_after,
            )
        )

    async def run_full_pipeline(
        self,
        request: SceneFullPipelineRequest,
    ) -> ScenePhaseOutcome:
        db = request.db
        novel_id = request.novel_id
        start_chapter = request.start_chapter
        end_chapter = request.end_chapter
        progress = request.progress
        workflow_id = request.workflow_id
        on_progress = request.on_progress
        stop_after = request.stop_after
        replace_existing = request.replace_existing
        workflow = self.workflow

        def _assert_provider_window(phase: str) -> None:
            if request.require_provider_no_transaction and db.in_transaction():
                raise RuntimeError(
                    f"scene_auto_extraction {phase} cannot run inside a transaction"
                )

        # Phase 0: deterministic Scene import plan.
        progress.current_step = DeepImportStep.scene_segmentation
        progress.current_phase = "phase0_plan"
        progress.current_operation = "scene_plan"
        progress.current_chapter_range = f"{start_chapter}-{end_chapter}"
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

        phase0_result = request.prepared_phase0_result
        if phase0_result is None:
            phase0_result = await workflow._run_phase0_plan(
                db,
                novel_id,
                start_chapter,
                end_chapter,
            )
        progress.quality_stats["phase0"] = phase0_result.quality_stats
        if phase0_diagnostics := workflow._diagnostic_samples(phase0_result.diagnostics):
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
                    "error_kind": phase0_result.block_reason or "phase0_plan_failed",
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
            await workflow._emit_progress(progress, 0.0, on_progress)
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
        progress.current_chapter_range = f"{start_chapter}-{end_chapter}"
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

        async def _on_phase1a_batch(completed: int, total: int, window_id: str) -> None:
            progress.current_window = window_id
            progress.current_item = {
                "kind": "window",
                "completed": completed,
                "total": total,
            }
            value = min(0.2, 0.1 + 0.1 * (completed / total)) if total else 0.1
            await workflow._emit_progress(progress, value, on_progress)
            _assert_provider_window("phase1a progress")

        _assert_provider_window("phase1a")
        phase1a_result = await workflow._run_phase1a_scene_slicing(
            db,
            novel_id,
            start_chapter,
            end_chapter,
            phase0_result,
            on_batch_progress=_on_phase1a_batch,
        )
        _assert_provider_window("phase1a")
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
            progress.message = "Phase 1a Scene 切分缺少章节覆盖，已停止深度导入。"
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
            await workflow._emit_progress(progress, 0.2, on_progress)
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
        progress.current_chapter_range = f"{start_chapter}-{end_chapter}"
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

        async def _on_phase1b_batch(
            completed: int, total: int, candidate_id: str
        ) -> None:
            progress.current_scene_candidate_id = candidate_id
            progress.current_item = {
                "kind": "scene_candidate",
                "completed": completed,
                "total": total,
            }
            value = min(0.3, 0.2 + 0.1 * (completed / total)) if total else 0.2
            await workflow._emit_progress(progress, value, on_progress)
            _assert_provider_window("phase1b progress")

        _assert_provider_window("phase1b")
        phase1b_kwargs: dict[str, Any] = {
            "start_chapter": start_chapter,
            "end_chapter": end_chapter,
            "chapters": phase0_result.chapters,
            "on_batch_progress": _on_phase1b_batch,
        }
        if _accepts_keyword(
            workflow._run_phase1b_enrichment,
            "phase1a_context",
        ):
            phase1b_kwargs["phase1a_context"] = phase0_result.phase1a_context
        phase1b_result = await workflow._run_phase1b_enrichment(
            db,
            novel_id,
            phase1a_result.candidates,
            **phase1b_kwargs,
        )
        _assert_provider_window("phase1b")
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
            await workflow._emit_progress(progress, 0.3, on_progress)
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

        final_candidates = phase1b_result.candidates
        fusion_suggestions = []
        high_quality = bool(getattr(workflow, "_deep_import_high_quality", False))
        if high_quality:
            progress.current_phase = "phase1c_scene_fusion"
            progress.current_operation = "scene_fusion"
            progress.message = "正在审核相邻 Scene 边界并静默融合..."
            workflow._start_phase(
                progress,
                "phase1c_scene_fusion",
                item={"kind": "scene_pairs", "count": max(len(final_candidates) - 1, 0)},
            )
            await workflow._emit_progress(progress, 0.30, on_progress)

            async def _on_phase1c_pair(
                completed: int,
                total: int,
                pair_id: str,
            ) -> None:
                progress.current_item = {
                    "kind": "scene_pair",
                    "completed": completed,
                    "total": total,
                    "pair_id": pair_id,
                }
                fraction = completed / total if total else 1.0
                await workflow._emit_progress(
                    progress,
                    0.30 + 0.05 * fraction,
                    on_progress,
                )
                _assert_provider_window("phase1c progress")

            _assert_provider_window("phase1c")
            phase1c_kwargs: dict[str, Any] = {
                "chapters": phase0_result.chapters,
                "project_profile": request.project_profile,
                "on_pair_progress": _on_phase1c_pair,
            }
            if _accepts_keyword(
                workflow._run_phase1c_scene_fusion,
                "phase1a_context",
            ):
                phase1c_kwargs["phase1a_context"] = phase0_result.phase1a_context
            phase1c_result = await workflow._run_phase1c_scene_fusion(
                db,
                novel_id,
                final_candidates,
                **phase1c_kwargs,
            )
            _assert_provider_window("phase1c")
            final_candidates = phase1c_result.candidates
            fusion_suggestions = phase1c_result.suggestions
            progress.quality_stats["phase1c"] = phase1c_result.quality_stats
            add_phase_artifact(
                progress,
                "phase1c_scene_fusion",
                start_chapter=start_chapter,
                end_chapter=end_chapter,
                status="degraded" if phase1c_result.degraded else "completed",
                quality_status="partial" if phase1c_result.degraded else "complete",
                quality_stats=phase1c_result.quality_stats,
                counts={
                    "candidate_count": len(final_candidates),
                    "suggestion_count": len(fusion_suggestions),
                },
                coverage=candidate_chapter_coverage(
                    final_candidates,
                    start_chapter,
                    end_chapter,
                ),
            )
            workflow._finish_phase(
                progress,
                "phase1c_scene_fusion",
                status="degraded" if phase1c_result.degraded else "completed",
                details=phase1c_result.quality_stats,
                error_kind=phase1c_result.block_reason,
            )
            if phase1c_result.degraded:
                progress.degraded = True
                progress.degraded_reason = (
                    phase1c_result.block_reason or "phase1c_review_or_synthesis_failures"
                )
                progress.phase_errors.append(
                    {
                        "phase": "phase1c_scene_fusion",
                        "error_kind": progress.degraded_reason,
                        "message": (
                            "部分相邻 Scene 边界复核或融合综合未完成；"
                            "已保留原 Scene，未生成技术失败对应的待处理建议。"
                        ),
                    }
                )
        else:
            progress.quality_stats["phase1c"] = {
                "status": "skipped",
                "reason": "high_quality_required",
            }
            add_phase_artifact(
                progress,
                "phase1c_scene_fusion",
                start_chapter=start_chapter,
                end_chapter=end_chapter,
                status="skipped",
                quality_status="complete",
                quality_stats=progress.quality_stats["phase1c"],
                counts={"candidate_count": len(final_candidates), "suggestion_count": 0},
                coverage=phase1b_coverage,
            )

        final_coverage = candidate_chapter_coverage(
            final_candidates,
            start_chapter,
            end_chapter,
        )

        # Scene commit: only this step writes formal Scene rows.
        progress.current_phase = "scene_commit"
        progress.current_operation = "scene_commit"
        progress.current_chapter_range = f"{start_chapter}-{end_chapter}"
        progress.message = "正在提交正式 Scene 与融合建议..."
        workflow._start_phase(
            progress,
            "scene_commit",
            item={
                "kind": "scene_candidates",
                "count": len(final_candidates),
            },
        )
        workflow._update_phase1_batch_counts(
            progress,
            phase0_result,
            phase1a_result,
            phase1b_result,
            commit_started=True,
        )
        await workflow._emit_progress(progress, 0.35, on_progress)

        commit_kwargs: dict[str, Any] = {
            "workflow_id": workflow_id or progress.workflow_id or "manual",
            "start_chapter": start_chapter,
            "end_chapter": end_chapter,
        }
        if replace_existing:
            commit_kwargs["replace_existing"] = True
        if fusion_suggestions:
            commit_kwargs["fusion_suggestions"] = fusion_suggestions
        if request.before_scene_commit is not None:
            await request.before_scene_commit()
        commit_result = await workflow._commit_fused_scenes(
            db,
            novel_id,
            final_candidates,
            **commit_kwargs,
        )
        workflow._update_phase1_batch_counts(
            progress,
            phase0_result,
            phase1a_result,
            phase1b_result,
            commit_completed=True,
        )
        progress.quality_stats["scene_commit"] = commit_result.model_dump(mode="json")
        total_scenes = (
            commit_result.effective_scene_count
            if replace_existing
            else commit_result.created_count + commit_result.skipped_count
        )
        scene_commit_coverage = (
            commit_result.effective_coverage
            if replace_existing and commit_result.effective_coverage
            else final_coverage
        )
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
                "replacement_suggestion_count": (
                    commit_result.replacement_suggestion_count
                ),
                "total_scenes": total_scenes,
            },
            coverage=scene_commit_coverage,
        )
        if total_scenes > 0 and scene_commit_coverage["coverage_complete"]:
            rag_task_id = None
            if not replace_existing or commit_result.active_scene_changed:
                rag_task_id = _enqueue_rag_reindex_after_scene_commit(
                    db,
                    novel_id,
                    start_chapter,
                    end_chapter,
                )
            if rag_task_id is not None:
                progress.quality_stats["scene_commit"]["rag_reindex_task_id"] = (
                    rag_task_id
                )
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
                "empty_scene_commit" if total_scenes <= 0 else "missing_chapter_coverage"
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
            await workflow._emit_progress(progress, 0.3, on_progress)
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
                "从正文提取 Scene 完成，"
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
        "repair_attempts": int(repair.quality_stats.get("repair_attempts", 0) or 0) + 1,
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
