"""深度导入工作流测试

测试 DeepImportWorkflow 编排逻辑和各步骤状态转换。
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from modules.imports.workflow import DeepImportWorkflow, count_pending_candidates
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
            phase="awaiting_review",
            completed_steps=["extract_world"],
            message="请审查候选",
        )
        assert p.phase == "awaiting_review"
        assert p.completed_steps == ["extract_world"]
        assert p.message == "请审查候选"

    def test_step_enum_values(self):
        assert DeepImportStep.extract_world.value == "extract_world"
        assert DeepImportStep.sync_characters.value == "sync_characters"
        assert DeepImportStep.generate_plot.value == "generate_plot"


class TestDeepImportWorkflowStep1:
    """测试 Step 1: 世界对象抽取"""

    @pytest.mark.asyncio
    async def test_pending_to_awaiting_review(self):
        workflow = DeepImportWorkflow()
        progress = DeepImportProgress()

        workflow._extract_world = AsyncMock(return_value={
            "total_created": 5,
            "total_skipped": 2,
            "items": [],
        })

        result = await workflow.run_step(
            db=None, novel_id=str(uuid.uuid4()),
            start_chapter=1, end_chapter=3,
            progress=progress,
        )

        assert result.phase == "awaiting_review"
        assert DeepImportStep.extract_world.value in result.completed_steps
        assert "5 个候选" in result.message

    @pytest.mark.asyncio
    async def test_rejects_non_pending_phase_for_step1(self):
        workflow = DeepImportWorkflow()
        progress = DeepImportProgress(phase="running")

        with pytest.raises(ValueError, match="无法处理当前进度状态"):
            await workflow.run_step(
                db=None, novel_id=str(uuid.uuid4()),
                start_chapter=1, end_chapter=3,
                progress=progress,
            )


class TestDeepImportWorkflowResume:
    """测试 Resume: Step 2 + 3"""

    @pytest.mark.asyncio
    async def test_resume_rejects_pending_candidates(self):
        workflow = DeepImportWorkflow()
        progress = DeepImportProgress(
            phase="awaiting_review",
            completed_steps=["extract_world"],
        )

        with patch("modules.imports.workflow.count_pending_candidates", return_value=3):
            with pytest.raises(ValueError, match="还有 3 个候选对象未处理"):
                await workflow.run_step(
                    db=None, novel_id=str(uuid.uuid4()),
                    start_chapter=1, end_chapter=3,
                    progress=progress,
                )

    @pytest.mark.asyncio
    async def test_resume_runs_sync_and_plot(self):
        workflow = DeepImportWorkflow()
        progress = DeepImportProgress(
            phase="awaiting_review",
            completed_steps=["extract_world"],
        )

        with (
            patch("modules.imports.workflow.count_pending_candidates", return_value=0),
        ):
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
        assert DeepImportStep.sync_characters.value in result.completed_steps
        assert DeepImportStep.generate_plot.value in result.completed_steps
        assert "3 个人物" in result.message
        assert "2 条剧情线" in result.message
        assert "4 个篇章纲" in result.message


class TestCountPendingCandidates:
    """测试模块级 count_pending_candidates 函数"""

    @pytest.mark.asyncio
    async def test_delegates_to_world_facade(self):
        """验证导入和函数签名"""
        assert callable(count_pending_candidates)
