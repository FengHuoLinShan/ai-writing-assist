from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from evals.rp_long_memory import (
    ARM_SPECS,
    RUBRIC_DIMENSIONS,
    BlindReview,
    SemanticFactExpectation,
    _arm_order,
    _candidate_id,
    _model_cache_key,
    _run_model_stage,
    _semantic_fact_matches,
    atomic_write_json,
    compile_report,
    load_calibration_cases,
    load_cases,
    main,
    materialize_case,
    review_report,
)
from infrastructure.llm.schemas import LLMStreamChunk, LLMUsage

DATASET = Path(__file__).parents[1] / "datasets" / "baselines" / "rp-long-memory-v2.jsonl"
LEGACY_DATASET = (
    Path(__file__).parents[1] / "datasets" / "baselines" / "rp-long-memory-v1.jsonl"
)


def _payloads() -> list[dict]:
    return [json.loads(line) for line in DATASET.read_text(encoding="utf-8").splitlines()]


def _write_jsonl(path: Path, payloads: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in payloads) + "\n",
        encoding="utf-8",
    )


def _verified_dataset(tmp_path: Path) -> Path:
    payload = _payloads()[0]
    payload["capability_profile"]["provider"] = "test-provider"
    payload["capability_profile"]["calibration_status"] = "verified"
    payload["capability_profile"]["official_spec_url"] = "https://example.test/models"
    payload["capability_profile"]["spec_verified_on"] = "2026-09-01"
    path = tmp_path / "verified.jsonl"
    _write_jsonl(path, [payload])
    return path


def _field(value):
    return SimpleNamespace(value=value)


class _FakeManager:
    def __init__(self) -> None:
        self.db = object()
        self.closed = False

    @asynccontextmanager
    async def session_factory(self):
        yield self.db

    async def close(self) -> None:
        self.closed = True


class _FakeModelClient:
    def __init__(
        self,
        *,
        probe_value: str = "只能操纵水流且不能使用火焰",
        story_text: str = "米娅放下火把，改用水流推动机关。",
    ) -> None:
        self.probe_value = probe_value
        self.story_text = story_text

    async def generate_structured(self, _request, response_model, **_kwargs):
        diagnostics = _kwargs.get("diagnostics")
        if diagnostics is not None:
            diagnostics.append(
                {
                    "kind": "structured_usage",
                    "status": "succeeded",
                    "attempt": 1,
                    "prompt_tokens": 50,
                    "completion_tokens": 5,
                    "total_tokens": 55,
                }
            )
        return response_model(
            probe_id="ability-probe",
            answers={
                "player.ability.limit": self.probe_value,
            },
        )

    async def generate_stream(self, _request, **_kwargs):
        yield LLMStreamChunk(
            content=self.story_text,
            finish_reason="stop",
            usage=LLMUsage(
                prompt_tokens=100,
                completion_tokens=20,
                total_tokens=120,
            ),
        )


def _install_fake_model_runtime(
    monkeypatch,
    *,
    model: str = "deepseek-v4-flash",
    provider: str = "test-provider",
    project_error: Exception | None = None,
    probe_value: str = "只能操纵水流且不能使用火焰",
    story_text: str = "米娅放下火把，改用水流推动机关。",
):
    from app import bootstrap
    from core import container, database
    from infrastructure.embedding.client import BgeEmbeddingClient
    from modules.project import facade as project_facade

    manager = _FakeManager()
    client = _FakeModelClient(
        probe_value=probe_value,
        story_text=story_text,
    )
    opened = {"count": 0}

    async def require_interaction_project(_db, _novel_id):
        if project_error is not None:
            raise project_error
        return None

    async def get_any_project_context(_db, _novel_id):
        return SimpleNamespace(settings={}, owner_id=str(uuid.uuid4()))

    async def resolve_effective_llm_settings_for_project_settings(
        _db,
        _project_settings,
        *,
        owner_id,
    ):
        assert owner_id is not None
        return SimpleNamespace(
            provider_id=_field(provider),
            model=_field(model),
            timeout=_field(60),
            max_tokens=_field(4096),
            temperature=_field(0.8),
            top_p=_field(1.0),
            extra=_field({"api_key": "PROFILE_SECRET", "safe": True}),
        )

    @asynccontextmanager
    async def open_project_llm_client(_db, _novel_id):
        opened["count"] += 1
        yield client

    async def no_op_async(*_args, **_kwargs):
        return None

    monkeypatch.setattr(bootstrap, "register_container_services", lambda **_kwargs: None)
    monkeypatch.setattr(database, "get_manager", lambda: manager)
    monkeypatch.setattr(container, "shutdown", no_op_async)
    monkeypatch.setattr(BgeEmbeddingClient, "close_instance", no_op_async)
    monkeypatch.setattr(
        project_facade,
        "require_interaction_project",
        require_interaction_project,
    )
    monkeypatch.setattr(
        project_facade,
        "get_any_project_context",
        get_any_project_context,
    )
    monkeypatch.setattr(
        project_facade,
        "resolve_effective_llm_settings_for_project_settings",
        resolve_effective_llm_settings_for_project_settings,
    )
    monkeypatch.setattr(
        project_facade,
        "open_project_llm_client",
        open_project_llm_client,
    )
    return manager, opened


def test_offline_compile_is_deterministic_and_hash_only() -> None:
    cases, dataset_hash = load_cases(DATASET)

    first, _ = compile_report(cases, dataset_hash=dataset_hash, split="dev")
    second, _ = compile_report(cases, dataset_hash=dataset_hash, split="dev")

    assert first["status"] == "ready"
    assert first["stable_report_hash"] == second["stable_report_hash"]
    assert first["case_count"] == 8
    assert all(
        item["actual_history_tokens"] == item["length"]["target_history_tokens"]
        for item in first["cases"]
    )
    assert {item["implementation_source"] for item in first["cases"][0]["arms"]} == {
        source for _arm, source in ARM_SPECS
    }
    unavailable = {item["name"]: item for item in first["metrics"]}
    assert unavailable["fact_probe_accuracy"] == {
        "name": "fact_probe_accuracy",
        "available": False,
        "blocking": False,
        "value": None,
        "threshold": None,
        "passed": None,
        "reason": "model stage not run",
    }
    serialized = json.dumps(first, ensure_ascii=False)
    assert '"story"' not in serialized
    assert str(DATASET.parent) not in serialized


def test_semantic_probe_accepts_paraphrase_but_keeps_missing_qualifiers_failed() -> None:
    expectation = SemanticFactExpectation(
        accepted_values=["已包扎但不能负重"],
        required_term_groups=[
            ["包扎"],
            ["不能负重", "无法负重", "不可承重"],
        ],
        forbidden_terms=["可以负重"],
    )

    assert _semantic_fact_matches("左臂已包扎，目前无法负重。", expectation)
    assert not _semantic_fact_matches("左臂受伤，已经包扎。", expectation)
    assert not _semantic_fact_matches("已经包扎，可以负重。", expectation)
    assert not _semantic_fact_matches(None, expectation)


def test_legacy_v1_stays_compile_only(tmp_path: Path) -> None:
    cases, dataset_hash = load_cases(LEGACY_DATASET)
    report, _runtime = compile_report(cases, dataset_hash=dataset_hash, split="dev")
    assert report["status"] == "ready"

    with pytest.raises(ValueError, match="v2 semantic fact expectations"):
        asyncio.run(
            _run_model_stage(
                dataset=LEGACY_DATASET,
                split="dev",
                novel_id="not-opened",
                allow_paid_model=True,
                runs=1,
                output_dir=tmp_path,
                cache_only=False,
            )
        )


def test_one_template_value_changes_only_its_case_root(tmp_path: Path) -> None:
    original_cases, _ = load_cases(DATASET)
    payloads = _payloads()
    payloads[0]["events"][0]["values"]["fact"] = "她在另一座合成港口醒来。"
    changed_dataset = tmp_path / "changed.jsonl"
    _write_jsonl(changed_dataset, payloads)
    changed_cases, _ = load_cases(changed_dataset)

    original_roots = {
        case.case_id: materialize_case(case).root_hash for case in original_cases
    }
    changed_roots = {
        case.case_id: materialize_case(case).root_hash for case in changed_cases
    }

    assert changed_roots["ability-long-recall"] != original_roots["ability-long-recall"]
    assert {
        case_id: root
        for case_id, root in changed_roots.items()
        if case_id != "ability-long-recall"
    } == {
        case_id: root
        for case_id, root in original_roots.items()
        if case_id != "ability-long-recall"
    }


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda payload: payload.update({"unknown": True}), "Extra inputs"),
        (lambda payload: payload.update({"source_text": "作品正文"}), "forbidden"),
        (lambda payload: payload.update({"copyright_text": "作品正文"}), "forbidden"),
        (
            lambda payload: payload.update({"schema_version": "rp-long-memory-v3"}),
            "unsupported schema_version",
        ),
        (
            lambda payload: payload["events"][0].update(
                {"template_id": "unknown-template"}
            ),
            "template_id",
        ),
        (
            lambda payload: payload["probe"]["values"].update(
                {"question": "/Users/example/private.txt"}
            ),
            "absolute paths",
        ),
        (
            lambda payload: payload["source_versions"][0].update(
                {"manifest_hash": "bad"}
            ),
            "manifest_hash",
        ),
    ],
)
def test_strict_schema_rejects_unsafe_fixture_fields(
    tmp_path: Path,
    mutate,
    message: str,
) -> None:
    payload = _payloads()[3]
    mutate(payload)
    dataset = tmp_path / "unsafe.jsonl"
    _write_jsonl(dataset, [payload])

    with pytest.raises(ValueError, match=message):
        load_cases(dataset)

    with pytest.raises(ValueError) as error:
        load_cases(dataset)
    assert "line 1 case knowledge-source-cutoff" in str(error.value)


def test_scenario_groups_cannot_cross_splits(tmp_path: Path) -> None:
    first = _payloads()[0]
    second = json.loads(json.dumps(first))
    second["case_id"] = "ability-test-copy"
    second["split"] = "test"
    dataset = tmp_path / "split-leak.jsonl"
    _write_jsonl(dataset, [first, second])

    with pytest.raises(ValueError, match="crosses dev/test"):
        load_cases(dataset)


def test_case_order_does_not_change_split_membership(tmp_path: Path) -> None:
    payloads = _payloads()
    reversed_dataset = tmp_path / "reversed.jsonl"
    _write_jsonl(reversed_dataset, list(reversed(payloads)))

    original, _ = load_cases(DATASET)
    reordered, _ = load_cases(reversed_dataset)

    assert {case.case_id: case.split for case in original} == {
        case.case_id: case.split for case in reordered
    }


def test_branch_dag_requires_parent_to_appear_first(tmp_path: Path) -> None:
    payload = _payloads()[0]
    payload["events"][0]["parent_event_id"] = "selected-tail"
    dataset = tmp_path / "bad-dag.jsonl"
    _write_jsonl(dataset, [payload])
    cases, _ = load_cases(dataset)

    with pytest.raises(ValueError, match="cycle|must appear first"):
        materialize_case(cases[0])


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda payload: payload["events"][1].update(
                {"parent_event_id": "missing-parent"}
            ),
            "missing",
        ),
        (
            lambda payload: payload["events"][1].update(
                {"parent_event_id": "rejected-sibling"}
            ),
            "must appear first",
        ),
        (
            lambda payload: payload["events"][3].update({"event_id": "water-limit"}),
            "event_id values must be unique",
        ),
        (
            lambda payload: payload["branch_plan"].update(
                {"shared_ancestor_event_id": "rejected-sibling"}
            ),
            "shared ancestor",
        ),
        (
            lambda payload: payload["branch_plan"].update(
                {"unselected_sibling_event_ids": ["water-limit"]}
            ),
            "non-selected events entered ancestry",
        ),
        (
            lambda payload: payload["events"][1]["operations"].insert(
                0,
                {
                    "kind": "create",
                    "object_key": "player",
                    "fact_key": None,
                    "field_key": None,
                    "value": "duplicate",
                    "target_object_key": None,
                },
            ),
            "duplicate object create",
        ),
    ],
)
def test_branch_and_object_graph_rejects_invalid_shapes(
    tmp_path: Path,
    mutate,
    message: str,
) -> None:
    payload = _payloads()[0]
    mutate(payload)
    dataset = tmp_path / "invalid-graph.jsonl"
    _write_jsonl(dataset, [payload])

    with pytest.raises(ValueError, match=message):
        cases, _ = load_cases(dataset)
        materialize_case(cases[0])


def test_oracle_catches_reference_builder_omission(tmp_path: Path) -> None:
    payload = _payloads()[0]
    payload["oracle"]["expected_raw_event_ids"] = ["rejected-sibling"]
    dataset = tmp_path / "bad-reference.jsonl"
    _write_jsonl(dataset, [payload])
    cases, dataset_hash = load_cases(dataset)

    report, _ = compile_report(cases, dataset_hash=dataset_hash, split="dev")

    assert report["status"] == "non_ready"
    assert report["cases"][0]["primary_failure"] == "required_fact_absent"


def test_oracle_catches_wrong_current_winner(tmp_path: Path) -> None:
    payload = _payloads()[0]
    payload["oracle"]["current_values"]["player.ability.limit"] = "错误赢家"
    dataset = tmp_path / "wrong-winner.jsonl"
    _write_jsonl(dataset, [payload])
    cases, dataset_hash = load_cases(dataset)

    report, _ = compile_report(cases, dataset_hash=dataset_hash, split="dev")

    assert report["status"] == "non_ready"
    assert report["cases"][0]["primary_failure"] == "fixture_invalid"


def test_source_identity_stays_stable_when_reference_key_rotates(tmp_path: Path) -> None:
    payload = _payloads()[3]
    second_version = json.loads(json.dumps(payload["source_versions"][0]))
    second_version["revision_id"] = "source-v2"
    second_version["manifest_hash"] = "d" * 64
    second_version["objects"][0]["reference_key"] = "e" * 64
    payload["source_versions"].append(second_version)
    dataset = tmp_path / "source-rotation.jsonl"
    _write_jsonl(dataset, [payload])
    cases, _ = load_cases(dataset)

    materialized = materialize_case(cases[0])

    assert materialized.object_handles["clockmaker"].startswith("source:")
    assert "bbbb" not in materialized.object_handles["clockmaker"]
    assert "eeee" not in materialized.object_handles["clockmaker"]


def test_atomic_report_failure_keeps_previous_file(tmp_path: Path, monkeypatch) -> None:
    output = tmp_path / "report.json"
    output.write_text("old\n", encoding="utf-8")

    def fail_write(_path: Path, _data: bytes) -> int:
        raise OSError("simulated write failure")

    monkeypatch.setattr(Path, "write_bytes", fail_write)

    with pytest.raises(OSError, match="simulated"):
        atomic_write_json(output, {"new": True})
    assert output.read_text(encoding="utf-8") == "old\n"


def test_compile_cli_exit_semantics_and_atomic_report(tmp_path: Path) -> None:
    ready_dataset = tmp_path / "ready.jsonl"
    _write_jsonl(ready_dataset, [_payloads()[0]])
    ready_report = tmp_path / "ready-report.json"

    assert (
        main(
            [
                "compile",
                str(ready_dataset),
                "--split",
                "dev",
                "--output",
                str(ready_report),
            ]
        )
        == 0
    )
    ready_bytes = ready_report.read_bytes()
    assert ready_bytes.endswith(b"\n")
    ready_payload = json.loads(ready_bytes)
    assert (
        ready_payload["dataset_hash"]
        == hashlib.sha256(ready_dataset.read_bytes()).hexdigest()
    )
    assert ready_payload["stable_report_hash"]

    non_ready = _payloads()[0]
    non_ready["oracle"]["current_values"]["player.ability.limit"] = "错误赢家"
    non_ready_dataset = tmp_path / "non-ready.jsonl"
    _write_jsonl(non_ready_dataset, [non_ready])
    assert (
        main(
            [
                "compile",
                str(non_ready_dataset),
                "--split",
                "dev",
                "--output",
                str(tmp_path / "non-ready-report.json"),
            ]
        )
        == 2
    )

    invalid = _payloads()[0]
    invalid["source_text"] = "forbidden"
    invalid_dataset = tmp_path / "invalid.jsonl"
    _write_jsonl(invalid_dataset, [invalid])
    assert (
        main(
            [
                "compile",
                str(invalid_dataset),
                "--split",
                "dev",
                "--output",
                str(tmp_path / "invalid-report.json"),
            ]
        )
        == 1
    )


def test_model_cli_without_paid_authorization_returns_nonzero(tmp_path: Path) -> None:
    assert (
        main(
            [
                "model",
                str(DATASET),
                "--split",
                "dev",
                "--novel-id",
                "00000000-0000-0000-0000-000000000001",
                "--output-dir",
                str(tmp_path),
            ]
        )
        == 1
    )
    assert not (tmp_path / "rp-long-memory-model-report.json").exists()


def test_paid_gate_fails_before_dataset_or_client_access(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="allow-paid-model"):
        asyncio.run(
            _run_model_stage(
                dataset=tmp_path / "missing.jsonl",
                split="dev",
                novel_id="not-used",
                allow_paid_model=False,
                runs=1,
                output_dir=tmp_path,
                cache_only=False,
            )
        )
    with pytest.raises(ValueError, match="novel-id"):
        asyncio.run(
            _run_model_stage(
                dataset=tmp_path / "missing.jsonl",
                split="dev",
                novel_id=None,
                allow_paid_model=True,
                runs=1,
                output_dir=tmp_path,
                cache_only=False,
            )
        )


def test_synthetic_profiles_fail_before_project_client_access(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="verified capability profiles"):
        asyncio.run(
            _run_model_stage(
                dataset=DATASET,
                split="dev",
                novel_id="not-used",
                allow_paid_model=True,
                runs=1,
                output_dir=tmp_path,
                cache_only=False,
            )
        )


def test_model_stage_uses_project_client_and_exports_blind_artifacts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    dataset = _verified_dataset(tmp_path)
    manager, opened = _install_fake_model_runtime(monkeypatch)

    report, exit_code = asyncio.run(
        _run_model_stage(
            dataset=dataset,
            split="dev",
            novel_id="00000000-0000-0000-0000-000000000001",
            allow_paid_model=True,
            runs=1,
            output_dir=tmp_path / "artifacts",
            cache_only=False,
            cache_dir=tmp_path / "cache",
        )
    )

    assert exit_code == 0
    assert report["status"] == "ready"
    assert report["candidate_count"] == len(ARM_SPECS)
    assert opened["count"] == 1
    assert manager.closed is True
    metric_by_name = {item["name"]: item for item in report["metrics"]}
    assert metric_by_name["fact_probe_accuracy"]["passed"] is None
    assert metric_by_name["fact_probe_accuracy"]["value"][
        "candidate_passed_count"
    ] == len(ARM_SPECS)
    assert metric_by_name["hard_fact_probe_retention"]["passed"] is True
    assert metric_by_name["probe_repair_attempts"]["value"] == 0
    assert metric_by_name["provider_input_output_usage"]["available"] is True
    assert metric_by_name["story_blind_review"]["available"] is False
    assert metric_by_name["provider_cache_usage"]["available"] is False

    candidates = [
        json.loads(line)
        for line in (tmp_path / "artifacts" / report["candidates_file"])
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert len(candidates) == len(ARM_SPECS)
    assert all(
        "arm" not in item and "case_id" not in item and "run_index" not in item
        for item in candidates
    )
    assert all(item["question"] and item["continuity_facts"] for item in candidates)
    review_template = [
        json.loads(line)
        for line in (tmp_path / "artifacts" / report["review_template_file"])
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert {item["candidate_id"] for item in review_template} == {
        item["candidate_id"] for item in candidates
    }
    assert all(set(item["scores"]) == set(RUBRIC_DIMENSIONS) for item in review_template)
    calibration_candidates = [
        json.loads(line)
        for line in (tmp_path / "artifacts" / report["calibration_candidates_file"])
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert len(calibration_candidates) == 8
    assert all("constraints" not in item for item in calibration_candidates)
    arm_map = json.loads(
        (tmp_path / "artifacts" / report["arm_map_file"]).read_text(encoding="utf-8")
    )
    assert set(arm_map["mapping"]) == {item["candidate_id"] for item in candidates}
    serialized_artifacts = "\n".join(
        path.read_text(encoding="utf-8") for path in tmp_path.rglob("*.json*")
    )
    assert "PROFILE_SECRET" not in serialized_artifacts

    model_report_path = tmp_path / "artifacts" / "model-report.json"
    atomic_write_json(model_report_path, report)
    reviews_path = tmp_path / "artifacts" / "reviews.jsonl"
    _write_jsonl(
        reviews_path,
        [
            {
                "candidate_id": item["candidate_id"],
                "reviewer_id": "reviewer-a",
                "scores": dict.fromkeys(RUBRIC_DIMENSIONS, 3),
                "severe_spoiler": False,
            }
            for item in candidates
        ],
    )
    calibration_cases, _calibration_hash = load_calibration_cases()
    calibration_reviews_path = tmp_path / "artifacts" / "calibration-reviews.jsonl"
    calibration_rows = []
    for case in calibration_cases:
        scores = dict.fromkeys(RUBRIC_DIMENSIONS, 2)
        for dimension, constraint in case.constraints.items():
            scores[dimension] = (
                constraint.min_score
                if constraint.min_score is not None
                else constraint.max_score
            )
        calibration_rows.append(
            {
                "calibration_id": case.calibration_id,
                "reviewer_id": "reviewer-a",
                "scores": scores,
                "severe_spoiler": case.expected_severe_spoiler,
            }
        )
    _write_jsonl(calibration_reviews_path, calibration_rows)
    reviewed, review_exit = review_report(
        model_report_path,
        reviews_path,
        tmp_path / "artifacts" / report["arm_map_file"],
        calibration_reviews_path=calibration_reviews_path,
    )
    assert review_exit == 2
    assert reviewed["model_evidence"]["fact_probe"]["value"][
        "candidate_passed_count"
    ] == len(ARM_SPECS)
    assert reviewed["model_evidence"]["hard_fact_probe"]["passed"] is True
    assert reviewed["review_calibration"]["passed"] is True
    assert sum(item["review_count"] for item in reviewed["arm_summary"].values()) == len(
        ARM_SPECS
    )
    assert reviewed["paired_comparisons"]["segments_vs_baseline"]["pair_count"] == 1

    calibration_rows[0]["scores"]["ability_boundaries"] = 0
    _write_jsonl(calibration_reviews_path, calibration_rows)
    uncalibrated, _ = review_report(
        model_report_path,
        reviews_path,
        tmp_path / "artifacts" / report["arm_map_file"],
        calibration_reviews_path=calibration_reviews_path,
    )
    assert uncalibrated["review_calibration"]["passed"] is False

    cached_report, cached_exit = asyncio.run(
        _run_model_stage(
            dataset=dataset,
            split="dev",
            novel_id="00000000-0000-0000-0000-000000000001",
            allow_paid_model=True,
            runs=1,
            output_dir=tmp_path / "cached-artifacts",
            cache_only=True,
            cache_dir=tmp_path / "cache",
        )
    )
    assert cached_exit == 0
    assert cached_report["cache"]["hit_count"] == len(ARM_SPECS)
    assert opened["count"] == 1

    compatible_output = tmp_path / "compatible-artifacts"
    compatible_output.mkdir()
    atomic_write_json(
        compatible_output / "rp-long-memory-model-report.json",
        report,
    )
    original_compile_report = compile_report

    def changed_compiler(*args, **kwargs):
        changed, runtime = original_compile_report(*args, **kwargs)
        changed["compiler_hash"] = "f" * 64
        return changed, runtime

    with patch(
        "evals.rp_long_memory.compile_report",
        autospec=True,
        side_effect=changed_compiler,
    ):
        compatible_report, compatible_exit = asyncio.run(
            _run_model_stage(
                dataset=dataset,
                split="dev",
                novel_id="00000000-0000-0000-0000-000000000001",
                allow_paid_model=True,
                runs=1,
                output_dir=compatible_output,
                cache_only=True,
                cache_dir=tmp_path / "cache",
            )
        )

    assert compatible_exit == 0
    assert compatible_report["cache"]["compatible_reuse_count"] == len(ARM_SPECS)
    assert opened["count"] == 1

    for cache_path in (tmp_path / "cache").glob("*.json"):
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        cached.pop("probe_usage")
        atomic_write_json(cache_path, cached)
    legacy_report, legacy_exit = asyncio.run(
        _run_model_stage(
            dataset=dataset,
            split="dev",
            novel_id="00000000-0000-0000-0000-000000000001",
            allow_paid_model=True,
            runs=1,
            output_dir=tmp_path / "legacy-artifacts",
            cache_only=True,
            cache_dir=tmp_path / "cache",
        )
    )
    assert legacy_exit == 0
    legacy_metrics = {item["name"]: item for item in legacy_report["metrics"]}
    assert legacy_metrics["probe_repair_attempts"]["available"] is False
    assert legacy_metrics["provider_input_output_usage"]["available"] is False
    assert opened["count"] == 1


def test_unexecutable_blocker_case_does_not_require_provider_calibration(
    tmp_path: Path,
    monkeypatch,
) -> None:
    payloads = [_payloads()[0], _payloads()[-1]]
    payloads[0]["capability_profile"]["provider"] = "test-provider"
    payloads[0]["capability_profile"]["calibration_status"] = "verified"
    payloads[0]["capability_profile"]["official_spec_url"] = "https://example.test/models"
    payloads[0]["capability_profile"]["spec_verified_on"] = "2026-09-01"
    dataset = tmp_path / "verified-with-blocker.jsonl"
    _write_jsonl(dataset, payloads)
    _manager, opened = _install_fake_model_runtime(monkeypatch)

    report, exit_code = asyncio.run(
        _run_model_stage(
            dataset=dataset,
            split="dev",
            novel_id="00000000-0000-0000-0000-000000000001",
            allow_paid_model=True,
            runs=1,
            output_dir=tmp_path / "artifacts",
            cache_only=False,
            cache_dir=tmp_path / "cache",
        )
    )

    assert exit_code == 0
    assert report["candidate_count"] == len(ARM_SPECS)
    assert opened["count"] == 1


@pytest.mark.parametrize(
    ("runtime_kwargs", "cache_only", "message"),
    [
        ({"model": "other-model"}, False, "project model"),
        ({"provider": "other-provider"}, False, "project provider"),
        ({"project_error": RuntimeError("not interaction")}, False, "not interaction"),
        ({}, True, "cache misses"),
    ],
)
def test_model_gates_fail_before_client_open(
    tmp_path: Path,
    monkeypatch,
    runtime_kwargs: dict,
    cache_only: bool,
    message: str,
) -> None:
    dataset = _verified_dataset(tmp_path)
    _manager, opened = _install_fake_model_runtime(
        monkeypatch,
        **runtime_kwargs,
    )

    with pytest.raises((RuntimeError, ValueError), match=message):
        asyncio.run(
            _run_model_stage(
                dataset=dataset,
                split="dev",
                novel_id="00000000-0000-0000-0000-000000000001",
                allow_paid_model=True,
                runs=1,
                output_dir=tmp_path / "artifacts",
                cache_only=cache_only,
                cache_dir=tmp_path / "empty-cache",
            )
        )
    assert opened["count"] == 0


def test_model_cache_key_covers_every_pairing_input() -> None:
    values = {
        "dataset_hash": "a" * 64,
        "template_hash": "b" * 64,
        "compiler_hash": "c" * 64,
        "prompt_hash": "d" * 64,
        "probe_prompt_hash": "0" * 64,
        "profile_hash": "e" * 64,
        "case_id": "case-one",
        "arm": "overview_tail",
        "run_index": 0,
    }
    baseline = _model_cache_key(**values)

    for key, replacement in {
        "dataset_hash": "f" * 64,
        "template_hash": "1" * 64,
        "compiler_hash": "2" * 64,
        "prompt_hash": "3" * 64,
        "probe_prompt_hash": "5" * 64,
        "profile_hash": "4" * 64,
        "case_id": "case-two",
        "arm": "overview_tail_segments",
        "run_index": 1,
    }.items():
        changed = {**values, key: replacement}
        assert _model_cache_key(**changed) != baseline


def test_story_text_cannot_rescue_a_failed_fact_probe(
    tmp_path: Path,
    monkeypatch,
) -> None:
    dataset = _verified_dataset(tmp_path)
    _manager, _opened = _install_fake_model_runtime(
        monkeypatch,
        probe_value="错误答案",
        story_text="只能操纵水流且不能使用火焰。",
    )

    report, exit_code = asyncio.run(
        _run_model_stage(
            dataset=dataset,
            split="dev",
            novel_id="00000000-0000-0000-0000-000000000001",
            allow_paid_model=True,
            runs=1,
            output_dir=tmp_path / "artifacts",
            cache_only=False,
            cache_dir=tmp_path / "cache",
        )
    )

    assert exit_code == 0
    assert report["status"] == "ready"
    assert all(item["primary_failure"] == "model_nonuse" for item in report["candidates"])
    metrics = {item["name"]: item for item in report["metrics"]}
    assert metrics["fact_probe_accuracy"]["value"]["candidate_passed_count"] == 0
    assert metrics["story_blind_review"]["available"] is False


def test_blind_ids_and_arm_order_are_deterministic() -> None:
    kwargs = {
        "dataset_hash": "a" * 64,
        "profile_hash": "b" * 64,
        "case_id": "case-one",
        "run_index": 0,
    }

    assert _arm_order(**kwargs) == _arm_order(**kwargs)
    assert len(set(_arm_order(**kwargs))) == len(ARM_SPECS)
    assert _candidate_id(**kwargs, arm="overview_tail") == _candidate_id(
        **kwargs,
        arm="overview_tail",
    )


def test_review_requires_complete_rubric_and_keeps_claim_blocked(tmp_path: Path) -> None:
    candidate_ids = [f"{index:024x}" for index in range(len(ARM_SPECS))]
    arm_map_path = tmp_path / "arm-map.json"
    atomic_write_json(
        arm_map_path,
        {
            "dataset_hash": "a" * 64,
            "profile_hash": "b" * 64,
            "compiler_hash": "c" * 64,
            "prompt_hash": "d" * 64,
            "probe_prompt_hash": "e" * 64,
            "mapping": {
                candidate_id: arm
                for candidate_id, (arm, _source) in zip(candidate_ids, ARM_SPECS)
            },
        },
    )
    model_report_path = tmp_path / "model-report.json"
    atomic_write_json(
        model_report_path,
        {
            "report_version": "rp-long-memory-model-report-v2",
            "status": "ready",
            "dataset_hash": "a" * 64,
            "compiler_hash": "c" * 64,
            "prompt_hash": "d" * 64,
            "probe_prompt_hash": "e" * 64,
            "profile": {"profile_hash": "b" * 64},
            "arm_map_hash": hashlib.sha256(arm_map_path.read_bytes()).hexdigest(),
            "candidates": [
                {
                    "candidate_id": candidate_id,
                    "case_id": "case-one",
                    "run_index": 0,
                }
                for candidate_id in candidate_ids
            ],
            "hard_failures": [],
            "metrics": [
                {
                    "name": "fact_probe_accuracy",
                    "available": True,
                    "blocking": False,
                    "value": {
                        "candidate_passed_count": len(candidate_ids),
                        "candidate_count": len(candidate_ids),
                    },
                    "threshold": None,
                    "passed": None,
                    "reason": None,
                },
                {
                    "name": "hard_fact_probe_retention",
                    "available": True,
                    "blocking": True,
                    "value": len(candidate_ids),
                    "threshold": len(candidate_ids),
                    "passed": True,
                    "reason": None,
                },
            ],
        },
    )
    reviews_path = tmp_path / "reviews.jsonl"
    _write_jsonl(
        reviews_path,
        [
            {
                "candidate_id": candidate_id,
                "reviewer_id": "reviewer-a",
                "scores": dict.fromkeys(RUBRIC_DIMENSIONS, 3),
                "severe_spoiler": False,
            }
            for candidate_id in candidate_ids
        ],
    )

    report, exit_code = review_report(
        model_report_path,
        reviews_path,
        arm_map_path,
    )

    assert exit_code == 2
    assert report["status"] == "non_ready"
    assert report["quality_claim_allowed"] is False
    metrics = {item["name"]: item for item in report["metrics"]}
    assert metrics["model_fact_probe"]["value"]["candidate_passed_count"] == len(
        candidate_ids
    )
    assert metrics["model_hard_fact_probe"]["passed"] is True
    assert metrics["reviewer_calibration"]["available"] is False

    missing_path = tmp_path / "missing-reviews.jsonl"
    _write_jsonl(
        missing_path,
        [
            {
                "candidate_id": candidate_id,
                "reviewer_id": "reviewer-a",
                "scores": dict.fromkeys(RUBRIC_DIMENSIONS, 3),
                "severe_spoiler": False,
            }
            for candidate_id in candidate_ids[:-1]
        ],
    )
    with pytest.raises(ValueError, match="missing reviews"):
        review_report(model_report_path, missing_path, arm_map_path)

    duplicate_path = tmp_path / "duplicate-reviews.jsonl"
    duplicate_rows = [
        {
            "candidate_id": candidate_id,
            "reviewer_id": "reviewer-a",
            "scores": dict.fromkeys(RUBRIC_DIMENSIONS, 3),
            "severe_spoiler": False,
        }
        for candidate_id in candidate_ids
    ]
    _write_jsonl(duplicate_path, [*duplicate_rows, duplicate_rows[0]])
    with pytest.raises(ValueError, match="duplicate reviewer"):
        review_report(model_report_path, duplicate_path, arm_map_path)

    tampered_map = json.loads(arm_map_path.read_text(encoding="utf-8"))
    tampered_map["mapping"][candidate_ids[0]] = "overview_tail_segments"
    atomic_write_json(arm_map_path, tampered_map)
    with pytest.raises(ValueError, match="arm map hash"):
        review_report(model_report_path, reviews_path, arm_map_path)


def test_blind_review_rejects_incomplete_or_out_of_range_scores() -> None:
    with pytest.raises(ValueError, match="every rubric"):
        BlindReview(
            candidate_id="0" * 24,
            reviewer_id="reviewer-a",
            scores={"character_voice": 3},
        )
    with pytest.raises(ValueError, match="between 0 and 4"):
        BlindReview(
            candidate_id="0" * 24,
            reviewer_id="reviewer-a",
            scores={**dict.fromkeys(RUBRIC_DIMENSIONS, 3), "character_voice": 5},
        )
