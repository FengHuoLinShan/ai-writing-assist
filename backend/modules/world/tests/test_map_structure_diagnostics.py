"""Extraction quality receipts retain counts, never unvalidated model text."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError as SchemaError

from modules.world.map_structure_schemas import MapRelationBatch
from modules.world.map_structure_workflow import (
    check_extracted_relations,
    extraction_summary,
    relation_evidence,
    relation_prompt,
    structured_call_summary,
)


def relation(**changes):
    return {
        "subject": "company",
        "relation": "along_street",
        "target": "street",
        "evidence": [
            {"source_key": "address", "quote": "在测试街三号"},
            {"source_key": "sign", "quote": "牌上写着测试公司"},
        ],
        **changes,
    }


TEXTS = {"address": "房子在测试街三号", "sign": "门牌上写着测试公司"}


def test_per_source_evidence_supports_combination_without_relaxing_exact_quotes():
    model = MapRelationBatch(relations=[relation()])
    good, rejected = check_extracted_relations(
        model, {"company", "street"}, {"company"}, TEXTS
    )
    assert len(good) == 1 and rejected == {}
    assert len(relation_evidence(good[0])) == 2
    invalid = relation(
        evidence=[
            {"source_key": "address", "quote": "在测试街三号"},
            {"source_key": "sign", "quote": "在测试街三号"},
        ]
    )
    assert check_extracted_relations(
        MapRelationBatch(relations=[invalid]), {"company", "street"}, {"company"}, TEXTS
    ) == ([], {"quote_mismatch": 1})
    old = {
        "subject": "company",
        "relation": "along_street",
        "target": "street",
        "source_keys": ["address", "sign"],
        "quote": "在测试街三号",
    }
    assert check_extracted_relations(
        MapRelationBatch(relations=[old]), {"company", "street"}, {"company"}, TEXTS
    ) == ([], {"quote_mismatch": 1})


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"subject": "unknown"}, "unknown_feature"),
        ({"subject": "street", "target": "street"}, "outside_selection"),
        (
            {"evidence": [{"source_key": "foreign", "quote": "秘密内容"}]},
            "unknown_source",
        ),
        (
            {"evidence": [{"source_key": "sign", "quote": "不在来源的非法回答"}]},
            "quote_mismatch",
        ),
        ({"path_label": "臆造道路"}, "path_label_mismatch"),
    ],
)
def test_each_discard_class_is_counted_without_retaining_invalid_text(changes, expected):
    kept, reasons = check_extracted_relations(
        MapRelationBatch(relations=[relation(**changes)]),
        {"company", "street"},
        {"company"},
        TEXTS,
    )
    assert kept == [] and reasons == {expected: 1}
    assert "秘密内容" not in json.dumps(reasons, ensure_ascii=False)
    assert "非法回答" not in json.dumps(reasons, ensure_ascii=False)


def test_first_request_contains_schema_and_empty_object_is_not_a_completed_batch():
    with pytest.raises(SchemaError):
        MapRelationBatch.model_validate({})
    assert MapRelationBatch(relations=[]).relations == []
    prompt = relation_prompt([], [], {})
    assert '"required": ["relations"]' in prompt
    assert "MapRelationEvidence" in prompt
    assert "不能靠模型常识" in prompt


def test_safe_receipt_explains_failed_validation_and_structured_repair():
    diagnostic = structured_call_summary(
        [
            {
                "kind": "structured_usage",
                "status": "failed",
                "attempt": 1,
                "untrusted": "do not store",
            },
            {
                "kind": "partial_list_validation",
                "attempt": 2,
                "skipped": 2,
                "errors": [{"input": "do not store"}],
            },
            {"kind": "structured_usage", "status": "succeeded", "attempt": 2},
        ]
    )
    assert diagnostic == {
        "structured_attempts": 2,
        "format_retries": 1,
        "schema_discarded": 2,
    }
    batches = {
        "0": {
            "failed": False,
            "truncated": False,
            "received_relations": 3,
            "discarded": 3,
            "discard_reasons": {"quote_mismatch": 1, "invalid_schema": 2},
            "input_characters": 500,
            **diagnostic,
        }
    }
    receipt = extraction_summary([{}, {}], {"a": {}, "b": {}}, batches, 0)
    assert receipt["outcome"] == "no_supported_relations"
    assert receipt["received_relations"] == 3 and receipt["discarded_relations"] == 3
    assert receipt["structured_attempts"] == 2 and receipt["format_retries"] == 1
    assert "引文无法与各自来源对应" in receipt["message"]
    assert "do not store" not in json.dumps(receipt)


def test_preserved_manual_override_is_not_counted_as_accepted_extraction():
    from modules.world.map_structure_schemas import MapDocument, SpatialConstraint
    from modules.world.map_structure_workflow import retained_extraction_count

    features = [{"id": key, "kind": "location", "label": key} for key in ["a", "b"]]
    extracted = SpatialConstraint(id="same-id", subject="a", target="b", relation="north")
    manual = extracted.model_copy(update={"relation": "south"})
    assert (
        retained_extraction_count(
            MapDocument(features=features, constraints=[manual]), {"same-id": extracted}
        )
        == 0
    )
    assert (
        retained_extraction_count(
            MapDocument(features=features, constraints=[extracted]),
            {"same-id": extracted},
        )
        == 1
    )
