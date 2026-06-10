"""Deep Import 新三阶段流水线集成测试

Phase 1: Scene 切分
Phase 2: 实体增量提取
Phase 3: 剧情结构分析
"""

from __future__ import annotations

from unittest import mock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.imports.workflow_schemas import DeepImportProgress, DeepImportStep


class TestSceneSegmentationIntegration:
    """Phase 1: Scene 切分集成测试"""

    async def test_segmentation_no_chapters(
        self, db_session: AsyncSession, sample_novel_id: str,
    ) -> None:
        """无章节时返回空结果"""
        from modules.imports.scene_segmentation import SceneSegmentationService

        service = SceneSegmentationService()
        result = await service.segment_chapters(
            db_session, sample_novel_id, start_chapter=1, end_chapter=1,
        )
        assert result["total_scenes"] == 0
        assert not result["degraded"]


class TestDeepImportWorkflowNewPipeline:
    """新三阶段流水线集成测试"""

    async def test_workflow_runs_3_phases(
        self, db_session: AsyncSession, sample_novel_id: str,
    ) -> None:
        """DeepImportWorkflow 应按 scene_segmentation → entity_extraction → structure_analysis 顺序执行"""
        from modules.imports.workflow import DeepImportWorkflow

        workflow = DeepImportWorkflow()
        progress = DeepImportProgress()

        async def _mock_segment(db, novel_id, start_chapter, end_chapter):
            return {"total_scenes": 5, "failed_batches": [], "degraded": False}

        async def _mock_extract(db, novel_id):
            return {"total_created": 3, "total_deltas": 2}

        async def _mock_analyze(db, novel_id, start_chapter, end_chapter):
            return {
                "total_threads": 2, "total_arcs": 1,
                "threads": [], "arcs": [], "extra_sections": {},
            }

        with (
            mock.patch.object(workflow, "_segment_scenes", side_effect=_mock_segment),
            mock.patch.object(workflow, "_extract_entities_by_scene", side_effect=_mock_extract),
            mock.patch.object(workflow, "_analyze_structure", side_effect=_mock_analyze),
        ):
            result = await workflow.run_step(
                db_session, sample_novel_id,
                start_chapter=1, end_chapter=5,
                progress=progress,
            )

        assert result.phase == "done"
        assert len(result.completed_steps) == 3
        assert DeepImportStep.scene_segmentation.value in result.completed_steps
        assert DeepImportStep.entity_extraction.value in result.completed_steps
        assert DeepImportStep.structure_analysis.value in result.completed_steps

    async def test_workflow_handles_phase2_failure(
        self, db_session: AsyncSession, sample_novel_id: str,
    ) -> None:
        """Phase 2 失败时不阻塞 Phase 3"""
        from modules.imports.workflow import DeepImportWorkflow

        workflow = DeepImportWorkflow()
        progress = DeepImportProgress()

        async def _mock_segment(db, novel_id, start_chapter, end_chapter):
            return {"total_scenes": 3, "failed_batches": [], "degraded": False}

        async def _mock_extract_fail(db, novel_id):
            # 模拟 Phase 2 内部异常被捕获后返回空结果，不阻塞 Phase 3
            return {"total_created": 0, "total_deltas": 0}

        async def _mock_analyze(db, novel_id, start_chapter, end_chapter):
            return {
                "total_threads": 1, "total_arcs": 1,
                "threads": [], "arcs": [], "extra_sections": {},
            }

        with (
            mock.patch.object(workflow, "_segment_scenes", side_effect=_mock_segment),
            mock.patch.object(workflow, "_extract_entities_by_scene", side_effect=_mock_extract_fail),
            mock.patch.object(workflow, "_analyze_structure", side_effect=_mock_analyze),
        ):
            result = await workflow.run_step(
                db_session, sample_novel_id,
                start_chapter=1, end_chapter=3,
                progress=progress,
            )

        assert result.phase == "done"
        assert len(result.completed_steps) == 3
