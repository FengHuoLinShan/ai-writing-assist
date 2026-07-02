"""Structure analysis phases for deep import workflows."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from importlib import import_module
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

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


class StructureAnalysisPhaseRunner:
    """Runs Phase 3 in full-pipeline and stage-only modes."""

    def __init__(self, workflow: Any) -> None:
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
            workflow._merge_audit_summary(progress, phase3_result)
            workflow._merge_snapshot_health_summary(progress, phase3_result)
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
        """Run Phase 3 against already committed Scenes and existing objects."""

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

        if not await workflow._has_scenes_in_range(
            db,
            novel_id,
            start_chapter,
            end_chapter,
        ):
            progress.phase = "failed"
            progress.quality_status = "failed"
            progress.current_step = None
            progress.degraded = True
            progress.degraded_reason = "missing_scene_prerequisite"
            progress.message = "请先执行场景（scene）自动提取"
            progress.phase_errors.append(
                {
                    "phase": DeepImportStep.structure_analysis.value,
                    "error_kind": "missing_scene_prerequisite",
                    "message": progress.message,
                }
            )
            workflow._finish_phase(
                progress,
                "structure_analysis",
                status="failed",
                error_kind="missing_scene_prerequisite",
                error_message=progress.message,
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
            workflow._merge_audit_summary(progress, phase3_result)
            workflow._merge_snapshot_health_summary(progress, phase3_result)

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
        await workflow._emit_progress(progress, 1.0, on_progress)
        return progress


def phase3_quality_stats(
    phase3_result: dict[str, Any],
    *,
    failed: bool,
) -> dict[str, Any]:
    extra_sections = phase3_result.get("extra_sections") or {}
    foreshadowing = phase3_result.get("total_foreshadowing")
    reveals = phase3_result.get("total_reveals")
    if foreshadowing is None:
        foreshadowing = len(extra_sections.get("foreshadowing_plans") or [])
    if reveals is None:
        reveals = len(extra_sections.get("reveal_plans") or [])
    return {
        "total_threads": int(phase3_result.get("total_threads", 0) or 0),
        "total_arcs": int(phase3_result.get("total_arcs", 0) or 0),
        "total_foreshadowing": int(foreshadowing or 0),
        "total_reveals": int(reveals or 0),
        "failed": failed,
        "error_kind": phase3_result.get("error_kind"),
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
    chapter_count = end_chapter - start_chapter + 1
    if chapter_count > 7:
        return result

    counts = structure_category_counts(result)
    target_count = _small_sample_structure_target_count()
    if all(value >= target_count for value in counts.values()):
        return result

    created_assets: list[dict[str, Any]] = []
    try:
        from modules.outline.schemas import (
            ForeshadowingPlanCreate,
            OutlineArcCreate,
            PlotThreadCreate,
            RevealPlanCreate,
        )

        arc_service = _container_get("outline.arc_service")
        thread_service = _container_get("outline.thread_service")
        foreshadowing_service = _container_get("outline.foreshadowing_service")
        reveal_service = _container_get("outline.reveal_service")
        provenance_meta = {
            "source": "deep_import",
            "workflow_id": workflow_id,
            "auto_ingested": True,
            "needs_review": True,
            "phase": "structure_analysis",
            "fallback": "category_minimum_structure_outputs",
        }

        for index in range(
            counts["threads"] + 1,
            target_count + 1,
        ):
            created = await thread_service.create(
                db,
                novel_id,
                PlotThreadCreate(
                    name=f"第 {start_chapter}-{end_chapter} 章补强剧情线 {index}",
                    thread_type=fallback_thread_type(index),
                    summary="根据已导入 Scene 和世界对象补齐的待复核剧情线。",
                    visible_goal="把章节范围内的关键行动转化为可追踪结构资产。",
                    hidden_truth="该项由深度导入小样本结构保底生成，需要人工复核。",
                    start_chapter=start_chapter,
                    planned_payoff_chapter=end_chapter,
                    current_stage="draft",
                    provenance_meta=dict(provenance_meta),
                    status="draft",
                ),
            )
            thread_summary = {
                "id": str(created.id),
                "name": created.name,
                "thread_type": created.thread_type,
            }
            result.setdefault("threads", []).append(thread_summary)
            result["total_threads"] = int(result.get("total_threads", 0) or 0) + 1
            created_assets.append(
                {
                    "type": "plot_thread",
                    "id": thread_summary["id"],
                    "reason": "category_minimum_structure_outputs",
                }
            )

        for index in range(
            counts["arcs"] + 1,
            target_count + 1,
        ):
            created = await arc_service.create(
                db,
                novel_id,
                OutlineArcCreate(
                    title=f"第 {start_chapter}-{end_chapter} 章补强篇章纲 {index}",
                    arc_index=index,
                    start_chapter=start_chapter,
                    end_chapter=end_chapter,
                    arc_goal="把已生成 Scene 的阶段性推进整理为可复核篇章结构。",
                    core_conflict=(
                        "关键 Scene 已存在，但结构分析输出不足以覆盖所有转折。"
                    ),
                    entry_hook="从导入 Scene 中回收章节开端的触发事件。",
                    midpoint_turn="以章节中段的认知变化或关系变化作为转折锚点。",
                    climax="以章节范围内最强冲突或信息揭示作为高潮锚点。",
                    result="生成待复核篇章纲候选，供用户整理、合并或删除。",
                    next_hook="用后续章节校验该篇章纲是否应保留。",
                    provenance_meta=dict(provenance_meta),
                    status="draft",
                ),
            )
            arc_summary = {
                "id": str(created.id),
                "title": created.title,
                "arc_index": created.arc_index,
            }
            result.setdefault("arcs", []).append(arc_summary)
            result["total_arcs"] = int(result.get("total_arcs", 0) or 0) + 1
            created_assets.append(
                {
                    "type": "outline_arc",
                    "id": arc_summary["id"],
                    "reason": "category_minimum_structure_outputs",
                }
            )

        extra_sections = result.setdefault("extra_sections", {})
        foreshadowing_items = extra_sections.setdefault("foreshadowing_plans", [])
        for index in range(
            counts["foreshadowing"] + 1,
            target_count + 1,
        ):
            created = await foreshadowing_service.create(
                db,
                novel_id,
                ForeshadowingPlanCreate(
                    name=f"第 {start_chapter}-{end_chapter} 章补强伏笔 {index}",
                    summary="根据已导入 Scene 补齐的待复核伏笔计划。",
                    surface_meaning="章节内已经出现但尚未整理为结构资产的线索。",
                    hidden_meaning="该线索可能指向后续身份、组织或非凡规则揭示。",
                    planned_seed_chapter=start_chapter,
                    planned_payoff_chapter=end_chapter,
                    provenance_meta=dict(provenance_meta),
                    status="draft",
                ),
            )
            item = {"id": str(created.id), "name": created.name}
            foreshadowing_items.append(item)
            created_assets.append(
                {
                    "type": "foreshadowing_plan",
                    "id": item["id"],
                    "reason": "category_minimum_structure_outputs",
                }
            )

        reveal_items = extra_sections.setdefault("reveal_plans", [])
        reveal_target = await select_fallback_reveal_target(db, novel_id)
        if (
            reveal_target is None
            and counts["reveals"] < target_count
        ):
            result.setdefault("warnings", []).append(
                "小样本揭示计划不足，但没有可关联世界对象，无法补强 reveal。"
            )
        elif reveal_target is not None:
            for index in range(
                counts["reveals"] + 1,
                target_count + 1,
            ):
                created = await reveal_service.create(
                    db,
                    novel_id,
                    RevealPlanCreate(
                        target_type="world_entity",
                        target_id=reveal_target["id"],
                        secret_summary=(
                            f"{reveal_target['name']} 在第 "
                            f"{start_chapter}-{end_chapter} 章范围内存在待复核"
                            "的信息层级或隐藏背景。"
                        ),
                        reveal_stages=[
                            {
                                "stage_index": 0,
                                "chapter_index": start_chapter,
                                "reveal_content": "读者获得初步表层线索。",
                                "trigger": "Scene 导入后的结构补强。",
                                "effect": "形成后续人工整理的揭示计划草稿。",
                            }
                        ],
                        provenance_meta=dict(provenance_meta),
                        status="draft",
                    ),
                )
                item = {
                    "id": str(created.id),
                    "target_name": reveal_target["name"],
                }
                reveal_items.append(item)
                created_assets.append(
                    {
                        "type": "reveal_plan",
                        "id": item["id"],
                        "reason": "category_minimum_structure_outputs",
                    }
                )
    except Exception as exc:
        warnings = result.setdefault("warnings", [])
        warnings.append(f"category_minimum_structure_outputs fallback failed: {exc}")
        return result

    if created_assets:
        extra_sections = result.setdefault("extra_sections", {})
        extra_sections.setdefault("fallback_structure_assets", []).extend(
            created_assets
        )
        result.setdefault("warnings", []).append(
            "小样本结构类别输出不足，已补充待复核结构候选。"
        )
    return result


def structure_category_counts(result: dict[str, Any]) -> dict[str, int]:
    extra_sections = result.get("extra_sections") or {}
    return {
        "threads": int(result.get("total_threads", 0) or 0),
        "arcs": int(result.get("total_arcs", 0) or 0),
        "foreshadowing": len(extra_sections.get("foreshadowing_plans") or []),
        "reveals": len(extra_sections.get("reveal_plans") or []),
    }


def structure_output_count(result: dict[str, Any]) -> int:
    return sum(structure_category_counts(result).values())


def fallback_thread_type(index: int) -> str:
    types = ["main", "secondary", "hidden", "foreshadowing"]
    return types[(index - 1) % len(types)]


async def select_fallback_reveal_target(
    db: AsyncSession,
    novel_id: str,
) -> dict[str, Any] | None:
    entities = await _container_get("world.list_entities")(
        db,
        novel_id,
        limit=20,
    )
    for entity in entities:
        entity_id = entity.get("id")
        name = entity.get("name")
        if entity_id and name:
            return {"id": entity_id, "name": name}
    return None


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
