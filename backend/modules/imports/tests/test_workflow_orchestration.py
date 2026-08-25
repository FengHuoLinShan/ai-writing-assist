"""深度导入工作流测试

测试 DeepImportWorkflow 编排逻辑和各步骤状态转换。
候选管理已移除，深度导入全自动执行三步。
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, Mock, patch

import pytest
from sqlalchemy import select

from infrastructure.tasks.models import AsyncTask
from modules.imports.adoption_policy import build_authorization_snapshot
from modules.imports.llm_schemas import (
    SceneChunk,
)
from modules.imports.models import ImportWorkflowRun
from modules.imports.orchestrator import (
    DeepImportOrchestrator,
    DeepImportWorkflowFailedError,
)
from modules.imports.scene_candidates import SceneCandidate
from modules.imports.scene_commit import SceneCommitResult
from modules.imports.scene_enrichment import Phase1bEnrichmentResult
from modules.imports.scene_fusion import FinalSceneCandidate
from modules.imports.scene_planning import ScenePlanResult, SceneWindowPlan
from modules.imports.scene_slicing import SceneSliceCandidate, SceneSlicingResult
from modules.imports.service_phase_artifacts import coverage_summary
from modules.imports.workflow import (
    DeepImportWorkflow,
)
from modules.imports.workflow_schemas import DeepImportProgress, DeepImportStep
from modules.project.contracts import ProjectLLMConfigurationError


def _authorized_task_meta(
    novel_id: str,
    *,
    start_chapter: int = 1,
    end_chapter: int = 5,
    stage: str | None = None,
) -> dict:
    snapshot = build_authorization_snapshot(
        novel_id=novel_id,
        start_chapter=start_chapter,
        end_chapter=end_chapter,
        adoption_policy="user_authorized_pipeline",
        authorization_confirmed=True,
        stage=stage,
    )
    return {
        "novel_id": novel_id,
        "start_chapter": start_chapter,
        "end_chapter": end_chapter,
        "stage": stage,
        "adoption_policy": "user_authorized_pipeline",
        "authorization_confirmed": True,
        "authorization_snapshot": snapshot,
    }


async def _empty_llm_execution_snapshot(_db, novel_id):
    return {"test_snapshot": True, "novel_id": novel_id}


async def _restore_empty_llm_execution_snapshot(_db, _novel_id, _snapshot):
    return None


def _unit_orchestrator(
    workflow=None,
    *,
    progress_observer=None,
) -> DeepImportOrchestrator:
    orchestrator = DeepImportOrchestrator(
        workflow=workflow,
        progress_observer=progress_observer,
        snapshot_builder=_empty_llm_execution_snapshot,
        snapshot_restorer=_restore_empty_llm_execution_snapshot,
    )
    orchestrator._find_active_import_task = AsyncMock(return_value=None)
    return orchestrator


def _phase0_plan_result(
    *,
    start_chapter: int = 1,
    end_chapter: int = 3,
    blocked: bool = False,
    block_reason: str | None = None,
) -> ScenePlanResult:
    chapters = [
        {
            "chapter_index": chapter_index,
            "title": f"第{chapter_index}章",
            "content": f"第{chapter_index}章正文。",
        }
        for chapter_index in range(start_chapter, end_chapter + 1)
    ]
    windows = (
        []
        if blocked
        else [
            SceneWindowPlan(
                window_index=1,
                window_id=f"B0001-{start_chapter}-{end_chapter}-owned-{start_chapter}-{end_chapter}",
                covered_start=start_chapter,
                covered_end=end_chapter,
                owned_start=start_chapter,
                owned_end=end_chapter,
                chapter_indices=list(range(start_chapter, end_chapter + 1)),
                owned_chapter_indices=list(range(start_chapter, end_chapter + 1)),
                input_chars=1200,
                max_tokens=13_000,
                batch_size=end_chapter - start_chapter + 1,
                overlap=0,
            )
        ]
    )
    return ScenePlanResult(
        chapters=[] if blocked else chapters,
        windows=windows,
        quality_stats={
            "parameter_version": "phase0_plan_v1",
            "total_chapters": 0 if blocked else len(chapters),
            "total_batches": len(windows),
            "completed_batches": len(windows),
            "window_count": len(windows),
            "llm_calls": 0,
        },
        diagnostics=[
            {
                "final_status": "failed" if blocked else "success",
                "final_error_type": block_reason if blocked else None,
            }
        ],
        blocked=blocked,
        block_reason=block_reason,
    )


def _scene_coverage(
    covered_chapters: set[int] | list[int] | tuple[int, ...],
    start_chapter: int,
    end_chapter: int,
) -> dict:
    return coverage_summary(set(covered_chapters), start_chapter, end_chapter)


def _scene_candidate(
    candidate_id: str = "phase-candidate-1",
    *,
    source_round: str = "A",
    source_batch_id: str = "A-1-1",
    source_batch_index: int = 1,
    source_chapter_indices: list[int] | None = None,
    quality: str = "high",
) -> SceneCandidate:
    chapters = source_chapter_indices or [1, 2, 3, 4, 5]
    return SceneCandidate(
        candidate_id=candidate_id,
        source_round=source_round,
        source_batch_id=source_batch_id,
        source_batch_index=source_batch_index,
        source_chapter_indices=chapters,
        quality=quality,
        payload={
            "scenes": [
                {
                    "title": "候选 Scene",
                    "goal": "保留导入事件",
                    "scene_chunks": [
                        {"chapter_index": chapters[0], "start_paragraph": 0}
                    ],
                }
            ],
            "boundary_status": "complete",
            "confidence": 0.9,
        },
        diagnostics={},
    )


def _scene_slice_candidate(
    candidate_id: str = "phase1a-candidate-1",
    *,
    start_chapter: int = 1,
    end_chapter: int = 1,
    needs_review: bool = False,
) -> SceneSliceCandidate:
    return SceneSliceCandidate(
        candidate_id=candidate_id,
        source_window_id="B0001",
        source_window_index=1,
        title=f"第{start_chapter}章 Scene",
        goal="推进当前章节核心目标。",
        core_conflict="当前章节存在待解决冲突。",
        start_chapter=start_chapter,
        end_chapter=end_chapter,
        boundary_status="complete",
        source_chapter_indices=list(range(start_chapter, end_chapter + 1)),
        needs_review=needs_review,
        review_reason="needs review" if needs_review else "",
    )


def _phase1a_slicing_result(
    covered_chapters: list[int] | None = None,
    *,
    blocked: bool = False,
    block_reason: str | None = None,
    fallback_count: int = 0,
) -> SceneSlicingResult:
    covered_chapters = covered_chapters or [1, 2, 3]
    candidates = [
        _scene_slice_candidate(
            f"phase1a-candidate-{chapter_index}",
            start_chapter=chapter_index,
            end_chapter=chapter_index,
            needs_review=chapter_index <= fallback_count,
        )
        for chapter_index in covered_chapters
    ]
    return SceneSlicingResult(
        candidates=[] if blocked else candidates,
        quality_stats={
            "total_batches": 1,
            "completed_batches": 0 if blocked else 1,
            "success": 0 if blocked else 1,
            "failed": 1 if blocked else 0,
            "fallback_count": fallback_count,
            "scene_count": 0 if blocked else len(candidates),
        },
        diagnostics=[
            {
                "final_status": "failed" if blocked else "success",
                "final_error_type": block_reason if blocked else None,
            }
        ],
        blocked=blocked,
        block_reason=block_reason,
    )


def _final_scene_candidate(
    *,
    phase: str = "phase1b_fusion",
    fallback_required: bool = False,
    source_chapter_indices: list[int] | None = None,
) -> FinalSceneCandidate:
    chapters = source_chapter_indices or [1, 2, 3, 4, 5]
    return FinalSceneCandidate(
        phase=phase,
        title="正式 Scene 候选",
        goal="提交融合结果",
        core_conflict="",
        emotional_beat="",
        narrative_tag="imported",
        scene_chunks=[SceneChunk(chapter_index=1, start_paragraph=0)],
        source_candidate_ids=["phase1a-candidate-1"],
        source_rounds=["A"],
        source_chapter_indices=chapters,
        operation="kept",
        confidence=0.9,
        fallback_required=fallback_required,
        boundary_status="complete",
        boundary_reason="",
        needs_review=fallback_required,
        review_reason="fallback" if fallback_required else "",
    )


def _phase1b_enrichment_result(
    source_chapter_indices: list[int] | None = None,
    *,
    degraded: bool = False,
) -> Phase1bEnrichmentResult:
    chapters = source_chapter_indices or [1, 2, 3]
    return Phase1bEnrichmentResult(
        candidates=[
            _final_scene_candidate(
                phase="phase1b_enrichment",
                fallback_required=degraded,
                source_chapter_indices=chapters,
            )
        ],
        quality_stats={
            "total_windows": 1,
            "completed_windows": 0 if degraded else 1,
            "total_scenes": 1,
            "completed": 0 if degraded else 1,
            "failed": 1 if degraded else 0,
            "fallback_count": 1 if degraded else 0,
            "concurrency": 20,
            "max_tokens": 4096,
            "max_retries": 1,
        },
        degraded=degraded,
        block_reason="phase1b_enrichment_fallback" if degraded else None,
    )


def _scene_commit_result(
    *,
    created_count: int = 5,
    skipped_count: int = 0,
    conflict_count: int = 0,
) -> SceneCommitResult:
    return SceneCommitResult(
        created_count=created_count,
        skipped_count=skipped_count,
        conflict_count=conflict_count,
        created_scene_ids=[f"scene-{index}" for index in range(created_count)],
    )


async def _create_recoverable_deep_import_task(
    db_session,
    *,
    task_type: str = "deep_import",
    recovery_required: bool = True,
    novel_id: str | None = None,
) -> AsyncTask:
    novel_id = novel_id or str(uuid.uuid4())
    recovery_flags = {
        "interrupted": recovery_required,
        "recoverable": recovery_required,
        "recovery_required": recovery_required,
    }
    task = AsyncTask(
        id=uuid.uuid4(),
        task_type=task_type,
        status="failed",
        meta={
            "novel_id": novel_id,
            "start_chapter": 1,
            "end_chapter": 3,
            **recovery_flags,
        },
        result={
            "current_phase": "phase1b_fusion",
            "workflow_id": "workflow-from-result",
            **recovery_flags,
        },
        progress=0.5,
        recovery_policy=(
            "manual_resume"
            if task_type
            in {
                "deep_import",
                "scene_auto_extraction",
                "world_object_auto_extraction",
                "plot_structure_auto_extraction",
            }
            else "restart_origin"
        ),
    )
    db_session.add(task)
    await db_session.flush()
    if task_type in {
        "deep_import",
        "scene_auto_extraction",
        "world_object_auto_extraction",
        "plot_structure_auto_extraction",
    }:
        db_session.add(
            ImportWorkflowRun(
                id=task.id,
                task_id=task.id,
                novel_id=uuid.UUID(novel_id),
                workflow_type=task_type,
                stage=None,
                start_chapter=1,
                end_chapter=3,
                status="failed",
                generation=1,
                recovery_required=recovery_required,
                authorization_snapshot={},
                llm_execution_snapshot={},
                prepare_checkpoint={},
                checkpoints={},
                progress=dict(task.result or {}),
            )
        )
        await db_session.flush()
    return task


@pytest.fixture(autouse=True)
def _stub_resilient_scene_pipeline(monkeypatch):
    async def _project_settings(_db, _novel_id):
        return {}

    async def _snapshot_health_summary(*_args, **_kwargs):
        return {}

    async def _plan(_self, _db, _novel_id, start_chapter, end_chapter):
        return _phase0_plan_result(start_chapter=start_chapter, end_chapter=end_chapter)

    async def _slice(
        _self,
        _db,
        _novel_id,
        start_chapter,
        end_chapter,
        _phase0_plan,
        **_kwargs,
    ):
        return _phase1a_slicing_result(list(range(start_chapter, end_chapter + 1)))

    async def _enrich(
        _self,
        _db,
        _novel_id,
        _phase1a_candidates,
        *,
        start_chapter,
        end_chapter,
        **_kwargs,
    ):
        return _phase1b_enrichment_result(list(range(start_chapter, end_chapter + 1)))

    async def _commit(
        _db,
        _novel_id,
        _candidates,
        *,
        workflow_id,
        fusion_suggestions=None,
        start_chapter=None,
        end_chapter=None,
        replace_existing=False,
    ):
        return _scene_commit_result()

    monkeypatch.setattr(DeepImportWorkflow, "_run_phase0_plan", _plan)
    monkeypatch.setattr(DeepImportWorkflow, "_run_phase1a_scene_slicing", _slice)
    monkeypatch.setattr(DeepImportWorkflow, "_run_phase1b_enrichment", _enrich)
    monkeypatch.setattr(
        DeepImportWorkflow,
        "_commit_fused_scenes",
        staticmethod(_commit),
    )
    monkeypatch.setattr(
        "modules.imports.workflow._project_settings_for_novel",
        _project_settings,
    )
    monkeypatch.setattr(
        "modules.evidence.facade.build_snapshot_health_summary",
        _snapshot_health_summary,
    )


class TestDeepImportOrchestrator:
    """测试深度导入入口编排器保持 facade/task 返回契约。"""

    @pytest.mark.asyncio
    async def test_start_rejects_implicit_authorization(self):
        orchestrator = _unit_orchestrator()

        with pytest.raises(ValueError, match="authorization_confirmed must be true"):
            await orchestrator.start(
                db=AsyncMock(),
                novel_id=str(uuid.uuid4()),
                start_chapter=1,
                end_chapter=3,
            )

    @pytest.mark.asyncio
    async def test_start_does_not_enqueue_when_llm_preflight_fails(self):
        orchestrator = _unit_orchestrator()
        orchestrator._build_llm_execution_snapshot = AsyncMock(
            side_effect=ProjectLLMConfigurationError(
                "Project LLM API key is not configured"
            )
        )
        orchestrator._check_duplicate_import = AsyncMock()
        orchestrator._enqueue_deep_import = Mock()

        with pytest.raises(ProjectLLMConfigurationError, match="API key"):
            await orchestrator.start(
                db=AsyncMock(),
                novel_id="novel-1",
                start_chapter=1,
                end_chapter=3,
                force=True,
                authorization_confirmed=True,
            )

        orchestrator._check_duplicate_import.assert_not_awaited()
        orchestrator._enqueue_deep_import.assert_not_called()

    @pytest.mark.asyncio
    async def test_start_reuses_existing_active_import_task_without_enqueue(self):
        orchestrator = _unit_orchestrator()
        task_id = uuid.uuid4()
        active = AsyncTask(
            id=task_id,
            task_type="scene_auto_extraction",
            status="running",
            meta={
                "novel_id": "novel-1",
                "stage": "scenes",
                "authorization_snapshot": {
                    "adoption_policy": "user_authorized_pipeline",
                    "authorization_confirmed": True,
                },
            },
        )
        orchestrator._find_active_import_task = AsyncMock(return_value=active)
        orchestrator._build_llm_execution_snapshot = AsyncMock()
        orchestrator._check_duplicate_import = AsyncMock()
        orchestrator._enqueue_deep_import = Mock()

        result = await orchestrator.start(
            db=AsyncMock(),
            novel_id="novel-1",
            start_chapter=1,
            end_chapter=3,
            authorization_confirmed=True,
        )

        assert result["task_id"] == str(task_id)
        assert result["workflow_type"] == "scene_auto_extraction"
        assert result["reused_task"] is True
        orchestrator._build_llm_execution_snapshot.assert_not_awaited()
        orchestrator._check_duplicate_import.assert_not_awaited()
        orchestrator._enqueue_deep_import.assert_not_called()

    @pytest.mark.asyncio
    async def test_start_discovers_persisted_pending_task_for_same_novel(
        self,
        db_session,
    ):
        novel_id = str(uuid.uuid4())
        active = AsyncTask(
            task_type="deep_import",
            status="pending",
            meta={
                "novel_id": novel_id,
                "authorization_snapshot": {
                    "adoption_policy": "user_authorized_pipeline",
                    "authorization_confirmed": True,
                },
            },
        )
        db_session.add(active)
        await db_session.flush()
        db_session.add(
            ImportWorkflowRun(
                id=active.id,
                task_id=active.id,
                novel_id=uuid.UUID(novel_id),
                workflow_type="deep_import",
                stage=None,
                start_chapter=1,
                end_chapter=3,
                status="pending",
                generation=1,
                recovery_required=False,
                authorization_snapshot=dict(active.meta["authorization_snapshot"]),
                llm_execution_snapshot={},
                prepare_checkpoint={},
                checkpoints={},
                progress={},
            )
        )
        await db_session.flush()
        orchestrator = DeepImportOrchestrator(
            snapshot_builder=AsyncMock(side_effect=AssertionError("must reuse task")),
        )

        result = await orchestrator.start(
            db=db_session,
            novel_id=novel_id,
            start_chapter=1,
            end_chapter=3,
            authorization_confirmed=True,
        )

        assert result["task_id"] == str(active.id)
        assert result["reused_task"] is True

    @pytest.mark.asyncio
    async def test_single_recovery_flag_does_not_block_new_submission(
        self,
        db_session,
    ):
        novel_id = str(uuid.uuid4())
        db_session.add_all(
            [
                AsyncTask(
                    task_type="deep_import",
                    status="failed",
                    meta={"novel_id": novel_id, "recovery_required": True},
                    result={},
                ),
                AsyncTask(
                    task_type="scene_auto_extraction",
                    status="failed",
                    meta={"novel_id": novel_id},
                    result={"recovery_required": True},
                ),
            ]
        )
        await db_session.flush()

        active = await DeepImportOrchestrator._find_active_import_task(
            db_session,
            novel_id,
        )

        assert active is None

    @pytest.mark.asyncio
    async def test_start_returns_confirmation_without_enqueue_when_duplicates_exist(self):
        orchestrator = _unit_orchestrator()
        orchestrator._check_duplicate_import = AsyncMock(return_value="已有派生数据")
        orchestrator._enqueue_deep_import = AsyncMock()

        result = await orchestrator.start(
            db=AsyncMock(),
            novel_id=str(uuid.uuid4()),
            start_chapter=1,
            end_chapter=3,
            force=False,
            authorization_confirmed=True,
        )

        assert result == {
            "workflow_id": None,
            "task_id": None,
            "status": "requires_confirmation",
            "requires_confirmation": True,
            "warning": "已有派生数据",
            "message": "已有派生数据",
        }
        orchestrator._enqueue_deep_import.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_start_force_defers_replacement_then_enqueues(self):
        orchestrator = _unit_orchestrator()
        task_id = uuid.uuid4()
        db = AsyncMock()
        orchestrator._check_duplicate_import = AsyncMock(return_value="已有派生数据")
        orchestrator._enqueue_deep_import = Mock(return_value=task_id)

        result = await orchestrator.start(
            db=db,
            novel_id="novel-1",
            start_chapter=1,
            end_chapter=3,
            force=True,
            authorization_confirmed=True,
        )

        _, enqueue_kwargs = orchestrator._enqueue_deep_import.call_args
        assert enqueue_kwargs["context_mode"] == "working"
        assert enqueue_kwargs["include_pending_objects"] is True
        assert enqueue_kwargs["high_quality"] is False
        assert enqueue_kwargs["replace_existing"] is True
        snapshot = enqueue_kwargs["authorization_snapshot"]
        assert snapshot["adoption_policy"] == "user_authorized_pipeline"
        assert snapshot["authorization_confirmed"] is True
        assert snapshot["scope"] == {
            "novel_id": "novel-1",
            "start_chapter": 1,
            "end_chapter": 3,
            "stage": None,
        }
        db.flush.assert_awaited_once()
        assert result.pop("adoption_policy") == "user_authorized_pipeline"
        assert result.pop("authorization_snapshot") == snapshot
        assert result == {
            "workflow_id": str(task_id),
            "task_id": str(task_id),
            "status": "pending",
            "requires_confirmation": False,
            "message": "深度导入任务已提交（第1-3章）",
        }

    @pytest.mark.asyncio
    async def test_resume_reuses_original_recoverable_deep_import_task(
        self,
        db_session,
    ):
        task = await _create_recoverable_deep_import_task(db_session)

        result = await _unit_orchestrator().resume_interrupted(db_session, str(task.id))

        assert result["task_id"] == str(task.id)
        assert result["workflow_id"] == str(task.id)
        assert result["status"] == "pending"
        assert task.status == "pending"
        assert task.result["interrupted"] is False
        assert task.result["recovery_required"] is False
        assert task.meta["interrupted"] is False
        assert task.meta["recovery_required"] is False

    @pytest.mark.asyncio
    async def test_resume_reuses_original_recoverable_stage_task(
        self,
        db_session,
    ):
        task = await _create_recoverable_deep_import_task(
            db_session,
            task_type="world_object_auto_extraction",
        )
        task.meta["stage"] = "world_objects"
        task.result["stage"] = "world_objects"
        await db_session.flush()

        result = await _unit_orchestrator().resume_interrupted(
            db_session,
            str(task.id),
        )

        assert result["task_id"] == str(task.id)
        assert result["status"] == "pending"
        assert task.task_type == "world_object_auto_extraction"
        assert task.status == "pending"
        assert task.result["recovery_required"] is False
        assert task.meta["recovery_required"] is False

    @pytest.mark.asyncio
    async def test_resume_missing_deep_import_task_raises_not_found(
        self,
        db_session,
    ):
        from modules.imports.contracts import TaskNotFoundError

        task_id = str(uuid.uuid4())

        with pytest.raises(TaskNotFoundError) as exc_info:
            await _unit_orchestrator().resume_interrupted(db_session, task_id)

        assert exc_info.value.task_id == task_id

    @pytest.mark.asyncio
    async def test_resume_non_deep_import_task_raises_value_error(
        self,
        db_session,
    ):
        task = await _create_recoverable_deep_import_task(
            db_session,
            task_type="rag_index_chapter",
        )

        with pytest.raises(ValueError, match="deep_import or deep import stage"):
            await _unit_orchestrator().resume_interrupted(db_session, str(task.id))

    @pytest.mark.asyncio
    async def test_resume_without_recovery_required_raises_value_error(
        self,
        db_session,
    ):
        task = await _create_recoverable_deep_import_task(
            db_session,
            recovery_required=False,
        )

        with pytest.raises(ValueError, match="does not require recovery"):
            await _unit_orchestrator().resume_interrupted(db_session, str(task.id))

    @pytest.mark.asyncio
    async def test_abandon_recovery_marks_original_cancelled_with_cleanup_summary(
        self,
        db_session,
    ):
        task = await _create_recoverable_deep_import_task(db_session)

        result = await _unit_orchestrator().abandon_recovery(db_session, str(task.id))

        assert result["task_id"] == str(task.id)
        assert result["workflow_id"] == str(task.id)
        assert result["status"] == "cancelled"
        assert result["cleanup_summary"] == {
            "deprecated_scenes": 0,
            "deprecated_entities": 0,
            "deprecated_structure_assets": 0,
            "hard_deleted_assets": 0,
            "cleanup_mode": "soft_deprecate",
            "rolled_back_delta_logs": 0,
            "rolled_back_aliases": 0,
            "rolled_back_relations": 0,
            "skipped_delta_logs": 0,
            "cleanup_todo": None,
        }
        assert task.status == "cancelled"
        assert task.finished_at is not None

    @pytest.mark.asyncio
    async def test_abandon_recovery_uses_cleanup_hook_without_hard_delete(
        self,
        db_session,
    ):
        task = await _create_recoverable_deep_import_task(db_session)
        orchestrator = _unit_orchestrator()
        orchestrator.cleanup_workflow_assets = AsyncMock(
            return_value={
                "deprecated_scenes": 0,
                "deprecated_entities": 0,
                "deprecated_structure_assets": 0,
                "hard_deleted_assets": 0,
                "cleanup_mode": "soft_deprecate",
            }
        )

        result = await orchestrator.abandon_recovery(db_session, str(task.id))

        orchestrator.cleanup_workflow_assets.assert_awaited_once_with(
            db_session,
            task.meta["novel_id"],
            str(task.id),
        )
        assert result["cleanup_summary"]["hard_deleted_assets"] == 0

    @pytest.mark.asyncio
    async def test_cleanup_workflow_assets_deprecates_only_same_workflow_assets(
        self,
        db_session,
    ):
        from modules.story.outline_state.models import OutlineArc, PlotThread, Scene
        from modules.world.models import CoreEntity
        from shared.utils import parse_uuid

        novel_id = parse_uuid(str(uuid.uuid4()), "novel_id")
        other_novel_id = parse_uuid(str(uuid.uuid4()), "novel_id")
        workflow_id = "wf-cleanup"

        current_scene = Scene(
            novel_id=novel_id,
            scene_index=1,
            title="当前工作流 Scene",
            source="deep_import",
            status="draft",
            structure_meta={
                "workflow_id": workflow_id,
                "auto_ingested": True,
            },
        )
        canonical_scene = Scene(
            novel_id=novel_id,
            scene_index=2,
            title="当前工作流正史 Scene",
            source="deep_import",
            status="canonical",
            structure_meta={
                "workflow_id": workflow_id,
                "auto_ingested": True,
            },
        )
        other_workflow_scene = Scene(
            novel_id=novel_id,
            scene_index=3,
            title="其他工作流 Scene",
            source="deep_import",
            status="draft",
            structure_meta={
                "workflow_id": "wf-other",
                "auto_ingested": True,
            },
        )
        other_novel_scene = Scene(
            novel_id=other_novel_id,
            scene_index=1,
            title="其他小说 Scene",
            source="deep_import",
            status="draft",
            structure_meta={
                "workflow_id": workflow_id,
                "auto_ingested": True,
            },
        )
        user_edited_scene = Scene(
            novel_id=novel_id,
            scene_index=4,
            title="用户编辑 Scene",
            source="deep_import",
            status="draft",
            structure_meta={
                "workflow_id": workflow_id,
                "auto_ingested": True,
                "user_edited": True,
            },
        )
        current_entity = CoreEntity(
            novel_id=novel_id,
            entity_type="character",
            name="当前实体",
            status="candidate",
            content_json={
                "_meta": {
                    "source": "deep_import",
                    "workflow_id": workflow_id,
                    "auto_ingested": True,
                }
            },
        )
        other_workflow_entity = CoreEntity(
            novel_id=novel_id,
            entity_type="character",
            name="其他工作流实体",
            status="candidate",
            content_json={
                "_meta": {
                    "source": "deep_import",
                    "workflow_id": "wf-other",
                    "auto_ingested": True,
                }
            },
        )
        user_edited_entity = CoreEntity(
            novel_id=novel_id,
            entity_type="character",
            name="用户编辑实体",
            status="candidate",
            content_json={
                "_meta": {
                    "source": "deep_import",
                    "workflow_id": workflow_id,
                    "auto_ingested": True,
                    "user_edited": True,
                }
            },
        )
        current_thread = PlotThread(
            novel_id=novel_id,
            name="当前剧情线",
            thread_type="main",
            status="draft",
            provenance_meta={
                "source": "deep_import",
                "workflow_id": workflow_id,
                "auto_ingested": True,
            },
        )
        current_arc = OutlineArc(
            novel_id=novel_id,
            title="当前篇章",
            status="draft",
            provenance_meta={
                "source": "deep_import",
                "workflow_id": workflow_id,
                "auto_ingested": True,
            },
        )
        other_workflow_arc = OutlineArc(
            novel_id=novel_id,
            title="其他工作流篇章",
            status="draft",
            provenance_meta={
                "source": "deep_import",
                "workflow_id": "wf-other",
                "auto_ingested": True,
            },
        )
        db_session.add_all(
            [
                current_scene,
                canonical_scene,
                other_workflow_scene,
                other_novel_scene,
                user_edited_scene,
                current_entity,
                other_workflow_entity,
                user_edited_entity,
                current_thread,
                current_arc,
                other_workflow_arc,
            ]
        )
        await db_session.flush()

        summary = await _unit_orchestrator().cleanup_workflow_assets(
            db_session,
            str(novel_id),
            workflow_id,
        )

        assert summary["deprecated_scenes"] == 2
        assert summary["deprecated_entities"] == 1
        assert summary["deprecated_structure_assets"] == 2
        assert summary["hard_deleted_assets"] == 0
        assert summary["cleanup_mode"] == "soft_deprecate"

        scenes = (
            await db_session.execute(
                select(Scene).where(
                    Scene.id.in_(
                        [
                            current_scene.id,
                            canonical_scene.id,
                            other_workflow_scene.id,
                            other_novel_scene.id,
                            user_edited_scene.id,
                        ]
                    )
                )
            )
        ).scalars()
        scene_status = {scene.title: scene.status for scene in scenes}
        assert scene_status["当前工作流 Scene"] == "deprecated"
        assert scene_status["当前工作流正史 Scene"] == "deprecated"
        assert scene_status["其他工作流 Scene"] == "draft"
        assert scene_status["其他小说 Scene"] == "draft"
        assert scene_status["用户编辑 Scene"] == "draft"

        entities = (
            await db_session.execute(
                select(CoreEntity).where(
                    CoreEntity.id.in_(
                        [
                            current_entity.id,
                            other_workflow_entity.id,
                            user_edited_entity.id,
                        ]
                    )
                )
            )
        ).scalars()
        entity_status = {entity.name: entity.status for entity in entities}
        assert entity_status["当前实体"] == "deprecated"
        assert entity_status["其他工作流实体"] == "candidate"
        assert entity_status["用户编辑实体"] == "candidate"

        thread = await db_session.get(PlotThread, current_thread.id)
        arc = await db_session.get(OutlineArc, current_arc.id)
        untouched_arc = await db_session.get(OutlineArc, other_workflow_arc.id)
        assert thread.status == "deprecated"
        assert arc.status == "deprecated"
        assert untouched_arc.status == "draft"

    @pytest.mark.asyncio
    async def test_run_task_rejects_missing_or_unconfirmed_authorization_snapshot(
        self,
    ):
        orchestrator = _unit_orchestrator()
        orchestrator.workflow.run_step = AsyncMock()
        db = AsyncMock()

        missing_task = Mock(id=uuid.uuid4(), meta={"novel_id": "n1"})
        missing_task.update_progress = Mock()
        with pytest.raises(ValueError, match="authorization_snapshot is required"):
            await orchestrator.run_task(db, missing_task)

        unconfirmed_meta = _authorized_task_meta("n1")
        unconfirmed_meta["authorization_snapshot"] = {
            **unconfirmed_meta["authorization_snapshot"],
            "authorization_confirmed": False,
        }
        unconfirmed_task = Mock(id=uuid.uuid4(), meta=unconfirmed_meta)
        unconfirmed_task.update_progress = Mock()
        with pytest.raises(
            ValueError,
            match="authorization_snapshot.authorization_confirmed must be true",
        ):
            await orchestrator.run_task(db, unconfirmed_task)

        mismatched_meta = _authorized_task_meta("n1")
        mismatched_meta["authorization_snapshot"] = {
            **mismatched_meta["authorization_snapshot"],
            "scope": {
                **mismatched_meta["authorization_snapshot"]["scope"],
                "novel_id": "another-novel",
            },
        }
        mismatched_task = Mock(id=uuid.uuid4(), meta=mismatched_meta)
        mismatched_task.update_progress = Mock()
        with pytest.raises(ValueError, match="scope does not match task meta"):
            await orchestrator.run_task(db, mismatched_task)

        orchestrator.workflow.run_step.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_run_task_returns_task_result_contract(self):
        orchestrator = _unit_orchestrator()
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
            quality_status="partial",
            phase_errors=[
                {
                    "phase": "entity_extraction",
                    "error_kind": "phase_failed",
                    "message": "实体写入失败",
                }
            ],
            llm_health={"ok": True, "model": "deepseek-v4-flash"},
        )
        orchestrator.workflow.run_step = AsyncMock(return_value=progress)
        task = Mock(
            id=uuid.uuid4(),
            meta=_authorized_task_meta(
                "n1",
                start_chapter=2,
                end_chapter=4,
            ),
        )
        task.update_progress = Mock()
        db = AsyncMock()

        result = await orchestrator.run_task(db, task)

        assert result.pop("adoption_policy") == "user_authorized_pipeline"
        authorization_snapshot = result.pop("authorization_snapshot")
        assert authorization_snapshot["authorization_confirmed"] is True
        assert "legacy_internal_default" not in authorization_snapshot
        assert result.pop("llm_execution_snapshot") == {}
        asset_summary = result.pop("asset_summary")
        assert asset_summary["adopted"] == 0
        assert asset_summary["review"] == 0
        assert asset_summary["not_adopted"] == 0
        assert set(asset_summary["by_kind"]) == {
            "scene",
            "entity",
            "relation",
            "alias",
            "structure",
        }
        assert result == {
            "workflow_type": "deep_import",
            "stage": None,
            "phase": "done",
            "current_step": None,
            "completed_steps": [
                "scene_segmentation",
                "entity_extraction",
                "structure_analysis",
            ],
            "message": "完成",
            "current_phase": None,
            "current_round": None,
            "current_chapter_range": None,
            "current_chapter": None,
            "current_scene_candidate_id": None,
            "current_window": None,
            "current_operation": None,
            "current_item": {},
            "phase_timeline": [],
            "progress_events": [],
            "acceptance_checks": [],
            "diagnostic_counts": {},
            "last_error": None,
            "quality_stats": {},
            "phase_artifacts": {},
            "checkpoints": {},
            "phase2_dedup": {},
            "recovery_summary": {},
            "interrupted": False,
            "recoverable": False,
            "recovery_required": False,
            "interrupted_at": None,
            "last_heartbeat_at": None,
            "degraded": True,
            "degraded_reason": None,
            "phase1a_fallback": False,
            "degraded_batches": [2],
            "quality_status": "partial",
            "phase_errors": [
                {
                    "phase": "entity_extraction",
                    "error_kind": "phase_failed",
                    "message": "实体写入失败",
                }
            ],
            "llm_health": {"ok": True, "model": "deepseek-v4-flash"},
            "snapshot_health_summary": {},
            "audit_summary": {},
        }

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("stage", "task_type", "method_name"),
        [
            (
                "world_objects",
                "world_object_auto_extraction",
                "run_entity_extraction_only",
            ),
            (
                "plot_structure",
                "plot_structure_auto_extraction",
                "run_structure_analysis_only",
            ),
        ],
    )
    async def test_stage_tasks_forward_high_quality_to_actual_workflow(
        self,
        stage,
        task_type,
        method_name,
    ):
        orchestrator = _unit_orchestrator()
        progress = DeepImportProgress(phase="done")
        method = AsyncMock(return_value=progress)
        setattr(orchestrator.workflow, method_name, method)
        meta = _authorized_task_meta(
            "00000000-0000-0000-0000-000000000001",
            stage=stage,
        )
        meta["high_quality"] = True
        task = Mock(
            id=uuid.uuid4(),
            task_type=task_type,
            meta=meta,
            result={},
        )
        task.update_progress = Mock()

        await orchestrator.run_stage_task(AsyncMock(), task, stage=stage)

        assert method.await_args.kwargs["high_quality"] is True
        assert method.await_args.kwargs["project_settings"] is None

    @pytest.mark.asyncio
    async def test_stage_task_reuses_frozen_profile_after_account_key_rotation(
        self,
        db_session,
        test_project_id,
        account_llm_connection,
    ):
        novel_id = test_project_id

        orchestrator = DeepImportOrchestrator()
        submitted = await orchestrator.start_stage(
            db_session,
            novel_id,
            1,
            3,
            stage="world_objects",
            authorization_confirmed=True,
        )
        task = await db_session.get(AsyncTask, uuid.UUID(submitted["task_id"]))
        assert task is not None
        original_snapshot = dict(task.meta["llm_execution_snapshot"])

        from datetime import UTC, datetime

        from infrastructure.llm.secret_store import encrypt_secret, fingerprint_secret
        from modules.account.settings_repositories import AccountLLMCredentialRepository

        rotated_key = "unit-test-rotated-account-key"
        await AccountLLMCredentialRepository().upsert(
            db_session,
            {
                "owner_id": account_llm_connection["owner_id"],
                "provider_id": account_llm_connection["provider_id"],
                "encrypted_api_key": encrypt_secret(rotated_key),
                "key_fingerprint": fingerprint_secret(
                    rotated_key,
                    purpose="account-llm-api-key",
                ),
                "verified_at": datetime.now(UTC),
            },
        )
        completed = DeepImportProgress(phase="done")
        orchestrator.workflow.run_entity_extraction_only = AsyncMock(
            return_value=completed
        )

        await orchestrator.run_stage_task(
            db_session,
            task,
            stage="world_objects",
        )

        kwargs = orchestrator.workflow.run_entity_extraction_only.await_args.kwargs
        assert (
            kwargs["project_settings"]["llm"]["model"] == account_llm_connection["model"]
        )
        assert kwargs["project_settings"]["llm"]["api_key"] == rotated_key
        assert task.meta["llm_execution_snapshot"] == original_snapshot

    @pytest.mark.asyncio
    async def test_run_task_defaults_missing_chapter_range(self):
        """任务 meta 未带章节范围时，orchestrator 使用 1-5 章默认范围。"""
        orchestrator = _unit_orchestrator()
        progress = DeepImportProgress(phase="done", message="完成")
        orchestrator.workflow.run_step = AsyncMock(return_value=progress)
        task = Mock(id=uuid.uuid4(), meta=_authorized_task_meta("n1"))
        task.update_progress = Mock()
        db = AsyncMock()

        await orchestrator.run_task(db, task)

        _, kwargs = orchestrator.workflow.run_step.await_args
        assert kwargs["start_chapter"] == 1
        assert kwargs["end_chapter"] == 5
        assert kwargs["context_mode"] == "working"
        assert kwargs["include_pending_objects"] is True

    @pytest.mark.asyncio
    async def test_run_task_calls_progress_observer_after_progress_commit(self):
        observed: list[dict] = []

        async def observer(updated, progress_value, task):
            observed.append(
                {
                    "phase": updated.phase,
                    "current_phase": updated.current_phase,
                    "progress": progress_value,
                    "task_id": str(task.id),
                }
            )

        orchestrator = _unit_orchestrator(progress_observer=observer)

        async def run_step(*_args, on_progress=None, **_kwargs):
            progress = DeepImportProgress(
                phase="running",
                current_phase="phase0_prefetch",
                message="预取中",
            )
            await on_progress(progress, 0.25)
            return DeepImportProgress(phase="done", message="完成")

        orchestrator.workflow.run_step = AsyncMock(side_effect=run_step)
        task = Mock(
            id=uuid.uuid4(),
            meta=_authorized_task_meta(
                "n1",
                start_chapter=1,
                end_chapter=2,
            ),
        )
        task.update_progress = Mock()
        db = AsyncMock()

        await orchestrator.run_task(db, task)

        assert observed == [
            {
                "phase": "running",
                "current_phase": "phase0_prefetch",
                "progress": 0.25,
                "task_id": str(task.id),
            }
        ]
        task.update_progress.assert_called_once_with(0.25)
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_run_task_keeps_progress_monotonic(self):
        orchestrator = _unit_orchestrator()

        async def run_step(*_args, on_progress=None, **_kwargs):
            progress = DeepImportProgress(phase="running")
            await on_progress(progress, 0.25)
            return DeepImportProgress(phase="done", message="完成")

        orchestrator.workflow.run_step = AsyncMock(side_effect=run_step)
        task = Mock(
            id=uuid.uuid4(),
            meta=_authorized_task_meta("n1"),
            progress=0.4,
        )
        task.update_progress = Mock()

        await orchestrator.run_task(AsyncMock(), task)

        task.update_progress.assert_called_once_with(0.4)

    @pytest.mark.parametrize(
        ("phase", "current_phase", "current_item", "expected"),
        [
            ("running", "phase0_plan", {}, 0.0),
            ("running", "phase1a_scene_slicing", {"completed": 0, "total": 4}, 0.0),
            ("running", "phase1a_scene_slicing", {"completed": 2, "total": 4}, 0.295),
            ("running", "phase1a_scene_slicing", {"completed": 4, "total": 4}, 0.59),
            ("running", "phase1b_enrichment", {"completed": 0, "total": 82}, 0.59),
            ("running", "phase1b_enrichment", {"completed": 41, "total": 82}, 0.79),
            ("running", "phase1b_enrichment", {"completed": 82, "total": 82}, 0.99),
            ("running", "scene_commit", {"count": 82}, 0.99),
            ("done", "scene_commit", {"count": 82}, 1.0),
        ],
    )
    def test_scene_stage_progress_uses_elapsed_time_weights(
        self,
        phase,
        current_phase,
        current_item,
        expected,
    ):
        progress = DeepImportProgress(
            phase=phase,
            current_phase=current_phase,
            current_item=current_item,
        )

        value = DeepImportOrchestrator._scene_stage_progress_value(progress)

        assert value == pytest.approx(expected)

    @pytest.mark.asyncio
    async def test_scene_stage_persists_elapsed_time_progress_instead_of_raw_ranges(
        self,
    ):
        orchestrator = _unit_orchestrator()

        async def run_step(*_args, on_progress=None, **_kwargs):
            updates = [
                ("running", "phase0_plan", {}, 0.0),
                (
                    "running",
                    "phase1a_scene_slicing",
                    {"completed": 2, "total": 4},
                    0.15,
                ),
                (
                    "running",
                    "phase1b_enrichment",
                    {"completed": 41, "total": 82},
                    0.25,
                ),
                ("running", "scene_commit", {"count": 82}, 0.3),
                ("done", "scene_commit", {"count": 82}, 1.0),
            ]
            latest = None
            for phase, current_phase, current_item, raw_value in updates:
                latest = DeepImportProgress(
                    phase=phase,
                    current_phase=current_phase,
                    current_item=current_item,
                )
                await on_progress(latest, raw_value)
            return latest

        orchestrator.workflow.run_step = AsyncMock(side_effect=run_step)
        task = Mock(
            id=uuid.uuid4(),
            task_type="scene_auto_extraction",
            meta=_authorized_task_meta("n1", stage="scenes"),
            result={},
            progress=0.0,
        )
        task.update_progress = Mock()

        await orchestrator.run_stage_task(AsyncMock(), task, stage="scenes")

        assert [
            call.args[0] for call in task.update_progress.call_args_list
        ] == pytest.approx([0.0, 0.295, 0.79, 0.99, 1.0])

    @pytest.mark.asyncio
    async def test_run_task_raises_after_persisting_failed_progress(self):
        orchestrator = _unit_orchestrator()
        failed = DeepImportProgress(
            phase="failed",
            quality_status="failed",
            message="Scene 提交失败",
        )
        orchestrator.workflow.run_step = AsyncMock(return_value=failed)
        task = Mock(
            id=uuid.uuid4(),
            meta=_authorized_task_meta("n1"),
            progress=0.3,
        )
        task.update_progress = Mock()
        db = AsyncMock()

        with pytest.raises(DeepImportWorkflowFailedError, match="Scene 提交失败"):
            await orchestrator.run_task(db, task)

        assert task.result["phase"] == "failed"
        task.update_progress.assert_called_once_with(0.3)
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_run_task_restores_progress_checkpoints_from_task_result(self):
        task_id = uuid.uuid4()
        orchestrator = _unit_orchestrator()
        progress = DeepImportProgress(phase="done", message="恢复完成")
        orchestrator.workflow.run_step = AsyncMock(return_value=progress)
        task = Mock(
            id=task_id,
            meta=_authorized_task_meta(
                "n1",
                start_chapter=2,
                end_chapter=4,
            ),
            result={
                "workflow_id": str(task_id),
                "phase": "running",
                "completed_steps": ["scene_segmentation"],
                "checkpoints": {
                    "phase2": {
                        "scenes": [
                            {
                                "scene_id": "scene-a",
                                "status": "done",
                                "retry_count": 0,
                            }
                        ]
                    }
                },
                "interrupted": True,
                "recoverable": True,
                "recovery_required": True,
            },
        )
        task.update_progress = Mock()
        db = AsyncMock()

        await orchestrator.run_task(db, task)

        _, kwargs = orchestrator.workflow.run_step.await_args
        restored = kwargs["progress"]
        assert restored.phase == "pending"
        assert restored.completed_steps == ["scene_segmentation"]
        assert restored.checkpoints["phase2"]["scenes"][0]["scene_id"] == "scene-a"
        assert restored.interrupted is False
        assert restored.recoverable is False
        assert restored.recovery_required is False

    @pytest.mark.asyncio
    async def test_analyze_structure_uses_working_context_mode(self):
        workflow = DeepImportWorkflow()
        generate = AsyncMock(
            return_value={
                "total_threads": 4,
                "total_arcs": 4,
                "extra_sections": {
                    "foreshadowing_plans": [{}, {}, {}, {}],
                    "reveal_plans": [{}, {}, {}, {}],
                },
            }
        )
        db = AsyncMock()

        with patch(
            "modules.imports.workflow._container_get",
            return_value=generate,
            autospec=True,
        ):
            await workflow._analyze_structure(
                db,
                "novel-1",
                1,
                3,
                workflow_id="wf-structure",
            )

        generate.assert_awaited_once_with(
            db,
            "novel-1",
            start_chapter=1,
            end_chapter=3,
            context_mode="working",
            include_pending_objects=True,
            workflow_id="wf-structure",
            audit_context_snapshot=True,
            include_chapter_texts=False,
            include_existing_scenes=True,
            generate_scenes=False,
            fast_structured=True,
            project_settings_snapshot=None,
            high_quality=False,
            persist=True,
        )


class TestDeepImportRecoveryApi:
    """测试深度导入恢复 API 的薄路由行为。"""

    @pytest.mark.asyncio
    async def test_resume_api_missing_task_id_returns_400(self, async_client):
        response = await async_client.post("/api/imports/deep/resume", json={})

        assert response.status_code == 400
        assert "task_id" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_resume_api_calls_facade(self, async_client):
        task_id = str(uuid.uuid4())
        expected = {
            "task_id": task_id,
            "workflow_id": task_id,
            "status": "pending",
        }

        novel_id = str(uuid.uuid4())
        from infrastructure.tasks.contracts import TaskOwnerContract

        with (
            patch(
                "infrastructure.tasks.facade.get_task_owner",
                autospec=True,
                return_value=TaskOwnerContract(novel_id=novel_id),
            ) as resolve_owner,
            patch(
                "modules.imports.api._require_active_project",
                autospec=True,
            ) as guard,
            patch(
                "modules.imports.facade.resume_deep_import",
                autospec=True,
                return_value=expected,
            ) as resume,
        ):
            response = await async_client.post(
                "/api/imports/deep/resume",
                json={"task_id": task_id},
            )

        assert response.status_code == 201
        assert response.json() == expected
        resolve_owner.assert_awaited_once()
        guard.assert_awaited_once()
        resume.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_abandon_api_missing_task_id_returns_400(self, async_client):
        response = await async_client.post("/api/imports/deep/abandon", json={})

        assert response.status_code == 400
        assert "task_id" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_abandon_api_calls_facade(self, async_client):
        task_id = str(uuid.uuid4())
        expected = {
            "task_id": task_id,
            "workflow_id": task_id,
            "status": "cancelled",
            "cleanup_summary": {"deprecated_scenes": 0},
            "message": "深度导入恢复已放弃",
        }

        novel_id = str(uuid.uuid4())
        from infrastructure.tasks.contracts import TaskOwnerContract

        with (
            patch(
                "infrastructure.tasks.facade.get_task_owner",
                autospec=True,
                return_value=TaskOwnerContract(novel_id=novel_id),
            ) as resolve_owner,
            patch(
                "modules.imports.api._require_active_project",
                autospec=True,
            ) as guard,
            patch(
                "modules.imports.facade.abandon_deep_import",
                autospec=True,
                return_value=expected,
            ) as abandon,
        ):
            response = await async_client.post(
                "/api/imports/deep/abandon",
                json={"task_id": task_id},
            )

        assert response.status_code == 200
        body = response.json()
        assert body["task_id"] == expected["task_id"]
        assert body["workflow_id"] == expected["workflow_id"]
        assert body["status"] == "cancelled"
        assert body["cleanup_summary"] == {
            "deprecated_scenes": 0,
            "deprecated_entities": 0,
            "deprecated_structure_assets": 0,
            "hard_deleted_assets": 0,
            "cleanup_mode": "soft_deprecate",
            "rolled_back_delta_logs": 0,
            "rolled_back_aliases": 0,
            "rolled_back_relations": 0,
            "skipped_delta_logs": 0,
            "cleanup_todo": None,
        }
        resolve_owner.assert_awaited_once()
        guard.assert_awaited_once()
        abandon.assert_awaited_once()
