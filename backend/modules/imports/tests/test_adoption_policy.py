from __future__ import annotations

from modules.imports.adoption_policy import build_asset_summary, empty_asset_summary


def test_empty_asset_summary_has_explicit_zeroes_for_every_kind() -> None:
    summary = empty_asset_summary()

    assert summary == {
        "adopted": 0,
        "review": 0,
        "not_adopted": 0,
        "by_kind": {
            kind: {"adopted": 0, "review": 0, "not_adopted": 0}
            for kind in ("scene", "entity", "relation", "alias", "structure")
        },
    }


def test_asset_summary_uses_phase_stats_without_double_counting_temporary() -> None:
    summary = build_asset_summary(
        {
            "scene_commit": {
                "created_count": 3,
                "adopted_count": 2,
                "review_count": 1,
                "conflict_count": 1,
            },
            "phase2": {
                "total_created": 4,
                "total_relations": 3,
                "total_aliases": 2,
                "phase2_ignored": 2,
                "phase2_temporary_only": 1,
                "phase2_dedup_counts": {"auto_merged": 1},
            },
            "phase3": {
                "total_threads": 1,
                "total_arcs": 1,
                "total_foreshadowing": 1,
                "total_reveals": 1,
                "uncertain_count": 1,
                "review_asset_count": 1,
                "review_asset_ids": ["outline_arc:a1"],
                "structure_dedup": {
                    "suggestions_recorded": 2,
                    "auto_applied": 1,
                    "skipped_external_asset": 1,
                    "current_workflow_asset_outcomes": {
                        "review": 1,
                        "not_adopted": 1,
                        "affected": 2,
                        "review_asset_ids": ["plot_thread:t1"],
                        "not_adopted_asset_ids": ["reveal_plan:r1"],
                    },
                },
            },
        }
    )

    assert summary["by_kind"]["scene"] == {
        "adopted": 2,
        "review": 1,
        "not_adopted": 1,
    }
    assert summary["by_kind"]["entity"] == {
        "adopted": 0,
        "review": 2,
        "not_adopted": 4,
    }
    assert summary["by_kind"]["relation"]["review"] == 3
    assert summary["by_kind"]["alias"]["review"] == 2
    assert summary["by_kind"]["structure"] == {
        "adopted": 1,
        "review": 2,
        "not_adopted": 1,
    }
    assert summary["adopted"] == 3
    assert summary["review"] == 10
    assert summary["not_adopted"] == 6


def test_structure_summary_uses_unique_workflow_assets_not_suggestion_pairs() -> None:
    summary = build_asset_summary(
        {
            "phase3": {
                "total_threads": 3,
                "review_asset_count": 0,
                "structure_dedup": {
                    "auto_applied": 0,
                    "skipped_external_asset": 6,
                    "current_workflow_asset_outcomes": {
                        "review": 3,
                        "not_adopted": 0,
                        "affected": 3,
                        "review_asset_ids": [
                            "plot_thread:t1",
                            "plot_thread:t2",
                            "plot_thread:t3",
                        ],
                        "not_adopted_asset_ids": [],
                    },
                },
            },
        }
    )

    assert summary["by_kind"]["structure"] == {
        "adopted": 0,
        "review": 3,
        "not_adopted": 0,
    }


def test_structure_summary_ignores_old_only_suggestion_pairs() -> None:
    summary = build_asset_summary(
        {
            "phase3": {
                "total_threads": 2,
                "review_asset_count": 0,
                "structure_dedup": {
                    "auto_applied": 0,
                    "skipped_external_asset": 4,
                    "current_workflow_asset_outcomes": {
                        "review": 0,
                        "not_adopted": 0,
                        "affected": 0,
                        "review_asset_ids": [],
                        "not_adopted_asset_ids": [],
                    },
                },
            },
        }
    )

    assert summary["by_kind"]["structure"] == {
        "adopted": 2,
        "review": 0,
        "not_adopted": 0,
    }


def test_structure_summary_combines_phase_review_and_dedup_outcomes_with_clamp() -> None:
    summary = build_asset_summary(
        {
            "phase3": {
                "total_threads": 3,
                "review_asset_count": 2,
                "review_asset_ids": ["plot_thread:t1", "plot_thread:t2"],
                "uncertain_count": 7,
                "structure_dedup": {
                    "current_workflow_asset_outcomes": {
                        "review": 2,
                        "not_adopted": 1,
                        "affected": 3,
                        "review_asset_ids": [
                            "plot_thread:t1",
                            "plot_thread:t2",
                        ],
                        "not_adopted_asset_ids": ["plot_thread:t3"],
                    },
                },
            },
        }
    )

    assert summary["by_kind"]["structure"] == {
        "adopted": 0,
        "review": 2,
        "not_adopted": 1,
    }
    assert sum(summary["by_kind"]["structure"].values()) == 3


def test_structure_summary_deduplicates_same_review_asset_across_sources() -> None:
    summary = build_asset_summary(
        {
            "phase3": {
                "total_threads": 2,
                "review_asset_count": 1,
                "review_asset_ids": ["plot_thread:t1"],
                "structure_dedup": {
                    "current_workflow_asset_outcomes": {
                        "review": 1,
                        "not_adopted": 0,
                        "affected": 1,
                        "review_asset_ids": ["plot_thread:t1"],
                        "not_adopted_asset_ids": [],
                    }
                },
            }
        }
    )

    assert summary["by_kind"]["structure"] == {
        "adopted": 1,
        "review": 1,
        "not_adopted": 0,
    }
