import copy
import hashlib
import json

import pytest

from evals.g7_review.review_bindings import snapshot_hash, validate_snapshot_units

from . import PROJECTS
from .test_review_validation import fixture


@pytest.mark.parametrize(
    "mutation,reason",
    [
        ("snapshot", "input_snapshot_mismatch"),
        ("field", "review_field_value_drift"),
        ("false_zero", "review_field_value_drift"),
        ("primary", "review_row_key_not_primary"),
        ("row_missing", "review_row_missing_or_ambiguous"),
        ("duplicate_row", "review_row_missing_or_ambiguous"),
        ("wrong_project_row", "review_cross_project_row"),
        ("field_missing", "unknown_physical_field"),
        ("holder", "review_holder_not_actual_row"),
        ("draft_missing", "source_draft_missing_or_ambiguous"),
        ("wrong_source_project", "cross_project_source_draft"),
        ("chapter", "source_chapter_or_version_mismatch"),
        ("version", "source_chapter_or_version_mismatch"),
        ("hash", "source_draft_hash_mismatch"),
        ("quote", "source_text_not_actual_draft_range"),
        ("range", "source_range_outside_actual_draft"),
        ("bool_offset", "source_range_outside_actual_draft"),
    ],
)
def test_input_cannot_spoof_actual_field_or_manuscript(mutation, reason):
    case, _, snapshot, inventory = fixture()
    unit = case["units"][0]
    source = unit["sources"][0]
    actual = snapshot["deep_import"]
    if mutation == "snapshot":
        actual["facts"][0]["knowledge"] = "改稿"
    elif mutation == "field":
        unit["fields"][0]["value"] = "伪造事实"
    elif mutation == "false_zero":
        unit["fields"][2]["value"] = 0
    elif mutation == "primary":
        unit["row_key"] = {"knowledge": "甲听说戒指属于丙"}
    elif mutation == "row_missing":
        unit["row_key"] = {"id": "absent"}
    elif mutation == "duplicate_row":
        actual["facts"].append(copy.deepcopy(actual["facts"][0]))
    elif mutation == "wrong_project_row":
        actual["facts"][0]["novel_id"] = "another"
    elif mutation == "field_missing":
        unit["fields"][0]["path"] = "invented"
    elif mutation == "holder":
        unit["holder_id"] = "乙"
    elif mutation == "draft_missing":
        source["draft_id"] = "absent"
    elif mutation == "wrong_source_project":
        actual["writing_drafts"][0]["novel_id"] = "another"
    elif mutation == "chapter":
        source["chapter_index"] = 2
    elif mutation == "version":
        source["version_number"] = 2
    elif mutation == "hash":
        source["content_hash"] = "wrong"
    elif mutation == "quote":
        source["text"] = "丙是戒指的所有者。"
        source["range_hash"] = hashlib.sha256(source["text"].encode()).hexdigest()
    elif mutation == "range":
        source["end_offset"] += 1
    else:
        source["start_offset"] = True
    if mutation != "snapshot":
        case["snapshot_hash"] = snapshot_hash(snapshot)
    with pytest.raises(ValueError, match=reason):
        validate_snapshot_units(case, snapshot, inventory, projects=PROJECTS)


def test_exact_json_leaf_preserves_false_and_pointer_escaping():
    case, _, snapshot, inventory = fixture()
    row = snapshot["deep_import"]["facts"][0]
    row["payload"] = json.dumps({"a/b~c": [False, 0]})
    inventory["tables"]["facts"]["columns"].append(
        {"column_name": "payload", "data_type": "jsonb"}
    )
    unit = case["units"][0]
    unit["fields"].append(
        {"path": "/payload/a~1b~0c/0", "kind": "semantic", "value": False}
    )
    case["snapshot_hash"] = snapshot_hash(snapshot)
    assert (
        validate_snapshot_units(case, snapshot, inventory, projects=PROJECTS)[
            "actual_rows_bound"
        ]
        == 1
    )
    unit["fields"][-1]["value"] = 0
    with pytest.raises(ValueError, match="review_field_value_drift"):
        validate_snapshot_units(case, snapshot, inventory, projects=PROJECTS)


@pytest.mark.parametrize("suffix", ["-1", "01", "2", "*"])
def test_array_paths_must_select_one_real_index(suffix):
    case, _, snapshot, inventory = fixture()
    snapshot["deep_import"]["facts"][0]["payload"] = '{"values":[1,2]}'
    inventory["tables"]["facts"]["columns"].append(
        {"column_name": "payload", "data_type": "jsonb"}
    )
    case["units"][0]["fields"].append(
        {"path": "/payload/values/" + suffix, "kind": "semantic", "value": 1}
    )
    case["snapshot_hash"] = snapshot_hash(snapshot)
    with pytest.raises(ValueError, match="invalid_array_index"):
        validate_snapshot_units(case, snapshot, inventory, projects=PROJECTS)


def test_partial_range_cannot_claim_full_source_scope():
    case, _, snapshot, inventory = fixture()
    case["units"][0]["full_source_scope"] = True
    with pytest.raises(ValueError, match="full_source_scope_gap"):
        validate_snapshot_units(case, snapshot, inventory, projects=PROJECTS)


def test_full_source_scope_covers_real_prefix_up_to_given_cutoff():
    case, _, snapshot, inventory = fixture()
    unit = case["units"][0]
    unit["full_source_scope"] = True
    prefix = {
        **unit["sources"][0],
        "id": "prefix",
        "start_offset": 0,
        "end_offset": 10,
        "text": "前" * 10,
    }
    prefix["range_hash"] = hashlib.sha256(prefix["text"].encode()).hexdigest()
    unit["sources"].append(prefix)
    assert validate_snapshot_units(case, snapshot, inventory, projects=PROJECTS)[
        "actual_draft_sources_bound"
    ]


@pytest.mark.parametrize(
    "mutation,reason",
    [
        ("holder_path", "holder_field_binding_missing"),
        ("duplicate_unit", "duplicate_input_unit"),
        ("duplicate_field", "duplicate_input_field"),
        ("duplicate_source", "ambiguous_source_ids"),
        ("range_hash", "attached_range_hash_mismatch"),
        ("future", "future_source_attached"),
        ("cutoff_missing_chapter", "invalid_input_cutoff"),
        ("cutoff_outside", "invalid_input_cutoff"),
    ],
)
def test_invalid_input_is_rejected_before_model_io(mutation, reason):
    case, _, snapshot, inventory = fixture()
    unit = case["units"][0]
    if mutation == "holder_path":
        unit.pop("holder_path")
    elif mutation == "duplicate_unit":
        case["units"].append(copy.deepcopy(unit))
    elif mutation == "duplicate_field":
        unit["fields"].append({**unit["fields"][0], "path": "/knowledge"})
    elif mutation == "duplicate_source":
        unit["sources"].append(copy.deepcopy(unit["sources"][0]))
    elif mutation == "range_hash":
        unit["sources"][0]["range_hash"] = "wrong"
    elif mutation == "future":
        unit["as_of"]["end_offset"] -= 1
    elif mutation == "cutoff_missing_chapter":
        unit["as_of"]["chapter_index"] = 2
    else:
        unit["as_of"]["end_offset"] += 1
    with pytest.raises(ValueError, match=reason):
        validate_snapshot_units(case, snapshot, inventory, projects=PROJECTS)
