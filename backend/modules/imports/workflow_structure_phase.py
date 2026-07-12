"""Structure analysis phases for deep import workflows."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from importlib import import_module
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.imports.deep_import_dedup import DeepImportDedupCoordinator
from modules.imports.service_phase_artifacts import add_phase_artifact
from modules.imports.workflow_phase_runner import (
    StructureFullPipelineRequest,
    StructureStageRequest,
)
from modules.imports.workflow_runtime import DeepImportWorkflowRuntime
from modules.imports.workflow_schemas import DeepImportProgress, DeepImportStep

PHASE3_STRUCTURE_TIMEOUT_SECONDS = 300
SMALL_SAMPLE_STRUCTURE_TARGET_COUNT = 4


def _small_sample_structure_target_count() -> int:
    workflow_module = import_module("modules.imports.workflow")
    return int(
        getattr(
            workflow_module,
            "SMALL_SAMPLE_STRUCTURE_TARGET_COUNT",
            SMALL_SAMPLE_STRUCTURE_TARGET_COUNT,
        )
    )


def minimum_structure_category_targets(chapter_count: int) -> dict[str, int]:
    from modules.outline.facade import get_deep_import_structure_category_targets

    return get_deep_import_structure_category_targets(
        chapter_count,
        small_sample_target_count=_small_sample_structure_target_count(),
    )


async def _review_structure_dedup(
    db: AsyncSession,
    novel_id: str,
    *,
    workflow_id: str | None,
) -> dict[str, Any]:
    if not isinstance(db, AsyncSession):
        return {
            "checked": 0,
            "suggestions_recorded": 0,
            "auto_applied": 0,
            "skipped_external_asset": 0,
            "current_workflow_asset_outcomes": {
                "review": 0,
                "not_adopted": 0,
                "affected": 0,
                "review_asset_ids": [],
                "not_adopted_asset_ids": [],
            },
            "degraded": 0,
            "skipped": True,
            "skip_reason": "non_async_session",
            "suggestions": [],
        }
    return await DeepImportDedupCoordinator().review_structure(
        db,
        novel_id,
        workflow_id=workflow_id,
    )


def structure_quality_gate(result: dict[str, Any]) -> dict[str, Any]:
    """Hard, rerunnable Phase 3 checks; soft quality remains diagnostic only."""
    threads = result.get("threads") or []
    arcs = result.get("arcs") or []
    reasons: list[str] = []
    total_threads = int(result.get("total_threads", 0) or 0)
    total_arcs = int(result.get("total_arcs", 0) or 0)
    if not threads and not arcs and total_threads <= 0 and total_arcs <= 0:
        reasons.append("empty_structure_output")
    if arcs and all(
        not item.get("start_chapter") or not item.get("end_chapter")
        for item in arcs
        if isinstance(item, dict)
    ):
        reasons.append("invalid_arc_chapter_range")
    assets = [item for item in [*threads, *arcs] if isinstance(item, dict)]
    if assets and all(
        not (item.get("related_entity_ids") or item.get("related_scene_ids"))
        for item in assets
    ):
        reasons.append("structure_references_missing")
    return {"ok": not reasons, "reasons": reasons}


async def rerun_structure_once_if_needed(
    workflow: DeepImportWorkflowRuntime,
    db: AsyncSession,
    novel_id: str,
    start_chapter: int,
    end_chapter: int,
    result: dict[str, Any],
    *,
    workflow_id: str | None,
    context_mode: str,
    include_pending_objects: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    gate = structure_quality_gate(result)
    if gate["ok"] or not workflow_id:
        return result, {"attempted": False, **gate}
    from modules.outline.facade import deprecate_deep_import_structure_assets_by_workflow

    await deprecate_deep_import_structure_assets_by_workflow(
        db,
        novel_id,
        workflow_id,
    )
    rerun = await workflow._analyze_structure(
        db,
        novel_id,
        start_chapter,
        end_chapter,
        workflow_id=workflow_id,
        context_mode=context_mode,
        include_pending_objects=include_pending_objects,
    )
    rerun["quality_rerun"] = {"attempt": 1, "reasons": gate["reasons"]}
    return rerun, {"attempted": True, **structure_quality_gate(rerun)}


class StructureAnalysisPhaseRunner:
    """Runs Phase 3 in full-pipeline and stage-only modes."""

    def __init__(self, workflow: DeepImportWorkflowRuntime) -> None:
        self.workflow = workflow

    async def run_full_pipeline_phase(
        self,
        db: AsyncSession,
        novel_id: str,
        start_chapter: int,
        end_chapter: int,
        progress: DeepImportProgress,
        *,
        workflow_id: str | None,
        context_mode: str,
        include_pending_objects: bool,
        total_scenes: int,
        on_progress: Callable[[DeepImportProgress, float], Awaitable[None]] | None,
    ) -> dict[str, Any]:
        return await self.run_full_pipeline(
            StructureFullPipelineRequest(
                db=db,
                novel_id=novel_id,
                start_chapter=start_chapter,
                end_chapter=end_chapter,
                progress=progress,
                workflow_id=workflow_id,
                on_progress=on_progress,
                total_scenes=total_scenes,
                context_mode=context_mode,
                include_pending_objects=include_pending_objects,
            )
        )

    async def run_full_pipeline(
        self,
        request: StructureFullPipelineRequest,
    ) -> dict[str, Any]:
        db = request.db
        novel_id = request.novel_id
        start_chapter = request.start_chapter
        end_chapter = request.end_chapter
        progress = request.progress
        workflow_id = request.workflow_id
        context_mode = request.context_mode
        include_pending_objects = request.include_pending_objects
        total_scenes = request.total_scenes
        on_progress = request.on_progress
        workflow = self.workflow
        progress.current_step = DeepImportStep.structure_analysis
        progress.current_phase = "structure_analysis"
        progress.current_operation = "structure_analysis"
        progress.message = "正在生成剧情线、篇章纲、伏笔和揭示计划..."
        workflow._start_phase(
            progress,
            "structure_analysis",
            item={
                "kind": "chapter_range",
                "start_chapter": start_chapter,
                "end_chapter": end_chapter,
            },
        )
        await workflow._emit_progress(progress, 0.8, on_progress)
        phase3_failed = False
        try:
            phase3_result = await asyncio.wait_for(
                workflow._analyze_structure(
                    db,
                    novel_id,
                    start_chapter,
                    end_chapter,
                    workflow_id=workflow_id,
                    context_mode=context_mode,
                    include_pending_objects=include_pending_objects,
                ),
                timeout=workflow._phase3_timeout_seconds(),
            )
        except TimeoutError as exc:
            phase3_failed = True
            await workflow._rollback_after_phase_failure(db, "structure_analysis", exc)
            phase3_result = _timeout_result()
            progress.degraded = True
            progress.phase_errors.append(
                {
                    "phase": DeepImportStep.structure_analysis.value,
                    "error_kind": "timeout",
                    "message": "剧情结构分析超时，已降级完成；可稍后重试结构分析。",
                }
            )
            progress.message = "剧情结构分析超时，已降级完成。"
        else:
            workflow._mark_step_completed(progress, DeepImportStep.structure_analysis)
            phase3_result, structure_gate = await rerun_structure_once_if_needed(
                workflow,
                db,
                novel_id,
                start_chapter,
                end_chapter,
                phase3_result,
                workflow_id=workflow_id,
                context_mode=context_mode,
                include_pending_objects=include_pending_objects,
            )
            phase3_result["structure_quality_gate"] = structure_gate
            workflow._merge_audit_summary(progress, phase3_result)
            workflow._merge_snapshot_health_summary(progress, phase3_result)
            phase3_result["structure_dedup"] = await _review_structure_dedup(
                db,
                novel_id,
                workflow_id=workflow_id or progress.workflow_id,
            )
        progress.quality_stats["phase3"] = phase3_quality_stats(
            phase3_result,
            failed=phase3_failed,
        )
        await workflow._refresh_snapshot_health_summary(
            db,
            novel_id,
            workflow_id or progress.workflow_id,
            progress,
        )
        if (
            total_scenes > 0
            and not phase3_failed
            and phase3_result.get("total_threads", 0) <= 0
            and phase3_result.get("total_arcs", 0) <= 0
        ):
            progress.degraded = True
            progress.quality_stats["phase3"]["error_kind"] = phase3_result.get(
                "error_kind",
                "empty_output",
            )
            progress.phase_errors.append(
                {
                    "phase": DeepImportStep.structure_analysis.value,
                    "error_kind": phase3_result.get("error_kind", "empty_output"),
                    "message": "剧情结构阶段未生成剧情线或篇章纲",
                }
            )
        workflow._finish_phase(
            progress,
            "structure_analysis",
            status="failed"
            if phase3_failed
            else (
                "degraded"
                if progress.quality_stats["phase3"]["error_kind"]
                else "completed"
            ),
            details=progress.quality_stats["phase3"],
            error_kind=progress.quality_stats["phase3"].get("error_kind"),
            error_message=phase3_result.get("error_message"),
        )
        add_phase_artifact(
            progress,
            "structure_analysis",
            start_chapter=start_chapter,
            end_chapter=end_chapter,
            status="failed"
            if phase3_failed
            else (
                "degraded"
                if progress.quality_stats["phase3"]["error_kind"]
                else "completed"
            ),
            quality_status="partial"
            if phase3_failed or progress.quality_stats["phase3"]["error_kind"]
            else "complete",
            quality_stats=progress.quality_stats["phase3"],
            counts=_phase3_counts(phase3_result),
            checkpoint_summary={"snapshot_health": progress.snapshot_health_summary},
            errors=[
                error
                for error in progress.phase_errors
                if error.get("phase") == DeepImportStep.structure_analysis.value
            ],
        )
        return phase3_result

    async def run_stage_only(
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
        return await self.run_stage(
            StructureStageRequest(
                db=db,
                novel_id=novel_id,
                start_chapter=start_chapter,
                end_chapter=end_chapter,
                progress=progress,
                workflow_id=workflow_id,
                on_progress=on_progress,
                context_mode=context_mode,
                include_pending_objects=include_pending_objects,
            )
        )

    async def run_stage(self, request: StructureStageRequest) -> DeepImportProgress:
        """Run Phase 3 against already committed Scenes and existing objects."""

        db = request.db
        novel_id = request.novel_id
        start_chapter = request.start_chapter
        end_chapter = request.end_chapter
        progress = request.progress
        workflow_id = request.workflow_id
        context_mode = request.context_mode
        include_pending_objects = request.include_pending_objects
        on_progress = request.on_progress
        workflow = self.workflow
        progress.phase = "running"
        progress.current_step = DeepImportStep.structure_analysis
        progress.current_phase = "structure_analysis"
        progress.current_operation = "structure_analysis"
        progress.message = "正在生成剧情线、篇章纲、伏笔和揭示计划..."
        workflow._start_phase(
            progress,
            "structure_analysis",
            item={
                "kind": "chapter_range",
                "start_chapter": start_chapter,
                "end_chapter": end_chapter,
            },
        )
        await workflow._emit_progress(progress, 0.05, on_progress)

        if workflow._is_llm_health_required():
            health = await workflow._check_llm_health(db, novel_id)
            progress.llm_health = health.model_dump()
            if not health.ok:
                return await workflow._fail_preflight(progress, health, on_progress)

        scene_coverage = await workflow._scene_chapter_coverage(
            db,
            novel_id,
            start_chapter,
            end_chapter,
        )
        if not scene_coverage["coverage_complete"]:
            progress.phase = "failed"
            progress.quality_status = "failed"
            progress.current_step = None
            progress.degraded = True
            progress.degraded_reason = (
                "missing_scene_prerequisite"
                if not scene_coverage["covered_chapters"]
                else "missing_scene_coverage"
            )
            missing = scene_coverage["missing_chapters"]
            progress.message = (
                "请先执行场景（scene）自动提取"
                if not scene_coverage["covered_chapters"]
                else f"场景（scene）覆盖不完整，缺少章节：{missing}"
            )
            progress.phase_errors.append(
                {
                    "phase": DeepImportStep.structure_analysis.value,
                    "error_kind": progress.degraded_reason,
                    "message": progress.message,
                }
            )
            workflow._finish_phase(
                progress,
                "structure_analysis",
                status="failed",
                error_kind=progress.degraded_reason,
                error_message=progress.message,
            )
            add_phase_artifact(
                progress,
                "structure_analysis",
                start_chapter=start_chapter,
                end_chapter=end_chapter,
                status="failed",
                quality_status="failed",
                quality_stats={},
                counts=_phase3_counts({}),
                coverage=scene_coverage,
                errors=[
                    error
                    for error in progress.phase_errors
                    if error.get("phase") == DeepImportStep.structure_analysis.value
                ],
            )
            await workflow._emit_progress(progress, 1.0, on_progress)
            return progress

        if await workflow._count_world_objects(db, novel_id) <= 0:
            progress.degraded = True
            progress.phase_errors.append(
                {
                    "phase": DeepImportStep.structure_analysis.value,
                    "error_kind": "missing_world_object_context",
                    "message": "世界对象为空，剧情线提取将以 Scene 上下文降级执行。",
                }
            )

        phase3_failed = False
        try:
            phase3_result = await asyncio.wait_for(
                workflow._analyze_structure(
                    db,
                    novel_id,
                    start_chapter,
                    end_chapter,
                    workflow_id=workflow_id,
                    context_mode=context_mode,
                    include_pending_objects=include_pending_objects,
                ),
                timeout=workflow._phase3_timeout_seconds(),
            )
        except TimeoutError as exc:
            phase3_failed = True
            await workflow._rollback_after_phase_failure(db, "structure_analysis", exc)
            phase3_result = _timeout_result()
            progress.degraded = True
            progress.phase_errors.append(
                {
                    "phase": DeepImportStep.structure_analysis.value,
                    "error_kind": "timeout",
                    "message": "剧情结构分析超时，已降级完成；可稍后重试结构分析。",
                }
            )
        else:
            workflow._mark_step_completed(progress, DeepImportStep.structure_analysis)
            phase3_result, structure_gate = await rerun_structure_once_if_needed(
                workflow,
                db,
                novel_id,
                start_chapter,
                end_chapter,
                phase3_result,
                workflow_id=workflow_id,
                context_mode=context_mode,
                include_pending_objects=include_pending_objects,
            )
            phase3_result["structure_quality_gate"] = structure_gate
            workflow._merge_audit_summary(progress, phase3_result)
            workflow._merge_snapshot_health_summary(progress, phase3_result)
            phase3_result["structure_dedup"] = await _review_structure_dedup(
                db,
                novel_id,
                workflow_id=workflow_id or progress.workflow_id,
            )

        progress.quality_stats["phase3"] = phase3_quality_stats(
            phase3_result,
            failed=phase3_failed,
        )
        await workflow._refresh_snapshot_health_summary(
            db,
            novel_id,
            workflow_id or progress.workflow_id,
            progress,
        )
        if (
            not phase3_failed
            and phase3_result.get("total_threads", 0) <= 0
            and phase3_result.get("total_arcs", 0) <= 0
        ):
            progress.degraded = True
            progress.phase_errors.append(
                {
                    "phase": DeepImportStep.structure_analysis.value,
                    "error_kind": phase3_result.get("error_kind", "empty_output"),
                    "message": "剧情结构阶段未生成剧情线或篇章纲",
                }
            )

        progress.current_step = None
        progress.phase = "done"
        progress.quality_status = "partial" if progress.degraded else "complete"
        progress.message = (
            "剧情线自动提取完成，共生成 "
            f"{phase3_result.get('total_threads', 0)} 条剧情线，"
            f"{phase3_result.get('total_arcs', 0)} 个篇章纲。"
        )
        workflow._finish_phase(
            progress,
            "structure_analysis",
            status="failed"
            if phase3_failed
            else ("degraded" if progress.degraded else "completed"),
            details=progress.quality_stats["phase3"],
            error_kind=progress.quality_stats["phase3"].get("error_kind"),
            error_message=phase3_result.get("error_message"),
        )
        add_phase_artifact(
            progress,
            "structure_analysis",
            start_chapter=start_chapter,
            end_chapter=end_chapter,
            status="failed"
            if phase3_failed
            else ("degraded" if progress.degraded else "completed"),
            quality_status=progress.quality_status,
            quality_stats=progress.quality_stats["phase3"],
            counts=_phase3_counts(phase3_result),
            checkpoint_summary={"snapshot_health": progress.snapshot_health_summary},
            errors=[
                error
                for error in progress.phase_errors
                if error.get("phase") == DeepImportStep.structure_analysis.value
            ],
        )
        await workflow._emit_progress(progress, 1.0, on_progress)
        return progress


def phase3_quality_stats(
    phase3_result: dict[str, Any],
    *,
    failed: bool,
) -> dict[str, Any]:
    extra_sections = phase3_result.get("extra_sections") or {}
    diagnostics = extra_sections.get("structure_diagnostics") or {}
    foreshadowing = phase3_result.get("total_foreshadowing")
    reveals = phase3_result.get("total_reveals")
    if foreshadowing is None:
        foreshadowing = len(extra_sections.get("foreshadowing_plans") or [])
    if reveals is None:
        reveals = len(extra_sections.get("reveal_plans") or [])
    review_asset_ids: set[str] = set()
    review_groups = (
        ("plot_thread", list(phase3_result.get("threads") or [])),
        ("outline_arc", list(phase3_result.get("arcs") or [])),
        (
            "foreshadowing_plan",
            list(extra_sections.get("foreshadowing_plans") or []),
        ),
        ("reveal_plan", list(extra_sections.get("reveal_plans") or [])),
    )
    for asset_type, items in review_groups:
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            provenance = item.get("provenance_meta")
            if not (
                item.get("needs_review")
                or (isinstance(provenance, dict) and provenance.get("needs_review"))
            ):
                continue
            asset_id = str(item.get("id") or "").strip()
            if not asset_id:
                asset_id = f"unresolved:{index}:{item.get('target_name') or ''}"
            review_asset_ids.add(f"{asset_type}:{asset_id}")
    return {
        "total_threads": int(phase3_result.get("total_threads", 0) or 0),
        "total_arcs": int(phase3_result.get("total_arcs", 0) or 0),
        "total_foreshadowing": int(foreshadowing or 0),
        "total_reveals": int(reveals or 0),
        "turning_point_count": len(extra_sections.get("turning_points") or []),
        "uncertain_count": len(extra_sections.get("uncertain_items") or []),
        "review_asset_count": len(review_asset_ids),
        "review_asset_ids": sorted(review_asset_ids),
        "parameter_version": diagnostics.get("parameter_version"),
        "input_mode": diagnostics.get("input_mode"),
        "prompt_level": diagnostics.get("prompt_level"),
        "invalid_scene_ref_count": int(
            diagnostics.get("invalid_scene_ref_count", 0) or 0
        ),
        "retry_count": int(diagnostics.get("retry_count", 0) or 0),
        "high_quality": bool(phase3_result.get("high_quality")),
        "model_override": phase3_result.get("model_override"),
        "structure_dedup": phase3_result.get("structure_dedup") or {},
        "structure_quality_gate": phase3_result.get("structure_quality_gate") or {},
        "quality_rerun": phase3_result.get("quality_rerun") or {},
        "failed": failed,
        "error_kind": phase3_result.get("error_kind"),
    }


def _phase3_counts(phase3_result: dict[str, Any]) -> dict[str, Any]:
    extra_sections = phase3_result.get("extra_sections") or {}
    return {
        "total_threads": int(phase3_result.get("total_threads", 0) or 0),
        "total_arcs": int(phase3_result.get("total_arcs", 0) or 0),
        "total_foreshadowing": int(
            phase3_result.get("total_foreshadowing")
            if phase3_result.get("total_foreshadowing") is not None
            else len(extra_sections.get("foreshadowing_plans") or [])
        ),
        "total_reveals": int(
            phase3_result.get("total_reveals")
            if phase3_result.get("total_reveals") is not None
            else len(extra_sections.get("reveal_plans") or [])
        ),
        "turning_point_count": len(extra_sections.get("turning_points") or []),
    }


async def ensure_minimum_structure_outputs(
    db: AsyncSession,
    novel_id: str,
    start_chapter: int,
    end_chapter: int,
    result: dict[str, Any],
    *,
    workflow_id: str | None,
) -> dict[str, Any]:
    from modules.outline.facade import ensure_deep_import_structure_outputs

    return await ensure_deep_import_structure_outputs(
        db,
        novel_id,
        start_chapter,
        end_chapter,
        result,
        workflow_id=workflow_id,
        service_resolver=_container_get,
        small_sample_target_count=_small_sample_structure_target_count(),
    )


def structure_category_counts(result: dict[str, Any]) -> dict[str, int]:
    from modules.outline.facade import get_deep_import_structure_category_counts

    return get_deep_import_structure_category_counts(result)


def structure_output_count(result: dict[str, Any]) -> int:
    from modules.outline.facade import get_deep_import_structure_output_count

    return get_deep_import_structure_output_count(result)


def fallback_thread_type(index: int) -> str:
    from modules.outline.facade import get_deep_import_fallback_thread_type

    return get_deep_import_fallback_thread_type(index)


async def select_fallback_reveal_target(
    db: AsyncSession,
    novel_id: str,
) -> dict[str, Any] | None:
    from modules.outline.facade import select_deep_import_fallback_reveal_target

    return await select_deep_import_fallback_reveal_target(
        db,
        novel_id,
        list_entities=_container_get("world.list_entities"),
    )


def _timeout_result() -> dict[str, Any]:
    return {
        "total_threads": 0,
        "total_arcs": 0,
        "total_foreshadowing": 0,
        "total_reveals": 0,
        "threads": [],
        "arcs": [],
        "foreshadowing_plans": [],
        "reveal_plans": [],
        "extra_sections": {},
        "error_kind": "timeout",
        "error_message": "剧情结构分析超时，已降级完成。",
    }


def _container_get(name: str):
    workflow_module = import_module("modules.imports.workflow")
    return workflow_module._container_get(name)
