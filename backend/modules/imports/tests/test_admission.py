from __future__ import annotations

from modules.imports.admission import (
    IMPORT_RUN_REQUEST_LIMIT,
    build_entity_fusion_deep_manifest,
    build_scene_phase_manifest,
)
from modules.imports.tasks import (
    _review_resolution_run_request_limit,
    _targeted_completion_run_request_limit,
)
from modules.world.contracts import ENTITY_FUSION_CHECKPOINT_PAIR_BATCH_SIZE


class _Task:
    def __init__(self, authorization_snapshot):
        self.meta = {"authorization_snapshot": authorization_snapshot}


def test_scene_manifest_does_not_claim_a_finite_a_before_model_output() -> None:
    manifest = build_scene_phase_manifest(window_count=7)

    assert manifest["unit_count"] == 7
    assert manifest["batch_size"] == 1
    assert manifest["batch_count"] == 7
    assert manifest["request_upper_bound"] is None
    assert manifest["status"] == "segmented"
    assert manifest["safety_limit"] == IMPORT_RUN_REQUEST_LIMIT
    assert len(manifest["fingerprint"]) == 64


def test_entity_fusion_manifest_is_replayable_and_includes_audit() -> None:
    manifest = build_entity_fusion_deep_manifest(pair_count=30_000)

    assert manifest["unit_count"] == 30_000
    assert manifest["request_upper_bound"] == 180_009
    assert manifest["batch_size"] == ENTITY_FUSION_CHECKPOINT_PAIR_BATCH_SIZE
    assert manifest["batch_count"] == 2_500
    assert manifest["status"] == "segmented"
    assert manifest["safety_limit"] == IMPORT_RUN_REQUEST_LIMIT


def test_entity_fusion_manifest_never_understates_the_actual_pair_count() -> None:
    manifest = build_entity_fusion_deep_manifest(pair_count=30_001)

    assert manifest["unit_count"] == 30_001
    assert manifest["request_upper_bound"] == 180_015


def test_standalone_import_task_limits_use_frozen_authorization() -> None:
    targeted = _Task(
        {"targeted_completion": {"roots": [{"key": str(index)} for index in range(11)]}}
    )
    assert _targeted_completion_run_request_limit(targeted) == 63

    review = _Task(
        {
            "review_resolution": {
                "items": [
                    {"meta": {"scene_id": "a"}} for _ in range(33)
                ]
                + [{"meta": {"scene_id": "b"}}],
                "scene_items": [{}, {}],
            }
        }
    )
    assert _review_resolution_run_request_limit(review) == 130


def test_c3_import_tasks_share_one_bounded_parent_segment() -> None:
    from infrastructure.tasks.registry import get_registry

    registry = get_registry()
    for task_type in (
        "deep_import",
        "scene_auto_extraction",
        "world_object_auto_extraction",
        "plot_structure_auto_extraction",
    ):
        assert registry.get_root_capability(task_type) == "imports.deep_import"
        assert (
            registry.resolve_run_request_limit(task_type, _Task({}))
            == IMPORT_RUN_REQUEST_LIMIT
        )
