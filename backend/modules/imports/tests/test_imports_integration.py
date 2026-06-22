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
from tests.utils import (
    _mock_analyze,
    _mock_extract,
    _mock_extract_fail,
    _mock_segment,
)


class TestSceneSegmentationIntegration:
    """Phase 1: Scene 切分集成测试"""

    async def test_segmentation_no_chapters(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
    ) -> None:
        """无章节时返回空结果"""
        from modules.imports.scene_segmentation import SceneSegmentationService

        service = SceneSegmentationService()
        result = await service.segment_chapters(
            db_session,
            sample_novel_id,
            start_chapter=1,
            end_chapter=1,
        )
        assert result["total_scenes"] == 0
        assert not result["degraded"]


class TestDeepImportWorkflowNewPipeline:
    """新三阶段流水线集成测试"""

    async def test_workflow_runs_3_phases(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
    ) -> None:
        """DeepImportWorkflow 应按 segmentation → extraction → analysis 顺序执行"""
        from modules.imports.workflow import DeepImportWorkflow

        workflow = DeepImportWorkflow()
        progress = DeepImportProgress()

        with (
            mock.patch.object(workflow, "_segment_scenes", side_effect=_mock_segment),
            mock.patch.object(
                workflow, "_extract_entities_by_scene", side_effect=_mock_extract
            ),
            mock.patch.object(workflow, "_analyze_structure", side_effect=_mock_analyze),
        ):
            result = await workflow.run_step(
                db_session,
                sample_novel_id,
                start_chapter=1,
                end_chapter=5,
                progress=progress,
            )

        assert result.phase == "done"
        assert len(result.completed_steps) == 3
        assert DeepImportStep.scene_segmentation.value in result.completed_steps
        assert DeepImportStep.entity_extraction.value in result.completed_steps
        assert DeepImportStep.structure_analysis.value in result.completed_steps

    async def test_workflow_handles_phase2_failure(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
    ) -> None:
        """Phase 2 失败时不阻塞 Phase 3"""
        from modules.imports.workflow import DeepImportWorkflow

        workflow = DeepImportWorkflow()
        progress = DeepImportProgress()

        with (
            mock.patch.object(workflow, "_segment_scenes", side_effect=_mock_segment),
            mock.patch.object(
                workflow, "_extract_entities_by_scene", side_effect=_mock_extract_fail
            ),
            mock.patch.object(workflow, "_analyze_structure", side_effect=_mock_analyze),
        ):
            result = await workflow.run_step(
                db_session,
                sample_novel_id,
                start_chapter=1,
                end_chapter=3,
                progress=progress,
            )

        assert result.phase == "done"
        assert len(result.completed_steps) == 3


@pytest.fixture
async def novel_with_drafts(db_session: AsyncSession):
    """创建一个项目并在第 1、2 章写入 draft，供集成测试使用。"""
    from modules.project.schemas import ProjectCreate
    from modules.project.services import ProjectService
    from modules.writing.facade import create_draft_only

    project = await ProjectService().create_project(
        db_session,
        ProjectCreate(title="Deep Import Test", language="zh"),
    )
    novel_id = str(project.id)
    await create_draft_only(
        db_session, novel_id, chapter_index=1, title="第一章", content="第一章内容。"
    )
    await create_draft_only(
        db_session, novel_id, chapter_index=2, title="第二章", content="第二章内容。"
    )
    await create_draft_only(
        db_session, novel_id, chapter_index=3, title="第三章", content="第三章内容。"
    )
    return novel_id


class TestSceneSegmentationDegradation:
    """Phase 1 失败降级路径集成测试。"""

    async def test_batch_failure_degrades_to_mechanical(
        self,
        db_session: AsyncSession,
        novel_with_drafts: str,
    ) -> None:
        """LLM 全部失败后，应逐章降级并最终使用机械分章。"""
        from modules.imports.scene_segmentation import SceneSegmentationService

        service = SceneSegmentationService()
        with (
            mock.patch.object(
                service,
                "_process_batch",
                side_effect=RuntimeError("LLM batch failure"),
            ),
            mock.patch.object(
                service,
                "_process_batch_single_chapter",
                side_effect=RuntimeError("single chapter failure"),
            ),
        ):
            result = await service.segment_chapters(
                db_session,
                novel_with_drafts,
                start_chapter=1,
                end_chapter=3,
            )

        assert result["total_scenes"] == 3
        assert result["degraded"] is True
        assert result["failed_batches"] == []

        from modules.outline.facade import get_scenes_by_novel

        scenes = await get_scenes_by_novel(
            db_session, novel_with_drafts, status_filter=["draft"]
        )
        assert len(scenes) == 3
        assert all(s["source"] == "deep_import" for s in scenes)


class TestDuplicateImportAndDeprecation:
    """重复导入检测与 force deprecation 集成测试。"""

    async def test_duplicate_import_requires_confirmation(
        self,
        db_session: AsyncSession,
        novel_with_drafts: str,
    ) -> None:
        from modules.imports.facade import start_deep_import
        from modules.outline.facade import create_scene

        await create_scene(
            db_session,
            novel_with_drafts,
            {
                "scene_index": 0,
                "title": "old scene",
                "narrative_tag": "draft",
                "source": "deep_import",
                "scene_chunks": [{"chapter_index": 1}],
                "chapter_ids": ["1"],
                "status": "draft",
            },
        )

        result = await start_deep_import(db_session, novel_with_drafts, 1, 1)
        assert result["requires_confirmation"] is True
        assert "workflow_id" in result

    async def test_force_import_deprecates_old_data(
        self,
        db_session: AsyncSession,
        novel_with_drafts: str,
    ) -> None:
        from modules.imports.facade import start_deep_import
        from modules.outline.facade import create_scene
        from modules.world.facade import create_entity

        await create_scene(
            db_session,
            novel_with_drafts,
            {
                "scene_index": 0,
                "title": "old scene",
                "narrative_tag": "draft",
                "source": "deep_import",
                "scene_chunks": [{"chapter_index": 1}],
                "chapter_ids": ["1"],
                "status": "draft",
            },
        )
        await create_entity(
            db_session,
            novel_with_drafts,
            {
                "name": "OldEntity",
                "entity_type": "character",
                "content_json": {
                    "_meta": {
                        "auto_ingested": True,
                        "source_chapter_index": 1,
                    }
                },
                "status": "canonical",
            },
        )

        result = await start_deep_import(db_session, novel_with_drafts, 1, 1, force=True)
        assert result["requires_confirmation"] is False
        assert "task_id" in result

        from sqlalchemy import select

        from modules.outline.models import Scene
        from shared.utils import parse_uuid

        nid = parse_uuid(novel_with_drafts, "novel_id")
        stmt = select(Scene).where(Scene.novel_id == nid, Scene.status == "deprecated")
        result = await db_session.execute(stmt)
        scenes = result.scalars().all()
        assert any(s.title == "old scene" for s in scenes)

        from modules.world.models import CoreEntity

        stmt = select(CoreEntity).where(
            CoreEntity.novel_id == nid, CoreEntity.name == "OldEntity"
        )
        result = await db_session.execute(stmt)
        old = result.scalar_one_or_none()
        assert old is not None
        assert old.status == "deprecated"

    async def test_duplicate_import_novel_isolation(
        self,
        db_session: AsyncSession,
        novel_with_drafts: str,
    ) -> None:
        """novel A 的派生数据不应影响 novel B 的重复检测。"""
        from modules.imports.facade import start_deep_import
        from modules.outline.facade import create_scene
        from modules.project.schemas import ProjectCreate
        from modules.project.services import ProjectService

        other_project = await ProjectService().create_project(
            db_session,
            ProjectCreate(title="Other Novel", language="zh"),
        )
        other_novel_id = str(other_project.id)

        await create_scene(
            db_session,
            novel_with_drafts,
            {
                "scene_index": 0,
                "title": "A scene",
                "narrative_tag": "draft",
                "source": "deep_import",
                "scene_chunks": [{"chapter_index": 1}],
                "chapter_ids": ["1"],
                "status": "draft",
            },
        )

        result = await start_deep_import(db_session, other_novel_id, 1, 1)
        assert result["requires_confirmation"] is False
