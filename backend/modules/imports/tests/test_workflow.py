"""深度导入工作流测试

测试 DeepImportWorkflow 编排逻辑和各步骤状态转换。
候选管理已移除，深度导入全自动执行三步。
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest

from modules.imports.workflow import DeepImportWorkflow
from modules.imports.workflow_schemas import DeepImportProgress, DeepImportStep


class TestDeepImportSchema:
    """测试深度导入进度数据结构"""

    def test_default_progress(self):
        p = DeepImportProgress()
        assert p.phase == "pending"
        assert p.total_steps == 3
        assert p.completed_steps == []
        assert p.current_step is None
        assert p.message == ""

    def test_progress_with_values(self):
        p = DeepImportProgress(
            phase="running",
            completed_steps=[],
            message="正在抽取世界对象",
        )
        assert p.phase == "running"
        assert p.completed_steps == []
        assert p.message == "正在抽取世界对象"

    def test_step_enum_values(self):
        assert DeepImportStep.scene_segmentation.value == "scene_segmentation"
        assert DeepImportStep.entity_extraction.value == "entity_extraction"
        assert DeepImportStep.structure_analysis.value == "structure_analysis"


class TestDeepImportWorkflowAutoRun:
    """测试全自动三步流程"""

    @pytest.mark.asyncio
    async def test_pending_to_done(self):
        """pending 直接跑完三步到达 done"""
        workflow = DeepImportWorkflow()
        progress = DeepImportProgress()

        workflow._segment_scenes = AsyncMock(return_value={
            "total_scenes": 5, "failed_batches": [], "degraded": False,
        })
        workflow._extract_entities_by_scene = AsyncMock(return_value={
            "total_created": 3, "total_deltas": 2,
        })
        workflow._analyze_structure = AsyncMock(return_value={
            "total_threads": 2, "total_arcs": 4,
            "threads": [{"id": "1", "name": "主线"}],
            "arcs": [{"id": "1", "title": "第一卷"}],
            "extra_sections": {},
        })

        result = await workflow.run_step(
            db=None, novel_id=str(uuid.uuid4()),
            start_chapter=1, end_chapter=3,
            progress=progress,
        )

        assert result.phase == "done"
        assert DeepImportStep.scene_segmentation.value in result.completed_steps
        assert DeepImportStep.entity_extraction.value in result.completed_steps
        assert DeepImportStep.structure_analysis.value in result.completed_steps
        assert "5 个 Scene" in result.message
        assert "3 个实体" in result.message
        assert "2 条剧情线" in result.message
        assert "4 个篇章纲" in result.message

    @pytest.mark.asyncio
    async def test_run_step_emits_phase_progress_updates(self):
        """运行中应暴露可轮询的阶段进度，而不是只在任务完成后写最终结果。"""
        workflow = DeepImportWorkflow()
        progress = DeepImportProgress()
        emitted: list[tuple[float, str, str | None, list[str]]] = []

        workflow._segment_scenes = AsyncMock(return_value={
            "total_scenes": 5, "failed_batches": [], "degraded": False,
        })
        workflow._extract_entities_by_scene = AsyncMock(return_value={
            "total_created": 3, "total_deltas": 2,
        })
        workflow._analyze_structure = AsyncMock(return_value={
            "total_threads": 2, "total_arcs": 4,
            "threads": [], "arcs": [], "extra_sections": {},
        })

        async def _on_progress(updated: DeepImportProgress, progress_value: float):
            emitted.append((
                progress_value,
                updated.phase,
                updated.current_step.value if updated.current_step else None,
                list(updated.completed_steps),
            ))

        await workflow.run_step(
            db=None,
            novel_id=str(uuid.uuid4()),
            start_chapter=1,
            end_chapter=3,
            progress=progress,
            on_progress=_on_progress,
        )

        assert emitted == [
            (0.0, "running", "scene_segmentation", []),
            (0.4, "running", "entity_extraction", ["scene_segmentation"]),
            (
                0.8,
                "running",
                "structure_analysis",
                ["scene_segmentation", "entity_extraction"],
            ),
            (
                1.0,
                "done",
                None,
                ["scene_segmentation", "entity_extraction", "structure_analysis"],
            ),
        ]

    @pytest.mark.asyncio
    async def test_rejects_non_pending_phase(self):
        workflow = DeepImportWorkflow()
        progress = DeepImportProgress(phase="running")

        with pytest.raises(ValueError, match="无法处理当前进度状态"):
            await workflow.run_step(
                db=None, novel_id=str(uuid.uuid4()),
                start_chapter=1, end_chapter=3,
                progress=progress,
            )

    @pytest.mark.asyncio
    async def test_rejects_done_state(self):
        """already done 的状态不应该重新执行"""
        workflow = DeepImportWorkflow()
        progress = DeepImportProgress(phase="done")

        with pytest.raises(ValueError, match="无法处理当前进度状态"):
            await workflow.run_step(
                db=None, novel_id=str(uuid.uuid4()),
                start_chapter=1, end_chapter=3,
                progress=progress,
            )

    @pytest.mark.asyncio
    async def test_rejects_failed_state(self):
        """不会自动重试 failed 状态"""
        workflow = DeepImportWorkflow()
        progress = DeepImportProgress(phase="failed")

        with pytest.raises(ValueError, match="无法处理当前进度状态"):
            await workflow.run_step(
                db=None, novel_id=str(uuid.uuid4()),
                start_chapter=1, end_chapter=3,
                progress=progress,
            )
