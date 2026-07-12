"""Offline human review package export, import, and judge calibration."""

from __future__ import annotations

import csv
import hashlib
import html
import json
import math
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from evals.metrics import cohens_kappa, spearman_rho
from evals.schemas import (
    DatasetCase,
    EvalSuite,
    HumanReview,
    HumanReviewDecision,
    RiskLevel,
)


class ReviewRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    status: Literal["unreviewed", "accepted", "edited", "rejected", "ambiguous"] = (
        "unreviewed"
    )
    reason: str | None = None
    score: int | None = Field(default=None, ge=1, le=5)
    corrected_reference: dict | None = None


def select_review_cases(
    cases: list[DatasetCase],
    *,
    fraction: float = 0.15,
    minimum_per_suite: int = 30,
    seed: str = "review-v1",
) -> list[DatasetCase]:
    if not 0 < fraction <= 1:
        raise ValueError("fraction must be in (0, 1]")
    selected: dict[str, DatasetCase] = {
        case.case_id: case
        for case in cases
        if case.risk_level == RiskLevel.safety_critical
    }
    by_suite: dict[EvalSuite, list[DatasetCase]] = defaultdict(list)
    by_stratum: dict[tuple[EvalSuite, str], list[DatasetCase]] = defaultdict(list)
    for case in cases:
        by_suite[case.suite].append(case)
        by_stratum[(case.suite, case.scenario)].append(case)

    for items in by_stratum.values():
        target = max(1, math.ceil(len(items) * fraction))
        for case in _stable_sample(items, target, seed):
            selected[case.case_id] = case
    for items in by_suite.values():
        target = min(len(items), minimum_per_suite)
        missing = target - sum(case.case_id in selected for case in items)
        if missing > 0:
            remaining = [case for case in items if case.case_id not in selected]
            for case in _stable_sample(remaining, missing, seed):
                selected[case.case_id] = case
    return sorted(selected.values(), key=lambda case: case.case_id)


def select_double_review_cases(
    cases: list[DatasetCase],
    *,
    fraction: float = 0.25,
    seed: str = "double-review-v1",
) -> list[DatasetCase]:
    if not 0 < fraction <= 1:
        raise ValueError("fraction must be in (0, 1]")
    target = math.ceil(len(cases) * fraction)
    return sorted(_stable_sample(cases, target, seed), key=lambda case: case.case_id)


def select_balanced_review_supplement(
    cases: list[DatasetCase],
    *,
    target: int,
    seed: str = "balanced-review-supplement-v1",
) -> list[DatasetCase]:
    """Select unreviewed cases with equal suite, then equal scenario, quotas."""
    if target < 1:
        raise ValueError("target must be positive")
    unreviewed = [
        case
        for case in cases
        if case.human_review.status == "unreviewed"
        and not case.human_review.independent_reviews
    ]
    if target > len(unreviewed):
        raise ValueError(
            "target exceeds unreviewed cases: "
            f"target={target} available={len(unreviewed)}"
        )
    by_suite: dict[EvalSuite, list[DatasetCase]] = defaultdict(list)
    for case in unreviewed:
        by_suite[case.suite].append(case)
    selected: list[DatasetCase] = []
    suite_order = [suite for suite in EvalSuite if by_suite[suite]]
    base_suite_target, suite_remainder = divmod(target, len(suite_order))
    for suite_index, suite in enumerate(suite_order):
        suite_target = base_suite_target + int(suite_index < suite_remainder)
        by_scenario: dict[str, list[DatasetCase]] = defaultdict(list)
        for case in by_suite[suite]:
            by_scenario[case.scenario].append(case)
        scenario_order = sorted(by_scenario)
        queues = {
            scenario: _stable_sample(items, len(items), f"{seed}:{suite.value}")
            for scenario, items in by_scenario.items()
        }
        while suite_target > 0:
            progressed = False
            for scenario in scenario_order:
                if not queues[scenario] or suite_target == 0:
                    continue
                selected.append(queues[scenario].pop(0))
                suite_target -= 1
                progressed = True
            if not progressed:
                raise ValueError(f"not enough unreviewed cases for suite {suite.value}")
    return sorted(selected, key=lambda case: case.case_id)


def export_review_html(
    cases: list[DatasetCase],
    output_path: Path,
    *,
    source_excerpts: dict[str, str] | None = None,
) -> Path:
    rows = []
    download_name = json.dumps(
        f"{output_path.stem}.completed.jsonl",
        ensure_ascii=False,
    )
    for case in cases:
        input_json = html.escape(json.dumps(case.input, ensure_ascii=False, indent=2))
        reference_json = html.escape(
            json.dumps(case.reference, ensure_ascii=False, indent=2)
        )
        source_refs = html.escape(
            json.dumps(
                [ref.model_dump(mode="json") for ref in case.source_refs],
                ensure_ascii=False,
                indent=2,
            )
        )
        hard_negatives = html.escape(
            json.dumps(
                [ref.model_dump(mode="json") for ref in case.hard_negative_refs],
                ensure_ascii=False,
                indent=2,
            )
        )
        judge_reasons = html.escape(
            json.dumps(case.qc.judge_decisions, ensure_ascii=False, indent=2)
        )
        excerpt = html.escape((source_excerpts or {}).get(case.case_id, ""))
        case_id = html.escape(case.case_id, quote=True)
        rows.append(
            f"<article class='review-case' data-case-id='{case_id}'>"
            f"<h2>{html.escape(case.case_id)}</h2>"
            f"<p><strong>Scenario:</strong> {html.escape(case.scenario)}</p>"
            f"<h3>Input</h3><pre>{input_json}</pre>"
            f"<h3>Reference</h3><pre>{reference_json}</pre>"
            f"<h3>Source refs</h3><pre>{source_refs}</pre>"
            f"<h3>Hard negatives</h3><pre>{hard_negatives}</pre>"
            f"<h3>Judge</h3><pre>{judge_reasons}</pre>"
            f"<h3>Source excerpt</h3><pre>{excerpt}</pre>"
            "<fieldset><legend>Human decision</legend>"
            "<label>Status <select class='status'><option value='unreviewed'>"
            "unreviewed</option><option value='accepted'>accepted</option>"
            "<option value='edited'>edited</option><option value='rejected'>"
            "rejected</option><option value='ambiguous'>ambiguous</option>"
            "</select></label> "
            "<label>Score <select class='score'><option value=''>-</option>"
            + "".join(
                f"<option value='{score}'>{score}</option>" for score in range(1, 6)
            )
            + "</select></label><br>"
            "<label>Reason<br><textarea class='reason' rows='3'></textarea></label><br>"
            "<label>Corrected reference JSON (edited only)<br>"
            "<textarea class='corrected-reference' rows='5'></textarea></label>"
            "</fieldset>"
            "</article>"
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        "<!doctype html><meta charset='utf-8'><title>Eval Review</title>"
        "<style>body{font-family:system-ui;max-width:1100px;margin:auto;padding:1rem}"
        ".toolbar{position:sticky;top:0;background:white;padding:1rem;"
        "border-bottom:1px solid #bbb}"
        "article{border-bottom:2px solid #ddd;padding:1rem 0}pre{white-space:pre-wrap}"
        "textarea{width:100%}.complete{border-left:5px solid #27864a;"
        "padding-left:1rem}</style>"
        "<div class='toolbar'><strong id='progress'></strong> "
        "<button id='download' type='button'>Download review JSONL</button></div>"
        + "\n".join(rows)
        + "<script>const cases=[...document.querySelectorAll('.review-case')];"
        "const progress=document.getElementById('progress');"
        "function update(){let done=0;for(const item of cases){const ok="
        "item.querySelector('.status').value!=='unreviewed'&&item.querySelector('.score').value;"
        "item.classList.toggle('complete',Boolean(ok));if(ok)done++;}"
        "progress.textContent=`${done}/${cases.length} completed`;return done;}"
        "for(const item of cases)item.addEventListener('change',update);update();"
        "document.getElementById('download').addEventListener('click',()=>{"
        "if(update()!==cases.length){"
        "alert('Complete status and score for every case first.');return;}"
        "const lines=[];for(const item of cases){"
        "const status=item.querySelector('.status').value;"
        "const raw=item.querySelector('.corrected-reference').value.trim();"
        "let corrected=null;"
        "if(status==='edited'){try{corrected=JSON.parse(raw);}catch(error){"
        "alert(`Invalid corrected reference JSON for ${item.dataset.caseId}`);return;}}"
        "lines.push(JSON.stringify({case_id:item.dataset.caseId,status,"
        "reason:item.querySelector('.reason').value||null,score:Number(item.querySelector('.score').value),"
        "corrected_reference:corrected}));}const blob=new Blob([lines.join('\\n')+'\\n'],"
        "{type:'application/x-ndjson'});const link=document.createElement('a');"
        "link.href=URL.createObjectURL(blob);link.download="
        + download_name
        + ";link.click();"
        "setTimeout(()=>URL.revokeObjectURL(link.href),1000);});</script>",
        encoding="utf-8",
    )
    return output_path


def export_review_jsonl(cases: list[DatasetCase], output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [ReviewRecord(case_id=case.case_id).model_dump_json() for case in cases]
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output_path


def export_review_csv(cases: list[DatasetCase], output_path: Path) -> Path:
    """Export the same compact, importable review template as CSV."""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=(
                "case_id",
                "status",
                "reason",
                "score",
                "corrected_reference_json",
            ),
        )
        writer.writeheader()
        for case in cases:
            writer.writerow(
                {
                    "case_id": case.case_id,
                    "status": "unreviewed",
                    "reason": "",
                    "score": "",
                    "corrected_reference_json": "",
                }
            )
    return output_path


def load_review_records(path: Path) -> list[ReviewRecord]:
    if path.suffix.casefold() == ".csv":
        with path.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        return [
            ReviewRecord(
                case_id=str(row.get("case_id") or ""),
                status=str(row.get("status") or "unreviewed"),
                reason=str(row["reason"]) if row.get("reason") else None,
                score=int(row["score"]) if row.get("score") else None,
                corrected_reference=(
                    json.loads(str(row["corrected_reference_json"]))
                    if row.get("corrected_reference_json")
                    else None
                ),
            )
            for row in rows
        ]
    return [
        ReviewRecord.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def apply_review_records(
    cases: list[DatasetCase],
    records: list[ReviewRecord],
    *,
    reviewer_version: str,
    adjudication: bool = False,
) -> list[DatasetCase]:
    by_id = {case.case_id: case for case in cases}
    if len(by_id) != len(cases):
        raise ValueError("dataset contains duplicate case IDs")
    seen: set[str] = set()
    for record in records:
        if record.case_id in seen:
            raise ValueError(f"duplicate review record: {record.case_id}")
        seen.add(record.case_id)
        case = by_id.get(record.case_id)
        if case is None:
            raise ValueError(f"unknown review case: {record.case_id}")
        if record.status == "edited" and record.corrected_reference is None:
            raise ValueError(
                f"edited review requires corrected_reference: {record.case_id}"
            )
        if record.corrected_reference is not None:
            original_reference = case.human_review.original_reference or dict(
                case.reference
            )
        else:
            original_reference = case.human_review.original_reference
        existing_reviews = list(case.human_review.independent_reviews)
        if adjudication:
            _apply_final_reference(case, record, original_reference)
            case.human_review = HumanReview(
                status=record.status,
                reviewer_version=reviewer_version,
                reason=record.reason,
                score=record.score,
                reviewed_at=(
                    datetime.now(UTC) if record.status != "unreviewed" else None
                ),
                independent_reviews=existing_reviews,
                original_reference=original_reference,
                adjudicated=True,
            )
            continue
        if record.status == "unreviewed":
            continue
        if any(
            decision.reviewer_version == reviewer_version for decision in existing_reviews
        ):
            raise ValueError(
                f"reviewer already submitted case: {reviewer_version}:{record.case_id}"
            )
        decision = HumanReviewDecision(
            status=record.status,
            reviewer_version=reviewer_version,
            reason=record.reason,
            score=record.score,
            corrected_reference=record.corrected_reference,
        )
        independent_reviews = [*existing_reviews, decision]
        statuses = {item.status for item in independent_reviews}
        corrections = {
            json.dumps(item.corrected_reference, ensure_ascii=False, sort_keys=True)
            for item in independent_reviews
            if item.status == "edited"
        }
        consensus = len(statuses) == 1 and len(corrections) <= 1
        if consensus:
            final_status = independent_reviews[0].status
            final_reason = record.reason
            _apply_final_reference(case, record, original_reference)
        else:
            final_status = "ambiguous"
            final_reason = "independent reviewer disagreement; adjudication required"
            if original_reference is not None:
                case.reference = dict(original_reference)
        case.human_review = HumanReview(
            status=final_status,
            reviewer_version=(
                reviewer_version
                if len(independent_reviews) == 1
                else "consensus"
                if consensus
                else None
            ),
            reason=final_reason,
            score=record.score if consensus else None,
            reviewed_at=datetime.now(UTC),
            independent_reviews=independent_reviews,
            original_reference=original_reference,
            adjudicated=False,
        )
    return cases


def _apply_final_reference(
    case: DatasetCase,
    record: ReviewRecord,
    original_reference: dict | None,
) -> None:
    if record.status == "edited" and record.corrected_reference is not None:
        case.reference = record.corrected_reference
    elif original_reference is not None:
        case.reference = dict(original_reference)


def judge_human_agreement(cases: list[DatasetCase]) -> dict[str, object]:
    judge_binary: list[str] = []
    human_binary: list[str] = []
    judge_scores: list[float] = []
    human_scores: list[float] = []
    for case in cases:
        if not case.qc.judge_decisions:
            continue
        human_label = _human_binary(case.human_review.status)
        judge_label = _judge_binary(case.qc.judge_decisions[-1].get("decision"))
        if human_label is not None and judge_label is not None:
            human_binary.append(human_label)
            judge_binary.append(judge_label)
        judge_score = case.qc.judge_decisions[-1].get("rubric_score")
        if case.human_review.score is not None and judge_score is not None:
            human_scores.append(float(case.human_review.score))
            judge_scores.append(float(judge_score))

    report: dict[str, object] = {
        "binary_sample_count": len(judge_binary),
        "ordinal_sample_count": len(judge_scores),
        "cohens_kappa": None,
        "spearman_rho": None,
        "binary_gate_passed": False,
        "ordinal_gate_passed": False,
        "llm_metrics_blocking": False,
    }
    human_binary_support = Counter(human_binary)
    judge_binary_support = Counter(judge_binary)
    binary_calibration_sufficient = all(
        human_binary_support[label] >= 20 and judge_binary_support[label] >= 20
        for label in ("accept", "reject")
    )
    ordinal_buckets = Counter(
        "low" if score <= 2 else "mid" if score == 3 else "high" for score in human_scores
    )
    ordinal_calibration_sufficient = all(
        ordinal_buckets[bucket] >= 20 for bucket in ("low", "mid", "high")
    )
    report.update(
        {
            "binary_human_support": dict(human_binary_support),
            "binary_judge_support": dict(judge_binary_support),
            "binary_calibration_sufficient": binary_calibration_sufficient,
            "ordinal_human_bucket_support": dict(ordinal_buckets),
            "ordinal_calibration_sufficient": ordinal_calibration_sufficient,
            "binary_accuracy": (
                sum(left == right for left, right in zip(judge_binary, human_binary))
                / len(judge_binary)
                if judge_binary
                else None
            ),
        }
    )
    if judge_binary:
        kappa = cohens_kappa(judge_binary, human_binary)
        report["cohens_kappa"] = kappa
        report["binary_gate_passed"] = kappa >= 0.75
    if len(judge_scores) >= 2:
        rho = spearman_rho(judge_scores, human_scores)
        report["spearman_rho"] = rho
        report["ordinal_gate_passed"] = rho >= 0.70
    inter_reviewer = inter_reviewer_agreement(cases)
    report["inter_reviewer"] = inter_reviewer
    report["llm_metrics_blocking"] = bool(
        report["binary_gate_passed"]
        and report["ordinal_gate_passed"]
        and inter_reviewer["gate_passed"]
    )
    return report


def inter_reviewer_agreement(cases: list[DatasetCase]) -> dict[str, object]:
    first_labels: list[str] = []
    second_labels: list[str] = []
    for case in cases:
        reviews = case.human_review.independent_reviews
        if len(reviews) < 2:
            continue
        first = _human_binary(reviews[0].status)
        second = _human_binary(reviews[1].status)
        if first is None or second is None:
            continue
        first_labels.append(first)
        second_labels.append(second)
    kappa = cohens_kappa(first_labels, second_labels) if first_labels else None
    raw_agreement = (
        sum(left == right for left, right in zip(first_labels, second_labels))
        / len(first_labels)
        if first_labels
        else None
    )
    label_support = Counter([*first_labels, *second_labels])
    calibration_sufficient = all(
        label_support[label] >= 20 for label in ("accept", "reject")
    )
    gate_passed = bool(
        (calibration_sufficient and kappa is not None and kappa >= 0.75)
        or (
            not calibration_sufficient
            and len(first_labels) >= 30
            and raw_agreement is not None
            and raw_agreement >= 0.95
        )
    )
    return {
        "sample_count": len(first_labels),
        "cohens_kappa": kappa,
        "raw_agreement": raw_agreement,
        "label_support": dict(label_support),
        "calibration_sufficient": calibration_sufficient,
        "gate_mode": "kappa" if calibration_sufficient else "prevalence_adjusted_raw",
        "gate_passed": gate_passed,
    }


def human_review_quality(cases: list[DatasetCase]) -> dict[str, object]:
    reviewed = [
        case
        for case in cases
        if case.human_review.status != "unreviewed"
        or bool(case.human_review.independent_reviews)
    ]
    accepted = sum(
        case.human_review.status in {"accepted", "edited"} for case in reviewed
    )
    invalid = sum(
        case.human_review.status in {"rejected", "ambiguous"} for case in reviewed
    )
    total = len(reviewed)
    faithful_rate = accepted / total if total else 0.0
    invalid_rate = invalid / total if total else 1.0
    return {
        "sample_count": total,
        "accepted_or_edited_count": accepted,
        "ambiguous_or_invalid_count": invalid,
        "faithful_answerable_rate": faithful_rate,
        "ambiguous_invalid_rate": invalid_rate,
        "faithful_gate_passed": total > 0 and faithful_rate >= 0.95,
        "invalid_gate_passed": total > 0 and invalid_rate <= 0.02,
    }


def reviewed_raw_candidate_diagnostic(cases: list[DatasetCase]) -> dict[str, object]:
    """Report raw-candidate review outcomes without filtering rejected cases."""

    quality = human_review_quality(cases)
    reviewed = int(quality["sample_count"])
    invalid = int(quality["ambiguous_or_invalid_count"])
    return {
        "candidate_count": len(cases),
        "reviewed_count": reviewed,
        "accepted_or_edited_count": int(quality["accepted_or_edited_count"]),
        "ambiguous_or_invalid_count": invalid,
        "ambiguous_invalid_rate": invalid / reviewed if reviewed else None,
        "target_max_rate": 0.02,
        "target_passed": reviewed > 0 and invalid / reviewed <= 0.02,
    }


def _human_binary(status: str) -> str | None:
    if status in {"accepted", "edited"}:
        return "accept"
    if status == "rejected":
        return "reject"
    return None


def _judge_binary(status: object) -> str | None:
    return str(status) if status in {"accept", "reject"} else None


def _stable_sample(
    cases: list[DatasetCase],
    size: int,
    seed: str,
) -> list[DatasetCase]:
    return sorted(
        cases,
        key=lambda case: hashlib.sha256(f"{seed}:{case.case_id}".encode()).hexdigest(),
    )[:size]
