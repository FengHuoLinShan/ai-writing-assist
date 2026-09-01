from __future__ import annotations

from dataclasses import replace

import pytest

from evals.rp_context import (
    RUBRIC_DIMENSIONS,
    RPBlindReview,
    load_case,
    summarize_blind_reviews,
)


def _scores(value: int) -> dict[str, int]:
    return dict.fromkeys(RUBRIC_DIMENSIONS, value)


def test_rp_case_rejects_raw_text_in_place_of_hashes() -> None:
    with pytest.raises(ValueError, match="hashes"):
        load_case(
            {
                "case_id": "unsafe",
                "corpus_hash": "copyrighted source text",
                "scenario_hash": "b" * 64,
                "source_refs": [{}],
            }
        )
    with pytest.raises(ValueError, match="only hashes"):
        load_case(
            {
                "case_id": "unsafe-extra",
                "corpus_hash": "a" * 64,
                "scenario_hash": "b" * 64,
                "source_refs": [{}],
                "source_text": "不应保存的正文",
            }
        )


def test_blind_summary_requires_improvement_without_spoiler_regression() -> None:
    reviews = [
        RPBlindReview(case_id="case", candidate="A", scores=_scores(4)),
        RPBlindReview(case_id="case", candidate="B", scores=_scores(2)),
    ]
    improved = summarize_blind_reviews(
        reviews,
        arm_by_candidate={"A": "context_on", "B": "context_off"},
    )
    spoiler_regression = summarize_blind_reviews(
        [replace(reviews[0], severe_spoiler=True), reviews[1]],
        arm_by_candidate={"A": "context_on", "B": "context_off"},
    )

    assert improved["claim_allowed"] is True
    assert spoiler_regression["claim_allowed"] is False
    assert "not a completed user trial" in improved["note"]
