from types import SimpleNamespace

from modules.story.world_progression_context import _life_state_checks
from modules.story.world_progression_engine import (
    detect_progression_intersections,
    low_progress_advice,
    recommend_step_length,
)
from modules.story.world_progression_schemas import (
    ProgressionActorIntent,
    ProgressionBudgetPreviewRequest,
    ProgressionLocationTarget,
    ProgressionParticipant,
)
from modules.story.world_progression_tasks import (
    _check_movement_feasibility,
    _progression_source_gaps,
)
from modules.world.map_progression_state import _declaration_active_at


def test_intersections_use_only_equal_structured_identities() -> None:
    actions = [
        {
            "actor_id": "a",
            "location_target": {"kind": "map_node", "id": "same"},
            "target_object_id": "object-1",
            "resource_key": "resource-1",
            "journey_route_ids": ["route-1"],
            "information_recipient_ids": ["b"],
        },
        {
            "actor_id": "b",
            "location_target": {"kind": "map_node", "id": "same"},
            "target_object_id": "object-1",
            "resource_key": "resource-1",
            "journey_route_ids": ["route-1"],
            "information_recipient_ids": [],
        },
        {
            "actor_id": "c",
            "location_target": {"kind": "object", "id": "same"},
            "target_object_id": None,
            "resource_key": None,
            "journey_route_ids": [],
            "information_recipient_ids": [],
        },
    ]

    result = detect_progression_intersections(actions, route_comparison_available=True)

    pair = result["items"][0]
    assert pair["actor_ids"] == ["a", "b"]
    assert set(pair["kinds"]) == {
        "same_location_target",
        "same_target_object",
        "same_resource_key",
        "shared_existing_route",
        "information_recipient",
    }
    assert len(result["items"]) == 1


def test_intersections_explain_uncompared_routes_without_guessing() -> None:
    result = detect_progression_intersections(
        [
            {"actor_id": "a", "location_target": None, "journey_route_ids": ["r"]},
            {"actor_id": "b", "location_target": None, "journey_route_ids": ["r"]},
        ],
        route_comparison_available=False,
    )
    assert result["items"] == []
    assert result["route_comparison"] == "not_available"
    assert "路线未比较" in result["route_note"]


def test_step_recommendation_uses_only_persisted_matching_model_metrics() -> None:
    assert (
        recommend_step_length([], model_name="gpt-6-luna")["status"]
        == "insufficient_data"
    )
    measured = recommend_step_length(
        [
            {"model_name": "gpt-6-luna", "step_length": "week", "progress_score": 1},
            {"model_name": "gpt-6-luna", "step_length": "month", "progress_score": 3},
            {"model_name": "gpt-6-luna", "step_length": "month", "progress_score": 4},
            {"model_name": "other", "step_length": "year", "progress_score": 99},
        ],
        model_name="gpt-6-luna",
    )
    assert measured["step_length"] == "month"
    assert measured["sample_count"] == 3
    assert (
        low_progress_advice(
            [
                {"step_id": "s1", "progress_score": 0, "step_length": "week"},
                {"step_id": "s2", "progress_score": 0, "step_length": "week"},
            ]
        )["suggested_step_length"]
        == "month"
    )


def test_user_selected_steps_and_participant_count_have_no_product_ceiling() -> None:
    participants = [
        {"id": f"00000000-0000-0000-0000-{index:012d}", "kind": "character"}
        for index in range(1, 31)
    ]
    request = ProgressionBudgetPreviewRequest(
        novel_id="00000000-0000-0000-0000-000000000001",
        request_limit=2000,
        token_limit=1000000,
        time_budget_seconds=3600,
        participants=participants,
        run_policy="n_steps",
        steps=500,
    )
    assert len(request.participants) == 30
    assert request.steps == 500


def test_actor_move_requires_a_typed_destination_id() -> None:
    try:
        ProgressionActorIntent(
            actor_id="00000000-0000-0000-0000-000000000001",
            action="移动",
            basis_ids=["source-1"],
            effect="move",
        )
    except ValueError as exc:
        assert "结构化地点" in str(exc)
    else:
        raise AssertionError("untyped movement destination was accepted")


def test_life_status_requires_one_exact_confirmed_author_fact() -> None:
    participant = ProgressionParticipant(
        id="00000000-0000-0000-0000-000000000001", kind="character"
    )
    author_state = {
        "dimensions": [
            {
                "dimension": "entities",
                "status": "ok",
                "facts": [
                    {
                        "subject_id": participant.id,
                        "field": "life_status",
                        "layer": "fact",
                        "confidence": "confirmed",
                        "value": "alive",
                        "source": {"provenance": {"status": "exact", "event_id": "e1"}},
                    }
                ],
            }
        ]
    }
    assert _life_state_checks(author_state, [participant]) == [
        {
            "participant_id": participant.id,
            "status": "verified_typed_fact",
            "value": "alive",
            "event_id": "e1",
        }
    ]
    author_state["dimensions"][0]["facts"][0]["source"]["provenance"]["status"] = (
        "unverified"
    )
    assert _life_state_checks(author_state, [participant])[0]["status"] == "unknown"


def test_map_validity_override_uses_exact_story_identity() -> None:
    node_id = "00000000-0000-0000-0000-000000000010"
    revision_id = "00000000-0000-0000-0000-000000000011"
    declaration_id = "journey:road"
    identity = {
        "contract_version": 1,
        "node_id": node_id,
        "subject_id": "00000000-0000-0000-0000-000000000012",
        "declaration_kind": "journey",
        "declaration_id": declaration_id,
        "field_key": "effective_status",
        "revision_id": revision_id,
    }
    target = (node_id, revision_id, "journey", declaration_id)
    notice = {
        "validity_decision": "story_override",
        "notice_key": "world.object_validity:map:journey",
        "basis_fingerprint": "a" * 64,
        "evidence": [{"kind": "story_map_declaration", "identity_ref": identity}],
    }
    declaration = SimpleNamespace(id=declaration_id, effective=None)
    author_state = {
        "dimensions": [
            {
                "dimension": "entities",
                "facts": [
                    {
                        "subject_id": identity["subject_id"],
                        "field": identity["field_key"],
                        "layer": "fact",
                        "confidence": "confirmed",
                        "value": "inactive",
                        "source": {
                            "provenance": {
                                "status": "exact",
                                "identity_ref": identity,
                            }
                        },
                    }
                ],
            }
        ]
    }
    unknowns = []
    active, resolved = _declaration_active_at(
        declaration,
        node_id=node_id,
        revision_id=revision_id,
        kind="journey",
        scene_index=4,
        scenes=[],
        author_state=author_state,
        notices_by_target={target: notice},
        unknowns=unknowns,
    )
    assert active is False
    assert resolved is notice
    assert unknowns == []

    author_state["dimensions"][0]["facts"][0]["source"]["provenance"][
        "identity_ref"
    ] = {**identity, "revision_id": "00000000-0000-0000-0000-000000000099"}
    active, _ = _declaration_active_at(
        declaration,
        node_id=node_id,
        revision_id=revision_id,
        kind="journey",
        scene_index=4,
        scenes=[],
        author_state=author_state,
        notices_by_target={target: notice},
        unknowns=unknowns,
    )
    assert active is False
    assert any(item.startswith("map_validity_override_unreadable") for item in unknowns)


def test_map_validity_author_priority_uses_interval_and_gap_is_disclosed() -> None:
    declaration = SimpleNamespace(id="journey:road", effective=None)
    key = ("node-1", "rev-1", "journey", declaration.id)
    author_state = {"dimensions": []}
    author_priority = {
        "notice_key": "world.object_validity:map:node-1:journey:road",
        "validity_decision": "author_priority",
        "basis_fingerprint": "c" * 64,
        "target": {
            "node_id": key[0],
            "revision_id": key[1],
            "map_item_kind": key[2],
            "map_item_id": key[3],
        },
        "evidence": [],
    }
    unknowns = []
    active, resolved = _declaration_active_at(
        declaration,
        node_id=key[0],
        revision_id=key[1],
        kind=key[2],
        scene_index=4,
        scenes=[],
        author_state=author_state,
        notices_by_target={key: author_priority},
        unknowns=unknowns,
    )
    assert active is True
    assert resolved is author_priority
    assert unknowns == []

    gap = {**author_priority, "validity_decision": "gap"}
    active, _ = _declaration_active_at(
        declaration,
        node_id=key[0],
        revision_id=key[1],
        kind=key[2],
        scene_index=4,
        scenes=[],
        author_state=author_state,
        notices_by_target={key: gap},
        unknowns=unknowns,
    )
    assert active is True
    assert any(item.startswith("map_validity_gap") for item in unknowns)


def test_source_gaps_report_missing_typed_time_and_coverage() -> None:
    gaps = _progression_source_gaps(
        {
            "author_brief": {"coverage": "partial"},
            "map_state": {"unknowns": ["journey_type_unavailable:node:road"]},
            "life_state_checks": [
                {
                    "participant_id": "participant-1",
                    "status": "unknown",
                    "reason": "life_status_missing_or_ambiguous",
                }
            ],
            "time_basis": {"facts": []},
        }
    )
    assert "exact_cutoff_time_fact_missing" in gaps
    assert "author_evidence_coverage_incomplete" in gaps
    assert "journey_type_unavailable:node:road" in gaps
    assert any(item.startswith("life_state_unknown") for item in gaps)


def test_movement_requires_actor_visible_typed_direct_route() -> None:
    actor = "00000000-0000-0000-0000-000000000001"
    origin = "00000000-0000-0000-0000-000000000002"
    destination = "00000000-0000-0000-0000-000000000003"
    route_id = "b" * 64
    intent = ProgressionActorIntent(
        actor_id=actor,
        action="沿路前往",
        basis_ids=[route_id],
        location_target=ProgressionLocationTarget(kind="map_node", id=destination),
        journey_route_ids=[route_id],
        effect="move",
    )
    source = {
        "map_state": {
            "coverage": "available",
            "routes": [
                {
                    "route_ref_id": route_id,
                    "origin_kind": "map_node",
                    "origin_id": origin,
                    "destination_kind": "map_node",
                    "destination_id": destination,
                    "duration": {"minimum": 1, "maximum": 2, "unit": "day"},
                    "travel_type_evidence": [
                        {"type_ref": "type-1", "computable": True}
                    ],
                }
            ],
        },
        "time_basis": {"facts": [{"value": "第三日"}]},
    }
    state = {"locations": {f"object:{actor}": f"map_node:{origin}"}}
    role = {"known_route_ids": [route_id]}
    result = _check_movement_feasibility(
        intent, source=source, state=state, role=role, actor_id=actor
    )
    assert result["status"] == "route_evidence_available"
    assert result["route_ids"] == [route_id]
    assert result["outcome_rule"] == "finite_model_must_assess_time_and_conditions"

    route_without_duration = {
        **source,
        "map_state": {
            "coverage": "available",
            "routes": [
                {
                    **source["map_state"]["routes"][0],
                    "duration": None,
                }
            ],
        },
    }
    result = _check_movement_feasibility(
        intent, source=route_without_duration, state=state, role=role, actor_id=actor
    )
    assert result["status"] == "uncertain"
    assert result["reason"] == "typed_duration_or_travel_type_missing"

    result = _check_movement_feasibility(
        intent, source=source, state=state, role={"known_route_ids": []}, actor_id=actor
    )
    assert result["status"] == "uncertain"
    assert result["reason"] == "route_not_cited_or_not_visible"
