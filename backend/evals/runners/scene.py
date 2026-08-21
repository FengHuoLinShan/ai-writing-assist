"""Scene boundary evaluation over official workflow output artifacts."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from evals.metrics import boundary_counts, precision_recall_f1
from evals.schemas import DatasetCase, EvalResult, EvalSuite, MetricValue

SubmitSceneStageFn = Callable[..., Awaitable[dict[str, Any]]]
RunSceneStageFn = Callable[..., Awaitable[dict[str, Any]]]
LoadSceneSpansFn = Callable[..., Awaitable[list[Any]]]
ListSourcesFn = Callable[..., Awaitable[list[Any]]]


async def run_scene_workflow_cases(
    db: AsyncSession,
    novel_id: str,
    cases: list[DatasetCase],
    *,
    dataset_id: str,
    dataset_version: str,
    isolated_db: bool,
    submit_stage_fn: SubmitSceneStageFn | None = None,
    run_stage_fn: RunSceneStageFn | None = None,
    load_spans_fn: LoadSceneSpansFn | None = None,
    list_sources_fn: ListSourcesFn | None = None,
) -> EvalResult:
    """Run the official Scene stage/commit path against an isolated database."""
    started_at = datetime.now(UTC)
    if not isolated_db:
        raise ValueError("Scene eval runner requires isolated_db=True")
    scene_cases = [case for case in cases if case.suite == EvalSuite.scene]
    coordinate_errors = _canonical_coordinate_errors(scene_cases)
    if coordinate_errors:
        return _unavailable_scene_result(
            dataset_id=dataset_id,
            dataset_version=dataset_version,
            reason=(
                "Scene gold lacks canonical chapter-local source ranges; "
                "input.text-relative offsets cannot be compared with SceneSpan offsets"
            ),
            case_errors=coordinate_errors,
            started_at=started_at,
        )
    downstream_cases = [
        case
        for case in cases
        if case.suite in {EvalSuite.scene, EvalSuite.world, EvalSuite.outline}
    ]
    chapter_indices = sorted(
        {index for case in downstream_cases for index in _case_chapter_indices(case)}
    )
    if not chapter_indices:
        raise ValueError("Scene eval cases require reference chapter indices")
    if submit_stage_fn is None or run_stage_fn is None:
        from modules.imports.facade import (
            run_submitted_deep_import_stage,
            start_deep_import_stage,
        )

        submit_stage_fn = submit_stage_fn or start_deep_import_stage
        run_stage_fn = run_stage_fn or run_submitted_deep_import_stage
    if load_spans_fn is None:
        from modules.story.facade import get_scene_spans_by_chapter

        load_spans_fn = get_scene_spans_by_chapter
    if list_sources_fn is None:
        from modules.writing.facade import list_manuscript_sources

        list_sources_fn = list_manuscript_sources

    submission = await submit_stage_fn(
        db,
        novel_id,
        min(chapter_indices),
        max(chapter_indices),
        stage="scenes",
        force=True,
        # Baseline boundary metrics exclude the optional Phase 1c fusion pass;
        # high-quality mode is covered by dedicated Phase 1c tests/evals.
        high_quality=False,
        authorization_confirmed=True,
    )
    task_id = submission.get("task_id")
    if not task_id or submission.get("requires_confirmation"):
        raise RuntimeError("Scene eval stage was not submitted")
    workflow_result = await run_stage_fn(db, str(task_id), stage="scenes")
    phase1a_stats = dict(
        (workflow_result.get("quality_stats") or {}).get("phase1a") or {}
    )
    semantic_fallback_chapters = {
        int(value) for value in phase1a_stats.get("fallback_chapter_indices", [])
    }

    spans_by_chapter = {
        chapter_index: await load_spans_fn(
            db,
            novel_id,
            chapter_index,
            status_filter=["draft", "canonical"],
            content_mode="canonical",
        )
        for chapter_index in chapter_indices
    }
    sources = await list_sources_fn(
        db,
        novel_id,
        chapter_indices,
        content_mode="canonical",
    )
    source_hash_by_chapter = {
        int(source.chapter_index): str(source.content_hash) for source in sources
    }
    predictions: dict[str, dict[str, Any]] = {}
    for case in scene_cases:
        spans = [
            span
            for chapter_index in _case_chapter_indices(case)
            for span in spans_by_chapter.get(chapter_index, [])
        ]
        hash_bound_spans = [
            span for span in spans if getattr(span, "source_content_hash", None)
        ]
        prediction = {
            "boundary_points": sorted(
                {
                    (int(getattr(span, "chapter_index")), int(offset))
                    for span in spans
                    for offset in (
                        getattr(span, "start_offset", None),
                        getattr(span, "end_offset", None),
                    )
                    if offset is not None
                }
            ),
            "boundary_offsets": sorted(
                {
                    int(span.start_offset)
                    for span in spans
                    if getattr(span, "start_offset", None) is not None
                }
            ),
            "chapter_indices": sorted(
                {int(getattr(span, "chapter_index")) for span in spans}
            ),
            "mapping_statuses": sorted(
                {str(getattr(span, "mapping_status", "chapter_only")) for span in spans}
            ),
            "fallback_required": any(
                str(getattr(span, "mapping_status", "chapter_only"))
                not in {"exact", "reanchored"}
                for span in spans
            )
            or bool(semantic_fallback_chapters.intersection(_case_chapter_indices(case))),
        }
        if hash_bound_spans:
            prediction["source_hash_valid"] = all(
                str(getattr(span, "source_content_hash"))
                == source_hash_by_chapter.get(int(getattr(span, "chapter_index")))
                for span in hash_bound_spans
            )
        predictions[case.case_id] = prediction
    result = evaluate_scene_cases(
        scene_cases,
        predictions,
        dataset_id=dataset_id,
        dataset_version=dataset_version,
        started_at=started_at,
    )
    result.run_context["workflow_range"] = {
        "strategy": "downstream_suite_reference_union",
        "chapter_from": min(chapter_indices),
        "chapter_to": max(chapter_indices),
        "chapter_count": len(chapter_indices),
    }
    result.run_context["scene_source_mapping"] = {
        key: phase1a_stats.get(key)
        for key in (
            "scene_count",
            "exact_scene_count",
            "unresolved_scene_count",
            "span_count",
            "exact_span_count",
            "unresolved_span_count",
            "exact_scene_rate",
            "length_retry_count",
            "structured_attempts",
            "fallback_count",
            "fallback_chapter_indices",
            "anchor_repair_attempted_count",
            "anchor_repair_succeeded_count",
            "anchor_repair_failed_count",
            "chapter_recovery_attempted_count",
            "chapter_recovery_succeeded_count",
            "chapter_recovery_failed_count",
        )
        if key in phase1a_stats
    }
    return result.model_copy(update={"completed_at": datetime.now(UTC)})


def _case_chapter_indices(case: DatasetCase) -> list[int]:
    indices = {ref.chapter_index for ref in case.source_refs}
    indices.update(int(value) for value in case.reference.get("chapter_indices", []))
    return sorted(indices)


def evaluate_scene_cases(
    cases: list[DatasetCase],
    predictions: dict[str, dict[str, Any]],
    *,
    dataset_id: str,
    dataset_version: str,
    started_at: datetime | None = None,
) -> EvalResult:
    started_at = started_at or datetime.now(UTC)
    tp = fp = fn = 0
    future_leakage = 0
    covered_chapters = 0
    expected_chapters = 0
    mapping_checks = 0
    mapping_mismatches = 0
    source_hash_checks = 0
    source_hash_failures = 0
    fallback_checks = 0
    fallback_count = 0
    coordinate_checks = 0
    case_results: list[dict[str, Any]] = []
    for case in cases:
        if case.suite != EvalSuite.scene:
            continue
        prediction = predictions.get(case.case_id, {})
        reference_points = _canonical_boundary_points(case)
        predicted_points = _coerce_boundary_points(prediction.get("boundary_points", []))
        if reference_points:
            coordinate_checks += 1
            case_tp, case_fp, case_fn = _boundary_point_counts(
                predicted_points,
                reference_points,
                tolerance=150,
            )
        else:
            predicted = [int(value) for value in prediction.get("boundary_offsets", [])]
            reference = [
                int(value) for value in case.reference.get("boundary_offsets", [])
            ]
            case_tp, case_fp, case_fn = boundary_counts(
                predicted,
                reference,
                tolerance=150,
            )
        tp += case_tp
        fp += case_fp
        fn += case_fn
        cutoff = case.visibility.visible_until_chapter
        case_leakage = sum(
            cutoff is not None and int(chapter) > cutoff
            for chapter in prediction.get("chapter_indices", [])
        )
        future_leakage += case_leakage
        expected_case_chapters = set(_case_chapter_indices(case))
        predicted_case_chapters = {
            int(chapter) for chapter in prediction.get("chapter_indices", [])
        }
        expected_chapters += len(expected_case_chapters)
        covered_chapters += len(expected_case_chapters & predicted_case_chapters)
        expected_mapping = case.reference.get("mapping_statuses")
        predicted_mapping = prediction.get("mapping_statuses")
        if isinstance(expected_mapping, list) and isinstance(predicted_mapping, list):
            mapping_checks += 1
            mapping_mismatches += int(set(expected_mapping) != set(predicted_mapping))
        if "source_hash_valid" in prediction:
            source_hash_checks += 1
            source_hash_failures += int(not bool(prediction["source_hash_valid"]))
        if "fallback_required" in prediction:
            fallback_checks += 1
            fallback_count += int(bool(prediction["fallback_required"]))
        case_results.append(
            {
                "case_id": case.case_id,
                "tp": case_tp,
                "fp": case_fp,
                "fn": case_fn,
                "future_leakage": case_leakage,
                "coordinate_system": (
                    "canonical_chapter_offset"
                    if reference_points
                    else "legacy_input_text_offset"
                ),
            }
        )
    precision, recall, f1 = precision_recall_f1(tp, fp, fn)
    return EvalResult(
        suite=EvalSuite.scene,
        dataset_id=dataset_id,
        dataset_version=dataset_version,
        metrics=[
            _metric("boundary_precision", precision, 0.90, greater=True),
            _metric("boundary_recall", recall, 0.85, greater=True),
            _metric("boundary_f1", f1, 0.87, greater=True),
            _metric("future_leakage_count", float(future_leakage), 0.0, greater=False),
            _optional_metric(
                "chapter_coverage",
                covered_chapters / expected_chapters if expected_chapters else None,
                1.0,
                greater=True,
                reason="Scene cases do not expose expected chapter coverage",
            ),
            _optional_metric(
                "wrong_mapping_attribution_count",
                float(mapping_mismatches) if mapping_checks else None,
                0.0,
                greater=False,
                reason="reference/prediction mapping statuses are not both available",
            ),
            _optional_metric(
                "source_hash_invalid_count",
                float(source_hash_failures) if source_hash_checks else None,
                0.0,
                greater=False,
                reason="Scene runner output lacks source-hash validity evidence",
            ),
            _optional_metric(
                "high_quality_fallback_rate",
                fallback_count / fallback_checks if fallback_checks else None,
                0.05,
                greater=False,
                reason="Scene runner output lacks per-case fallback evidence",
            ),
        ],
        case_results=case_results,
        started_at=started_at,
        completed_at=datetime.now(UTC),
        run_context={
            "boundary_coordinate_system": (
                "canonical_chapter_offset"
                if coordinate_checks
                else "legacy_input_text_offset"
            )
        },
    )


def _canonical_coordinate_errors(cases: list[DatasetCase]) -> dict[str, list[str]]:
    errors: dict[str, list[str]] = {}
    for case in cases:
        case_errors: list[str] = []
        if not case.source_refs:
            case_errors.append("source_refs_missing")
        for index, ref in enumerate(case.source_refs):
            if ref.start_offset is None or ref.end_offset is None:
                case_errors.append(f"source_ref_{index}_range_missing")
            if not ref.range_hash:
                case_errors.append(f"source_ref_{index}_range_hash_missing")
        if case_errors:
            errors[case.case_id] = case_errors
    return errors


def _canonical_boundary_points(case: DatasetCase) -> list[tuple[int, int]]:
    return sorted(
        {
            (ref.chapter_index, int(offset))
            for ref in case.source_refs
            for offset in (ref.start_offset, ref.end_offset)
            if offset is not None
        }
    )


def _coerce_boundary_points(value: Any) -> list[tuple[int, int]]:
    points: set[tuple[int, int]] = set()
    if not isinstance(value, list):
        return []
    for item in value:
        if isinstance(item, (list, tuple)) and len(item) == 2:
            points.add((int(item[0]), int(item[1])))
        elif isinstance(item, dict):
            points.add((int(item["chapter_index"]), int(item["offset"])))
    return sorted(points)


def _boundary_point_counts(
    predicted: list[tuple[int, int]],
    reference: list[tuple[int, int]],
    *,
    tolerance: int,
) -> tuple[int, int, int]:
    chapters = {chapter for chapter, _ in predicted + reference}
    tp = fp = fn = 0
    for chapter in chapters:
        case_tp, case_fp, case_fn = boundary_counts(
            [offset for point_chapter, offset in predicted if point_chapter == chapter],
            [offset for point_chapter, offset in reference if point_chapter == chapter],
            tolerance=tolerance,
        )
        tp += case_tp
        fp += case_fp
        fn += case_fn
    return tp, fp, fn


def _unavailable_scene_result(
    *,
    dataset_id: str,
    dataset_version: str,
    reason: str,
    case_errors: dict[str, list[str]],
    started_at: datetime | None = None,
) -> EvalResult:
    started_at = started_at or datetime.now(UTC)
    thresholds = {
        "boundary_precision": 0.90,
        "boundary_recall": 0.85,
        "boundary_f1": 0.87,
        "future_leakage_count": 0.0,
        "chapter_coverage": 1.0,
        "wrong_mapping_attribution_count": 0.0,
        "source_hash_invalid_count": 0.0,
        "high_quality_fallback_rate": 0.05,
    }
    return EvalResult(
        suite=EvalSuite.scene,
        dataset_id=dataset_id,
        dataset_version=dataset_version,
        run_context={
            "reference_coordinate_preflight": {
                "ready": False,
                "reason": reason,
                "invalid_case_count": len(case_errors),
                "invalid_case_ids": sorted(case_errors),
            }
        },
        metrics=[
            MetricValue(
                name=name,
                available=False,
                blocking=True,
                threshold=threshold,
                details={"reason": reason},
            )
            for name, threshold in thresholds.items()
        ],
        case_results=[
            {"case_id": case_id, "errors": errors}
            for case_id, errors in sorted(case_errors.items())
        ],
        errors=["scene_reference_coordinate_unavailable"],
        started_at=started_at,
        completed_at=datetime.now(UTC),
    )


def _metric(name: str, value: float, threshold: float, *, greater: bool) -> MetricValue:
    return MetricValue(
        name=name,
        value=value,
        threshold=threshold,
        blocking=True,
        passed=value >= threshold if greater else value <= threshold,
    )


def _optional_metric(
    name: str,
    value: float | None,
    threshold: float,
    *,
    greater: bool,
    reason: str,
) -> MetricValue:
    if value is None:
        return MetricValue(
            name=name,
            available=False,
            blocking=True,
            threshold=threshold,
            details={"reason": reason},
        )
    return _metric(name, value, threshold, greater=greater)
