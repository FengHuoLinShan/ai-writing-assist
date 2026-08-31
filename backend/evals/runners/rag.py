"""RAG evaluation runner through the module's stable facade."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from evals.metrics import ndcg_at_k, precision_at_k, recall_at_k, reciprocal_rank
from evals.schemas import DatasetCase, EvalResult, EvalSuite, MetricValue
from modules.evidence.contracts import RagResultBundle

RetrieveFn = Callable[..., Awaitable[RagResultBundle]]


async def evaluate_rag_cases(
    db: AsyncSession,
    novel_id: str,
    cases: list[DatasetCase],
    *,
    dataset_id: str,
    dataset_version: str,
    retrieve_fn: RetrieveFn | None = None,
) -> EvalResult:
    started_at = datetime.now(UTC)
    if retrieve_fn is None:
        from modules.evidence.facade import retrieve as retrieve_fn

    case_results: list[dict[str, Any]] = []
    p5_values: list[float] = []
    r10_values: list[float] = []
    rr_values: list[float] = []
    ndcg_values: list[float] = []
    no_answer_false_positives = 0
    no_answer_count = 0
    leakage_count = 0
    stale_chunk_count = 0
    stale_marker_observations = 0
    source_hash_checks = 0
    source_hash_failures = 0
    scenario_values: dict[str, dict[str, list[float]]] = {}
    split_values: dict[str, list[dict[str, Any]]] = {}
    calibration_items: list[dict[str, Any]] = []

    for case in cases:
        if case.suite != EvalSuite.rag:
            continue
        query = str(case.input.get("query") or "")
        bundle = await retrieve_fn(
            db,
            novel_id,
            query,
            visibility=_retrieval_visibility(case),
            visible_until_chapter=case.visibility.visible_until_chapter,
            content_mode=str(case.input.get("content_mode") or "canonical"),
            mode=str(case.input.get("mode") or "search"),
            top_k=10,
        )
        relevant_ids = set(case.reference.get("context_ids") or [])
        logical_prefix = _logical_context_prefix(relevant_ids)
        retrieved_candidates = [
            {
                "context_id": _logical_chunk_id(chunk, logical_prefix),
                "score": float(chunk.score) if chunk.score is not None else None,
                "chapter_index": chunk.chapter_index,
            }
            for chunk in bundle.chunks
        ]
        retrieved_ids = _deduplicate(
            [item["context_id"] for item in retrieved_candidates]
        )
        no_answer = bool(case.reference.get("no_answer"))
        if no_answer:
            no_answer_count += 1
            no_answer_false_positives += bool(retrieved_ids)
        p5 = precision_at_k(retrieved_ids, relevant_ids, 5)
        r10 = recall_at_k(retrieved_ids, relevant_ids, 10)
        rr = reciprocal_rank(retrieved_ids, relevant_ids)
        ndcg = ndcg_at_k(retrieved_ids, relevant_ids, 10)
        ranking_eligible = not no_answer
        if ranking_eligible:
            p5_values.append(p5)
            r10_values.append(r10)
            rr_values.append(rr)
            ndcg_values.append(ndcg)
            values = scenario_values.setdefault(
                case.scenario,
                {"p_at_5": [], "r_at_10": [], "mrr": [], "ndcg_at_10": []},
            )
            values["p_at_5"].append(p5)
            values["r_at_10"].append(r10)
            values["mrr"].append(rr)
            values["ndcg_at_10"].append(ndcg)
        cutoff = case.visibility.visible_until_chapter
        case_leakage = sum(
            cutoff is not None and chunk.chapter_index > cutoff for chunk in bundle.chunks
        )
        leakage_count += case_leakage
        raw_context_hashes = case.reference.get("context_hashes") or {}
        context_hashes = (
            raw_context_hashes if isinstance(raw_context_hashes, dict) else {}
        )
        for chunk in bundle.chunks:
            meta = dict(getattr(chunk, "meta", {}) or {})
            if "stale" in meta:
                stale_marker_observations += 1
                stale_chunk_count += int(bool(meta["stale"]))
            logical_id = _logical_chunk_id(chunk, logical_prefix)
            expected_hash = context_hashes.get(logical_id)
            actual_hash = (
                meta.get("content_hash")
                or meta.get("source_hash")
                or getattr(chunk, "source_content_hash", None)
            )
            if expected_hash is not None and actual_hash is not None:
                source_hash_checks += 1
                source_hash_failures += int(str(expected_hash) != str(actual_hash))
        case_results.append(
            {
                "case_id": case.case_id,
                "scenario": case.scenario,
                "split": case.split.value,
                "retrieved_ids": retrieved_ids,
                "retrieved_candidates": retrieved_candidates,
                "result_count": len(retrieved_ids),
                "degraded": bundle.degraded,
                "p_at_5": p5,
                "r_at_10": r10,
                "reciprocal_rank": rr,
                "ndcg_at_10": ndcg,
                "ranking_eligible": ranking_eligible,
                "visibility_leakage": case_leakage,
                "warnings": bundle.warnings,
            }
        )
        split_values.setdefault(case.split.value, []).append(case_results[-1])
        calibration_items.append(
            {
                "split": case.split.value,
                "no_answer": no_answer,
                "relevant_ids": relevant_ids,
                "candidates": retrieved_candidates,
            }
        )

    ranking_details = {
        "aggregation_scope": "answerable_cases_only",
        "eligible_case_count": len(p5_values),
        "no_answer_case_count": no_answer_count,
    }
    metrics = [
        _metric(
            "p_at_5",
            _mean(p5_values),
            0.80,
            greater=True,
            details=ranking_details,
        ),
        _metric(
            "mrr",
            _mean(rr_values),
            0.85,
            greater=True,
            details=ranking_details,
        ),
        _metric(
            "r_at_10",
            _mean(r10_values),
            0.75,
            greater=True,
            details=ranking_details,
        ),
        _metric(
            "ndcg_at_10",
            _mean(ndcg_values),
            None,
            greater=True,
            details=ranking_details,
        ),
        _metric(
            "no_answer_false_positive_rate",
            no_answer_false_positives / no_answer_count if no_answer_count else 0.0,
            0.05,
            greater=False,
        ),
        _metric("visibility_leakage_count", float(leakage_count), 0.0, greater=False),
        _optional_metric(
            "source_hash_validity",
            (
                1.0 - source_hash_failures / source_hash_checks
                if source_hash_checks
                else None
            ),
            1.0,
            reason="dataset/context output lacks comparable logical context hashes",
        ),
        _optional_metric(
            "stale_chunk_evidence_count",
            float(stale_chunk_count) if stale_marker_observations else None,
            0.0,
            greater=False,
            reason="retrieval output does not expose stale-source markers",
        ),
        _unavailable_metric(
            "ragas_context_precision",
            0.85,
            "requires the calibrated LLM metric phase",
        ),
        _unavailable_metric(
            "ragas_context_recall",
            0.75,
            "requires the calibrated LLM metric phase",
        ),
        _unavailable_metric(
            "ragas_noise_sensitivity",
            0.10,
            "requires the calibrated LLM metric phase",
        ),
    ]
    for metric_name, threshold in (
        ("p_at_5", 0.80),
        ("mrr", 0.85),
        ("r_at_10", 0.75),
        ("ndcg_at_10", None),
    ):
        by_scenario = {
            scenario: _mean(values[metric_name])
            for scenario, values in sorted(scenario_values.items())
        }
        macro_value = _mean(list(by_scenario.values()))
        metrics.append(
            MetricValue(
                name=f"macro_scenario_{metric_name}",
                value=macro_value,
                blocking=False,
                threshold=threshold,
                passed=(macro_value >= threshold if threshold is not None else None),
                details={
                    "aggregation": "equal_weight_scenario_macro",
                    "scenario_values": by_scenario,
                    "scenario_count": len(by_scenario),
                },
            )
        )
    return EvalResult(
        suite=EvalSuite.rag,
        dataset_id=dataset_id,
        dataset_version=dataset_version,
        run_context={
            "selection_calibration": _calibrate_selection_thresholds(calibration_items),
            "split_summaries": {
                split: _split_summary(items)
                for split, items in sorted(split_values.items())
            },
        },
        metrics=metrics,
        case_results=case_results,
        started_at=started_at,
        completed_at=datetime.now(UTC),
    )


def _calibrate_selection_thresholds(items: list[dict[str, Any]]) -> dict[str, Any]:
    dev = [item for item in items if item["split"] == "dev"]
    answerable = [item for item in dev if not item["no_answer"]]
    no_answer = [item for item in dev if item["no_answer"]]
    if not answerable or not no_answer:
        return {
            "calibration_split": "dev",
            "available": False,
            "reason": "dev split requires answerable and no-answer cases",
            "selected": None,
        }

    absolute_thresholds = {0.0}
    relative_margins = {0.0}
    for item in dev:
        candidates = item["candidates"]
        scores = [
            float(candidate["score"])
            for candidate in candidates
            if candidate["score"] is not None
        ]
        absolute_thresholds.update(scores)
        if scores:
            relative_margins.update(max(0.0, scores[0] - score) for score in scores)

    feasible: list[dict[str, float]] = []
    tested = 0
    for absolute_threshold in sorted(absolute_thresholds):
        for relative_margin in sorted(relative_margins):
            tested += 1
            metrics = _selection_metrics(
                dev,
                absolute_threshold=absolute_threshold,
                relative_margin=relative_margin,
            )
            if (
                metrics["no_answer_false_positive_rate"] <= 0.05
                and metrics["r_at_10"] >= 0.75
            ):
                feasible.append(
                    {
                        "absolute_threshold": absolute_threshold,
                        "relative_margin": relative_margin,
                        **metrics,
                    }
                )

    selected = max(
        feasible,
        key=lambda item: (
            item["mrr"],
            item["p_at_5"],
            item["r_at_10"],
            -item["mean_result_count"],
            item["absolute_threshold"],
            -item["relative_margin"],
        ),
        default=None,
    )
    return {
        "calibration_split": "dev",
        "available": True,
        "constraints": {
            "no_answer_false_positive_rate_lte": 0.05,
            "r_at_10_gte": 0.75,
        },
        "tested_combination_count": tested,
        "feasible_combination_count": len(feasible),
        "selected": selected,
    }


def _selection_metrics(
    items: list[dict[str, Any]],
    *,
    absolute_threshold: float,
    relative_margin: float,
) -> dict[str, float]:
    p_at_5: list[float] = []
    r_at_10: list[float] = []
    reciprocal_ranks: list[float] = []
    false_positives: list[float] = []
    result_counts: list[float] = []
    for item in items:
        selected_ids = _select_candidate_ids(
            item["candidates"],
            absolute_threshold=absolute_threshold,
            relative_margin=relative_margin,
        )
        result_counts.append(float(len(selected_ids)))
        if item["no_answer"]:
            false_positives.append(float(bool(selected_ids)))
            continue
        relevant_ids = set(item["relevant_ids"])
        p_at_5.append(precision_at_k(selected_ids, relevant_ids, 5))
        r_at_10.append(recall_at_k(selected_ids, relevant_ids, 10))
        reciprocal_ranks.append(reciprocal_rank(selected_ids, relevant_ids))
    return {
        "p_at_5": _mean(p_at_5),
        "mrr": _mean(reciprocal_ranks),
        "r_at_10": _mean(r_at_10),
        "no_answer_false_positive_rate": _mean(false_positives),
        "mean_result_count": _mean(result_counts),
    }


def _select_candidate_ids(
    candidates: list[dict[str, Any]],
    *,
    absolute_threshold: float,
    relative_margin: float,
) -> list[str]:
    scores = [
        float(candidate["score"])
        for candidate in candidates
        if candidate["score"] is not None
    ]
    if not scores:
        return []
    floor = max(absolute_threshold, scores[0] - relative_margin)
    selected: list[str] = []
    for candidate in candidates:
        score = candidate["score"]
        context_id = str(candidate["context_id"])
        if score is None or float(score) < floor or context_id in selected:
            continue
        selected.append(context_id)
        if len(selected) == 8:
            break
    return selected


def _split_summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    answerable = [item for item in items if item["ranking_eligible"]]
    no_answer = [item for item in items if not item["ranking_eligible"]]
    return {
        "case_count": len(items),
        "answerable_count": len(answerable),
        "no_answer_count": len(no_answer),
        "p_at_5": _mean([float(item["p_at_5"]) for item in answerable]),
        "mrr": _mean([float(item["reciprocal_rank"]) for item in answerable]),
        "r_at_10": _mean([float(item["r_at_10"]) for item in answerable]),
        "no_answer_false_positive_rate": _mean(
            [float(bool(item["retrieved_ids"])) for item in no_answer]
        ),
        "mean_result_count": _mean([float(item["result_count"]) for item in items]),
        "degraded_rate": _mean([float(item["degraded"]) for item in items]),
    }


def _retrieval_visibility(case: DatasetCase) -> str | None:
    explicit = case.input.get("rag_visibility")
    if explicit is not None:
        return str(explicit)
    if case.visibility.mode in {"reader", "character"}:
        return "reader_known"
    return None


def _logical_context_prefix(relevant_ids: set[str]) -> str | None:
    prefixes = {
        value.rsplit(":chapter:", 1)[0] for value in relevant_ids if ":chapter:" in value
    }
    return next(iter(prefixes)) if len(prefixes) == 1 else None


def _logical_chunk_id(chunk: Any, logical_prefix: str | None = None) -> str:
    meta = dict(getattr(chunk, "meta", {}) or {})
    explicit = meta.get("logical_context_id")
    if explicit:
        return str(explicit)
    chapter_index = getattr(chunk, "chapter_index", None)
    if logical_prefix is not None and chapter_index is not None:
        return f"{logical_prefix}:chapter:{chapter_index}"
    return str(getattr(chunk, "id", ""))


def _deduplicate(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _metric(
    name: str,
    value: float,
    threshold: float | None,
    *,
    greater: bool,
    details: dict[str, Any] | None = None,
) -> MetricValue:
    passed = None
    if threshold is not None:
        passed = value >= threshold if greater else value <= threshold
    return MetricValue(
        name=name,
        value=value,
        threshold=threshold,
        blocking=threshold is not None,
        passed=passed,
        details=dict(details or {}),
    )


def _optional_metric(
    name: str,
    value: float | None,
    threshold: float,
    *,
    greater: bool = True,
    reason: str,
) -> MetricValue:
    if value is None:
        return _unavailable_metric(name, threshold, reason)
    return _metric(name, value, threshold, greater=greater)


def _unavailable_metric(
    name: str,
    threshold: float,
    reason: str,
) -> MetricValue:
    return MetricValue(
        name=name,
        available=False,
        blocking=True,
        threshold=threshold,
        details={"reason": reason},
    )
