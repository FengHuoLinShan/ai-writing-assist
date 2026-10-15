import pytest

from evals.g7_review.coverage_audit import collect, filled, json_paths, latest_drafts

from . import PROJECTS


def fixture():
    schema = {
        "tables": {
            "assets": {
                "columns": [
                    {"column_name": "id", "data_type": "uuid"},
                    {"column_name": "novel_id", "data_type": "uuid"},
                    {"column_name": "status", "data_type": "text"},
                    {"column_name": "payload", "data_type": "jsonb"},
                ]
            },
            "empty_capability": {
                "columns": [
                    {"column_name": "id", "data_type": "uuid"},
                    {"column_name": "novel_id", "data_type": "uuid"},
                ]
            },
        }
    }
    snap = {"captured_at": 1}
    for arm, nid in PROJECTS.items():
        snap[arm] = {
            "assets": [
                {
                    "id": "one",
                    "novel_id": nid,
                    "status": "draft",
                    "payload": (
                        '{"zero":0,"false":false,'
                        '"aliases":[{"alias":"甲"},{"alias":"乙"}]}'
                    ),
                }
            ],
            "empty_capability": [],
        }
    return snap, schema


def test_all_fields_and_empty_capabilities_are_covered_without_semantic_claim():
    snap, schema = fixture()
    out = collect(snap, schema, projects=PROJECTS)
    assert out["schema_columns"] == 6 and not out["semantic_quality_verified"]
    for arm in PROJECTS:
        record = out[arm]["tables"]["assets"]
        assert set(record["physical_fields"]) == {"id", "novel_id", "status", "payload"}
        assert record["state_distributions"]["status"] == {"draft": 1}
        assert out[arm]["tables"]["empty_capability"]["rows"] == 0
        assert record["json_paths"]["payload"]["/aliases/*/alias"]["occurrences"] == 2
        assert record["json_paths"]["payload"]["/aliases/*/alias"]["rows_present"] == 1
        assert record["json_paths"]["payload"]["/zero"]["nonempty_occurrences"] == 1
        assert record["json_paths"]["payload"]["/false"]["nonempty_occurrences"] == 1


@pytest.mark.parametrize(
    "mutation", ["missing_table", "missing_field", "extra_field", "wrong_project"]
)
def test_incomplete_or_cross_project_snapshot_fails_closed(mutation):
    snap, schema = fixture()
    row = snap["deep_import"]["assets"][0]
    if mutation == "missing_table":
        snap["deep_import"].pop("empty_capability")
    elif mutation == "missing_field":
        row.pop("status")
    elif mutation == "extra_field":
        row["unknown"] = "new"
    else:
        row["novel_id"] = "another"
    with pytest.raises(ValueError):
        collect(snap, schema, projects=PROJECTS)


def test_json_path_normalizes_ids_not_named_fields():
    paths = list(
        json_paths(
            {
                "123": {"alias": "甲"},
                "a/b~c": 0,
                "550e8400-e29b-41d4-a716-446655440000": {"alias": "乙"},
            }
        )
    )
    assert sum(p == "/*/alias" for p, _, _ in paths) == 2
    assert any(p == "/a~1b~0c" for p, _, _ in paths)


@pytest.mark.parametrize(
    "values", [[None, "", [], {}], [0, False, "0", [0], {"value": False}]]
)
def test_presence_preserves_boolean_and_zero(values):
    assert [filled(v) for v in values] == (
        [False] * 4 if len(values) == 4 else [True] * 5
    )


def test_latest_source_is_version_order_not_export_order():
    rows = [
        {"chapter_index": 1, "version_number": 3, "id": "new"},
        {"chapter_index": 1, "version_number": 1, "id": "old"},
    ]
    assert latest_drafts(rows)[1]["id"] == "new"
    with pytest.raises(ValueError):
        latest_drafts([rows[0], {**rows[0], "id": "other"}])


def test_fk_checks_current_project_snapshot_and_retains_unresolved():
    snap, schema = fixture()
    schema["tables"]["assets"]["columns"].append(
        {
            "column_name": "parent_id",
            "data_type": "uuid",
            "references": [{"target_table": "assets", "target_column": "id"}],
        }
    )
    for arm in PROJECTS:
        snap[arm]["assets"][0]["parent_id"] = "not-present"
    result = collect(snap, schema, projects=PROJECTS)
    assert len(result["deep_import"]["foreign_key_findings"]) == 1
    assert not result["deep_import"]["field_presence_is_accuracy"]


def test_invalid_json_is_not_silently_treated_as_empty():
    snap, schema = fixture()
    snap["deep_import"]["assets"][0]["payload"] = "unclosed {"
    with pytest.raises(ValueError):
        collect(snap, schema, projects=PROJECTS)


def test_missing_fk_target_is_unchecked_not_implied_valid():
    snap, schema = fixture()
    schema["tables"]["assets"]["columns"].append(
        {
            "column_name": "source_id",
            "data_type": "uuid",
            "references": [{"target_table": "not_exported", "target_column": "id"}],
        }
    )
    for arm in PROJECTS:
        snap[arm]["assets"][0]["source_id"] = "reference"
    report = collect(snap, schema, projects=PROJECTS)
    assert report["deep_import"]["foreign_key_findings"] == []
    assert report["deep_import"]["foreign_key_not_checked"][0]["nonempty_rows"] == 1
