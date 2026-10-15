from modules.story.assistant_generation_tools import OPERATIONS_SPEC


def test_card_and_reaction_operations_are_suggest_only_and_trace_exact_schema_fields():
    assert set(OPERATIONS_SPEC) == {
        "story.character_card.generate",
        "story.reaction.generate",
    }
    for spec in OPERATIONS_SPEC.values():
        assert spec["permission"] == "suggest"
        assert spec["risk_level"] == "R1"
        assert spec["fee_category"] == "possible_model_charge"
        assert spec["transaction_mode"] == "multi_stage"
        assert spec["trace_rule"]["parameter_fields"] == tuple(
            spec["schema"].model_fields
        )
        assert spec["trace_rule"]["parameter_policy"] == "schema_safe"
        assert callable(spec["read_result"])


def test_generation_operation_arguments_bind_scene_and_pov_targets():
    card = OPERATIONS_SPEC["story.character_card.generate"]["schema"]
    reaction = OPERATIONS_SPEC["story.reaction.generate"]["schema"]
    assert tuple(card.model_fields) == (
        "scene_id",
        "character_id",
        "additional_notes",
    )
    assert tuple(reaction.model_fields) == (
        "scene_id",
        "character_ids",
        "additional_notes",
    )
