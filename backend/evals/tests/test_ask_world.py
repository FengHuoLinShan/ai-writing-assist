import json
from pathlib import Path

from evals.ask_world import (
    DEFAULT_DATASET,
    load_ask_world_cases,
    run_ask_world_eval,
)


def test_committed_ask_world_launch_gate_passes() -> None:
    cases = load_ask_world_cases()
    report = run_ask_world_eval()

    assert report["ready"] is True
    assert report["quality_scope"] == "offline_evidence_ranking_and_dataset_integrity"
    assert report["metrics"] == {
        "visibility_leakage": 0.0,
        "source_hash_validity": 1.0,
        "citation_open_rate": 1.0,
        "p_at_5": 1.0,
        "no_answer_false_positive_rate": 0.0,
    }
    assert any(case.should_answer for case in cases)
    assert any(not case.should_answer for case in cases)
    blocked = {
        "ask-cross-project-evidence-blocked",
        "ask-role-only-evidence-blocked",
    }
    assert all(
        result["retrieved_source_keys"] == []
        for result in report["case_results"]
        if result["scenario_id"] in blocked
    )
    source = DEFAULT_DATASET.read_text(encoding="utf-8")
    assert "真名回响" not in source
    assert "/Users/" not in source


def test_ask_world_gate_fails_closed_for_bad_hash_and_missing_metrics(
    tmp_path: Path,
) -> None:
    rows = [json.loads(line) for line in DEFAULT_DATASET.read_text().splitlines()]
    rows[0]["sources"][0]["source_hash"] = "0" * 64
    tampered = tmp_path / "tampered.jsonl"
    tampered.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )
    report = run_ask_world_eval(tampered)
    assert report["ready"] is False
    assert "metric_failed:source_hash_validity" in report["failures"]
    assert "metric_failed:citation_open_rate" in report["failures"]

    no_answer_only = tmp_path / "no-answer-only.jsonl"
    no_answer_only.write_text(
        json.dumps(rows[-1], ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    report = run_ask_world_eval(no_answer_only)
    assert report["ready"] is False
    assert "metric_unavailable:p_at_5" in report["failures"]
    assert "metric_unavailable:source_hash_validity" in report["failures"]
    assert "metric_unavailable:citation_open_rate" in report["failures"]
