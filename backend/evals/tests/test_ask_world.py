import json
from pathlib import Path

from evals.ask_world import (
    DEFAULT_DATASET,
    load_ask_world_cases,
    run_ask_world_eval,
)

FORBIDDEN_TERMS = (
    "真名回响",
    "/Users/",
    "白堤",
    "折光塔",
    "三河根桥",
    "远誓塔",
    "千阶城",
    "淤泥理想主义者",
    "太一",
    "理法之环",
)

# Every committed negative case must produce an empty evidence packet.
MUST_STAY_EMPTY = {
    "ask-no-evidence",
    "ask-cross-project-evidence-blocked",
    "ask-role-only-evidence-blocked",
    "ask-fog-lake-fish-count",
    "ask-dawn-road-reorder-date",
    "ask-reader-only-evidence-blocked",
    "ask-same-name-cross-novel",
}


def _dataset_rows() -> list[dict]:
    return [
        json.loads(line)
        for line in DEFAULT_DATASET.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _write_dataset(tmp_path: Path, rows: list[dict], name: str) -> Path:
    path = tmp_path / name
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )
    return path


def test_committed_ask_world_launch_gate_passes() -> None:
    cases = load_ask_world_cases()
    report = run_ask_world_eval()

    assert report["ready"] is True
    assert report["quality_scope"] == "offline_evidence_ranking_and_dataset_integrity"
    metrics = report["metrics"]
    assert metrics["source_hash_validity"] == 1.0
    assert metrics["citation_open_rate"] == 1.0
    assert metrics["p_at_5"] >= 0.8
    assert metrics["no_answer_false_positive_rate"] <= 0.05
    assert any(case.should_answer for case in cases)
    assert any(not case.should_answer for case in cases)
    assert all(
        result["retrieved_source_keys"] == []
        for result in report["case_results"]
        if result["scenario_id"] in MUST_STAY_EMPTY
    )
    source = DEFAULT_DATASET.read_text(encoding="utf-8")
    for forbidden in FORBIDDEN_TERMS:
        assert forbidden not in source


def test_ask_world_gate_fails_closed_for_bad_hash_and_missing_metrics(
    tmp_path: Path,
) -> None:
    rows = _dataset_rows()
    rows[0]["sources"][0]["source_hash"] = "0" * 64
    tampered = _write_dataset(tmp_path, rows, "tampered.jsonl")
    report = run_ask_world_eval(tampered)
    assert report["ready"] is False
    assert "metric_failed:source_hash_validity" in report["failures"]
    assert "metric_failed:citation_open_rate" in report["failures"]

    # The last committed row is a negative case: p@5 has no answerable input,
    # and with no retrieval there is no citation denominator. Hash validity is
    # still available because the tightened runner checks every eligible
    # source, not only ranked ones.
    no_answer_only = tmp_path / "no-answer-only.jsonl"
    no_answer_only.write_text(
        json.dumps(rows[-1], ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    report = run_ask_world_eval(no_answer_only)
    assert report["ready"] is False
    assert report["metrics"]["source_hash_validity"] == 1.0
    assert "metric_unavailable:p_at_5" in report["failures"]
    assert "metric_unavailable:citation_open_rate" in report["failures"]


def test_ask_world_gate_rejects_false_answers(
    tmp_path: Path,
) -> None:
    """A negative case that becomes answerable must turn the gate red."""
    cross = next(
        row
        for row in _dataset_rows()
        if row["scenario_id"] == "ask-cross-project-evidence-blocked"
    )
    # Simulate the eligible filter being bypassed: the foreign answer page now
    # claims the case novel. It is retrieved and the no-answer case is wrongly
    # answered, so the false-positive gate fails closed.
    cross["sources"][0]["novel_id"] = cross["novel_id"]
    report = run_ask_world_eval(
        _write_dataset(tmp_path, [cross], "cross-novel-bypass.jsonl")
    )
    assert report["ready"] is False
    assert report["metrics"]["no_answer_false_positive_rate"] > 0.05

    role = next(
        row
        for row in _dataset_rows()
        if row["scenario_id"] == "ask-role-only-evidence-blocked"
    )
    # Simulate the visibility filter being bypassed: a role-only source now
    # passes the author filter and is wrongly retrieved as answer evidence.
    role["sources"][0]["visibility"] = "author"
    report = run_ask_world_eval(
        _write_dataset(tmp_path, [role], "role-visibility-bypass.jsonl")
    )
    assert report["ready"] is False
    assert report["metrics"]["no_answer_false_positive_rate"] > 0.05


def test_ask_world_rejects_bad_hash_on_low_score_distractor(
    tmp_path: Path,
) -> None:
    """Hash integrity covers every eligible source, not only ranked ones."""
    rows = _dataset_rows()
    for source in rows[0]["sources"]:
        if source["key"] == "page:orchard":
            source["source_hash"] = "0" * 64
    report = run_ask_world_eval(
        _write_dataset(tmp_path, rows, "low-score-tampered.jsonl")
    )
    assert report["ready"] is False
    assert report["metrics"]["source_hash_validity"] < 1.0
    assert "metric_failed:source_hash_validity" in report["failures"]


def test_ask_world_rejects_openable_source_without_open_hash(
    tmp_path: Path,
) -> None:
    """An openable retrieved source with a missing open_hash fails reopening."""
    rows = _dataset_rows()
    rows[0]["sources"][0]["open_hash"] = None
    report = run_ask_world_eval(
        _write_dataset(tmp_path, rows, "open-hash-missing.jsonl")
    )
    assert report["ready"] is False
    assert report["metrics"]["citation_open_rate"] < 1.0
    assert "metric_failed:citation_open_rate" in report["failures"]


def test_committed_ask_world_dataset_structure() -> None:
    cases = load_ask_world_cases()
    assert len(cases) == 23
    assert sum(case.should_answer for case in cases) == 16
    assert sum(not case.should_answer for case in cases) == 7


def test_ask_world_density_case_survives_rank_budget() -> None:
    """The densest interference case keeps all relevant keys inside top-5."""
    report = run_ask_world_eval()
    case = next(
        result
        for result in report["case_results"]
        if result["scenario_id"] == "ask-bell-density-8"
    )
    relevant = {
        "object:bell",
        "manuscript:guard-rotation",
        "page:tower-rules",
        "manuscript:bell-ledger",
        "object:guard-room-key",
    }
    assert set(case["retrieved_source_keys"]) == relevant


def test_ask_world_model_probes_blocklist() -> None:
    probes = DEFAULT_DATASET.parent / "ask-world-model-probes-v1.jsonl"
    source = probes.read_text(encoding="utf-8")
    for forbidden in FORBIDDEN_TERMS:
        assert forbidden not in source

