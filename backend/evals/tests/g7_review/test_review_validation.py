import copy
import hashlib

import pytest

from evals.g7_review.review_bindings import snapshot_hash
from evals.g7_review.review_validation import validate_response

from . import PROJECTS


def fixture():
    text = "甲听见乙说戒指属于丙。"
    source = {
        "id": "s",
        "draft_id": "draft-1",
        "version_number": 1,
        "content_hash": hashlib.sha256(("前" * 10 + text).encode()).hexdigest(),
        "chapter_index": 1,
        "start_offset": 10,
        "end_offset": 10 + len(text),
        "text": text,
        "range_hash": hashlib.sha256(text.encode()).hexdigest(),
    }
    case = {
        "snapshot_hash": "immutable",
        "units": [
            {
                "id": "u",
                "arm": "deep_import",
                "table": "facts",
                "row_key": {"id": "u"},
                "holder_id": "甲",
                "holder_path": "holder",
                "as_of": {"chapter_index": 1, "end_offset": 10 + len(text)},
                "full_source_scope": False,
                "sources": [source],
                "fields": [
                    {
                        "path": "knowledge",
                        "value": "甲听说戒指属于丙",
                        "kind": "semantic",
                    },
                    {"path": "missing", "value": None, "kind": "semantic"},
                    {"path": "public_baseline", "value": False, "kind": "metadata"},
                ],
            }
        ],
    }
    response = {
        "snapshot_hash": "immutable",
        "reviews": [
            {
                "id": "u",
                "holder_id": "甲",
                "fields": [
                    {
                        "path": "knowledge",
                        "verdict": "supported",
                        "reason": "只核本合成句的听说归属，不宣称传言为真。",
                        "quotes": [
                            {
                                "source_id": "s",
                                "start_offset": 10,
                                "end_offset": 10 + len(text),
                                "text": text,
                            }
                        ],
                    },
                    {
                        "path": "missing",
                        "verdict": "not_populated",
                        "reason": "字段空",
                        "quotes": [],
                    },
                    {
                        "path": "public_baseline",
                        "verdict": "structural_inference",
                        "reason": "产品元数据，false非空。",
                        "quotes": [],
                    },
                ],
            }
        ],
    }
    snapshot = {
        "captured_at": 1,
        "deep_import": {
            "facts": [
                {
                    "id": "u",
                    "novel_id": PROJECTS["deep_import"],
                    "holder": "甲",
                    "knowledge": "甲听说戒指属于丙",
                    "missing": None,
                    "public_baseline": False,
                }
            ],
            "writing_drafts": [
                {
                    "id": "draft-1",
                    "novel_id": PROJECTS["deep_import"],
                    "chapter_index": 1,
                    "version_number": 1,
                    "content": "前" * 10 + text,
                    "content_hash": source["content_hash"],
                }
            ],
        },
    }
    inventory = {
        "tables": {
            "facts": {
                "columns": [
                    {
                        "column_name": k,
                        "data_type": "text",
                        "constraints": ["PRIMARY KEY"] if k == "id" else [],
                    }
                    for k in snapshot["deep_import"]["facts"][0]
                ]
            }
        }
    }
    case["snapshot_hash"] = response["snapshot_hash"] = snapshot_hash(snapshot)
    return case, response, snapshot, inventory


def test_exact_coverage_and_quotes_keep_model_bias_explicit():
    c, r, snapshot, inventory = fixture()
    p = validate_response(c, r, snapshot=snapshot, inventory=inventory, projects=PROJECTS)
    assert (
        p["exact_citations"] == 1
        and p["fields_reviewed"] == 3
        and p["same_model_bias"]
        and not p["semantic_quality_verified_by_host"]
        and not p["human_validated"]
    )


@pytest.mark.parametrize(
    "case",
    [
        "snapshot",
        "duplicate_unit",
        "missing_field",
        "extra_field",
        "holder",
        "quote_text",
        "quote_offset",
        "future_source",
        "attached_hash",
        "unsupported_absence",
        "empty_as_supported",
        "false_as_empty",
        "supported_no_quote",
    ],
)
def test_reject_invalid_review_bindings_and_scope(case):
    c, r, snapshot, inventory = fixture()
    u = c["units"][0]
    v = r["reviews"][0]
    field = v["fields"][0]
    q = field["quotes"][0]
    if case == "snapshot":
        r["snapshot_hash"] = "stale"
    elif case == "duplicate_unit":
        r["reviews"].append(copy.deepcopy(v))
    elif case == "missing_field":
        v["fields"].pop()
    elif case == "extra_field":
        v["fields"].append({**v["fields"][-1], "path": "not_requested"})
    elif case == "holder":
        v["holder_id"] = "乙"
    elif case == "quote_text":
        q["text"] = "甲其实知道真相"
    elif case == "quote_offset":
        q["start_offset"] = 9
    elif case == "future_source":
        u["as_of"]["end_offset"] -= 1
    elif case == "attached_hash":
        u["sources"][0]["range_hash"] = "different"
    elif case == "unsupported_absence":
        field["verdict"] = "unsupported"
        field["quotes"] = []
    elif case == "empty_as_supported":
        v["fields"][1]["verdict"] = "supported"
    elif case == "false_as_empty":
        v["fields"][2]["verdict"] = "not_populated"
    else:
        field["quotes"] = []
    with pytest.raises(ValueError):
        validate_response(c, r, snapshot=snapshot, inventory=inventory, projects=PROJECTS)


def test_partial_scope_contradiction_requires_explicit_source():
    c, r, snapshot, inventory = fixture()
    r["reviews"][0]["fields"][0].update(
        verdict="unsupported", explicit_contradiction=True
    )
    assert (
        validate_response(
            c, r, snapshot=snapshot, inventory=inventory, projects=PROJECTS
        )["exact_citations"]
        == 1
    )


def test_duplicate_field_cannot_hide_a_missing_requested_metric():
    c, r, snapshot, inventory = fixture()
    r["reviews"][0]["fields"][2] = copy.deepcopy(r["reviews"][0]["fields"][0])
    with pytest.raises(ValueError, match="field_coverage"):
        validate_response(c, r, snapshot=snapshot, inventory=inventory, projects=PROJECTS)
