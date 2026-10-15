import hashlib
import json
import os
from pathlib import Path

import pytest

from evals.map_spatial import (
    ALLOWED_GENRES,
    ALLOWED_SPLITS,
    MapSpatialEvalError,
    _require_live_scope_approval,
    _write_private_json,
    assert_pair_invariants,
    claim_case,
    report_template,
    update_run,
    verify_materials,
)


def _fixture(tmp_path: Path, monkeypatch):
    private_root = tmp_path / "private"
    private_root.mkdir(mode=0o700)
    os.chmod(private_root, 0o700)
    matrix_path = tmp_path / "matrix.json"
    monkeypatch.setattr("evals.map_spatial.MATRIX_PATH", matrix_path)
    families = []
    metric_names = {
        "cold_start": ["clue_precision", "total_cost"],
        "type_emergence": ["trait_accuracy"],
        "writing_paired": ["spatial_consistency"],
        "assistant": ["unknown_answer_accuracy"],
    }
    for genre in ALLOWED_GENRES:
        for split in ALLOWED_SPLITS:
            family_id = f"map-{genre}-{split}-v1"
            family_dir = private_root / family_id
            family_dir.mkdir(mode=0o700)
            os.chmod(family_dir, 0o700)
            case_ids = [f"{family_id}-p{index}" for index in range(1, 6)]
            source = {
                "family_id": family_id,
                "genre": genre,
                "split": split,
                "human_validated": False,
                "cases": [
                    {
                        "case_id": case_id,
                        "source_excerpt": f"原创文本-{genre}-{split}-{index}",
                    }
                    for index, case_id in enumerate(case_ids, 1)
                ],
            }
            expected = {
                "family_id": family_id,
                "genre": genre,
                "split": split,
                "human_validated": False,
                "cases": [{"case_id": case_id} for case_id in case_ids],
            }
            _write_private_json(family_dir / "source.json", source)
            _write_private_json(family_dir / "expected.json", expected)
            families.append(
                {
                    "family_id": family_id,
                    "genre": genre,
                    "split": split,
                    "source_sha256": hashlib.sha256(
                        (family_dir / "source.json").read_bytes()
                    ).hexdigest(),
                    "expected_sha256": hashlib.sha256(
                        (family_dir / "expected.json").read_bytes()
                    ).hexdigest(),
                    "review_status": "not_run",
                    "case_count": 5,
                }
            )
    matrix = {
        "schema_version": 2,
        "suite": "map_spatial",
        "status": "frozen_unreviewed",
        "metrics_by_genre": {genre: metric_names for genre in ALLOWED_GENRES},
        "families": families,
    }
    matrix_path.write_text(json.dumps(matrix), encoding="utf-8")
    return private_root, matrix_path, matrix


def test_private_material_contract_checks_hashes_splits_and_case_pairs(
    tmp_path, monkeypatch
):
    private_root, _, matrix = _fixture(tmp_path, monkeypatch)

    verified = verify_materials(private_root, matrix)

    assert len(verified) == 10
    assert sum(row["case_count"] for row in verified) == 50
    assert {row["review_status"] for row in verified} == {"not_run"}
    family = private_root / "map-xianxia-development-v1" / "source.json"
    source = json.loads(family.read_text(encoding="utf-8"))
    source["cases"][0]["source_excerpt"] = "被修改的材料"
    _write_private_json(family, source)
    with pytest.raises(MapSpatialEvalError, match="哈希与冻结矩阵不符"):
        verify_materials(private_root, matrix)


def test_holdout_gate_and_ledger_make_unknown_single_use(tmp_path, monkeypatch):
    private_root, _, matrix = _fixture(tmp_path, monkeypatch)
    holdout = next(row for row in matrix["families"] if row["split"] == "holdout")
    with pytest.raises(MapSpatialEvalError):
        claim_case(private_root, matrix, holdout, f"{holdout['family_id']}-p1")
    assert not (private_root / "run-ledger.json").exists()

    monkeypatch.setattr("evals.map_spatial._require_development_gate", lambda *_: None)
    case_id = f"{holdout['family_id']}-p1"
    claimed = claim_case(private_root, matrix, holdout, case_id)
    assert claimed["status"] == "started"
    update_run(
        private_root,
        holdout["family_id"],
        case_id,
        status="unknown",
        cost_status="unknown",
    )
    with pytest.raises(MapSpatialEvalError, match="不自动重发"):
        claim_case(private_root, matrix, holdout, case_id)


def test_report_preserves_unrun_as_unknown_and_keeps_genres_separate(
    tmp_path, monkeypatch
):
    _, _, matrix = _fixture(tmp_path, monkeypatch)

    report = report_template(matrix)

    assert set(report["genres"]) == set(ALLOWED_GENRES)
    for genre in ALLOWED_GENRES:
        assert set(report["genres"][genre]) == set(matrix["metrics_by_genre"][genre])
        cost = report["genres"][genre]["cold_start"]["metrics"]["total_cost"]
        assert cost["value"] is None
        assert cost["status"] == "unknown"
    assert report["human_validated"] is False


def test_pair_invariants_require_identical_frozen_inputs():
    without = {
        "source_hash": "a" * 64,
        "project_snapshot_hash": "b" * 64,
        "scene_hash": "c" * 64,
        "map_snapshot_hash": "d" * 64,
        "prompt_hash": "e" * 64,
        "core_context_hash": "f" * 64,
        "map_enabled": False,
    }
    with_map = {**without, "map_enabled": True}
    assert_pair_invariants(without, with_map)
    with_map["scene_hash"] = "1" * 64
    with pytest.raises(MapSpatialEvalError, match="scene_hash"):
        assert_pair_invariants(without, with_map)


def test_evolution_preview_requires_complete_spatial_quota_and_root_cap():
    from evals.map_spatial_control import _validate_evolution_preview

    request = {"end_chapter": 2, "request_limit": 15}
    preview = {
        "spatial_discovery_enabled": True,
        "scene_count": 5,
        "end_chapter": 2,
        "request_limit": 15,
        "budget_mode": "bounded",
        "model": "gpt-6-luna",
        "fingerprint": "product-preview-fingerprint",
        "mandatory_request_reserve": 5,
        "optional_steps": {
            "spatial": {
                "quota": 10,
                "per_scene_limit": 2,
                "used": 0,
                "remaining": 10,
                "request_range": {"minimum": 0, "maximum": 10},
            }
        },
    }

    assert _validate_evolution_preview(preview, request) == {
        "fingerprint": "product-preview-fingerprint",
        "scene_count": 5,
        "mandatory_request_reserve": 5,
        "mandatory_reserve_kind": "static_minimum",
        "spatial_quota": 10,
        "spatial_quota_kind": "child_maximum",
        "spatial_per_scene_limit": 2,
        "required_root_limit": 15,
        "request_limit": 15,
        "extra_headroom": 0,
        "completion_guaranteed": False,
        "total_call_upper_bound": 311,
        "total_call_upper_bound_with_connection_verification": 312,
        "within_root_limit": True,
    }
    assert not _validate_evolution_preview(
        {**preview, "request_limit": 14}, {**request, "request_limit": 14}
    )["within_root_limit"]
    with pytest.raises(MapSpatialEvalError, match="完整空间子额度"):
        _validate_evolution_preview(
            {
                **preview,
                "optional_steps": {
                    "spatial": {
                        **preview["optional_steps"]["spatial"],
                        "quota": 8,
                        "remaining": 8,
                        "request_range": {"minimum": 0, "maximum": 8},
                    }
                },
            },
            request,
        )


def test_optional_stage_contract_is_same_attempt_and_preserves_product_gaps():
    from evals.map_spatial_guard import _validate_evolution_optional_stage

    attempt = {
        "attempt_id": "attempt-1",
        "optional_stage_version": 1,
        "optional_scene_stage": {
            "version": 1,
            "receipt_attempt_id": "attempt-1",
            "scene_card_hash": "post-enrichment-scene-card",
            "main_state_fingerprint": "main-state",
            "completed_state_fingerprint": "settled-state",
            "steps": {
                "details": {"status": "not_run", "gaps": [{"reason": "step_disabled"}]},
                "spatial": {"status": "complete", "gaps": []},
            },
        },
        "optional_step_coverage": {"spatial": {"status": "inspected", "gaps": []}},
        "spatial_discovery_result": {"status": "inspected", "clues": []},
        "spatial_stage_result": {"status": "inspected", "gaps": []},
    }

    stage = _validate_evolution_optional_stage(attempt)
    assert stage["scene_card_hash"] == "post-enrichment-scene-card"
    assert stage["spatial_step_coverage"]["status"] == "inspected"
    assert stage["spatial_stage_result"]["status"] == "inspected"
    with pytest.raises(MapSpatialEvalError, match="同attempt"):
        _validate_evolution_optional_stage(
            {
                **attempt,
                "optional_scene_stage": {
                    **attempt["optional_scene_stage"],
                    "receipt_attempt_id": "another-attempt",
                },
            }
        )
    with pytest.raises(MapSpatialEvalError, match="同attempt"):
        _validate_evolution_optional_stage(
            {
                **attempt,
                "optional_scene_stage": {
                    **attempt["optional_scene_stage"],
                    "steps": {
                        **attempt["optional_scene_stage"]["steps"],
                        "spatial": {"status": "unknown", "gaps": []},
                    },
                },
            }
        )


def test_live_execution_fails_closed_until_sol_scope_is_integrated(tmp_path, monkeypatch):
    private_root = tmp_path / "private"
    private_root.mkdir(mode=0o700)
    os.chmod(private_root, 0o700)
    monkeypatch.delenv("MAP_SPATIAL_EVAL_ALLOW_LIVE", raising=False)
    with pytest.raises(MapSpatialEvalError, match="默认关闭"):
        _require_live_scope_approval(private_root, {}, execute=False)
    monkeypatch.setenv("MAP_SPATIAL_EVAL_ALLOW_LIVE", "1")
    with pytest.raises(MapSpatialEvalError, match="not_ready_for_live"):
        _require_live_scope_approval(private_root, {}, execute=True)


def test_private_output_cannot_be_written_under_repository():
    path = Path(__file__).resolve().parents[3] / ".agent" / "private-map-eval-test.json"
    with pytest.raises(MapSpatialEvalError, match="仓库外"):
        _write_private_json(path, {"raw": "synthetic"})
