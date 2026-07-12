"""World extraction/dedup evaluation from isolated-run outputs."""

from __future__ import annotations

import unicodedata
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from evals.schemas import DatasetCase, EvalResult, EvalSuite, MetricValue

SubmitStageFn = Callable[..., Awaitable[dict[str, Any]]]
RunStageFn = Callable[..., Awaitable[dict[str, Any]]]
LoadEntitiesFn = Callable[..., Awaitable[list[dict[str, Any]]]]
LoadSceneSpansFn = Callable[..., Awaitable[list[Any]]]

_SCENARIO_TARGET_KINDS = {
    "durable_entity": "entity",
    "alias": "alias",
    "relation": "relation",
    "ordinary_object_negative": "negative",
}
_MISSING = object()


async def run_world_workflow_cases(
    db: AsyncSession,
    novel_id: str,
    cases: list[DatasetCase],
    *,
    dataset_id: str,
    dataset_version: str,
    isolated_db: bool,
    submit_stage_fn: SubmitStageFn | None = None,
    run_stage_fn: RunStageFn | None = None,
    load_entities_fn: LoadEntitiesFn | None = None,
    load_scene_spans_fn: LoadSceneSpansFn | None = None,
) -> EvalResult:
    """Run the official deep-import World stage against an isolated database."""
    started_at = datetime.now(UTC)
    if not isolated_db:
        raise ValueError("World eval runner requires isolated_db=True")
    world_cases = [case for case in cases if case.suite == EvalSuite.world]
    chapter_indices = sorted(
        {ref.chapter_index for case in world_cases for ref in case.source_refs}
        | {
            int(value)
            for case in world_cases
            for value in case.reference.get("chapter_indices", [])
        }
    )
    if not chapter_indices:
        raise ValueError("World eval cases require reference chapter indices")
    if load_scene_spans_fn is None:
        from modules.outline.facade import get_scene_spans_by_chapter

        load_scene_spans_fn = get_scene_spans_by_chapter
    span_preflight = await _scene_span_coverage_preflight(
        db,
        novel_id,
        chapter_indices,
        load_scene_spans_fn=load_scene_spans_fn,
    )
    if not span_preflight["ready"]:
        return _world_preflight_unavailable_result(
            world_cases,
            dataset_id=dataset_id,
            dataset_version=dataset_version,
            chapter_indices=chapter_indices,
            preflight=span_preflight,
            started_at=started_at,
        )
    if submit_stage_fn is None or run_stage_fn is None:
        from modules.imports.facade import (
            run_submitted_deep_import_stage,
            start_deep_import_stage,
        )

        submit_stage_fn = submit_stage_fn or start_deep_import_stage
        run_stage_fn = run_stage_fn or run_submitted_deep_import_stage
    if load_entities_fn is None:
        from modules.world.facade import list_auto_ingested_entities

        load_entities_fn = list_auto_ingested_entities

    submission = await submit_stage_fn(
        db,
        novel_id,
        min(chapter_indices),
        max(chapter_indices),
        stage="world_objects",
        force=True,
        high_quality=False,
        authorization_confirmed=True,
    )
    task_id = submission.get("task_id")
    if not task_id or submission.get("requires_confirmation"):
        raise RuntimeError("World eval stage was not submitted")
    workflow_result = await run_stage_fn(
        db,
        str(task_id),
        stage="world_objects",
    )
    if workflow_result.get("phase") == "failed":
        return _failed_world_result(
            world_cases,
            dataset_id=dataset_id,
            dataset_version=dataset_version,
            task_id=str(task_id),
            chapter_indices=chapter_indices,
            workflow_result=workflow_result,
            started_at=started_at,
        )
    all_items = await load_entities_fn(
        db,
        novel_id,
        start_chapter=min(chapter_indices),
        end_chapter=max(chapter_indices),
        limit=10000,
        status_filter=["candidate", "draft", "canonical"],
    )
    items = [
        item
        for item in all_items
        if str((item.get("content_json") or {}).get("_meta", {}).get("workflow_id"))
        == str(task_id)
    ]
    explicit_predictions = dict(workflow_result.get("case_predictions") or {})
    failed_chapters = {int(value) for value in workflow_result.get("failed_chapters", [])}
    canonical_false_merge = bool(workflow_result.get("canonical_false_merge"))
    predictions: dict[str, dict[str, Any]] = {}
    for case in world_cases:
        if case.case_id in explicit_predictions:
            predictions[case.case_id] = dict(explicit_predictions[case.case_id])
            continue
        expected_entity = case.reference.get("entity")
        target_kind, _, scenario_shaped = _case_target(case)
        matched = _match_expected_entity(
            items,
            expected_entity,
            ignore_entity_type=scenario_shaped,
        )
        case_chapters = {ref.chapter_index for ref in case.source_refs}
        prediction: dict[str, Any] = {
            "expected_action": "create_new" if matched else "ignore",
            "canonical_false_merge": canonical_false_merge,
            "invalid_source_ref": bool(case_chapters & failed_chapters),
        }
        if target_kind == "alias":
            # A matching entity alone does not prove alias extraction.  The
            # persisted entity must carry alias evidence from this workflow.
            prediction["alias_target"] = (
                matched if matched and matched.get("aliases") else None
            )
        elif target_kind == "relation":
            # Relations live outside CoreEntity.  Unless the workflow returns
            # explicit per-case relation evidence, this loader cannot claim a
            # relation prediction.
            prediction["relation"] = None
        else:
            # Positive entity cases and ordinary-object negatives are both
            # evaluated from entity presence; their expected semantics differ.
            prediction["entity"] = matched
        predictions[case.case_id] = prediction
    result = evaluate_world_cases(
        world_cases,
        predictions,
        dataset_id=dataset_id,
        dataset_version=dataset_version,
        started_at=started_at,
    )
    result.run_context["workflow_batches"] = {
        "strategy": "deep_import_world_objects_stage",
        "workflow_id": str(task_id),
        "chapter_count": len(chapter_indices),
        "chapter_indices": chapter_indices,
        "range_from": min(chapter_indices),
        "range_to": max(chapter_indices),
        "quality_status": workflow_result.get("quality_status"),
        "degraded_reason": workflow_result.get("degraded_reason"),
    }
    result.run_context["scene_span_preflight"] = span_preflight
    return result.model_copy(update={"completed_at": datetime.now(UTC)})


async def _scene_span_coverage_preflight(
    db: AsyncSession,
    novel_id: str,
    chapter_indices: list[int],
    *,
    load_scene_spans_fn: LoadSceneSpansFn,
) -> dict[str, Any]:
    missing_chapters: list[int] = []
    missing_exact_chapters: list[int] = []
    exact_chapters: set[int] = set()
    unresolved_span_ids: set[str] = set()
    span_ids: set[str] = set()
    for chapter_index in chapter_indices:
        spans = await load_scene_spans_fn(
            db,
            novel_id,
            chapter_index,
            status_filter=["draft", "canonical"],
            content_mode="canonical",
        )
        if not spans:
            missing_chapters.append(chapter_index)
        chapter_has_exact_span = False
        for span in spans:
            span_id = str(getattr(span, "id", f"chapter-{chapter_index}:{id(span)}"))
            span_ids.add(span_id)
            span_is_exact = (
                str(getattr(span, "mapping_status", "chapter_only"))
                in {"exact", "reanchored"}
                and getattr(span, "start_offset", None) is not None
                and getattr(span, "end_offset", None) is not None
                and bool(getattr(span, "source_content_hash", None))
            )
            if span_is_exact:
                chapter_has_exact_span = True
            else:
                unresolved_span_ids.add(span_id)
        if spans and not chapter_has_exact_span:
            missing_exact_chapters.append(chapter_index)
        if chapter_has_exact_span:
            exact_chapters.add(chapter_index)
    return {
        "ready": not missing_chapters and not missing_exact_chapters,
        "chapter_from": min(chapter_indices),
        "chapter_to": max(chapter_indices),
        "chapter_count": len(chapter_indices),
        "exact_chapter_count": len(exact_chapters),
        "span_count": len(span_ids),
        "unresolved_span_count": len(unresolved_span_ids),
        "missing_chapters": missing_chapters,
        "missing_exact_chapters": missing_exact_chapters,
    }


def _world_preflight_unavailable_result(
    cases: list[DatasetCase],
    *,
    dataset_id: str,
    dataset_version: str,
    chapter_indices: list[int],
    preflight: dict[str, Any],
    started_at: datetime | None = None,
) -> EvalResult:
    result = _failed_world_result(
        cases,
        dataset_id=dataset_id,
        dataset_version=dataset_version,
        task_id="not-submitted",
        chapter_indices=chapter_indices,
        started_at=started_at,
        workflow_result={
            "phase": "not_started",
            "quality_status": "unavailable",
            "degraded_reason": "scene_span_coverage_incomplete",
            "completed_scenes": 0,
            "failed_scenes": (
                int(preflight["unresolved_span_count"])
                + len(preflight.get("missing_chapters", []))
                + len(preflight.get("missing_exact_chapters", []))
            ),
        },
    )
    result.run_context["scene_span_preflight"] = preflight
    result.errors = ["world_preflight_unavailable:scene_span_coverage_incomplete"]
    return result


def _failed_world_result(
    cases: list[DatasetCase],
    *,
    dataset_id: str,
    dataset_version: str,
    task_id: str,
    chapter_indices: list[int],
    workflow_result: dict[str, Any],
    started_at: datetime | None = None,
) -> EvalResult:
    """Persist a failed official workflow as unavailable evidence, never fake zeroes."""
    started_at = started_at or datetime.now(UTC)
    reason = str(workflow_result.get("degraded_reason") or "world_stage_failed")
    inventory = (
        ("entity_precision", 0.92, True),
        ("entity_recall", None, False),
        ("entity_prediction_coverage", None, False),
        ("alias_precision", 0.95, True),
        ("alias_recall", None, False),
        ("alias_prediction_coverage", None, False),
        ("relation_precision", 0.90, True),
        ("relation_recall", None, False),
        ("relation_prediction_coverage", None, False),
        ("canonical_false_merge_count", 0.0, True),
        ("invalid_source_ref_count", 0.0, True),
        ("ordinary_object_pollution_rate", 0.02, True),
        ("unresolved_endpoint_valid_relation_count", 0.0, True),
        ("source_quote_range_validity", 1.0, True),
        ("workflow_rollback_overreach_count", 0.0, True),
    )
    diagnostic_keys = (
        "phase",
        "quality_status",
        "degraded_reason",
        "bulk_error_kind",
        "completed_scenes",
        "failed_scenes",
        "phase2_batches_total",
        "attempts",
    )
    diagnostics = {
        key: workflow_result[key] for key in diagnostic_keys if key in workflow_result
    }
    return EvalResult(
        suite=EvalSuite.world,
        dataset_id=dataset_id,
        dataset_version=dataset_version,
        run_context={
            "workflow_batches": {
                "strategy": "deep_import_world_objects_stage",
                "workflow_id": task_id,
                "chapter_count": len(chapter_indices),
                "chapter_indices": chapter_indices,
                "range_from": min(chapter_indices),
                "range_to": max(chapter_indices),
                "status": "failed",
                "diagnostics": diagnostics,
            }
        },
        metrics=[
            MetricValue(
                name=name,
                value=None,
                available=False,
                blocking=blocking,
                threshold=threshold,
                passed=None,
                details={"reason": reason},
            )
            for name, threshold, blocking in inventory
        ],
        case_results=[
            {"case_id": case.case_id, "error": "world_stage_failed"} for case in cases
        ],
        errors=[f"world_stage_failed:{reason}"],
        started_at=started_at,
        completed_at=datetime.now(UTC),
    )


def _match_expected_entity(
    items: list[dict[str, Any]],
    expected: Any,
    *,
    ignore_entity_type: bool = False,
) -> dict[str, Any] | None:
    if not isinstance(expected, dict):
        return None
    expected_name = _normalize_text(expected.get("name"))
    expected_type = _normalize_text(expected.get("entity_type"))
    if not expected_name:
        return None
    for item in items:
        if _normalize_text(item.get("name")) != expected_name:
            continue
        item_type = _normalize_text(item.get("entity_type"))
        if not ignore_entity_type and expected_type and item_type != expected_type:
            continue
        return {
            "name": item.get("name"),
            "entity_type": item.get("entity_type"),
            "aliases": _entity_aliases(item),
        }
    return None


def _entity_aliases(item: Mapping[str, Any]) -> list[str]:
    aliases: list[str] = []
    content = item.get("content_json")
    raw_aliases = content.get("aliases", []) if isinstance(content, Mapping) else []
    if not isinstance(raw_aliases, list):
        return aliases
    for entry in raw_aliases:
        if isinstance(entry, Mapping):
            value = entry.get("alias") or entry.get("name")
        else:
            value = entry
        text = " ".join(str(value or "").split())
        if text:
            aliases.append(text)
    return aliases


def _case_target(case: DatasetCase) -> tuple[str | None, Any, bool]:
    """Return the metric target aligned with legacy and frozen references.

    Frozen Pilot cases use ``scenario`` to identify the World task and store the
    canonical target under ``reference.entity``.  Older fixtures may instead
    carry ``alias_target`` or ``relation`` directly.  The boolean indicates the
    scenario-shaped form, whose ``entity_type`` is a task label rather than a
    production CoreEntity type.
    """
    scenario_kind = _SCENARIO_TARGET_KINDS.get(case.scenario)
    if scenario_kind == "alias":
        expected = case.reference.get(
            "alias_target",
            case.reference.get("entity", _MISSING),
        )
        return "alias", expected, True
    if scenario_kind == "relation":
        expected = case.reference.get(
            "relation",
            case.reference.get("entity", _MISSING),
        )
        return "relation", expected, True
    if scenario_kind == "entity":
        return "entity", case.reference.get("entity", _MISSING), True
    if scenario_kind == "negative":
        return "negative", case.reference.get("entity", _MISSING), True
    if "alias_target" in case.reference:
        return "alias", case.reference["alias_target"], False
    if "relation" in case.reference:
        return "relation", case.reference["relation"], False
    if "entity" in case.reference:
        return "entity", case.reference["entity"], False
    return None, _MISSING, False


def _prediction_target(
    prediction: Mapping[str, Any],
    target_kind: str,
) -> tuple[Any, bool]:
    key = {
        "entity": "entity",
        "alias": "alias_target",
        "relation": "relation",
    }[target_kind]
    if key not in prediction:
        return _MISSING, False
    return prediction[key], prediction[key] is not None


def _targets_equal(expected: Any, predicted: Any, *, scenario_shaped: bool) -> bool:
    if isinstance(expected, Mapping) and isinstance(predicted, Mapping):
        if scenario_shaped:
            expected_name = _normalize_text(expected.get("name"))
            predicted_name = _normalize_text(predicted.get("name"))
            return bool(expected_name and expected_name == predicted_name)
        return all(
            key in predicted and _reference_value_equal(value, predicted[key])
            for key, value in expected.items()
        )
    if isinstance(expected, str) or isinstance(predicted, str):
        return _normalize_text(expected) == _normalize_text(predicted)
    return predicted == expected


def _reference_value_equal(expected: Any, predicted: Any) -> bool:
    if isinstance(expected, Mapping) and isinstance(predicted, Mapping):
        return all(
            key in predicted and _reference_value_equal(value, predicted[key])
            for key, value in expected.items()
        )
    if isinstance(expected, list) and isinstance(predicted, list):
        return len(expected) == len(predicted) and all(
            _reference_value_equal(left, right)
            for left, right in zip(expected, predicted, strict=True)
        )
    if isinstance(expected, str) or isinstance(predicted, str):
        return _normalize_text(expected) == _normalize_text(predicted)
    return expected == predicted


def _normalize_text(value: Any) -> str:
    return " ".join(unicodedata.normalize("NFKC", str(value or "")).split()).casefold()


def evaluate_world_cases(
    cases: list[DatasetCase],
    predictions: dict[str, dict[str, Any]],
    *,
    dataset_id: str,
    dataset_version: str,
    started_at: datetime | None = None,
) -> EvalResult:
    started_at = started_at or datetime.now(UTC)
    counts = {
        "entity_tp": 0,
        "entity_fp": 0,
        "entity_reference": 0,
        "entity_prediction": 0,
        "alias_tp": 0,
        "alias_fp": 0,
        "alias_reference": 0,
        "alias_prediction": 0,
        "relation_tp": 0,
        "relation_fp": 0,
        "relation_reference": 0,
        "relation_prediction": 0,
        "canonical_false_merge": 0,
        "invalid_source_ref": 0,
        "ordinary_negative": 0,
        "ordinary_negative_pollution": 0,
        "unresolved_endpoint_valid_relation": 0,
        "unresolved_endpoint_checks": 0,
        "source_quote_valid": 0,
        "source_quote_checks": 0,
        "rollback_overreach": 0,
        "rollback_checks": 0,
    }
    case_results: list[dict[str, Any]] = []
    for case in cases:
        if case.suite != EvalSuite.world:
            continue
        prediction = predictions.get(case.case_id, {})
        target_kind, expected_value, scenario_shaped = _case_target(case)
        result: dict[str, Any] = {
            "case_id": case.case_id,
            "target_kind": target_kind,
        }
        if target_kind in {"entity", "alias", "relation"}:
            expected_available = (
                expected_value is not _MISSING and expected_value is not None
            )
            result["reference_available"] = expected_available
            if expected_available:
                counts[f"{target_kind}_reference"] += 1
                predicted_value, predicted_available = _prediction_target(
                    prediction,
                    target_kind,
                )
                result["prediction_available"] = predicted_available
                correct = bool(
                    predicted_available
                    and _targets_equal(
                        expected_value,
                        predicted_value,
                        scenario_shaped=scenario_shaped,
                    )
                )
                result[f"{target_kind}_correct"] = correct
                if predicted_available:
                    counts[f"{target_kind}_prediction"] += 1
                    outcome = "tp" if correct else "fp"
                    counts[f"{target_kind}_{outcome}"] += 1
            else:
                result["prediction_available"] = False
                result["reference_error"] = "missing_world_target"
        counts["canonical_false_merge"] += int(
            bool(prediction.get("canonical_false_merge"))
        )
        counts["invalid_source_ref"] += int(bool(prediction.get("invalid_source_ref")))
        if target_kind == "negative":
            counts["ordinary_negative"] += 1
            polluted = prediction.get("entity") is not None
            counts["ordinary_negative_pollution"] += int(polluted)
            result["ordinary_object_pollution"] = polluted
        if "unresolved_endpoint_valid_relation" in prediction:
            counts["unresolved_endpoint_checks"] += 1
            counts["unresolved_endpoint_valid_relation"] += int(
                bool(prediction["unresolved_endpoint_valid_relation"])
            )
        if "source_quote_valid" in prediction:
            counts["source_quote_checks"] += 1
            counts["source_quote_valid"] += int(bool(prediction["source_quote_valid"]))
        if "rollback_overreach" in prediction:
            counts["rollback_checks"] += 1
            counts["rollback_overreach"] += int(bool(prediction["rollback_overreach"]))
        for evidence_key in (
            "canonical_false_merge",
            "invalid_source_ref",
            "unresolved_endpoint_valid_relation",
            "source_quote_valid",
            "rollback_overreach",
        ):
            if evidence_key in prediction:
                result[evidence_key] = prediction[evidence_key]
        case_results.append(result)

    target_metrics: list[MetricValue] = []
    for target_kind, threshold in (
        ("entity", 0.92),
        ("alias", 0.95),
        ("relation", 0.90),
    ):
        support = counts[f"{target_kind}_reference"]
        prediction_count = counts[f"{target_kind}_prediction"]
        tp = counts[f"{target_kind}_tp"]
        fp = counts[f"{target_kind}_fp"]
        details = {
            "definition": "case_target",
            "reference_count": support,
            "prediction_count": prediction_count,
            "true_positive_count": tp,
            "false_positive_count": fp,
            "false_negative_count": support - tp,
        }
        target_metrics.extend(
            [
                _optional_metric(
                    f"{target_kind}_precision",
                    _precision(tp, fp),
                    threshold,
                    greater=True,
                    reason=(
                        f"World output has no {target_kind} predictions"
                        if support
                        else f"World dataset has no {target_kind} references"
                    ),
                    details=details,
                ),
                _diagnostic_rate_metric(
                    f"{target_kind}_recall",
                    _ratio(tp, support),
                    reason=f"World dataset has no {target_kind} references",
                    details=details,
                ),
                _diagnostic_rate_metric(
                    f"{target_kind}_prediction_coverage",
                    _ratio(prediction_count, support),
                    reason=f"World dataset has no {target_kind} references",
                    details=details,
                ),
            ]
        )
    return EvalResult(
        suite=EvalSuite.world,
        dataset_id=dataset_id,
        dataset_version=dataset_version,
        metrics=[
            *target_metrics,
            _metric(
                "canonical_false_merge_count",
                float(counts["canonical_false_merge"]),
                0.0,
                greater=False,
            ),
            _metric(
                "invalid_source_ref_count",
                float(counts["invalid_source_ref"]),
                0.0,
                greater=False,
            ),
            _optional_metric(
                "ordinary_object_pollution_rate",
                (
                    counts["ordinary_negative_pollution"] / counts["ordinary_negative"]
                    if counts["ordinary_negative"]
                    else None
                ),
                0.02,
                greater=False,
                reason="World dataset has no ordinary-object negative cases",
            ),
            _optional_metric(
                "unresolved_endpoint_valid_relation_count",
                (
                    float(counts["unresolved_endpoint_valid_relation"])
                    if counts["unresolved_endpoint_checks"]
                    else None
                ),
                0.0,
                reason="World output lacks unresolved-endpoint evidence",
            ),
            _optional_metric(
                "source_quote_range_validity",
                (
                    counts["source_quote_valid"] / counts["source_quote_checks"]
                    if counts["source_quote_checks"]
                    else None
                ),
                1.0,
                greater=True,
                reason="World output lacks quote/range validity evidence",
            ),
            _optional_metric(
                "workflow_rollback_overreach_count",
                (
                    float(counts["rollback_overreach"])
                    if counts["rollback_checks"]
                    else None
                ),
                0.0,
                reason="World eval run did not execute rollback verification",
            ),
        ],
        case_results=case_results,
        started_at=started_at,
        completed_at=datetime.now(UTC),
    )


def _precision(tp: int, fp: int) -> float | None:
    return _ratio(tp, tp + fp)


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _metric(
    name: str,
    value: float,
    threshold: float,
    *,
    greater: bool = True,
    details: dict[str, Any] | None = None,
) -> MetricValue:
    return MetricValue(
        name=name,
        value=value,
        threshold=threshold,
        blocking=True,
        passed=value >= threshold if greater else value <= threshold,
        details=details or {},
    )


def _optional_metric(
    name: str,
    value: float | None,
    threshold: float,
    *,
    greater: bool = False,
    reason: str,
    details: dict[str, Any] | None = None,
) -> MetricValue:
    if value is None:
        unavailable_details = dict(details or {})
        unavailable_details["reason"] = reason
        return MetricValue(
            name=name,
            available=False,
            blocking=True,
            threshold=threshold,
            details=unavailable_details,
        )
    return _metric(name, value, threshold, greater=greater, details=details)


def _diagnostic_rate_metric(
    name: str,
    value: float | None,
    *,
    reason: str,
    details: dict[str, Any],
) -> MetricValue:
    if value is None:
        unavailable_details = dict(details)
        unavailable_details["reason"] = reason
        return MetricValue(
            name=name,
            available=False,
            blocking=False,
            details=unavailable_details,
        )
    return MetricValue(
        name=name,
        value=value,
        available=True,
        blocking=False,
        passed=None,
        details=details,
    )
