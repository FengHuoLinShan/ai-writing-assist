from types import MappingProxyType, SimpleNamespace

import pytest

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
from modules.evolution.workflow import (
    ReadingRequest,
    _configure_spatial_authorization,
    _optional_coverage_summary,
    _request_payload,
)


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


def test_continue_preserves_spatial_child_quota_without_extending_it():
    quotas = {
        "details": {"version": 1, "limit": 16, "used": 4, "remaining": 12},
        "spatial": {"version": 1, "limit": 4, "used": 1, "remaining": 3},
    }
    plan = {
        "spatial_version": 1,
        "discovery_version": 2,
        "world_version": 0,
        "state_review_version": 0,
        "enrichment_version": 0,
        "structure_version": 0,
        "optional_step_quotas": quotas,
        "mandatory_scene_calls": [{"scene_index": 0, "calls": {"scene_sample": 1}}],
    }
    request = ReadingRequest(
        operation_id="f16f8017-f7b1-4d0a-a88e-7cffb6759f6a",
        end_chapter=2,
        request_limit=10,
        discover_spatial=True,
        discover_details=True,
    )

    _configure_spatial_authorization(
        plan,
        request,
        [{"scene_index": 1, "chapter_ids": [2]}],
        preserve_previous=True,
        add_quotas=False,
    )

    assert plan["optional_step_quotas"] == quotas
    assert [item["scene_index"] for item in plan["mandatory_scene_calls"]] == [0, 1]


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


def test_spatial_optional_calls_preserve_dynamic_review_and_structure_reserve():
    plan = {
        "mandatory_scene_calls": [
            {
                "scene_index": 0,
                "calls": {
                    "scene_sample": 1,
                    "world": 1,
                    "world_relations": 1,
                    "state_review": 1,
                    "enrichment": 2,
                },
            },
            {
                "scene_index": 1,
                "calls": {
                    "scene_sample": 1,
                    "world": 1,
                    "world_relations": 1,
                    "state_review": 1,
                },
            },
        ],
        "structure_version": 1,
        "structure": {"through_scene_index": -1, "complete": False},
        "steps": [{"scene_index": 0}, {"scene_index": 1}],
        "optional_step_quotas": {
            "details": {"limit": 1, "used": 0, "remaining": 1},
            "spatial": {"limit": 2, "used": 0, "remaining": 2},
        },
    }
    run = SimpleNamespace(
        committed_scene_index=-1,
        budget_remaining=10,
        reading_plan_json=plan,
    )
    current = {
        "scene_index": 0,
        "stage": "verified",
        "scene_sample": {"stage": "sampled"},
        "scene_world": {"stage": "sampled"},
        "world_result": {"context": {}},
        "scene_enrichment": {"stage": "sampled"},
        "state_review_version": 1,
        "state_event_candidates": [{"event_type": "arrival"}],
        "relations_preparation": {"call": {"request": {}}},
        "world_review_preparation": {
            "groups": [
                {"group_id": "a" * 64, "spec": {"claim": "left"}},
                {"group_id": "b" * 64, "spec": {"claim": "right"}},
            ]
        },
    }

    assert mandatory_requests_remaining(run, current) == 10
    assert (
        optional_call_block_reason(run, current, "spatial")
        == "main_understanding_reserve_protected"
    )
    run.budget_remaining = 11
    assert optional_call_block_reason(run, current, "details") is None


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


@pytest.mark.asyncio
@pytest.mark.parametrize("spatial_enabled", [False, True])
async def test_prepared_scenes_freeze_source_mode_only_for_spatial(
    monkeypatch, spatial_enabled
):
    import modules.evolution.preparation as preparation
    import modules.evolution.workflow as workflow

    captured = {}

    async def noop(*args, **kwargs):
        return None

    async def scenes(*args, **kwargs):
        return [{"scene_index": 4, "chapter_ids": [2]}]

    async def collect(*args, **kwargs):
        captured.update(kwargs)
        return [{"scene_index": 4, "source_binding": {}}]

    monkeypatch.setattr(preparation, "require_active_project_exclusive", noop)
    monkeypatch.setattr(preparation, "read_preparation_sources", noop)
    monkeypatch.setattr(preparation, "get_scenes_by_novel", scenes)
    monkeypatch.setattr(workflow, "collect_scene_steps", collect)

    class Db:
        async def flush(self):
            return None

    run = SimpleNamespace(
        reading_plan_json={
            "spatial_version": 1 if spatial_enabled else 0,
            "world_version": 0,
            "state_review_version": 0,
            "enrichment_version": 0,
            "steps": [],
            "mandatory_scene_calls": [],
            "preparation": {
                "sources": [{"chapter_index": 2}],
                "start_scene_index": 4,
                "stage": "pending",
            },
        }
    )

    await preparation.finish_preparation(Db(), "novel", run)

    assert captured["include_source_content_mode"] is spatial_enabled
    assert run.reading_plan_json["preparation"]["stage"] == "complete"


@pytest.mark.asyncio
async def test_spatial_coverage_projects_four_states_without_journal_identifiers():
    payloads = [
        {
            "scene_index": 0,
            "spatial_discovery_result": {"status": "inspected", "gaps": []},
            "optional_step_coverage": {"spatial": {"status": "inspected", "gaps": []}},
        },
        {
            "scene_index": 1,
            "spatial_discovery_result": {
                "status": "inspected",
                "gaps": [{"reason": "low_spatial_density"}],
            },
            "optional_step_coverage": {
                "spatial": {
                    "status": "inspected",
                    "gaps": [{"reason": "low_spatial_density"}],
                }
            },
        },
        {
            "scene_index": 2,
            "spatial_discovery_result": {
                "status": "unknown",
                "gaps": [
                    {
                        "reason": "request_requires_reconciliation",
                        "journal_key": "scene_spatial_discovery",
                    }
                ],
            },
            "optional_step_coverage": {
                "spatial": {
                    "status": "unknown",
                    "gaps": [
                        {
                            "reason": "request_requires_reconciliation",
                            "journal_key": "scene_spatial_discovery",
                        }
                    ],
                }
            },
        },
    ]

    class Store:
        async def load_committed_pairs(self, run_key):
            return [
                (
                    SimpleNamespace(committed_scene_index=index),
                    SimpleNamespace(payload_json=payload),
                )
                for index, payload in enumerate(payloads)
            ]

    run = SimpleNamespace(
        run_key="reading",
        status="active",
        reading_plan_json={
            "spatial_version": 1,
            "steps": [{"scene_index": index} for index in range(4)],
            "optional_step_quotas": {"spatial": {"limit": 8, "used": 3, "remaining": 5}},
        },
    )

    summary = await _optional_coverage_summary(Store(), run, None)

    assert summary["spatial"]["counts"] == {
        "inspected": 1,
        "density_skipped": 1,
        "gap": 1,
        "not_checked": 1,
    }
    assert summary["spatial"]["gaps"] == [
        {
            "scene_index": 2,
            "reason": "request_requires_reconciliation",
            "coverage": "gap",
        }
    ]
