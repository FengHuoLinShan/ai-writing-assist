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
        assert DeepImportStep.extract_world.value == "extract_world"
        assert DeepImportStep.sync_characters.value == "sync_characters"
        assert DeepImportStep.generate_plot.value == "generate_plot"


class TestDeepImportWorkflowAutoRun:
    """测试全自动三步流程"""

    @pytest.mark.asyncio
    async def test_pending_to_done(self):
        """pending 直接跑完三步到达 done"""
        workflow = DeepImportWorkflow()
        progress = DeepImportProgress()

        workflow._extract_world = AsyncMock(return_value={
            "total_created": 5,
            "total_skipped": 2,
            "items": [],
        })
        workflow._sync_characters = AsyncMock(return_value={
            "total_synced": 3, "total_entities": 5,
        })
        workflow._generate_plot = AsyncMock(return_value={
            "total_threads": 2, "total_arcs": 4,
            "threads": [{"id": "1", "name": "主线"}],
            "arcs": [{"id": "1", "title": "第一卷"}],
        })

        result = await workflow.run_step(
            db=None, novel_id=str(uuid.uuid4()),
            start_chapter=1, end_chapter=3,
            progress=progress,
        )

        assert result.phase == "done"
        assert DeepImportStep.extract_world.value in result.completed_steps
        assert DeepImportStep.sync_characters.value in result.completed_steps
        assert DeepImportStep.generate_plot.value in result.completed_steps
        assert "3 个人物" in result.message
        assert "2 条剧情线" in result.message
        assert "4 个篇章纲" in result.message

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
