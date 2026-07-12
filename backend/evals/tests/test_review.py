from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from evals.report import (
    build_dataset_report,
    build_result_version_reuse_proof,
    render_markdown_report,
)
from evals.review import (
    ReviewRecord,
    apply_review_records,
    export_review_csv,
    export_review_html,
    export_review_jsonl,
    human_review_quality,
    inter_reviewer_agreement,
    judge_human_agreement,
    load_review_records,
    select_balanced_review_supplement,
    select_double_review_cases,
    select_review_cases,
)
from evals.schemas import (
    DatasetCase,
    DatasetSplit,
    EvalResult,
    EvalSuite,
    HumanReview,
    MetricValue,
    QCDecision,
    RiskLevel,
    SystemUnderTestProfile,
)


def _case(
    case_id: str,
    suite: EvalSuite,
    *,
    scenario: str = "fixture",
    risk: RiskLevel = RiskLevel.normal,
) -> DatasetCase:
    return DatasetCase(
        case_id=case_id,
        suite=suite,
        scenario=scenario,
        risk_level=risk,
        source_group_id=f"group-{case_id}",
        input={"query": "<script>alert(1)</script>"},
        reference={"answer": "fixture"},
        split=DatasetSplit.test,
    )


def _result(
    case: DatasetCase,
    *,
    dataset_version: str = "v1",
    model: str = "fixture-model",
    case_result: dict | None = None,
    metric: MetricValue | None = None,
) -> EvalResult:
    started_at = datetime.now(UTC)
    return EvalResult(
        suite=case.suite,
        dataset_id="pilot",
        dataset_version=dataset_version,
        system_under_test=SystemUnderTestProfile(
            provider_id="fixture",
            model=model,
            profile_hash="a" * 64,
        ),
        metrics=[metric or MetricValue(name="fixture", value=1.0)],
        case_results=[case_result or {"case_id": case.case_id}],
        started_at=started_at,
        completed_at=started_at + timedelta(milliseconds=5),
    )


def test_review_selection_is_stratified_deterministic_and_includes_safety() -> None:
    cases = [
        _case(f"rag-{index:03d}", EvalSuite.rag, scenario=f"s-{index % 3}")
        for index in range(40)
    ]
    safety = _case(
        "world-safety",
        EvalSuite.world,
        risk=RiskLevel.safety_critical,
    )
    cases.append(safety)

    first = select_review_cases(cases, minimum_per_suite=30)
    second = select_review_cases(cases, minimum_per_suite=30)

    assert [case.case_id for case in first] == [case.case_id for case in second]
    assert safety in first
    assert sum(case.suite == EvalSuite.rag for case in first) == 30
    double_review = select_double_review_cases(first)
    assert len(double_review) == 8
    assert [case.case_id for case in double_review] == [
        case.case_id for case in select_double_review_cases(first)
    ]


def test_balanced_review_supplement_equalizes_suites_and_scenarios() -> None:
    cases = [
        _case(
            f"{suite.value}-{index:03d}",
            suite,
            scenario=f"scenario-{index % 2}",
        )
        for suite in EvalSuite
        for index in range(10)
    ]
    for suite in EvalSuite:
        reviewed = next(case for case in cases if case.suite == suite)
        reviewed.human_review = HumanReview(status="accepted")

    selected = select_balanced_review_supplement(cases, target=12)

    assert len(selected) == 12
    assert all(case.human_review.status == "unreviewed" for case in selected)
    for suite in EvalSuite:
        suite_cases = [case for case in selected if case.suite == suite]
        assert len(suite_cases) == 3
        scenario_counts = {
            scenario: sum(case.scenario == scenario for case in suite_cases)
            for scenario in {case.scenario for case in suite_cases}
        }
        assert max(scenario_counts.values()) - min(scenario_counts.values()) <= 1


def test_review_export_is_compact_and_html_escaped(tmp_path: Path) -> None:
    case = _case("rag-export", EvalSuite.rag)
    case.qc = QCDecision(
        status="review",
        judge_decisions=[{"decision": "review", "reason": "ambiguous"}],
    )
    jsonl_path = export_review_jsonl([case], tmp_path / "review.jsonl")
    csv_path = export_review_csv([case], tmp_path / "review.csv")
    html_path = export_review_html(
        [case],
        tmp_path / "review.html",
        source_excerpts={case.case_id: "source <excerpt>"},
    )

    payload = json.loads(jsonl_path.read_text(encoding="utf-8"))
    assert payload == {
        "case_id": "rag-export",
        "status": "unreviewed",
        "reason": None,
        "score": None,
        "corrected_reference": None,
    }
    csv_records = load_review_records(csv_path)
    assert csv_records == [ReviewRecord(case_id="rag-export")]
    html_text = html_path.read_text(encoding="utf-8")
    assert "&lt;script&gt;" in html_text
    assert "source &lt;excerpt&gt;" in html_text
    assert "ambiguous" in html_text
    assert "Download review JSONL" in html_text
    assert "class='status'" in html_text
    assert "corrected-reference" in html_text
    assert "application/x-ndjson" in html_text
    assert "innerHTML" not in html_text


def test_review_import_updates_cases_and_calculates_agreement(tmp_path: Path) -> None:
    cases = [
        _case("rag-a", EvalSuite.rag),
        _case("rag-b", EvalSuite.rag),
    ]
    cases[0].qc = QCDecision(
        status="accepted",
        judge_decisions=[{"decision": "accept", "rubric_score": 5}],
    )
    cases[1].qc = QCDecision(
        status="rejected",
        judge_decisions=[{"decision": "reject", "rubric_score": 1}],
    )
    records_path = tmp_path / "records.jsonl"
    records_path.write_text(
        "\n".join(
            [
                ReviewRecord(
                    case_id="rag-a",
                    status="edited",
                    reason="reference normalized",
                    score=5,
                    corrected_reference={"answer": "corrected"},
                ).model_dump_json(),
                ReviewRecord(
                    case_id="rag-b",
                    status="rejected",
                    reason="unsupported",
                    score=1,
                ).model_dump_json(),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    updated = apply_review_records(
        cases,
        load_review_records(records_path),
        reviewer_version="reviewer-a-v1",
    )
    updated = apply_review_records(
        updated,
        [
            ReviewRecord(
                case_id="rag-a",
                status="edited",
                reason="same normalized reference",
                score=5,
                corrected_reference={"answer": "corrected"},
            ),
            ReviewRecord(
                case_id="rag-b",
                status="rejected",
                reason="unsupported",
                score=1,
            ),
        ],
        reviewer_version="reviewer-b-v1",
    )
    agreement = judge_human_agreement(updated)

    assert updated[0].reference == {"answer": "corrected"}
    assert updated[0].human_review.original_reference == {"answer": "fixture"}
    assert len(updated[0].human_review.independent_reviews) == 2
    assert updated[0].human_review.reviewer_version == "consensus"
    assert agreement["cohens_kappa"] == pytest.approx(1.0)
    assert agreement["spearman_rho"] == pytest.approx(1.0)
    assert agreement["inter_reviewer"]["cohens_kappa"] == pytest.approx(1.0)
    assert agreement["llm_metrics_blocking"] is False
    assert agreement["inter_reviewer"]["raw_agreement"] == pytest.approx(1.0)
    assert agreement["inter_reviewer"]["gate_passed"] is False


def test_edited_review_requires_corrected_reference() -> None:
    with pytest.raises(ValueError, match="requires corrected_reference"):
        apply_review_records(
            [_case("rag-edit", EvalSuite.rag)],
            [ReviewRecord(case_id="rag-edit", status="edited")],
            reviewer_version="human-v1",
        )


def test_independent_review_disagreement_requires_adjudication() -> None:
    cases = [_case("rag-double", EvalSuite.rag)]
    first = apply_review_records(
        cases,
        [ReviewRecord(case_id="rag-double", status="accepted", score=5)],
        reviewer_version="reviewer-a",
    )
    second = apply_review_records(
        first,
        [ReviewRecord(case_id="rag-double", status="rejected", score=1)],
        reviewer_version="reviewer-b",
    )

    assert second[0].human_review.status == "ambiguous"
    assert second[0].human_review.adjudicated is False
    assert len(second[0].human_review.independent_reviews) == 2
    inter = inter_reviewer_agreement(second)
    assert inter["sample_count"] == 1
    assert inter["gate_passed"] is False

    adjudicated = apply_review_records(
        second,
        [
            ReviewRecord(
                case_id="rag-double",
                status="accepted",
                reason="evidence supports reference",
                score=5,
            )
        ],
        reviewer_version="adjudicator-v1",
        adjudication=True,
    )
    assert adjudicated[0].human_review.status == "accepted"
    assert adjudicated[0].human_review.adjudicated is True
    assert len(adjudicated[0].human_review.independent_reviews) == 2


def test_human_review_quality_uses_the_full_reviewed_sample() -> None:
    cases = [_case(f"rag-quality-{index:03d}", EvalSuite.rag) for index in range(100)]
    for index, case in enumerate(cases):
        case.human_review.status = "accepted" if index < 98 else "ambiguous"

    at_threshold = human_review_quality(cases)
    assert at_threshold["faithful_answerable_rate"] == pytest.approx(0.98)
    assert at_threshold["ambiguous_invalid_rate"] == pytest.approx(0.02)
    assert at_threshold["faithful_gate_passed"] is True
    assert at_threshold["invalid_gate_passed"] is True

    cases[97].human_review.status = "rejected"
    above_threshold = human_review_quality(cases)
    assert above_threshold["ambiguous_invalid_rate"] == pytest.approx(0.03)
    assert above_threshold["invalid_gate_passed"] is False


def test_versioned_report_includes_failures_and_metric_availability() -> None:
    case = _case("rag-report", EvalSuite.rag)
    case.qc = QCDecision(status="review")
    report = build_dataset_report(
        [case],
        dataset_id="pilot",
        dataset_version="v0",
        deterministic_qc={"errors": {"rag-report": ["fixture"]}},
    )
    markdown = render_markdown_report(report)

    assert report["failed_case_ids"] == ["rag-report"]
    assert report["metric_availability"] == {"available": 0, "unavailable": 0}
    assert "Semantic Eval Report: pilot" in markdown
    assert "`rag-report`" in markdown


def test_formal_report_validates_and_records_runner_provenance() -> None:
    cases = [_case(f"{suite.value}-formal", suite) for suite in EvalSuite]
    rag_case = next(case for case in cases if case.suite == EvalSuite.rag)
    rag_case.reference = {"no_answer": True}
    results = []
    for case in cases:
        case_result: dict = {"case_id": case.case_id}
        metric = MetricValue(name="fixture", value=1.0)
        if case.suite == EvalSuite.rag:
            case_result.update(
                {
                    "retrieved_ids": ["unexpected"],
                    "r_at_10": 0.0,
                    "visibility_leakage": 0,
                }
            )
            metric = MetricValue(
                name="no_answer_false_positive_rate",
                value=1.0,
                threshold=0.05,
                blocking=True,
                passed=False,
            )
        elif case.suite == EvalSuite.scene:
            case_result.update({"tp": 0, "fp": 1, "fn": 1})
        results.append(_result(case, case_result=case_result, metric=metric))
    sources = {
        result.suite.value: {
            "path": f"results/{result.suite.value}.json",
            "sha256": "abcd"[index] * 64,
        }
        for index, result in enumerate(results)
    }

    report = build_dataset_report(
        cases,
        dataset_id="pilot",
        dataset_version="v1",
        deterministic_qc={"errors": {"outline-formal": ["legacy-qc"]}},
        eval_results=results,
        result_sources=sources,
    )
    markdown = render_markdown_report(report)

    assert report["failed_case_source"] == "runner_system"
    assert report["failed_case_ids"] == ["rag-formal", "scene-formal"]
    assert report["dataset_qc_attention_case_ids"] == ["outline-formal"]
    assert report["error_taxonomy"]["case_failure_counts"] == {
        "boundary_mismatch": 1,
        "no_answer_false_positive": 1,
    }
    assert len(report["runner_results"]) == 4
    assert all(item["timing_status"] == "complete" for item in report["runner_results"])
    assert all(item["duration_ms"] == 5 for item in report["runner_results"])
    assert "Runner provenance" in markdown
    assert "System failed cases" in markdown


def test_formal_report_requires_complete_consistent_results() -> None:
    cases = [_case(f"{suite.value}-formal", suite) for suite in EvalSuite]
    results = [_result(case) for case in cases]

    with pytest.raises(ValueError, match="suites incomplete"):
        build_dataset_report(
            cases,
            dataset_id="pilot",
            dataset_version="v1",
            deterministic_qc={"errors": {}},
            eval_results=results[:-1],
        )

    with pytest.raises(ValueError, match="duplicate eval result suites"):
        build_dataset_report(
            cases,
            dataset_id="pilot",
            dataset_version="v1",
            deterministic_qc={"errors": {}},
            eval_results=[*results, results[0]],
        )

    mismatched_dataset = [
        results[0].model_copy(update={"dataset_id": "other"}),
        *results[1:],
    ]
    with pytest.raises(ValueError, match="dataset_id mismatch"):
        build_dataset_report(
            cases,
            dataset_id="pilot",
            dataset_version="v1",
            deterministic_qc={"errors": {}},
            eval_results=mismatched_dataset,
        )

    inconsistent = [*results[:-1], _result(cases[-1], model="other-model")]
    with pytest.raises(ValueError, match="inconsistent system-under-test"):
        build_dataset_report(
            cases,
            dataset_id="pilot",
            dataset_version="v1",
            deterministic_qc={"errors": {}},
            eval_results=inconsistent,
        )

    with pytest.raises(ValueError, match="result source metadata"):
        build_dataset_report(
            cases,
            dataset_id="pilot",
            dataset_version="v1",
            deterministic_qc={"errors": {}},
            eval_results=results,
        )


def test_result_version_reuse_requires_explicit_identical_suite_proof() -> None:
    cases = [_case(f"{suite.value}-reuse", suite) for suite in EvalSuite]
    results = [
        _result(case, dataset_version="v0" if case.suite == EvalSuite.rag else "v1")
        for case in cases
    ]

    with pytest.raises(ValueError, match="without a valid reuse proof"):
        build_dataset_report(
            cases,
            dataset_id="pilot",
            dataset_version="v1",
            deterministic_qc={"errors": {}},
            eval_results=results,
        )

    proof = build_result_version_reuse_proof(
        cases,
        [case.model_copy(deep=True) for case in cases],
        suite=EvalSuite.rag,
        source_dataset_version="v0",
        target_dataset_version="v1",
    )
    report = build_dataset_report(
        cases,
        dataset_id="pilot",
        dataset_version="v1",
        deterministic_qc={"errors": {}},
        eval_results=results,
        result_sources={
            result.suite.value: {
                "path": f"results/{result.suite.value}.json",
                "sha256": "a" * 64,
            }
            for result in results
        },
        version_reuse_proofs={"rag": proof},
    )
    rag_summary = next(
        item for item in report["runner_results"] if item["suite"] == "rag"
    )
    assert rag_summary["version_reuse_proof"] == proof

    changed = [case.model_copy(deep=True) for case in cases]
    changed[0].input = {"query": "changed"}
    with pytest.raises(ValueError, match="identical suite cases"):
        build_result_version_reuse_proof(
            cases,
            changed,
            suite=EvalSuite.rag,
            source_dataset_version="v0",
            target_dataset_version="v1",
        )


def test_report_can_attach_reviewed_raw_candidate_diagnostic() -> None:
    cases = [_case("rag-baseline", EvalSuite.rag)]
    raw_cases = [_case(f"rag-raw-{index:03d}", EvalSuite.rag) for index in range(205)]
    for index, case in enumerate(raw_cases):
        case.human_review.status = "accepted" if index < 200 else "rejected"

    report = build_dataset_report(
        cases,
        dataset_id="pilot",
        dataset_version="v1",
        deterministic_qc={"errors": {}},
        raw_candidate_cases=raw_cases,
        raw_candidate_source={"source_dataset_hash": "b" * 64},
    )

    diagnostic = report["raw_candidate_diagnostic"]
    assert diagnostic["reviewed_count"] == 205
    assert diagnostic["ambiguous_or_invalid_count"] == 5
    assert diagnostic["ambiguous_invalid_rate"] == pytest.approx(5 / 205)
    assert diagnostic["target_passed"] is False
    assert diagnostic["source_dataset_hash"] == "b" * 64
