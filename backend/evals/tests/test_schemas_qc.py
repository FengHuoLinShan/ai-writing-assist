from __future__ import annotations

import hashlib
from pathlib import Path

from evals.corpus import ChapterSnapshot, CorpusSnapshot
from evals.qc import calibration_report, run_deterministic_qc
from evals.schemas import (
    DatasetCase,
    DatasetSplit,
    EvalSuite,
    HumanReview,
    LogicalSourceRef,
    RiskLevel,
    VisibilitySpec,
)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _corpus() -> CorpusSnapshot:
    return CorpusSnapshot(
        source_alias="fixture",
        file_hash=_hash("file"),
        byte_size=100,
        chapters=[
            ChapterSnapshot(
                chapter_index=1,
                title="第一章",
                start_offset=0,
                end_offset=50,
                content_hash=_hash("chapter-1"),
                source_group_id="group-1",
            ),
            ChapterSnapshot(
                chapter_index=2,
                title="第二章",
                start_offset=50,
                end_offset=100,
                content_hash=_hash("chapter-2"),
                source_group_id="group-1",
            ),
        ],
    )


def _ref(chapter: int) -> LogicalSourceRef:
    return LogicalSourceRef(
        corpus_id="lotm-clown-v1",
        source_alias="fixture",
        source_group_id="group-1",
        chapter_index=chapter,
        content_hash=_hash(f"chapter-{chapter}"),
    )


def _case(case_id: str, *, split: DatasetSplit, query: str) -> DatasetCase:
    return DatasetCase(
        case_id=case_id,
        suite=EvalSuite.rag,
        scenario="exact_name",
        source_group_id="group-1",
        source_refs=[_ref(1)],
        input={"query": query},
        reference={"answer": "答案", "context_ids": ["fixture:chapter:1"]},
        split=split,
    )


def test_qc_detects_duplicate_and_source_group_split_leakage() -> None:
    report = run_deterministic_qc(
        [
            _case("rag-0001", split=DatasetSplit.train, query="克莱恩是谁？"),
            _case("rag-0002", split=DatasetSplit.test, query="克莱恩是谁"),
        ],
        corpora={"fixture": _corpus()},
    )

    assert report["accepted_count"] == 0
    assert report["exact_duplicate_count"] == 1
    assert report["split_leakage_group_count"] == 1


def test_qc_allows_same_structural_input_with_distinct_references() -> None:
    left = _case("scene-0001", split=DatasetSplit.train, query="同一正文")
    right = _case("scene-0002", split=DatasetSplit.train, query="同一正文")
    left.suite = EvalSuite.scene
    right.suite = EvalSuite.scene
    left.scenario = "location_shift"
    right.scenario = "goal_shift"
    left.input = {"text": "同一正文"}
    right.input = {"text": "同一正文"}
    left.reference = {"boundary_offsets": [10]}
    right.reference = {"boundary_offsets": [20]}

    report = run_deterministic_qc(
        [left, right],
        corpora={"fixture": _corpus()},
    )

    assert report["exact_duplicate_count"] == 0
    assert "exact_duplicate_query" not in report["errors"].get(left.case_id, [])
    assert "exact_duplicate_query" not in report["errors"].get(right.case_id, [])


def test_qc_rejects_future_evidence_and_unreviewed_safety_case() -> None:
    case = _case("rag-safe-0001", split=DatasetSplit.test, query="未来发生什么")
    case = case.model_copy(
        update={
            "risk_level": RiskLevel.safety_critical,
            "source_refs": [_ref(2)],
            "visibility": VisibilitySpec(mode="reader", visible_until_chapter=1),
            "human_review": HumanReview(status="unreviewed"),
        }
    )

    report = run_deterministic_qc([case], corpora={"fixture": _corpus()})

    assert "future_evidence_leakage" in report["errors"][case.case_id]
    assert "safety_critical_requires_human_review" in report["errors"][case.case_id]


def test_qc_rejects_visibility_scenario_without_cutoff() -> None:
    case = _case("rag-safe-0002", split=DatasetSplit.test, query="截至当前章")
    case = case.model_copy(update={"scenario": "visibility_cutoff"})

    report = run_deterministic_qc([case], corpora={"fixture": _corpus()})

    assert "missing_visibility_cutoff" in report["errors"][case.case_id]


def test_calibration_report_controls_llm_blocking_gate() -> None:
    report = calibration_report(
        ["accept", "accept", "reject", "reject"],
        ["accept", "accept", "reject", "reject"],
        [1, 2, 3, 4],
        [1, 2, 3, 4],
    )

    assert report["llm_metrics_blocking"] is True


def test_qc_flags_source_copy_and_invalid_hard_negative() -> None:
    case = _case(
        "rag-source-0001",
        split=DatasetSplit.test,
        query="这是一条直接复制正文的很长查询文本",
    )
    case.reference["answer"] = "关键答案"
    case.hard_negative_refs = [_ref(2)]
    source = "这是一条直接复制正文的很长查询文本，关键答案就在这里。".ljust(
        50, "甲"
    ) + "容易混淆的章节也错误包含关键答案。".ljust(50, "乙")

    report = run_deterministic_qc(
        [case],
        corpora={"fixture": _corpus()},
        source_texts={"fixture": source},
    )

    assert "query_copies_source_text" in report["warnings"][case.case_id]
    assert "hard_negative_contains_reference_answer" in report["errors"][case.case_id]


def test_qc_validates_chapter_local_range_hash_and_reads_the_correct_chapter() -> None:
    first = "甲" * 50
    second = "乙" * 8 + "关键答案" + "乙" * 37
    source = first + second
    corpus = CorpusSnapshot(
        source_alias="fixture",
        file_hash=_hash(source),
        byte_size=len(source.encode()),
        chapters=[
            ChapterSnapshot(
                chapter_index=1,
                title="第一章",
                start_offset=0,
                end_offset=len(first),
                content_hash=_hash(first),
                source_group_id="group-1",
            ),
            ChapterSnapshot(
                chapter_index=2,
                title="第二章",
                start_offset=len(first),
                end_offset=len(source),
                content_hash=_hash(second),
                source_group_id="group-1",
            ),
        ],
    )
    start = second.index("关键答案")
    end = start + len("关键答案")
    case = _case("rag-range-0001", split=DatasetSplit.test, query="答案是什么")
    case.source_refs = [
        LogicalSourceRef(
            corpus_id="lotm-clown-v1",
            source_alias="fixture",
            source_group_id="group-1",
            chapter_index=2,
            content_hash=_hash(second),
            range_hash=_hash(second[start:end]),
            start_offset=start,
            end_offset=end,
        )
    ]
    case.reference["answer"] = "关键答案"

    report = run_deterministic_qc(
        [case],
        corpora={"fixture": corpus},
        source_texts={"fixture": source},
    )

    assert report["accepted_case_ids"] == [case.case_id]
    assert "reference_answer_not_verbatim" not in report["warnings"].get(case.case_id, [])

    unverified = run_deterministic_qc([case], corpora={"fixture": corpus})
    assert "source_text_missing:fixture" in unverified["errors"][case.case_id]


def test_qc_rejects_bad_chapter_local_bounds_and_range_hash() -> None:
    source = "甲" * 50 + "乙" * 50
    corpus = _corpus()
    bad_hash = _case("rag-range-hash", split=DatasetSplit.test, query="范围哈希")
    bad_hash.source_refs = [
        LogicalSourceRef.model_validate(
            _ref(2).model_dump()
            | {
                "range_hash": _hash("wrong"),
                "start_offset": 2,
                "end_offset": 8,
            }
        )
    ]
    bad_bounds = _case("rag-range-bounds", split=DatasetSplit.test, query="范围越界")
    bad_bounds.source_refs = [
        LogicalSourceRef.model_validate(
            _ref(2).model_dump()
            | {
                "range_hash": _hash("still-wrong"),
                "start_offset": 45,
                "end_offset": 60,
            }
        )
    ]

    report = run_deterministic_qc(
        [bad_hash, bad_bounds],
        corpora={"fixture": corpus},
        source_texts={"fixture": source},
    )

    assert "range_hash_mismatch:2" in report["errors"][bad_hash.case_id]
    assert "range_out_of_bounds:2" in report["errors"][bad_bounds.case_id]


def test_committed_fast_dataset_covers_all_suites() -> None:
    dataset_path = (
        Path(__file__).resolve().parents[1] / "datasets" / "baselines" / "fast-v1.jsonl"
    )
    cases = [
        DatasetCase.model_validate_json(line)
        for line in dataset_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert len(cases) == 4
    assert {case.suite for case in cases} == set(EvalSuite)
