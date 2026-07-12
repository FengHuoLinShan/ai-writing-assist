"""Versioned JSON and Markdown reports for semantic evaluation datasets."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from evals.review import (
    human_review_quality,
    judge_human_agreement,
    reviewed_raw_candidate_diagnostic,
)
from evals.schemas import DatasetCase, EvalResult, EvalSuite


def build_result_version_reuse_proof(
    current_cases: list[DatasetCase],
    source_cases: list[DatasetCase],
    *,
    suite: EvalSuite,
    source_dataset_version: str,
    target_dataset_version: str,
    source_dataset_path: Path | None = None,
) -> dict[str, Any]:
    """Prove that one suite is byte-semantically unchanged across dataset versions."""

    current_hash, current_count = _suite_case_hash(current_cases, suite)
    source_hash, source_count = _suite_case_hash(source_cases, suite)
    if source_hash != current_hash or source_count != current_count:
        raise ValueError(
            "result version reuse requires identical suite cases: "
            f"suite={suite.value} source_count={source_count} "
            f"target_count={current_count}"
        )
    proof: dict[str, Any] = {
        "suite": suite.value,
        "source_dataset_version": source_dataset_version,
        "target_dataset_version": target_dataset_version,
        "case_count": current_count,
        "suite_case_hash": current_hash,
    }
    if source_dataset_path is not None:
        proof["source_dataset_path"] = str(source_dataset_path)
        proof["source_dataset_hash"] = hashlib.sha256(
            source_dataset_path.read_bytes()
        ).hexdigest()
    return proof


def build_dataset_report(
    cases: list[DatasetCase],
    *,
    dataset_id: str,
    dataset_version: str,
    deterministic_qc: dict[str, Any],
    eval_results: list[EvalResult] | None = None,
    result_sources: dict[str, dict[str, str]] | None = None,
    version_reuse_proofs: dict[str, dict[str, Any]] | None = None,
    raw_candidate_cases: list[DatasetCase] | None = None,
    raw_candidate_source: dict[str, str] | None = None,
) -> dict[str, Any]:
    results = eval_results or []
    sources = result_sources or {}
    reuse_proofs = version_reuse_proofs or {}
    runner_results = _validate_and_summarize_results(
        cases,
        results,
        dataset_id=dataset_id,
        dataset_version=dataset_version,
        result_sources=sources,
        version_reuse_proofs=reuse_proofs,
    )
    qc_status_counts = Counter(case.qc.status for case in cases)
    human_status_counts = Counter(case.human_review.status for case in cases)
    stratum_counts = Counter((case.suite.value, case.scenario) for case in cases)
    metrics = [
        {
            "suite": result.suite.value,
            **metric.model_dump(mode="json"),
        }
        for result in results
        for metric in result.metrics
    ]
    dataset_attention_ids = sorted(
        {
            *deterministic_qc.get("errors", {}).keys(),
            *(case.case_id for case in cases if case.qc.status in {"rejected", "review"}),
        }
    )
    system_failures = _system_failure_report(cases, results)
    failed_case_ids = (
        system_failures["failed_case_ids"] if results else dataset_attention_ids
    )
    raw_diagnostic = None
    if raw_candidate_cases is not None:
        raw_diagnostic = reviewed_raw_candidate_diagnostic(raw_candidate_cases)
        if raw_candidate_source:
            raw_diagnostic.update(raw_candidate_source)
    return {
        "dataset_id": dataset_id,
        "dataset_version": dataset_version,
        "case_count": len(cases),
        "suite_counts": dict(Counter(case.suite.value for case in cases)),
        "scenario_counts": dict(Counter(case.scenario for case in cases)),
        "suite_scenario_strata": {
            f"{suite}:{scenario}": count
            for (suite, scenario), count in sorted(stratum_counts.items())
        },
        "regularized_aggregation": {
            "method": "equal_weight_suite_scenario_macro",
            "stratum_count": len(stratum_counts),
            "weight_per_stratum": 1 / len(stratum_counts) if stratum_counts else None,
            "minimum_stratum_size": min(stratum_counts.values()) if stratum_counts else 0,
            "maximum_stratum_size": max(stratum_counts.values()) if stratum_counts else 0,
            "micro_case_count": len(cases),
        },
        "split_counts": dict(Counter(case.split.value for case in cases)),
        "qc_status_counts": dict(qc_status_counts),
        "human_status_counts": dict(human_status_counts),
        "deterministic_qc": deterministic_qc,
        "judge_human_agreement": judge_human_agreement(cases),
        "human_review_quality": human_review_quality(cases),
        "raw_candidate_diagnostic": raw_diagnostic,
        "runner_results": runner_results,
        "metrics": metrics,
        "metric_availability": {
            "available": sum(metric["available"] for metric in metrics),
            "unavailable": sum(not metric["available"] for metric in metrics),
        },
        "failed_case_source": "runner_system" if results else "dataset_qc",
        "failed_case_ids": failed_case_ids,
        "system_case_failures": system_failures["case_failures"],
        "error_taxonomy": system_failures["error_taxonomy"],
        "dataset_qc_attention_case_ids": dataset_attention_ids,
        "runner_errors": [
            {"suite": result.suite.value, "errors": result.errors}
            for result in results
            if result.errors
        ],
    }


def render_markdown_report(report: dict[str, Any]) -> str:
    lines = [
        f"# Semantic Eval Report: {report['dataset_id']}",
        "",
        f"- Version: `{report['dataset_version']}`",
        f"- Cases: {report['case_count']}",
        f"- Suites: `{report['suite_counts']}`",
        f"- Splits: `{report['split_counts']}`",
        f"- QC status: `{report['qc_status_counts']}`",
        f"- Human status: `{report['human_status_counts']}`",
        f"- Regularized aggregation: `{report['regularized_aggregation']}`",
        "",
        "## Calibration",
        "",
        f"- `{report['judge_human_agreement']}`",
        f"- Human review quality: `{report['human_review_quality']}`",
    ]
    if report.get("raw_candidate_diagnostic") is not None:
        lines.extend(
            [
                "",
                "## Raw candidate diagnostic",
                "",
                f"- `{report['raw_candidate_diagnostic']}`",
            ]
        )
    if report.get("runner_results"):
        lines.extend(
            [
                "",
                "## Runner provenance",
                "",
                "| Suite | Dataset version | Artifact SHA-256 | Model | Timing | "
                "Duration ms |",
                "|---|---|---|---|---|---:|",
            ]
        )
        for result in report["runner_results"]:
            profile = result.get("system_under_test") or {}
            lines.append(
                "| {suite} | {dataset_version} | {artifact_sha256} | {model} | "
                "{timing_status} | {duration_ms} |".format(
                    suite=result["suite"],
                    dataset_version=result["dataset_version"],
                    artifact_sha256=result.get("artifact_sha256") or "-",
                    model=profile.get("model") or "-",
                    timing_status=result["timing_status"],
                    duration_ms=result["duration_ms"],
                )
            )
    lines.extend(
        [
            "",
            "## Metrics",
            "",
            "| Suite | Metric | Value | Threshold | Available | Blocking | Passed |",
            "|---|---|---:|---:|---|---|---|",
        ]
    )
    for metric in report["metrics"]:
        lines.append(
            "| {suite} | {name} | {value} | {threshold} | {available} | "
            "{blocking} | {passed} |".format(**metric)
        )
    if not report["metrics"]:
        lines.append("| - | No runner results supplied | - | - | - | - | - |")
    lines.extend(["", "## Error taxonomy", ""])
    taxonomy = report.get("error_taxonomy") or {}
    case_counts = taxonomy.get("case_failure_counts") or {}
    for reason, count in sorted(case_counts.items()):
        lines.append(f"- `{reason}`: {count} case(s)")
    for metric in taxonomy.get("metric_failures") or []:
        lines.append(f"- `{metric['suite']}:{metric['metric']}`: {metric['status']}")
    for runner_error in taxonomy.get("runner_errors") or []:
        lines.append(f"- `{runner_error['suite']}`: `{runner_error['error']}`")
    if (
        not case_counts
        and not taxonomy.get("metric_failures")
        and not taxonomy.get("runner_errors")
    ):
        lines.append("- None")
    heading = (
        "## System failed cases"
        if report.get("failed_case_source") == "runner_system"
        else "## Dataset QC attention cases"
    )
    lines.extend(
        [
            "",
            heading,
            "",
            *[f"- `{case_id}`" for case_id in report["failed_case_ids"]],
        ]
    )
    if not report["failed_case_ids"]:
        lines.append("- None")
    if (
        report.get("dataset_qc_attention_case_ids")
        and report.get("failed_case_source") == "runner_system"
    ):
        lines.extend(["", "## Dataset QC attention cases", ""])
        lines.extend(
            f"- `{case_id}`" for case_id in report["dataset_qc_attention_case_ids"]
        )
    return "\n".join(lines) + "\n"


def _validate_and_summarize_results(
    cases: list[DatasetCase],
    results: list[EvalResult],
    *,
    dataset_id: str,
    dataset_version: str,
    result_sources: dict[str, dict[str, str]],
    version_reuse_proofs: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    if not results:
        if result_sources or version_reuse_proofs:
            raise ValueError("result metadata was supplied without eval results")
        return []
    suites = [result.suite for result in results]
    duplicates = sorted(
        suite.value for suite, count in Counter(suites).items() if count > 1
    )
    if duplicates:
        raise ValueError(f"duplicate eval result suites: {duplicates}")
    missing = sorted(suite.value for suite in set(EvalSuite) - set(suites))
    extra = sorted(suite.value for suite in set(suites) - set(EvalSuite))
    if missing or extra:
        raise ValueError(
            f"eval result suites incomplete: missing={missing} extra={extra}"
        )
    profile_identities: set[str] = set()
    summaries: list[dict[str, Any]] = []
    for result in sorted(results, key=lambda item: item.suite.value):
        suite = result.suite
        if result.dataset_id != dataset_id:
            raise ValueError(
                f"eval result dataset_id mismatch: suite={suite.value} "
                f"expected={dataset_id} actual={result.dataset_id}"
            )
        reuse_proof = None
        if result.dataset_version != dataset_version:
            reuse_proof = version_reuse_proofs.get(suite.value)
            expected_hash, expected_count = _suite_case_hash(cases, suite)
            if (
                reuse_proof is None
                or reuse_proof.get("suite") != suite.value
                or reuse_proof.get("source_dataset_version") != result.dataset_version
                or reuse_proof.get("target_dataset_version") != dataset_version
                or reuse_proof.get("suite_case_hash") != expected_hash
                or reuse_proof.get("case_count") != expected_count
            ):
                raise ValueError(
                    "eval result dataset_version mismatch without a valid reuse proof: "
                    f"suite={suite.value} expected={dataset_version} "
                    f"actual={result.dataset_version}"
                )
        elif suite.value in version_reuse_proofs:
            raise ValueError(
                f"unnecessary result version reuse proof for suite {suite.value}"
            )

        expected_ids = {case.case_id for case in cases if case.suite == suite}
        actual_ids = [str(item.get("case_id") or "") for item in result.case_results]
        if len(actual_ids) != len(set(actual_ids)) or set(actual_ids) != expected_ids:
            raise ValueError(
                f"eval result case IDs mismatch: suite={suite.value} "
                f"expected={len(expected_ids)} actual={len(set(actual_ids))}"
            )
        if result.system_under_test is None:
            raise ValueError(f"eval result lacks system profile: suite={suite.value}")
        profile = result.system_under_test.model_dump(mode="json")
        profile_identities.add(json.dumps(profile, sort_keys=True))
        timing_status = "complete"
        duration_ms: int | None = None
        if result.completed_at is None:
            timing_status = "incomplete"
        elif result.completed_at < result.started_at:
            timing_status = "invalid_completed_before_started"
        else:
            duration_ms = round(
                (result.completed_at - result.started_at).total_seconds() * 1000
            )
        source = result_sources.get(suite.value, {})
        summaries.append(
            {
                "suite": suite.value,
                "dataset_id": result.dataset_id,
                "dataset_version": result.dataset_version,
                "case_count": len(result.case_results),
                "artifact_path": source.get("path"),
                "artifact_sha256": source.get("sha256"),
                "system_under_test": profile,
                "started_at": result.started_at.isoformat(),
                "completed_at": (
                    result.completed_at.isoformat() if result.completed_at else None
                ),
                "timing_status": timing_status,
                "duration_ms": duration_ms,
                "run_context": result.run_context,
                "errors": result.errors,
                "version_reuse_proof": reuse_proof,
            }
        )
    if len(profile_identities) != 1:
        raise ValueError("eval results use inconsistent system-under-test profiles")
    expected_source_suites = {suite.value for suite in suites}
    if set(result_sources) != expected_source_suites:
        raise ValueError("result source metadata must cover every suite exactly once")
    for suite, source in result_sources.items():
        digest = str(source.get("sha256") or "")
        if (
            not source.get("path")
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise ValueError(f"invalid result source provenance for suite {suite}")
    return summaries


def _suite_case_hash(
    cases: list[DatasetCase],
    suite: EvalSuite,
) -> tuple[str, int]:
    payloads = [
        case.model_dump(mode="json")
        for case in sorted(cases, key=lambda item: item.case_id)
        if case.suite == suite
    ]
    encoded = json.dumps(
        payloads,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest(), len(payloads)


def _system_failure_report(
    cases: list[DatasetCase],
    results: list[EvalResult],
) -> dict[str, Any]:
    case_by_id = {case.case_id: case for case in cases}
    failures: dict[str, set[str]] = defaultdict(set)
    metric_failures: list[dict[str, Any]] = []
    runner_errors: list[dict[str, str]] = []
    for result in results:
        for error in result.errors:
            runner_errors.append({"suite": result.suite.value, "error": error})
        for metric in result.metrics:
            if not metric.available:
                metric_failures.append(
                    {
                        "suite": result.suite.value,
                        "metric": metric.name,
                        "status": "unavailable",
                        "reason": metric.details.get("reason")
                        or metric.details.get("error"),
                    }
                )
            elif metric.blocking and metric.passed is False:
                metric_failures.append(
                    {
                        "suite": result.suite.value,
                        "metric": metric.name,
                        "status": "threshold_failed",
                        "value": metric.value,
                        "threshold": metric.threshold,
                    }
                )
        for case_result in result.case_results:
            case_id = str(case_result.get("case_id") or "")
            case = case_by_id.get(case_id)
            for reason in _case_failure_reasons(result.suite, case, case_result):
                failures[case_id].add(reason)
    case_failures = {
        case_id: sorted(reasons) for case_id, reasons in sorted(failures.items())
    }
    reason_counts = Counter(
        reason for reasons in case_failures.values() for reason in reasons
    )
    return {
        "failed_case_ids": sorted(case_failures),
        "case_failures": case_failures,
        "error_taxonomy": {
            "case_failure_counts": dict(sorted(reason_counts.items())),
            "metric_failures": metric_failures,
            "runner_errors": runner_errors,
        },
    }


def _case_failure_reasons(
    suite: EvalSuite,
    case: DatasetCase | None,
    result: dict[str, Any],
) -> list[str]:
    explicit = result.get("failure_reasons")
    if isinstance(explicit, list):
        return [str(value) for value in explicit if value]
    errors = result.get("errors")
    if isinstance(errors, list) and errors:
        return [str(value) for value in errors]
    if result.get("error"):
        return [str(result["error"])]
    reasons: list[str] = []
    if suite == EvalSuite.rag:
        no_answer = bool(case and case.reference.get("no_answer"))
        retrieved = list(result.get("retrieved_ids") or [])
        if no_answer and retrieved:
            reasons.append("no_answer_false_positive")
        if not no_answer and float(result.get("r_at_10") or 0.0) < 1.0:
            reasons.append("reference_context_not_fully_retrieved")
        if int(result.get("visibility_leakage") or 0) > 0:
            reasons.append("visibility_leakage")
    elif suite == EvalSuite.scene:
        if int(result.get("fp") or 0) > 0 or int(result.get("fn") or 0) > 0:
            reasons.append("boundary_mismatch")
        if int(result.get("future_leakage") or 0) > 0:
            reasons.append("future_scene_leakage")
    elif suite == EvalSuite.world:
        for key in ("entity_correct", "alias_correct", "relation_correct"):
            if result.get(key) is False:
                reasons.append(key.replace("_correct", "_mismatch"))
        for key in (
            "canonical_false_merge",
            "invalid_source_ref",
            "unresolved_endpoint_valid_relation",
            "rollback_overreach",
        ):
            if result.get(key):
                reasons.append(key)
    elif suite == EvalSuite.outline:
        availability = dict(result.get("_availability") or {})
        if availability.get("source_refs_valid") and not result.get("source_refs_valid"):
            reasons.append("invalid_source_ref")
        for key in (
            "unsupported_fact",
            "false_merge",
            "hidden_knowledge_leak",
            "unconfirmed_asset_write",
        ):
            if result.get(key):
                reasons.append(key)
        if (
            availability.get("rubric_score")
            and float(result.get("rubric_score") or 0) < 4
        ):
            reasons.append("rubric_below_threshold")
    return reasons
