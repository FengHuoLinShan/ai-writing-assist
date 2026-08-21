"""Outline preview/suggestion evaluation without applying assets."""

from __future__ import annotations

from collections import Counter
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from evals.schemas import DatasetCase, EvalResult, EvalSuite, MetricValue

PreviewFn = Callable[..., Awaitable[dict[str, Any]]]


async def run_outline_preview_cases(
    db: AsyncSession,
    novel_id: str,
    cases: list[DatasetCase],
    *,
    dataset_id: str,
    dataset_version: str,
    isolated_db: bool,
    preview_fn: PreviewFn | None = None,
) -> EvalResult:
    """Run the official suggestion-only seam; never apply generated assets."""
    started_at = datetime.now(UTC)
    if not isolated_db:
        raise ValueError("Outline eval runner requires isolated_db=True")
    outline_cases = [case for case in cases if case.suite == EvalSuite.outline]
    if preview_fn is None:
        from modules.story.facade import suggest_structure_dedup

        preview_fn = suggest_structure_dedup
    preview = await preview_fn(
        db,
        novel_id,
        limit=1000,
        max_suggestions=80,
    )
    explicit_predictions = dict(preview.get("case_predictions") or {})
    predictions: dict[str, dict[str, Any]] = {}
    for case in outline_cases:
        prediction = dict(explicit_predictions.get(case.case_id) or {})
        availability = {
            key: key in prediction or key in preview
            for key in (
                "source_refs_valid",
                "unsupported_fact",
                "false_merge",
                "hidden_knowledge_leak",
                "rubric_score",
            )
        }
        prediction.setdefault(
            "source_refs_valid",
            bool(preview.get("source_refs_valid", False)),
        )
        prediction.setdefault("unsupported_fact", bool(preview.get("unsupported_fact")))
        prediction.setdefault("false_merge", bool(preview.get("false_merge")))
        prediction.setdefault(
            "hidden_knowledge_leak",
            bool(preview.get("hidden_knowledge_leak")),
        )
        # This runner never imports or calls apply_structure_dedup.
        prediction["unconfirmed_asset_write"] = False
        if "rubric_score" not in prediction and preview.get("rubric_score") is not None:
            prediction["rubric_score"] = preview["rubric_score"]
        prediction["_availability"] = availability
        predictions[case.case_id] = prediction
    return evaluate_outline_cases(
        outline_cases,
        predictions,
        dataset_id=dataset_id,
        dataset_version=dataset_version,
        started_at=started_at,
    )


def evaluate_outline_cases(
    cases: list[DatasetCase],
    predictions: dict[str, dict[str, Any]],
    *,
    dataset_id: str,
    dataset_version: str,
    started_at: datetime | None = None,
) -> EvalResult:
    started_at = started_at or datetime.now(UTC)
    total = 0
    source_valid = unsupported = false_merge = hidden_leak = auto_write = 0
    rubric_scores: list[float] = []
    availability_counts: Counter[str] = Counter()
    case_results: list[dict[str, Any]] = []
    for case in cases:
        if case.suite != EvalSuite.outline:
            continue
        total += 1
        prediction = predictions.get(case.case_id, {})
        for key in (
            "source_refs_valid",
            "unsupported_fact",
            "false_merge",
            "hidden_knowledge_leak",
            "rubric_score",
        ):
            availability_counts[key] += int(_prediction_has_evidence(prediction, key))
        source_valid += int(bool(prediction.get("source_refs_valid", False)))
        unsupported += int(bool(prediction.get("unsupported_fact")))
        false_merge += int(bool(prediction.get("false_merge")))
        hidden_leak += int(bool(prediction.get("hidden_knowledge_leak")))
        auto_write += int(bool(prediction.get("unconfirmed_asset_write")))
        if prediction.get("rubric_score") is not None:
            rubric_scores.append(float(prediction["rubric_score"]))
        case_results.append({"case_id": case.case_id, **prediction})

    denominator = max(total, 1)
    metrics = [
        _optional_metric(
            "source_ref_validity",
            source_valid / denominator
            if availability_counts["source_refs_valid"] == total
            else None,
            1.0,
            greater=True,
            reason="Outline preview lacks source-reference validity evidence",
        ),
        _optional_metric(
            "unsupported_fact_rate",
            unsupported / denominator
            if availability_counts["unsupported_fact"] == total
            else None,
            0.02,
            greater=False,
            reason="Outline preview lacks unsupported-fact evidence",
        ),
        _optional_metric(
            "false_merge_count",
            float(false_merge) if availability_counts["false_merge"] == total else None,
            0.0,
            greater=False,
            reason="Outline preview lacks false-merge evidence",
        ),
        _optional_metric(
            "hidden_knowledge_leak_count",
            float(hidden_leak)
            if availability_counts["hidden_knowledge_leak"] == total
            else None,
            0.0,
            greater=False,
            reason="Outline preview lacks hidden-knowledge evidence",
        ),
        _metric("unconfirmed_asset_write_count", float(auto_write), 0.0, greater=False),
        _optional_metric(
            "rubric_average",
            (
                sum(rubric_scores) / len(rubric_scores)
                if availability_counts["rubric_score"] == total and rubric_scores
                else None
            ),
            4.0,
            greater=True,
            reason="Outline preview lacks calibrated rubric scores",
        ),
    ]
    return EvalResult(
        suite=EvalSuite.outline,
        dataset_id=dataset_id,
        dataset_version=dataset_version,
        metrics=metrics,
        case_results=case_results,
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


def _prediction_has_evidence(prediction: dict[str, Any], key: str) -> bool:
    availability = prediction.get("_availability")
    if isinstance(availability, dict):
        return bool(availability.get(key))
    return key in prediction
