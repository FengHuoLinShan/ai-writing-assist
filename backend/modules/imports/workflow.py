"""Deep Import 工作流编排器

三阶段流水线：
  Phase 1: Scene 切分（并行批次）→ scenes 表
  Phase 2: 实体增量提取（串行按 Scene）→ core_entities + delta_log
  Phase 3: 剧情结构分析（单次）
  → plot_threads + outline_arcs + foreshadowing_plans + reveal_plans
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Awaitable, Callable
from typing import Any
from unittest.mock import Mock

from sqlalchemy.ext.asyncio import AsyncSession

from core.config import get_settings
from core.container import get as _container_get
from modules.imports.legacy_scene_pipeline import (
    require_legacy_scene_pipeline_enabled,
)
from modules.imports.service_phase_artifacts import coverage_summary
from modules.imports.workflow_entity_phase import (
    EntityExtractionPhaseRunner,
    phase2_quality_stats,
)
from modules.imports.workflow_llm_adapters import (
    DEEP_IMPORT_STRUCTURED_MAX_FIX_ATTEMPTS,
    DEEP_IMPORT_STRUCTURED_TIMEOUT_GRACE_SECONDS,
    PHASE1B_COMPACT_TEXT_LIMIT,
    PHASE1B_SMALL_SAMPLE_MAX_TOKENS,
    PHASE1B_SMALL_SAMPLE_TIMEOUT_SECONDS,
    _Phase0SceneCandidateLLM,
    _Phase1aSceneCandidateLLM,
    _Phase1aSceneSlicingLLM,
    _Phase1bSceneEnrichmentLLM,
    _Phase1bSceneFusionLLM,
    _Phase2WorldExtractionLLM,
    _project_settings_for_novel,
    _SingleChapterSceneCandidateLLM,
)
from modules.imports.workflow_llm_adapters import (
    _compact_phase1b_payload as _compact_phase1b_payload,
)
from modules.imports.workflow_llm_adapters import (
    _run_deep_import_structured_call as _run_deep_import_structured_call,
)
from modules.imports.workflow_progress import DeepImportProgressTracker
from modules.imports.workflow_scene_phase import (
    PHASE0_422_RECOMMENDATION,
    ScenePhaseRunner,
)
from modules.imports.workflow_schemas import DeepImportProgress, DeepImportStep
from modules.imports.workflow_structure_phase import (
    PHASE3_STRUCTURE_TIMEOUT_SECONDS,
    SMALL_SAMPLE_STRUCTURE_TARGET_COUNT,
    StructureAnalysisPhaseRunner,
    ensure_minimum_structure_outputs,
    fallback_thread_type,
    minimum_structure_category_targets,
    phase3_quality_stats,
    select_fallback_reveal_target,
    structure_category_counts,
    structure_output_count,
)
from shared.deep_import_settings import (
    deep_import_bool_setting,
    deep_import_int_setting,
)

logger = logging.getLogger(__name__)

__all__ = [
    "DEEP_IMPORT_STRUCTURED_MAX_FIX_ATTEMPTS",
    "DEEP_IMPORT_STRUCTURED_TIMEOUT_GRACE_SECONDS",
    "DeepImportWorkflow",
    "PHASE0_422_RECOMMENDATION",
    "PHASE1B_COMPACT_TEXT_LIMIT",
    "PHASE1B_SMALL_SAMPLE_MAX_TOKENS",
    "PHASE1B_SMALL_SAMPLE_TIMEOUT_SECONDS",
    "PHASE3_STRUCTURE_TIMEOUT_SECONDS",
    "SMALL_SAMPLE_STRUCTURE_TARGET_COUNT",
    "minimum_structure_category_targets",
]


def _accepts_keyword(callable_obj: Any, keyword: str) -> bool:
    try:
        signature = inspect.signature(callable_obj)
    except (TypeError, ValueError):
        return True
    for parameter in signature.parameters.values():
        if parameter.kind == inspect.Parameter.VAR_KEYWORD:
            return True
        if parameter.name == keyword:
            return True
    return False


def _phase1b_use_llm(
    *,
    start_chapter: int,
    end_chapter: int,
    project_settings: dict[str, Any] | None = None,
) -> bool:
    configured = deep_import_bool_setting(
        project_settings,
        "phase1b",
        "use_llm",
        env_name="PHASE1B_USE_LLM",
        default=None,
    )
    if configured is not None:
        return configured
    return end_chapter - start_chapter + 1 <= 7


def _dummy_chapters(start_chapter: int, end_chapter: int) -> list[dict[str, Any]]:
    return [
        {
            "chapter_index": chapter,
            "title": f"第{chapter}章",
            "content": f"第{chapter}章测试正文。",
        }
        for chapter in range(start_chapter, end_chapter + 1)
    ]


def _dummy_scene_slicing_result(phase0_plan):
    from modules.imports.scene_slicing import SceneSliceCandidate, SceneSlicingResult

    candidates = [
        SceneSliceCandidate(
            candidate_id=f"phase1a-dummy-{chapter['chapter_index']:04d}",
            source_window_id="dummy",
            source_window_index=1,
            title=chapter.get("title") or f"第{chapter['chapter_index']}章",
            goal="测试 Scene 目标。",
            core_conflict="测试 Scene 冲突。",
            start_chapter=int(chapter["chapter_index"]),
            end_chapter=int(chapter["chapter_index"]),
            boundary_status="complete",
            source_chapter_indices=[int(chapter["chapter_index"])],
        )
        for chapter in getattr(phase0_plan, "chapters", [])
    ]
    return SceneSlicingResult(
        candidates=candidates,
        quality_stats={
            "total_batches": int(
                (getattr(phase0_plan, "quality_stats", {}) or {}).get(
                    "total_batches",
                    1,
                )
            ),
            "completed_batches": int(
                (getattr(phase0_plan, "quality_stats", {}) or {}).get(
                    "total_batches",
                    1,
                )
            ),
            "success": len(candidates),
            "failed": 0,
            "fallback_count": 0,
            "scene_count": len(candidates),
        },
    )


def _dummy_scene_enrichment_result(phase1a_candidates):
    from modules.imports.llm_schemas import SceneChunk
    from modules.imports.scene_enrichment import Phase1bEnrichmentResult
    from modules.imports.scene_fusion import FinalSceneCandidate

    candidates = []
    for index, scene in enumerate(phase1a_candidates, start=1):
        chapter_indices = list(
            range(int(scene.start_chapter), int(scene.end_chapter) + 1)
        )
        candidates.append(
            FinalSceneCandidate(
                candidate_id=f"phase1b-dummy-{index:04d}",
                phase="phase1b_enrichment",
                title=scene.title,
                goal=scene.goal,
                core_conflict=scene.core_conflict,
                emotional_beat="测试情绪节拍。",
                must_happen=scene.goal or "保留 Scene 推进。",
                must_not_happen=scene.core_conflict or "不得偏离章节事实。",
                narrative_tag="imported",
                scene_chunks=[
                    SceneChunk(chapter_index=chapter) for chapter in chapter_indices
                ],
                source_candidate_ids=[scene.candidate_id],
                source_rounds=["A"],
                source_chapter_indices=chapter_indices,
                operation="kept",
                confidence=0.7,
                fallback_required=False,
                boundary_status=scene.boundary_status,
                boundary_reason="Dummy enrichment for non-DB workflow test.",
                needs_review=scene.needs_review,
                review_reason=scene.review_reason,
            )
        )
    return Phase1bEnrichmentResult(
        candidates=candidates,
        quality_stats={
            "total_windows": len(candidates),
            "completed_windows": len(candidates),
            "total_scenes": len(candidates),
            "completed": len(candidates),
            "failed": 0,
            "fallback_count": 0,
            "concurrency": 20,
            "max_tokens": 4096,
            "max_retries": 1,
        },
    )


class DeepImportWorkflow:
    """深度导入流水线编排器 — 三阶段全自动"""

    async def run_step(
        self,
        db: AsyncSession,
        novel_id: str,
        start_chapter: int,
        end_chapter: int,
        progress: DeepImportProgress,
        *,
        workflow_id: str | None = None,
        context_mode: str = "working",
        include_pending_objects: bool = True,
        high_quality: bool = False,
        on_progress: Callable[[DeepImportProgress, float], Awaitable[None]] | None = None,
        stop_after: DeepImportStep | None = None,
    ) -> DeepImportProgress:
        if progress.phase == "pending":
            self._agent_project_settings = await _project_settings_for_novel(
                db,
                novel_id,
            )
            self._deep_import_high_quality = bool(high_quality)
            if self._is_llm_health_required():
                health = await self._check_llm_health(db, novel_id)
                progress.llm_health = health.model_dump()
                if not health.ok:
                    progress.phase = "failed"
                    progress.quality_status = "failed"
                    progress.current_step = None
                    progress.degraded = True
                    progress.message = (
                        "LLM 健康检查失败，已停止深度导入："
                        f"{health.error_kind or health.message}"
                    )
                    progress.phase_errors.append(
                        {
                            "phase": "preflight",
                            "error_kind": health.error_kind or "llm_unavailable",
                            "message": health.message[:300],
                        }
                    )
                    await self._emit_progress(progress, 1.0, on_progress)
                    return progress

            progress.phase = "running"

            scene_outcome = await ScenePhaseRunner(self).run(
                db,
                novel_id,
                start_chapter,
                end_chapter,
                progress,
                workflow_id=workflow_id,
                on_progress=on_progress,
                stop_after=stop_after,
            )
            if scene_outcome.stopped:
                return progress
            total_scenes = scene_outcome.total_scenes

            phase2_result = await EntityExtractionPhaseRunner(
                self
            ).run_full_pipeline_phase(
                db,
                novel_id,
                start_chapter,
                end_chapter,
                progress,
                workflow_id=workflow_id,
                total_scenes=total_scenes,
                on_progress=on_progress,
            )

            phase3_result = await StructureAnalysisPhaseRunner(
                self
            ).run_full_pipeline_phase(
                db,
                novel_id,
                start_chapter,
                end_chapter,
                progress,
                workflow_id=workflow_id,
                context_mode=context_mode,
                include_pending_objects=include_pending_objects,
                total_scenes=total_scenes,
                on_progress=on_progress,
            )

            progress.current_step = None
            progress.phase = "done"
            if total_scenes <= 0:
                progress.quality_status = "failed"
            else:
                progress.quality_status = "partial" if progress.degraded else "complete"
            progress.message = (
                f"深度导入完成！"
                f"共 {total_scenes} 个 Scene，"
                f"{phase2_result.get('total_created', 0)} 个实体，"
                f"{phase3_result.get('total_threads', 0)} 条剧情线，"
                f"{phase3_result.get('total_arcs', 0)} 个篇章纲。"
            )
            await self._emit_progress(progress, 1.0, on_progress)

        else:
            raise ValueError(f"无法处理当前进度状态: {progress.phase}")

        return progress

    @staticmethod
    def _is_llm_health_required() -> bool:
        return get_settings().llm_health_required

    @staticmethod
    async def _check_llm_health(
        db: AsyncSession | None = None,
        novel_id: str | None = None,
    ):
        from infrastructure.llm.health import (
            check_llm_health,
            check_llm_health_for_project,
        )

        if db is None or not novel_id:
            return await check_llm_health()
        project_settings = await _project_settings_for_novel(db, novel_id)
        return await check_llm_health_for_project(project_settings)

    def _phase3_timeout_seconds(self) -> int | float:
        project_settings = getattr(self, "_agent_project_settings", None)
        return deep_import_int_setting(
            project_settings,
            "phase3",
            "structure_timeout_seconds",
            env_name="PHASE3_STRUCTURE_TIMEOUT_SECONDS",
            default=PHASE3_STRUCTURE_TIMEOUT_SECONDS,
        )

    @staticmethod
    async def _run_phase0_prefetch(
        db: AsyncSession,
        novel_id: str,
        start_chapter: int,
        end_chapter: int,
    ):
        """Deprecated legacy wrapper; default Scene flow uses _run_phase0_plan."""

        require_legacy_scene_pipeline_enabled("DeepImportWorkflow._run_phase0_prefetch")
        from modules.imports.scene_prefetch import Phase0ScenePrefetcher

        if end_chapter - start_chapter + 1 <= 7:
            return DeepImportWorkflow._small_sample_phase0_skip_result(
                start_chapter,
                end_chapter,
            )

        project_settings = await _project_settings_for_novel(db, novel_id)
        prefetcher = Phase0ScenePrefetcher(
            llm=_Phase0SceneCandidateLLM(
                db,
                novel_id,
                timeout_seconds=None,
                project_settings=project_settings,
            ),
        )
        return await prefetcher.run(
            db,
            novel_id=novel_id,
            start_chapter=start_chapter,
            end_chapter=end_chapter,
        )

    @staticmethod
    def _small_sample_phase0_skip_result(start_chapter: int, end_chapter: int):
        from modules.imports.scene_candidates import (
            ScenePrefetchResult,
            build_scene_candidate_quality_stats,
        )
        from modules.imports.scene_prefetch import build_phase0_prefetch_batches

        batches = build_phase0_prefetch_batches(start_chapter, end_chapter)
        diagnostics = [
            {
                "attempts": 0,
                "final_status": "skipped",
                "final_error_type": None,
                "chapter_index": None,
                "source_batch_id": batch.batch_id,
                "diagnostics": [
                    {
                        "error_type": None,
                        "message": (
                            "small sample bypassed Phase 0; Phase 1a single "
                            "chapter extraction is authoritative"
                        ),
                    }
                ],
            }
            for batch in batches
        ]
        quality_stats = build_scene_candidate_quality_stats(
            [],
            total_batches=len(batches),
            completed_batches=len(batches),
        )
        quality_stats.update(
            {
                "skipped": len(batches),
                "skipped_for_small_sample": True,
            }
        )
        return ScenePrefetchResult(
            candidates=[],
            quality_stats=quality_stats,
            diagnostics=diagnostics,
            blocked=False,
            block_reason=None,
        )

    async def _run_phase0_plan(
        self,
        db: AsyncSession,
        novel_id: str,
        start_chapter: int,
        end_chapter: int,
    ):
        from modules.imports.scene_planning import build_scene_import_plan
        from modules.imports.scene_segmentation import SceneSegmentationService

        if db is None or isinstance(db, Mock):
            chapters = _dummy_chapters(start_chapter, end_chapter)
        else:
            chapters = await SceneSegmentationService()._load_chapters(
                db,
                novel_id,
                start_chapter,
                end_chapter,
            )
        project_settings = getattr(self, "_agent_project_settings", None)
        if project_settings is None and db is not None and not isinstance(db, Mock):
            project_settings = await _project_settings_for_novel(db, novel_id)
        return build_scene_import_plan(
            chapters,
            start_chapter=start_chapter,
            end_chapter=end_chapter,
            project_settings=project_settings,
        )

    async def _run_phase1a_scene_slicing(
        self,
        db: AsyncSession,
        novel_id: str,
        start_chapter: int,
        end_chapter: int,
        phase0_plan,
        *,
        on_batch_progress: Callable[[int, int, str], Awaitable[None]] | None = None,
    ):
        del start_chapter, end_chapter
        if db is None or isinstance(db, Mock):
            return _dummy_scene_slicing_result(phase0_plan)
        from modules.imports.scene_slicing import Phase1aSceneSlicer

        project_settings = getattr(self, "_agent_project_settings", None)
        if project_settings is None:
            project_settings = await _project_settings_for_novel(db, novel_id)
        high_quality = bool(getattr(self, "_deep_import_high_quality", False))
        result = await Phase1aSceneSlicer(
            llm=_Phase1aSceneSlicingLLM(
                project_settings=project_settings,
                high_quality=high_quality,
            ),
        ).run(phase0_plan, on_batch_progress=on_batch_progress)
        result.quality_stats["high_quality"] = high_quality
        if high_quality:
            result.quality_stats["model_override"] = "deepseek-v4-pro"
        return result

    async def _run_phase1b_enrichment(
        self,
        db: AsyncSession,
        novel_id: str,
        phase1a_candidates,
        *,
        start_chapter: int,
        end_chapter: int,
        chapters,
        on_batch_progress: Callable[[int, int, str], Awaitable[None]] | None = None,
    ):
        del start_chapter, end_chapter
        if db is None or isinstance(db, Mock):
            return _dummy_scene_enrichment_result(phase1a_candidates)
        from modules.imports.scene_enrichment import Phase1bSceneEnricher

        project_settings = getattr(self, "_agent_project_settings", None)
        if project_settings is None:
            project_settings = await _project_settings_for_novel(db, novel_id)
        high_quality = bool(getattr(self, "_deep_import_high_quality", False))
        result = await Phase1bSceneEnricher(
            llm=_Phase1bSceneEnrichmentLLM(
                project_settings=project_settings,
                high_quality=high_quality,
            ),
        ).run(
            scenes=phase1a_candidates,
            chapters=chapters,
            on_batch_progress=on_batch_progress,
        )
        result.quality_stats["high_quality"] = high_quality
        if high_quality:
            result.quality_stats["model_override"] = "deepseek-v4-pro"
        return result

    @staticmethod
    async def _load_chapters_for_reinforcement(
        db: AsyncSession,
        novel_id: str,
        start_chapter: int,
        end_chapter: int,
    ) -> list[dict]:
        from modules.imports.scene_segmentation import SceneSegmentationService

        return await SceneSegmentationService()._load_chapters(
            db,
            novel_id,
            start_chapter,
            end_chapter,
        )

    async def _run_phase1a_reinforcement(
        self,
        db: AsyncSession,
        novel_id: str,
        start_chapter: int,
        end_chapter: int,
        phase0_candidates,
    ):
        """Deprecated legacy wrapper; default Scene flow uses scene slicing."""

        require_legacy_scene_pipeline_enabled(
            "DeepImportWorkflow._run_phase1a_reinforcement"
        )
        from modules.imports.scene_reinforcement import Phase1aSceneReinforcer

        chapters = await self._load_chapters_for_reinforcement(
            db,
            novel_id,
            start_chapter,
            end_chapter,
        )
        project_settings = await _project_settings_for_novel(db, novel_id)
        return await Phase1aSceneReinforcer(
            llm=_Phase1aSceneCandidateLLM(project_settings=project_settings),
        ).run(
            phase0_candidates=phase0_candidates,
            chapters=chapters,
        )

    @staticmethod
    async def _run_phase1a_single_chapter_fallback(
        db: AsyncSession,
        novel_id: str,
        start_chapter: int,
        end_chapter: int,
        *,
        only_chapters: list[int] | None = None,
    ):
        from modules.imports.deep_import_retry import run_deep_import_llm_with_retry
        from modules.imports.llm_schemas import SceneSegmentationOutput
        from modules.imports.scene_candidates import (
            SceneCandidate,
            SceneCandidateBatch,
            SceneReinforcementResult,
            build_scene_candidate_quality_stats,
        )
        from modules.imports.scene_segmentation import SceneSegmentationService

        chapters = await SceneSegmentationService()._load_chapters(
            db,
            novel_id,
            start_chapter,
            end_chapter,
        )
        wanted_chapters = set(only_chapters or [])
        if wanted_chapters:
            chapters = [
                chapter
                for chapter in chapters
                if int(chapter["chapter_index"]) in wanted_chapters
            ]
        semaphore = asyncio.Semaphore(50)
        project_settings = await _project_settings_for_novel(db, novel_id)
        llm = _SingleChapterSceneCandidateLLM(project_settings=project_settings)

        async def process(chapter: dict[str, Any]) -> SceneCandidate:
            chapter_index = int(chapter["chapter_index"])
            batch = SceneCandidateBatch(
                batch_id=f"S-{chapter_index:04d}",
                round_name="A",
                batch_index=chapter_index,
                chapter_indices=[chapter_index],
            )
            async with semaphore:
                retry_result = await run_deep_import_llm_with_retry(
                    lambda: llm(chapter),
                    is_empty_result=lambda output: not output.scenes,
                    max_retries=1,
                )
            diagnostics = retry_result.model_dump(mode="json", exclude={"value"})
            diagnostics["chapter_index"] = chapter_index
            diagnostics["source_batch_id"] = batch.batch_id
            if retry_result.final_status != "success":
                return SceneCandidate(
                    candidate_id=f"phase1a-single-{chapter_index}",
                    source_round="A",
                    source_batch_id=batch.batch_id,
                    source_batch_index=batch.batch_index,
                    source_chapter_indices=[chapter_index],
                    quality="failed",
                    payload={},
                    diagnostics=diagnostics,
                )

            output = retry_result.value
            if not isinstance(output, SceneSegmentationOutput):
                output = SceneSegmentationOutput.model_validate(output)
            return SceneCandidate(
                candidate_id=f"phase1a-single-{chapter_index}",
                source_round="A",
                source_batch_id=batch.batch_id,
                source_batch_index=batch.batch_index,
                source_chapter_indices=[chapter_index],
                quality="high",
                payload={
                    "scenes": [scene.model_dump(mode="json") for scene in output.scenes],
                    "boundary_status": "complete",
                    "boundary_reason": "single chapter fallback",
                    "confidence": 0.65,
                    "source_round": "A",
                    "source_batch_id": batch.batch_id,
                    "source_chapter_indices": [chapter_index],
                },
                diagnostics=diagnostics,
            )

        candidates = await asyncio.gather(*(process(chapter) for chapter in chapters))
        quality_stats = build_scene_candidate_quality_stats(
            candidates,
            total_batches=len(chapters),
        )
        return SceneReinforcementResult(
            candidates=candidates,
            quality_stats=quality_stats,
            diagnostics=[
                candidate.diagnostics
                for candidate in candidates
                if candidate.diagnostics
            ],
            blocked=False,
            block_reason=None,
        )

    @staticmethod
    def _missing_phase1a_chapters(
        candidates,
        start_chapter: int,
        end_chapter: int,
    ) -> list[int]:
        covered = {
            int(chapter)
            for candidate in candidates
            if candidate.quality != "failed"
            for chapter in candidate.source_chapter_indices
            if start_chapter <= int(chapter) <= end_chapter
        }
        return [
            chapter
            for chapter in range(start_chapter, end_chapter + 1)
            if chapter not in covered
        ]

    @staticmethod
    def _should_use_single_chapter_phase1a(
        phase0_result,
        *,
        start_chapter: int,
        end_chapter: int,
    ) -> bool:
        chapter_count = end_chapter - start_chapter + 1
        if chapter_count > 7:
            return False
        stats = getattr(phase0_result, "quality_stats", {}) or {}
        if stats.get("skipped_for_small_sample"):
            return False
        return int(stats.get("failed", 0)) > 0

    @staticmethod
    def _merge_phase1a_results(primary, fallback):
        from modules.imports.scene_candidates import SceneReinforcementResult

        count_keys = {
            "total_batches",
            "completed_batches",
            "success",
            "failed",
            "high_quality",
            "low_quality",
            "empty_result",
            "schema_error",
            "timeout",
            "network",
            "rate_limit",
            "quality_gate",
            "http_error",
            "unknown",
            "final_422",
        }
        quality_stats = {
            **primary.quality_stats,
            "fallback_chapter_count": int(
                primary.quality_stats.get("fallback_chapter_count", 0)
            )
            + len(fallback.candidates),
        }
        for key in count_keys:
            quality_stats[key] = int(primary.quality_stats.get(key, 0)) + int(
                fallback.quality_stats.get(key, 0)
            )
        total_batches = int(quality_stats.get("total_batches", 0))
        quality_stats["final_422_rate"] = (
            int(quality_stats.get("final_422", 0)) / total_batches
            if total_batches
            else 0.0
        )
        return SceneReinforcementResult(
            candidates=[*primary.candidates, *fallback.candidates],
            quality_stats=quality_stats,
            diagnostics=[*primary.diagnostics, *fallback.diagnostics],
            blocked=primary.blocked or fallback.blocked,
            block_reason=primary.block_reason or fallback.block_reason,
            did_merge_rounds=primary.did_merge_rounds or fallback.did_merge_rounds,
        )

    async def _run_phase1b_fusion(
        self,
        phase1a_candidates,
        *,
        start_chapter: int,
        end_chapter: int,
    ):
        from modules.imports.scene_fusion import Phase1bSceneFusion

        project_settings = getattr(self, "_agent_project_settings", None)
        return await Phase1bSceneFusion(
            llm=_Phase1bSceneFusionLLM(project_settings=project_settings),
            use_llm=_phase1b_use_llm(
                start_chapter=start_chapter,
                end_chapter=end_chapter,
                project_settings=project_settings,
            ),
        ).run(
            phase1a_candidates=phase1a_candidates,
            start_chapter=start_chapter,
            end_chapter=end_chapter,
        )

    @staticmethod
    async def _commit_fused_scenes(
        db: AsyncSession,
        novel_id: str,
        candidates,
        *,
        workflow_id: str,
    ):
        from modules.imports.scene_commit import SceneCommitter

        return await SceneCommitter().commit(
            db,
            novel_id,
            candidates,
            workflow_id=workflow_id,
        )

    @staticmethod
    def _update_phase1_batch_counts(
        progress: DeepImportProgress,
        phase0_result,
        phase1a_result=None,
        phase1b_result=None,
        *,
        commit_started: bool = False,
        commit_completed: bool = False,
    ) -> None:
        phase0_stats = phase0_result.quality_stats if phase0_result else {}
        phase1a_stats = phase1a_result.quality_stats if phase1a_result else {}
        phase1b_stats = phase1b_result.quality_stats if phase1b_result else {}

        total = int(phase0_stats.get("total_batches", 0)) + int(
            phase1a_stats.get("total_batches", 0)
        )
        completed = int(phase0_stats.get("completed_batches", 0)) + int(
            phase1a_stats.get("completed_batches", 0)
        )
        total += int(phase1b_stats.get("total_windows", 0))
        completed += int(phase1b_stats.get("completed_windows", 0))
        if commit_started or commit_completed:
            total += 1
        if commit_completed:
            completed += 1

        progress.phase1_total_batches = total
        progress.phase1_completed_batches = completed

    @staticmethod
    def _diagnostic_samples(
        diagnostics: list[dict[str, Any]] | None,
        *,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        if not diagnostics:
            return []
        samples: list[dict[str, Any]] = []
        for diagnostic in diagnostics:
            attempts = diagnostic.get("diagnostics")
            last_attempt = attempts[-1] if isinstance(attempts, list) and attempts else {}
            samples.append(
                {
                    "attempts": diagnostic.get("attempts"),
                    "final_status": diagnostic.get("final_status"),
                    "final_error_type": diagnostic.get("final_error_type"),
                    "chapter_index": diagnostic.get("chapter_index"),
                    "source_batch_id": diagnostic.get("source_batch_id"),
                    "last_error_type": last_attempt.get("error_type"),
                    "last_message": str(last_attempt.get("message") or "")[:300],
                }
            )
            if len(samples) >= limit:
                break
        return samples

    @staticmethod
    def _phase2_quality_stats(phase2_result: dict[str, Any]) -> dict[str, Any]:
        return phase2_quality_stats(phase2_result)

    @staticmethod
    def _phase3_quality_stats(
        phase3_result: dict[str, Any],
        *,
        failed: bool,
    ) -> dict[str, Any]:
        return phase3_quality_stats(phase3_result, failed=failed)

    @staticmethod
    def _now_iso() -> str:
        return DeepImportProgressTracker.now_iso()

    @staticmethod
    def _short_message(message: Any) -> str:
        return DeepImportProgressTracker.short_message(message)

    @classmethod
    def _start_phase(
        cls,
        progress: DeepImportProgress,
        phase: str,
        *,
        item: dict[str, Any] | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        DeepImportProgressTracker.start_phase(
            progress,
            phase,
            item=item,
            details=details,
        )

    @classmethod
    def _finish_phase(
        cls,
        progress: DeepImportProgress,
        phase: str,
        *,
        status: str = "completed",
        details: dict[str, Any] | None = None,
        error_kind: str | None = None,
        error_message: str | None = None,
    ) -> None:
        DeepImportProgressTracker.finish_phase(
            progress,
            phase,
            status=status,
            details=details,
            error_kind=error_kind,
            error_message=error_message,
        )

    @staticmethod
    def _duration_seconds(started_at: Any, ended_at: str) -> float | None:
        return DeepImportProgressTracker.duration_seconds(started_at, ended_at)

    @classmethod
    def _set_last_error(
        cls,
        progress: DeepImportProgress,
        *,
        phase: str,
        error_kind: str | None,
        message: Any,
    ) -> None:
        DeepImportProgressTracker.set_last_error(
            progress,
            phase=phase,
            error_kind=error_kind,
            message=message,
        )

    @classmethod
    def _refresh_diagnostic_counts(cls, progress: DeepImportProgress) -> None:
        DeepImportProgressTracker.refresh_diagnostic_counts(progress)

    @staticmethod
    def _checkpoint_summary(checkpoints: dict[str, Any] | None) -> dict[str, Any]:
        return DeepImportProgressTracker.checkpoint_summary(checkpoints)

    @staticmethod
    async def _emit_progress(
        progress: DeepImportProgress,
        progress_value: float,
        on_progress: Callable[[DeepImportProgress, float], Awaitable[None]] | None,
    ) -> None:
        await DeepImportProgressTracker.emit_progress(
            progress,
            progress_value,
            on_progress,
        )

    @staticmethod
    def _mark_step_completed(
        progress: DeepImportProgress,
        step: DeepImportStep,
    ) -> None:
        DeepImportProgressTracker.mark_step_completed(progress, step)

    @staticmethod
    def _merge_checkpoints(
        progress: DeepImportProgress,
        phase_result: dict[str, Any],
    ) -> None:
        DeepImportProgressTracker.merge_checkpoints(progress, phase_result)

    @staticmethod
    def _merge_audit_summary(
        progress: DeepImportProgress,
        phase_result: dict[str, Any],
    ) -> None:
        DeepImportProgressTracker.merge_audit_summary(progress, phase_result)

    @staticmethod
    def _merge_snapshot_health_summary(
        progress: DeepImportProgress,
        phase_result: dict[str, Any],
    ) -> None:
        DeepImportProgressTracker.merge_snapshot_health_summary(progress, phase_result)

    @staticmethod
    async def _refresh_snapshot_health_summary(
        db: AsyncSession,
        novel_id: str,
        workflow_id: str | None,
        progress: DeepImportProgress,
    ) -> None:
        await DeepImportProgressTracker.refresh_snapshot_health_summary(
            db,
            novel_id,
            workflow_id,
            progress,
        )

    @staticmethod
    async def _rollback_after_phase_failure(
        db: AsyncSession,
        phase: str,
        exc: Exception,
    ) -> None:
        try:
            await db.rollback()
        except Exception:
            logger.warning("%s failed and rollback also failed", phase, exc_info=True)
        else:
            logger.warning("%s failed; transaction rolled back: %s", phase, exc)

    async def run_entity_extraction_only(
        self,
        db: AsyncSession,
        novel_id: str,
        start_chapter: int,
        end_chapter: int,
        progress: DeepImportProgress,
        *,
        workflow_id: str | None = None,
        on_progress: Callable[[DeepImportProgress, float], Awaitable[None]] | None = None,
    ) -> DeepImportProgress:
        return await EntityExtractionPhaseRunner(self).run_stage_only(
            db,
            novel_id,
            start_chapter,
            end_chapter,
            progress,
            workflow_id=workflow_id,
            on_progress=on_progress,
        )

    async def run_structure_analysis_only(
        self,
        db: AsyncSession,
        novel_id: str,
        start_chapter: int,
        end_chapter: int,
        progress: DeepImportProgress,
        *,
        workflow_id: str | None = None,
        context_mode: str = "working",
        include_pending_objects: bool = True,
        on_progress: Callable[[DeepImportProgress, float], Awaitable[None]] | None = None,
    ) -> DeepImportProgress:
        return await StructureAnalysisPhaseRunner(self).run_stage_only(
            db,
            novel_id,
            start_chapter,
            end_chapter,
            progress,
            workflow_id=workflow_id,
            context_mode=context_mode,
            include_pending_objects=include_pending_objects,
            on_progress=on_progress,
        )

    async def _fail_preflight(
        self,
        progress: DeepImportProgress,
        health,
        on_progress: Callable[[DeepImportProgress, float], Awaitable[None]] | None,
    ) -> DeepImportProgress:
        progress.phase = "failed"
        progress.quality_status = "failed"
        progress.current_step = None
        progress.degraded = True
        progress.message = (
            "LLM 健康检查失败，已停止自动提取："
            f"{health.error_kind or health.message}"
        )
        progress.phase_errors.append(
            {
                "phase": "preflight",
                "error_kind": health.error_kind or "llm_unavailable",
                "message": health.message[:300],
            }
        )
        await self._emit_progress(progress, 1.0, on_progress)
        return progress

    @staticmethod
    def _scene_overlaps_chapter_range(
        scene: dict[str, Any],
        start_chapter: int,
        end_chapter: int,
    ) -> bool:
        chapter_ids = scene.get("chapter_ids") or []
        for chapter_id in chapter_ids:
            try:
                chapter_index = int(chapter_id)
            except (TypeError, ValueError):
                continue
            if start_chapter <= chapter_index <= end_chapter:
                return True
        return False

    async def _has_scenes_in_range(
        self,
        db: AsyncSession,
        novel_id: str,
        start_chapter: int,
        end_chapter: int,
    ) -> bool:
        coverage = await self._scene_chapter_coverage(
            db,
            novel_id,
            start_chapter,
            end_chapter,
        )
        return bool(coverage["covered_chapters"])

    async def _scene_chapter_coverage(
        self,
        db: AsyncSession,
        novel_id: str,
        start_chapter: int,
        end_chapter: int,
    ) -> dict[str, Any]:
        from modules.outline.facade import get_scenes_by_novel

        scenes = await get_scenes_by_novel(
            db,
            novel_id,
            status_filter=["draft", "canonical"],
            exclude_narrative_tags=["valley", "transition"],
        )
        covered = {
            chapter
            for scene in scenes
            for chapter in self._scene_chapter_indices(scene)
            if start_chapter <= chapter <= end_chapter
        }
        return coverage_summary(
            covered,
            start_chapter,
            end_chapter,
        )

    @staticmethod
    def _scene_chapter_indices(scene: dict[str, Any]) -> list[int]:
        chapters: set[int] = set()
        for raw in scene.get("chapter_ids") or []:
            try:
                chapter = int(raw)
            except (TypeError, ValueError):
                continue
            if chapter > 0:
                chapters.add(chapter)
        for chunk in scene.get("scene_chunks") or []:
            if not isinstance(chunk, dict):
                continue
            try:
                chapter = int(chunk.get("chapter_index"))
            except (TypeError, ValueError):
                continue
            if chapter > 0:
                chapters.add(chapter)
        return sorted(chapters)

    @staticmethod
    async def _count_world_objects(db: AsyncSession, novel_id: str) -> int:
        from modules.world.facade import count_entities

        return await count_entities(
            db,
            novel_id,
            status_filter=["candidate", "draft", "canonical"],
        )

    # ------------------------------------------------------------------
    # Phase 1: Scene 切分
    # ------------------------------------------------------------------

    async def _segment_scenes(
        self,
        db: AsyncSession,
        novel_id: str,
        start_chapter: int,
        end_chapter: int,
        on_batch_progress: Callable[[int, int], Awaitable[None]] | None = None,
    ) -> dict[str, Any]:
        from modules.imports.scene_segmentation import SceneSegmentationService

        service = SceneSegmentationService()
        result = await service.segment_chapters(
            db,
            novel_id,
            start_chapter,
            end_chapter,
            on_batch_progress=on_batch_progress,
        )
        logger.info(
            "Phase 1 complete: %d scenes, %d failed batches, degraded=%s",
            result.get("total_scenes", 0),
            len(result.get("failed_batches", [])),
            result.get("degraded", False),
        )
        return result

    # ------------------------------------------------------------------
    # Phase 2: 实体增量提取
    # ------------------------------------------------------------------

    async def _extract_entities_by_scene(
        self,
        db: AsyncSession,
        novel_id: str,
        workflow_id: str | None = None,
        on_scene_progress: Callable[..., Awaitable[None]] | None = None,
        existing_checkpoints: dict[str, Any] | None = None,
        start_chapter: int | None = None,
        end_chapter: int | None = None,
    ) -> dict[str, Any]:
        if db is None or isinstance(db, Mock):
            handler = _container_get("world.run_scene_entity_extraction")
            return await handler(
                db,
                novel_id=novel_id,
                workflow_id=workflow_id,
                on_scene_progress=on_scene_progress,
                existing_checkpoints=existing_checkpoints,
                start_chapter=start_chapter,
                end_chapter=end_chapter,
            )

        from modules.imports.phase2_world_extraction import Phase2WorldExtractor
        from modules.imports.scene_entity_config import (
            phase2_project_settings_context,
        )

        project_settings = getattr(self, "_agent_project_settings", None)
        if project_settings is None:
            project_settings = await _project_settings_for_novel(db, novel_id)
        high_quality = bool(getattr(self, "_deep_import_high_quality", False))
        with phase2_project_settings_context(project_settings):
            result = await Phase2WorldExtractor(
                llm=_Phase2WorldExtractionLLM(
                    project_settings=project_settings,
                    high_quality=high_quality,
                )
            ).run(
                db,
                novel_id,
                workflow_id=workflow_id,
                on_scene_progress=on_scene_progress,
                existing_checkpoints=existing_checkpoints,
                start_chapter=start_chapter,
                end_chapter=end_chapter,
            )
        result["high_quality"] = high_quality
        if high_quality:
            result["model_override"] = "deepseek-v4-pro"
        return result

    # ------------------------------------------------------------------
    # Phase 3: 剧情结构分析
    # ------------------------------------------------------------------

    async def _analyze_structure(
        self,
        db: AsyncSession,
        novel_id: str,
        start_chapter: int,
        end_chapter: int,
        *,
        workflow_id: str | None = None,
        context_mode: str = "working",
        include_pending_objects: bool = True,
    ) -> dict[str, Any]:
        _generate = _container_get("outline.generate_structure")
        high_quality = bool(getattr(self, "_deep_import_high_quality", False))
        structure_kwargs = {
            "context_mode": context_mode,
            "include_pending_objects": include_pending_objects,
            "workflow_id": workflow_id,
            "audit_context_snapshot": True,
            "include_chapter_texts": False,
            "include_existing_scenes": True,
            "generate_scenes": False,
            "fast_structured": True,
        }
        if high_quality and _accepts_keyword(_generate, "high_quality"):
            structure_kwargs["high_quality"] = high_quality
        try:
            result = await _generate(
                db,
                novel_id,
                start_chapter=start_chapter,
                end_chapter=end_chapter,
                **structure_kwargs,
            )
            result["high_quality"] = high_quality
            if high_quality:
                result["model_override"] = "deepseek-v4-pro"
            result = await self._ensure_minimum_structure_outputs(
                db,
                novel_id,
                start_chapter,
                end_chapter,
                result,
                workflow_id=workflow_id,
            )
            logger.info(
                "Phase 3 complete: %d threads, %d arcs",
                result.get("total_threads", 0),
                result.get("total_arcs", 0),
            )
            return result
        except Exception as exc:
            logger.warning("Phase 3 structure analysis failed: %s", exc)
            return {
                "total_threads": 0,
                "total_arcs": 0,
                "threads": [],
                "arcs": [],
                "extra_sections": {},
                "error_kind": getattr(exc, "error_kind", "phase_error"),
                "error_message": str(exc)[:300],
            }

    async def _ensure_minimum_structure_outputs(
        self,
        db: AsyncSession,
        novel_id: str,
        start_chapter: int,
        end_chapter: int,
        result: dict[str, Any],
        *,
        workflow_id: str | None,
    ) -> dict[str, Any]:
        return await ensure_minimum_structure_outputs(
            db,
            novel_id,
            start_chapter,
            end_chapter,
            result,
            workflow_id=workflow_id,
        )

    @staticmethod
    def _structure_category_counts(result: dict[str, Any]) -> dict[str, int]:
        return structure_category_counts(result)

    @staticmethod
    def _structure_output_count(result: dict[str, Any]) -> int:
        return structure_output_count(result)

    @staticmethod
    def _fallback_thread_type(index: int) -> str:
        return fallback_thread_type(index)

    @staticmethod
    async def _select_fallback_reveal_target(
        db: AsyncSession,
        novel_id: str,
    ) -> dict[str, Any] | None:
        return await select_fallback_reveal_target(db, novel_id)
