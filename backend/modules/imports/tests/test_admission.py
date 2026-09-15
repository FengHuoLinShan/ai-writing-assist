from __future__ import annotations

from modules.imports.admission import (
    build_entity_fusion_deep_manifest,
    build_scene_phase_manifest,
)
from modules.world.contracts import ENTITY_FUSION_CHECKPOINT_PAIR_BATCH_SIZE


def test_scene_manifest_does_not_claim_a_finite_a_before_model_output() -> None:
    manifest = build_scene_phase_manifest(window_count=7)

    assert manifest["unit_count"] == 7
    assert manifest["batch_size"] == 1
    assert manifest["batch_count"] == 7
    assert manifest["request_upper_bound"] is None
    assert manifest["status"] == "awaiting_model_cardinality"
    assert len(manifest["fingerprint"]) == 64


def test_entity_fusion_manifest_is_replayable_and_includes_audit() -> None:
    manifest = build_entity_fusion_deep_manifest(pair_count=30_000)

    assert manifest["unit_count"] == 30_000
    assert manifest["request_upper_bound"] == 180_009
    assert manifest["batch_size"] == ENTITY_FUSION_CHECKPOINT_PAIR_BATCH_SIZE
    assert manifest["batch_count"] == 2_500
    assert manifest["status"] == "safety_limit_required"
    assert manifest["reason"] == "product safety gate H is intentionally not inferred"


def test_entity_fusion_manifest_never_understates_the_actual_pair_count() -> None:
    manifest = build_entity_fusion_deep_manifest(pair_count=30_001)

    assert manifest["unit_count"] == 30_001
    assert manifest["request_upper_bound"] == 180_015
