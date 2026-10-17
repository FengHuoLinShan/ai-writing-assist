"""Frozen editorial samples must keep their wording and evaluation strata."""

import copy
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


def test_editorial_v4_preserves_frozen_hashes_and_adds_cross_chapter_cases():
    datasets = Path(__file__).parents[1] / "datasets"
    frozen_hashes = {
        "editorial_cases.json": (
            "c6c874c8af2ed1b952c11c9ae889c00300dae6dfab6d102488d7f99d3f3a75b8"
        ),
        "editorial_cases_v2.json": (
            "a448a0651cd61a34652e4974134cf2db1e268af1408c7b931c1c108b57c0c268"
        ),
        "editorial_cases_v3.json": (
            "9aeb7180aef575d00180a1ae139fefa5febdcf65456f91126cdfed1a980bcd31"
        ),
    }
    for filename, expected_hash in frozen_hashes.items():
        actual_hash = hashlib.sha256((datasets / filename).read_bytes()).hexdigest()
        assert actual_hash == expected_hash

    v3 = json.loads((datasets / "editorial_cases_v3.json").read_text(encoding="utf-8"))
    v4 = json.loads((datasets / "editorial_cases_v4.json").read_text(encoding="utf-8"))
    cases = v4["cases"]
    by_id = {case["id"]: case for case in cases}
    added = {
        "X01_timeline_conflict",
        "X01_timeline_rescheduled_control",
        "X02_identity_relation_conflict",
        "X02_adoption_explained_control",
        "X03_remote_object_state_conflict",
        "X03_object_repaired_control",
    }
    assert v4["version"] == 4
    assert len(cases) == 35 and len(by_id) == len(cases)
    assert sum(case["expected_result"] == "report" for case in cases) == 14
    assert sum(case["expected_result"] == "no_report" for case in cases) == 20
    assert sum(case["expected_result"] == "unchecked" for case in cases) == 1
    assert set(by_id) - {case["id"] for case in v3["cases"]} == added

    for old_case in v3["cases"]:
        expected = copy.deepcopy(old_case)
        if expected["id"] == "S09_revenge_promise_unfulfilled":
            expected["chapters"][1]["content"] = (
                "末班车停了半分钟，没有乘客下来。杜师傅关掉门外的灯，留下柜台上方的黄灯。"
                "天亮时，他把仍未写上纵火者姓名的追查簿合上，锁回柜台，独自等送奶车。"
            )
            expected["chapters"][1]["content_sha256"] = hashlib.sha256(
                expected["chapters"][1]["content"].encode()
            ).hexdigest()
        elif expected["id"] == "S18_intentional_passive_character_control":
            expected["chapters"][0]["content"] = (
                "值夜人莲生守在内门。交班规定：双铃响过才可离岗；若等到天亮仍无第二声铃，"
                "就登记缺铃并把值簿交给继任者，完成交班后回值房。远处传来一声短铃，"
                "他记下时辰，继续等第二声。"
            )
            expected["chapters"][1]["content"] = (
                "第二声铃始终没有响。天亮后，莲生在簿上登记“缺铃”，把值簿递给继任者；"
                "对方当面接过并签名，莲生照章回到值房。门外的人群散去，制度没有改变。"
            )
            for chapter in expected["chapters"]:
                chapter["content_sha256"] = hashlib.sha256(
                    chapter["content"].encode()
                ).hexdigest()
        assert by_id[expected["id"]] == expected

    remote = by_id["X03_remote_object_state_conflict"]["chapters"]
    assert [chapter["index"] for chapter in remote] == [1, 2, 3]
    assert "航标牌" not in remote[1]["content"]
    assert "六月初三" in "".join(
        chapter["content"] for chapter in by_id["X01_timeline_conflict"]["chapters"]
    )
    assert all(
        case["expected_result"] == "report"
        for case in (
            by_id["X01_timeline_conflict"],
            by_id["X02_identity_relation_conflict"],
            by_id["X03_remote_object_state_conflict"],
        )
    )
    assert all(
        case["expected_result"] == "no_report"
        for case in (
            by_id["X01_timeline_rescheduled_control"],
            by_id["X02_adoption_explained_control"],
            by_id["X03_object_repaired_control"],
        )
    )
    for case in cases:
        assert case["evaluation_focus"]
        for chapter in case["chapters"]:
            assert hashlib.sha256(chapter["content"].encode()).hexdigest() == chapter[
                "content_sha256"
            ]
    s09_last_chapter = by_id["S09_revenge_promise_unfulfilled"]["chapters"][1][
        "content"
    ]
    s18_first_chapter = by_id["S18_intentional_passive_character_control"][
        "chapters"
    ][0]["content"]
    assert "全文没有找到" not in s09_last_chapter
    assert "完成交班后回值房" in s18_first_chapter
