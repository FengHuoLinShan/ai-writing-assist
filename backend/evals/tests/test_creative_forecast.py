import json

import pytest

from evals.creative_forecast import (
    DIMENSIONS,
    TOOLS,
    Receipt,
    blind_export,
    corpus,
    digest,
    report,
)


def test_frozen_prefixes_family_split_and_blind_export(tmp_path):
    cases = corpus()
    assert len(cases) == 120 and len({case["family"] for case in cases}) == 12
    assert sum(case["quiet_or_weak"] for case in cases) == 48
    assert {case["family"] for case in cases if case["split"] == "dev"}.isdisjoint(
        {case["family"] for case in cases if case["split"] == "holdout"}
    )
    first, second = cases[:2]
    assert second["prefix"].startswith(first["prefix"])
    assert first["source_manifest"]["synthetic-prose"] == digest(first["prefix"])
    record = Receipt(
        case_id=first["id"],
        arm="B",
        capability="revision",
        code_sha="a" * 40,
        profile_hash="b" * 64,
        scope_hash="c" * 64,
        tools=[],
        workspace=True,
        run_id="synthetic",
        evidence_kind="fixture",
        output="<script>not HTML</script>",
        status="failed",
        requests=1,
        tool_calls=0,
        audit_requests=0,
        repair_requests=0,
        unknown_usage=1,
        duration_ms=25,
    )
    blind_export([record], tmp_path, seed="secret-blinding-seed")
    visible = (tmp_path / "reviewer-1/review.html").read_text()
    assert "<script>" not in visible and "&lt;script&gt;" in visible
    assert "fixture" not in visible and "secret-blinding-seed" not in visible
    mapping = json.loads((tmp_path / "operator-only/mapping.json").read_text())
    summary = report(mapping, {})
    result = summary["capabilities"]["creative:revision"]
    assert result["content_gate"] == "not_passed"
    assert result["arms"]["B"]["cost"] is None
    assert result["arms"]["B"]["unknown_usage"] == 1
    with pytest.raises(ValueError, match="Unknown usage"):
        Receipt.model_validate({**record.model_dump(), "cost": 0, "currency": "USD"})
    with pytest.raises(ValueError, match="gateway call receipt"):
        Receipt.model_validate({**record.model_dump(), "evidence_kind": "real_gateway"})

    # Synthetic accounting inputs exercise both contribution comparisons; four
    # prefixes cannot pass the publication gate, even with perfect fake scores.
    paired, reviews = {}, {}
    prefixes = [
        case
        for case in cases
        if case["split"] == "holdout" and case["id"].endswith("-01")
    ]
    for case in prefixes:
        for arm, score in [("A", 0), ("B", 1), ("C", 2), ("D", 0)]:
            key = case["id"] + arm
            paired[key] = {
                **record.model_dump(),
                "case_id": case["id"],
                "arm": arm,
                "tools": sorted(TOOLS),
                "workspace": arm in {"B", "C"},
                "evidence_kind": "real_gateway",
                "provider_call_ids": ["unit-test-only-" + key],
                "status": "completed",
                "unknown_usage": 0,
            }
            reviews[key] = [
                {
                    **dict.fromkeys(DIMENSIONS, score),
                    "hard_boundary_violation": 0,
                    "new_severe_errors": 0,
                    "unsupported_strong_claims": 0,
                    "hard_constraints_kept": 1,
                }
            ] * 2
    comparison = report(paired, reviews)["capabilities"]["creative:revision"]
    assert comparison["comparisons"]["C minus B"]["paired_family_interval"] == [1, 1]
    assert comparison["comparisons"]["C minus D"]["holdout_family_interval"] == [2, 2]
    assert comparison["content_gate"] == "not_passed"
