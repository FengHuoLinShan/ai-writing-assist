"""深度导入工作流测试

测试 DeepImportWorkflow 编排逻辑和各步骤状态转换。
候选管理已移除，深度导入全自动执行三步。
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, Mock, patch

import pytest

from modules.imports.orchestrator import DeepImportOrchestrator
from modules.imports.scene_entity_extraction import SceneEntityExtractionService
from modules.imports.scene_segmentation import SceneSegmentationService
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

        workflow._segment_scenes = AsyncMock(
            return_value={
                "total_scenes": 5,
                "failed_batches": [],
                "degraded": False,
            }
        )
        workflow._extract_entities_by_scene = AsyncMock(
            return_value={
                "total_created": 3,
                "total_deltas": 2,
            }
        )
        workflow._analyze_structure = AsyncMock(
            return_value={
                "total_threads": 2,
                "total_arcs": 4,
                "threads": [{"id": "1", "name": "主线"}],
                "arcs": [{"id": "1", "title": "第一卷"}],
                "extra_sections": {},
            }
        )

        result = await workflow.run_step(
            db=None,
            novel_id=str(uuid.uuid4()),
            start_chapter=1,
            end_chapter=3,
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

        workflow._segment_scenes = AsyncMock(
            return_value={
                "total_scenes": 5,
                "failed_batches": [],
                "degraded": False,
            }
        )
        workflow._extract_entities_by_scene = AsyncMock(
            return_value={
                "total_created": 3,
                "total_deltas": 2,
            }
        )
        workflow._analyze_structure = AsyncMock(
            return_value={
                "total_threads": 2,
                "total_arcs": 4,
                "threads": [],
                "arcs": [],
                "extra_sections": {},
            }
        )

        async def _on_progress(updated: DeepImportProgress, progress_value: float):
            emitted.append(
                (
                    progress_value,
                    updated.phase,
                    updated.current_step.value if updated.current_step else None,
                    list(updated.completed_steps),
                )
            )

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
                db=None,
                novel_id=str(uuid.uuid4()),
                start_chapter=1,
                end_chapter=3,
                progress=progress,
            )

    @pytest.mark.asyncio
    async def test_rejects_done_state(self):
        """already done 的状态不应该重新执行"""
        workflow = DeepImportWorkflow()
        progress = DeepImportProgress(phase="done")

        with pytest.raises(ValueError, match="无法处理当前进度状态"):
            await workflow.run_step(
                db=None,
                novel_id=str(uuid.uuid4()),
                start_chapter=1,
                end_chapter=3,
                progress=progress,
            )

    @pytest.mark.asyncio
    async def test_rejects_failed_state(self):
        """不会自动重试 failed 状态"""
        workflow = DeepImportWorkflow()
        progress = DeepImportProgress(phase="failed")

        with pytest.raises(ValueError, match="无法处理当前进度状态"):
            await workflow.run_step(
                db=None,
                novel_id=str(uuid.uuid4()),
                start_chapter=1,
                end_chapter=3,
                progress=progress,
            )


class TestDeepImportOrchestrator:
    """测试深度导入入口编排器保持 facade/task 返回契约。"""

    @pytest.mark.asyncio
    async def test_start_returns_confirmation_without_enqueue_when_duplicates_exist(self):
        orchestrator = DeepImportOrchestrator()
        orchestrator._check_duplicate_import = AsyncMock(return_value="已有派生数据")
        orchestrator._deprecate_derived_data = AsyncMock()
        orchestrator._enqueue_deep_import = AsyncMock()

        result = await orchestrator.start(
            db=AsyncMock(),
            novel_id=str(uuid.uuid4()),
            start_chapter=1,
            end_chapter=3,
            force=False,
        )

        assert result == {
            "workflow_id": None,
            "task_id": None,
            "status": "requires_confirmation",
            "requires_confirmation": True,
            "warning": "已有派生数据",
            "message": "已有派生数据",
        }
        orchestrator._deprecate_derived_data.assert_not_awaited()
        orchestrator._enqueue_deep_import.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_start_force_deprecates_then_enqueues(self):
        orchestrator = DeepImportOrchestrator()
        task_id = uuid.uuid4()
        db = AsyncMock()
        orchestrator._check_duplicate_import = AsyncMock(return_value="已有派生数据")
        orchestrator._deprecate_derived_data = AsyncMock(
            return_value={"deprecated_scenes": 1, "deprecated_entities": 2}
        )
        orchestrator._enqueue_deep_import = Mock(return_value=task_id)

        result = await orchestrator.start(
            db=db,
            novel_id="novel-1",
            start_chapter=1,
            end_chapter=3,
            force=True,
        )

        orchestrator._deprecate_derived_data.assert_awaited_once_with(db, "novel-1", 1, 3)
        orchestrator._enqueue_deep_import.assert_called_once_with(db, "novel-1", 1, 3)
        db.flush.assert_awaited_once()
        assert result == {
            "workflow_id": str(task_id),
            "task_id": str(task_id),
            "status": "pending",
            "requires_confirmation": False,
            "message": "深度导入任务已提交（第1-3章）",
        }

    @pytest.mark.asyncio
    async def test_run_task_returns_task_result_contract(self):
        orchestrator = DeepImportOrchestrator()
        progress = DeepImportProgress(
            phase="done",
            completed_steps=[
                DeepImportStep.scene_segmentation.value,
                DeepImportStep.entity_extraction.value,
                DeepImportStep.structure_analysis.value,
            ],
            message="完成",
            degraded=True,
            degraded_batches=[2],
        )
        orchestrator.workflow.run_step = AsyncMock(return_value=progress)
        task = Mock(
            id=uuid.uuid4(),
            meta={"novel_id": "n1", "start_chapter": 2, "end_chapter": 4},
        )
        task.update_progress = Mock()
        db = AsyncMock()

        result = await orchestrator.run_task(db, task)

        assert result == {
            "phase": "done",
            "current_step": None,
            "completed_steps": [
                "scene_segmentation",
                "entity_extraction",
                "structure_analysis",
            ],
            "message": "完成",
            "degraded": True,
            "degraded_batches": [2],
        }

    @pytest.mark.asyncio
    async def test_run_task_defaults_missing_chapter_range(self):
        """任务 meta 未带章节范围时，orchestrator 使用 1-5 章默认范围。"""
        orchestrator = DeepImportOrchestrator()
        progress = DeepImportProgress(phase="done", message="完成")
        orchestrator.workflow.run_step = AsyncMock(return_value=progress)
        task = Mock(id=uuid.uuid4(), meta={"novel_id": "n1"})
        task.update_progress = Mock()
        db = AsyncMock()

        await orchestrator.run_task(db, task)

        _, kwargs = orchestrator.workflow.run_step.await_args
        assert kwargs["start_chapter"] == 1
        assert kwargs["end_chapter"] == 5


class TestSceneSegmentationProgress:
    """测试 Scene 切分服务的细粒度进度回调"""

    @pytest.mark.asyncio
    @patch("modules.outline.facade.create_scene", new_callable=AsyncMock)
    @patch("modules.outline.facade.get_next_scene_index", return_value=0)
    async def test_segment_chapters_reports_batch_progress(
        self,
        mock_get_next,
        mock_create_scene,
    ):
        service = SceneSegmentationService()
        service._load_chapters = AsyncMock(
            return_value=[
                {"chapter_index": i, "title": f"第{i}章", "content": "..."}
                for i in range(1, 7)
            ]
        )
        service._process_batch = AsyncMock(
            return_value=[
                {"title": "Scene", "scene_chunks": [{"chapter_index": 1}]},
            ]
        )

        progress_calls = []

        async def on_progress(completed, total):
            progress_calls.append((completed, total))

        db = AsyncMock()
        result = await service.segment_chapters(
            db=db,
            novel_id=str(uuid.uuid4()),
            start_chapter=1,
            end_chapter=6,
            on_batch_progress=on_progress,
        )

        assert progress_calls[0] == (0, 2)
        assert progress_calls[1] == (1, 2)
        assert progress_calls[2] == (2, 2)
        assert result["total_scenes"] == 2
        assert mock_create_scene.await_count == 2


class TestSceneEntityExtractionProgress:
    """测试实体提取服务的细粒度进度回调"""

    @pytest.mark.asyncio
    @patch(
        "modules.world.facade.get_world_context",
        new_callable=AsyncMock,
    )
    async def test_extract_by_scenes_reports_scene_progress(self, mock_ctx):
        mock_ctx.return_value = Mock(entities=[])

        service = SceneEntityExtractionService()
        service._get_scenes = AsyncMock(
            return_value=[
                Mock(scene_index=1, chapter_ids=["1"]),
                Mock(scene_index=2, chapter_ids=["2"]),
            ]
        )
        service._process_scene = AsyncMock(
            return_value={
                "created": 1,
                "relations": 0,
                "deltas": 0,
                "updated_context": "",
                "updated_memory": [],
            }
        )

        progress_calls = []

        async def on_progress(completed, total):
            progress_calls.append((completed, total))

        db = AsyncMock()
        result = await service.extract_by_scenes(
            db=db,
            novel_id=str(uuid.uuid4()),
            on_scene_progress=on_progress,
        )

        assert progress_calls == [(0, 2), (1, 2), (2, 2)]
        assert result["total_scenes"] == 2
        assert "total_relations" in result


class TestHandleDeepImportTaskResult:
    """测试 task handler 在阶段边界更新 task.result"""

    @pytest.mark.asyncio
    async def test_handle_deep_import_updates_task_result_at_phase_boundaries(self):
        from modules.imports.tasks import handle_deep_import

        class FakeTask:
            def __init__(self):
                self.id = uuid.uuid4()
                self.meta = {
                    "novel_id": str(uuid.uuid4()),
                    "start_chapter": 1,
                    "end_chapter": 3,
                }
                self.result = {}
                self.progress_values = []

            def update_progress(self, value):
                self.progress_values.append(value)

        task = FakeTask()
        mock_db = AsyncMock()

        with (
            patch.object(
                DeepImportWorkflow,
                "_segment_scenes",
                new_callable=AsyncMock,
                return_value={
                    "total_scenes": 5,
                    "failed_batches": [],
                    "degraded": False,
                },
            ),
            patch.object(
                DeepImportWorkflow,
                "_extract_entities_by_scene",
                new_callable=AsyncMock,
                return_value={"total_created": 3, "total_deltas": 2},
            ),
            patch.object(
                DeepImportWorkflow,
                "_analyze_structure",
                new_callable=AsyncMock,
                return_value={"total_threads": 2, "total_arcs": 4},
            ),
        ):
            result = await handle_deep_import(db=mock_db, task=task)

        assert result["phase"] == "done"
        assert task.result["phase"] == "done"
        assert DeepImportStep.scene_segmentation.value in task.result["completed_steps"]
        assert DeepImportStep.entity_extraction.value in task.result["completed_steps"]
        assert DeepImportStep.structure_analysis.value in task.result["completed_steps"]
        assert len(task.progress_values) >= 4
        assert 1.0 in task.progress_values
