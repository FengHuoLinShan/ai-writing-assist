"""Human qualification and burden comparison for import review, without model grading."""

from __future__ import annotations

from collections import defaultdict
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from evals.schemas import DatasetSplit


class ResolutionReviewCase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    case_id: str
    project_id: str
    source_group_id: str
    source_hash: str = Field(min_length=64, max_length=64)
    split: DatasetSplit
    category: Literal["entity", "relation", "alias", "scene"]
    proposed_outcome: Literal[
        "eligible", "organized", "decision", "optional", "incomplete"
    ]
    reviewer_type: Literal["human", "model"] | None = None
    reviewer_id: str | None = None
    human_correct: bool | None = None
    critical_error: bool | None = None
    expected_decision: bool | None = None


def qualification_report(
    cases: list[ResolutionReviewCase],
    *,
    baseline_decisions=None,
    new_decisions=None,
    baseline_seconds=None,
    new_seconds=None,
):
    """Missing human evidence stays unknown and never counts as a passing label."""
    partitions, categories = defaultdict(set), defaultdict(list)
    for case in cases:
        partitions[(case.project_id, case.source_group_id)].add(case.split)
        if case.split == DatasetSplit.test:
            categories[case.category].append(case)
    if any(
        DatasetSplit.test in splits and len(splits) > 1 for splits in partitions.values()
    ):
        raise ValueError("A source group cannot occur in development and held-out data")
    result = {}
    for category, samples in categories.items():
        human = [
            case
            for case in samples
            if case.reviewer_type == "human"
            and case.reviewer_id
            and case.human_correct is not None
            and case.critical_error is not None
            and case.expected_decision is not None
        ]
        admitted = [case for case in human if case.proposed_outcome == "eligible"]
        accuracy = (
            sum(case.human_correct for case in admitted) / len(admitted)
            if admitted
            else None
        )
        critical = sum(case.critical_error for case in human)
        missed = sum(
            case.expected_decision and case.proposed_outcome != "decision"
            for case in human
        )
        result[category] = {
            "test_cases": len(samples),
            "human_reviewed": len(human),
            "unreviewed": len(samples) - len(human),
            "admission_sample_size": len(admitted),
            "admission_accuracy": accuracy,
            "critical_errors": critical,
            "missed_decisions": missed,
            "qualified": len(human) == len(samples)
            and len({case.project_id for case in samples}) >= 2
            and accuracy is not None
            and accuracy >= 0.98
            and critical == 0
            and missed == 0,
        }

    def reduction(before, after):
        return (
            None
            if before is None or after is None or before <= 0
            else (before - after) / before
        )

    decisions, seconds = (
        reduction(baseline_decisions, new_decisions),
        reduction(baseline_seconds, new_seconds),
    )
    return {
        "categories": result,
        "decision_reduction": decisions,
        "time_reduction": seconds,
        "burden_target_met": decisions is not None
        and seconds is not None
        and decisions >= 0.5
        and seconds >= 0.5,
        "limitations": "Frozen sample only; model confidence is not human qualification.",
    }
