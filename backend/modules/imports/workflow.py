"""Deep Import 工作流编排器

三阶段流水线：
  Phase 1: Scene 切分（并行批次）→ scenes 表
  Phase 2: 实体增量提取（串行按 Scene）→ core_entities + delta_log
  Phase 3: 剧情结构分析（单次）
  → plot_threads + outline_arcs + foreshadowing_plans + reveal_plans
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

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
    ) -> DeepImportProgress:
        if progress.phase == "pending":
            progress.phase = "running"

            # Phase 1: Scene 切分
            progress.current_step = DeepImportStep.scene_segmentation
            progress.message = "正在切分叙事 Scene..."
            phase1_result = await self._segment_scenes(
                db,
                novel_id,
                start_chapter,
                end_chapter,
            )
            progress.completed_steps.append(DeepImportStep.scene_segmentation.value)
            progress.message = (
                f"Scene 切分完成，共创建 {phase1_result['total_scenes']} 个 Scene。"
            )
            if phase1_result.get("degraded"):
                progress.degraded = True
                failed_count = len(phase1_result.get("failed_batches", []))
                progress.message += f"（{failed_count} 个批次触发降级）"

            # Phase 2: 实体增量提取
            progress.current_step = DeepImportStep.entity_extraction
            progress.message = "正在按 Scene 提取世界对象..."
            phase2_result = await self._extract_entities_by_scene(
                db,
                novel_id,
            )
            progress.completed_steps.append(DeepImportStep.entity_extraction.value)
            progress.message = (
                f"实体提取完成，共创建 {phase2_result.get('total_created', 0)} 个实体，"
                f"记录 {phase2_result.get('total_deltas', 0)} 条变更。"
            )

            # Phase 3: 剧情结构分析
            progress.current_step = DeepImportStep.structure_analysis
            progress.message = "正在生成剧情线、篇章纲、伏笔和揭示计划..."
            phase3_result = await self._analyze_structure(
                db,
                novel_id,
                start_chapter,
                end_chapter,
            )
            progress.completed_steps.append(DeepImportStep.structure_analysis.value)

            progress.current_step = None
            progress.phase = "done"
            progress.message = (
                f"深度导入完成！"
                f"共 {phase1_result.get('total_scenes', 0)} 个 Scene，"
                f"{phase2_result.get('total_created', 0)} 个实体，"
                f"{phase3_result.get('total_threads', 0)} 条剧情线，"
                f"{phase3_result.get('total_arcs', 0)} 个篇章纲。"
            )

        else:
            raise ValueError(f"无法处理当前进度状态: {progress.phase}")

        return progress

    # ------------------------------------------------------------------
    # Phase 1: Scene 切分
    # ------------------------------------------------------------------

    async def _segment_scenes(
        self,
        db: AsyncSession,
        novel_id: str,
        start_chapter: int,
        end_chapter: int,
    ) -> dict[str, Any]:
        from modules.imports.scene_segmentation import SceneSegmentationService

        service = SceneSegmentationService()
        result = await service.segment_chapters(
            db,
            novel_id,
            start_chapter,
            end_chapter,
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
    ) -> dict[str, Any]:
        try:
            handler = _container_get("world.run_scene_entity_extraction")
            result = await handler(db, novel_id=novel_id)
            return result
        except Exception as exc:
            logger.warning("Phase 2 entity extraction failed: %s", exc)
            return {"total_created": 0, "total_deltas": 0}

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
            }
