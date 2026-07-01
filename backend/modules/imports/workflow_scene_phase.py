"""Scene phases for the deep import workflow director."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from importlib import import_module
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.imports.workflow_schemas import DeepImportProgress, DeepImportStep

PHASE0_422_RECOMMENDATION = (
    "推荐使用官方api以保障稳定性与质量；"
    "强推 DeepSeek-v4-flash，质量高价格低并发超快。"
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

    def __init__(self, workflow: Any) -> None:
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

        # Phase 0: Scene candidate prefetch quality gate.
        progress.current_step = DeepImportStep.scene_segmentation
        progress.current_phase = "phase0_prefetch"
        progress.current_operation = "scene_prefetch"
        progress.message = "正在预取 Scene 候选并统计质量..."
        workflow._start_phase(
            progress,
            "phase0_prefetch",
            item={
                "kind": "chapter_range",
                "start_chapter": start_chapter,
                "end_chapter": end_chapter,
            },
        )
        await workflow._emit_progress(progress, 0.0, on_progress)

        phase0_result = await workflow._run_phase0_prefetch(
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
        progress.phase1_total_batches = int(
            phase0_result.quality_stats.get("total_batches", 0)
        )
        progress.phase1_completed_batches = int(
            phase0_result.quality_stats.get("completed_batches", 0)
        )
        workflow._finish_phase(
            progress,
            "phase0_prefetch",
            status="completed",
            details=phase0_result.quality_stats,
        )

        if phase0_result.blocked:
            progress.phase = "failed"
            progress.quality_status = "failed"
            progress.current_step = None
            progress.degraded = True
            progress.degraded_reason = phase0_result.block_reason
            progress.message = (
                "Phase 0 Scene 预取 422 错误率过高，已停止深度导入。"
                f"{_phase0_422_recommendation()}"
            )
            progress.phase_errors.append(
                {
                    "phase": "phase0_prefetch",
                    "error_kind": phase0_result.block_reason
                    or "phase0_422_rate_exceeded",
                    "message": progress.message[:300],
                }
            )
            workflow._finish_phase(
                progress,
                "phase0_prefetch",
                status="failed",
                error_kind=progress.degraded_reason,
                error_message=progress.message,
            )
            await workflow._emit_progress(progress, 1.0, on_progress)
            return ScenePhaseOutcome(total_scenes=0, stopped=True)

        # Phase 1a: text-backed candidate reinforcement.
        progress.current_step = DeepImportStep.scene_segmentation
        progress.current_phase = "phase1a_reinforce"
        progress.current_operation = "scene_reinforcement"
        progress.message = "正在结合正文强化 Scene 候选..."
        workflow._start_phase(
            progress,
            "phase1a_reinforce",
            item={
                "kind": "chapter_range",
                "start_chapter": start_chapter,
                "end_chapter": end_chapter,
            },
            details={
                "phase0_candidate_count": len(phase0_result.candidates),
            },
        )
        await workflow._emit_progress(progress, 0.1, on_progress)

        if phase0_result.quality_stats.get("skipped_for_small_sample"):
            phase1a_result = await workflow._run_phase1a_single_chapter_fallback(
                db,
                novel_id,
                start_chapter,
                end_chapter,
            )
            phase1a_result.quality_stats["direct_single_chapter_fallback"] = True
        elif workflow._should_use_single_chapter_phase1a(
            phase0_result,
            start_chapter=start_chapter,
            end_chapter=end_chapter,
        ):
            phase1a_result = await workflow._run_phase1a_single_chapter_fallback(
                db,
                novel_id,
                start_chapter,
                end_chapter,
            )
            phase1a_result.quality_stats["direct_single_chapter_fallback"] = True
        else:
            phase1a_result = await workflow._run_phase1a_reinforcement(
                db,
                novel_id,
                start_chapter,
                end_chapter,
                phase0_result.candidates,
            )
        progress.quality_stats["phase1a"] = phase1a_result.quality_stats
        if phase1a_diagnostics := workflow._diagnostic_samples(
            phase1a_result.diagnostics
        ):
            progress.quality_stats["phase1a_diagnostics"] = phase1a_diagnostics
        workflow._update_phase1_batch_counts(
            progress,
            phase0_result,
            phase1a_result,
        )
        if phase1a_result.blocked:
            progress.phase = "failed"
            progress.quality_status = "failed"
            progress.current_step = None
            progress.degraded = True
            progress.degraded_reason = phase1a_result.block_reason
            progress.message = (
                "Phase 1a Scene 强化 422 错误率过高，已停止深度导入。"
                f"{_phase0_422_recommendation()}"
            )
            progress.phase_errors.append(
                {
                    "phase": "phase1a_reinforce",
                    "error_kind": phase1a_result.block_reason
                    or "phase1a_422_rate_exceeded",
                    "message": progress.message[:300],
                }
            )
            workflow._finish_phase(
                progress,
                "phase1a_reinforce",
                status="failed",
                details=phase1a_result.quality_stats,
                error_kind=progress.degraded_reason,
                error_message=progress.message,
            )
            await workflow._emit_progress(progress, 1.0, on_progress)
            return ScenePhaseOutcome(total_scenes=0, stopped=True)

        fallback_chapters = workflow._missing_phase1a_chapters(
            phase1a_result.candidates,
            start_chapter,
            end_chapter,
        )
        phase1a_success_count = int(phase1a_result.quality_stats.get("success", 0))
        phase1a_failed_count = int(phase1a_result.quality_stats.get("failed", 0))
        if (
            fallback_chapters
            and phase1a_failed_count > 0
            and end_chapter - start_chapter + 1 <= 12
            and not phase1a_result.quality_stats.get("direct_single_chapter_fallback")
        ):
            fallback_result = await workflow._run_phase1a_single_chapter_fallback(
                db,
                novel_id,
                start_chapter,
                end_chapter,
                only_chapters=fallback_chapters,
            )
            progress.quality_stats["phase1a_single_chapter_fallback"] = (
                fallback_result.quality_stats
            )
            if fallback_result.candidates:
                if phase1a_success_count <= 0:
                    phase1a_result = fallback_result
                else:
                    phase1a_result = workflow._merge_phase1a_results(
                        phase1a_result,
                        fallback_result,
                    )
        progress.quality_stats["phase1a"] = phase1a_result.quality_stats
        if phase1a_diagnostics := workflow._diagnostic_samples(
            phase1a_result.diagnostics
        ):
            progress.quality_stats["phase1a_diagnostics"] = phase1a_diagnostics
        workflow._update_phase1_batch_counts(
            progress,
            phase0_result,
            phase1a_result,
        )
        workflow._finish_phase(
            progress,
            "phase1a_reinforce",
            status="completed",
            details={
                **phase1a_result.quality_stats,
                "candidate_count": len(phase1a_result.candidates),
                "missing_chapters": workflow._missing_phase1a_chapters(
                    phase1a_result.candidates,
                    start_chapter,
                    end_chapter,
                ),
            },
        )

        # Phase 1b: windowed reducer/fusion.
        progress.current_phase = "phase1b_fusion"
        progress.current_operation = "scene_fusion"
        progress.message = "正在融合 Scene 候选并生成正式写入候选..."
        workflow._start_phase(
            progress,
            "phase1b_fusion",
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

        phase1b_result = await workflow._run_phase1b_fusion(
            phase1a_result.candidates,
            start_chapter=start_chapter,
            end_chapter=end_chapter,
        )
        progress.quality_stats["phase1b"] = phase1b_result.quality_stats
        if phase1b_diagnostics := workflow._diagnostic_samples(
            phase1b_result.diagnostics
        ):
            progress.quality_stats["phase1b_diagnostics"] = phase1b_diagnostics
        progress.phase1a_fallback = phase1b_result.phase1a_fallback
        workflow._update_phase1_batch_counts(
            progress,
            phase0_result,
            phase1a_result,
            phase1b_result,
        )

        if phase1b_result.degraded:
            progress.degraded = True
            progress.degraded_reason = (
                phase1b_result.block_reason or "phase1b_degraded_fallback"
            )
            progress.phase_errors.append(
                {
                    "phase": "phase1b_fusion",
                    "error_kind": progress.degraded_reason,
                    "message": (
                        "Phase 1b Scene 融合降级，已使用 Phase 1a fallback "
                        "候选继续提交。"
                    ),
                }
            )
        workflow._finish_phase(
            progress,
            "phase1b_fusion",
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
        progress.message = "正在提交融合后的正式 Scene..."
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
        if total_scenes > 0:
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
            progress.degraded_reason = "empty_scene_commit"
            progress.phase_errors.append(
                {
                    "phase": DeepImportStep.scene_segmentation.value,
                    "error_kind": "empty_scene_commit",
                    "message": "Scene 提交阶段未创建或复用任何 Scene",
                }
            )
            progress.message = "Scene 提交阶段未创建或复用任何 Scene，已停止深度导入。"
            workflow._finish_phase(
                progress,
                "scene_commit",
                status="failed",
                details=progress.quality_stats["scene_commit"],
                error_kind="empty_scene_commit",
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
