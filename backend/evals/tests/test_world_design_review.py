import json
from pathlib import Path

import pytest

from evals.world_design_review import (
    WorldDesignReviewPair,
    evaluate_world_design_review_pairs,
)


def _arm(**updates):
    return {
        "model": "frozen-model",
        "context_hash": "a" * 64,
        "token_budget": 12000,
        "adjudicated": True,
        "severe_goal_errors": 1,
        "severe_causal_errors": 1,
        "false_positive_issues": 1,
        "unnecessary_author_decisions": 0,
        "knowledge_boundary_regressions": 0,
        "project_isolation_regressions": 0,
        **updates,
    }


def test_same_budget_gate_requires_fewer_severe_errors_without_new_friction():
    pair = WorldDesignReviewPair.model_validate(
        {
            "case_id": "resource-loop",
            "baseline": _arm(),
            "candidate": _arm(
                severe_goal_errors=0,
                severe_causal_errors=1,
            ),
        }
    )
    report = evaluate_world_design_review_pairs([pair])
    assert report["enabled"] is True
    assert all(report["gates"].values())


def test_gate_fails_on_false_positive_or_boundary_regression():
    pair = WorldDesignReviewPair.model_validate(
        {
            "case_id": "reasonable-weirdness",
            "baseline": _arm(),
            "candidate": _arm(
                severe_goal_errors=0,
                severe_causal_errors=0,
                false_positive_issues=2,
                knowledge_boundary_regressions=1,
            ),
        }
    )
    report = evaluate_world_design_review_pairs([pair])
    assert report["enabled"] is False
    assert report["gates"]["false_positives_not_increased"] is False
    assert report["gates"]["knowledge_and_project_isolation_zero_regression"] is False


def test_pair_rejects_different_model_context_budget_or_unreviewed_arm():
    for candidate in (
        _arm(model="other"),
        _arm(context_hash="b" * 64),
        _arm(token_budget=12001),
        _arm(adjudicated=False),
    ):
        with pytest.raises(ValueError):
            WorldDesignReviewPair.model_validate(
                {"case_id": "mismatch", "baseline": _arm(), "candidate": candidate}
            )


def test_manifest_covers_required_world_design_failure_modes():
    path = (
        Path(__file__).parents[1]
        / "datasets"
        / "manifests"
        / "world-design-review-v1.json"
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert {item["case_id"] for item in payload["cases"]} == {
        "goal-misread",
        "author-boundary",
        "resource-loop",
        "information-flow",
        "institution-enforcement",
        "maintenance-failure",
        "long-feedback",
        "reasonable-weirdness",
        "no-issue",
        "insufficient-evidence",
        "value-tradeoff",
    }
