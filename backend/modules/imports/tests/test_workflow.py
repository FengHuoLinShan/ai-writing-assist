"""深度导入工作流测试

测试 DeepImportWorkflow 编排逻辑和各步骤状态转换。
候选管理已移除，深度导入全自动执行三步。
"""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import ANY, AsyncMock, Mock, patch

import pytest
from sqlalchemy import select

from infrastructure.tasks.models import AsyncTask
from modules.imports.deep_import_retry import DeepImportRetryResult
from modules.imports.llm_schemas import SceneChunk, SceneItem, SceneSegmentationOutput
from modules.imports.orchestrator import DeepImportOrchestrator
from modules.imports.scene_candidates import (
    SceneCandidate,
    SceneCandidateBatch,
    ScenePrefetchResult,
    SceneReinforcementResult,
)
from modules.imports.scene_commit import SceneCommitResult
from modules.imports.scene_entity_extraction import SceneEntityExtractionService
from modules.imports.scene_fusion import FinalSceneCandidate, Phase1bFusionResult
from modules.imports.scene_segmentation import SceneSegmentationService
from modules.imports.workflow import (
    DeepImportWorkflow,
    _compact_phase1b_payload,
    _Phase0SceneCandidateLLM,
    _Phase1bSceneFusionLLM,
)
from modules.imports.workflow_schemas import DeepImportProgress, DeepImportStep


def _phase0_prefetch_result(
    quality_stats: dict | None = None,
    *,
    blocked: bool = False,
    block_reason: str | None = None,
) -> ScenePrefetchResult:
    return ScenePrefetchResult(
        quality_stats={
            "total_batches": 1,
            "completed_batches": 1,
            "success": 1,
            "failed": 0,
            "empty_result": 0,
            "schema_error": 0,
            "timeout": 0,
            "final_422": 0,
            "final_422_rate": 0.0,
            **(quality_stats or {}),
        },
        blocked=blocked,
        block_reason=block_reason,
    )


def _scene_candidate(
    candidate_id: str = "phase-candidate-1",
    *,
    source_round: str = "A",
    source_batch_id: str = "A-1-1",
    source_batch_index: int = 1,
    source_chapter_indices: list[int] | None = None,
    quality: str = "high",
) -> SceneCandidate:
    chapters = source_chapter_indices or [1]
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


def _phase1a_reinforcement_result(
    quality_stats: dict | None = None,
    *,
    blocked: bool = False,
    block_reason: str | None = None,
) -> SceneReinforcementResult:
    return SceneReinforcementResult(
        candidates=[] if blocked else [_scene_candidate("phase1a-candidate-1")],
        quality_stats={
            "total_batches": 1,
            "completed_batches": 1,
            "success": 1 if not blocked else 0,
            "failed": 0 if not blocked else 1,
            "final_422": 0,
            "final_422_rate": 0.0,
            **(quality_stats or {}),
        },
        blocked=blocked,
        block_reason=block_reason,
    )


def _final_scene_candidate(
    *,
    phase: str = "phase1b_fusion",
    fallback_required: bool = False,
) -> FinalSceneCandidate:
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
        source_chapter_indices=[1],
        operation="kept",
        confidence=0.9,
        fallback_required=fallback_required,
        boundary_status="complete",
        boundary_reason="",
        needs_review=fallback_required,
        review_reason="fallback" if fallback_required else "",
    )


def _phase1b_fusion_result(
    quality_stats: dict | None = None,
    *,
    degraded: bool = False,
    phase1a_fallback: bool = False,
) -> Phase1bFusionResult:
    return Phase1bFusionResult(
        candidates=[
            _final_scene_candidate(
                phase="phase1a_fallback" if phase1a_fallback else "phase1b_fusion",
                fallback_required=phase1a_fallback,
            )
        ],
        quality_stats={
            "total_windows": 1,
            "completed_windows": 1,
            "success": 1 if not degraded else 0,
            "failed": 0 if not degraded else 1,
            "final_422": 0 if not degraded else 1,
            "final_422_rate": 0.0 if not degraded else 1.0,
            **(quality_stats or {}),
        },
        degraded=degraded,
        phase1a_fallback=phase1a_fallback,
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


@pytest.mark.asyncio
async def test_phase0_small_sample_adapter_passes_timeout_budget(monkeypatch):
    captured: dict[str, object] = {}

    async def fake_load_chapters(_self, _db, _novel_id, _start, _end):
        return [
            {
                "chapter_index": 1,
                "title": "第一章",
                "content": "正文",
            }
        ]

    async def fake_structured_call(client, request, schema, **kwargs):
        del client, request, schema
        captured["kwargs"] = kwargs
        return {"scenes": [{"title": "候选", "scene_chunks": [{"chapter_index": 1}]}]}

    monkeypatch.setattr(
        "modules.imports.scene_segmentation.SceneSegmentationService._load_chapters",
        fake_load_chapters,
    )
    monkeypatch.setattr(
        "modules.imports.workflow._run_deep_import_structured_call",
        fake_structured_call,
    )

    batch = SceneCandidateBatch(
        batch_id="A-0001-1-5",
        round_name="A",
        batch_index=1,
        chapter_indices=[1],
    )
    await _Phase0SceneCandidateLLM(
        None,
        "novel-1",
        timeout_seconds=35,
    )(batch)

    assert captured["kwargs"]["timeout_seconds"] == 35


@pytest.mark.asyncio
async def test_phase1a_single_chapter_diagnostics_include_chapter(monkeypatch):
    async def fake_load_chapters(_self, _db, _novel_id, _start, _end):
        return [
            {
                "chapter_index": 3,
                "title": "第三章",
                "content": "正文",
            }
        ]

    async def fake_retry(operation, *, is_empty_result, max_retries):
        del operation, is_empty_result
        assert max_retries == 1
        return DeepImportRetryResult(
            attempts=1,
            final_status="success",
            value=SceneSegmentationOutput(
                scenes=[
                    SceneItem(
                        title="单章 Scene",
                        goal="保留定位",
                        scene_chunks=[SceneChunk(chapter_index=3)],
                    )
                ]
            ),
        )

    monkeypatch.setattr(
        "modules.imports.scene_segmentation.SceneSegmentationService._load_chapters",
        fake_load_chapters,
    )
    monkeypatch.setattr(
        "modules.imports.deep_import_retry.run_deep_import_llm_with_retry",
        fake_retry,
    )
    monkeypatch.setattr(
        "modules.imports.workflow.run_deep_import_llm_with_retry",
        fake_retry,
        raising=False,
    )

    result = await DeepImportWorkflow._run_phase1a_single_chapter_fallback(
        None,
        "novel-1",
        1,
        7,
        only_chapters=[3],
    )

    assert result.quality_stats["success"] == 1
    assert result.candidates[0].source_chapter_indices == [3]
    assert result.diagnostics[0]["chapter_index"] == 3
    assert result.diagnostics[0]["source_batch_id"] == "S-0003"


def test_small_sample_phase0_skip_result_does_not_count_timeouts():
    result = DeepImportWorkflow._small_sample_phase0_skip_result(1, 7)

    assert result.candidates == []
    assert result.quality_stats["total_batches"] == 3
    assert result.quality_stats["skipped"] == 3
    assert result.quality_stats["failed"] == 0
    assert result.quality_stats["timeout"] == 0
    assert result.quality_stats["skipped_for_small_sample"] is True
    assert DeepImportWorkflow._should_use_single_chapter_phase1a(
        result,
        start_chapter=1,
        end_chapter=7,
    ) is False


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
async def test_phase1b_llm_prompt_requires_complete_scene_contract(monkeypatch):
    captured: dict[str, object] = {}

    async def fake_structured_call(client, request, schema, **kwargs):
        del client, schema
        captured["request"] = request
        captured["kwargs"] = kwargs
        return {"scenes": []}

    monkeypatch.setattr(
        "modules.imports.workflow._run_deep_import_structured_call",
        fake_structured_call,
    )

    await _Phase1bSceneFusionLLM()(
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
    assert "title、goal、core_conflict、emotional_beat" in system_content
    assert "scene_chunks 内必须有 chapter_index" in system_content
    assert "source_chapter_indices 并集必须覆盖" in system_content
    assert "小样本 1-7 章不足 9 个时优先拆分跨章候选" in user_content
    assert "\"scene_chunks\":[{\"chapter_index\":1}]" in user_content
    assert request.max_tokens == 6144
    assert kwargs["timeout_seconds"] == 90


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
        status="running",
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
    async def _prefetch(_db, _novel_id, _start_chapter, _end_chapter):
        return _phase0_prefetch_result()

    async def _reinforce(
        _self,
        _db,
        _novel_id,
        _start_chapter,
        _end_chapter,
        _phase0_candidates,
    ):
        return _phase1a_reinforcement_result()

    async def _fuse(_phase1a_candidates, *, start_chapter, end_chapter):
        return _phase1b_fusion_result()

    async def _commit(_db, _novel_id, _candidates, *, workflow_id):
        return _scene_commit_result()

    monkeypatch.setattr(
        DeepImportWorkflow,
        "_run_phase0_prefetch",
        staticmethod(_prefetch),
    )
    monkeypatch.setattr(DeepImportWorkflow, "_run_phase1a_reinforcement", _reinforce)
    monkeypatch.setattr(
        DeepImportWorkflow,
        "_run_phase1b_fusion",
        staticmethod(_fuse),
    )
    monkeypatch.setattr(
        DeepImportWorkflow,
        "_commit_fused_scenes",
        staticmethod(_commit),
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
        progress.current_phase = "phase0_prefetch"
        progress.current_round = "A"
        progress.current_chapter_range = "1-5"
        progress.current_chapter = 3
        progress.current_scene_candidate_id = "scene-candidate-1"
        progress.current_window = "chapters:1-5"
        progress.current_operation = "scene_prefetch"
        progress.current_item = {"kind": "batch", "batch_id": "A-0001"}
        progress.phase_timeline = [
            {
                "phase": "phase0_prefetch",
                "status": "running",
                "started_at": "2026-06-30T10:00:00+00:00",
            }
        ]
        progress.diagnostic_counts = {"scene_count": 0}
        progress.last_error = {
            "phase": "phase0_prefetch",
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
            assert payload["current_phase"] == "phase0_prefetch"
            assert payload["current_round"] == "A"
            assert payload["current_chapter_range"] == "1-5"
            assert payload["current_chapter"] == 3
            assert payload["current_scene_candidate_id"] == "scene-candidate-1"
            assert payload["current_window"] == "chapters:1-5"
            assert payload["current_operation"] == "scene_prefetch"
            assert payload["current_item"]["batch_id"] == "A-0001"
            assert payload["phase_timeline"][0]["phase"] == "phase0_prefetch"
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

        assert result["current_step"] is None
        assert result["completed_steps"] == []


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
        assert result.quality_status == "complete"
        assert result.phase_errors == []
        timeline = {item["phase"]: item for item in result.phase_timeline}
        for phase in (
            "phase0_prefetch",
            "phase1a_reinforce",
            "phase1b_fusion",
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
        workflow._run_phase0_prefetch = AsyncMock(
            return_value=_phase0_prefetch_result()
        )
        workflow._run_phase1a_reinforcement = AsyncMock(
            return_value=_phase1a_reinforcement_result()
        )
        workflow._run_phase1b_fusion = AsyncMock(
            return_value=_phase1b_fusion_result()
        )
        workflow._commit_fused_scenes = AsyncMock(
            return_value=_scene_commit_result(created_count=2)
        )
        workflow._extract_entities_by_scene = AsyncMock()
        workflow._analyze_structure = AsyncMock()

        result = await workflow.run_step(
            db=AsyncMock(),
            novel_id=str(uuid.uuid4()),
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
        workflow._extract_entities_by_scene.assert_not_awaited()
        workflow._analyze_structure.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_world_object_stage_fails_without_scenes(self):
        workflow = DeepImportWorkflow()
        workflow._has_scenes_in_range = AsyncMock(return_value=False)
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

    @pytest.mark.asyncio
    async def test_world_object_stage_runs_phase2_only_for_range(self):
        workflow = DeepImportWorkflow()
        workflow._has_scenes_in_range = AsyncMock(return_value=True)
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
        workflow._extract_entities_by_scene.assert_awaited_once()
        assert workflow._extract_entities_by_scene.await_args.kwargs[
            "start_chapter"
        ] == 2
        assert workflow._extract_entities_by_scene.await_args.kwargs["end_chapter"] == 7

    @pytest.mark.asyncio
    async def test_plot_structure_stage_allows_missing_world_objects_as_partial(self):
        workflow = DeepImportWorkflow()
        workflow._has_scenes_in_range = AsyncMock(return_value=True)
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

    @pytest.mark.asyncio
    async def test_run_step_merges_snapshot_health_summary_and_audit_alias(self):
        """Phase 2/3 的快照摘要应进入 workflow progress 并保留兼容 alias。"""
        workflow = DeepImportWorkflow()
        progress = DeepImportProgress()

        workflow._segment_scenes = AsyncMock(
            return_value={
                "total_scenes": 1,
                "failed_batches": [],
                "degraded": False,
            }
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
        workflow._segment_scenes = AsyncMock()
        workflow._run_phase1a_reinforcement = AsyncMock()
        workflow._run_phase1b_fusion = AsyncMock()
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
        workflow._segment_scenes.assert_not_awaited()
        workflow._run_phase1a_reinforcement.assert_not_awaited()
        workflow._run_phase1b_fusion.assert_not_awaited()
        workflow._commit_fused_scenes.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_phase0_422_gate_stops_before_scene_segmentation(self):
        workflow = DeepImportWorkflow()
        progress = DeepImportProgress()
        workflow._run_phase0_prefetch = AsyncMock(
            return_value=_phase0_prefetch_result(
                {
                    "total_batches": 5,
                    "completed_batches": 5,
                    "success": 2,
                    "failed": 3,
                    "final_422": 3,
                    "final_422_rate": 0.60,
                },
                blocked=True,
                block_reason="phase0_422_rate_exceeded",
            )
        )
        workflow._segment_scenes = AsyncMock()
        workflow._run_phase1a_reinforcement = AsyncMock()
        workflow._run_phase1b_fusion = AsyncMock()
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
        assert result.degraded is True
        assert result.current_step is None
        assert result.quality_stats["phase0"]["final_422_rate"] == 0.60
        assert result.phase_errors == [
            {
                "phase": "phase0_prefetch",
                "error_kind": "phase0_422_rate_exceeded",
                "message": result.message[:300],
            }
        ]
        assert "推荐使用官方api以保障稳定性与质量" in result.message
        assert "强推 DeepSeek-v4-flash，质量高价格低并发超快" in result.message
        workflow._segment_scenes.assert_not_awaited()
        workflow._run_phase1a_reinforcement.assert_not_awaited()
        workflow._run_phase1b_fusion.assert_not_awaited()
        workflow._commit_fused_scenes.assert_not_awaited()
        workflow._extract_entities_by_scene.assert_not_awaited()
        workflow._analyze_structure.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_phase0_non_422_diagnostics_do_not_block_scene_reinforcement(self):
        workflow = DeepImportWorkflow()
        progress = DeepImportProgress()
        workflow._run_phase0_prefetch = AsyncMock(
            return_value=_phase0_prefetch_result(
                {
                    "total_batches": 5,
                    "completed_batches": 5,
                    "success": 2,
                    "failed": 3,
                    "empty_result": 1,
                    "schema_error": 1,
                    "timeout": 1,
                    "final_422": 0,
                    "final_422_rate": 0.0,
                }
            )
        )
        workflow._segment_scenes = AsyncMock()
        workflow._run_phase1a_reinforcement = AsyncMock(
            return_value=_phase1a_reinforcement_result()
        )
        workflow._run_phase1b_fusion = AsyncMock(
            return_value=_phase1b_fusion_result()
        )
        workflow._commit_fused_scenes = AsyncMock(
            return_value=_scene_commit_result(created_count=1)
        )
        workflow._extract_entities_by_scene = AsyncMock(
            return_value={
                "total_created": 1,
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
            end_chapter=10,
            progress=progress,
        )

        assert result.phase == "done"
        assert result.quality_stats["phase0"]["schema_error"] == 1
        assert result.quality_stats["phase0"]["empty_result"] == 1
        assert result.quality_stats["phase0"]["timeout"] == 1
        workflow._segment_scenes.assert_not_awaited()
        workflow._run_phase1a_reinforcement.assert_awaited_once()
        workflow._run_phase1b_fusion.assert_awaited_once()
        workflow._commit_fused_scenes.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_phase1a_422_gate_stops_before_phase1b_commit_phase2_phase3(self):
        workflow = DeepImportWorkflow()
        progress = DeepImportProgress()
        workflow._run_phase1a_reinforcement = AsyncMock(
            return_value=_phase1a_reinforcement_result(
                {
                    "total_batches": 5,
                    "completed_batches": 5,
                    "success": 2,
                    "failed": 3,
                    "final_422": 3,
                    "final_422_rate": 0.60,
                },
                blocked=True,
                block_reason="phase1a_422_rate_exceeded",
            )
        )
        workflow._run_phase1b_fusion = AsyncMock()
        workflow._commit_fused_scenes = AsyncMock()
        workflow._extract_entities_by_scene = AsyncMock()
        workflow._analyze_structure = AsyncMock()
        workflow._segment_scenes = AsyncMock()

        result = await workflow.run_step(
            db=None,
            novel_id=str(uuid.uuid4()),
            start_chapter=1,
            end_chapter=10,
            progress=progress,
        )

        assert result.phase == "failed"
        assert result.quality_status == "failed"
        assert result.degraded_reason == "phase1a_422_rate_exceeded"
        assert DeepImportStep.scene_segmentation.value not in result.completed_steps
        assert result.quality_stats["phase1a"]["final_422_rate"] == 0.60
        assert result.phase_errors[0]["phase"] == "phase1a_reinforce"
        timeline = {item["phase"]: item for item in result.phase_timeline}
        assert timeline["phase1a_reinforce"]["status"] == "failed"
        assert timeline["phase1a_reinforce"]["error_kind"] == (
            "phase1a_422_rate_exceeded"
        )
        assert result.last_error["phase"] == "phase1a_reinforce"
        assert result.last_error["error_kind"] == "phase1a_422_rate_exceeded"
        assert result.diagnostic_counts["scene_count"] == 0
        workflow._segment_scenes.assert_not_awaited()
        workflow._run_phase1b_fusion.assert_not_awaited()
        workflow._commit_fused_scenes.assert_not_awaited()
        workflow._extract_entities_by_scene.assert_not_awaited()
        workflow._analyze_structure.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_phase1b_degraded_still_commits_fallback_and_runs_phase2_phase3(self):
        workflow = DeepImportWorkflow()
        progress = DeepImportProgress()
        workflow._run_phase1b_fusion = AsyncMock(
            return_value=_phase1b_fusion_result(
                degraded=True,
                phase1a_fallback=True,
            )
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
        workflow._segment_scenes = AsyncMock()

        result = await workflow.run_step(
            db=None,
            novel_id=str(uuid.uuid4()),
            start_chapter=1,
            end_chapter=90,
            progress=progress,
        )

        assert result.phase == "done"
        assert result.quality_status == "partial"
        assert result.phase1a_fallback is True
        assert DeepImportStep.scene_segmentation.value in result.completed_steps
        assert DeepImportStep.entity_extraction.value in result.completed_steps
        assert DeepImportStep.structure_analysis.value in result.completed_steps
        assert result.phase_errors[0]["phase"] == "phase1b_fusion"
        workflow._segment_scenes.assert_not_awaited()
        workflow._commit_fused_scenes.assert_awaited_once()
        workflow._extract_entities_by_scene.assert_awaited_once()
        workflow._analyze_structure.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_phase1a_zero_success_uses_single_chapter_fallback(self):
        workflow = DeepImportWorkflow()
        progress = DeepImportProgress()
        fallback_result = _phase1a_reinforcement_result(
            {
                "total_batches": 3,
                "completed_batches": 3,
                "success": 3,
                "failed": 0,
            }
        )
        seen_phase1b_candidates = None

        async def phase1b(phase1a_candidates, *, start_chapter, end_chapter):
            nonlocal seen_phase1b_candidates
            seen_phase1b_candidates = phase1a_candidates
            assert (start_chapter, end_chapter) == (1, 3)
            return _phase1b_fusion_result()

        workflow._run_phase0_prefetch = AsyncMock(
            return_value=_phase0_prefetch_result()
        )
        workflow._run_phase1a_reinforcement = AsyncMock(
            return_value=_phase1a_reinforcement_result(
                {
                    "total_batches": 3,
                    "completed_batches": 3,
                    "success": 0,
                    "failed": 3,
                    "timeout": 3,
                }
            )
        )
        workflow._run_phase1a_single_chapter_fallback = AsyncMock(
            return_value=fallback_result
        )
        workflow._run_phase1b_fusion = AsyncMock(side_effect=phase1b)
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
        workflow._run_phase1a_single_chapter_fallback.assert_awaited_once()
        assert seen_phase1b_candidates == fallback_result.candidates
        assert result.quality_stats["phase1a"]["success"] == 3
        assert result.quality_stats["phase1a_single_chapter_fallback"]["success"] == 3

    @pytest.mark.asyncio
    async def test_phase0_all_failed_small_sample_skips_batch_phase1a(self):
        workflow = DeepImportWorkflow()
        progress = DeepImportProgress()
        fallback_result = _phase1a_reinforcement_result(
            {
                "total_batches": 3,
                "completed_batches": 3,
                "success": 3,
                "failed": 0,
            }
        )

        workflow._run_phase0_prefetch = AsyncMock(
            return_value=_phase0_prefetch_result(
                {
                    "total_batches": 3,
                    "completed_batches": 3,
                    "success": 0,
                    "failed": 3,
                    "timeout": 3,
                }
            )
        )
        workflow._run_phase1a_reinforcement = AsyncMock()
        workflow._run_phase1a_single_chapter_fallback = AsyncMock(
            return_value=fallback_result
        )
        workflow._run_phase1b_fusion = AsyncMock(return_value=_phase1b_fusion_result())
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
        workflow._run_phase1a_reinforcement.assert_not_awaited()
        workflow._run_phase1a_single_chapter_fallback.assert_awaited_once_with(
            None,
            ANY,
            1,
            3,
        )
        assert result.quality_stats["phase1a"]["direct_single_chapter_fallback"] is True

    @pytest.mark.asyncio
    async def test_phase0_skipped_small_sample_uses_direct_single_chapter_phase1a(self):
        workflow = DeepImportWorkflow()
        progress = DeepImportProgress()
        phase1a_result = _phase1a_reinforcement_result(
            {
                "total_batches": 7,
                "completed_batches": 7,
                "success": 3,
                "failed": 4,
                "direct_single_chapter_fallback": True,
            }
        )

        workflow._run_phase0_prefetch = AsyncMock(
            return_value=DeepImportWorkflow._small_sample_phase0_skip_result(1, 7)
        )
        workflow._run_phase1a_reinforcement = AsyncMock()
        workflow._run_phase1a_single_chapter_fallback = AsyncMock(
            return_value=phase1a_result
        )
        workflow._run_phase1b_fusion = AsyncMock(return_value=_phase1b_fusion_result())
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
            end_chapter=7,
            progress=progress,
        )

        assert result.phase == "done"
        workflow._run_phase1a_reinforcement.assert_not_awaited()
        workflow._run_phase1a_single_chapter_fallback.assert_awaited_once_with(
            None,
            ANY,
            1,
            7,
        )
        assert (
            result.quality_stats["phase1a"]["direct_single_chapter_fallback"] is True
        )
        assert "small_sample_parallel" not in result.quality_stats["phase1a"]

    @pytest.mark.asyncio
    async def test_phase1a_partial_coverage_falls_back_only_missing_chapters(self):
        workflow = DeepImportWorkflow()
        progress = DeepImportProgress()
        primary_candidate = _scene_candidate(
            "phase1a-candidate-1",
            source_chapter_indices=[1, 2],
        )
        fallback_candidate = _scene_candidate(
            "phase1a-single-3",
            source_batch_id="S-0003",
            source_batch_index=3,
            source_chapter_indices=[3],
        )
        fallback_result = SceneReinforcementResult(
            candidates=[fallback_candidate],
            quality_stats={
                "total_batches": 1,
                "completed_batches": 1,
                "success": 1,
                "failed": 0,
                "final_422": 0,
                "final_422_rate": 0.0,
            },
        )
        seen_phase1b_candidates = None

        async def phase1b(phase1a_candidates, *, start_chapter, end_chapter):
            nonlocal seen_phase1b_candidates
            seen_phase1b_candidates = phase1a_candidates
            assert (start_chapter, end_chapter) == (1, 3)
            return _phase1b_fusion_result()

        workflow._run_phase0_prefetch = AsyncMock(
            return_value=_phase0_prefetch_result()
        )
        workflow._run_phase1a_reinforcement = AsyncMock(
            return_value=SceneReinforcementResult(
                candidates=[primary_candidate],
                quality_stats={
                    "total_batches": 3,
                    "completed_batches": 3,
                    "success": 1,
                    "failed": 2,
                    "timeout": 2,
                    "final_422": 0,
                    "final_422_rate": 0.0,
                },
            )
        )
        workflow._run_phase1a_single_chapter_fallback = AsyncMock(
            return_value=fallback_result
        )
        workflow._run_phase1b_fusion = AsyncMock(side_effect=phase1b)
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
        workflow._run_phase1a_single_chapter_fallback.assert_awaited_once_with(
            None,
            ANY,
            1,
            3,
            only_chapters=[3],
        )
        assert seen_phase1b_candidates == [primary_candidate, fallback_candidate]
        assert result.quality_stats["phase1a"]["success"] == 2
        assert result.quality_stats["phase1a"]["failed"] == 2
        assert result.quality_stats["phase1a"]["fallback_chapter_count"] == 1

    @pytest.mark.asyncio
    async def test_happy_path_wires_phase0_phase1a_phase1b_commit_before_phase2_phase3(
        self,
    ):
        workflow = DeepImportWorkflow()
        progress = DeepImportProgress(workflow_id="wf-happy")
        calls: list[str] = []

        async def phase0(_db, _novel_id, _start_chapter, _end_chapter):
            calls.append("phase0")
            return _phase0_prefetch_result(
                {
                    "total_batches": 2,
                    "completed_batches": 2,
                }
            )

        async def phase1a(
            _db,
            _novel_id,
            _start_chapter,
            _end_chapter,
            phase0_candidates,
        ):
            calls.append("phase1a")
            assert phase0_candidates == []
            return _phase1a_reinforcement_result(
                {
                    "total_batches": 3,
                    "completed_batches": 3,
                }
            )

        async def phase1b(phase1a_candidates, *, start_chapter, end_chapter):
            calls.append("phase1b")
            assert phase1a_candidates
            assert (start_chapter, end_chapter) == (1, 3)
            return _phase1b_fusion_result(
                {
                    "total_windows": 1,
                    "completed_windows": 1,
                }
            )

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

        workflow._run_phase0_prefetch = AsyncMock(side_effect=phase0)
        workflow._run_phase1a_reinforcement = AsyncMock(side_effect=phase1a)
        workflow._run_phase1b_fusion = AsyncMock(side_effect=phase1b)
        workflow._commit_fused_scenes = AsyncMock(side_effect=commit)
        workflow._extract_entities_by_scene = AsyncMock(side_effect=phase2)
        workflow._analyze_structure = AsyncMock(side_effect=phase3)
        workflow._segment_scenes = AsyncMock()

        result = await workflow.run_step(
            db=None,
            novel_id=str(uuid.uuid4()),
            start_chapter=1,
            end_chapter=3,
            progress=progress,
        )

        assert result.phase == "done"
        assert calls == ["phase0", "phase1a", "phase1b", "commit", "phase2", "phase3"]
        assert result.phase1_total_batches == 7
        assert result.phase1_completed_batches == 7
        assert result.quality_stats["scene_commit"]["created_count"] == 2
        workflow._segment_scenes.assert_not_awaited()

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

        workflow._run_phase0_prefetch = AsyncMock(
            return_value=_phase0_prefetch_result()
        )
        workflow._run_phase1a_reinforcement = AsyncMock(
            return_value=_phase1a_reinforcement_result()
        )
        workflow._run_phase1b_fusion = AsyncMock(
            return_value=_phase1b_fusion_result()
        )
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
        workflow = DeepImportWorkflow()

        def _response(**kwargs):
            return Mock(id=uuid.uuid4(), **kwargs)

        thread_service = Mock()
        thread_service.create = AsyncMock(
            return_value=_response(
                name="第 1-7 章补强剧情线 4",
                thread_type="foreshadowing",
            )
        )
        arc_service = Mock()
        arc_service.create = AsyncMock(
            side_effect=[
                _response(title=f"第 1-7 章补强篇章纲 {index}", arc_index=index)
                for index in range(2, 5)
            ]
        )
        foreshadowing_service = Mock()
        foreshadowing_service.create = AsyncMock(
            return_value=_response(name="第 1-7 章补强伏笔 4")
        )
        reveal_service = Mock()
        reveal_service.create = AsyncMock(
            side_effect=[
                _response(target_name="克莱恩")
                for _ in range(3)
            ]
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
        ):
            updated = await workflow._ensure_minimum_structure_outputs(
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
        assert updated["warnings"] == [
            "小样本结构类别输出不足，已补充待复核结构候选。"
        ]
        thread_service.create.assert_awaited_once()
        assert arc_service.create.await_count == 3
        foreshadowing_service.create.assert_awaited_once()
        assert reveal_service.create.await_count == 3

    @pytest.mark.asyncio
    async def test_workflow_constant_monkeypatch_controls_structure_fallback_target(
        self,
        monkeypatch,
    ):
        workflow = DeepImportWorkflow()
        monkeypatch.setattr(
            "modules.imports.workflow.SMALL_SAMPLE_STRUCTURE_TARGET_COUNT",
            2,
        )

        def _response(**kwargs):
            return Mock(id=uuid.uuid4(), **kwargs)

        thread_service = Mock()
        thread_service.create = AsyncMock(
            return_value=_response(
                name="第 1-7 章补强剧情线 2",
                thread_type="foreshadowing",
            )
        )
        arc_service = Mock()
        arc_service.create = AsyncMock(
            return_value=_response(title="第 1-7 章补强篇章纲 2", arc_index=2)
        )
        foreshadowing_service = Mock()
        foreshadowing_service.create = AsyncMock(
            return_value=_response(name="第 1-7 章补强伏笔 2")
        )
        reveal_service = Mock()
        reveal_service.create = AsyncMock()

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
        ):
            updated = await workflow._ensure_minimum_structure_outputs(
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

    @pytest.mark.asyncio
    async def test_empty_phase2_and_phase3_outputs_are_partial(self):
        """Done with empty AI assets should be machine-readable as partial."""
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

    @pytest.mark.asyncio
    async def test_zero_scene_commit_is_failed_not_complete(self):
        """A run that commits no Scene must not be reported as complete."""
        workflow = DeepImportWorkflow()
        progress = DeepImportProgress()

        workflow._run_phase0_prefetch = AsyncMock(
            return_value=_phase0_prefetch_result()
        )
        workflow._run_phase1a_reinforcement = AsyncMock(
            return_value=_phase1a_reinforcement_result()
        )
        workflow._run_phase1b_fusion = AsyncMock(
            return_value=_phase1b_fusion_result()
        )
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
        scene_commit = {
            item["phase"]: item for item in result.phase_timeline
        }["scene_commit"]
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

        workflow._segment_scenes = AsyncMock(
            return_value={
                "total_scenes": 5,
                "failed_batches": [],
                "degraded": False,
            }
        )
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
            "modules.imports.workflow.PHASE3_STRUCTURE_TIMEOUT_SECONDS",
            0.01,
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
            await asyncio.sleep(1)
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

        workflow._segment_scenes = AsyncMock(
            return_value={
                "total_scenes": 3,
                "failed_batches": [],
                "degraded": False,
            }
        )
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
            (0.0, "running", "scene_segmentation", "phase0_prefetch", []),
            (0.1, "running", "scene_segmentation", "phase1a_reinforce", []),
            (0.2, "running", "scene_segmentation", "phase1b_fusion", []),
            (0.3, "running", "scene_segmentation", "scene_commit", []),
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
        orchestrator._enqueue_deep_import.assert_called_once_with(
            db,
            "novel-1",
            1,
            3,
            context_mode="working",
            include_pending_objects=True,
        )
        db.flush.assert_awaited_once()
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

        result = await DeepImportOrchestrator().resume_interrupted(
            db_session, str(task.id)
        )

        assert result["task_id"] == str(task.id)
        assert result["workflow_id"] == str(task.id)
        assert result["status"] == "pending"
        assert task.status == "pending"
        assert task.result["interrupted"] is False
        assert task.result["recovery_required"] is False
        assert task.meta["interrupted"] is False
        assert task.meta["recovery_required"] is False

    @pytest.mark.asyncio
    async def test_resume_missing_deep_import_task_raises_not_found(
        self,
        db_session,
    ):
        from modules.imports.contracts import TaskNotFoundError

        task_id = str(uuid.uuid4())

        with pytest.raises(TaskNotFoundError) as exc_info:
            await DeepImportOrchestrator().resume_interrupted(db_session, task_id)

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

        with pytest.raises(ValueError, match="deep_import"):
            await DeepImportOrchestrator().resume_interrupted(db_session, str(task.id))

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
            await DeepImportOrchestrator().resume_interrupted(db_session, str(task.id))

    @pytest.mark.asyncio
    async def test_abandon_recovery_marks_original_cancelled_with_cleanup_summary(
        self,
        db_session,
    ):
        task = await _create_recoverable_deep_import_task(db_session)

        result = await DeepImportOrchestrator().abandon_recovery(
            db_session, str(task.id)
        )

        assert result["task_id"] == str(task.id)
        assert result["workflow_id"] == str(task.id)
        assert result["status"] == "cancelled"
        assert result["cleanup_summary"] == {
            "deprecated_scenes": 0,
            "deprecated_entities": 0,
            "deprecated_structure_assets": 0,
            "hard_deleted_assets": 0,
            "cleanup_mode": "soft_deprecate",
            "skipped_delta_logs": 0,
            "skipped_map_observations": 0,
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
        orchestrator = DeepImportOrchestrator()
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
        from modules.outline.models import OutlineArc, PlotThread, Scene
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

        summary = await DeepImportOrchestrator().cleanup_workflow_assets(
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
            meta={"novel_id": "n1", "start_chapter": 2, "end_chapter": 4},
        )
        task.update_progress = Mock()
        db = AsyncMock()

        result = await orchestrator.run_task(db, task)

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
            "diagnostic_counts": {},
            "last_error": None,
            "quality_stats": {},
            "checkpoints": {},
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

        orchestrator = DeepImportOrchestrator(progress_observer=observer)

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
            meta={"novel_id": "n1", "start_chapter": 1, "end_chapter": 2},
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
    async def test_run_task_restores_progress_checkpoints_from_task_result(self):
        task_id = uuid.uuid4()
        orchestrator = DeepImportOrchestrator()
        progress = DeepImportProgress(phase="done", message="恢复完成")
        orchestrator.workflow.run_step = AsyncMock(return_value=progress)
        task = Mock(
            id=task_id,
            meta={"novel_id": "n1", "start_chapter": 2, "end_chapter": 4},
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

        with patch("modules.imports.workflow._container_get", return_value=generate):
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

        with patch(
            "modules.imports.facade.resume_deep_import",
            new_callable=AsyncMock,
            return_value=expected,
        ) as resume:
            response = await async_client.post(
                "/api/imports/deep/resume",
                json={"task_id": task_id},
            )

        assert response.status_code == 201
        assert response.json() == expected
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
        }

        with patch(
            "modules.imports.facade.abandon_deep_import",
            new_callable=AsyncMock,
            return_value=expected,
        ) as abandon:
            response = await async_client.post(
                "/api/imports/deep/abandon",
                json={"task_id": task_id},
            )

        assert response.status_code == 200
        assert response.json() == expected
        abandon.assert_awaited_once()


class TestSceneSegmentationProgress:
    """测试 Scene 切分服务的细粒度进度回调"""

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

        assert [
            [ch["chapter_index"] for ch in batch] for batch in batches
        ] == [[1, 2], [2, 3], [3, 4]]
        assert all(
            sum(len(ch["content"]) for ch in batch) <= 10 for batch in batches
        )

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

        assert [
            [ch["chapter_index"] for ch in batch] for batch in batches
        ] == [[1], [2, 3]]

    @pytest.mark.asyncio
    async def test_generate_with_timeout_raises_llm_timeout(self):
        """HTTP 客户端未及时超时时，上层应主动中断 LLM 调用。"""
        from infrastructure.llm.errors import LLMTimeoutError

        class SlowLLMClient:
            provider = "openai"

            async def generate(self, _request):
                import asyncio

                await asyncio.sleep(1)

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
            existing_checkpoints={"unrelated-scene": {"status": "done"}},
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
                "_run_phase0_prefetch",
                new_callable=AsyncMock,
                return_value=_phase0_prefetch_result(),
            ),
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
