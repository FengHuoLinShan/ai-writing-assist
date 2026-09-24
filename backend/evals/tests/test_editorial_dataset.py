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
            assert hashlib.sha256(chapter["content"].encode()).hexdigest() == chapter[
                "content_sha256"
            ]
