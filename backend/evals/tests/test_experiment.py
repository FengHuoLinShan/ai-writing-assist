import pytest

from evals.experiment import RequestObservation, summarize_requests, validate_story_splits
from evals.metrics import evidence_group_recall, precision_at_fixed_k, precision_at_k
from evals.schemas import DatasetCase, LogicalSourceRef


def ref(start=0, end=10, **changes):
    return LogicalSourceRef.model_validate(
        {
            "corpus_id": "synthetic",
            "source_alias": "chapter-a",
            "source_group_id": "story-a",
            "chapter_index": 1,
            "content_hash": "a" * 64,
            "start_offset": start,
            "end_offset": end,
            **changes,
        }
    )


def test_short_results_preserve_legacy_but_do_not_inflate_fixed_k():
    assert precision_at_k(["a"], {"a"}, 5) == 1
    assert precision_at_fixed_k(["a"], {"a"}, 5) == 0.2
    assert precision_at_fixed_k(["a", "a"], {"a"}, 5) == 0.2
    with pytest.raises(ValueError):
        precision_at_fixed_k([], set(), 0)


def test_gold_requires_every_range_and_version_without_double_counting():
    group = [ref(0, 10), ref(20, 30)]
    assert evidence_group_recall([ref(0, 6), ref(4, 10), ref(20, 30)], [group]) == 1
    assert evidence_group_recall([ref(0, 6), ref(7, 10), ref(20, 30)], [group]) == 0
    assert evidence_group_recall([ref(0, 30, content_hash="b" * 64)], [group]) == 0
    assert evidence_group_recall([ref(0, 30, source_alias="other")], [group]) == 0
    with pytest.raises(ValueError):
        evidence_group_recall([], [[]])


def test_unknown_consumption_is_not_zero_and_failures_are_counted():
    receipts = [
        RequestObservation(
            request_id="1",
            stage="read",
            status="succeeded",
            input_tokens=12,
            output_tokens=4,
        ),
        RequestObservation(request_id="2", stage="review", status="unknown"),
        RequestObservation(
            request_id="3",
            stage="retry",
            status="failed",
            input_tokens=8,
            output_tokens=0,
        ),
    ]
    summary = summarize_requests(receipts)
    assert summary["actual_requests"] == 3
    assert summary["known_input_tokens"] == 20
    assert summary["total_input_tokens"] is None
    assert summary["unknown_usage_requests"] == summary["failed_requests"] == 1
    assert not summary["usage_complete"]
    assert summarize_requests([])["actual_requests"] == 0
    with pytest.raises(ValueError):
        summarize_requests([receipts[0], receipts[0]])


def test_story_and_source_cannot_cross_dataset_splits():
    case = DatasetCase(
        case_id="story-a-01",
        suite="rag",
        scenario="negation",
        source_group_id="story-a",
        source_refs=[ref()],
        input={},
        reference={},
        split="dev",
    )
    validate_story_splits([case])
    for changed in ({}, {"source_group_id": "different-story"}):
        other = DatasetCase.model_validate(
            {**case.model_dump(), "case_id": "story-b-01", "split": "test", **changed}
        )
        with pytest.raises(ValueError, match="cross-split"):
            validate_story_splits([case, other])
