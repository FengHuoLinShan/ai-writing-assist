import asyncio
import hashlib
import json
from collections import Counter
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from evals.ask_world import (
    _ASK_WORLD_SYSTEM_PROMPT,
    _ASK_WORLD_TEACHER_RUBRIC,
    ASK_WORLD_TEACHER_MODEL,
    DEFAULT_DATASET,
    MODEL_PROBE_DATASET,
    AskWorldEvalCase,
    AskWorldTeacherDecision,
    _code_provenance,
    _holdout_material_sha,
    _validate_holdout_freeze,
    evaluate_ask_world_model_cases,
    evaluate_ask_world_teacher_calibration,
    load_ask_world_cases,
    run_ask_world_eval,
    run_ask_world_model_probe_eval,
    summarize_ask_world_semantic_review,
)
from evals.ask_world import main as ask_world_main
from evals.codex_executor import CodexStructuredExecutor
from modules.world.llm_schemas import GeneratedAskWorldClaim, GeneratedAskWorldOutput

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
    report = run_ask_world_eval(_write_dataset(tmp_path, rows, "open-hash-missing.jsonl"))
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
    source = MODEL_PROBE_DATASET.read_text(encoding="utf-8")
    for forbidden in FORBIDDEN_TERMS:
        assert forbidden not in source


def test_ask_world_model_probe_dataset_structure() -> None:
    cases = load_ask_world_cases(MODEL_PROBE_DATASET)

    assert len(cases) == 7
    assert sum(case.should_answer for case in cases) == 3
    assert sum(not case.should_answer for case in cases) == 4
    assert {case.scenario_id for case in cases if case.source_conflict} == {
        "ask-probe-bridge-closure-conflict",
        "ask-probe-archive-stale",
        "ask-probe-ferry-toll-conflict",
    }


PROBE_V2 = MODEL_PROBE_DATASET.parent / "ask-world-model-probes-v2.jsonl"
PROBE_V3 = MODEL_PROBE_DATASET.parent / "ask-world-model-probes-v3.jsonl"


def test_probe_v3_holdout_does_not_reuse_exposed_teacher_families() -> None:
    cases = load_ask_world_cases(PROBE_V3)
    original = load_ask_world_cases(PROBE_V2)
    exposed = {
        "copper-hill",
        "kiln-street",
        "harvest-festival",
        "river-mouth-treaty",
        "mist-river",
        "windmill-hill",
    }
    assert len(cases) == 46
    assert len({case.scenario_id for case in cases}) == len(cases)
    debug = [case for case in cases if case.split == "debug"]
    holdout = [case for case in cases if case.split == "holdout"]
    assert len(debug) == 34
    assert len(holdout) == 12
    assert {case.family for case in debug}.isdisjoint(case.family for case in holdout)
    assert exposed.isdisjoint(case.family for case in holdout)
    assert {case.stratum for case in holdout} == {case.stratum for case in cases}
    untouched = {
        case.scenario_id: case
        for case in original
        if case.split == "holdout" and case.family not in exposed
    }
    for case in holdout:
        if case.scenario_id in untouched:
            assert case == untouched[case.scenario_id]
    for case in cases:
        for source in case.sources:
            assert (
                source.source_hash == hashlib.sha256(source.content.encode()).hexdigest()
            )


def test_probe_v3_does_not_conflate_custodian_and_location() -> None:
    case = next(
        case
        for case in load_ask_world_cases(PROBE_V3)
        if case.scenario_id == "ask-probe-archive-stale"
    )
    assert not case.source_conflict
    assert case.stratum == "multi_source"
    assert len(case.relevant_source_keys) == 2


def _freeze_fixture(tmp_path, dataset=PROBE_V3):
    cases = load_ask_world_cases(dataset)

    def sha(content):
        return hashlib.sha256(content).hexdigest()

    dataset_hash = sha(dataset.read_bytes())
    rubric_hash = sha(_ASK_WORLD_TEACHER_RUBRIC.encode())
    executor_hash = CodexStructuredExecutor(
        model=ASK_WORLD_TEACHER_MODEL,
        reasoning_effort="high",
        allowed_models=frozenset({ASK_WORLD_TEACHER_MODEL}),
    ).meta.executor_hash
    system_under_test = {
        "provider_id": "test-provider",
        "model": "test-model",
        "profile_hash": "a" * 64,
    }
    teacher_meta = {
        "teacher_model": ASK_WORLD_TEACHER_MODEL,
        "reasoning_effort": "high",
        "executor_hash": executor_hash,
        "rubric_hash": rubric_hash,
    }
    debug_cases = [case for case in cases if case.split == "debug"]
    debug = {
        "complete": True,
        "split": "debug",
        "case_count": len(debug_cases),
        "dataset_sha256": dataset_hash,
        "holdout_material_sha256": _holdout_material_sha(cases),
        "provenance": {"system_prompt_sha256": sha(_ASK_WORLD_SYSTEM_PROMPT.encode())},
        "system_under_test": system_under_test,
        "case_results": [{"scenario_id": case.scenario_id} for case in debug_cases],
        "semantic_review": {"available": True},
        "teacher_calibration": {
            **teacher_meta,
            "metrics": {"reference_acceptance_rate": 1.0, "ambiguous_count": 0},
        },
    }
    selftest = {
        "all_expected_matched": True,
        "dataset_sha256": dataset_hash,
        "teacher": teacher_meta,
    }
    config = {
        "review_ready": True,
        "dataset_sha256": dataset_hash,
        "holdout_material_sha256": _holdout_material_sha(cases),
        "system_prompt_sha256": sha(_ASK_WORLD_SYSTEM_PROMPT.encode()),
        "rubric_sha256": rubric_hash,
        "runner_sha256": sha(
            Path(run_ask_world_model_probe_eval.__code__.co_filename).read_bytes()
        ),
        "teacher_model": ASK_WORLD_TEACHER_MODEL,
        "teacher_reasoning_effort": "high",
        "teacher_executor_hash": executor_hash,
        "system_under_test": system_under_test,
    }
    for name, result in (("debug_report", debug), ("teacher_selftest", selftest)):
        path = tmp_path / (name + ".json")
        path.write_text(json.dumps(result))
        config[name] = {"path": str(path), "sha256": sha(path.read_bytes())}
    freeze = tmp_path / "freeze.json"
    freeze.write_text(json.dumps(config))
    return freeze, config


def test_holdout_freeze_rejects_missing_stale_or_incomplete_evidence(tmp_path):
    with pytest.raises(ValueError, match="requires --freeze-config"):
        _validate_holdout_freeze(PROBE_V3, None)
    freeze, config = _freeze_fixture(tmp_path)
    assert _validate_holdout_freeze(PROBE_V3, freeze)["review_ready"]
    config["rubric_sha256"] = "0" * 64
    freeze.write_text(json.dumps(config))
    with pytest.raises(ValueError, match="does not match"):
        _validate_holdout_freeze(PROBE_V3, freeze)
    freeze, config = _freeze_fixture(tmp_path)
    debug_path = Path(config["debug_report"]["path"])
    debug = json.loads(debug_path.read_text())
    debug["case_results"].pop()
    debug_path.write_text(json.dumps(debug))
    with pytest.raises(ValueError, match="evidence changed"):
        _validate_holdout_freeze(PROBE_V3, freeze)
    config["debug_report"]["sha256"] = hashlib.sha256(debug_path.read_bytes()).hexdigest()
    freeze.write_text(json.dumps(config))
    with pytest.raises(ValueError, match="complete matching debug"):
        _validate_holdout_freeze(PROBE_V3, freeze)


def test_holdout_cannot_start_twice_even_when_first_attempt_fails_before_model_access(
    monkeypatch, tmp_path
):
    monkeypatch.setattr("evals.ask_world._HOLDOUT_RUNS", tmp_path / "canonical-runs")
    freeze, _ = _freeze_fixture(tmp_path)
    calls = []

    def init(_self):
        calls.append("database")
        raise RuntimeError("deliberately unavailable test database")

    monkeypatch.setattr("core.database.DatabaseManager.init", init)
    args = {
        "split": "holdout",
        "teacher_model": ASK_WORLD_TEACHER_MODEL,
        "teacher_reasoning_effort": "high",
        "freeze_config": freeze,
    }
    with pytest.raises(RuntimeError, match="deliberately unavailable"):
        asyncio.run(run_ask_world_model_probe_eval("novel-a", PROBE_V3, **args))
    copied = tmp_path / "new-directory" / "freeze.json"
    copied.parent.mkdir()
    copied.write_bytes(freeze.read_bytes())
    args["freeze_config"] = copied
    with pytest.raises(ValueError, match="already started"):
        asyncio.run(run_ask_world_model_probe_eval("novel-a", PROBE_V3, **args))
    rows = [json.loads(line) for line in PROBE_V3.read_text().splitlines()]
    next(row for row in rows if row["split"] == "debug")["question"] += "（仅改调试问法）"
    changed_debug = tmp_path / "debug-changed.jsonl"
    changed_debug.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
    )
    changed_freeze, _ = _freeze_fixture(tmp_path, changed_debug)
    args["freeze_config"] = changed_freeze
    with pytest.raises(ValueError, match="already started"):
        asyncio.run(run_ask_world_model_probe_eval("novel-a", changed_debug, **args))
    assert calls == ["database"]


def test_partitioned_dataset_cannot_consume_holdout_by_omitting_split(monkeypatch):
    def init(_self):
        raise AssertionError("implicit holdout must fail before database access")

    monkeypatch.setattr("core.database.DatabaseManager.init", init)
    with pytest.raises(ValueError, match="require --split"):
        asyncio.run(run_ask_world_model_probe_eval("novel-a", PROBE_V3))


@pytest.mark.parametrize(
    "report_name,section,field",
    [
        ("debug_report", "provenance", "system_prompt_sha256"),
        ("debug_report", "system_under_test", "profile_hash"),
        ("debug_report", "teacher_calibration", "reasoning_effort"),
        ("debug_report", "teacher_calibration", "executor_hash"),
        ("teacher_selftest", "teacher", "teacher_model"),
        ("teacher_selftest", "teacher", "reasoning_effort"),
        ("teacher_selftest", "teacher", "executor_hash"),
    ],
)
def test_holdout_checks_actual_debug_and_selftest_parameters(
    tmp_path, report_name, section, field
):
    freeze, config = _freeze_fixture(tmp_path)
    report_path = Path(config[report_name]["path"])
    report = json.loads(report_path.read_text())
    report[section][field] = "other"
    report_path.write_text(json.dumps(report))
    config[report_name]["sha256"] = hashlib.sha256(report_path.read_bytes()).hexdigest()
    freeze.write_text(json.dumps(config))
    with pytest.raises(ValueError, match="complete matching debug"):
        _validate_holdout_freeze(PROBE_V3, freeze)


def test_probe_project_lookup_uses_a_read_only_postgresql_transaction(monkeypatch):
    statements = []

    class Session:
        async def execute(self, statement):
            statements.append(str(statement))

        async def commit(self):
            pass

        def in_transaction(self):
            return False

    class Manager:
        engine = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

        def init(self):
            pass

        @asynccontextmanager
        async def session_factory(self):
            yield Session()

        async def close(self):
            pass

    @asynccontextmanager
    async def client(db, novel_id, **kwargs):
        assert statements == ["SET TRANSACTION READ ONLY"]
        yield SimpleNamespace(model_name="test-model", profile_summary={})

    async def generate(_self, _client, _data, _sources, **kwargs):
        return GeneratedAskWorldOutput(answer="证据不足", no_answer=True)

    monkeypatch.setattr("core.database.DatabaseManager", Manager)
    monkeypatch.setattr("modules.project.facade.open_project_llm_client", client)
    monkeypatch.setattr("evals.ask_world.AskWorldService._generate", generate)
    assert asyncio.run(run_ask_world_model_probe_eval("novel-a"))["complete"]
    assert statements == ["SET TRANSACTION READ ONLY"]


def test_ask_world_model_probe_v2_is_a_stratified_candidate_set() -> None:
    cases = load_ask_world_cases(PROBE_V2)
    v1 = {case.scenario_id: case for case in load_ask_world_cases(MODEL_PROBE_DATASET)}

    assert len(cases) == 40
    assert len({case.scenario_id for case in cases}) == 40
    assert sum(case.should_answer for case in cases) == 24
    assert Counter(case.stratum for case in cases) == {
        "single_source": 7,
        "multi_source": 6,
        "conflict": 7,
        "near_miss": 9,
        "scope_excluded": 4,
        "injection_distractor": 7,
    }
    assert all(case.family and case.split for case in cases)
    # Conflict is declared by data, never inferred from the number of sources.
    assert {case.scenario_id for case in cases if case.source_conflict} == {
        case.scenario_id for case in cases if case.stratum == "conflict"
    }
    assert any(
        len(case.relevant_source_keys) > 1 and not case.source_conflict for case in cases
    )
    # The seven earlier probes are regression anchors: unchanged and debug-only.
    by_id = {case.scenario_id: case for case in cases}
    for scenario_id, anchor in v1.items():
        assert by_id[scenario_id].split == "debug"
        assert by_id[scenario_id].model_dump(
            include={"question", "should_answer", "relevant_source_keys", "sources"}
        ) == anchor.model_dump(
            include={"question", "should_answer", "relevant_source_keys", "sources"}
        )


def test_ask_world_model_probe_v2_splits_by_source_family() -> None:
    cases = load_ask_world_cases(PROBE_V2)
    splits_by_family: dict[str, set[str]] = {}
    for case in cases:
        splits_by_family.setdefault(str(case.family), set()).add(str(case.split))

    assert all(len(splits) == 1 for splits in splits_by_family.values())
    holdout = [case for case in cases if case.split == "holdout"]
    assert len(holdout) == 12
    assert {case.stratum for case in holdout} == {case.stratum for case in cases}
    assert any(case.should_answer for case in holdout)
    assert any(not case.should_answer for case in holdout)


def test_ask_world_model_probe_v2_scope_cases_keep_the_answer_out_of_reach() -> None:
    for case in load_ask_world_cases(PROBE_V2):
        if case.stratum != "scope_excluded":
            continue
        eligible = [
            source
            for source in case.sources
            if source.novel_id == case.novel_id and source.visibility == "author"
        ]
        # The model still sees adjacent evidence, so it is genuinely asked.
        assert eligible and len(eligible) < len(case.sources)
        assert not case.should_answer


def test_ask_world_model_probe_v2_is_synthetic_and_scores_end_to_end() -> None:
    source = PROBE_V2.read_text(encoding="utf-8")
    for forbidden in FORBIDDEN_TERMS:
        assert forbidden not in source

    cases = load_ask_world_cases(PROBE_V2)

    async def oracle(case):
        if not case.should_answer:
            return GeneratedAskWorldOutput(answer="证据不足。", no_answer=True)
        return (
            _conflict_answer(case)
            if case.source_conflict
            else GeneratedAskWorldOutput(
                answer="依据来源可答。",
                claims=[
                    GeneratedAskWorldClaim(
                        text="结论。", citation_keys=case.relevant_source_keys
                    )
                ],
            )
        )

    report = asyncio.run(evaluate_ask_world_model_cases(cases, oracle))

    assert report["metrics"]["deterministic_pass_rate"] == 1.0
    assert report["by_stratum"] == {
        "conflict": {"case_count": 7, "deterministic_passed": 7},
        "injection_distractor": {"case_count": 7, "deterministic_passed": 7},
        "multi_source": {"case_count": 6, "deterministic_passed": 6},
        "near_miss": {"case_count": 9, "deterministic_passed": 9},
        "scope_excluded": {"case_count": 4, "deterministic_passed": 4},
        "single_source": {"case_count": 7, "deterministic_passed": 7},
    }


def test_model_probe_run_rejects_a_split_the_dataset_does_not_have() -> None:
    with pytest.raises(ValueError, match="no holdout cases"):
        asyncio.run(
            run_ask_world_model_probe_eval(
                "novel-a", MODEL_PROBE_DATASET, split="holdout"
            )
        )


def test_ask_world_source_conflict_needs_two_relevant_sources() -> None:
    row = next(
        item for item in _dataset_rows() if item["scenario_id"] == "ask-bell-density-8"
    )
    row["source_conflict"] = True
    row["relevant_source_keys"] = row["relevant_source_keys"][:1]

    with pytest.raises(ValueError, match="at least two relevant sources"):
        AskWorldEvalCase.model_validate(row)


def _probe(scenario_id: str) -> AskWorldEvalCase:
    return next(
        case
        for case in load_ask_world_cases(MODEL_PROBE_DATASET)
        if case.scenario_id == scenario_id
    )


def _conflict_answer(
    case: AskWorldEvalCase,
    *,
    keys: list[str] | None = None,
    uncertainty: str = "需要作者决定采用哪一版。",
) -> GeneratedAskWorldOutput:
    return GeneratedAskWorldOutput(
        answer="来源存在冲突。",
        claims=[
            GeneratedAskWorldClaim(
                text="两份来源给出了不同说法。",
                citation_keys=keys or case.relevant_source_keys,
            )
        ],
        uncertainty=uncertainty,
    )


def _deterministic(case: AskWorldEvalCase, output: GeneratedAskWorldOutput) -> dict:
    async def generate(_case):
        return output

    report = asyncio.run(evaluate_ask_world_model_cases([case], generate))
    return report["case_results"][0]


def _review(
    case: AskWorldEvalCase,
    output: GeneratedAskWorldOutput,
    **overrides,
) -> AskWorldTeacherDecision:
    values = {
        "scenario_id": case.scenario_id,
        "reference_verdict": "accept",
        "model_verdict": "pass",
        "answerability_justified": True,
        "claims": [
            {"claim_index": index, "supported": True, "attribute_matched": True}
            for index, _ in enumerate(output.claims)
        ],
        "answer_consistent": True,
        "conflict_presented": True if case.source_conflict else None,
        "reason": "逐条核对来源。",
    }
    return AskWorldTeacherDecision.model_validate(values | overrides)


def _semantic(
    case: AskWorldEvalCase,
    output: GeneratedAskWorldOutput,
    decision: AskWorldTeacherDecision | None,
) -> tuple[dict, dict]:
    result = _deterministic(case, output)
    summary = summarize_ask_world_semantic_review(
        [case],
        [result],
        [decision] if decision else [],
        {"kind": "surrogate_teacher", "human_validated": False},
    )
    return result, summary


def test_semantic_review_passes_only_a_fully_reviewed_correct_answer() -> None:
    case = _probe("ask-probe-ferry-toll-conflict")
    output = _conflict_answer(case)

    result, summary = _semantic(case, output, _review(case, output))

    assert result["deterministic_passed"] is True
    assert summary["available"] is True
    assert summary["metrics"]["semantic_pass_rate"] == 1.0
    assert summary["case_results"][0] == {
        "scenario_id": case.scenario_id,
        "stratum": None,
        "semantic_status": "pass",
        "failed_checks": [],
    }


@pytest.mark.parametrize(
    ("overrides", "expected_check"),
    [
        # Right keys, wrong number: citation sets cannot see this.
        (
            {
                "claims": [
                    {"claim_index": 0, "supported": False, "attribute_matched": True}
                ]
            },
            "claim_unsupported:0",
        ),
        # The answer text adds a fact no claim carries.
        ({"answer_consistent": False}, "answer_inconsistent"),
        # Unknown wrapped as an answer to the asked attribute.
        (
            {
                "claims": [
                    {"claim_index": 0, "supported": True, "attribute_matched": False}
                ]
            },
            "claim_attribute_mismatch:0",
        ),
        # Both keys cited, but only one version is actually presented.
        ({"conflict_presented": False}, "conflict_not_presented"),
        ({"conflict_presented": None}, "conflict_not_presented"),
    ],
)
def test_semantic_review_rejects_distortions_that_citation_sets_miss(
    overrides: dict, expected_check: str
) -> None:
    case = _probe("ask-probe-ferry-toll-conflict")
    output = _conflict_answer(case)

    result, summary = _semantic(
        case,
        output,
        _review(case, output, model_verdict="fail", **overrides),
    )

    # The deterministic source-set score is blind to every one of these.
    assert result["deterministic_passed"] is True
    assert summary["case_results"][0]["semantic_status"] == "fail"
    assert expected_check in summary["case_results"][0]["failed_checks"]
    assert summary["metrics"]["semantic_pass_rate"] == 0.0


def test_semantic_review_rejects_citations_swapped_between_versions() -> None:
    case = _probe("ask-probe-ferry-toll-conflict")
    first, second = case.relevant_source_keys
    output = GeneratedAskWorldOutput(
        answer="两版票价不同。",
        claims=[
            GeneratedAskWorldClaim(text="第一版：每人三枚铜币。", citation_keys=[second]),
            GeneratedAskWorldClaim(text="第二版：每人五枚铜币。", citation_keys=[first]),
        ],
        uncertainty="需要作者决定采用哪一版。",
    )
    unsupported = [
        {"claim_index": index, "supported": False, "attribute_matched": True}
        for index in range(2)
    ]

    result, summary = _semantic(
        case,
        output,
        _review(case, output, model_verdict="fail", claims=unsupported),
    )

    assert result["deterministic_passed"] is True
    assert summary["case_results"][0]["failed_checks"] == [
        "claim_unsupported:0",
        "claim_unsupported:1",
    ]


def test_semantic_review_cannot_rescue_a_deterministic_failure() -> None:
    case = _probe("ask-probe-ferry-toll-conflict")
    # Only one conflicting version cited, hidden behind generic uncertainty.
    one_sided = _conflict_answer(
        case, keys=case.relevant_source_keys[:1], uncertainty="存在不确定。"
    )
    refusal = GeneratedAskWorldOutput(answer="证据不足。", no_answer=True)
    unknown_as_answer = GeneratedAskWorldOutput(
        answer="数量是一些。",
        claims=[
            GeneratedAskWorldClaim(
                text="数量约为若干。", citation_keys=["page:fog-lake-market"]
            )
        ],
    )

    checks = {}
    for name, target, output in (
        ("one_sided", case, one_sided),
        ("refused_clear_evidence", case, refusal),
        ("unknown_as_answer", _probe("ask-probe-fog-lake-fish-count"), unknown_as_answer),
    ):
        # A mistaken reviewer approves everything.
        _, summary = _semantic(target, output, _review(target, output))
        assert summary["case_results"][0]["semantic_status"] == "fail", name
        assert summary["metrics"]["semantic_pass_rate"] == 0.0, name
        checks[name] = summary["case_results"][0]["failed_checks"]

    assert "conflict_sources_not_covered" in checks["one_sided"]
    assert "answerability_mismatch" in checks["refused_clear_evidence"]
    assert "answerability_mismatch" in checks["unknown_as_answer"]


def test_semantic_review_is_unavailable_without_review_evidence() -> None:
    cases = load_ask_world_cases(MODEL_PROBE_DATASET)

    async def generate(case):
        if not case.should_answer:
            return GeneratedAskWorldOutput(answer="证据不足。", no_answer=True)
        return _conflict_answer(case)

    report = asyncio.run(evaluate_ask_world_model_cases(cases, generate))
    # Every deterministic check passes, yet nothing semantic is claimed.
    assert report["metrics"]["deterministic_pass_rate"] == 1.0
    assert report["semantic_review"] == {
        "available": False,
        "reason": "no_independent_review",
    }

    summary = summarize_ask_world_semantic_review(
        cases, report["case_results"], [], {"kind": "surrogate_teacher"}
    )
    assert summary["available"] is False
    assert summary["reason"] == "incomplete_review_coverage"
    assert summary["metrics"]["semantic_pass_rate"] is None
    assert summary["coverage"]["status_counts"] == {"unreviewed": len(cases)}


def test_semantic_review_keeps_invalid_ambiguous_and_disputed_reviews_visible() -> None:
    case = _probe("ask-probe-ferry-toll-conflict")
    output = _conflict_answer(case)

    _, invalid = _semantic(case, output, _review(case, output, claims=[]))
    assert invalid["case_results"][0]["semantic_status"] == "invalid_review"
    assert invalid["available"] is False
    assert invalid["metrics"]["semantic_pass_rate"] is None

    _, ambiguous = _semantic(
        case, output, _review(case, output, model_verdict="ambiguous")
    )
    _, disputed = _semantic(
        case, output, _review(case, output, reference_verdict="needs_edit")
    )
    for summary, status in ((ambiguous, "ambiguous"), (disputed, "reference_disputed")):
        assert summary["case_results"][0]["semantic_status"] == status
        assert summary["available"] is True
        assert summary["metrics"]["semantic_pass_rate"] == 0.0
        assert summary["coverage"]["decided_case_count"] == 0


def test_semantic_review_flags_a_reviewer_verdict_that_contradicts_its_fields() -> None:
    case = _probe("ask-probe-ferry-toll-conflict")
    output = _conflict_answer(case)

    _, pass_with_failed_field = _semantic(
        case, output, _review(case, output, answer_consistent=False)
    )
    assert pass_with_failed_field["case_results"][0]["failed_checks"] == [
        "answer_inconsistent",
        "reviewer_verdict_inconsistent",
    ]

    _, fail_without_reason = _semantic(
        case, output, _review(case, output, model_verdict="fail")
    )
    assert fail_without_reason["case_results"][0]["failed_checks"] == [
        "reviewer_verdict_fail"
    ]


def test_non_conflicting_multi_source_answer_does_not_need_uncertainty() -> None:
    row = next(
        item for item in _dataset_rows() if item["scenario_id"] == "ask-bell-density-8"
    )
    case = AskWorldEvalCase.model_validate(row)
    assert len(case.relevant_source_keys) > 1 and not case.source_conflict
    output = GeneratedAskWorldOutput(
        answer="综合来源可得结论。",
        claims=[
            GeneratedAskWorldClaim(
                text="组合结论。", citation_keys=case.relevant_source_keys[:3]
            ),
            GeneratedAskWorldClaim(
                text="补充结论。", citation_keys=case.relevant_source_keys[3:]
            ),
        ],
    )

    result = _deterministic(case, output)

    assert result["conflict_sources_covered"] is None
    assert result["deterministic_passed"] is True


def test_model_probe_generation_failure_is_never_recorded_as_complete() -> None:
    cases = load_ask_world_cases(MODEL_PROBE_DATASET)

    async def generate(case):
        if case.scenario_id == cases[2].scenario_id:
            raise TimeoutError("provider stalled")
        return GeneratedAskWorldOutput(answer="证据不足。", no_answer=True)

    report = asyncio.run(evaluate_ask_world_model_cases(cases, generate))

    assert report["complete"] is False
    assert report["status"] == "incomplete"
    assert report["failure"] == {
        "stage": "generation",
        "scenario_id": cases[2].scenario_id,
        "error_type": "TimeoutError",
    }
    assert report["metrics"] is None
    assert len(report["case_results"]) == 2
    assert report["semantic_review"] == {
        "available": False,
        "reason": "run_incomplete",
    }


def test_code_provenance_names_the_revision_and_working_tree_state() -> None:
    provenance = _code_provenance()

    assert set(provenance) == {"git_commit", "git_dirty", "working_tree_sha256"}
    if provenance["git_commit"] is not None:
        assert len(provenance["git_commit"]) == 40
        assert isinstance(provenance["git_dirty"], bool)
        assert (provenance["working_tree_sha256"] is None) == (
            not provenance["git_dirty"]
        )


def _write_cli_args(monkeypatch, output: Path) -> None:
    monkeypatch.setattr(
        "sys.argv",
        [
            "evals.ask_world",
            "--model-probes",
            "--novel-id",
            "novel-a",
            "--output",
            str(output),
        ],
    )


def test_model_probe_cli_replaces_stale_reports_and_fails_on_incomplete_runs(
    monkeypatch, tmp_path: Path
) -> None:
    output = tmp_path / "probe.result.json"
    output.write_text(json.dumps({"complete": True, "status": "complete"}))
    seen_during_run: dict = {}

    async def incomplete_run(*_args, **_kwargs):
        seen_during_run.update(json.loads(output.read_text()))
        return {"complete": False, "status": "incomplete"}

    monkeypatch.setattr("evals.ask_world.run_ask_world_model_probe_eval", incomplete_run)
    _write_cli_args(monkeypatch, output)

    with pytest.raises(SystemExit) as exit_info:
        ask_world_main()

    assert exit_info.value.code == 2
    # The earlier complete report is gone before any paid call starts.
    assert seen_during_run["status"] == "running"
    assert seen_during_run["complete"] is False
    assert json.loads(output.read_text())["status"] == "incomplete"


def test_model_probe_cli_marks_an_interrupted_run_as_aborted(
    monkeypatch, tmp_path: Path
) -> None:
    output = tmp_path / "probe.result.json"

    async def interrupted_run(*_args, **_kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr("evals.ask_world.run_ask_world_model_probe_eval", interrupted_run)
    _write_cli_args(monkeypatch, output)

    with pytest.raises(KeyboardInterrupt):
        ask_world_main()

    assert json.loads(output.read_text()) == {
        "blocking": False,
        "complete": False,
        "error_type": "KeyboardInterrupt",
        "status": "aborted",
    }


def test_ask_world_model_probe_metrics_cover_refusal_and_conflicts() -> None:
    cases = load_ask_world_cases(MODEL_PROBE_DATASET)

    async def generate(case):
        if not case.should_answer:
            return GeneratedAskWorldOutput(
                answer="证据不足。",
                no_answer=True,
            )
        return _conflict_answer(case)

    report = asyncio.run(evaluate_ask_world_model_cases(cases, generate))

    assert report["blocking"] is False
    assert report["complete"] is True
    assert report["status"] == "complete"
    assert report["quality_scope"] == "model_answer_source_set_diagnostic"
    assert report["metrics"] == {
        "answerability_accuracy": 1.0,
        "no_answer_accuracy": 1.0,
        "citation_precision": 1.0,
        "citation_recall": 1.0,
        "conflict_source_coverage": 1.0,
        "deterministic_pass_rate": 1.0,
    }
    assert all("answer" not in result for result in report["case_results"])


def test_ask_world_model_probe_metrics_expose_bad_model_behavior() -> None:
    cases = load_ask_world_cases(MODEL_PROBE_DATASET)

    async def generate(case):
        key = case.sources[0].key
        return GeneratedAskWorldOutput(
            answer="直接选择一个说法。",
            claims=[GeneratedAskWorldClaim(text="结论。", citation_keys=[key])],
        )

    report = asyncio.run(evaluate_ask_world_model_cases(cases, generate))

    assert report["metrics"]["answerability_accuracy"] == 3 / 7
    assert report["metrics"]["no_answer_accuracy"] == 0.0
    assert report["metrics"]["citation_recall"] == 0.5
    assert report["metrics"]["conflict_source_coverage"] == 0.0
    assert report["metrics"]["deterministic_pass_rate"] == 0.0


def _teacher(decisions_for):
    class Teacher:
        meta = SimpleNamespace(
            model=ASK_WORLD_TEACHER_MODEL,
            reasoning_effort="medium",
            executor_hash="a" * 64,
        )

        async def generate_structured(self, prompt, schema, *, step_name):
            assert step_name == "eval.ask_world.teacher_calibration"
            assert '"claim_index":0' in prompt
            assert '"source_conflict":true' in prompt
            return schema(decisions=decisions_for())

    return Teacher()


def _good_probe_run():
    cases = load_ask_world_cases(MODEL_PROBE_DATASET)
    generated = {
        case.scenario_id: (
            GeneratedAskWorldOutput(answer="证据不足。", no_answer=True)
            if not case.should_answer
            else _conflict_answer(case)
        )
        for case in cases
    }

    async def generate(case):
        return generated[case.scenario_id]

    report = asyncio.run(evaluate_ask_world_model_cases(cases, generate))
    return cases, generated, report["case_results"]


def test_ask_world_teacher_calibration_is_explicitly_not_human() -> None:
    cases, generated, results = _good_probe_run()

    report = asyncio.run(
        evaluate_ask_world_teacher_calibration(
            cases,
            generated,
            results,
            _teacher(
                lambda: [
                    _review(case, generated[case.scenario_id]).model_dump()
                    for case in cases
                ]
            ),
        )
    )

    assert report["kind"] == "surrogate_teacher"
    assert report["human_validated"] is False
    assert report["blocking"] is False
    assert report["teacher_model"] == ASK_WORLD_TEACHER_MODEL
    assert report["metrics"] == {
        "reference_acceptance_rate": 1.0,
        "deterministic_teacher_agreement": 1.0,
        "ambiguous_count": 0,
    }
    assert report["disagreement_scenarios"] == []
    semantic = report["semantic_review"]
    assert semantic["available"] is True
    assert semantic["reviewer"]["human_validated"] is False
    assert semantic["reviewer"]["kind"] == "surrogate_teacher"
    assert semantic["metrics"]["semantic_pass_rate"] == 1.0
    assert semantic["metrics"]["claim_support_rate"] == 1.0


def test_ask_world_teacher_disagreement_with_deterministic_score_is_listed() -> None:
    cases, generated, results = _good_probe_run()
    target = "ask-probe-ferry-toll-conflict"

    def decisions():
        return [
            _review(
                case,
                generated[case.scenario_id],
                **(
                    {
                        "model_verdict": "fail",
                        "claims": [
                            {
                                "claim_index": 0,
                                "supported": False,
                                "attribute_matched": True,
                            }
                        ],
                    }
                    if case.scenario_id == target
                    else {}
                ),
            ).model_dump()
            for case in cases
        ]

    report = asyncio.run(
        evaluate_ask_world_teacher_calibration(
            cases, generated, results, _teacher(decisions)
        )
    )

    assert report["disagreement_scenarios"] == [target]
    assert report["metrics"]["deterministic_teacher_agreement"] == 6 / 7
    assert report["semantic_review"]["metrics"]["semantic_pass_rate"] == 6 / 7
    assert report["semantic_review"]["metrics"]["claim_support_rate"] == 2 / 3


def test_ask_world_teacher_rejects_missing_scenario() -> None:
    cases = load_ask_world_cases(MODEL_PROBE_DATASET)
    generated = {
        case.scenario_id: GeneratedAskWorldOutput(
            answer="证据不足。",
            no_answer=True,
        )
        for case in cases
    }

    class Teacher:
        meta = SimpleNamespace()

        async def generate_structured(self, _prompt, schema, *, step_name):
            del step_name
            return schema(
                decisions=[
                    {
                        "scenario_id": cases[0].scenario_id,
                        "reference_verdict": "accept",
                        "model_verdict": "pass",
                        "answerability_justified": True,
                        "claims": [],
                        "answer_consistent": True,
                        "conflict_presented": None,
                        "reason": "只返回了一条。",
                    }
                ]
            )

    with pytest.raises(ValueError, match="do not match requested scenarios"):
        asyncio.run(
            evaluate_ask_world_teacher_calibration(
                cases,
                generated,
                [{"scenario_id": case.scenario_id} for case in cases],
                Teacher(),
            )
        )


def test_generation_ledger_keeps_each_output_for_review(tmp_path: Path) -> None:
    from evals.ask_world import _write_generation_ledger

    ledger = tmp_path / "private" / "ledger.jsonl"
    _write_generation_ledger(
        ledger,
        {"dataset_sha256": "d" * 64, "system_under_test": {"model": "deepseek-v4-flash"}},
        {
            "ask-a": GeneratedAskWorldOutput(
                answer="可答。",
                claims=[GeneratedAskWorldClaim(text="结论。", citation_keys=["page:a"])],
            ),
            "ask-b": GeneratedAskWorldOutput(answer="证据不足。", no_answer=True),
        },
    )

    rows = [json.loads(line) for line in ledger.read_text().splitlines()]
    assert [row["scenario_id"] for row in rows] == ["ask-a", "ask-b"]
    assert rows[0]["generated"]["claims"][0]["citation_keys"] == ["page:a"]
    assert rows[1]["generated"]["no_answer"] is True
    assert {row["model"] for row in rows} == {"deepseek-v4-flash"}
    assert not list(ledger.parent.glob("*.tmp"))
