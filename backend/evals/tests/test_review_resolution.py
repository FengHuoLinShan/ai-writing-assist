import pytest

from evals.review_resolution import ResolutionReviewCase, qualification_report


def case(**changes):
    return ResolutionReviewCase.model_validate(
        {
            "case_id": "a",
            "project_id": "p1",
            "source_group_id": "scene1",
            "source_hash": "a" * 64,
            "split": "test",
            "category": "alias",
            "proposed_outcome": "eligible",
            **changes,
        }
    )


def test_model_scores_and_unreviewed_samples_do_not_open_auto_admission():
    report = qualification_report(
        [
            case(
                reviewer_type="model",
                reviewer_id="review-model",
                human_correct=True,
                critical_error=False,
                expected_decision=False,
            )
        ]
    )
    assert not report["categories"]["alias"]["qualified"]
    assert report["categories"]["alias"]["human_reviewed"] == 0
    assert report["time_reduction"] is None
    assert not report["burden_target_met"]


def test_critical_miss_blocks_qualification_even_with_high_accuracy():
    samples = [
        case(
            case_id=str(i),
            project_id="p1" if i % 2 else "p2",
            reviewer_type="human",
            reviewer_id="author",
            human_correct=True,
            critical_error=i == 0,
            expected_decision=i == 0,
        )
        for i in range(100)
    ]
    assert not qualification_report(samples)["categories"]["alias"]["qualified"]


def test_holdout_cannot_share_source_groups_with_development():
    with pytest.raises(ValueError):
        qualification_report([case(), case(case_id="dev", split="dev")])
