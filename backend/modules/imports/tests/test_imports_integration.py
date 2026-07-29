"""Deep Import 新三阶段流水线集成测试

Phase 1: Scene 切分
Phase 2: 实体增量提取
Phase 3: 剧情结构分析
"""

from __future__ import annotations

import uuid
from unittest import mock

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from modules.imports.llm_schemas import SceneChunk
from modules.imports.scene_commit import SceneCommitResult
from modules.imports.scene_enrichment import Phase1bEnrichmentResult
from modules.imports.scene_fusion import FinalSceneCandidate
from modules.imports.scene_planning import ScenePlanResult, SceneWindowPlan
from modules.imports.scene_slicing import SceneSliceCandidate, SceneSlicingResult
from modules.imports.workflow_schemas import DeepImportProgress, DeepImportStep
from modules.project.models import Project
from tests.utils import (
    _mock_analyze,
    _mock_extract,
    _mock_extract_fail,
)


def _integration_phase0_plan(start_chapter: int, end_chapter: int) -> ScenePlanResult:
    chapters = [
        {
            "chapter_index": chapter,
            "title": f"第{chapter}章",
            "content": f"第{chapter}章正文。",
        }
        for chapter in range(start_chapter, end_chapter + 1)
    ]
    return ScenePlanResult(
        chapters=chapters,
        windows=[
            SceneWindowPlan(
                window_index=1,
                window_id=f"B0001-{start_chapter}-{end_chapter}",
                covered_start=start_chapter,
                covered_end=end_chapter,
                owned_start=start_chapter,
                owned_end=end_chapter,
                chapter_indices=list(range(start_chapter, end_chapter + 1)),
                owned_chapter_indices=list(range(start_chapter, end_chapter + 1)),
                input_chars=1000,
                max_tokens=13_000,
                batch_size=end_chapter - start_chapter + 1,
                overlap=0,
            )
        ],
        quality_stats={"total_batches": 1, "completed_batches": 1},
    )


def _integration_phase1a_slicing(
    start_chapter: int,
    end_chapter: int,
) -> SceneSlicingResult:
    candidates = [
        SceneSliceCandidate(
            candidate_id=f"phase1a-{chapter}",
            source_window_id="B0001",
            source_window_index=1,
            title=f"第{chapter}章 Scene",
            goal="推进章节目标。",
            core_conflict="章节冲突。",
            start_chapter=chapter,
            end_chapter=chapter,
            boundary_status="complete",
            source_chapter_indices=[chapter],
        )
        for chapter in range(start_chapter, end_chapter + 1)
    ]
    return SceneSlicingResult(
        candidates=candidates,
        quality_stats={
            "total_batches": 1,
            "completed_batches": 1,
            "success": 1,
            "failed": 0,
            "fallback_count": 0,
            "scene_count": len(candidates),
        },
    )


def _integration_phase1b_enrichment(
    start_chapter: int,
    end_chapter: int,
) -> Phase1bEnrichmentResult:
    return Phase1bEnrichmentResult(
        candidates=[
            FinalSceneCandidate(
                phase="phase1b_enrichment",
                title=f"第{chapter}章 Scene",
                goal="推进章节目标。",
                core_conflict="章节冲突。",
                emotional_beat="稳定推进。",
                must_happen="保留章节事件。",
                must_not_happen="不得偏离原文。",
                narrative_tag="imported",
                scene_chunks=[SceneChunk(chapter_index=chapter)],
                source_candidate_ids=[f"phase1a-{chapter}"],
                source_rounds=["A"],
                source_chapter_indices=[chapter],
                operation="kept",
                confidence=0.8,
                fallback_required=False,
                boundary_status="complete",
                boundary_reason="integration test",
            )
            for chapter in range(start_chapter, end_chapter + 1)
        ],
        quality_stats={
            "total_windows": 1,
            "completed_windows": 1,
            "total_scenes": end_chapter - start_chapter + 1,
            "completed": end_chapter - start_chapter + 1,
            "failed": 0,
            "fallback_count": 0,
        },
    )


class TestDeepImportApiValidation:
    """Deep Import API should rely on typed request validation."""

    async def test_deep_import_force_string_false_is_not_truthy(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        from modules.imports import facade as imports_facade

        novel_id = uuid.uuid4()
        db_session.add(Project(id=novel_id, title="Deep import API validation"))
        await db_session.flush()

        async def fake_start(
            db,
            novel_id: str,
            start_chapter: int,
            end_chapter: int,
            *,
            force: bool,
            high_quality: bool,
            adoption_policy: str,
            authorization_confirmed: bool,
        ) -> dict:
            return {
                "novel_id": novel_id,
                "start_chapter": start_chapter,
                "end_chapter": end_chapter,
                "force": force,
                "high_quality": high_quality,
                "adoption_policy": adoption_policy,
                "authorization_confirmed": authorization_confirmed,
            }

        with mock.patch.object(
            imports_facade,
            "start_deep_import",
            autospec=True,
            side_effect=fake_start,
        ):
            resp = await async_client.post(
                "/api/imports/deep",
                json={
                    "novel_id": str(novel_id),
                    "start_chapter": 1,
                    "end_chapter": 2,
                    "force": "false",
                    "authorization_confirmed": True,
                },
            )

        assert resp.status_code == 201, resp.text
        assert resp.json()["force"] is False
        assert resp.json()["high_quality"] is False
        assert resp.json()["adoption_policy"] == "user_authorized_pipeline"
        assert resp.json()["authorization_confirmed"] is True

    async def test_deep_import_sync_route_is_not_public(
        self,
        async_client: AsyncClient,
    ) -> None:
        resp = await async_client.post(
            "/api/imports/deep/sync",
            json={
                "novel_id": "00000000-0000-0000-0000-000000000502",
                "start_chapter": 1,
                "end_chapter": 2,
            },
        )

        assert resp.status_code == 404


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
            mock.patch.object(
                workflow,
                "_run_phase0_plan",
                return_value=_integration_phase0_plan(1, 5),
                autospec=True,
            ),
            mock.patch.object(
                workflow,
                "_run_phase1a_scene_slicing",
                return_value=_integration_phase1a_slicing(1, 5),
                autospec=True,
            ),
            mock.patch.object(
                workflow,
                "_run_phase1b_enrichment",
                return_value=_integration_phase1b_enrichment(1, 5),
                autospec=True,
            ),
            mock.patch.object(
                workflow,
                "_commit_fused_scenes",
                return_value=SceneCommitResult(
                    created_count=5,
                    skipped_count=0,
                    conflict_count=0,
                    created_scene_ids=[f"scene-{index}" for index in range(5)],
                ),
                autospec=True,
            ),
            mock.patch.object(
                workflow,
                "_extract_entities_by_scene",
                side_effect=_mock_extract,
                autospec=True,
            ),
            mock.patch.object(
                workflow, "_analyze_structure", side_effect=_mock_analyze, autospec=True
            ),
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
            mock.patch.object(
                workflow,
                "_run_phase0_plan",
                return_value=_integration_phase0_plan(1, 3),
                autospec=True,
            ),
            mock.patch.object(
                workflow,
                "_run_phase1a_scene_slicing",
                return_value=_integration_phase1a_slicing(1, 3),
                autospec=True,
            ),
            mock.patch.object(
                workflow,
                "_run_phase1b_enrichment",
                return_value=_integration_phase1b_enrichment(1, 3),
                autospec=True,
            ),
            mock.patch.object(
                workflow,
                "_commit_fused_scenes",
                return_value=SceneCommitResult(
                    created_count=3,
                    skipped_count=0,
                    conflict_count=0,
                    created_scene_ids=[f"scene-{index}" for index in range(3)],
                ),
                autospec=True,
            ),
            mock.patch.object(
                workflow,
                "_extract_entities_by_scene",
                side_effect=_mock_extract_fail,
                autospec=True,
            ),
            mock.patch.object(
                workflow, "_analyze_structure", side_effect=_mock_analyze, autospec=True
            ),
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


@pytest_asyncio.fixture
async def novel_with_drafts(
    db_session: AsyncSession,
    account_llm_connection: dict,
):
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
                "structure_meta": {
                    "workflow_id": "wf-old",
                    "auto_ingested": True,
                },
                "status": "draft",
            },
        )

        task_result = await start_deep_import(
            db_session,
            novel_with_drafts,
            1,
            1,
            authorization_confirmed=True,
        )
        assert task_result["requires_confirmation"] is True
        assert "workflow_id" in task_result

    async def test_force_import_defers_scene_replacement_without_touching_entities(
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
                "structure_meta": {
                    "workflow_id": "wf-old",
                    "auto_ingested": True,
                },
                "status": "draft",
            },
        )
        manual_scene = await create_scene(
            db_session,
            novel_with_drafts,
            {
                "scene_index": 1,
                "title": "manual scene",
                "source": "manual",
                "scene_chunks": [{"chapter_index": 1}],
                "chapter_ids": ["1"],
                "status": "draft",
            },
        )
        unowned_import_scene = await create_scene(
            db_session,
            novel_with_drafts,
            {
                "scene_index": 2,
                "title": "unowned import scene",
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

        task_result = await start_deep_import(
            db_session,
            novel_with_drafts,
            1,
            1,
            force=True,
            authorization_confirmed=True,
        )
        assert task_result["requires_confirmation"] is False
        assert "task_id" in task_result

        from sqlalchemy import select

        from modules.outline.models import Scene
        from shared.utils import parse_uuid

        nid = parse_uuid(novel_with_drafts, "novel_id")
        stmt = select(Scene).where(Scene.novel_id == nid, Scene.title == "old scene")
        result = await db_session.execute(stmt)
        old_scene = result.scalar_one()
        assert old_scene.status == "draft"
        manual = await db_session.get(Scene, uuid.UUID(manual_scene["id"]))
        assert manual is not None
        assert manual.status == "draft"
        unowned = await db_session.get(
            Scene,
            uuid.UUID(unowned_import_scene["id"]),
        )
        assert unowned is not None
        assert unowned.status == "draft"

        from modules.world.models import CoreEntity

        stmt = select(CoreEntity).where(
            CoreEntity.novel_id == nid, CoreEntity.name == "OldEntity"
        )
        result = await db_session.execute(stmt)
        old = result.scalar_one_or_none()
        assert old is not None
        assert old.status == "canonical"

        from infrastructure.tasks.models import AsyncTask

        task = await db_session.get(AsyncTask, uuid.UUID(task_result["task_id"]))
        assert task is not None
        assert task.meta["replace_existing"] is True

    async def test_manual_scene_also_requires_reextract_confirmation(
        self,
        db_session: AsyncSession,
        novel_with_drafts: str,
    ) -> None:
        from modules.imports.facade import start_deep_import_stage
        from modules.outline.facade import create_scene

        await create_scene(
            db_session,
            novel_with_drafts,
            {
                "scene_index": 0,
                "title": "Protected manual Scene",
                "source": "manual",
                "scene_chunks": [{"chapter_index": 1}],
                "chapter_ids": ["1"],
                "status": "canonical",
            },
        )

        result = await start_deep_import_stage(
            db_session,
            novel_with_drafts,
            1,
            1,
            stage="scenes",
            authorization_confirmed=True,
        )

        assert result["requires_confirmation"] is True
        assert "1 个已采用/受保护 Scene" in result["warning"]

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

        result = await start_deep_import(
            db_session,
            other_novel_id,
            1,
            1,
            authorization_confirmed=True,
        )
        assert result["requires_confirmation"] is False
