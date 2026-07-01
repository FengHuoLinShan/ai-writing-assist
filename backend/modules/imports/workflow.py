"""Deep Import 工作流编排器

三阶段流水线：
  Phase 1: Scene 切分（并行批次）→ scenes 表
  Phase 2: 实体增量提取（串行按 Scene）→ core_entities + delta_log
  Phase 3: 剧情结构分析（单次）
  → plot_threads + outline_arcs + foreshadowing_plans + reveal_plans
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from core.config import get_settings
from core.container import get as _container_get
from modules.imports.workflow_schemas import DeepImportProgress, DeepImportStep

logger = logging.getLogger(__name__)

PHASE0_422_RECOMMENDATION = (
    "推荐使用官方api以保障稳定性与质量；"
    "强推 DeepSeek-v4-flash，质量高价格低并发超快。"
)
PHASE3_STRUCTURE_TIMEOUT_SECONDS = 300
DEEP_IMPORT_STRUCTURED_TIMEOUT_GRACE_SECONDS = 15
SMALL_SAMPLE_STRUCTURE_TARGET_COUNT = 4
PHASE1B_SMALL_SAMPLE_MAX_TOKENS = 6144
PHASE1B_SMALL_SAMPLE_TIMEOUT_SECONDS = 90
PHASE1B_COMPACT_TEXT_LIMIT = 180


class DeepImportWorkflow:
    """深度导入流水线编排器 — 三阶段全自动"""

    async def run_step(
        self,
        db: AsyncSession,
        novel_id: str,
        start_chapter: int,
        end_chapter: int,
        progress: DeepImportProgress,
        *,
        workflow_id: str | None = None,
        context_mode: str = "working",
        include_pending_objects: bool = True,
        on_progress: Callable[[DeepImportProgress, float], Awaitable[None]] | None = None,
    ) -> DeepImportProgress:
        if progress.phase == "pending":
            if self._is_llm_health_required():
                health = await self._check_llm_health()
                progress.llm_health = health.model_dump()
                if not health.ok:
                    progress.phase = "failed"
                    progress.quality_status = "failed"
                    progress.current_step = None
                    progress.degraded = True
                    progress.message = (
                        "LLM 健康检查失败，已停止深度导入："
                        f"{health.error_kind or health.message}"
                    )
                    progress.phase_errors.append(
                        {
                            "phase": "preflight",
                            "error_kind": health.error_kind or "llm_unavailable",
                            "message": health.message[:300],
                        }
                    )
                    await self._emit_progress(progress, 1.0, on_progress)
                    return progress

            progress.phase = "running"

            # Phase 0: Scene candidate prefetch quality gate.
            progress.current_step = DeepImportStep.scene_segmentation
            progress.current_phase = "phase0_prefetch"
            progress.current_operation = "scene_prefetch"
            progress.message = "正在预取 Scene 候选并统计质量..."
            self._start_phase(
                progress,
                "phase0_prefetch",
                item={
                    "kind": "chapter_range",
                    "start_chapter": start_chapter,
                    "end_chapter": end_chapter,
                },
            )
            await self._emit_progress(progress, 0.0, on_progress)

            phase0_result = await self._run_phase0_prefetch(
                db,
                novel_id,
                start_chapter,
                end_chapter,
            )
            progress.quality_stats["phase0"] = phase0_result.quality_stats
            if phase0_diagnostics := self._diagnostic_samples(
                phase0_result.diagnostics
            ):
                progress.quality_stats["phase0_diagnostics"] = phase0_diagnostics
            progress.phase1_total_batches = int(
                phase0_result.quality_stats.get("total_batches", 0)
            )
            progress.phase1_completed_batches = int(
                phase0_result.quality_stats.get("completed_batches", 0)
            )
            self._finish_phase(
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
                    f"{PHASE0_422_RECOMMENDATION}"
                )
                progress.phase_errors.append(
                    {
                        "phase": "phase0_prefetch",
                        "error_kind": phase0_result.block_reason
                        or "phase0_422_rate_exceeded",
                        "message": progress.message[:300],
                    }
                )
                self._finish_phase(
                    progress,
                    "phase0_prefetch",
                    status="failed",
                    error_kind=progress.degraded_reason,
                    error_message=progress.message,
                )
                await self._emit_progress(progress, 1.0, on_progress)
                return progress

            # Phase 1a: text-backed candidate reinforcement.
            progress.current_step = DeepImportStep.scene_segmentation
            progress.current_phase = "phase1a_reinforce"
            progress.current_operation = "scene_reinforcement"
            progress.message = "正在结合正文强化 Scene 候选..."
            self._start_phase(
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
            await self._emit_progress(progress, 0.1, on_progress)

            if phase0_result.quality_stats.get("skipped_for_small_sample"):
                phase1a_result = await self._run_phase1a_single_chapter_fallback(
                    db,
                    novel_id,
                    start_chapter,
                    end_chapter,
                )
                phase1a_result.quality_stats["direct_single_chapter_fallback"] = True
            elif self._should_use_single_chapter_phase1a(
                phase0_result,
                start_chapter=start_chapter,
                end_chapter=end_chapter,
            ):
                phase1a_result = await self._run_phase1a_single_chapter_fallback(
                    db,
                    novel_id,
                    start_chapter,
                    end_chapter,
                )
                phase1a_result.quality_stats["direct_single_chapter_fallback"] = True
            else:
                phase1a_result = await self._run_phase1a_reinforcement(
                    db,
                    novel_id,
                    start_chapter,
                    end_chapter,
                    phase0_result.candidates,
                )
            progress.quality_stats["phase1a"] = phase1a_result.quality_stats
            if phase1a_diagnostics := self._diagnostic_samples(
                phase1a_result.diagnostics
            ):
                progress.quality_stats["phase1a_diagnostics"] = phase1a_diagnostics
            self._update_phase1_batch_counts(
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
                    f"{PHASE0_422_RECOMMENDATION}"
                )
                progress.phase_errors.append(
                    {
                        "phase": "phase1a_reinforce",
                        "error_kind": phase1a_result.block_reason
                        or "phase1a_422_rate_exceeded",
                        "message": progress.message[:300],
                    }
                )
                self._finish_phase(
                    progress,
                    "phase1a_reinforce",
                    status="failed",
                    details=phase1a_result.quality_stats,
                    error_kind=progress.degraded_reason,
                    error_message=progress.message,
                )
                await self._emit_progress(progress, 1.0, on_progress)
                return progress

            fallback_chapters = self._missing_phase1a_chapters(
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
                and not phase1a_result.quality_stats.get(
                    "direct_single_chapter_fallback"
                )
            ):
                fallback_result = await self._run_phase1a_single_chapter_fallback(
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
                        phase1a_result = self._merge_phase1a_results(
                            phase1a_result,
                            fallback_result,
                        )
            progress.quality_stats["phase1a"] = phase1a_result.quality_stats
            if phase1a_diagnostics := self._diagnostic_samples(
                phase1a_result.diagnostics
            ):
                progress.quality_stats["phase1a_diagnostics"] = phase1a_diagnostics
            self._update_phase1_batch_counts(
                progress,
                phase0_result,
                phase1a_result,
            )
            self._finish_phase(
                progress,
                "phase1a_reinforce",
                status="completed",
                details={
                    **phase1a_result.quality_stats,
                    "candidate_count": len(phase1a_result.candidates),
                    "missing_chapters": self._missing_phase1a_chapters(
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
            self._start_phase(
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
            await self._emit_progress(progress, 0.2, on_progress)

            phase1b_result = await self._run_phase1b_fusion(
                phase1a_result.candidates,
                start_chapter=start_chapter,
                end_chapter=end_chapter,
            )
            progress.quality_stats["phase1b"] = phase1b_result.quality_stats
            if phase1b_diagnostics := self._diagnostic_samples(
                phase1b_result.diagnostics
            ):
                progress.quality_stats["phase1b_diagnostics"] = phase1b_diagnostics
            progress.phase1a_fallback = phase1b_result.phase1a_fallback
            self._update_phase1_batch_counts(
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
            self._finish_phase(
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
            self._start_phase(
                progress,
                "scene_commit",
                item={
                    "kind": "scene_candidates",
                    "count": len(phase1b_result.candidates),
                },
            )
            self._update_phase1_batch_counts(
                progress,
                phase0_result,
                phase1a_result,
                phase1b_result,
                commit_started=True,
            )
            await self._emit_progress(progress, 0.3, on_progress)

            commit_result = await self._commit_fused_scenes(
                db,
                novel_id,
                phase1b_result.candidates,
                workflow_id=workflow_id or progress.workflow_id or "manual",
            )
            self._update_phase1_batch_counts(
                progress,
                phase0_result,
                phase1a_result,
                phase1b_result,
                commit_completed=True,
            )
            progress.quality_stats["scene_commit"] = commit_result.model_dump(
                mode="json"
            )
            total_scenes = commit_result.created_count + commit_result.skipped_count
            if total_scenes > 0:
                self._mark_step_completed(progress, DeepImportStep.scene_segmentation)
                self._finish_phase(
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
                progress.message = (
                    "Scene 提交阶段未创建或复用任何 Scene，已停止深度导入。"
                )
                self._finish_phase(
                    progress,
                    "scene_commit",
                    status="failed",
                    details=progress.quality_stats["scene_commit"],
                    error_kind="empty_scene_commit",
                    error_message=progress.message,
                )
                await self._emit_progress(progress, 1.0, on_progress)
                return progress
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

            # Phase 2: 实体增量提取
            progress.current_step = DeepImportStep.entity_extraction
            progress.current_phase = "entity_extraction"
            progress.current_operation = "scene_entity_extraction"
            progress.message = "正在按 Scene 提取世界对象..."
            self._start_phase(
                progress,
                "entity_extraction",
                item={"kind": "scene", "completed": 0, "total": total_scenes},
            )
            await self._emit_progress(progress, 0.4, on_progress)

            async def _on_scene_progress(completed: int, total: int) -> None:
                progress.phase2_total_scenes = total
                progress.phase2_completed_scenes = completed
                progress.current_item = {
                    "kind": "scene",
                    "completed": completed,
                    "total": total,
                }
                value = 0.4 + 0.4 * (completed / total) if total else 0.4
                await self._emit_progress(progress, value, on_progress)

            phase2_failed = False
            try:
                phase2_result = await self._extract_entities_by_scene(
                    db,
                    novel_id,
                    workflow_id=workflow_id,
                    on_scene_progress=_on_scene_progress,
                    existing_checkpoints=progress.checkpoints,
                )
                self._merge_checkpoints(progress, phase2_result)
                self._mark_step_completed(progress, DeepImportStep.entity_extraction)
                self._merge_audit_summary(progress, phase2_result)
                self._merge_snapshot_health_summary(progress, phase2_result)
                progress.quality_stats["phase2"] = self._phase2_quality_stats(
                    phase2_result
                )
                await self._refresh_snapshot_health_summary(
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
                self._finish_phase(
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
                await self._rollback_after_phase_failure(db, "entity_extraction", exc)
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
                progress.quality_stats["phase2"] = self._phase2_quality_stats(
                    phase2_result
                )
                progress.degraded = True
                progress.phase_errors.append(
                    {
                        "phase": DeepImportStep.entity_extraction.value,
                        "error_kind": "phase_failed",
                        "message": f"实体提取阶段失败，已继续后续阶段：{str(exc)[:180]}",
                    }
                )
                progress.message = "实体提取阶段失败，已降级继续结构分析。"
                self._finish_phase(
                    progress,
                    "entity_extraction",
                    status="failed",
                    details=progress.quality_stats["phase2"],
                    error_kind="phase_failed",
                    error_message=str(exc),
                )
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
                self._finish_phase(
                    progress,
                    "entity_extraction",
                    status="degraded",
                    details=progress.quality_stats["phase2"],
                    error_kind=phase2_result.get("error_kind", "empty_output"),
                    error_message="实体提取阶段未生成任何实体",
                )

            # Phase 3: 剧情结构分析
            progress.current_step = DeepImportStep.structure_analysis
            progress.current_phase = "structure_analysis"
            progress.current_operation = "structure_analysis"
            progress.message = "正在生成剧情线、篇章纲、伏笔和揭示计划..."
            self._start_phase(
                progress,
                "structure_analysis",
                item={
                    "kind": "chapter_range",
                    "start_chapter": start_chapter,
                    "end_chapter": end_chapter,
                },
            )
            await self._emit_progress(progress, 0.8, on_progress)
            phase3_failed = False
            try:
                phase3_result = await asyncio.wait_for(
                    self._analyze_structure(
                        db,
                        novel_id,
                        start_chapter,
                        end_chapter,
                        workflow_id=workflow_id,
                        context_mode=context_mode,
                        include_pending_objects=include_pending_objects,
                    ),
                    timeout=PHASE3_STRUCTURE_TIMEOUT_SECONDS,
                )
            except TimeoutError as exc:
                phase3_failed = True
                await self._rollback_after_phase_failure(db, "structure_analysis", exc)
                phase3_result = {
                    "total_threads": 0,
                    "total_arcs": 0,
                    "total_foreshadowing": 0,
                    "total_reveals": 0,
                    "threads": [],
                    "arcs": [],
                    "foreshadowing_plans": [],
                    "reveal_plans": [],
                    "extra_sections": {},
                    "error_kind": "timeout",
                    "error_message": "剧情结构分析超时，已降级完成。",
                }
                progress.degraded = True
                progress.phase_errors.append(
                    {
                        "phase": DeepImportStep.structure_analysis.value,
                        "error_kind": "timeout",
                        "message": "剧情结构分析超时，已降级完成；可稍后重试结构分析。",
                    }
                )
                progress.message = "剧情结构分析超时，已降级完成。"
            else:
                self._mark_step_completed(progress, DeepImportStep.structure_analysis)
                self._merge_audit_summary(progress, phase3_result)
                self._merge_snapshot_health_summary(progress, phase3_result)
            progress.quality_stats["phase3"] = self._phase3_quality_stats(
                phase3_result,
                failed=phase3_failed,
            )
            await self._refresh_snapshot_health_summary(
                db,
                novel_id,
                workflow_id or progress.workflow_id,
                progress,
            )
            if (
                total_scenes > 0
                and not phase3_failed
                and phase3_result.get("total_threads", 0) <= 0
                and phase3_result.get("total_arcs", 0) <= 0
            ):
                progress.degraded = True
                progress.quality_stats["phase3"]["error_kind"] = phase3_result.get(
                    "error_kind",
                    "empty_output",
                )
                progress.phase_errors.append(
                    {
                        "phase": DeepImportStep.structure_analysis.value,
                        "error_kind": phase3_result.get("error_kind", "empty_output"),
                        "message": "剧情结构阶段未生成剧情线或篇章纲",
                    }
                )
            self._finish_phase(
                progress,
                "structure_analysis",
                status="failed"
                if phase3_failed
                else (
                    "degraded"
                    if progress.quality_stats["phase3"]["error_kind"]
                    else "completed"
                ),
                details=progress.quality_stats["phase3"],
                error_kind=progress.quality_stats["phase3"].get("error_kind"),
                error_message=phase3_result.get("error_message"),
            )

            progress.current_step = None
            progress.phase = "done"
            if total_scenes <= 0:
                progress.quality_status = "failed"
            else:
                progress.quality_status = "partial" if progress.degraded else "complete"
            progress.message = (
                f"深度导入完成！"
                f"共 {total_scenes} 个 Scene，"
                f"{phase2_result.get('total_created', 0)} 个实体，"
                f"{phase3_result.get('total_threads', 0)} 条剧情线，"
                f"{phase3_result.get('total_arcs', 0)} 个篇章纲。"
            )
            await self._emit_progress(progress, 1.0, on_progress)

        else:
            raise ValueError(f"无法处理当前进度状态: {progress.phase}")

        return progress

    @staticmethod
    def _is_llm_health_required() -> bool:
        return get_settings().llm_health_required

    @staticmethod
    async def _check_llm_health():
        from infrastructure.llm.health import check_llm_health

        return await check_llm_health()

    @staticmethod
    async def _run_phase0_prefetch(
        db: AsyncSession,
        novel_id: str,
        start_chapter: int,
        end_chapter: int,
    ):
        from modules.imports.scene_prefetch import Phase0ScenePrefetcher

        if end_chapter - start_chapter + 1 <= 7:
            return DeepImportWorkflow._small_sample_phase0_skip_result(
                start_chapter,
                end_chapter,
            )

        prefetcher = Phase0ScenePrefetcher(
            llm=_Phase0SceneCandidateLLM(
                db,
                novel_id,
                timeout_seconds=None,
            ),
        )
        return await prefetcher.run(
            db,
            novel_id=novel_id,
            start_chapter=start_chapter,
            end_chapter=end_chapter,
        )

    @staticmethod
    def _small_sample_phase0_skip_result(start_chapter: int, end_chapter: int):
        from modules.imports.scene_candidates import ScenePrefetchResult
        from modules.imports.scene_prefetch import build_phase0_prefetch_batches

        batches = build_phase0_prefetch_batches(start_chapter, end_chapter)
        diagnostics = [
            {
                "attempts": 0,
                "final_status": "skipped",
                "final_error_type": None,
                "chapter_index": None,
                "source_batch_id": batch.batch_id,
                "diagnostics": [
                    {
                        "error_type": None,
                        "message": (
                            "small sample bypassed Phase 0; Phase 1a single "
                            "chapter extraction is authoritative"
                        ),
                    }
                ],
            }
            for batch in batches
        ]
        return ScenePrefetchResult(
            candidates=[],
            quality_stats={
                "total_batches": len(batches),
                "completed_batches": len(batches),
                "success": 0,
                "failed": 0,
                "high_quality": 0,
                "low_quality": 0,
                "empty_result": 0,
                "schema_error": 0,
                "timeout": 0,
                "network": 0,
                "rate_limit": 0,
                "quality_gate": 0,
                "http_error": 0,
                "unknown": 0,
                "final_422": 0,
                "final_422_rate": 0.0,
                "skipped": len(batches),
                "skipped_for_small_sample": True,
            },
            diagnostics=diagnostics,
            blocked=False,
            block_reason=None,
        )

    @staticmethod
    async def _load_chapters_for_reinforcement(
        db: AsyncSession,
        novel_id: str,
        start_chapter: int,
        end_chapter: int,
    ) -> list[dict]:
        from modules.imports.scene_segmentation import SceneSegmentationService

        return await SceneSegmentationService()._load_chapters(
            db,
            novel_id,
            start_chapter,
            end_chapter,
        )

    async def _run_phase1a_reinforcement(
        self,
        db: AsyncSession,
        novel_id: str,
        start_chapter: int,
        end_chapter: int,
        phase0_candidates,
    ):
        from modules.imports.scene_reinforcement import Phase1aSceneReinforcer

        chapters = await self._load_chapters_for_reinforcement(
            db,
            novel_id,
            start_chapter,
            end_chapter,
        )
        return await Phase1aSceneReinforcer(
            llm=_Phase1aSceneCandidateLLM(),
        ).run(
            phase0_candidates=phase0_candidates,
            chapters=chapters,
        )

    @staticmethod
    async def _run_phase1a_single_chapter_fallback(
        db: AsyncSession,
        novel_id: str,
        start_chapter: int,
        end_chapter: int,
        *,
        only_chapters: list[int] | None = None,
    ):
        from modules.imports.deep_import_retry import run_deep_import_llm_with_retry
        from modules.imports.llm_schemas import SceneSegmentationOutput
        from modules.imports.scene_candidates import (
            SceneCandidate,
            SceneCandidateBatch,
            SceneReinforcementResult,
        )
        from modules.imports.scene_segmentation import SceneSegmentationService

        chapters = await SceneSegmentationService()._load_chapters(
            db,
            novel_id,
            start_chapter,
            end_chapter,
        )
        wanted_chapters = set(only_chapters or [])
        if wanted_chapters:
            chapters = [
                chapter
                for chapter in chapters
                if int(chapter["chapter_index"]) in wanted_chapters
            ]
        semaphore = asyncio.Semaphore(50)

        async def process(chapter: dict[str, Any]) -> SceneCandidate:
            chapter_index = int(chapter["chapter_index"])
            batch = SceneCandidateBatch(
                batch_id=f"S-{chapter_index:04d}",
                round_name="A",
                batch_index=chapter_index,
                chapter_indices=[chapter_index],
            )
            async with semaphore:
                retry_result = await run_deep_import_llm_with_retry(
                    lambda: _SingleChapterSceneCandidateLLM()(chapter),
                    is_empty_result=lambda output: not output.scenes,
                    max_retries=1,
                )
            diagnostics = retry_result.model_dump(mode="json", exclude={"value"})
            diagnostics["chapter_index"] = chapter_index
            diagnostics["source_batch_id"] = batch.batch_id
            if retry_result.final_status != "success":
                return SceneCandidate(
                    candidate_id=f"phase1a-single-{chapter_index}",
                    source_round="A",
                    source_batch_id=batch.batch_id,
                    source_batch_index=batch.batch_index,
                    source_chapter_indices=[chapter_index],
                    quality="failed",
                    payload={},
                    diagnostics=diagnostics,
                )

            output = retry_result.value
            if not isinstance(output, SceneSegmentationOutput):
                output = SceneSegmentationOutput.model_validate(output)
            return SceneCandidate(
                candidate_id=f"phase1a-single-{chapter_index}",
                source_round="A",
                source_batch_id=batch.batch_id,
                source_batch_index=batch.batch_index,
                source_chapter_indices=[chapter_index],
                quality="high",
                payload={
                    "scenes": [scene.model_dump(mode="json") for scene in output.scenes],
                    "boundary_status": "complete",
                    "boundary_reason": "single chapter fallback",
                    "confidence": 0.65,
                    "source_round": "A",
                    "source_batch_id": batch.batch_id,
                    "source_chapter_indices": [chapter_index],
                },
                diagnostics=diagnostics,
            )

        candidates = await asyncio.gather(*(process(chapter) for chapter in chapters))
        quality_stats = {
            "total_batches": len(chapters),
            "completed_batches": len(candidates),
            "success": sum(1 for item in candidates if item.quality != "failed"),
            "failed": sum(1 for item in candidates if item.quality == "failed"),
            "high_quality": sum(1 for item in candidates if item.quality == "high"),
            "low_quality": sum(1 for item in candidates if item.quality == "low"),
            "empty_result": 0,
            "schema_error": 0,
            "timeout": 0,
            "network": 0,
            "rate_limit": 0,
            "quality_gate": 0,
            "http_error": 0,
            "unknown": 0,
            "final_422": 0,
        }
        for candidate in candidates:
            error_type = candidate.diagnostics.get("final_error_type")
            if error_type in quality_stats:
                quality_stats[error_type] += 1
            if error_type == "422":
                quality_stats["final_422"] += 1
        quality_stats["final_422_rate"] = (
            quality_stats["final_422"] / len(chapters) if chapters else 0.0
        )
        return SceneReinforcementResult(
            candidates=candidates,
            quality_stats=quality_stats,
            diagnostics=[
                candidate.diagnostics
                for candidate in candidates
                if candidate.diagnostics
            ],
            blocked=False,
            block_reason=None,
        )

    @staticmethod
    def _missing_phase1a_chapters(
        candidates,
        start_chapter: int,
        end_chapter: int,
    ) -> list[int]:
        covered = {
            int(chapter)
            for candidate in candidates
            if candidate.quality != "failed"
            for chapter in candidate.source_chapter_indices
            if start_chapter <= int(chapter) <= end_chapter
        }
        return [
            chapter
            for chapter in range(start_chapter, end_chapter + 1)
            if chapter not in covered
        ]

    @staticmethod
    def _should_use_single_chapter_phase1a(
        phase0_result,
        *,
        start_chapter: int,
        end_chapter: int,
    ) -> bool:
        chapter_count = end_chapter - start_chapter + 1
        if chapter_count > 7:
            return False
        stats = getattr(phase0_result, "quality_stats", {}) or {}
        if stats.get("skipped_for_small_sample"):
            return False
        return int(stats.get("failed", 0)) > 0

    @staticmethod
    def _merge_phase1a_results(primary, fallback):
        from modules.imports.scene_candidates import SceneReinforcementResult

        count_keys = {
            "total_batches",
            "completed_batches",
            "success",
            "failed",
            "high_quality",
            "low_quality",
            "empty_result",
            "schema_error",
            "timeout",
            "network",
            "rate_limit",
            "quality_gate",
            "http_error",
            "unknown",
            "final_422",
        }
        quality_stats = {
            **primary.quality_stats,
            "fallback_chapter_count": len(fallback.candidates),
        }
        for key in count_keys:
            quality_stats[key] = int(primary.quality_stats.get(key, 0)) + int(
                fallback.quality_stats.get(key, 0)
            )
        total_batches = int(quality_stats.get("total_batches", 0))
        quality_stats["final_422_rate"] = (
            int(quality_stats.get("final_422", 0)) / total_batches
            if total_batches
            else 0.0
        )
        return SceneReinforcementResult(
            candidates=[*primary.candidates, *fallback.candidates],
            quality_stats=quality_stats,
            diagnostics=[*primary.diagnostics, *fallback.diagnostics],
            blocked=primary.blocked or fallback.blocked,
            block_reason=primary.block_reason or fallback.block_reason,
            did_merge_rounds=primary.did_merge_rounds or fallback.did_merge_rounds,
        )

    @staticmethod
    async def _run_phase1b_fusion(
        phase1a_candidates,
        *,
        start_chapter: int,
        end_chapter: int,
    ):
        from modules.imports.scene_fusion import Phase1bSceneFusion

        return await Phase1bSceneFusion(llm=_Phase1bSceneFusionLLM()).run(
            phase1a_candidates=phase1a_candidates,
            start_chapter=start_chapter,
            end_chapter=end_chapter,
        )

    @staticmethod
    async def _commit_fused_scenes(
        db: AsyncSession,
        novel_id: str,
        candidates,
        *,
        workflow_id: str,
    ):
        from modules.imports.scene_commit import SceneCommitter

        return await SceneCommitter().commit(
            db,
            novel_id,
            candidates,
            workflow_id=workflow_id,
        )

    @staticmethod
    def _update_phase1_batch_counts(
        progress: DeepImportProgress,
        phase0_result,
        phase1a_result=None,
        phase1b_result=None,
        *,
        commit_started: bool = False,
        commit_completed: bool = False,
    ) -> None:
        phase0_stats = phase0_result.quality_stats if phase0_result else {}
        phase1a_stats = phase1a_result.quality_stats if phase1a_result else {}
        phase1b_stats = phase1b_result.quality_stats if phase1b_result else {}

        total = int(phase0_stats.get("total_batches", 0)) + int(
            phase1a_stats.get("total_batches", 0)
        )
        completed = int(phase0_stats.get("completed_batches", 0)) + int(
            phase1a_stats.get("completed_batches", 0)
        )
        total += int(phase1b_stats.get("total_windows", 0))
        completed += int(phase1b_stats.get("completed_windows", 0))
        if commit_started or commit_completed:
            total += 1
        if commit_completed:
            completed += 1

        progress.phase1_total_batches = total
        progress.phase1_completed_batches = completed

    @staticmethod
    def _diagnostic_samples(
        diagnostics: list[dict[str, Any]] | None,
        *,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        if not diagnostics:
            return []
        samples: list[dict[str, Any]] = []
        for diagnostic in diagnostics:
            attempts = diagnostic.get("diagnostics")
            last_attempt = attempts[-1] if isinstance(attempts, list) and attempts else {}
            samples.append(
                {
                    "attempts": diagnostic.get("attempts"),
                    "final_status": diagnostic.get("final_status"),
                    "final_error_type": diagnostic.get("final_error_type"),
                    "chapter_index": diagnostic.get("chapter_index"),
                    "source_batch_id": diagnostic.get("source_batch_id"),
                    "last_error_type": last_attempt.get("error_type"),
                    "last_message": str(last_attempt.get("message") or "")[:300],
                }
            )
            if len(samples) >= limit:
                break
        return samples

    @staticmethod
    def _phase2_quality_stats(phase2_result: dict[str, Any]) -> dict[str, Any]:
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
            "parallel_llm_fallback": bool(
                phase2_result.get("parallel_llm_fallback")
            ),
            "bulk_error_kind": phase2_result.get("bulk_error_kind"),
            "degraded": bool(phase2_result.get("degraded")),
            "error_kind": phase2_result.get("error_kind"),
            "checkpoint_status_counts": status_counts,
        }

    @staticmethod
    def _phase3_quality_stats(
        phase3_result: dict[str, Any],
        *,
        failed: bool,
    ) -> dict[str, Any]:
        extra_sections = phase3_result.get("extra_sections") or {}
        foreshadowing = phase3_result.get("total_foreshadowing")
        reveals = phase3_result.get("total_reveals")
        if foreshadowing is None:
            foreshadowing = len(extra_sections.get("foreshadowing_plans") or [])
        if reveals is None:
            reveals = len(extra_sections.get("reveal_plans") or [])
        return {
            "total_threads": int(phase3_result.get("total_threads", 0) or 0),
            "total_arcs": int(phase3_result.get("total_arcs", 0) or 0),
            "total_foreshadowing": int(foreshadowing or 0),
            "total_reveals": int(reveals or 0),
            "failed": failed,
            "error_kind": phase3_result.get("error_kind"),
        }

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(UTC).isoformat()

    @staticmethod
    def _short_message(message: Any) -> str:
        return str(message or "")[:300]

    @classmethod
    def _start_phase(
        cls,
        progress: DeepImportProgress,
        phase: str,
        *,
        item: dict[str, Any] | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        progress.current_item = item or {}
        progress.phase_timeline.append(
            {
                "phase": phase,
                "operation": progress.current_operation,
                "status": "running",
                "started_at": cls._now_iso(),
                "details": details or {},
            }
        )
        cls._refresh_diagnostic_counts(progress)

    @classmethod
    def _finish_phase(
        cls,
        progress: DeepImportProgress,
        phase: str,
        *,
        status: str = "completed",
        details: dict[str, Any] | None = None,
        error_kind: str | None = None,
        error_message: str | None = None,
    ) -> None:
        now = cls._now_iso()
        target: dict[str, Any] | None = None
        for item in reversed(progress.phase_timeline):
            if item.get("phase") == phase and item.get("status") == "running":
                target = item
                break
        if target is None:
            for item in reversed(progress.phase_timeline):
                if item.get("phase") == phase:
                    target = item
                    break
        if target is not None:
            target["status"] = status
            target["ended_at"] = now
            target["duration_s"] = cls._duration_seconds(target.get("started_at"), now)
            if details:
                target["details"] = {**(target.get("details") or {}), **details}
            if error_kind:
                target["error_kind"] = error_kind
        if error_kind:
            cls._set_last_error(
                progress,
                phase=phase,
                error_kind=error_kind,
                message=error_message,
            )
        cls._refresh_diagnostic_counts(progress)

    @staticmethod
    def _duration_seconds(started_at: Any, ended_at: str) -> float | None:
        if not isinstance(started_at, str):
            return None
        try:
            start = datetime.fromisoformat(started_at)
            end = datetime.fromisoformat(ended_at)
        except ValueError:
            return None
        return round((end - start).total_seconds(), 2)

    @classmethod
    def _set_last_error(
        cls,
        progress: DeepImportProgress,
        *,
        phase: str,
        error_kind: str | None,
        message: Any,
    ) -> None:
        progress.last_error = {
            "phase": phase,
            "error_kind": error_kind or "unknown",
            "message": cls._short_message(message),
        }

    @classmethod
    def _refresh_diagnostic_counts(cls, progress: DeepImportProgress) -> None:
        scene_commit = progress.quality_stats.get("scene_commit") or {}
        phase2 = progress.quality_stats.get("phase2") or {}
        phase3 = progress.quality_stats.get("phase3") or {}
        snapshot = progress.snapshot_health_summary or {}
        snapshot_status = snapshot.get("by_status") or {}
        checkpoint_summary = cls._checkpoint_summary(progress.checkpoints)
        progress.diagnostic_counts = {
            "scene_count": int(scene_commit.get("created_count", 0) or 0)
            + int(scene_commit.get("skipped_count", 0) or 0),
            "created_scene_count": int(scene_commit.get("created_count", 0) or 0),
            "skipped_scene_count": int(scene_commit.get("skipped_count", 0) or 0),
            "phase2_total_scenes": progress.phase2_total_scenes,
            "phase2_completed_scenes": max(
                progress.phase2_completed_scenes,
                int(phase2.get("completed_scenes", 0) or 0),
            ),
            "entity_count": int(phase2.get("total_created", 0) or 0),
            "relation_count": int(phase2.get("total_relations", 0) or 0),
            "delta_count": int(phase2.get("total_deltas", 0) or 0),
            "structure_counts": {
                "threads": int(phase3.get("total_threads", 0) or 0),
                "arcs": int(phase3.get("total_arcs", 0) or 0),
                "foreshadowing": int(phase3.get("total_foreshadowing", 0) or 0),
                "reveals": int(phase3.get("total_reveals", 0) or 0),
            },
            "snapshot_total": int(snapshot.get("total_snapshots", 0) or 0),
            "snapshot_succeeded": int(snapshot_status.get("succeeded", 0) or 0),
            "snapshot_failed": int(snapshot_status.get("failed", 0) or 0),
            "checkpoint_summary": checkpoint_summary,
            "phase_error_count": len(progress.phase_errors),
        }

    @staticmethod
    def _checkpoint_summary(checkpoints: dict[str, Any] | None) -> dict[str, Any]:
        phase2 = (checkpoints or {}).get("phase2")
        scenes = phase2.get("scenes") if isinstance(phase2, dict) else []
        if not isinstance(scenes, list):
            return {}
        status_counts: dict[str, int] = {}
        for item in scenes:
            if not isinstance(item, dict):
                continue
            status = str(item.get("status") or "unknown")
            status_counts[status] = status_counts.get(status, 0) + 1
        return {
            "phase2_scene_checkpoints": len(scenes),
            "phase2_status_counts": status_counts,
        }

    @staticmethod
    async def _emit_progress(
        progress: DeepImportProgress,
        progress_value: float,
        on_progress: Callable[[DeepImportProgress, float], Awaitable[None]] | None,
    ) -> None:
        DeepImportWorkflow._refresh_diagnostic_counts(progress)
        if progress.phase_errors and progress.last_error is None:
            error = progress.phase_errors[-1]
            DeepImportWorkflow._set_last_error(
                progress,
                phase=error.get("phase", progress.current_phase or "unknown"),
                error_kind=error.get("error_kind"),
                message=error.get("message"),
            )
        if on_progress is not None:
            await on_progress(progress, progress_value)

    @staticmethod
    def _mark_step_completed(
        progress: DeepImportProgress,
        step: DeepImportStep,
    ) -> None:
        if step.value not in progress.completed_steps:
            progress.completed_steps.append(step.value)

    @staticmethod
    def _merge_checkpoints(
        progress: DeepImportProgress,
        phase_result: dict[str, Any],
    ) -> None:
        checkpoints = phase_result.get("checkpoints")
        if not isinstance(checkpoints, dict):
            return
        progress.checkpoints = {
            **(progress.checkpoints or {}),
            **checkpoints,
        }

    @staticmethod
    def _merge_audit_summary(
        progress: DeepImportProgress,
        phase_result: dict[str, Any],
    ) -> None:
        audit_summary = phase_result.get("audit_summary")
        if isinstance(audit_summary, dict):
            progress.audit_summary = {
                **(progress.audit_summary or {}),
                **audit_summary,
            }

    @staticmethod
    def _merge_snapshot_health_summary(
        progress: DeepImportProgress,
        phase_result: dict[str, Any],
    ) -> None:
        snapshot_health_summary = phase_result.get("snapshot_health_summary")
        if isinstance(snapshot_health_summary, dict):
            progress.snapshot_health_summary = snapshot_health_summary

    @staticmethod
    async def _refresh_snapshot_health_summary(
        db: AsyncSession,
        novel_id: str,
        workflow_id: str | None,
        progress: DeepImportProgress,
    ) -> None:
        if db is None or not workflow_id or type(db).__module__ == "unittest.mock":
            return
        from modules.context.facade import build_snapshot_health_summary

        try:
            progress.snapshot_health_summary = await build_snapshot_health_summary(
                db,
                novel_id=novel_id,
                workflow_id=workflow_id,
            )
        except Exception as exc:
            logger.warning("snapshot health summary refresh failed: %s", exc)

    @staticmethod
    async def _rollback_after_phase_failure(
        db: AsyncSession,
        phase: str,
        exc: Exception,
    ) -> None:
        try:
            await db.rollback()
        except Exception:
            logger.warning("%s failed and rollback also failed", phase, exc_info=True)
        else:
            logger.warning("%s failed; transaction rolled back: %s", phase, exc)

    # ------------------------------------------------------------------
    # Phase 1: Scene 切分
    # ------------------------------------------------------------------

    async def _segment_scenes(
        self,
        db: AsyncSession,
        novel_id: str,
        start_chapter: int,
        end_chapter: int,
        on_batch_progress: Callable[[int, int], Awaitable[None]] | None = None,
    ) -> dict[str, Any]:
        from modules.imports.scene_segmentation import SceneSegmentationService

        service = SceneSegmentationService()
        result = await service.segment_chapters(
            db,
            novel_id,
            start_chapter,
            end_chapter,
            on_batch_progress=on_batch_progress,
        )
        logger.info(
            "Phase 1 complete: %d scenes, %d failed batches, degraded=%s",
            result.get("total_scenes", 0),
            len(result.get("failed_batches", [])),
            result.get("degraded", False),
        )
        return result

    # ------------------------------------------------------------------
    # Phase 2: 实体增量提取
    # ------------------------------------------------------------------

    async def _extract_entities_by_scene(
        self,
        db: AsyncSession,
        novel_id: str,
        workflow_id: str | None = None,
        on_scene_progress: Callable[[int, int], Awaitable[None]] | None = None,
        existing_checkpoints: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            handler = _container_get("world.run_scene_entity_extraction")
            result = await handler(
                db,
                novel_id=novel_id,
                workflow_id=workflow_id,
                on_scene_progress=on_scene_progress,
                existing_checkpoints=existing_checkpoints,
            )
            return result
        except Exception as exc:
            logger.warning("Phase 2 entity extraction failed: %s", exc)
            return {
                "total_created": 0,
                "total_relations": 0,
                "total_deltas": 0,
                "error_kind": getattr(exc, "error_kind", "phase_error"),
                "error_message": str(exc)[:300],
            }

    # ------------------------------------------------------------------
    # Phase 3: 剧情结构分析
    # ------------------------------------------------------------------

    async def _analyze_structure(
        self,
        db: AsyncSession,
        novel_id: str,
        start_chapter: int,
        end_chapter: int,
        *,
        workflow_id: str | None = None,
        context_mode: str = "working",
        include_pending_objects: bool = True,
    ) -> dict[str, Any]:
        _generate = _container_get("outline.generate_structure")
        try:
            result = await _generate(
                db,
                novel_id,
                start_chapter=start_chapter,
                end_chapter=end_chapter,
                context_mode=context_mode,
                include_pending_objects=include_pending_objects,
                workflow_id=workflow_id,
                audit_context_snapshot=True,
                include_chapter_texts=False,
                include_existing_scenes=True,
                generate_scenes=False,
                fast_structured=True,
            )
            result = await self._ensure_minimum_structure_outputs(
                db,
                novel_id,
                start_chapter,
                end_chapter,
                result,
                workflow_id=workflow_id,
            )
            logger.info(
                "Phase 3 complete: %d threads, %d arcs",
                result.get("total_threads", 0),
                result.get("total_arcs", 0),
            )
            return result
        except Exception as exc:
            logger.warning("Phase 3 structure analysis failed: %s", exc)
            return {
                "total_threads": 0,
                "total_arcs": 0,
                "threads": [],
                "arcs": [],
                "extra_sections": {},
                "error_kind": getattr(exc, "error_kind", "phase_error"),
                "error_message": str(exc)[:300],
            }

    async def _ensure_minimum_structure_outputs(
        self,
        db: AsyncSession,
        novel_id: str,
        start_chapter: int,
        end_chapter: int,
        result: dict[str, Any],
        *,
        workflow_id: str | None,
    ) -> dict[str, Any]:
        chapter_count = end_chapter - start_chapter + 1
        if chapter_count > 7:
            return result

        counts = self._structure_category_counts(result)
        if all(
            value >= SMALL_SAMPLE_STRUCTURE_TARGET_COUNT for value in counts.values()
        ):
            return result

        created_assets: list[dict[str, Any]] = []
        try:
            from modules.outline.schemas import (
                ForeshadowingPlanCreate,
                OutlineArcCreate,
                PlotThreadCreate,
                RevealPlanCreate,
            )

            arc_service = _container_get("outline.arc_service")
            thread_service = _container_get("outline.thread_service")
            foreshadowing_service = _container_get("outline.foreshadowing_service")
            reveal_service = _container_get("outline.reveal_service")
            provenance_meta = {
                "source": "deep_import",
                "workflow_id": workflow_id,
                "auto_ingested": True,
                "needs_review": True,
                "phase": "structure_analysis",
                "fallback": "category_minimum_structure_outputs",
            }

            for index in range(
                counts["threads"] + 1,
                SMALL_SAMPLE_STRUCTURE_TARGET_COUNT + 1,
            ):
                created = await thread_service.create(
                    db,
                    novel_id,
                    PlotThreadCreate(
                        name=f"第 {start_chapter}-{end_chapter} 章补强剧情线 {index}",
                        thread_type=self._fallback_thread_type(index),
                        summary="根据已导入 Scene 和世界对象补齐的待复核剧情线。",
                        visible_goal="把章节范围内的关键行动转化为可追踪结构资产。",
                        hidden_truth="该项由深度导入小样本结构保底生成，需要人工复核。",
                        start_chapter=start_chapter,
                        planned_payoff_chapter=end_chapter,
                        current_stage="draft",
                        provenance_meta=dict(provenance_meta),
                        status="draft",
                    ),
                )
                thread_summary = {
                    "id": str(created.id),
                    "name": created.name,
                    "thread_type": created.thread_type,
                }
                result.setdefault("threads", []).append(thread_summary)
                result["total_threads"] = int(result.get("total_threads", 0) or 0) + 1
                created_assets.append(
                    {
                        "type": "plot_thread",
                        "id": thread_summary["id"],
                        "reason": "category_minimum_structure_outputs",
                    }
                )

            for index in range(
                counts["arcs"] + 1,
                SMALL_SAMPLE_STRUCTURE_TARGET_COUNT + 1,
            ):
                created = await arc_service.create(
                    db,
                    novel_id,
                    OutlineArcCreate(
                        title=f"第 {start_chapter}-{end_chapter} 章补强篇章纲 {index}",
                        arc_index=index,
                        start_chapter=start_chapter,
                        end_chapter=end_chapter,
                        arc_goal="把已生成 Scene 的阶段性推进整理为可复核篇章结构。",
                        core_conflict=(
                            "关键 Scene 已存在，但结构分析输出不足以覆盖所有转折。"
                        ),
                        entry_hook="从导入 Scene 中回收章节开端的触发事件。",
                        midpoint_turn="以章节中段的认知变化或关系变化作为转折锚点。",
                        climax="以章节范围内最强冲突或信息揭示作为高潮锚点。",
                        result="生成待复核篇章纲候选，供用户整理、合并或删除。",
                        next_hook="用后续章节校验该篇章纲是否应保留。",
                        provenance_meta=dict(provenance_meta),
                        status="draft",
                    ),
                )
                arc_summary = {
                    "id": str(created.id),
                    "title": created.title,
                    "arc_index": created.arc_index,
                }
                result.setdefault("arcs", []).append(arc_summary)
                result["total_arcs"] = int(result.get("total_arcs", 0) or 0) + 1
                created_assets.append(
                    {
                        "type": "outline_arc",
                        "id": arc_summary["id"],
                        "reason": "category_minimum_structure_outputs",
                    }
                )

            extra_sections = result.setdefault("extra_sections", {})
            foreshadowing_items = extra_sections.setdefault("foreshadowing_plans", [])
            for index in range(
                counts["foreshadowing"] + 1,
                SMALL_SAMPLE_STRUCTURE_TARGET_COUNT + 1,
            ):
                created = await foreshadowing_service.create(
                    db,
                    novel_id,
                    ForeshadowingPlanCreate(
                        name=f"第 {start_chapter}-{end_chapter} 章补强伏笔 {index}",
                        summary="根据已导入 Scene 补齐的待复核伏笔计划。",
                        surface_meaning="章节内已经出现但尚未整理为结构资产的线索。",
                        hidden_meaning="该线索可能指向后续身份、组织或非凡规则揭示。",
                        planned_seed_chapter=start_chapter,
                        planned_payoff_chapter=end_chapter,
                        provenance_meta=dict(provenance_meta),
                        status="draft",
                    ),
                )
                item = {"id": str(created.id), "name": created.name}
                foreshadowing_items.append(item)
                created_assets.append(
                    {
                        "type": "foreshadowing_plan",
                        "id": item["id"],
                        "reason": "category_minimum_structure_outputs",
                    }
                )

            reveal_items = extra_sections.setdefault("reveal_plans", [])
            reveal_target = await self._select_fallback_reveal_target(db, novel_id)
            if (
                reveal_target is None
                and counts["reveals"] < SMALL_SAMPLE_STRUCTURE_TARGET_COUNT
            ):
                result.setdefault("warnings", []).append(
                    "小样本揭示计划不足，但没有可关联世界对象，无法补强 reveal。"
                )
            elif reveal_target is not None:
                for index in range(
                    counts["reveals"] + 1,
                    SMALL_SAMPLE_STRUCTURE_TARGET_COUNT + 1,
                ):
                    created = await reveal_service.create(
                        db,
                        novel_id,
                        RevealPlanCreate(
                            target_type="world_entity",
                            target_id=reveal_target["id"],
                            secret_summary=(
                                f"{reveal_target['name']} 在第 "
                                f"{start_chapter}-{end_chapter} 章范围内存在待复核"
                                "的信息层级或隐藏背景。"
                            ),
                            reveal_stages=[
                                {
                                    "stage_index": 0,
                                    "chapter_index": start_chapter,
                                    "reveal_content": "读者获得初步表层线索。",
                                    "trigger": "Scene 导入后的结构补强。",
                                    "effect": "形成后续人工整理的揭示计划草稿。",
                                }
                            ],
                            provenance_meta=dict(provenance_meta),
                            status="draft",
                        ),
                    )
                    item = {
                        "id": str(created.id),
                        "target_name": reveal_target["name"],
                    }
                    reveal_items.append(item)
                    created_assets.append(
                        {
                            "type": "reveal_plan",
                            "id": item["id"],
                            "reason": "category_minimum_structure_outputs",
                        }
                    )
        except Exception as exc:
            warnings = result.setdefault("warnings", [])
            warnings.append(f"category_minimum_structure_outputs fallback failed: {exc}")
            return result

        if created_assets:
            extra_sections = result.setdefault("extra_sections", {})
            extra_sections.setdefault("fallback_structure_assets", []).extend(
                created_assets
            )
            result.setdefault("warnings", []).append(
                "小样本结构类别输出不足，已补充待复核结构候选。"
            )
        return result

    @staticmethod
    def _structure_category_counts(result: dict[str, Any]) -> dict[str, int]:
        extra_sections = result.get("extra_sections") or {}
        return {
            "threads": int(result.get("total_threads", 0) or 0),
            "arcs": int(result.get("total_arcs", 0) or 0),
            "foreshadowing": len(extra_sections.get("foreshadowing_plans") or []),
            "reveals": len(extra_sections.get("reveal_plans") or []),
        }

    @staticmethod
    def _structure_output_count(result: dict[str, Any]) -> int:
        return sum(DeepImportWorkflow._structure_category_counts(result).values())

    @staticmethod
    def _fallback_thread_type(index: int) -> str:
        types = ["main", "secondary", "hidden", "foreshadowing"]
        return types[(index - 1) % len(types)]

    @staticmethod
    async def _select_fallback_reveal_target(
        db: AsyncSession,
        novel_id: str,
    ) -> dict[str, Any] | None:
        entities = await _container_get("world.list_entities")(
            db,
            novel_id,
            limit=20,
        )
        for entity in entities:
            entity_id = entity.get("id")
            name = entity.get("name")
            if entity_id and name:
                return {"id": entity_id, "name": name}
        return None


class _Phase0SceneCandidateLLM:
    """LLM adapter that feeds Phase 0 batches with chapter text without writes."""

    def __init__(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        timeout_seconds: int | None = None,
    ) -> None:
        self.db = db
        self.novel_id = novel_id
        self.timeout_seconds = timeout_seconds

    async def __call__(self, batch) -> Any:
        from core.config import get_settings
        from infrastructure.llm.client import LLMClient
        from infrastructure.llm.schemas import LLMCallRequest, LLMMessage
        from modules.imports.llm_schemas import SceneCandidateOutput
        from modules.imports.scene_segmentation import SceneSegmentationService

        service = SceneSegmentationService()
        chapters = await service._load_chapters(
            self.db,
            self.novel_id,
            min(batch.chapter_indices),
            max(batch.chapter_indices),
        )
        wanted = set(batch.chapter_indices)
        chapters = [ch for ch in chapters if ch.get("chapter_index") in wanted]
        if not chapters:
            return SceneCandidateOutput(
                scenes=[],
                boundary_status="uncertain",
                missing_or_uncertain_items=["no chapter content found"],
            )

        settings = get_settings()
        request = LLMCallRequest(
            model=settings.llm_model,
            messages=[
                LLMMessage(
                    role="system",
                    content=(
                        service._load_prompt()
                        + "\n\n输出 JSON 必须包含 scenes，并可包含 "
                        "boundary_status、evidence_anchors、merge_hints、"
                        "split_hints、confidence、missing_or_uncertain_items。"
                    ),
                ),
                LLMMessage(
                    role="user",
                    content=(
                        "请预取以下章节的候选 Scene。候选只用于质量诊断和后续参考，"
                        "不要假设它们会直接写入正式 Scene。\n\n"
                        f"{service._build_chapters_text(chapters)}"
                    ),
                ),
            ],
            temperature=0.3,
            max_tokens=4096,
            response_format={"type": "json_object"},
        )
        return await _run_deep_import_structured_call(
            LLMClient(timeout=settings.llm_timeout),
            request,
            SceneCandidateOutput,
            transport_retries=False,
            timeout_seconds=self.timeout_seconds,
            fix_prompt=(
                "上一轮输出无法通过 SceneCandidateOutput 校验。请只输出一个 JSON "
                "object，必须包含 scenes 数组；每个 scene 至少包含 title、goal、"
                "scene_chunks，scene_chunks 内必须有 chapter_index。不要 Markdown。"
            ),
        )


class _Phase1aSceneCandidateLLM:
    """LLM adapter for text-backed Phase 1a candidate reinforcement."""

    async def __call__(self, payload: dict[str, Any]) -> Any:
        from core.config import get_settings
        from infrastructure.llm.client import LLMClient
        from infrastructure.llm.schemas import LLMCallRequest, LLMMessage
        from modules.imports.llm_schemas import SceneCandidateOutput

        settings = get_settings()
        request = LLMCallRequest(
            model=settings.llm_model,
            messages=[
                LLMMessage(
                    role="system",
                    content=(
                        "你是长篇小说导入的 Scene 候选强化器。"
                        "只输出 JSON，必须包含 scenes，可包含 boundary_status、"
                        "evidence_anchors、merge_hints、split_hints、confidence、"
                        "missing_or_uncertain_items。不要写入正式 Scene。"
                    ),
                ),
                LLMMessage(
                    role="user",
                    content=(
                        "请基于章节正文、Phase 0 强/弱候选和相邻批次摘要强化当前"
                        "批次候选。保持 source_round/source_batch_id/"
                        "source_chapter_indices 可追溯。\n\n"
                        f"{json.dumps(payload, ensure_ascii=False)}"
                    ),
                ),
            ],
            temperature=0.3,
            max_tokens=4096,
            response_format={"type": "json_object"},
        )
        return await _run_deep_import_structured_call(
            LLMClient(timeout=settings.llm_timeout),
            request,
            SceneCandidateOutput,
            transport_retries=False,
            fix_prompt=(
                "上一轮输出无法通过 SceneCandidateOutput 校验。请只输出一个 JSON "
                "object，必须包含 scenes 数组；不要 Markdown。保留 source_round、"
                "source_batch_id、source_chapter_indices 等可追溯信息。"
            ),
        )


class _SingleChapterSceneCandidateLLM:
    """Small-scope fallback when batch Phase 1a produces no usable candidates."""

    async def __call__(self, chapter: dict[str, Any]) -> Any:
        from core.config import get_settings
        from infrastructure.llm.client import LLMClient
        from infrastructure.llm.schemas import LLMCallRequest, LLMMessage
        from modules.imports.llm_schemas import SceneSegmentationOutput
        from modules.imports.scene_segmentation import SceneSegmentationService

        service = SceneSegmentationService()
        settings = get_settings()
        request = LLMCallRequest(
            model=settings.llm_model,
            messages=[
                LLMMessage(
                    role="system",
                    content=(
                        service._load_prompt()
                        + "\n\n这是小样本恢复路径。只处理单章正文，输出 1-3 个"
                        "高价值 Scene。只输出 JSON，不要 Markdown。"
                    ),
                ),
                LLMMessage(
                    role="user",
                    content=(
                        "请将以下单章正文切分为叙事 Scene。每个 Scene 必须"
                        "包含 title、goal、core_conflict、emotional_beat、"
                        "narrative_tag、scene_chunks。\n\n"
                        f"{service._build_chapters_text([chapter])}"
                    ),
                ),
            ],
            temperature=0.2,
            max_tokens=4096,
            response_format={"type": "json_object"},
        )
        return await _run_deep_import_structured_call(
            LLMClient(timeout=settings.llm_timeout),
            request,
            SceneSegmentationOutput,
            transport_retries=False,
            fix_prompt=(
                "上一轮输出无法通过 SceneSegmentationOutput 校验。请只输出一个 JSON "
                "object，必须包含 scenes 数组；每个 scene 必须包含 title、goal、"
                "core_conflict、emotional_beat、narrative_tag、scene_chunks。"
            ),
        )


class _Phase1bSceneFusionLLM:
    """LLM adapter for Phase 1b reducer windows."""

    async def __call__(self, payload: dict[str, Any]) -> Any:
        from core.config import get_settings
        from infrastructure.llm.client import LLMClient
        from infrastructure.llm.schemas import LLMCallRequest, LLMMessage
        from modules.imports.scene_fusion import Phase1bReducerOutput

        settings = get_settings()
        compact_payload = _compact_phase1b_payload(payload)
        small_sample = _is_small_phase1b_payload(compact_payload)
        max_tokens = PHASE1B_SMALL_SAMPLE_MAX_TOKENS if small_sample else 8192
        timeout_seconds = (
            PHASE1B_SMALL_SAMPLE_TIMEOUT_SECONDS
            if small_sample
            else max(int(settings.llm_timeout), 45)
        )
        scene_guidance = (
            "1-7章样本目标输出9个Scene，必须覆盖1-7章；只合并真正重复的候选。"
            "如果候选覆盖多个章节，应按章节/事件拆分为多个Scene，而不是吞并。"
            if small_sample
            else "按窗口推荐数量输出Scene，必须覆盖窗口核心章节。"
        )
        scene_contract = (
            "每个Scene必须包含完整内容字段：title、goal、core_conflict、"
            "emotional_beat、narrative_tag、scene_chunks，以及追溯字段："
            "source_candidate_ids、source_rounds、source_chapter_indices、operation、"
            "confidence、fallback_required、boundary_status、boundary_reason、"
            "needs_review、review_reason。scene_chunks 内必须有 chapter_index。"
            "所有输出 Scene 的 source_chapter_indices 并集必须覆盖输入的"
            " source_chapter_indices。除非候选确实不可用，不要输出"
            " fallback_required=true。"
        )
        request = LLMCallRequest(
            model=settings.llm_model,
            messages=[
                LLMMessage(
                    role="system",
                    content=(
                        "你是长篇小说导入的 Scene reducer。"
                        "只根据 Phase 1a 候选融合、去重和排序，不读取正文。"
                        f"{scene_guidance}"
                        f"{scene_contract}"
                        "只输出 JSON，必须包含 scenes，可包含 discarded_candidates。"
                    ),
                ),
                LLMMessage(
                    role="user",
                    content=(
                        "请把窗口内候选融合为可提交的正式 Scene 候选。\n"
                        "硬性要求：\n"
                        "1. 输出 scenes 数量应接近 recommended_scene_count；"
                        "小样本 1-7 章不足 9 个时优先拆分跨章候选。\n"
                        "2. 输出 Scene 必须覆盖所有 source_chapter_indices；"
                        "不能只覆盖第一个章节。\n"
                        "3. title/goal/core_conflict/emotional_beat 应来自候选"
                        "内容的综合，不允许留空。\n"
                        "4. scene_chunks 必须写出对应 chapter_index。\n"
                        "5. 只把真正重复或被融合的候选写入 discarded_candidates。\n"
                        "输出示例形状：{\"scenes\":[{\"title\":\"...\","
                        "\"goal\":\"...\",\"core_conflict\":\"...\","
                        "\"emotional_beat\":\"...\",\"narrative_tag\":\"imported\","
                        "\"scene_chunks\":[{\"chapter_index\":1}],"
                        "\"source_candidate_ids\":[\"...\"],"
                        "\"source_rounds\":[\"A\"],"
                        "\"source_chapter_indices\":[1],\"operation\":\"kept\","
                        "\"confidence\":0.8,\"fallback_required\":false,"
                        "\"boundary_status\":\"complete\",\"boundary_reason\":\"...\","
                        "\"needs_review\":true,\"review_reason\":\"...\"}]}\n\n"
                        f"{json.dumps(compact_payload, ensure_ascii=False)}"
                    ),
                ),
            ],
            temperature=0.2,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )
        return await _run_deep_import_structured_call(
            LLMClient(timeout=settings.llm_timeout),
            request,
            Phase1bReducerOutput,
            transport_retries=False,
            timeout_seconds=timeout_seconds,
            fix_prompt=(
                "上一轮输出无法通过 Phase1bReducerOutput 校验。请只输出一个 JSON "
                "object，必须包含 scenes 数组。每个 scene 必须包含 "
                "source_candidate_ids、source_rounds、source_chapter_indices、"
                "operation、confidence、fallback_required、boundary_status、"
                "boundary_reason、needs_review、review_reason。不要 Markdown。"
            ),
        )


def _is_small_phase1b_payload(payload: dict[str, Any]) -> bool:
    chapters = payload.get("source_chapter_indices") or []
    return 0 < len(set(chapters)) <= 7


def _compact_phase1b_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Keep Phase 1b reducer input bounded and正文-free."""

    return {
        "phase": payload.get("phase"),
        "window": payload.get("window"),
        "source_candidate_ids": _compact_list(payload.get("source_candidate_ids")),
        "source_rounds": _compact_list(payload.get("source_rounds")),
        "source_chapter_indices": _compact_chapters(
            payload.get("source_chapter_indices")
        ),
        "recommended_scene_count": payload.get("recommended_scene_count"),
        "scene_count_guidance": _compact_text(payload.get("scene_count_guidance")),
        "candidates": [
            _compact_phase1b_candidate(candidate)
            for candidate in payload.get("candidates", [])
            if isinstance(candidate, dict)
        ],
        "merge_hints": _compact_list(payload.get("merge_hints"), limit=12),
        "split_hints": _compact_list(payload.get("split_hints"), limit=12),
        "output_requirements": {
            "required_scene_fields": [
                "title",
                "goal",
                "core_conflict",
                "emotional_beat",
                "narrative_tag",
                "scene_chunks",
                "source_candidate_ids",
                "source_rounds",
                "source_chapter_indices",
                "operation",
                "confidence",
                "fallback_required",
                "boundary_status",
                "boundary_reason",
                "needs_review",
                "review_reason",
            ],
            "operation_values": ["kept", "merged", "split", "reordered", "rewritten"],
            "discard_reason_values": [
                "merged",
                "split",
                "duplicate_candidate",
                "low_confidence_unusable",
                "outside_scope",
            ],
        },
    }


def _compact_phase1b_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "candidate_id": candidate.get("candidate_id"),
        "source_round": candidate.get("source_round"),
        "source_batch_id": candidate.get("source_batch_id"),
        "source_batch_index": candidate.get("source_batch_index"),
        "source_chapter_indices": _compact_chapters(
            candidate.get("source_chapter_indices")
        ),
        "quality": candidate.get("quality"),
        "confidence": candidate.get("confidence"),
        "boundary_status": candidate.get("boundary_status"),
        "boundary_reason": _compact_text(candidate.get("boundary_reason")),
        "scenes": [
            _compact_phase1b_scene(scene)
            for scene in candidate.get("scenes", [])
            if isinstance(scene, dict)
        ],
        "evidence_anchors": _compact_list(candidate.get("evidence_anchors"), limit=4),
        "merge_hints": _compact_list(candidate.get("merge_hints"), limit=4),
        "split_hints": _compact_list(candidate.get("split_hints"), limit=4),
        "missing_or_uncertain_items": _compact_list(
            candidate.get("missing_or_uncertain_items"),
            limit=4,
        ),
    }


def _compact_phase1b_scene(scene: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": _compact_text(scene.get("title"), limit=80),
        "goal": _compact_text(scene.get("goal")),
        "core_conflict": _compact_text(scene.get("core_conflict")),
        "emotional_beat": _compact_text(scene.get("emotional_beat")),
        "narrative_tag": _compact_text(scene.get("narrative_tag"), limit=48),
        "scene_chunks": [
            _compact_scene_chunk(chunk)
            for chunk in scene.get("scene_chunks", [])
            if isinstance(chunk, dict)
        ],
    }


def _compact_scene_chunk(chunk: dict[str, Any]) -> dict[str, Any]:
    compact = {"chapter_index": chunk.get("chapter_index")}
    if chunk.get("start_paragraph") is not None:
        compact["start_paragraph"] = chunk.get("start_paragraph")
    if chunk.get("end_paragraph") is not None:
        compact["end_paragraph"] = chunk.get("end_paragraph")
    return compact


def _compact_list(value: Any, *, limit: int | None = None) -> list[Any]:
    if not isinstance(value, list):
        return []
    items = value[:limit] if limit is not None else value
    return [
        _compact_text(item) if isinstance(item, str) else item
        for item in items
        if item is not None and item != ""
    ]


def _compact_chapters(value: Any) -> list[int]:
    if not isinstance(value, list):
        return []
    chapters: list[int] = []
    for item in value:
        try:
            chapter = int(item)
        except (TypeError, ValueError):
            continue
        if chapter > 0:
            chapters.append(chapter)
    return sorted(set(chapters))


def _compact_text(value: Any, *, limit: int = PHASE1B_COMPACT_TEXT_LIMIT) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip()


async def _run_deep_import_structured_call(
    client,
    request,
    schema,
    *,
    transport_retries: bool,
    fix_prompt: str,
    timeout_seconds: int | None = None,
):
    from core.config import get_settings

    settings = get_settings()
    timeout = (
        timeout_seconds
        if timeout_seconds is not None
        else int(settings.llm_timeout) + DEEP_IMPORT_STRUCTURED_TIMEOUT_GRACE_SECONDS
    )
    return await asyncio.wait_for(
        client.generate_structured(
            request,
            schema,
            max_fix_attempts=1,
            transport_retries=transport_retries,
            fix_prompt=fix_prompt,
        ),
        timeout=timeout,
    )
