"""Purely offline readiness gates for freezing or running eval baselines."""

from __future__ import annotations

import math
from collections import Counter
from typing import Any, Literal

from evals.schemas import (
    ALLOWED_HIGH_QUALITY_LLM_MODELS,
    DatasetCase,
    EvalSuite,
    RiskLevel,
)

BaselineTier = Literal["pilot", "release"]

BASELINE_MINIMUMS: dict[BaselineTier, dict[EvalSuite, int]] = {
    "pilot": {
        EvalSuite.rag: 80,
        EvalSuite.scene: 40,
        EvalSuite.world: 50,
        EvalSuite.outline: 30,
    },
    "release": {
        EvalSuite.rag: 300,
        EvalSuite.scene: 180,
        EvalSuite.world: 200,
        EvalSuite.outline: 120,
    },
}
BASELINE_TOTAL_MINIMUMS: dict[BaselineTier, int] = {
    "pilot": 200,
    "release": 800,
}
BASELINE_SCENARIOS: dict[EvalSuite, tuple[str, ...]] = {
    EvalSuite.rag: (
        "exact_name",
        "alias_paraphrase",
        "multi_hop",
        "hard_negative",
        "no_answer",
        "visibility_cutoff",
    ),
    EvalSuite.scene: (
        "location_shift",
        "goal_shift",
        "weak_boundary",
        "cross_chapter",
    ),
    EvalSuite.world: (
        "durable_entity",
        "alias",
        "relation",
        "ordinary_object_negative",
    ),
    EvalSuite.outline: (
        "thread",
        "foreshadow",
        "duplicate",
        "early_reveal",
    ),
}
SAFETY_REVIEW_ERROR = "safety_critical_requires_human_review"


def assess_baseline_readiness(
    cases: list[DatasetCase],
    *,
    tier: BaselineTier,
    suites: tuple[EvalSuite, ...],
) -> dict[str, Any]:
    """Assess already-materialized decisions without running QC or an LLM."""
    selected = [case for case in cases if case.suite in suites]
    eligible = [case for case in selected if is_baseline_eligible(case)]
    rejected = [case.case_id for case in selected if not is_baseline_eligible(case)]
    suite_counts = Counter(case.suite for case in eligible)
    scenario_counts = Counter((case.suite, case.scenario) for case in eligible)
    issues: list[str] = []

    invalid_generation_provenance = [
        case.case_id
        for case in eligible
        if case.generation_meta.model not in ALLOWED_HIGH_QUALITY_LLM_MODELS
        or not _is_sha256(case.generation_meta.profile_hash)
        or not _is_sha256(case.generation_meta.prompt_hash)
        or not _is_sha256(case.generation_meta.source_hash)
    ]
    if invalid_generation_provenance:
        issues.append(
            f"generation_provenance_invalid:count={len(invalid_generation_provenance)}"
        )
    invalid_judge_provenance = [
        case.case_id
        for case in eligible
        if len(case.qc.judge_decisions)
        < (2 if case.risk_level == RiskLevel.safety_critical else 1)
        or any(
            decision.get("model") not in ALLOWED_HIGH_QUALITY_LLM_MODELS
            or not _is_sha256(str(decision.get("prompt_hash") or ""))
            for decision in case.qc.judge_decisions
        )
    ]
    if invalid_judge_provenance:
        issues.append(f"judge_provenance_invalid:count={len(invalid_judge_provenance)}")

    invalid_scene_coordinate_case_ids = [
        case.case_id
        for case in eligible
        if case.suite == EvalSuite.scene
        and (
            not case.source_refs
            or any(
                ref.start_offset is None or ref.end_offset is None or not ref.range_hash
                for ref in case.source_refs
            )
        )
    ]
    if invalid_scene_coordinate_case_ids:
        issues.append(
            "scene_canonical_source_range_invalid:"
            f"count={len(invalid_scene_coordinate_case_ids)}"
        )

    source_group_splits: dict[str, set[str]] = {}
    for case in eligible:
        source_group_splits.setdefault(case.source_group_id, set()).add(case.split.value)
    leaking_groups = sorted(
        group for group, splits in source_group_splits.items() if len(splits) > 1
    )
    if leaking_groups:
        issues.append(f"source_group_split_leakage:count={len(leaking_groups)}")

    for suite in suites:
        minimum = BASELINE_MINIMUMS[tier][suite]
        actual = suite_counts[suite]
        if actual < minimum:
            issues.append(
                f"suite_minimum:{suite.value}:required={minimum}:actual={actual}"
            )
        scenario_minimum = 20 if tier == "release" else 1
        for scenario in BASELINE_SCENARIOS[suite]:
            actual_scenario_count = scenario_counts[(suite, scenario)]
            if actual_scenario_count < scenario_minimum:
                issues.append(
                    f"scenario_minimum:{suite.value}:{scenario}:"
                    f"required={scenario_minimum}:actual={actual_scenario_count}"
                )

    if set(suites) == set(EvalSuite):
        minimum = BASELINE_TOTAL_MINIMUMS[tier]
        if len(eligible) < minimum:
            issues.append(f"total_minimum:required={minimum}:actual={len(eligible)}")

    split_group_counts = Counter(
        next(iter(splits)) for splits in source_group_splits.values() if len(splits) == 1
    )
    if tier == "release" and source_group_splits:
        total_groups = sum(split_group_counts.values())
        for split, target in {"train": 0.60, "dev": 0.20, "test": 0.20}.items():
            actual = split_group_counts[split] / total_groups
            if abs(actual - target) > 0.05:
                issues.append(
                    f"source_group_split_ratio:{split}:"
                    f"target={target:.2f}:actual={actual:.3f}"
                )

    reviewed = [
        case
        for case in eligible
        if case.human_review.status != "unreviewed"
        or bool(case.human_review.independent_reviews)
    ]
    reviewed_ids = {case.case_id for case in reviewed}
    for suite in suites:
        suite_cases = [case for case in eligible if case.suite == suite]
        reviewed_count = sum(case.case_id in reviewed_ids for case in suite_cases)
        required = min(
            len(suite_cases),
            max(30, math.ceil(len(suite_cases) * 0.15)),
        )
        if reviewed_count < required:
            issues.append(
                f"human_review_suite_minimum:{suite.value}:"
                f"required={required}:actual={reviewed_count}"
            )
        for scenario in BASELINE_SCENARIOS[suite]:
            scenario_cases = [case for case in suite_cases if case.scenario == scenario]
            required_scenario = math.ceil(len(scenario_cases) * 0.15)
            actual_scenario = sum(case.case_id in reviewed_ids for case in scenario_cases)
            if actual_scenario < required_scenario:
                issues.append(
                    f"human_review_scenario_minimum:{suite.value}:{scenario}:"
                    f"required={required_scenario}:actual={actual_scenario}"
                )
    double_review_count = sum(
        len(case.human_review.independent_reviews) >= 2 for case in reviewed
    )
    required_double_reviews = math.ceil(len(reviewed) * 0.25)
    if double_review_count < required_double_reviews:
        issues.append(
            "double_review_minimum:"
            f"required={required_double_reviews}:actual={double_review_count}"
        )

    from evals.review import judge_human_agreement

    agreement = judge_human_agreement(eligible)
    if agreement["binary_calibration_sufficient"] and not agreement["binary_gate_passed"]:
        issues.append("judge_human_binary_agreement_below_threshold")
    if (
        agreement["ordinal_calibration_sufficient"]
        and not agreement["ordinal_gate_passed"]
    ):
        issues.append("judge_human_ordinal_agreement_below_threshold")
    if not agreement["inter_reviewer"]["gate_passed"]:
        issues.append("inter_reviewer_agreement_below_threshold")

    safety_without_human_acceptance = [
        case.case_id
        for case in selected
        if case.risk_level == RiskLevel.safety_critical
        and (
            case.human_review.status not in {"accepted", "edited"}
            or not (
                case.human_review.independent_reviews or case.human_review.adjudicated
            )
        )
    ]
    if safety_without_human_acceptance:
        issues.append(
            f"safety_human_review_incomplete:count={len(safety_without_human_acceptance)}"
        )
    if rejected:
        issues.append(f"dataset_contains_nonaccepted_cases:count={len(rejected)}")

    return {
        "ready": not issues,
        "tier": tier,
        "selected_suites": [suite.value for suite in suites],
        "case_count": len(selected),
        "eligible_count": len(eligible),
        "suite_counts": {suite.value: suite_counts[suite] for suite in suites},
        "scenario_counts": {
            f"{suite.value}:{scenario}": count
            for (suite, scenario), count in sorted(
                scenario_counts.items(),
                key=lambda item: (item[0][0].value, item[0][1]),
            )
        },
        "source_group_count": len(source_group_splits),
        "split_group_counts": dict(split_group_counts),
        "split_leakage_groups": leaking_groups,
        "invalid_generation_provenance_case_ids": invalid_generation_provenance,
        "invalid_judge_provenance_case_ids": invalid_judge_provenance,
        "invalid_scene_coordinate_case_ids": invalid_scene_coordinate_case_ids,
        "generation_models": sorted({case.generation_meta.model for case in eligible}),
        "judge_models": sorted(
            {
                str(decision.get("model"))
                for case in eligible
                for decision in case.qc.judge_decisions
                if decision.get("model")
            }
        ),
        "human_reviewed_count": len(reviewed),
        "double_reviewed_count": double_review_count,
        "required_double_review_count": required_double_reviews,
        "agreement": agreement,
        "nonaccepted_case_ids": rejected,
        "safety_without_human_acceptance": safety_without_human_acceptance,
        "issues": issues,
    }


def is_baseline_eligible(case: DatasetCase) -> bool:
    human_status = case.human_review.status
    if human_status in {"rejected", "ambiguous"}:
        return False
    human_accepted = human_status in {"accepted", "edited"}
    blocking_deterministic_errors = {
        error for error in case.qc.deterministic_errors if error != SAFETY_REVIEW_ERROR
    }
    if blocking_deterministic_errors:
        return False
    if case.risk_level == RiskLevel.safety_critical:
        return human_accepted
    return case.qc.status == "accepted" or human_accepted


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(
        character in "0123456789abcdef" for character in value
    )
