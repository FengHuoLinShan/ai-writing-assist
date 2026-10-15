"""World dossier operation catalog entries stay pure until author confirmation."""

from modules.world.assistant_dossier_tools import OPERATIONS_SPEC


def test_dossier_operations_declare_inline_catalog_metadata() -> None:
    traced_fields = {
        "world.dossier.read": ("entity_id", "as_of_scene_id", "limit", "offset"),
        "world.dossier.history.read": ("entity_id", "entry_group_id", "limit", "offset"),
        "world.dossier.template.read": ("profile_type",),
        "world.dossier.entry.create": ("entity_id", "entry"),
        "world.dossier.entry.edit": ("entity_id", "revision_id", "update"),
        "world.dossier.entry.restore": ("entity_id", "entry_group_id", "restore"),
        "world.dossier.template.edit": ("profile_type", "update"),
    }
    assert set(OPERATIONS_SPEC) == set(traced_fields)
    for name, operation in OPERATIONS_SPEC.items():
        schema = operation["schema"]
        assert operation["op_version"] == "1"
        assert operation["fee_category"] == "free"
        assert operation["transaction_mode"] == "single_transaction"
        assert operation["trace_rule"] == {
            "parameter_fields": traced_fields[name],
            "mode": "per_call",
            "parameter_policy": "schema_safe",
        }
        assert set(traced_fields[name]) == set(schema.model_fields)
        if operation["permission"] == "read":
            assert operation["risk_level"] == "R0"
            assert "apply" not in operation
        else:
            assert operation["permission"] == "confirm"
            assert operation["risk_level"] == "R2"
            assert callable(operation["apply"])
