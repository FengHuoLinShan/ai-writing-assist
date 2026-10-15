from types import MappingProxyType, SimpleNamespace

from modules.evolution.optional_step_budget import (
    adjust_optional_quota,
    mandatory_requests_remaining,
    optional_call_block_reason,
    optional_quotas,
)
from modules.evolution.optional_steps import (
    OPTIONAL_READING_STEPS,
    optional_step_enabled,
)
from modules.evolution.workflow import ReadingRequest, _request_payload


def test_optional_step_registry_is_pure_immutable_data():
    assert isinstance(OPTIONAL_READING_STEPS, MappingProxyType)
    assert OPTIONAL_READING_STEPS["details"].request_field == "discover_details"
    assert OPTIONAL_READING_STEPS["details"].journal_prefix == "scene_discovery"
    assert OPTIONAL_READING_STEPS["spatial"].request_field == "discover_spatial"
    assert OPTIONAL_READING_STEPS["spatial"].journal_prefix == "scene_spatial"


def test_details_flag_keeps_legacy_api_default_and_explicit_opt_in():
    base = {
        "operation_id": "f16f8017-f7b1-4d0a-a88e-7cffb6759f6a",
        "end_chapter": 1,
        "budget_mode": "bounded",
        "request_limit": 10,
    }
    disabled = ReadingRequest(**base)
    enabled = ReadingRequest(**{**base, "discover_details": True})

    assert disabled.discover_details is False
    assert optional_step_enabled(disabled, "details") is False
    assert optional_step_enabled(enabled, "details") is True
    assert optional_step_enabled(disabled, "spatial") is False


def test_spatial_opt_in_preserves_legacy_request_shape_when_disabled():
    request = ReadingRequest(
        operation_id="f16f8017-f7b1-4d0a-a88e-7cffb6759f6a",
        end_chapter=1,
        request_limit=10,
    )
    assert "discover_spatial" not in _request_payload(request)


def test_spatial_enabled_steps_receive_finite_independent_quotas():
    plan = {"discovery_version": 2, "spatial_version": 1}
    first = optional_quotas(plan, additional_scenes=3)
    assert first["details"]["limit"] == 24
    assert first["spatial"]["limit"] == 6

    appended = optional_quotas(
        {**plan, "optional_step_quotas": first}, additional_scenes=1
    )
    assert appended["details"]["limit"] == 32
    assert appended["spatial"]["limit"] == 8
    assert appended["details"]["used"] == 0


def test_mandatory_reserve_uses_frozen_versions_and_known_followups():
    run = SimpleNamespace(
        committed_scene_index=-1,
        reading_plan_json={
            "mandatory_scene_calls": [
                {
                    "scene_index": 0,
                    "calls": {"scene_sample": 1, "world": 1, "enrichment": 2},
                },
                {"scene_index": 1, "calls": {"scene_sample": 1, "world": 1}},
            ],
            "structure_version": 0,
        },
    )
    current = {
        "stage": "verified",
        "scene_sample": {"stage": "sampled"},
        "scene_world": {"stage": "sampled"},
        "scene_enrichment": {"stage": "sampled"},
        "state_review_version": 1,
        "state_event_candidates": [{"event_type": "arrival"}],
        "relations_preparation": {"call": {"request": {}}},
        "world_review_preparation": {
            "groups": [{"group_id": "a" * 64, "spec": {"claim": 1}}]
        },
    }
    assert mandatory_requests_remaining(run, current) == 6

    current["scene_enrichment_review"] = {"stage": "sampled"}
    current["state_review"] = {"stage": "sampled"}
    current["scene_relations"] = {"stage": "sampled"}
    current[f"scene_world_review_group_{'a' * 64}"] = {"stage": "sampled"}
    assert mandatory_requests_remaining(run, current) == 2


def test_optional_quota_cannot_spend_main_reserve_or_peer_step_quota():
    plan = {
        "mandatory_scene_calls": [
            {"scene_index": 1, "calls": {"scene_sample": 1, "world": 1}}
        ],
        "optional_step_quotas": {
            "details": {"limit": 1, "used": 0, "remaining": 1},
            "spatial": {"limit": 2, "used": 0, "remaining": 2},
        },
    }
    run = SimpleNamespace(
        committed_scene_index=0, budget_remaining=1, reading_plan_json=plan
    )
    payload = {"scene_index": 1, "stage": "verified"}

    assert (
        optional_call_block_reason(run, payload, "details")
        == "main_understanding_reserve_protected"
    )
    run.budget_remaining = 2
    assert optional_call_block_reason(run, payload, "details") is None

    charged = adjust_optional_quota(plan, "details", 1)
    assert charged["optional_step_quotas"]["details"]["remaining"] == 0
    assert (
        charged["optional_step_quotas"]["spatial"]
        == plan["optional_step_quotas"]["spatial"]
    )
    run.reading_plan_json = charged
    run.budget_remaining = None  # confirmed_scope still obeys finite child quotas
    assert optional_call_block_reason(run, payload, "details") == "child_quota_exhausted"
    assert optional_call_block_reason(run, payload, "spatial") is None
