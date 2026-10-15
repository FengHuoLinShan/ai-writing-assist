"""World dossier operation catalog entries stay pure until author confirmation."""

from modules.world.assistant_dossier_tools import OPERATIONS_SPEC


def test_dossier_operations_declare_inline_catalog_metadata() -> None:
    assert set(OPERATIONS_SPEC) == {
        "world.dossier.read",
        "world.dossier.history.read",
        "world.dossier.template.read",
        "world.dossier.entry.create",
        "world.dossier.entry.edit",
        "world.dossier.entry.restore",
        "world.dossier.template.edit",
    }
    for operation in OPERATIONS_SPEC.values():
        schema = operation["schema"]
        assert operation["op_version"] == "1"
        assert operation["fee_category"] == "free"
        assert operation["transaction_mode"] == "single_transaction"
        assert operation["trace_rule"] == {
            "parameter_fields": tuple(schema.model_fields),
            "mode": "per_call",
            "parameter_policy": "schema_safe",
        }
        if operation["permission"] == "read":
            assert operation["risk_level"] == "R0"
            assert "apply" not in operation
        else:
            assert operation["permission"] == "confirm"
            assert operation["risk_level"] == "R2"
            assert callable(operation["apply"])
