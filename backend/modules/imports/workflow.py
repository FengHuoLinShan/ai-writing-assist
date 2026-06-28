"""Deep Import 工作流编排器

三阶段流水线：
  Phase 1: Scene 切分（并行批次）→ scenes 表
  Phase 2: 实体增量提取（串行按 Scene）→ core_entities + delta_log
  Phase 3: 剧情结构分析（单次）
  → plot_threads + outline_arcs + foreshadowing_plans + reveal_plans
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from core.config import get_settings
from core.container import get as _container_get
from modules.imports.workflow_schemas import DeepImportProgress, DeepImportStep

logger = logging.getLogger(__name__)


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

            # Phase 1: Scene 切分
            progress.current_step = DeepImportStep.scene_segmentation
            progress.message = "正在切分叙事 Scene..."
            await self._emit_progress(progress, 0.0, on_progress)

            async def _on_batch_progress(completed: int, total: int) -> None:
                progress.phase1_total_batches = total
                progress.phase1_completed_batches = completed
                value = 0.0 + 0.4 * (completed / total) if total else 0.0
                await self._emit_progress(progress, value, on_progress)

            phase1_result = await self._segment_scenes(
                db,
                novel_id,
                start_chapter,
                end_chapter,
                on_batch_progress=_on_batch_progress,
            )
            progress.completed_steps.append(DeepImportStep.scene_segmentation.value)
            progress.message = (
                f"Scene 切分完成，共创建 {phase1_result['total_scenes']} 个 Scene。"
            )
            if phase1_result.get("degraded"):
                progress.degraded = True
                failed_count = len(phase1_result.get("failed_batches", []))
                progress.message += f"（{failed_count} 个批次触发降级）"
                progress.phase_errors.append(
                    {
                        "phase": DeepImportStep.scene_segmentation.value,
                        "error_kind": "degraded_batches",
                        "message": f"{failed_count} 个批次触发降级",
                    }
                )

            # Phase 2: 实体增量提取
            progress.current_step = DeepImportStep.entity_extraction
            progress.message = "正在按 Scene 提取世界对象..."
            await self._emit_progress(progress, 0.4, on_progress)

            async def _on_scene_progress(completed: int, total: int) -> None:
                progress.phase2_total_scenes = total
                progress.phase2_completed_scenes = completed
                value = 0.4 + 0.4 * (completed / total) if total else 0.4
                await self._emit_progress(progress, value, on_progress)

            phase2_failed = False
            try:
                phase2_result = await self._extract_entities_by_scene(
                    db,
                    novel_id,
                    workflow_id=workflow_id,
                    on_scene_progress=_on_scene_progress,
                )
                progress.completed_steps.append(DeepImportStep.entity_extraction.value)
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
            except Exception as exc:
                phase2_failed = True
                await self._rollback_after_phase_failure(db, "entity_extraction", exc)
                phase2_result = {
                    "total_created": 0,
                    "total_relations": 0,
                    "total_deltas": 0,
                    "error_kind": "phase_failed",
                    "error_message": str(exc)[:300],
                }
                progress.degraded = True
                progress.phase_errors.append(
                    {
                        "phase": DeepImportStep.entity_extraction.value,
                        "error_kind": "phase_failed",
                        "message": f"实体提取阶段失败，已继续后续阶段：{str(exc)[:180]}",
                    }
                )
                progress.message = "实体提取阶段失败，已降级继续结构分析。"
            if (
                not phase2_failed
                and phase1_result.get("total_scenes", 0) > 0
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

            # Phase 3: 剧情结构分析
            progress.current_step = DeepImportStep.structure_analysis
            progress.message = "正在生成剧情线、篇章纲、伏笔和揭示计划..."
            await self._emit_progress(progress, 0.8, on_progress)
            phase3_result = await self._analyze_structure(
                db,
                novel_id,
                start_chapter,
                end_chapter,
            )
            progress.completed_steps.append(DeepImportStep.structure_analysis.value)
            if phase1_result.get("total_scenes", 0) > 0 and (
                phase3_result.get("total_threads", 0) <= 0
                and phase3_result.get("total_arcs", 0) <= 0
            ):
                progress.degraded = True
                progress.phase_errors.append(
                    {
                        "phase": DeepImportStep.structure_analysis.value,
                        "error_kind": phase3_result.get("error_kind", "empty_output"),
                        "message": "剧情结构阶段未生成剧情线或篇章纲",
                    }
                )

            progress.current_step = None
            progress.phase = "done"
            progress.quality_status = "partial" if progress.degraded else "complete"
            progress.message = (
                f"深度导入完成！"
                f"共 {phase1_result.get('total_scenes', 0)} 个 Scene，"
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
    async def _emit_progress(
        progress: DeepImportProgress,
        progress_value: float,
        on_progress: Callable[[DeepImportProgress, float], Awaitable[None]] | None,
    ) -> None:
        if on_progress is not None:
            await on_progress(progress, progress_value)

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
    ) -> dict[str, Any]:
        try:
            handler = _container_get("world.run_scene_entity_extraction")
            result = await handler(
                db,
                novel_id=novel_id,
                workflow_id=workflow_id,
                on_scene_progress=on_scene_progress,
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
    ) -> dict[str, Any]:
        _generate = _container_get("outline.generate_structure")
        try:
            result = await _generate(
                db,
                novel_id,
                start_chapter=start_chapter,
                end_chapter=end_chapter,
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
