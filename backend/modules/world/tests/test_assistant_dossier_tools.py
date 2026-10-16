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
        "world.dossier.template.borrowed.read": ("profile_type",),
        "world.dossier.template.borrowed.edit": ("profile_type", "update"),
        "world.dossier.manifest.preview": ("entity_id", "request"),
        "world.dossier.manifest.apply": ("entity_id", "request"),
    }
    assert set(OPERATIONS_SPEC) == set(traced_fields)
    for name, operation in OPERATIONS_SPEC.items():
        schema = operation["schema"]
        expected_version = (
            "3"
            if name == "world.dossier.template.edit"
            else "1"
            if name
            in {
                "world.dossier.template.borrowed.read",
                "world.dossier.template.borrowed.edit",
                "world.dossier.manifest.preview",
                "world.dossier.manifest.apply",
            }
            else "2"
        )
        assert operation["op_version"] == expected_version
        assert operation.get("revision", "1") == expected_version
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
            assert operation["risk_level"] == (
                "R3"
                if name
                in {
                    "world.dossier.template.borrowed.edit",
                    "world.dossier.manifest.apply",
                }
                else "R2"
            )
            assert callable(operation["apply"])
