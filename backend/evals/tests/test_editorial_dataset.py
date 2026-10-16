"""Frozen editorial samples must keep their wording and evaluation strata."""

import hashlib
import json
from pathlib import Path


def test_editorial_samples_are_frozen_and_cover_risky_judgments():
    path = Path(__file__).parents[1] / "datasets" / "editorial_cases.json"
    cases = json.loads(path.read_text(encoding="utf-8"))["cases"]
    assert {case["stratum"] for case in cases} == {
        "explicit_error",
        "multiple_explanations",
        "intentional_gap",
        "no_major_issue",
    }
    assert {case["scope"] for case in cases} == {"book", "range"}
    for case in cases:
        assert case["evaluation_focus"]
        for chapter in [*case["chapters"], *case.get("revised_chapters", [])]:
            assert (
                hashlib.sha256(chapter["content"].encode()).hexdigest()
                == chapter["content_sha256"]
            )


def test_editorial_v2_preserves_v1_and_hashes_all_synthetic_cases():
    datasets = Path(__file__).parents[1] / "datasets"
    v1 = json.loads((datasets / "editorial_cases.json").read_text(encoding="utf-8"))
    v2 = json.loads((datasets / "editorial_cases_v2.json").read_text(encoding="utf-8"))
    cases = v2["cases"]
    ids = [case["id"] for case in cases]
    new_ids = {
        "S01_hard_contradiction",
        "S02_unreliable_narrator",
        "S03_causal_gap",
        "S04_causal_setup_control",
        "S05_comprehension_friction",
        "S06_understood_but_disliked",
        "S07_goal_mismatch",
        "S08_no_arc_open_ending",
        "S09_taste_slow_town",
        "S10_sparse_style_control",
        "S11_unsolicited_ethics_control",
        "S12_countervoice_control",
        "S13_clue_early",
        "S13_clue_middle",
        "S14_knowledge_unconfirmed",
        "S14_knowledge_confirmed_control",
        "S15_external_fact_pending",
        "S16_duplicate_domain_finding",
        "S17_serialized_chapter_no_hook",
    }

    assert v2["version"] == 2
    assert "original synthetic Chinese fiction" in v2["provenance"]
    assert cases[: len(v1["cases"])] == v1["cases"]
    assert len(cases) == len(v1["cases"]) + len(new_ids)
    assert len(ids) == len(set(ids))
    assert set(ids[len(v1["cases"]) :]) == new_ids
    assert all("mismatch_type" not in case for case in cases)

    for case in cases[len(v1["cases"]) :]:
        assert case["evaluation_focus"]
        assert 1 <= len(case["chapters"]) <= 3
        if "scope_note" in case:
            assert case["scope_note"]
        for chapter in [*case["chapters"], *case.get("revised_chapters", [])]:
            assert (
                hashlib.sha256(chapter["content"].encode()).hexdigest()
                == chapter["content_sha256"]
            )


def test_editorial_v3_preserves_frozen_versions_and_balances_positive_controls():
    datasets = Path(__file__).parents[1] / "datasets"
    v2 = json.loads((datasets / "editorial_cases_v2.json").read_text(encoding="utf-8"))
    v3 = json.loads((datasets / "editorial_cases_v3.json").read_text(encoding="utf-8"))
    v2_cases = {case["id"]: case for case in v2["cases"]}
    cases = v3["cases"]
    by_id = {case["id"]: case for case in cases}
    positive_controls = {
        "S02_objective_record_conflict",
        "S08_mystery_promise_unfulfilled",
        "S09_revenge_promise_unfulfilled",
        "S17_serialized_promise_abandoned",
        "S19_active_goal_passivity_mismatch",
    }

    assert v3["version"] == 3
    assert len(cases) == 29
    assert len(by_id) == len(cases)
    assert set(v3["expected_result_values"]) == {"report", "no_report", "unchecked"}
    assert {case["expected_result"] for case in cases} <= set(
        v3["expected_result_values"]
    )
    assert sum(case["expected_result"] == "report" for case in cases) == 11
    assert sum(case["expected_result"] == "no_report" for case in cases) == 17
    assert sum(case["expected_result"] == "unchecked" for case in cases) == 1
    assert set(by_id) - set(v2_cases) == positive_controls | {
        "S18_intentional_passive_character_control"
    }
    for case_id, old_case in v2_cases.items():
        current = dict(by_id[case_id])
        current.pop("expected_result")
        if case_id == "S01_hard_contradiction":
            assert current != old_case
            assert "铜钥匙" not in "".join(
                chapter["content"] for chapter in current["chapters"]
            )
            assert "左手" in "".join(
                chapter["content"] for chapter in current["chapters"]
            )
        else:
            assert current == old_case
    assert all(
        by_id[case_id]["expected_result"] == "report" for case_id in positive_controls
    )
    assert (
        by_id["S18_intentional_passive_character_control"]["expected_result"]
        == "no_report"
    )

    for case in cases:
        assert 1 <= len(case["chapters"]) <= 3
        assert case["evaluation_focus"]
        for chapter in [*case["chapters"], *case.get("revised_chapters", [])]:
            assert (
                hashlib.sha256(chapter["content"].encode()).hexdigest()
                == chapter["content_sha256"]
            )
