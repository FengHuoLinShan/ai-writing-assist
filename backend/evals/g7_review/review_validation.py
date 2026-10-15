"""Validate audit coverage/citations/horizon; exact quotes never prove semantics."""

import hashlib
import json

from .coverage_audit import filled
from .review_bindings import validate_snapshot_units

VERDICTS = {
    "supported",
    "structural_inference",
    "partial",
    "unsupported",
    "uncertain",
    "not_populated",
    "not_covered",
}


def require(test, why):
    if not test:
        raise ValueError(why)


def validate_response(case, response, *, snapshot, inventory, projects):
    bindings = validate_snapshot_units(case, snapshot, inventory, projects=projects)
    require(response.get("snapshot_hash") == case["snapshot_hash"], "snapshot_mismatch")
    expected = {u["id"]: u for u in case["units"]}
    require(len(expected) == len(case["units"]), "duplicate_input_unit")
    reviews = response.get("reviews", [])
    require(
        len(reviews) == len(expected) and {r["id"] for r in reviews} == set(expected),
        "unit_coverage_mismatch",
    )
    citation_count = 0
    for review in reviews:
        unit = expected[review["id"]]
        sources = {s["id"]: s for s in unit["sources"]}
        require(len(sources) == len(unit["sources"]), "ambiguous_source_ids")
        for source in sources.values():
            require(
                source["start_offset"] >= 0
                and source["end_offset"] > source["start_offset"]
                and len(source["text"]) == source["end_offset"] - source["start_offset"],
                "invalid_attached_range",
            )
            if unit.get("as_of"):
                cutoff = unit["as_of"]
                require(
                    (source["chapter_index"], source["end_offset"])
                    <= (cutoff["chapter_index"], cutoff["end_offset"]),
                    "future_source_attached",
                )
            require(
                hashlib.sha256(source["text"].encode()).hexdigest()
                == source["range_hash"],
                "attached_range_hash_mismatch",
            )
        if unit.get("holder_id") is not None:
            require(
                review.get("holder_id") == unit["holder_id"],
                "knowledge_holder_mismatch",
            )
        fields = {f["path"]: f for f in unit["fields"]}
        require(len(fields) == len(unit["fields"]), "duplicate_input_field")
        returned = review.get("fields", [])
        require(
            len(returned) == len(fields) and {f["path"] for f in returned} == set(fields),
            "field_coverage_mismatch",
        )
        for result in returned:
            field = fields[result["path"]]
            verdict = result["verdict"]
            quotes = result.get("quotes", [])
            require(
                verdict in VERDICTS and bool(result.get("reason", "").strip()),
                "invalid_verdict_or_reason",
            )
            require(
                (verdict == "not_populated") == (not filled(field["value"])),
                "empty_field_classification_mismatch",
            )
            if verdict == "supported" and field["kind"] == "semantic":
                require(bool(quotes), "supported_without_evidence")
            if verdict == "unsupported" and not unit.get("full_source_scope", False):
                require(
                    result.get("explicit_contradiction") is True and bool(quotes),
                    "partial_scope_cannot_prove_absence",
                )
            for quote in quotes:
                require(quote["source_id"] in sources, "citation_source_not_attached")
                source = sources[quote["source_id"]]
                start, end = quote["start_offset"], quote["end_offset"]
                require(
                    source["start_offset"] <= start < end <= source["end_offset"],
                    "citation_out_of_range",
                )
                local_start = start - source["start_offset"]
                local_end = end - source["start_offset"]
                require(
                    bool(quote["text"])
                    and source["text"][local_start:local_end] == quote["text"],
                    "citation_not_verbatim_at_offset",
                )
                citation_count += 1
    return {
        **bindings,
        "status": "model_review_bound_and_citations_checked",
        "snapshot_hash": case["snapshot_hash"],
        "units_reviewed": len(expected),
        "fields_reviewed": sum(len(u["fields"]) for u in expected.values()),
        "exact_citations": citation_count,
        "semantic_quality_verified_by_host": False,
        "same_model_bias": True,
        "human_validated": False,
        "review_hash": hashlib.sha256(
            json.dumps(response, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest(),
    }
