from modules.story.world_progression_engine import (
    detect_progression_intersections,
    low_progress_advice,
    recommend_step_length,
)
from modules.story.world_progression_schemas import (
    ProgressionActorIntent,
    ProgressionBudgetPreviewRequest,
)


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
