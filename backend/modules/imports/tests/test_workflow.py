"""深度导入工作流测试

测试 DeepImportWorkflow 编排逻辑和各步骤状态转换。
候选管理已移除，深度导入全自动执行三步。
"""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.tasks.models import AsyncTask
from modules.imports.adoption_policy import build_authorization_snapshot
from modules.imports.entity_extraction.scene_entity_extraction import (
    SceneEntityExtractionService,
)
from modules.imports.llm_schemas import (
    AliasRelationExtractionOutput,
    ExtractedEntity,
    Phase2WorldExtractionOutput,
    SceneCandidateOutput,
    SceneChunk,
    SceneEntityExtractionOutput,
    SceneSegmentationOutput,
)
from modules.imports.orchestrator import (
    DeepImportOrchestrator,
)
from modules.imports.phase2_world_extraction import (
    PHASE2_WORLD_WINDOW_CONCURRENCY,
    Phase2WorldExtractor,
    _normalize_world_output,
)
from modules.imports.scene_candidates import SceneCandidate
from modules.imports.scene_commit import SceneCommitResult
from modules.imports.scene_enrichment import Phase1bEnrichmentResult
from modules.imports.scene_fusion import FinalSceneCandidate
from modules.imports.scene_planning import ScenePlanResult, SceneWindowPlan
from modules.imports.scene_segmentation import SceneSegmentationService
from modules.imports.scene_slicing import SceneSliceCandidate, SceneSlicingResult
from modules.imports.service_phase_artifacts import add_phase_artifact, coverage_summary
from modules.imports.service_progress_logs import (
    record_acceptance_check,
    record_progress_event,
)
from modules.imports.workflow import (
    DeepImportPhaseRunners,
    DeepImportWorkflow,
    _compact_phase1b_payload,
)
from modules.imports.workflow_entity_phase import phase2_quality_stats
from modules.imports.workflow_llm_adapters import (
    _materialize_phase1b_decision_output,
    _Phase1bDecisionOutput,
    _Phase1bSceneFusionLLM,
    _Phase1cSceneFusionLLM,
    _run_deep_import_structured_call,
)
from modules.imports.workflow_schemas import DeepImportProgress, DeepImportStep
from modules.imports.workflow_structure_phase import (
    ensure_minimum_structure_outputs,
    phase3_quality_stats,
)
from modules.writing.contracts import WritingDraftContract
from shared.deep_import_settings import DEEP_IMPORT_DEFAULT_SETTINGS


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
    return DeepImportOrchestrator(
        workflow=workflow,
        progress_observer=progress_observer,
        snapshot_builder=_empty_llm_execution_snapshot,
        snapshot_restorer=_restore_empty_llm_execution_snapshot,
    )


def test_scene_item_accepts_constraint_lists_from_llm() -> None:
    output = SceneSegmentationOutput.model_validate(
        {
            "scenes": [
                {
                    "title": "旧钟楼",
                    "must_happen": ["林澈拿到铜钥匙", "发现北境航道"],
                    "must_not_happen": ["钥匙丢失", "航线图被毁"],
                    "scene_chunks": [{"chapter_index": 1}],
                }
            ]
        }
    )

    scene = output.scenes[0]
    assert scene.must_happen == "林澈拿到铜钥匙；发现北境航道"
    assert scene.must_not_happen == "钥匙丢失；航线图被毁"


def test_phase3_quality_stats_counts_unique_review_assets_from_provenance() -> None:
    stats = phase3_quality_stats(
        {
            "total_threads": 1,
            "total_arcs": 1,
            "threads": [{"id": "t1", "needs_review": True}],
            "arcs": [
                {
                    "id": "a1",
                    "provenance_meta": {"needs_review": True},
                }
            ],
            "extra_sections": {
                "foreshadowing_plans": [{"id": "f1", "needs_review": False}],
                "reveal_plans": [
                    {
                        "id": None,
                        "target_name": "待消歧目标",
                        "needs_review": True,
                    },
                ],
                "uncertain_items": [],
            },
        },
        failed=False,
    )

    assert stats["review_asset_count"] == 3
    assert stats["review_asset_ids"] == [
        "outline_arc:a1",
        "plot_thread:t1",
        "reveal_plan:unresolved:0:待消歧目标",
    ]


def test_phase_runner_request_defaults_and_required_fields() -> None:
    from modules.imports.workflow_phase_runner import (
        EntityFullPipelineRequest,
        SceneFullPipelineRequest,
        StructureStageRequest,
    )

    progress = DeepImportProgress()
    scene_request = SceneFullPipelineRequest(
        db=None,
        novel_id="novel-1",
        start_chapter=1,
        end_chapter=2,
        progress=progress,
    )
    structure_stage_request = StructureStageRequest(
        db=None,
        novel_id="novel-1",
        start_chapter=1,
        end_chapter=2,
        progress=progress,
    )

    assert scene_request.workflow_id is None
    assert scene_request.stop_after is None
    assert scene_request.on_progress is None
    assert structure_stage_request.context_mode == "working"
    assert structure_stage_request.include_pending_objects is True
    with pytest.raises(TypeError):
        EntityFullPipelineRequest(
            db=None,
            novel_id="novel-1",
            start_chapter=1,
            end_chapter=2,
            progress=progress,
        )


@pytest.mark.asyncio
async def test_workflow_spine_uses_injected_phase_runner_protocols() -> None:
    from modules.imports.workflow_phase_runner import (
        EntityFullPipelineRequest,
        EntityStageRequest,
        SceneFullPipelineRequest,
        StructureFullPipelineRequest,
        StructureStageRequest,
    )

    calls: list[tuple[str, object]] = []

    class FakeSceneFullRunner:
        async def run_full_pipeline(self, request):
            calls.append(("scene_full", request))
            return SimpleNamespace(total_scenes=4, stopped=False)

    class FakeEntityFullRunner:
        async def run_full_pipeline(self, request):
            calls.append(("entity_full", request))
            return {"total_created": 7}

    class FakeStructureFullRunner:
        async def run_full_pipeline(self, request):
            calls.append(("structure_full", request))
            return {"total_threads": 2, "total_arcs": 3}

    class FakeEntityStageRunner:
        async def run_stage(self, request):
            calls.append(("entity_stage", request))
            request.progress.message = "entity-stage"
            return request.progress

    class FakeStructureStageRunner:
        async def run_stage(self, request):
            calls.append(("structure_stage", request))
            request.progress.message = "structure-stage"
            return request.progress

    workflow = DeepImportWorkflow(
        phase_runners=DeepImportPhaseRunners(
            scene_full=FakeSceneFullRunner(),
            entity_full=FakeEntityFullRunner(),
            entity_stage=FakeEntityStageRunner(),
            structure_full=FakeStructureFullRunner(),
            structure_stage=FakeStructureStageRunner(),
        )
    )

    with (
        patch(
            "modules.imports.workflow._project_settings_for_novel",
            autospec=True,
            return_value={},
        ),
        patch.object(
            DeepImportWorkflow,
            "_is_llm_health_required",
            return_value=False,
            autospec=True,
        ),
    ):
        progress = await workflow.run_step(
            None,
            "novel-1",
            1,
            3,
            DeepImportProgress(),
            workflow_id="wf-protocol",
        )

    assert progress.phase == "done"
    assert progress.message == (
        "深度导入完成！共 4 个 Scene，7 个实体，2 条剧情线，3 个篇章纲。"
    )
    assert [name for name, _request in calls] == [
        "scene_full",
        "entity_full",
        "structure_full",
    ]
    assert isinstance(calls[0][1], SceneFullPipelineRequest)
    assert isinstance(calls[1][1], EntityFullPipelineRequest)
    assert isinstance(calls[2][1], StructureFullPipelineRequest)

    entity_progress = await workflow.run_entity_extraction_only(
        None,
        "novel-1",
        1,
        3,
        DeepImportProgress(),
    )
    structure_progress = await workflow.run_structure_analysis_only(
        None,
        "novel-1",
        1,
        3,
        DeepImportProgress(),
    )

    assert entity_progress.message == "entity-stage"
    assert structure_progress.message == "structure-stage"
    assert isinstance(calls[3][1], EntityStageRequest)
    assert isinstance(calls[4][1], StructureStageRequest)


@pytest.mark.asyncio
async def test_phase_runner_old_methods_delegate_to_request_entrypoints() -> None:
    from modules.imports.workflow_entity_phase import EntityExtractionPhaseRunner
    from modules.imports.workflow_phase_runner import (
        EntityFullPipelineRequest,
        EntityStageRequest,
        SceneFullPipelineRequest,
        StructureFullPipelineRequest,
        StructureStageRequest,
    )
    from modules.imports.workflow_scene_phase import (
        ScenePhaseOutcome,
        ScenePhaseRunner,
    )
    from modules.imports.workflow_structure_phase import StructureAnalysisPhaseRunner

    progress = DeepImportProgress(workflow_id="wf-adapter")
    scene_runner = ScenePhaseRunner(Mock())
    entity_runner = EntityExtractionPhaseRunner(Mock())
    structure_runner = StructureAnalysisPhaseRunner(Mock())
    scene_runner.run_full_pipeline = AsyncMock(return_value=ScenePhaseOutcome(3))
    entity_runner.run_full_pipeline = AsyncMock(return_value={"total_created": 1})
    entity_runner.run_stage = AsyncMock(return_value=progress)
    structure_runner.run_full_pipeline = AsyncMock(return_value={"total_threads": 1})
    structure_runner.run_stage = AsyncMock(return_value=progress)

    scene_result = await scene_runner.run(
        None,
        "novel-1",
        1,
        3,
        progress,
        workflow_id="wf-adapter",
        on_progress=None,
        stop_after=DeepImportStep.scene_segmentation,
    )
    await entity_runner.run_full_pipeline_phase(
        None,
        "novel-1",
        1,
        3,
        progress,
        workflow_id="wf-adapter",
        total_scenes=3,
        on_progress=None,
    )
    await entity_runner.run_stage_only(
        None,
        "novel-1",
        1,
        3,
        progress,
        workflow_id="wf-adapter",
        on_progress=None,
    )
    await structure_runner.run_full_pipeline_phase(
        None,
        "novel-1",
        1,
        3,
        progress,
        workflow_id="wf-adapter",
        context_mode="working",
        include_pending_objects=True,
        total_scenes=3,
        on_progress=None,
    )
    await structure_runner.run_stage_only(
        None,
        "novel-1",
        1,
        3,
        progress,
        workflow_id="wf-adapter",
        context_mode="working",
        include_pending_objects=True,
        on_progress=None,
    )

    assert scene_result.total_scenes == 3
    assert isinstance(
        scene_runner.run_full_pipeline.await_args.args[0],
        SceneFullPipelineRequest,
    )
    assert isinstance(
        entity_runner.run_full_pipeline.await_args.args[0],
        EntityFullPipelineRequest,
    )
    assert entity_runner.run_full_pipeline.await_args.args[0].total_scenes == 3
    assert isinstance(entity_runner.run_stage.await_args.args[0], EntityStageRequest)
    assert isinstance(
        structure_runner.run_full_pipeline.await_args.args[0],
        StructureFullPipelineRequest,
    )
    assert structure_runner.run_full_pipeline.await_args.args[0].total_scenes == 3
    assert isinstance(
        structure_runner.run_stage.await_args.args[0],
        StructureStageRequest,
    )


@pytest.mark.asyncio
async def test_workflow_director_uses_phase_runner_request_entrypoints(monkeypatch):
    from modules.imports.workflow_phase_runner import (
        EntityFullPipelineRequest,
        SceneFullPipelineRequest,
        StructureFullPipelineRequest,
    )
    from modules.imports.workflow_scene_phase import ScenePhaseOutcome

    seen: list[str] = []

    async def scene_run(_self, request):
        assert isinstance(request, SceneFullPipelineRequest)
        assert request.workflow_id == "wf-request"
        assert request.stop_after is None
        seen.append("scene")
        return ScenePhaseOutcome(total_scenes=2)

    async def entity_run(_self, request):
        assert isinstance(request, EntityFullPipelineRequest)
        assert request.total_scenes == 2
        assert request.workflow_id == "wf-request"
        seen.append("entity")
        return {"total_created": 1, "total_relations": 0, "total_deltas": 0}

    async def structure_run(_self, request):
        assert isinstance(request, StructureFullPipelineRequest)
        assert request.total_scenes == 2
        assert request.context_mode == "working"
        assert request.include_pending_objects is True
        seen.append("structure")
        return {"total_threads": 1, "total_arcs": 1}

    monkeypatch.setattr(
        "modules.imports.workflow.ScenePhaseRunner.run_full_pipeline",
        scene_run,
    )
    monkeypatch.setattr(
        "modules.imports.workflow.EntityExtractionPhaseRunner.run_full_pipeline",
        entity_run,
    )
    monkeypatch.setattr(
        "modules.imports.workflow.StructureAnalysisPhaseRunner.run_full_pipeline",
        structure_run,
    )

    result = await DeepImportWorkflow().run_step(
        db=None,
        novel_id=str(uuid.uuid4()),
        start_chapter=1,
        end_chapter=3,
        progress=DeepImportProgress(),
        workflow_id="wf-request",
    )

    assert result.phase == "done"
    assert seen == ["scene", "entity", "structure"]


def test_scene_entity_output_accepts_singletons_and_text_variants_from_llm() -> None:
    output = SceneEntityExtractionOutput.model_validate(
        {
            "entities": {
                "name": "旧钟楼",
                "entity_type": {"name": "location"},
                "summary": ["藏有钥匙", "连接北境航道"],
                "aliases": "钟楼",
            },
            "relations": {
                "source_name": "林澈",
                "target_name": "旧钟楼",
                "relation_type": {"value": "发现"},
                "description": ["第一次发现", "尚未公开"],
                "strength": "较高",
            },
            "delta_events": {
                "category": "ENTITY_UPDATED",
                "meta": "安提哥努斯笔记被重新定位为1级封印物",
            },
        }
    )

    assert len(output.entities) == 1
    assert output.entities[0].entity_type == "location"
    assert output.entities[0].summary == "藏有钥匙；连接北境航道"
    assert output.entities[0].aliases == [{"alias": "钟楼", "type": "name"}]
    assert len(output.relations) == 1
    assert output.relations[0].relation_type == "发现"
    assert output.relations[0].description == "第一次发现；尚未公开"
    assert output.relations[0].strength == 0.8
    assert len(output.delta_events) == 1
    assert output.delta_events[0].meta == {"note": "安提哥努斯笔记被重新定位为1级封印物"}


def test_alias_relation_output_accepts_single_alias_and_relation() -> None:
    output = AliasRelationExtractionOutput.model_validate(
        {
            "aliases": {
                "entity_name": "周明瑞",
                "alias": "克莱恩",
                "alias_type": None,
                "quote": ["自称", "新身份"],
                "confidence": "90%",
            },
            "relations": {
                "source_name": "克莱恩",
                "target_name": "灰雾",
                "relation_type": "进入",
            },
        }
    )

    assert len(output.aliases) == 1
    assert output.aliases[0].alias_type == "alias"
    assert output.aliases[0].quote == "自称；新身份"
    assert output.aliases[0].confidence == 0.9
    assert len(output.relations) == 1


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


def test_phase_artifact_removes_raw_payload_fields_and_redacts_credentials():
    progress = DeepImportProgress()

    add_phase_artifact(
        progress,
        "phase0_prefetch",
        start_chapter=1,
        end_chapter=3,
        status="completed",
        quality_stats={
            "total_batches": 1,
            "raw_prompt": "do not store",
            "nested": {
                "messages": [{"role": "user", "content": "raw body"}],
                "body_text": "chapter body",
                "safe_count": 2,
            },
            "completion": "raw model output",
        },
        counts={
            "total_created": 1,
            "content": "raw content",
        },
        coverage={
            "covered_chapters": [1, 2],
            "missing_chapters": [3],
        },
        provider_summary={
            "provider_id": "test-provider",
            "api_key": "sk-secret",
        },
    )

    artifact = progress.phase_artifacts["phase0_prefetch"]
    assert artifact["quality_stats"]["total_batches"] == 1
    assert "raw_prompt" not in artifact["quality_stats"]
    assert "completion" not in artifact["quality_stats"]
    assert artifact["quality_stats"]["nested"] == {"safe_count": 2}
    assert artifact["counts"] == {"total_created": 1}
    assert artifact["coverage"]["missing_chapters"] == [3]
    assert artifact["provider_summary"]["api_key"] == "<redacted>"


def test_compact_phase1b_payload_keeps_reducer_fields_without_body_text():
    long_text = "正文内容" * 200
    payload = {
        "phase": "phase1b_fusion",
        "window": {"window_index": 1, "core_range": [1, 7]},
        "source_candidate_ids": ["a-1"],
        "source_rounds": ["A"],
        "source_chapter_indices": ["1", "2", "3"],
        "recommended_scene_count": 9,
        "scene_count_guidance": long_text,
        "candidates": [
            {
                "candidate_id": "a-1",
                "source_round": "A",
                "source_batch_id": "A-1-5",
                "source_batch_index": 1,
                "source_chapter_indices": ["1", "2", "3"],
                "quality": "high",
                "confidence": 0.9,
                "boundary_status": "complete",
                "boundary_reason": long_text,
                "scenes": [
                    {
                        "title": long_text,
                        "goal": long_text,
                        "core_conflict": long_text,
                        "emotional_beat": long_text,
                        "narrative_tag": "imported",
                        "chapter_text": long_text,
                        "content": long_text,
                        "scene_chunks": [
                            {
                                "chapter_index": "1",
                                "start_paragraph": 3,
                                "end_paragraph": 8,
                                "text": long_text,
                            }
                        ],
                    }
                ],
                "evidence_anchors": [long_text] * 8,
                "merge_hints": [long_text] * 8,
                "split_hints": [long_text] * 8,
                "missing_or_uncertain_items": [long_text] * 8,
            }
        ],
    }

    compact = _compact_phase1b_payload(payload)

    assert compact["source_chapter_indices"] == [1, 2, 3]
    assert compact["recommended_scene_count"] == 9
    assert len(compact["scene_count_guidance"]) <= 180
    candidate = compact["candidates"][0]
    assert candidate["candidate_id"] == "a-1"
    assert candidate["source_chapter_indices"] == [1, 2, 3]
    assert len(candidate["boundary_reason"]) <= 180
    assert len(candidate["evidence_anchors"]) == 4
    scene = candidate["scenes"][0]
    assert len(scene["title"]) <= 80
    assert len(scene["goal"]) <= 180
    assert scene["scene_chunks"] == [
        {"chapter_index": "1", "start_paragraph": 3, "end_paragraph": 8}
    ]
    assert "chapter_text" not in str(compact)
    assert "content" not in str(compact).lower()


def test_compact_phase1b_payload_uses_project_compact_text_limit():
    long_text = "目标" * 80
    payload = {
        "phase": "phase1b_fusion",
        "source_chapter_indices": [1],
        "scene_count_guidance": long_text,
        "candidates": [
            {
                "candidate_id": "a-1",
                "source_chapter_indices": [1],
                "boundary_reason": long_text,
                "scenes": [{"title": long_text, "goal": long_text}],
            }
        ],
    }

    compact = _compact_phase1b_payload(
        payload,
        project_settings={"deep_import": {"phase1b": {"compact_text_limit": 40}}},
    )

    assert len(compact["scene_count_guidance"]) <= 40
    assert len(compact["candidates"][0]["boundary_reason"]) <= 40
    assert len(compact["candidates"][0]["scenes"][0]["goal"]) <= 40
    assert len(compact["candidates"][0]["scenes"][0]["title"]) <= 80


def test_phase1a_scene_max_tokens_env_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modules.imports import workflow_llm_adapters

    monkeypatch.delenv("PHASE1A_SCENE_MAX_TOKENS", raising=False)
    assert workflow_llm_adapters._phase1a_scene_max_tokens(8192) == 8192

    monkeypatch.setenv("PHASE1A_SCENE_MAX_TOKENS", "4096")
    assert workflow_llm_adapters._phase1a_scene_max_tokens(8192) == 4096

    monkeypatch.setenv("PHASE1A_SCENE_MAX_TOKENS", "nope")
    assert workflow_llm_adapters._phase1a_scene_max_tokens(8192) == 8192


def test_phase1a_structured_max_fix_attempts_env_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modules.imports import workflow_llm_adapters

    monkeypatch.delenv("PHASE1A_STRUCTURED_MAX_FIX_ATTEMPTS", raising=False)
    assert workflow_llm_adapters._phase1a_structured_max_fix_attempts() == 1

    monkeypatch.setenv("PHASE1A_STRUCTURED_MAX_FIX_ATTEMPTS", "0")
    assert workflow_llm_adapters._phase1a_structured_max_fix_attempts() == 0

    monkeypatch.setenv("PHASE1A_STRUCTURED_MAX_FIX_ATTEMPTS", "2")
    assert workflow_llm_adapters._phase1a_structured_max_fix_attempts() == 2


def test_deep_import_structured_call_old_workflow_paths_match() -> None:
    from modules.imports import workflow, workflow_llm_adapters

    assert (
        workflow._run_deep_import_structured_call
        is workflow_llm_adapters._run_deep_import_structured_call
    )


@pytest.mark.asyncio
async def test_deep_import_structured_call_uses_configured_fix_attempts(monkeypatch):
    captured: dict[str, object] = {}

    class FakeClient:
        async def generate_structured(self, request, schema, **kwargs):
            del request
            captured.update(kwargs)
            return schema.model_validate(
                {
                    "scenes": [
                        {
                            "title": "候选",
                            "scene_chunks": [{"chapter_index": 1}],
                        }
                    ]
                }
            )

    monkeypatch.setenv("DEEP_IMPORT_STRUCTURED_MAX_FIX_ATTEMPTS", "3")

    await _run_deep_import_structured_call(
        FakeClient(),
        object(),
        SceneCandidateOutput,
        transport_retries=False,
        fix_prompt="fix",
        timeout_seconds=1,
    )

    assert captured["max_fix_attempts"] == 3
    assert captured["transport_retries"] is False
    assert captured["fix_prompt"] == "fix"
    assert "scenes" in captured["partial_list_fields"]
    assert "missing_or_uncertain_items" in captured["partial_list_fields"]
    assert captured["format_repair_attempts"] == 1


def test_diagnostic_samples_keep_chapter_locator_fields():
    samples = DeepImportWorkflow._diagnostic_samples(
        [
            {
                "attempts": 2,
                "final_status": "failed",
                "final_error_type": "timeout",
                "chapter_index": 3,
                "source_batch_id": "S-0003",
                "diagnostics": [
                    {
                        "error_type": "timeout",
                        "message": "slow",
                    }
                ],
            }
        ]
    )

    assert samples == [
        {
            "attempts": 2,
            "final_status": "failed",
            "final_error_type": "timeout",
            "chapter_index": 3,
            "source_batch_id": "S-0003",
            "last_error_type": "timeout",
            "last_message": "slow",
        }
    ]


@pytest.mark.asyncio
async def test_phase1b_llm_prompt_requires_compact_scene_contract(monkeypatch):
    captured: dict[str, object] = {}

    async def fake_structured_call(client, request, schema, **kwargs):
        del client, schema
        captured["request"] = request
        captured["kwargs"] = kwargs
        return {"scenes": []}

    monkeypatch.setattr(
        "modules.imports.workflow_llm_adapters._run_deep_import_structured_call",
        fake_structured_call,
    )

    await _Phase1bSceneFusionLLM(
        {
            "llm": {
                "api_key": "sk-test-only",
                "base_url": "https://llm.test/v1",
                "model": "test-model",
            }
        }
    )(
        {
            "phase": "phase1b_fusion",
            "window": {"window_index": 1, "core_range": [1, 7]},
            "source_candidate_ids": ["a-1"],
            "source_rounds": ["A"],
            "source_chapter_indices": list(range(1, 8)),
            "recommended_scene_count": 9,
            "scene_count_guidance": "完整 1-7 章样本至少 9 个 Scene",
            "candidates": [
                {
                    "candidate_id": "a-1",
                    "source_round": "A",
                    "source_chapter_indices": list(range(1, 8)),
                    "quality": "high",
                    "scenes": [
                        {
                            "title": "跨章候选",
                            "goal": "覆盖关键事件",
                            "scene_chunks": [{"chapter_index": 1}],
                        }
                    ],
                }
            ],
        }
    )

    request = captured["request"]
    system_content = request.messages[0].content
    user_content = request.messages[1].content
    kwargs = captured["kwargs"]

    assert "目标输出9个Scene" in system_content
    assert "必须覆盖1-7章" in system_content
    assert (
        "每个Scene只输出短字段：title、goal、must_happen、must_not_happen、scene_chunks"
    ) in system_content
    assert "不要重写成长摘要" in system_content
    assert "不要补 core_conflict、emotional_beat、narrative_tag" in system_content
    assert "scene_chunks 内必须有 chapter_index" in system_content
    assert "source_chapter_indices 并集必须覆盖" in system_content
    assert "不要拆散同一目标/冲突/行动链延续的跨章 Scene" in user_content
    assert '"scene_chunks":[{"chapter_index":1}]' in user_content
    assert request.max_tokens == 6144
    assert kwargs["timeout_seconds"] == 90


@pytest.mark.asyncio
async def test_phase1b_llm_uses_compact_budget_for_regular_window(monkeypatch):
    captured: dict[str, object] = {}

    async def fake_structured_call(client, request, schema, **kwargs):
        del client, schema
        captured["request"] = request
        captured["kwargs"] = kwargs
        return {"scenes": []}

    monkeypatch.setenv("PHASE01_SCENE_MAX_TOKENS", "8192")
    monkeypatch.delenv("PHASE1B_REDUCER_MAX_TOKENS", raising=False)
    monkeypatch.delenv("PHASE1B_REDUCER_TIMEOUT_SECONDS", raising=False)
    monkeypatch.setattr(
        "modules.imports.workflow_llm_adapters._run_deep_import_structured_call",
        fake_structured_call,
    )

    await _Phase1bSceneFusionLLM(
        {
            "llm": {
                "api_key": "sk-test-only",
                "base_url": "https://llm.test/v1",
                "model": "test-model",
            }
        }
    )(
        {
            "phase": "phase1b_fusion",
            "window": {"window_index": 1, "core_range": [11, 20]},
            "source_candidate_ids": ["a-1"],
            "source_rounds": ["A"],
            "source_chapter_indices": list(range(9, 23)),
            "recommended_scene_count": 14,
            "candidates": [
                {
                    "candidate_id": "a-1",
                    "source_round": "A",
                    "source_chapter_indices": list(range(9, 23)),
                    "quality": "high",
                    "scenes": [
                        {
                            "title": "候选",
                            "goal": "覆盖关键事件",
                            "scene_chunks": [{"chapter_index": 9}],
                        }
                    ],
                }
            ],
        }
    )

    request = captured["request"]
    kwargs = captured["kwargs"]
    assert request.max_tokens == 128
    assert "use_primary_round" in request.messages[0].content
    assert "candidates=" in request.messages[1].content
    assert "payload=" not in request.messages[1].content
    assert kwargs["timeout_seconds"] == 45


@pytest.mark.asyncio
async def test_phase1c_llm_inherits_effective_token_budget_and_uses_360_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def fake_structured_call(client, request, schema, **kwargs):
        del client, schema
        captured["request"] = request
        captured["kwargs"] = kwargs
        return {
            "decision": "keep_separate",
            "confidence": 0.9,
            "reason": "independent scenes",
        }

    monkeypatch.delenv("PHASE1C_DECISION_MAX_TOKENS", raising=False)
    monkeypatch.delenv("PHASE1C_TIMEOUT_SECONDS", raising=False)
    monkeypatch.setattr(
        "modules.imports.workflow_llm_adapters._run_deep_import_structured_call",
        fake_structured_call,
    )

    await _Phase1cSceneFusionLLM(
        {
            "llm": {
                "api_key": "sk-test-only",
                "base_url": "https://llm.test/v1",
                "model": "test-model",
                "max_tokens": 12_000,
            }
        }
    )({"left": {}, "right": {}, "suggestion_kind": "cross_chapter"})

    request = captured["request"]
    kwargs = captured["kwargs"]
    assert request.max_tokens == 12_000
    assert kwargs["timeout_seconds"] == 360

    captured.clear()
    await _Phase1cSceneFusionLLM(
        {
            "llm": {
                "api_key": "sk-test-only",
                "base_url": "https://llm.test/v1",
                "model": "test-model",
                "max_tokens": 12_000,
            },
            "deep_import": {
                "phase1c": {
                    "decision_max_tokens": 4096,
                    "timeout_seconds": 444,
                }
            },
        }
    )({"left": {}, "right": {}, "suggestion_kind": "cross_chapter"})

    request = captured["request"]
    kwargs = captured["kwargs"]
    assert request.max_tokens == 4096
    assert kwargs["timeout_seconds"] == 444


def test_phase1b_decision_materializer_distributes_missing_chunks() -> None:
    output = _materialize_phase1b_decision_output(
        {
            "window": {"core_range": [106, 110]},
            "candidates": [
                {
                    "candidate_id": "a-1",
                    "source_round": "A",
                    "source_chapter_indices": [106, 107, 108, 109, 110],
                    "scenes": [
                        {"title": "佛尔思", "goal": "沙龙与营救请求"},
                        {"title": "推理", "goal": "查尼斯门事件推理"},
                        {"title": "深夜", "goal": "值守异常"},
                        {"title": "画家克莱恩", "goal": "委托调查"},
                        {"title": "确认", "goal": "圣堂确认问题"},
                    ],
                }
            ],
        },
        decision=_Phase1bDecisionOutput(use_primary_round=True),
    )

    assert [scene.source_chapter_indices for scene in output.scenes] == [
        [106],
        [107],
        [108],
        [109],
        [110],
    ]


def test_phase1b_decision_materializer_preserves_explicit_cross_chapter_chunks() -> None:
    output = _materialize_phase1b_decision_output(
        {
            "window": {"core_range": [113, 115]},
            "candidates": [
                {
                    "candidate_id": "a-1",
                    "source_round": "A",
                    "source_chapter_indices": [113, 114, 115],
                    "scenes": [
                        {
                            "title": "塔罗会规则",
                            "goal": "塔罗会规则延续",
                            "scene_chunks": [
                                {"chapter_index": 113},
                                {"chapter_index": 114},
                            ],
                        },
                        {
                            "title": "诈骗案调查",
                            "goal": "兰尔乌斯线索",
                            "scene_chunks": [{"chapter_index": 115}],
                        },
                    ],
                }
            ],
        },
        decision=_Phase1bDecisionOutput(use_primary_round=True),
    )

    assert [scene.source_chapter_indices for scene in output.scenes] == [
        [113, 114],
        [115],
    ]
    assert [
        [chunk.chapter_index for chunk in scene.scene_chunks] for scene in output.scenes
    ] == [[113, 114], [115]]


@pytest.mark.asyncio
async def test_phase1b_llm_decision_schema_failure_repairs_to_primary_round(
    monkeypatch,
):
    async def fake_structured_call(client, request, schema, **kwargs):
        del client, request, schema, kwargs
        raise ValueError("truncated decision")

    monkeypatch.setattr(
        "modules.imports.workflow_llm_adapters._run_deep_import_structured_call",
        fake_structured_call,
    )

    output = await _Phase1bSceneFusionLLM()(
        {
            "phase": "phase1b_fusion",
            "window": {"window_index": 1, "core_range": [11, 20]},
            "source_candidate_ids": ["a-1", "b-1"],
            "source_rounds": ["A", "B"],
            "source_chapter_indices": list(range(11, 21)),
            "recommended_scene_count": 10,
            "candidates": [
                {
                    "candidate_id": "a-1",
                    "source_round": "A",
                    "source_chapter_indices": list(range(11, 21)),
                    "quality": "high",
                    "scenes": [
                        {
                            "title": f"A候选{chapter}",
                            "goal": "覆盖核心章节",
                            "scene_chunks": [{"chapter_index": chapter}],
                        }
                        for chapter in range(11, 21)
                    ],
                },
                {
                    "candidate_id": "b-1",
                    "source_round": "B",
                    "source_chapter_indices": list(range(11, 21)),
                    "quality": "high",
                    "scenes": [
                        {
                            "title": "B候选",
                            "goal": "重复覆盖核心章节",
                            "scene_chunks": [{"chapter_index": 11}],
                        }
                    ],
                },
            ],
        }
    )

    assert [scene.source_candidate_ids for scene in output.scenes] == [["a-1"]] * 10
    assert output.discarded_candidates == {"b-1": "duplicate_candidate"}


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
    )
    db_session.add(task)
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

    async def _commit(_db, _novel_id, _candidates, *, workflow_id):
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
        "modules.context.facade.build_snapshot_health_summary",
        _snapshot_health_summary,
    )


class TestDeepImportSchema:
    """测试深度导入进度数据结构"""

    def test_default_progress(self):
        p = DeepImportProgress()
        assert p.phase == "pending"
        assert p.quality_status == "pending"
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

    def test_deep_import_progress_exposes_resilient_result_contract(self):
        progress = DeepImportProgress(workflow_id="task-1")
        progress.current_phase = "phase0_plan"
        progress.current_round = "A"
        progress.current_chapter_range = "1-5"
        progress.current_chapter = 3
        progress.current_scene_candidate_id = "scene-candidate-1"
        progress.current_window = "chapters:1-5"
        progress.current_operation = "scene_planning"
        progress.current_item = {"kind": "batch", "batch_id": "A-0001"}
        progress.phase_timeline = [
            {
                "phase": "phase0_plan",
                "status": "running",
                "started_at": "2026-06-30T10:00:00+00:00",
            }
        ]
        progress.progress_events = [
            {
                "event": "phase_started",
                "phase": "phase0_plan",
                "status": "running",
            }
        ]
        progress.acceptance_checks = [
            {
                "name": "phase0_coverage",
                "phase": "phase0_plan",
                "ok": True,
            }
        ]
        progress.diagnostic_counts = {"scene_count": 0}
        progress.last_error = {
            "phase": "phase0_plan",
            "error_kind": "network",
            "message": "connection failed",
        }
        progress.quality_stats["phase0"] = {
            "total_batches": 4,
            "completed_batches": 1,
            "success": 1,
            "final_422_rate": 0.0,
        }
        progress.checkpoints["phase0"] = {"completed_batches": [0]}
        progress.recovery_summary["last_checkpoint"] = "phase0:batch:0"
        progress.interrupted = True
        progress.recoverable = True
        progress.recovery_required = True
        progress.interrupted_at = "2026-06-30T10:00:00Z"
        progress.last_heartbeat_at = "2026-06-30T09:59:00Z"
        progress.degraded_reason = "phase1b_422_rate_exceeded"
        progress.phase1a_fallback = True

        dumped = progress.model_dump(mode="json")
        result = DeepImportOrchestrator._result_from_progress(progress)

        for payload in (dumped, result):
            assert payload["current_phase"] == "phase0_plan"
            assert payload["current_round"] == "A"
            assert payload["current_chapter_range"] == "1-5"
            assert payload["current_chapter"] == 3
            assert payload["current_scene_candidate_id"] == "scene-candidate-1"
            assert payload["current_window"] == "chapters:1-5"
            assert payload["current_operation"] == "scene_planning"
            assert payload["current_item"]["batch_id"] == "A-0001"
            assert payload["phase_timeline"][0]["phase"] == "phase0_plan"
            assert payload["progress_events"][0]["event"] == "phase_started"
            assert payload["acceptance_checks"][0]["name"] == "phase0_coverage"
            assert payload["diagnostic_counts"]["scene_count"] == 0
            assert payload["last_error"]["error_kind"] == "network"
            assert payload["quality_stats"]["phase0"]["total_batches"] == 4
            assert payload["checkpoints"]["phase0"]["completed_batches"] == [0]
            assert payload["recovery_summary"]["last_checkpoint"] == "phase0:batch:0"
            assert payload["interrupted"] is True
            assert payload["recoverable"] is True
            assert payload["recovery_required"] is True
            assert payload["interrupted_at"] == "2026-06-30T10:00:00Z"
            assert payload["last_heartbeat_at"] == "2026-06-30T09:59:00Z"
            assert payload["degraded_reason"] == "phase1b_422_rate_exceeded"
            assert payload["phase1a_fallback"] is True

    def test_progress_events_are_sanitized_and_capped(self):
        progress = DeepImportProgress()

        for index in range(205):
            record_progress_event(
                progress,
                "llm_call",
                phase="phase0_prefetch",
                details={
                    "index": index,
                    "raw_prompt": "do not persist",
                    "nested": {
                        "messages": [{"content": "chapter body"}],
                        "safe_count": 1,
                    },
                    "api_key": "sk-secret",
                },
            )

        assert len(progress.progress_events) == 200
        assert progress.progress_events[0]["truncated"] is True
        assert progress.progress_events[0]["dropped_event_count"] == 5
        details = progress.progress_events[-1]["details"]
        assert "raw_prompt" not in details
        assert details["nested"] == {"safe_count": 1}
        assert details["api_key"] == "<redacted>"

    def test_progress_phase_timeline_is_capped_with_recent_entries(self):
        progress = DeepImportProgress()
        progress.phase_timeline = [
            {"phase": f"phase-{index}", "status": "done"} for index in range(125)
        ]

        from modules.imports.workflow_progress import DeepImportProgressTracker

        DeepImportProgressTracker.refresh_diagnostic_counts(progress)

        assert len(progress.phase_timeline) == 120
        assert progress.phase_timeline[0]["phase"] == "phase-5"
        assert progress.phase_timeline[0]["truncated"] is True
        assert progress.phase_timeline[0]["dropped_phase_timeline_count"] == 5
        assert progress.phase_timeline[-1]["phase"] == "phase-124"

    def test_acceptance_checks_are_capped_when_recorded_and_accumulate_drops(self):
        progress = DeepImportProgress()
        progress.acceptance_checks = [
            {
                "name": "previous-boundary",
                "ok": True,
                "dropped_acceptance_check_count": 3,
            }
        ]

        for index in range(205):
            record_acceptance_check(
                progress,
                f"check-{index}",
                ok=True,
                details={"index": index},
            )

        assert len(progress.acceptance_checks) == 200
        assert progress.acceptance_checks[0]["name"] == "check-5"
        assert progress.acceptance_checks[0]["truncated"] is True
        assert progress.acceptance_checks[0]["dropped_acceptance_check_count"] == 9
        assert progress.acceptance_checks[-1]["name"] == "check-204"

    def test_phase_errors_are_capped_by_result_payload_fallback(self):
        progress = DeepImportProgress()
        progress.phase_errors = [
            {
                "phase": f"phase-{index}",
                "error_kind": "phase_failed",
                "message": "failed",
                "details": {"index": index},
            }
            for index in range(125)
        ]

        result = DeepImportOrchestrator._result_from_progress(progress)

        assert len(result["phase_errors"]) == 120
        assert result["phase_errors"][0]["phase"] == "phase-5"
        assert result["phase_errors"][0]["truncated"] is True
        assert result["phase_errors"][0]["dropped_phase_error_count"] == 5
        assert result["phase_errors"][0]["details"] == {"index": 5}
        assert result["phase_errors"][-1]["phase"] == "phase-124"


class TestDeepImportWorkflowAutoRun:
    """测试全自动三步流程"""

    def test_phase2_stats_include_batch_boundary_and_action_counts(self):
        stats = phase2_quality_stats(
            {
                "total_created": 3,
                "total_relations": 2,
                "total_aliases": 1,
                "total_deltas": 4,
                "total_scenes": 24,
                "completed_scenes": 24,
                "phase2_batches_total": 2,
                "phase2_batches_completed": 2,
                "phase2_batch_size_scenes": 12,
                "phase2_batch_concurrency": 6,
                "phase2_boundary_windows_total": 1,
                "phase2_boundary_windows_completed": 1,
                "phase2_action_counts": {"create_new": 3, "ignore": 1},
                "phase2_dedup_counts": {"checked": 3, "skipped": 1},
                "phase2_boundary_supplement_counts": {
                    "created": 1,
                    "aliases": 1,
                    "relations": 0,
                    "link_suggestions": 1,
                    "conflicts": 0,
                    "failed": 0,
                },
                "structured_format_diagnostics": [
                    {
                        "kind": "partial_list_validation",
                        "field": "entities",
                        "kept": 2,
                        "skipped": 1,
                    },
                    {
                        "kind": "format_repair",
                        "status": "succeeded",
                    },
                ],
                "alias_relation_format_diagnostics": [
                    {
                        "kind": "structured_parse",
                        "strategy": "markdown_code_block",
                    }
                ],
                "phase2_failed_batches": [],
                "failed_scene_ids": ["scene-3"],
                "phase2_degraded_batches": [],
                "alias_relation_skipped": True,
                "alias_relation_skip_reason": (
                    "phase2_alias_relation_supplement_disabled"
                ),
            }
        )

        assert stats["phase2_batches_total"] == 2
        assert stats["phase2_batches_completed"] == 2
        assert stats["phase2_batch_size_scenes"] == 12
        assert stats["phase2_batch_concurrency"] == 6
        assert stats["phase2_boundary_windows_total"] == 1
        assert stats["phase2_boundary_windows_completed"] == 1
        assert stats["phase2_action_counts"]["create_new"] == 3
        assert stats["phase2_dedup_counts"]["skipped"] == 1
        assert stats["phase2_boundary_supplement_counts"]["created"] == 1
        assert stats["structured_format_diagnostics"]["total"] == 2
        assert (
            stats["structured_format_diagnostics"]["kind_counts"][
                "partial_list_validation"
            ]
            == 1
        )
        assert stats["structured_format_diagnostics"]["skipped_items"] == 1
        assert stats["structured_format_diagnostics"]["format_repair_succeeded"] == 1
        assert stats["alias_relation_format_diagnostics"]["total"] == 1
        assert stats["failed_scene_ids"] == ["scene-3"]
        assert stats["alias_relation_skipped"] is True
        assert (
            stats["alias_relation_skip_reason"]
            == "phase2_alias_relation_supplement_disabled"
        )

    def test_phase2_world_normalize_classifies_invalid_scene_refs(self):
        scene_a_id = str(uuid.uuid4())
        scene_b_id = str(uuid.uuid4())
        unknown_uuid = str(uuid.uuid4())
        scenes_by_id = {
            scene_a_id: {"id": scene_a_id, "scene_index": 11, "chapter_ids": ["1"]},
            scene_b_id: {"id": scene_b_id, "scene_index": 22, "chapter_ids": ["2"]},
        }
        output = Phase2WorldExtractionOutput.model_validate(
            {
                "objects": [
                    {
                        "name": "灰雾空间",
                        "entity_type": "location",
                        "supporting_scene_ids": [f" {scene_a_id} ", "22"],
                    },
                    {
                        "name": "空证据对象",
                        "entity_type": "item",
                        "supporting_scene_ids": [],
                    },
                ],
                "relations": [
                    {
                        "source_name": "克莱恩",
                        "target_name": "未知组织",
                        "relation_type": "member_of",
                        "supporting_scene_ids": [unknown_uuid],
                    }
                ],
                "deltas": [
                    {
                        "subject_name": "灰雾空间",
                        "category": "state",
                        "field": "status",
                        "new": "activated",
                        "supporting_scene_ids": ["chapter-1"],
                    }
                ],
                "uncertain_items": [
                    {
                        "description": "疑似一次性设定",
                        "reason": "证据不足",
                        "supporting_scene_ids": ["普通文本"],
                    }
                ],
            }
        )

        normalized, invalid_count, overlap_only, diagnostics = _normalize_world_output(
            output,
            scenes_by_id=scenes_by_id,
            owned_scene_ids={scene_a_id},
            diagnostics_context={
                "window_id": "W-1",
                "chapter_indices": [1, 2],
                "owned_chapter_indices": [1],
                "available_scene_ids": [scene_a_id, scene_b_id],
                "owned_scene_ids": [scene_a_id],
                "scene_index_values": {"11", "22"},
                "chapter_values": {"1", "2"},
                "available_id_source_counts": {"id": 2},
            },
        )

        assert invalid_count == 5
        assert overlap_only == 0
        assert [item.name for item in normalized.objects] == ["灰雾空间"]
        assert normalized.objects[0].supporting_scene_ids == [scene_a_id]
        assert normalized.objects[0].needs_review is True
        assert normalized.relations == []
        assert normalized.deltas == []
        assert normalized.uncertain_items[0].supporting_scene_ids == []
        assert diagnostics["category_counts"] == {
            "scene_index_like": 1,
            "empty_after_normalize": 1,
            "uuid_like_but_unknown": 1,
            "not_in_available_ids": 1,
            "non_uuid_text": 1,
        }
        assert diagnostics["available_id_source_counts"] == {"id": 2}
        sample = diagnostics["samples"][0]
        assert sample["window_id"] == "W-1"
        assert "summary" not in sample
        assert "description" not in sample
        assert "raw_output" not in sample

    def test_phase2_stats_keep_only_aggregated_diagnostics(self):
        stats = phase2_quality_stats(
            {
                "phase2_world_window_concurrency": 20,
                "phase2_batch_concurrency": 20,
                "phase2_window_diagnostics": {
                    "samples": [
                        {
                            "source_batch_id": "W-1",
                            "elapsed_ms_total": 1200,
                            "attempts": 1,
                            "final_status": "success",
                            "final_error_type": None,
                        },
                        {
                            "source_batch_id": "W-2",
                            "elapsed_ms_total": 3000,
                            "attempts": 2,
                            "final_status": "failed",
                            "final_error_type": "timeout",
                        },
                    ]
                },
                "phase2_invalid_scene_ref_diagnostics": {
                    "category_counts": {"scene_index_like": 2},
                    "sampled_count": 1,
                    "truncated": False,
                    "available_id_source_counts": {"id": 3},
                    "samples": [{"raw_ids": ["1"]}],
                },
            }
        )

        assert stats["phase2_world_window_concurrency"] == 20
        assert stats["phase2_window_diagnostics"]["total"] == 2
        assert stats["phase2_window_diagnostics"]["elapsed_ms_total"] == 4200
        assert stats["phase2_window_diagnostics"]["failed_window_ids"] == ["W-2"]
        assert stats["invalid_scene_ref_categories"] == {"scene_index_like": 2}
        assert stats["invalid_scene_ref_sample_count"] == 1
        assert stats["available_id_source_counts"] == {"id": 3}
        assert "samples" not in stats["invalid_scene_ref_categories"]

    def test_phase2_artifact_stores_budgeted_sanitized_diagnostics(self):
        progress = DeepImportProgress()
        artifact = add_phase_artifact(
            progress,
            "entity_extraction",
            start_chapter=1,
            end_chapter=2,
            status="completed",
            quality_stats={
                "total_created": 1,
                "phase2_window_diagnostics": {"total": 1},
            },
            diagnostics={
                "phase2_windows": {
                    "samples": [
                        {
                            "source_batch_id": "W-1",
                            "token_attempts": [
                                {
                                    "attempts": 1,
                                    "diagnostics": [
                                        {
                                            "attempt": 1,
                                            "status": "success",
                                            "message": "must not persist",
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                    "prompt": "must not persist",
                    "content": "must not persist",
                },
                "invalid_scene_refs": {
                    "samples": [{"raw_ids": ["1"], "body_text": "must not persist"}],
                },
            },
        )

        assert artifact["quality_stats"]["total_created"] == 1
        assert "phase2_window_diagnostics" not in artifact["quality_stats"]
        assert (
            artifact["diagnostics"]["phase2_windows"]["samples"][0]["source_batch_id"]
            == "W-1"
        )
        assert "prompt" not in artifact["diagnostics"]["phase2_windows"]
        assert "content" not in artifact["diagnostics"]["phase2_windows"]
        invalid_sample = artifact["diagnostics"]["invalid_scene_refs"]["samples"][0]
        assert invalid_sample == {"raw_ids": ["1"]}

    def test_phase2_world_window_concurrency_defaults_and_overrides(self, monkeypatch):
        from modules.imports.entity_extraction.scene_entity_config import (
            phase2_project_settings_context,
        )

        monkeypatch.delenv("PHASE2_WORLD_WINDOW_CONCURRENCY", raising=False)

        assert PHASE2_WORLD_WINDOW_CONCURRENCY == 20
        assert DEEP_IMPORT_DEFAULT_SETTINGS["phase2"]["world_window_concurrency"] == 20
        assert DEEP_IMPORT_DEFAULT_SETTINGS["phase0"]["max_tokens_per_input_char"] == 1.0
        assert (
            DEEP_IMPORT_DEFAULT_SETTINGS["phase2"]["world_max_tokens_per_source_char"]
            == 1.0
        )
        assert Phase2WorldExtractor(lambda payload: payload).concurrency == 20

        with phase2_project_settings_context(
            {"deep_import": {"phase2": {"world_window_concurrency": 7}}}
        ):
            assert Phase2WorldExtractor(lambda payload: payload).concurrency == 7

        monkeypatch.setenv("PHASE2_WORLD_WINDOW_CONCURRENCY", "5")
        with phase2_project_settings_context(
            {"deep_import": {"phase2": {"world_window_concurrency": 7}}}
        ):
            assert Phase2WorldExtractor(lambda payload: payload).concurrency == 5

    @pytest.mark.asyncio
    async def test_phase2_world_window_progress_callback_is_serialized(self):
        scene_ids = [str(uuid.uuid4()) for _ in range(4)]
        chapters = [
            {"chapter_index": index, "title": f"第{index}章", "content": "正文"}
            for index in range(1, 5)
        ]
        scenes = [
            {
                "id": scene_id,
                "scene_index": index,
                "chapter_ids": [str(index)],
                "title": f"Scene {index}",
            }
            for index, scene_id in enumerate(scene_ids, start=1)
        ]
        windows = [
            SceneWindowPlan(
                window_index=index,
                window_id=f"W-{index}",
                covered_start=index,
                covered_end=index,
                owned_start=index,
                owned_end=index,
                chapter_indices=[index],
                owned_chapter_indices=[index],
                input_chars=100,
            )
            for index in range(1, 5)
        ]
        active_llm = 0
        max_active_llm = 0
        callback_active = False
        callback_overlap = False
        llm_barrier = asyncio.Event()

        async def fake_llm(payload):
            nonlocal active_llm, max_active_llm
            active_llm += 1
            max_active_llm = max(max_active_llm, active_llm)
            if active_llm >= 2:
                llm_barrier.set()
            await llm_barrier.wait()
            active_llm -= 1
            return Phase2WorldExtractionOutput.model_validate(
                {
                    "objects": [
                        {
                            "name": f"对象{payload['window']['window_index']}",
                            "entity_type": "other",
                            "supporting_scene_ids": [payload["owned_scene_ids"][0]],
                        }
                    ]
                }
            )

        async def on_scene_progress(**_kwargs):
            nonlocal callback_active, callback_overlap
            if callback_active:
                callback_overlap = True
            callback_active = True
            callback_active = False

        extractor = Phase2WorldExtractor(fake_llm, concurrency=20)

        await extractor._run_windows(
            windows,
            chapters,
            scenes,
            on_scene_progress=on_scene_progress,
            total_owned_scenes=len(scenes),
        )

        assert max_active_llm > 1
        assert callback_overlap is False

    @pytest.mark.asyncio
    async def test_extract_entities_by_scene_propagates_handler_errors(self):
        workflow = DeepImportWorkflow()
        workflow._agent_project_settings = {}

        async def broken_handler(*_args, **_kwargs):
            raise RuntimeError("phase2 boom")

        with patch(
            "modules.imports.workflow._container_get",
            return_value=broken_handler,
            autospec=True,
        ):
            with pytest.raises(RuntimeError, match="phase2 boom"):
                await workflow._extract_entities_by_scene(
                    Mock(),
                    "00000000-0000-0000-0000-00000000b201",
                )

    @pytest.mark.asyncio
    async def test_real_db_phase2_routes_through_scene_activation_handler(
        self,
        db_session: AsyncSession,
    ) -> None:
        workflow = DeepImportWorkflow()
        expected = {
            "total_created": 1,
            "activation_version": "import-context-v1",
        }
        handler = AsyncMock(return_value=expected)

        with (
            patch(
                "modules.imports.workflow._container_get",
                return_value=handler,
                autospec=True,
            ),
            patch(
                "modules.imports.workflow._project_settings_for_novel",
                autospec=True,
                return_value={},
            ),
        ):
            result = await workflow._extract_entities_by_scene(
                db_session,
                "00000000-0000-0000-0000-00000000b202",
                workflow_id="wf-activation",
                start_chapter=78,
                end_chapter=80,
            )

        assert result is expected
        handler.assert_awaited_once()
        assert handler.await_args.kwargs["novel_id"].endswith("b202")
        assert handler.await_args.kwargs["start_chapter"] == 78
        assert handler.await_args.kwargs["end_chapter"] == 80

    @pytest.mark.asyncio
    async def test_pending_to_done(self):
        """pending 直接跑完三步到达 done"""
        workflow = DeepImportWorkflow()
        progress = DeepImportProgress()

        workflow._extract_entities_by_scene = AsyncMock(
            return_value={
                "total_created": 3,
                "total_relations": 1,
                "total_aliases": 2,
                "total_deltas": 2,
                "alias_relation_scenes": 4,
                "alias_relation_failed_scenes": [5],
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
            db=Mock(),
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
        assert result.quality_status == "complete"
        assert result.phase_errors == []
        timeline = {item["phase"]: item for item in result.phase_timeline}
        for phase in (
            "phase0_plan",
            "phase1a_scene_slicing",
            "phase1b_enrichment",
            "scene_commit",
            "entity_extraction",
            "structure_analysis",
        ):
            assert timeline[phase]["status"] == "completed"
            assert timeline[phase]["duration_s"] is not None
        assert result.diagnostic_counts["scene_count"] == 5
        assert result.diagnostic_counts["entity_count"] == 3
        assert result.diagnostic_counts["relation_count"] == 1
        assert result.diagnostic_counts["alias_count"] == 2
        assert result.diagnostic_counts["alias_relation_scenes"] == 4
        assert result.diagnostic_counts["alias_relation_failed_scene_count"] == 1
        assert result.diagnostic_counts["structure_counts"]["threads"] == 2
        assert result.quality_stats["phase3"]["total_threads"] == 2

    @pytest.mark.asyncio
    async def test_scene_auto_extraction_stops_after_scene_commit(self):
        workflow = DeepImportWorkflow()
        progress = DeepImportProgress(
            workflow_type="scene_auto_extraction",
            stage="scenes",
        )
        workflow._commit_fused_scenes = AsyncMock(
            return_value=_scene_commit_result(created_count=2)
        )
        workflow._extract_entities_by_scene = AsyncMock()
        workflow._analyze_structure = AsyncMock()

        db = AsyncMock()
        novel_id = str(uuid.uuid4())
        with patch(
            "modules.imports.workflow_scene_phase._enqueue_rag_reindex_after_scene_commit",
            return_value="task-rag-reindex",
            autospec=True,
        ) as enqueue_rag:
            result = await workflow.run_step(
                db=db,
                novel_id=novel_id,
                start_chapter=1,
                end_chapter=5,
                progress=progress,
                workflow_id="wf-scenes",
                stop_after=DeepImportStep.scene_segmentation,
            )

        assert result.phase == "done"
        assert result.workflow_type == "scene_auto_extraction"
        assert result.stage == "scenes"
        assert result.completed_steps == [DeepImportStep.scene_segmentation.value]
        assert "场景（scene）自动提取完成" in result.message
        assert result.phase_artifacts["phase0_plan"]["counts"]["window_count"] == 1
        assert result.phase_artifacts["phase0_plan"]["counts"]["chapter_count"] == 5
        assert (
            result.phase_artifacts["phase1a_scene_slicing"]["coverage"][
                "coverage_complete"
            ]
            is True
        )
        assert (
            result.phase_artifacts["phase1b_enrichment"]["coverage"]["coverage_complete"]
            is True
        )
        assert result.phase_artifacts["scene_commit"]["counts"]["total_scenes"] == 2
        assert (
            result.quality_stats["scene_commit"]["rag_reindex_task_id"]
            == "task-rag-reindex"
        )
        enqueue_rag.assert_called_once_with(db, novel_id, 1, 5)
        assert any(
            event["event"] == "phase_started" and event["phase"] == "phase0_plan"
            for event in result.progress_events
        )
        assert any(
            check["name"] == "scene_commit_coverage" and check["ok"] is True
            for check in result.acceptance_checks
        )
        workflow._extract_entities_by_scene.assert_not_awaited()
        workflow._analyze_structure.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_scene_auto_extraction_fails_before_commit_when_coverage_missing(
        self,
    ):
        workflow = DeepImportWorkflow()
        progress = DeepImportProgress(
            workflow_type="scene_auto_extraction",
            stage="scenes",
        )
        workflow._run_phase1b_enrichment = AsyncMock(
            return_value=_phase1b_enrichment_result(source_chapter_indices=[1])
        )
        workflow._commit_fused_scenes = AsyncMock()

        result = await workflow.run_step(
            db=AsyncMock(),
            novel_id=str(uuid.uuid4()),
            start_chapter=1,
            end_chapter=5,
            progress=progress,
            workflow_id="wf-scenes",
            stop_after=DeepImportStep.scene_segmentation,
        )

        assert result.phase == "failed"
        assert result.degraded_reason == "missing_chapter_coverage"
        assert result.phase_artifacts["phase1b_enrichment"]["quality_status"] == "failed"
        assert result.phase_artifacts["phase1b_enrichment"]["coverage"][
            "missing_chapters"
        ] == [2, 3, 4, 5]
        workflow._commit_fused_scenes.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_world_object_stage_fails_without_scenes(self):
        workflow = DeepImportWorkflow()
        workflow._scene_chapter_coverage = AsyncMock(
            return_value=_scene_coverage(set(), 1, 5)
        )
        progress = DeepImportProgress(
            workflow_type="world_object_auto_extraction",
            stage="world_objects",
        )

        result = await workflow.run_entity_extraction_only(
            db=AsyncMock(),
            novel_id=str(uuid.uuid4()),
            start_chapter=1,
            end_chapter=5,
            progress=progress,
            workflow_id="wf-world",
        )

        assert result.phase == "failed"
        assert result.quality_status == "failed"
        assert result.degraded_reason == "missing_scene_prerequisite"
        assert "请先执行场景" in result.message
        assert result.phase_artifacts["entity_extraction"]["status"] == "failed"
        assert result.phase_artifacts["entity_extraction"]["coverage"][
            "missing_chapters"
        ] == [1, 2, 3, 4, 5]
        assert any(
            check["name"] == "entity_extraction_missing_scene_prerequisite"
            for check in result.acceptance_checks
        )

    @pytest.mark.asyncio
    async def test_world_object_stage_fails_when_scene_coverage_is_partial(self):
        workflow = DeepImportWorkflow()
        workflow._scene_chapter_coverage = AsyncMock(
            return_value=_scene_coverage({1, 2, 3}, 1, 5)
        )
        workflow._extract_entities_by_scene = AsyncMock()
        progress = DeepImportProgress(
            workflow_type="world_object_auto_extraction",
            stage="world_objects",
        )

        result = await workflow.run_entity_extraction_only(
            db=AsyncMock(),
            novel_id=str(uuid.uuid4()),
            start_chapter=1,
            end_chapter=5,
            progress=progress,
            workflow_id="wf-world",
        )

        assert result.phase == "failed"
        assert result.degraded_reason == "missing_scene_coverage"
        assert "缺少章节" in result.message
        assert result.phase_artifacts["entity_extraction"]["coverage"][
            "missing_chapters"
        ] == [4, 5]
        workflow._extract_entities_by_scene.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_world_object_stage_runs_phase2_only_for_range(self):
        workflow = DeepImportWorkflow()
        workflow._scene_chapter_coverage = AsyncMock(
            return_value=_scene_coverage({2, 3, 4, 5, 6, 7}, 2, 7)
        )
        workflow._extract_entities_by_scene = AsyncMock(
            return_value={
                "total_created": 2,
                "total_aliases": 1,
                "total_relations": 3,
                "total_deltas": 1,
                "total_scenes": 4,
                "completed_scenes": 4,
                "failed_scene_indices": [],
                "checkpoints": {"phase2": {"scenes": []}},
            }
        )
        progress = DeepImportProgress(
            workflow_type="world_object_auto_extraction",
            stage="world_objects",
        )

        result = await workflow.run_entity_extraction_only(
            db=AsyncMock(),
            novel_id="novel-1",
            start_chapter=2,
            end_chapter=7,
            progress=progress,
            workflow_id="wf-world",
        )

        assert result.phase == "done"
        assert DeepImportStep.entity_extraction.value in result.completed_steps
        assert result.quality_stats["phase2"]["total_aliases"] == 1
        assert result.phase_artifacts["entity_extraction"]["counts"]["total_created"] == 2
        workflow._extract_entities_by_scene.assert_awaited_once()
        assert workflow._extract_entities_by_scene.await_args.kwargs["start_chapter"] == 2
        assert workflow._extract_entities_by_scene.await_args.kwargs["end_chapter"] == 7

    @pytest.mark.asyncio
    async def test_plot_structure_stage_allows_missing_world_objects_as_partial(self):
        workflow = DeepImportWorkflow()
        workflow._refresh_snapshot_health_summary = AsyncMock()
        workflow._scene_chapter_coverage = AsyncMock(
            return_value=_scene_coverage({1, 2, 3, 4, 5}, 1, 5)
        )
        workflow._count_world_objects = AsyncMock(return_value=0)
        workflow._analyze_structure = AsyncMock(
            return_value={
                "total_threads": 1,
                "total_arcs": 1,
                "threads": [],
                "arcs": [],
                "extra_sections": {},
            }
        )
        progress = DeepImportProgress(
            workflow_type="plot_structure_auto_extraction",
            stage="plot_structure",
        )

        result = await workflow.run_structure_analysis_only(
            db=AsyncMock(),
            novel_id=str(uuid.uuid4()),
            start_chapter=1,
            end_chapter=5,
            progress=progress,
            workflow_id="wf-plot",
        )

        assert result.phase == "done"
        assert result.quality_status == "partial"
        assert DeepImportStep.structure_analysis.value in result.completed_steps
        assert result.phase_errors[0]["error_kind"] == "missing_world_object_context"
        assert result.phase_artifacts["structure_analysis"]["status"] == "degraded"
        assert any(
            check["name"] == "structure_analysis_missing_world_object_context"
            for check in result.acceptance_checks
        )

    @pytest.mark.asyncio
    async def test_plot_structure_stage_fails_when_scene_coverage_is_partial(self):
        workflow = DeepImportWorkflow()
        workflow._scene_chapter_coverage = AsyncMock(
            return_value=_scene_coverage({1, 2, 3}, 1, 5)
        )
        workflow._count_world_objects = AsyncMock()
        workflow._analyze_structure = AsyncMock()
        progress = DeepImportProgress(
            workflow_type="plot_structure_auto_extraction",
            stage="plot_structure",
        )

        result = await workflow.run_structure_analysis_only(
            db=AsyncMock(),
            novel_id=str(uuid.uuid4()),
            start_chapter=1,
            end_chapter=5,
            progress=progress,
            workflow_id="wf-plot",
        )

        assert result.phase == "failed"
        assert result.degraded_reason == "missing_scene_coverage"
        assert result.phase_artifacts["structure_analysis"]["coverage"][
            "missing_chapters"
        ] == [4, 5]
        workflow._count_world_objects.assert_not_awaited()
        workflow._analyze_structure.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_world_object_stage_repairs_phase2a_failures_with_checkpoints(self):
        workflow = DeepImportWorkflow()
        workflow._scene_chapter_coverage = AsyncMock(
            return_value=_scene_coverage({1, 2, 3}, 1, 3)
        )
        workflow._extract_entities_by_scene = AsyncMock(
            side_effect=[
                {
                    "total_created": 1,
                    "total_aliases": 0,
                    "total_relations": 0,
                    "total_deltas": 1,
                    "total_scenes": 10,
                    "completed_scenes": 9,
                    "failed_scene_indices": [3],
                    "phase2_failed_batches": [1],
                    "degraded": True,
                    "error_kind": "timeout",
                    "checkpoints": {
                        "phase2": {
                            "scenes": [
                                {"scene_id": "s1", "status": "done"},
                                {"scene_id": "s2", "status": "done"},
                                {"scene_id": "s3", "status": "failed"},
                            ]
                        }
                    },
                },
                {
                    "total_created": 1,
                    "total_aliases": 0,
                    "total_relations": 0,
                    "total_deltas": 1,
                    "total_scenes": 10,
                    "completed_scenes": 10,
                    "failed_scene_indices": [],
                    "phase2_failed_batches": [],
                    "degraded": False,
                    "checkpoints": {
                        "phase2": {
                            "scenes": [
                                {"scene_id": "s1", "status": "done"},
                                {"scene_id": "s2", "status": "done"},
                                {"scene_id": "s3", "status": "done"},
                            ]
                        }
                    },
                },
            ]
        )
        progress = DeepImportProgress(
            workflow_type="world_object_auto_extraction",
            stage="world_objects",
        )

        result = await workflow.run_entity_extraction_only(
            db=AsyncMock(),
            novel_id="novel-1",
            start_chapter=1,
            end_chapter=3,
            progress=progress,
            workflow_id="wf-world",
        )

        assert result.phase == "done"
        assert workflow._extract_entities_by_scene.await_count == 2
        assert result.phase_artifacts["entity_extraction"]["repair"]["attempted"] is True
        assert any(
            event["event"] == "artifact_produced"
            and event["phase"] == "entity_extraction"
            for event in result.progress_events
        )
        assert result.quality_stats["phase2"]["failed_scene_count"] == 0

    @pytest.mark.asyncio
    async def test_count_world_objects_includes_candidate_context(self):
        with patch(
            "modules.world.facade.count_entities",
            autospec=True,
        ) as count:
            count.return_value = 3

            result = await DeepImportWorkflow._count_world_objects(
                AsyncMock(),
                "novel-1",
            )

        assert result == 3
        assert count.await_args.kwargs["status_filter"] == [
            "candidate",
            "draft",
            "canonical",
        ]

    @pytest.mark.asyncio
    async def test_run_step_merges_snapshot_health_summary_and_audit_alias(self):
        """Phase 2/3 的快照摘要应进入 workflow progress 并保留兼容 alias。"""
        workflow = DeepImportWorkflow()
        progress = DeepImportProgress()

        workflow._commit_fused_scenes = AsyncMock(
            return_value=_scene_commit_result(created_count=1)
        )
        workflow._extract_entities_by_scene = AsyncMock(
            return_value={
                "total_created": 1,
                "total_relations": 0,
                "total_deltas": 0,
                "audit_summary": {
                    "entity_extraction": {
                        "snapshot_count": 1,
                        "succeeded": 1,
                        "failed": 0,
                    }
                },
                "snapshot_health_summary": {
                    "novel_id": "novel-1",
                    "workflow_id": "wf-1",
                    "total_snapshots": 1,
                    "by_status": {"running": 0, "succeeded": 1, "failed": 0},
                    "by_phase": {
                        "entity_extraction": {
                            "running": 0,
                            "succeeded": 1,
                            "failed": 0,
                        }
                    },
                    "stale_running_count": 0,
                    "retained_rendered_context_count": 0,
                    "latest_failure": None,
                },
            }
        )
        workflow._analyze_structure = AsyncMock(
            return_value={
                "total_threads": 1,
                "total_arcs": 1,
                "audit_summary": {
                    "structure_analysis": {
                        "snapshot_count": 1,
                        "succeeded": 1,
                        "failed": 0,
                    }
                },
                "snapshot_health_summary": {
                    "novel_id": "novel-1",
                    "workflow_id": "wf-1",
                    "total_snapshots": 2,
                    "by_status": {"running": 0, "succeeded": 2, "failed": 0},
                    "by_phase": {
                        "entity_extraction": {
                            "running": 0,
                            "succeeded": 1,
                            "failed": 0,
                        },
                        "structure_analysis": {
                            "running": 0,
                            "succeeded": 1,
                            "failed": 0,
                        },
                    },
                    "stale_running_count": 0,
                    "retained_rendered_context_count": 0,
                    "latest_failure": None,
                },
            }
        )

        result = await workflow.run_step(
            db=None,
            novel_id=str(uuid.uuid4()),
            start_chapter=1,
            end_chapter=1,
            progress=progress,
        )

        assert result.audit_summary == {
            "entity_extraction": {
                "snapshot_count": 1,
                "succeeded": 1,
                "failed": 0,
            },
            "structure_analysis": {
                "snapshot_count": 1,
                "succeeded": 1,
                "failed": 0,
            },
        }
        assert result.snapshot_health_summary == {
            "novel_id": "novel-1",
            "workflow_id": "wf-1",
            "total_snapshots": 2,
            "by_status": {"running": 0, "succeeded": 2, "failed": 0},
            "by_phase": {
                "entity_extraction": {
                    "running": 0,
                    "succeeded": 1,
                    "failed": 0,
                },
                "structure_analysis": {
                    "running": 0,
                    "succeeded": 1,
                    "failed": 0,
                },
            },
            "stale_running_count": 0,
            "retained_rendered_context_count": 0,
            "latest_failure": None,
        }

    @pytest.mark.asyncio
    async def test_health_failure_stops_before_scene_segmentation(self):
        """LLM preflight failure should fail the workflow before writing assets."""
        from infrastructure.llm.health import LLMHealthResult

        workflow = DeepImportWorkflow()
        progress = DeepImportProgress()
        workflow._check_llm_health = AsyncMock(
            return_value=LLMHealthResult(
                ok=False,
                model="deepseek-v4-flash",
                base_url_host="opencode.ai",
                error_kind="proxy_error",
                message="CONNECT tunnel failed",
            )
        )
        workflow._is_llm_health_required = Mock(return_value=True)
        workflow._run_phase0_plan = AsyncMock()
        workflow._run_phase1a_scene_slicing = AsyncMock()
        workflow._run_phase1b_enrichment = AsyncMock()
        workflow._commit_fused_scenes = AsyncMock()

        result = await workflow.run_step(
            db=None,
            novel_id=str(uuid.uuid4()),
            start_chapter=1,
            end_chapter=3,
            progress=progress,
        )

        assert result.phase == "failed"
        assert result.quality_status == "failed"
        assert result.current_step is None
        assert result.phase_errors[0]["phase"] == "preflight"
        assert result.phase_errors[0]["error_kind"] == "proxy_error"
        workflow._run_phase0_plan.assert_not_awaited()
        workflow._run_phase1a_scene_slicing.assert_not_awaited()
        workflow._run_phase1b_enrichment.assert_not_awaited()
        workflow._commit_fused_scenes.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_phase0_plan_block_stops_before_scene_slicing(self):
        workflow = DeepImportWorkflow()
        progress = DeepImportProgress()
        workflow._run_phase0_plan = AsyncMock(
            return_value=_phase0_plan_result(
                blocked=True,
                block_reason="no_chapter_content",
            )
        )
        workflow._run_phase1a_scene_slicing = AsyncMock()
        workflow._run_phase1b_enrichment = AsyncMock()
        workflow._commit_fused_scenes = AsyncMock()
        workflow._extract_entities_by_scene = AsyncMock()
        workflow._analyze_structure = AsyncMock()

        result = await workflow.run_step(
            db=None,
            novel_id=str(uuid.uuid4()),
            start_chapter=1,
            end_chapter=10,
            progress=progress,
        )

        assert result.phase == "failed"
        assert result.quality_status == "failed"
        assert result.degraded_reason == "no_chapter_content"
        assert result.phase_errors[0]["phase"] == "phase0_plan"
        workflow._run_phase1a_scene_slicing.assert_not_awaited()
        workflow._run_phase1b_enrichment.assert_not_awaited()
        workflow._commit_fused_scenes.assert_not_awaited()
        workflow._extract_entities_by_scene.assert_not_awaited()
        workflow._analyze_structure.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_phase1a_missing_coverage_stops_before_enrichment_and_commit(self):
        workflow = DeepImportWorkflow()
        progress = DeepImportProgress()
        workflow._run_phase0_plan = AsyncMock(
            return_value=_phase0_plan_result(start_chapter=1, end_chapter=3)
        )
        workflow._run_phase1a_scene_slicing = AsyncMock(
            return_value=_phase1a_slicing_result([1, 2])
        )
        workflow._run_phase1b_enrichment = AsyncMock()
        workflow._commit_fused_scenes = AsyncMock()
        workflow._extract_entities_by_scene = AsyncMock()
        workflow._analyze_structure = AsyncMock()

        result = await workflow.run_step(
            db=None,
            novel_id=str(uuid.uuid4()),
            start_chapter=1,
            end_chapter=3,
            progress=progress,
        )

        assert result.phase == "failed"
        assert result.quality_status == "failed"
        assert result.degraded_reason == "missing_chapter_coverage"
        assert result.phase_errors[0]["phase"] == "phase1a_scene_slicing"
        artifact = result.phase_artifacts["phase1a_scene_slicing"]
        assert artifact["coverage"]["missing_chapters"] == [3]
        workflow._run_phase1b_enrichment.assert_not_awaited()
        workflow._commit_fused_scenes.assert_not_awaited()
        workflow._extract_entities_by_scene.assert_not_awaited()
        workflow._analyze_structure.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_phase1a_fallback_coverage_continues_to_enrichment(self):
        workflow = DeepImportWorkflow()
        progress = DeepImportProgress()
        seen_candidates = None

        async def enrich(_db, _novel_id, phase1a_candidates, **_kwargs):
            nonlocal seen_candidates
            seen_candidates = phase1a_candidates
            return _phase1b_enrichment_result([1, 2, 3])

        workflow._run_phase0_plan = AsyncMock(
            return_value=_phase0_plan_result(start_chapter=1, end_chapter=3)
        )
        workflow._run_phase1a_scene_slicing = AsyncMock(
            return_value=_phase1a_slicing_result([1, 2, 3], fallback_count=1)
        )
        workflow._run_phase1b_enrichment = AsyncMock(side_effect=enrich)
        workflow._commit_fused_scenes = AsyncMock(
            return_value=_scene_commit_result(created_count=1)
        )
        workflow._extract_entities_by_scene = AsyncMock(
            return_value={"total_created": 1, "total_relations": 0, "total_deltas": 0}
        )
        workflow._analyze_structure = AsyncMock(
            return_value={"total_threads": 1, "total_arcs": 1}
        )

        result = await workflow.run_step(
            db=None,
            novel_id=str(uuid.uuid4()),
            start_chapter=1,
            end_chapter=3,
            progress=progress,
        )

        assert result.phase == "done"
        assert result.phase1a_fallback is True
        assert len(seen_candidates) == 3
        repair = result.phase_artifacts["phase1a_scene_slicing"]["repair"]
        assert repair["attempted"] is True

    @pytest.mark.asyncio
    async def test_phase1b_degraded_still_commits_fallback_and_runs_phase2_phase3(self):
        workflow = DeepImportWorkflow()
        progress = DeepImportProgress()
        workflow._run_phase0_plan = AsyncMock(
            return_value=_phase0_plan_result(start_chapter=1, end_chapter=3)
        )
        workflow._run_phase1a_scene_slicing = AsyncMock(
            return_value=_phase1a_slicing_result([1, 2, 3])
        )
        workflow._run_phase1b_enrichment = AsyncMock(
            return_value=_phase1b_enrichment_result([1, 2, 3], degraded=True)
        )
        workflow._commit_fused_scenes = AsyncMock(
            return_value=_scene_commit_result(created_count=1)
        )
        workflow._extract_entities_by_scene = AsyncMock(
            return_value={"total_created": 1, "total_relations": 0, "total_deltas": 0}
        )
        workflow._analyze_structure = AsyncMock(
            return_value={"total_threads": 1, "total_arcs": 1}
        )

        result = await workflow.run_step(
            db=None,
            novel_id=str(uuid.uuid4()),
            start_chapter=1,
            end_chapter=3,
            progress=progress,
        )

        assert result.phase == "done"
        assert result.quality_status == "partial"
        assert DeepImportStep.scene_segmentation.value in result.completed_steps
        assert DeepImportStep.entity_extraction.value in result.completed_steps
        assert DeepImportStep.structure_analysis.value in result.completed_steps
        assert result.phase_errors[0]["phase"] == "phase1b_enrichment"
        workflow._commit_fused_scenes.assert_awaited_once()
        workflow._extract_entities_by_scene.assert_awaited_once()
        workflow._analyze_structure.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_happy_path_wires_phase0_phase1a_phase1b_commit_before_phase2_phase3(
        self,
    ):
        workflow = DeepImportWorkflow()
        progress = DeepImportProgress(workflow_id="wf-happy")
        calls: list[str] = []

        async def phase0(_db, _novel_id, _start_chapter, _end_chapter):
            calls.append("phase0")
            return _phase0_plan_result(start_chapter=1, end_chapter=3)

        async def phase1a(
            _db,
            _novel_id,
            _start_chapter,
            _end_chapter,
            phase0_plan,
            **kwargs,
        ):
            calls.append("phase1a")
            assert phase0_plan.windows
            assert "on_batch_progress" in kwargs
            return _phase1a_slicing_result([1, 2, 3])

        async def phase1b(_db, _novel_id, phase1a_candidates, **kwargs):
            calls.append("phase1b")
            assert phase1a_candidates
            assert (kwargs["start_chapter"], kwargs["end_chapter"]) == (1, 3)
            assert kwargs["chapters"]
            assert "on_batch_progress" in kwargs
            return _phase1b_enrichment_result([1, 2, 3])

        async def commit(_db, _novel_id, candidates, *, workflow_id):
            calls.append("commit")
            assert candidates
            assert workflow_id == "wf-happy"
            return _scene_commit_result(created_count=2)

        async def phase2(_db, _novel_id, **_kwargs):
            calls.append("phase2")
            return {"total_created": 1, "total_relations": 0, "total_deltas": 0}

        async def phase3(_db, _novel_id, _start, _end, **_kwargs):
            calls.append("phase3")
            return {"total_threads": 1, "total_arcs": 1}

        workflow._run_phase0_plan = AsyncMock(side_effect=phase0)
        workflow._run_phase1a_scene_slicing = AsyncMock(side_effect=phase1a)
        workflow._run_phase1b_enrichment = AsyncMock(side_effect=phase1b)
        workflow._commit_fused_scenes = AsyncMock(side_effect=commit)
        workflow._extract_entities_by_scene = AsyncMock(side_effect=phase2)
        workflow._analyze_structure = AsyncMock(side_effect=phase3)

        result = await workflow.run_step(
            db=None,
            novel_id=str(uuid.uuid4()),
            start_chapter=1,
            end_chapter=3,
            progress=progress,
        )

        assert result.phase == "done"
        assert calls == ["phase0", "phase1a", "phase1b", "commit", "phase2", "phase3"]
        assert result.phase1_total_batches == 4
        assert result.phase1_completed_batches == 4
        assert result.quality_stats["scene_commit"]["created_count"] == 2

    @pytest.mark.asyncio
    async def test_run_step_sets_current_chapter_range_and_invokes_batch_callbacks(self):
        workflow = DeepImportWorkflow()
        progress = DeepImportProgress(workflow_id="wf-progress")
        emitted_values: list[float] = []
        chapter_ranges: set[str | None] = set()

        async def _record_progress(_progress, value):
            emitted_values.append(value)
            chapter_ranges.add(_progress.current_chapter_range)

        async def phase1a(_db, _novel_id, _s, _e, phase0_plan, **kwargs):
            cb = kwargs["on_batch_progress"]
            for index, window in enumerate(phase0_plan.windows, start=1):
                await cb(index, len(phase0_plan.windows), window.window_id)
            return _phase1a_slicing_result([1, 2, 3])

        async def phase1b(_db, _novel_id, candidates, **kwargs):
            cb = kwargs["on_batch_progress"]
            for index, scene in enumerate(candidates, start=1):
                await cb(index, len(candidates), scene.candidate_id)
            return _phase1b_enrichment_result([1, 2, 3])

        async def phase0(_db, _novel_id, _s, _e):
            return _phase0_plan_result(start_chapter=1, end_chapter=3)

        async def commit(_db, _novel_id, _candidates, *, workflow_id):
            return _scene_commit_result(created_count=2)

        async def phase2(_db, _novel_id, **_kwargs):
            return {"total_created": 1, "total_relations": 0, "total_deltas": 0}

        async def phase3(_db, _novel_id, _s, _e, **_kwargs):
            return {"total_threads": 1, "total_arcs": 1}

        workflow._run_phase0_plan = AsyncMock(side_effect=phase0)
        workflow._run_phase1a_scene_slicing = AsyncMock(side_effect=phase1a)
        workflow._run_phase1b_enrichment = AsyncMock(side_effect=phase1b)
        workflow._commit_fused_scenes = AsyncMock(side_effect=commit)
        workflow._extract_entities_by_scene = AsyncMock(side_effect=phase2)
        workflow._analyze_structure = AsyncMock(side_effect=phase3)

        result = await workflow.run_step(
            db=None,
            novel_id=str(uuid.uuid4()),
            start_chapter=1,
            end_chapter=3,
            progress=progress,
            on_progress=_record_progress,
        )

        assert result.phase == "done"
        assert "1-3" in chapter_ranges
        assert None not in chapter_ranges
        assert emitted_values, "progress should be emitted during phase1"
        assert emitted_values == sorted(emitted_values)
        assert 0.0 in emitted_values or any(v <= 0.1 for v in emitted_values)
        assert any(v >= 0.4 for v in emitted_values)

    @pytest.mark.asyncio
    async def test_run_step_passes_and_merges_phase2_checkpoints(self):
        workflow = DeepImportWorkflow()
        progress = DeepImportProgress(
            workflow_id="wf-resume",
            checkpoints={
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
        )
        returned_checkpoints = {
            "phase2": {
                "scenes": [
                    {
                        "scene_id": "scene-a",
                        "status": "skipped",
                        "retry_count": 0,
                    },
                    {
                        "scene_id": "scene-b",
                        "status": "done",
                        "retry_count": 1,
                    },
                ]
            }
        }

        workflow._commit_fused_scenes = AsyncMock(
            return_value=_scene_commit_result(created_count=1)
        )
        workflow._extract_entities_by_scene = AsyncMock(
            return_value={
                "total_created": 1,
                "total_relations": 0,
                "total_deltas": 0,
                "checkpoints": returned_checkpoints,
            }
        )
        workflow._analyze_structure = AsyncMock(
            return_value={"total_threads": 1, "total_arcs": 1}
        )

        result = await workflow.run_step(
            db=None,
            novel_id=str(uuid.uuid4()),
            start_chapter=1,
            end_chapter=3,
            progress=progress,
            workflow_id="wf-resume",
        )

        _, kwargs = workflow._extract_entities_by_scene.await_args
        assert kwargs["existing_checkpoints"] == {
            "phase2": {
                "scenes": [
                    {
                        "scene_id": "scene-a",
                        "status": "done",
                        "retry_count": 0,
                    }
                ]
            }
        }
        assert result.checkpoints == returned_checkpoints

    @pytest.mark.asyncio
    async def test_small_sample_structure_fallback_balances_categories(self):
        def _response(**kwargs):
            return Mock(id=uuid.uuid4(), **kwargs)

        thread_service = Mock()
        thread_service.create = AsyncMock(
            side_effect=AssertionError("should use create_batch")
        )
        thread_service.create_batch = AsyncMock(
            return_value=[
                _response(
                    name="第 1-7 章补强剧情线 4",
                    thread_type="foreshadowing",
                )
            ]
        )
        arc_service = Mock()
        arc_service.create = AsyncMock(
            side_effect=AssertionError("should use create_batch")
        )
        arc_service.create_batch = AsyncMock(
            return_value=[
                _response(title=f"第 1-7 章补强篇章纲 {index}", arc_index=index)
                for index in range(2, 5)
            ]
        )
        foreshadowing_service = Mock()
        foreshadowing_service.create = AsyncMock(
            side_effect=AssertionError("should use create_batch")
        )
        foreshadowing_service.create_batch = AsyncMock(
            return_value=[_response(name="第 1-7 章补强伏笔 4")]
        )
        reveal_service = Mock()
        reveal_service.create = AsyncMock(
            side_effect=AssertionError("should use create_batch")
        )
        reveal_service.create_batch = AsyncMock(
            return_value=[_response(target_name="克莱恩") for _ in range(3)]
        )

        async def list_entities(_db, _novel_id, *, limit=20):
            return [{"id": uuid.uuid4(), "name": "克莱恩", "entity_type": "character"}]

        services = {
            "outline.thread_service": thread_service,
            "outline.arc_service": arc_service,
            "outline.foreshadowing_service": foreshadowing_service,
            "outline.reveal_service": reveal_service,
            "world.list_entities": list_entities,
        }

        result = {
            "total_threads": 3,
            "total_arcs": 1,
            "threads": [{"id": "thread-1", "name": "既有剧情线"}],
            "arcs": [{"id": "arc-1", "title": "既有篇章纲", "arc_index": 1}],
            "extra_sections": {
                "foreshadowing_plans": [{"id": "f1"}, {"id": "f2"}, {"id": "f3"}],
                "reveal_plans": [{"id": "r1"}],
            },
            "warnings": [],
        }

        with patch(
            "modules.imports.workflow._container_get",
            side_effect=lambda name: services[name],
            autospec=True,
        ):
            updated = await ensure_minimum_structure_outputs(
                db=Mock(),
                novel_id=str(uuid.uuid4()),
                start_chapter=1,
                end_chapter=7,
                result=result,
                workflow_id="wf-structure",
            )

        assert updated["total_threads"] == 4
        assert updated["total_arcs"] == 4
        assert len(updated["extra_sections"]["foreshadowing_plans"]) == 4
        assert len(updated["extra_sections"]["reveal_plans"]) == 4
        fallback_types = [
            item["type"]
            for item in updated["extra_sections"]["fallback_structure_assets"]
        ]
        assert fallback_types == [
            "plot_thread",
            "outline_arc",
            "outline_arc",
            "outline_arc",
            "foreshadowing_plan",
            "reveal_plan",
            "reveal_plan",
            "reveal_plan",
        ]
        assert updated["warnings"] == ["结构类别输出不足，已补充待处理结构建议。"]
        thread_service.create.assert_not_awaited()
        arc_service.create.assert_not_awaited()
        thread_service.create_batch.assert_awaited_once()
        arc_service.create_batch.assert_awaited_once()
        assert len(thread_service.create_batch.await_args.args[2]) == 1
        assert len(arc_service.create_batch.await_args.args[2]) == 3
        foreshadowing_service.create.assert_not_awaited()
        reveal_service.create.assert_not_awaited()
        foreshadowing_service.create_batch.assert_awaited_once()
        reveal_service.create_batch.assert_awaited_once()
        assert len(foreshadowing_service.create_batch.await_args.args[2]) == 1
        assert len(reveal_service.create_batch.await_args.args[2]) == 3
        for service in (
            thread_service,
            arc_service,
            foreshadowing_service,
            reveal_service,
        ):
            for payload in service.create_batch.await_args.args[2]:
                assert payload.provenance_meta["needs_review"] is True
                assert payload.provenance_meta["confidence"] == 0.0
                assert payload.provenance_meta["review_reason"]
                assert payload.provenance_meta["supporting_scene_ids"] == []
        fallback_summaries = [
            updated["threads"][-1],
            updated["arcs"][-1],
            updated["extra_sections"]["foreshadowing_plans"][-1],
            updated["extra_sections"]["reveal_plans"][-1],
        ]
        assert all(item["needs_review"] is True for item in fallback_summaries)
        assert all(
            item["provenance_meta"]["supporting_scene_ids"] == []
            for item in fallback_summaries
        )

    @pytest.mark.asyncio
    async def test_workflow_constant_monkeypatch_controls_structure_fallback_target(
        self,
        monkeypatch,
    ):
        monkeypatch.setattr(
            "modules.imports.workflow.SMALL_SAMPLE_STRUCTURE_TARGET_COUNT",
            2,
        )

        def _response(**kwargs):
            return Mock(id=uuid.uuid4(), **kwargs)

        thread_service = Mock()
        thread_service.create = AsyncMock(
            side_effect=AssertionError("should use create_batch")
        )
        thread_service.create_batch = AsyncMock(
            return_value=[
                _response(
                    name="第 1-7 章补强剧情线 2",
                    thread_type="foreshadowing",
                )
            ]
        )
        arc_service = Mock()
        arc_service.create = AsyncMock(
            side_effect=AssertionError("should use create_batch")
        )
        arc_service.create_batch = AsyncMock(
            return_value=[_response(title="第 1-7 章补强篇章纲 2", arc_index=2)]
        )
        foreshadowing_service = Mock()
        foreshadowing_service.create = AsyncMock(
            side_effect=AssertionError("should use create_batch")
        )
        foreshadowing_service.create_batch = AsyncMock(
            return_value=[_response(name="第 1-7 章补强伏笔 2")]
        )
        reveal_service = Mock()
        reveal_service.create = AsyncMock(
            side_effect=AssertionError("reveals already satisfy target")
        )
        reveal_service.create_batch = AsyncMock(
            side_effect=AssertionError("reveals already satisfy target")
        )

        services = {
            "outline.thread_service": thread_service,
            "outline.arc_service": arc_service,
            "outline.foreshadowing_service": foreshadowing_service,
            "outline.reveal_service": reveal_service,
        }

        result = {
            "total_threads": 1,
            "total_arcs": 1,
            "threads": [{"id": "thread-1", "name": "既有剧情线"}],
            "arcs": [{"id": "arc-1", "title": "既有篇章纲", "arc_index": 1}],
            "extra_sections": {
                "foreshadowing_plans": [{"id": "f1"}],
                "reveal_plans": [{"id": "r1"}, {"id": "r2"}],
            },
            "warnings": [],
        }

        with patch(
            "modules.imports.workflow._container_get",
            side_effect=lambda name: services[name],
            autospec=True,
        ):
            updated = await ensure_minimum_structure_outputs(
                db=Mock(),
                novel_id=str(uuid.uuid4()),
                start_chapter=1,
                end_chapter=7,
                result=result,
                workflow_id="wf-constant",
            )

        assert updated["total_threads"] == 2
        assert updated["total_arcs"] == 2
        assert len(updated["extra_sections"]["foreshadowing_plans"]) == 2
        assert len(updated["extra_sections"]["reveal_plans"]) == 2
        thread_service.create.assert_not_awaited()
        arc_service.create.assert_not_awaited()
        thread_service.create_batch.assert_awaited_once()
        arc_service.create_batch.assert_awaited_once()
        foreshadowing_service.create.assert_not_awaited()
        foreshadowing_service.create_batch.assert_awaited_once()
        reveal_service.create.assert_not_awaited()
        reveal_service.create_batch.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_large_sample_structure_fallback_uses_long_form_minimums(self):
        def _response(**kwargs):
            return Mock(id=uuid.uuid4(), **kwargs)

        thread_service = Mock()
        thread_service.create = AsyncMock(
            side_effect=AssertionError("threads already satisfy target")
        )
        thread_service.create_batch = AsyncMock(
            side_effect=AssertionError("threads already satisfy target")
        )
        arc_service = Mock()
        arc_service.create = AsyncMock(
            side_effect=AssertionError("should use create_batch")
        )
        arc_service.create_batch = AsyncMock(
            return_value=[_response(title="第 1-60 章补强篇章纲 4", arc_index=4)]
        )
        foreshadowing_service = Mock()
        foreshadowing_service.create = AsyncMock(
            side_effect=AssertionError("should use create_batch")
        )
        foreshadowing_service.create_batch = AsyncMock(
            return_value=[
                _response(name=f"第 1-60 章补强伏笔 {index}") for index in range(2, 4)
            ]
        )
        reveal_service = Mock()
        reveal_service.create = AsyncMock(
            side_effect=AssertionError("should use create_batch")
        )
        reveal_service.create_batch = AsyncMock(
            return_value=[_response(target_name="克莱恩") for _ in range(2)]
        )

        async def list_entities(_db, _novel_id, *, limit=20):
            return [{"id": uuid.uuid4(), "name": "克莱恩", "entity_type": "character"}]

        services = {
            "outline.thread_service": thread_service,
            "outline.arc_service": arc_service,
            "outline.foreshadowing_service": foreshadowing_service,
            "outline.reveal_service": reveal_service,
            "world.list_entities": list_entities,
        }
        result = {
            "total_threads": 3,
            "total_arcs": 3,
            "threads": [{"id": f"thread-{i}", "name": f"剧情线 {i}"} for i in range(3)],
            "arcs": [
                {"id": f"arc-{i}", "title": f"篇章纲 {i}", "arc_index": i}
                for i in range(3)
            ],
            "extra_sections": {
                "foreshadowing_plans": [{"id": "f1"}],
                "reveal_plans": [{"id": "r1"}],
            },
            "warnings": [],
        }

        with patch(
            "modules.imports.workflow._container_get",
            side_effect=lambda name: services[name],
            autospec=True,
        ):
            updated = await ensure_minimum_structure_outputs(
                db=Mock(),
                novel_id=str(uuid.uuid4()),
                start_chapter=1,
                end_chapter=60,
                result=result,
                workflow_id="wf-structure-large",
            )

        assert updated["total_threads"] == 3
        assert updated["total_arcs"] == 4
        assert len(updated["extra_sections"]["foreshadowing_plans"]) == 3
        assert len(updated["extra_sections"]["reveal_plans"]) == 3
        thread_service.create.assert_not_awaited()
        thread_service.create_batch.assert_not_awaited()
        arc_service.create.assert_not_awaited()
        arc_service.create_batch.assert_awaited_once()
        assert len(arc_service.create_batch.await_args.args[2]) == 1
        foreshadowing_service.create.assert_not_awaited()
        reveal_service.create.assert_not_awaited()
        foreshadowing_service.create_batch.assert_awaited_once()
        reveal_service.create_batch.assert_awaited_once()
        assert len(foreshadowing_service.create_batch.await_args.args[2]) == 2
        assert len(reveal_service.create_batch.await_args.args[2]) == 2

    @pytest.mark.asyncio
    async def test_empty_phase2_and_phase3_outputs_are_partial(self):
        """Done with empty AI assets should be machine-readable as partial."""
        workflow = DeepImportWorkflow()
        progress = DeepImportProgress()

        workflow._extract_entities_by_scene = AsyncMock(
            return_value={
                "total_created": 0,
                "total_relations": 0,
                "total_deltas": 0,
            }
        )
        workflow._analyze_structure = AsyncMock(
            return_value={
                "total_threads": 0,
                "total_arcs": 0,
                "threads": [],
                "arcs": [],
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
        assert result.quality_status == "partial"
        assert result.degraded is True
        assert [e["phase"] for e in result.phase_errors] == [
            "entity_extraction",
            "structure_analysis",
        ]
        phase2_artifact = result.phase_artifacts["entity_extraction"]
        assert phase2_artifact["status"] == "degraded"
        assert phase2_artifact["quality_status"] == "partial"
        assert phase2_artifact["errors"][0]["error_kind"] == "empty_output"

    @pytest.mark.asyncio
    async def test_zero_scene_commit_is_failed_not_complete(self):
        """A run that commits no Scene must not be reported as complete."""
        workflow = DeepImportWorkflow()
        progress = DeepImportProgress()

        workflow._commit_fused_scenes = AsyncMock(
            return_value=_scene_commit_result(created_count=0, skipped_count=0)
        )
        workflow._extract_entities_by_scene = AsyncMock(
            return_value={
                "total_created": 0,
                "total_relations": 0,
                "total_deltas": 0,
            }
        )
        workflow._analyze_structure = AsyncMock(
            return_value={
                "total_threads": 1,
                "total_arcs": 1,
                "threads": [],
                "arcs": [],
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

        assert result.phase == "failed"
        assert result.quality_status == "failed"
        assert result.degraded_reason == "empty_scene_commit"
        assert DeepImportStep.scene_segmentation.value not in result.completed_steps
        assert result.phase_errors[0] == {
            "phase": "scene_segmentation",
            "error_kind": "empty_scene_commit",
            "message": "Scene 提交阶段未创建或复用任何 Scene",
        }
        scene_commit = {item["phase"]: item for item in result.phase_timeline}[
            "scene_commit"
        ]
        assert scene_commit["status"] == "failed"
        assert scene_commit["error_kind"] == "empty_scene_commit"
        assert result.last_error == {
            "phase": "scene_commit",
            "error_kind": "empty_scene_commit",
            "message": "Scene 提交阶段未创建或复用任何 Scene，已停止深度导入。",
        }
        assert result.diagnostic_counts["scene_count"] == 0
        workflow._extract_entities_by_scene.assert_not_called()
        workflow._analyze_structure.assert_not_called()

    @pytest.mark.asyncio
    async def test_phase2_exception_is_partial_and_phase3_still_runs(self):
        """A per-scene persistence failure should not leave the whole task failed."""
        workflow = DeepImportWorkflow()
        progress = DeepImportProgress()

        workflow._extract_entities_by_scene = AsyncMock(
            side_effect=RuntimeError("cannot insert generated column")
        )
        workflow._analyze_structure = AsyncMock(
            return_value={
                "total_threads": 1,
                "total_arcs": 1,
                "threads": [],
                "arcs": [],
                "extra_sections": {},
            }
        )
        db = AsyncMock()

        result = await workflow.run_step(
            db=db,
            novel_id=str(uuid.uuid4()),
            start_chapter=1,
            end_chapter=3,
            progress=progress,
        )

        assert result.phase == "done"
        assert result.quality_status == "partial"
        assert result.degraded is True
        assert DeepImportStep.structure_analysis.value in result.completed_steps
        assert result.phase_errors[0]["phase"] == "entity_extraction"
        assert result.phase_errors[0]["error_kind"] == "phase_failed"
        timeline = {item["phase"]: item for item in result.phase_timeline}
        assert timeline["entity_extraction"]["status"] == "failed"
        assert timeline["entity_extraction"]["error_kind"] == "phase_failed"
        assert result.last_error["phase"] == "entity_extraction"
        assert result.last_error["error_kind"] == "phase_failed"
        assert result.diagnostic_counts["entity_count"] == 0
        db.rollback.assert_awaited_once()
        workflow._analyze_structure.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_phase3_timeout_is_partial_and_diagnostic(self, monkeypatch):
        """A slow structure analysis should not leave the import stuck as running."""
        monkeypatch.setattr(
            DeepImportWorkflow,
            "_phase3_timeout_seconds",
            lambda _self: 0.01,
        )
        workflow = DeepImportWorkflow()
        progress = DeepImportProgress()

        workflow._extract_entities_by_scene = AsyncMock(
            return_value={
                "total_created": 2,
                "total_relations": 0,
                "total_deltas": 0,
            }
        )

        async def _slow_structure(*_args, **_kwargs):
            await asyncio.Event().wait()
            return {
                "total_threads": 1,
                "total_arcs": 1,
                "threads": [],
                "arcs": [],
                "extra_sections": {},
            }

        workflow._analyze_structure = AsyncMock(side_effect=_slow_structure)
        db = AsyncMock()

        result = await workflow.run_step(
            db=db,
            novel_id=str(uuid.uuid4()),
            start_chapter=1,
            end_chapter=3,
            progress=progress,
        )

        assert result.phase == "done"
        assert result.quality_status == "partial"
        assert result.degraded is True
        assert DeepImportStep.scene_segmentation.value in result.completed_steps
        assert DeepImportStep.entity_extraction.value in result.completed_steps
        assert DeepImportStep.structure_analysis.value not in result.completed_steps
        assert result.phase_errors[-1] == {
            "phase": DeepImportStep.structure_analysis.value,
            "error_kind": "timeout",
            "message": "剧情结构分析超时，已降级完成；可稍后重试结构分析。",
        }
        timeline = {item["phase"]: item for item in result.phase_timeline}
        assert timeline["structure_analysis"]["status"] == "failed"
        assert timeline["structure_analysis"]["error_kind"] == "timeout"
        assert result.quality_stats["phase3"]["error_kind"] == "timeout"
        assert result.diagnostic_counts["structure_counts"]["threads"] == 0
        assert "0 条剧情线" in result.message
        db.rollback.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_phase2_degraded_result_is_partial_even_with_created_entities(self):
        """A normal Phase 2 return with partial entities must still expose degradation."""
        workflow = DeepImportWorkflow()
        progress = DeepImportProgress()

        workflow._extract_entities_by_scene = AsyncMock(
            return_value={
                "total_created": 2,
                "total_relations": 0,
                "total_aliases": 1,
                "total_deltas": 0,
                "degraded": True,
                "error_kind": "transport_failure",
                "error_message": "connection failed",
                "failed_scene_indices": [],
                "completed_scenes": 1,
                "alias_relation_scenes": 1,
                "alias_relation_failed_scenes": [2],
                "skipped_scenes": 2,
                "fallback_created": 1,
                "stopped_early": True,
            }
        )
        workflow._analyze_structure = AsyncMock(
            return_value={
                "total_threads": 1,
                "total_arcs": 1,
                "threads": [],
                "arcs": [],
                "extra_sections": {},
            }
        )

        result = await workflow.run_step(
            db=AsyncMock(),
            novel_id=str(uuid.uuid4()),
            start_chapter=1,
            end_chapter=3,
            progress=progress,
        )

        assert result.phase == "done"
        assert result.quality_status == "partial"
        assert result.degraded is True
        assert result.phase_errors[0]["phase"] == "entity_extraction"
        assert result.phase_errors[0]["error_kind"] == "transport_failure"
        assert "跳过 2 个 Scene" in result.phase_errors[0]["message"]
        assert result.quality_stats["phase2"]["total_created"] == 2
        assert result.quality_stats["phase2"]["completed_scenes"] == 1
        assert result.quality_stats["phase2"]["skipped_scenes"] == 2
        assert result.quality_stats["phase2"]["fallback_created"] == 1
        assert result.quality_stats["phase2"]["degraded"] is True
        timeline = {item["phase"]: item for item in result.phase_timeline}
        assert timeline["entity_extraction"]["status"] == "degraded"
        assert timeline["entity_extraction"]["error_kind"] == "transport_failure"
        assert result.diagnostic_counts["entity_count"] == 2
        assert result.diagnostic_counts["alias_count"] == 1
        assert result.diagnostic_counts["alias_relation_scenes"] == 1
        assert result.diagnostic_counts["alias_relation_failed_scene_count"] == 1
        assert result.diagnostic_counts["phase2_completed_scenes"] == 1
        assert result.last_error["error_kind"] == "transport_failure"

    @pytest.mark.asyncio
    async def test_run_step_emits_phase_progress_updates(self):
        """运行中应暴露可轮询的阶段进度，而不是只在任务完成后写最终结果。"""
        workflow = DeepImportWorkflow()
        progress = DeepImportProgress()
        emitted: list[tuple[float, str, str | None, str | None, list[str]]] = []

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
                    updated.current_phase,
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
            (0.0, "running", "scene_segmentation", "phase0_plan", []),
            (0.1, "running", "scene_segmentation", "phase1a_scene_slicing", []),
            (0.2, "running", "scene_segmentation", "phase1b_enrichment", []),
            (0.35, "running", "scene_segmentation", "scene_commit", []),
            (
                0.4,
                "running",
                "entity_extraction",
                "entity_extraction",
                ["scene_segmentation"],
            ),
            (
                0.8,
                "running",
                "structure_analysis",
                "structure_analysis",
                ["scene_segmentation", "entity_extraction"],
            ),
            (
                1.0,
                "done",
                None,
                "structure_analysis",
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




class TestSceneSegmentationProgress:
    """测试 Scene 切分服务的细粒度进度回调"""

    @pytest.mark.asyncio
    async def test_load_chapters_batches_draft_lookup(self, monkeypatch):
        """加载章节正文时应一次批量查草稿，不能逐章查询。"""
        calls: list[tuple[str, list[int]]] = []

        async def list_latest_drafts_for_chapters(db, novel_id, chapter_indices):
            calls.append((novel_id, list(chapter_indices)))
            return [
                WritingDraftContract(
                    novel_id=novel_id,
                    chapter_index=3,
                    title="第三章",
                    content="第三章正文",
                ),
                WritingDraftContract(
                    novel_id=novel_id,
                    chapter_index=1,
                    title="第一章",
                    content="第一章正文",
                ),
            ]

        async def get_latest_draft_for_chapter(*args, **kwargs):
            raise AssertionError("scene segmentation should batch draft lookup")

        import modules.writing.facade as writing_facade

        monkeypatch.setattr(
            writing_facade,
            "list_latest_drafts_for_chapters",
            list_latest_drafts_for_chapters,
        )
        monkeypatch.setattr(
            writing_facade,
            "get_latest_draft_for_chapter",
            get_latest_draft_for_chapter,
        )

        chapters = await SceneSegmentationService()._load_chapters(
            Mock(),
            "novel-1",
            1,
            3,
        )

        assert calls == [("novel-1", [1, 2, 3])]
        assert [chapter["chapter_index"] for chapter in chapters] == [1, 3]
        assert [chapter["title"] for chapter in chapters] == ["第一章", "第三章"]

    def test_split_batches_respects_char_budget_with_overlap(self, monkeypatch):
        """长章节应按字符预算缩小批次，并保留 1 章 overlap。"""
        from modules.imports import scene_segmentation

        monkeypatch.setattr(scene_segmentation, "MAX_BATCH_CHARS", 10)
        service = SceneSegmentationService()
        chapters = [
            {"chapter_index": i, "title": f"第{i}章", "content": "x" * 4}
            for i in range(1, 5)
        ]

        batches = service._split_into_batches(chapters)

        assert [[ch["chapter_index"] for ch in batch] for batch in batches] == [
            [1, 2],
            [2, 3],
            [3, 4],
        ]
        assert all(sum(len(ch["content"]) for ch in batch) <= 10 for batch in batches)

    def test_split_batches_allows_single_chapter_over_budget(self, monkeypatch):
        """单章超过预算时仍应独立成批，不能卡住。"""
        from modules.imports import scene_segmentation

        monkeypatch.setattr(scene_segmentation, "MAX_BATCH_CHARS", 10)
        service = SceneSegmentationService()
        chapters = [
            {"chapter_index": 1, "title": "第1章", "content": "x" * 20},
            {"chapter_index": 2, "title": "第2章", "content": "x" * 4},
            {"chapter_index": 3, "title": "第3章", "content": "x" * 4},
        ]

        batches = service._split_into_batches(chapters)

        assert [[ch["chapter_index"] for ch in batch] for batch in batches] == [
            [1],
            [2, 3],
        ]

    @pytest.mark.asyncio
    async def test_generate_with_timeout_raises_llm_timeout(self):
        """HTTP 客户端未及时超时时，上层应主动中断 LLM 调用。"""
        from infrastructure.llm.errors import LLMTimeoutError

        class SlowLLMClient:
            provider = "openai"

            async def generate(self, _request):
                import asyncio

                await asyncio.Event().wait()

        request = Mock(model="deepseek-v4-flash")

        with pytest.raises(LLMTimeoutError) as exc_info:
            await SceneSegmentationService._generate_with_timeout(
                SlowLLMClient(),
                request,
                timeout_seconds=0.01,
            )

        assert exc_info.value.provider == "openai"
        assert exc_info.value.model == "deepseek-v4-flash"

    @pytest.mark.asyncio
    @patch("modules.outline.facade.create_scene", autospec=True)
    @patch("modules.outline.facade.get_next_scene_index", return_value=0, autospec=True)
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

    def test_phase2_splits_scenes_into_fixed_size_batches(self, monkeypatch):
        monkeypatch.delenv("PHASE2_BATCH_SIZE_SCENES", raising=False)
        service = SceneEntityExtractionService()
        scenes = [{"id": f"scene-{idx}", "scene_index": idx} for idx in range(1, 31)]

        batches = service._split_scene_batches(scenes)

        assert [[scene["scene_index"] for scene in batch] for batch in batches] == [
            list(range(1, 13)),
            list(range(13, 25)),
            list(range(25, 31)),
        ]
        assert service._phase2_batch_size_scenes() == 12
        assert service._phase2_batch_concurrency() == 6

    def test_phase2_batch_config_uses_env_override(self, monkeypatch):
        monkeypatch.setenv("PHASE2_BATCH_SIZE_SCENES", "8")
        monkeypatch.setenv("PHASE2_BATCH_CONCURRENCY", "8")
        service = SceneEntityExtractionService()
        scenes = [{"id": f"scene-{idx}", "scene_index": idx} for idx in range(1, 18)]

        batches = service._split_scene_batches(scenes)

        assert [[scene["scene_index"] for scene in batch] for batch in batches] == [
            list(range(1, 9)),
            list(range(9, 17)),
            [17],
        ]
        assert service._phase2_batch_size_scenes() == 8
        assert service._phase2_batch_concurrency() == 8

    def test_phase2_batch_config_invalid_env_falls_back(self, monkeypatch):
        monkeypatch.setenv("PHASE2_BATCH_SIZE_SCENES", "nope")
        monkeypatch.setenv("PHASE2_BATCH_CONCURRENCY", "0")
        service = SceneEntityExtractionService()

        assert service._phase2_batch_size_scenes() == 12
        assert service._phase2_batch_concurrency() == 6

    def test_phase2_boundary_windows_use_adjacent_batch_edges_only(self):
        service = SceneEntityExtractionService()
        batches = [
            [{"scene_index": idx} for idx in range(1, 13)],
            [{"scene_index": idx} for idx in range(13, 25)],
            [{"scene_index": idx} for idx in range(25, 31)],
        ]

        windows = service._phase2_boundary_windows(batches, boundary_size=2)

        assert [
            [scene["scene_index"] for scene in window["scenes"]] for window in windows
        ] == [
            [11, 12, 13, 14],
            [23, 24, 25, 26],
        ]
        assert windows[0]["left_batch_index"] == 0
        assert windows[0]["right_batch_index"] == 1
        assert windows[1]["left_batch_index"] == 1
        assert windows[1]["right_batch_index"] == 2

    def test_phase2_boundary_windows_use_project_boundary_size(self):
        from modules.imports.entity_extraction.scene_entity_config import (
            phase2_project_settings_context,
        )

        service = SceneEntityExtractionService()
        batches = [
            [{"scene_index": idx} for idx in range(1, 13)],
            [{"scene_index": idx} for idx in range(13, 25)],
        ]

        with phase2_project_settings_context(
            {"deep_import": {"phase2": {"boundary_scenes": 3}}}
        ):
            windows = service._phase2_boundary_windows(batches)

        assert [scene["scene_index"] for scene in windows[0]["scenes"]] == [
            10,
            11,
            12,
            13,
            14,
            15,
        ]

    @pytest.mark.asyncio
    @patch(
        "modules.world.facade.get_world_context",
        autospec=True,
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
            existing_checkpoints={"unrelated-scene": {"status": "done"}},
        )

        assert progress_calls == [(0, 2), (1, 2), (2, 2)]
        assert result["total_scenes"] == 2
        assert "total_relations" in result

    @pytest.mark.asyncio
    @patch("modules.world.facade.get_world_context", autospec=True)
    async def test_phase2_runs_batches_in_parallel_but_scenes_serial_within_batch(
        self,
        mock_ctx,
        monkeypatch,
    ):
        monkeypatch.delenv("PHASE2_BATCH_SIZE_SCENES", raising=False)
        monkeypatch.delenv("PHASE2_BATCH_CONCURRENCY", raising=False)
        mock_ctx.return_value = Mock(entities=[])
        service = SceneEntityExtractionService()
        service._get_scenes = AsyncMock(
            return_value=[
                {"id": f"scene-{idx}", "scene_index": idx, "chapter_ids": [str(idx)]}
                for idx in range(1, 25)
            ]
        )
        service._run_alias_relation_phase = AsyncMock(
            return_value={
                "total_aliases": 0,
                "total_relations": 0,
                "alias_relation_scenes": 0,
                "alias_relation_failed_scenes": [],
                "checkpoints": {"phase2b": {"scenes": []}},
            }
        )
        service._run_boundary_supplements = AsyncMock(
            return_value={
                "phase2_boundary_windows_total": 1,
                "phase2_boundary_windows_completed": 1,
                "phase2_boundary_supplement_counts": {
                    "created": 0,
                    "aliases": 0,
                    "relations": 0,
                    "link_suggestions": 0,
                    "conflicts": 0,
                    "failed": 0,
                },
                "degraded": False,
                "error_kind": None,
                "error_message": None,
            }
        )
        service._phase2_audit_summary = AsyncMock(return_value={})
        service._phase2_snapshot_health_summary = AsyncMock(return_value={})

        active_batches: set[int] = set()
        max_active_batches = 0
        scene_order_by_batch: dict[int, list[int]] = {}

        async def fake_process_scene(
            db,
            nid,
            scene,
            scene_idx,
            existing_context,
            accumulated_memory,
            seen_entity_keys,
            workflow_id=None,
            persistence_stats=None,
            db_lock=None,
        ):
            nonlocal max_active_batches
            batch_index = (int(scene["scene_index"]) - 1) // 12
            active_batches.add(batch_index)
            max_active_batches = max(max_active_batches, len(active_batches))
            scene_order_by_batch.setdefault(batch_index, []).append(
                int(scene["scene_index"])
            )
            await asyncio.sleep(0)
            active_batches.discard(batch_index)
            return {
                "created": 0,
                "relations": 0,
                "deltas": 0,
                "updated_context": existing_context,
                "updated_memory": accumulated_memory,
                "checkpoint": service._build_scene_checkpoint(
                    scene,
                    status="done",
                    workflow_id="wf",
                    scene_provenance_key=f"wf:scene:{scene['scene_index']}",
                    retry_count=0,
                ),
                "created_entity_ids": [],
                "created_relation_ids": [],
                "created_delta_ids": [],
            }

        service._process_scene = fake_process_scene
        progress_calls = []

        async def on_progress(completed, total):
            progress_calls.append((completed, total))

        result = await service.extract_by_scenes(
            AsyncMock(),
            str(uuid.uuid4()),
            workflow_id="wf",
            on_scene_progress=on_progress,
            existing_checkpoints={},
        )

        assert max_active_batches > 1
        assert scene_order_by_batch[0] == list(range(1, 13))
        assert scene_order_by_batch[1] == list(range(13, 25))
        assert result["phase2_batches_total"] == 2
        assert result["phase2_batches_completed"] == 2
        assert result["phase2_batch_size_scenes"] == 12
        assert result["phase2_batch_concurrency"] == 6
        assert progress_calls[0] == (0, 24)
        assert progress_calls[-1] == (24, 24)

    @pytest.mark.asyncio
    @patch("modules.world.facade.get_world_context", autospec=True)
    async def test_phase2_batched_result_reports_env_override(
        self,
        mock_ctx,
        monkeypatch,
    ):
        monkeypatch.setenv("PHASE2_BATCH_SIZE_SCENES", "8")
        monkeypatch.setenv("PHASE2_BATCH_CONCURRENCY", "8")
        mock_ctx.return_value = Mock(entities=[])
        service = SceneEntityExtractionService()
        service._get_scenes = AsyncMock(
            return_value=[
                {"id": f"scene-{idx}", "scene_index": idx, "chapter_ids": [str(idx)]}
                for idx in range(1, 18)
            ]
        )
        service._process_scene = AsyncMock(
            return_value={
                "created": 0,
                "relations": 0,
                "deltas": 0,
                "updated_context": "",
                "updated_memory": [],
            }
        )
        service._run_boundary_supplements = AsyncMock(
            return_value={
                "phase2_boundary_windows_total": 2,
                "phase2_boundary_windows_completed": 2,
                "phase2_boundary_supplement_counts": {
                    "created": 0,
                    "aliases": 0,
                    "relations": 0,
                    "link_suggestions": 0,
                    "conflicts": 0,
                    "failed": 0,
                },
                "degraded": False,
                "error_kind": None,
                "error_message": None,
            }
        )
        service._run_alias_relation_phase = AsyncMock(
            return_value={
                "total_aliases": 0,
                "total_relations": 0,
                "alias_relation_scenes": 0,
                "alias_relation_failed_scenes": [],
                "checkpoints": {"phase2b": {"scenes": []}},
            }
        )
        service._phase2_audit_summary = AsyncMock(return_value={})
        service._phase2_snapshot_health_summary = AsyncMock(return_value={})

        result = await service.extract_by_scenes(
            AsyncMock(),
            str(uuid.uuid4()),
            workflow_id="wf",
            existing_checkpoints={},
        )
        stats = phase2_quality_stats(result)

        assert result["phase2_batch_size_scenes"] == 8
        assert result["phase2_batch_concurrency"] == 8
        assert result["phase2_batches_total"] == 3
        assert stats["phase2_batch_size_scenes"] == 8
        assert stats["phase2_batch_concurrency"] == 8

    @pytest.mark.asyncio
    async def test_phase2_boundary_supplement_disabled_by_default(self):
        service = SceneEntityExtractionService()
        batches = [
            [{"scene_index": idx, "id": f"scene-{idx}"} for idx in range(1, 13)],
            [{"scene_index": idx, "id": f"scene-{idx}"} for idx in range(13, 25)],
        ]
        service._process_boundary_window = AsyncMock()

        result = await service._run_boundary_supplements(
            AsyncMock(),
            uuid.uuid4(),
            batches,
            workflow_id="wf",
        )

        assert result["phase2_boundary_windows_total"] == 1
        assert result["phase2_boundary_windows_completed"] == 0
        assert result["phase2_boundary_supplement_counts"]["created"] == 0
        assert result["phase2_boundary_skipped"] is True
        assert result["phase2_boundary_skip_reason"] == "disabled"
        service._process_boundary_window.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_phase2_boundary_supplement_receives_only_adjacent_edges(
        self,
        monkeypatch,
    ):
        monkeypatch.setattr(
            "modules.imports.entity_extraction.scene_entity_extraction."
            "_phase2_config.phase2_boundary_supplement_enabled",
            lambda: True,
        )
        service = SceneEntityExtractionService()
        batches = [
            [{"scene_index": idx, "id": f"scene-{idx}"} for idx in range(1, 13)],
            [{"scene_index": idx, "id": f"scene-{idx}"} for idx in range(13, 25)],
        ]
        seen_windows = []

        async def fake_process_boundary(db, nid, window, workflow_id=None):
            seen_windows.append([scene["scene_index"] for scene in window["scenes"]])
            return {
                "created": 1,
                "aliases": 1,
                "relations": 1,
                "link_suggestions": 1,
                "conflicts": 0,
                "failed": False,
            }

        service._process_boundary_window = fake_process_boundary

        result = await service._run_boundary_supplements(
            AsyncMock(),
            uuid.uuid4(),
            batches,
            workflow_id="wf",
        )

        assert seen_windows == [[11, 12, 13, 14]]
        assert result["phase2_boundary_windows_total"] == 1
        assert result["phase2_boundary_windows_completed"] == 1
        assert result["phase2_boundary_supplement_counts"] == {
            "created": 1,
            "aliases": 1,
            "relations": 1,
            "link_suggestions": 1,
            "conflicts": 0,
            "failed": 0,
        }

    @pytest.mark.asyncio
    async def test_phase2_boundary_failure_degrades_without_rollback(
        self,
        monkeypatch,
    ):
        monkeypatch.setattr(
            "modules.imports.entity_extraction.scene_entity_extraction."
            "_phase2_config.phase2_boundary_supplement_enabled",
            lambda: True,
        )
        service = SceneEntityExtractionService()
        batches = [
            [{"scene_index": idx, "id": f"scene-{idx}"} for idx in range(1, 13)],
            [{"scene_index": idx, "id": f"scene-{idx}"} for idx in range(13, 25)],
        ]

        async def fail_boundary(db, nid, window, workflow_id=None):
            raise RuntimeError("boundary llm failed")

        service._process_boundary_window = fail_boundary

        result = await service._run_boundary_supplements(
            AsyncMock(),
            uuid.uuid4(),
            batches,
            workflow_id="wf",
        )

        assert result["phase2_boundary_windows_total"] == 1
        assert result["phase2_boundary_windows_completed"] == 0
        assert result["phase2_boundary_supplement_counts"]["failed"] == 1
        assert result["degraded"] is True
        assert result["error_kind"] == "RuntimeError"

    @pytest.mark.asyncio
    async def test_phase2_boundary_timeout_degrades_remaining_windows(self, monkeypatch):
        monkeypatch.setattr(
            "modules.imports.entity_extraction.scene_entity_extraction."
            "_phase2_config.phase2_boundary_supplement_enabled",
            lambda: True,
        )
        service = SceneEntityExtractionService()
        batches = [
            [{"scene_index": idx, "id": f"scene-{idx}"} for idx in range(1, 13)],
            [{"scene_index": idx, "id": f"scene-{idx}"} for idx in range(13, 25)],
        ]

        async def slow_boundary(db, nid, window, workflow_id=None):
            await asyncio.Event().wait()
            return {
                "created": 1,
                "aliases": 0,
                "relations": 0,
                "link_suggestions": 0,
                "conflicts": 0,
                "failed": False,
            }

        monkeypatch.setattr(
            "modules.imports.entity_extraction.scene_entity_extraction."
            "_phase2_config.phase2_boundary_total_timeout_seconds",
            lambda: 0.01,
        )
        service._process_boundary_window = slow_boundary

        result = await service._run_boundary_supplements(
            AsyncMock(),
            uuid.uuid4(),
            batches,
            workflow_id="wf",
        )

        assert result["phase2_boundary_windows_total"] == 1
        assert result["phase2_boundary_windows_completed"] == 0
        assert result["phase2_boundary_supplement_counts"]["failed"] == 1
        assert result["degraded"] is True
        assert result["error_kind"] == "timeout"
        assert result["phase2_boundary_total_timeout_s"] == 0.01

    @pytest.mark.asyncio
    async def test_phase2_boundary_window_skips_duplicate_alias_relation_phase(self):
        service = SceneEntityExtractionService()
        service._process_scenes_bulk = AsyncMock(
            return_value={"created": 2, "relations": 3}
        )
        service._run_alias_relation_phase = AsyncMock(
            return_value={"total_aliases": 99, "total_relations": 99}
        )

        result = await service._process_boundary_window(
            AsyncMock(),
            uuid.uuid4(),
            {"scenes": [{"scene_index": 11}, {"scene_index": 12}]},
            workflow_id="wf",
        )

        assert result == {
            "created": 2,
            "aliases": 0,
            "relations": 0,
            "link_suggestions": 0,
            "conflicts": 0,
            "failed": False,
        }
        service._run_alias_relation_phase.assert_not_awaited()

    @pytest.mark.asyncio
    @patch("modules.world.facade.find_similar_entities", autospec=True)
    @patch("modules.world.facade.create_entity", autospec=True)
    @patch("modules.world.facade.find_entity_id_by_name", autospec=True)
    async def test_phase2_persist_entities_collects_action_and_dedup_stats(
        self,
        mock_find_entity_id,
        mock_create,
        mock_find_similar,
    ):
        service = SceneEntityExtractionService()
        target_id = str(uuid.uuid4())
        existing_id = str(uuid.uuid4())
        mock_find_entity_id.return_value = existing_id
        mock_find_similar.return_value = [
            Mock(
                similarity_score=0.96,
                match_method="exact_name",
                existing_entity_id=target_id,
            )
        ]
        mock_create.return_value = {"id": str(uuid.uuid4())}
        stats = service._empty_phase2_persistence_stats()

        class FakeSavepoint:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

        class FakeDb:
            def begin_nested(self):
                return FakeSavepoint()

        entities = [
            ExtractedEntity(
                name="克莱恩",
                entity_type="character",
                summary="主角",
                suggested_action="create_new",
                confidence=0.92,
            ),
            ExtractedEntity(
                name="廷根市",
                entity_type="location",
                summary="城市",
                suggested_action="link_to_existing",
                suggested_existing_entity_name="廷根",
                confidence=0.76,
            ),
            ExtractedEntity(
                name="路人甲",
                entity_type="character",
                summary="一次性人物",
                suggested_action="ignore",
                confidence=0.3,
            ),
            ExtractedEntity(
                name="普通晚餐",
                entity_type="item",
                summary="临时道具",
                suggested_action="temporary_only",
                confidence=0.52,
            ),
        ]

        fake_db = FakeDb()
        novel_id = uuid.uuid4()
        with patch(
            "modules.imports.entity_extraction.scene_entity_extraction."
            "SceneEntityExtractionService._record_quote_evidence",
            autospec=True,
        ):
            created = await service._persist_entities(
                fake_db,
                novel_id,
                entities,
                scene_index=1,
                source_chapter_index=1,
                persistence_stats=stats,
            )

        assert created == 3
        assert mock_create.await_count == 3
        high_confidence_payload = mock_create.await_args_list[0].args[2]
        assert high_confidence_payload["status"] == "candidate"
        assert (
            high_confidence_payload["content_json"]["_meta"]["suggested_target_entity_id"]
            == target_id
        )
        linked_payload = mock_create.await_args_list[1].args[2]
        assert (
            linked_payload["content_json"]["_meta"]["suggested_existing_entity_id"]
            == existing_id
        )
        mock_find_entity_id.assert_awaited_once_with(
            fake_db,
            str(novel_id),
            "廷根",
            entity_type="location",
        )
        assert stats["action_counts"] == {
            "create_new": 1,
            "link_to_existing": 1,
            "ignore": 1,
            "temporary_only": 1,
        }
        assert stats["dedup_counts"]["auto_merged"] == 0
        assert stats["dedup_counts"]["review_suggested"] == 2
        assert stats["dedup_counts"]["skipped"] == 0
        assert stats["linked_to_existing"] == 1
        assert stats["ignored"] == 1
        assert stats["temporary_only"] == 1
        assert stats["low_confidence"] == 2


class TestHandleDeepImportTaskResult:
    """测试 task handler 在阶段边界更新 task.result"""

    @pytest.mark.asyncio
    async def test_handle_deep_import_updates_task_result_at_phase_boundaries(self):
        from modules.imports.tasks import handle_deep_import

        class FakeTask:
            def __init__(self):
                self.id = uuid.uuid4()
                self.meta = _authorized_task_meta(
                    str(uuid.uuid4()),
                    start_chapter=1,
                    end_chapter=3,
                )
                self.result = {}
                self.progress_values = []

            def update_progress(self, value):
                self.progress_values.append(value)

        task = FakeTask()
        mock_db = AsyncMock()

        with (
            patch(
                "modules.project.facade.build_project_llm_execution_snapshot",
                autospec=True,
                return_value={},
            ),
            patch(
                "modules.project.facade.restore_project_llm_execution_settings",
                autospec=True,
                return_value=None,
            ),
            patch.object(
                DeepImportWorkflow,
                "_extract_entities_by_scene",
                autospec=True,
                return_value={"total_created": 3, "total_deltas": 2},
            ),
            patch.object(
                DeepImportWorkflow,
                "_analyze_structure",
                autospec=True,
                return_value={"total_threads": 2, "total_arcs": 4},
            ),
            patch.object(
                DeepImportWorkflow,
                "_refresh_snapshot_health_summary",
                autospec=True,
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
