"""A1 additions are complete, versioned specs before root registry wiring."""

from app.assistant_operation_registry import _materialize
from modules.evidence.assistant_read_operations import (
    OPERATIONS_SPEC as EVIDENCE_A1,
)
from modules.evolution.assistant_tools import OPERATIONS_SPEC as EVOLUTION
from modules.story.assistant_scene_operations import OPERATIONS_SPEC as STORY_A1
from modules.world.assistant_author_operations import OPERATIONS_SPEC as WORLD_A1
from modules.writing.assistant_a1_operations import OPERATIONS_SPEC as WRITING_A1


def test_a1_catalog_specs_materialize_with_privacy_and_risk_contracts() -> None:
    specs = {
        **WORLD_A1,
        **STORY_A1,
        **WRITING_A1,
        **EVIDENCE_A1,
        "evolution.prepare_reading": EVOLUTION["evolution.prepare_reading"],
    }

    assert len(specs) == 15
    operations = _materialize(specs)
    assert set(operations) == set(specs)
    for op_id, operation in operations.items():
        assert operation.op_id == op_id
        assert operation.op_version == "1"
        assert operation.risk_level in {"R0", "R1", "R2", "R3", "R4"}
        assert operation.fee_category == "free"
        assert operation.trace_rule.parameter_fields == tuple(
            operation.schema.model_fields
        )
        if operation.permission == "read":
            assert operation.risk_level == "R0"
            assert operation.apply is None
        if operation.risk_level in {"R3", "R4"}:
            assert operation.permission == "confirm"
        if operation.permission != "read":
            assert operation.apply is not None
        assert operation.transaction_mode == "single_transaction"


def test_story_information_edits_and_existing_evolution_previews_are_reused() -> None:
    from modules.story.assistant_information_tools import OPERATIONS_SPEC as STORY_INFO

    assert set(STORY_INFO) == {"story.edit_information_plan"}
    assert set(EVOLUTION) == {
        "evolution.prepare_reading",
        "evolution.prepare_spatial_reading",
        "evolution.prepare_spatial_rescan",
    }
    assert (
        EVOLUTION["evolution.prepare_reading"]["prepare"]
        is EVOLUTION["evolution.prepare_spatial_reading"]["prepare"]
    )
    assert (
        EVOLUTION["evolution.prepare_reading"]["apply"]
        is EVOLUTION["evolution.prepare_spatial_reading"]["apply"]
    )


def test_a1_trace_rules_never_persist_free_text_or_nested_decisions() -> None:
    from modules.assistant.operation_trace_service import _parameter_summary

    operations = _materialize(
        {
            "world.history.set_note": WORLD_A1["world.history.set_note"],
            "world.entity.fuse": WORLD_A1["world.entity.fuse"],
        }
    )
    private_note = "只供作者阅读的私密历史说明"
    note_summary = _parameter_summary(
        operations["world.history.set_note"],
        "novel-id",
        "test-project-salt",
        {
            "target_kind": "entity",
            "revision_id": "not-a-uuid",
            "note": private_note,
        },
    )
    assert private_note not in str(note_summary)
    assert note_summary["fields"]["note"]["length"] == len(private_note)
    assert note_summary["fields"]["note"]["project_hash"]

    fusion_text = "不进入留痕的作者别名"
    fusion_summary = _parameter_summary(
        operations["world.entity.fuse"],
        "novel-id",
        "test-project-salt",
        {"suggestions": [{"alias": fusion_text}]},
    )
    assert fusion_text not in str(fusion_summary)
    assert fusion_summary["fields"]["suggestions"]["type"] == "array"
