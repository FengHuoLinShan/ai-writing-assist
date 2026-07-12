from __future__ import annotations

from pathlib import Path

import pytest

from evals.corpus import (
    build_corpus_snapshot,
    build_fixture_source_snapshot,
    source_group_id,
)
from evals.metrics import (
    boundary_counts,
    cohens_kappa,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
    spearman_rho,
)


def test_corpus_snapshot_parses_chapters_without_storing_text(tmp_path: Path) -> None:
    path = tmp_path / "novel.txt"
    path.write_text(
        "序言\n第一章 开始\n甲乙丙\n第二章 转折\n丁戊己\n",
        encoding="utf-8",
    )

    snapshot = build_corpus_snapshot(path, source_alias="fixture")

    assert [item.title for item in snapshot.chapters] == ["第一章 开始", "第二章 转折"]
    assert snapshot.chapters[0].content_hash != snapshot.chapters[1].content_hash
    assert "甲乙丙" not in snapshot.model_dump_json()
    assert source_group_id(1) == source_group_id(5)
    assert source_group_id(6) != source_group_id(5)


def test_fixture_source_snapshot_covers_modules_without_payloads() -> None:
    snapshot = build_fixture_source_snapshot()

    assert {entry.module for entry in snapshot.entries} == {
        "writing",
        "outline",
        "world",
    }
    assert len({entry.logical_id for entry in snapshot.entries}) == len(snapshot.entries)
    assert all(not entry.relative_path.startswith("/") for entry in snapshot.entries)
    serialized = snapshot.model_dump_json()
    assert "synthetic-ten-chapters" in serialized
    assert "测试正文" not in serialized


def test_retrieval_metrics_have_expected_values() -> None:
    retrieved = ["wrong", "right", "also-right"]
    relevant = {"right", "also-right"}

    assert precision_at_k(retrieved, relevant, 2) == 0.5
    assert recall_at_k(retrieved, relevant, 2) == 0.5
    assert reciprocal_rank(retrieved, relevant) == 0.5
    assert 0 < ndcg_at_k(retrieved, relevant, 3) < 1


def test_boundary_and_calibration_metrics() -> None:
    assert boundary_counts([100, 500], [120, 900], tolerance=50) == (1, 1, 1)
    assert cohens_kappa(["yes", "yes", "no"], ["yes", "yes", "no"]) == 1.0
    assert spearman_rho([1, 2, 3], [10, 20, 30]) == pytest.approx(1.0)
