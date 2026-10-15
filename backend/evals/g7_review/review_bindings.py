"""Bind review inputs to immutable rows and draft ranges."""

import hashlib
import json

from .coverage_audit import latest_drafts


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def snapshot_hash(snapshot):
    # Match capture_final's exact JSON serialization, including original key order.
    return hashlib.sha256(
        json.dumps(snapshot, ensure_ascii=False, default=str).encode()
    ).hexdigest()


def field_value(row, path, columns):
    tokens = path.removeprefix("/").split("/")
    tokens = [token.replace("~1", "/").replace("~0", "~") for token in tokens]
    require(tokens[0] in columns and tokens[0] in row, "unknown_physical_field")
    value = row[tokens[0]]
    column_type = columns[tokens[0]]["data_type"]
    if len(tokens) > 1:
        require(
            column_type in {"json", "jsonb", "ARRAY"},
            "nested_path_on_non_json_column",
        )
    if column_type in {"json", "jsonb"} and isinstance(value, str):
        value = json.loads(value)
    for token in tokens[1:]:
        if isinstance(value, dict):
            require(token in value, "missing_json_field")
            value = value[token]
        elif isinstance(value, list):
            require(
                token.isdigit() and str(int(token)) == token and int(token) < len(value),
                "invalid_array_index",
            )
            value = value[int(token)]
        else:
            require(False, "nested_path_on_scalar")
    return value


def same_value(a, b):
    # Python equality equates False with 0; review provenance must distinguish them.
    return json.dumps(a, sort_keys=True, ensure_ascii=False, default=str) == json.dumps(
        b, sort_keys=True, ensure_ascii=False, default=str
    )


def validate_snapshot_units(case, snapshot, inventory, *, projects):
    require(
        bool(projects) and len(set(projects.values())) == len(projects),
        "invalid_project_manifest",
    )
    require(case["snapshot_hash"] == snapshot_hash(snapshot), "input_snapshot_mismatch")
    require(
        len({u["id"] for u in case["units"]}) == len(case["units"]),
        "duplicate_input_unit",
    )
    for unit in case["units"]:
        arm, table = unit["arm"], unit["table"]
        require(arm in projects and arm in snapshot, "unknown_review_arm")
        require(
            table in inventory["tables"] and table in snapshot[arm],
            "unknown_review_table",
        )
        columns = {c["column_name"]: c for c in inventory["tables"][table]["columns"]}
        primary = {
            k for k, c in columns.items() if "PRIMARY KEY" in c.get("constraints", [])
        }
        key = unit["row_key"]
        require(bool(primary) and set(key) == primary, "review_row_key_not_primary")
        rows = [
            row
            for row in snapshot[arm][table]
            if all(str(row.get(k)) == str(v) for k, v in key.items())
        ]
        require(len(rows) == 1, "review_row_missing_or_ambiguous")
        row = rows[0]
        require(str(row.get("novel_id")) == projects[arm], "review_cross_project_row")
        require(
            len({f["path"].removeprefix("/") for f in unit["fields"]})
            == len(unit["fields"]),
            "duplicate_input_field",
        )
        if unit.get("holder_id") is not None:
            require(
                isinstance(unit.get("holder_path"), str), "holder_field_binding_missing"
            )
            require(
                same_value(
                    field_value(row, unit["holder_path"], columns), unit["holder_id"]
                ),
                "review_holder_not_actual_row",
            )
        for field in unit["fields"]:
            require(field["kind"] in {"semantic", "metadata"}, "unknown_field_kind")
            require(
                same_value(field_value(row, field["path"], columns), field["value"]),
                "review_field_value_drift",
            )
        drafts = snapshot[arm]["writing_drafts"]
        require(
            len({s["id"] for s in unit["sources"]}) == len(unit["sources"]),
            "ambiguous_source_ids",
        )
        cutoff = unit.get("as_of")
        latest = latest_drafts(drafts)
        if cutoff:
            chapter, end = cutoff["chapter_index"], cutoff["end_offset"]
            require(
                type(chapter) is int
                and chapter in latest
                and type(end) is int
                and 0 <= end <= len(latest[chapter]["content"]),
                "invalid_input_cutoff",
            )
        for source in unit["sources"]:
            matched = [d for d in drafts if str(d["id"]) == str(source["draft_id"])]
            require(len(matched) == 1, "source_draft_missing_or_ambiguous")
            draft = matched[0]
            require(str(draft["novel_id"]) == projects[arm], "cross_project_source_draft")
            require(
                int(source["chapter_index"]) == int(draft["chapter_index"])
                and int(source["version_number"]) == int(draft["version_number"]),
                "source_chapter_or_version_mismatch",
            )
            content = draft["content"]
            require(
                source["content_hash"]
                == draft["content_hash"]
                == hashlib.sha256(content.encode()).hexdigest(),
                "source_draft_hash_mismatch",
            )
            start, end = source["start_offset"], source["end_offset"]
            require(
                type(start) is int
                and type(end) is int
                and 0 <= start < end <= len(content),
                "source_range_outside_actual_draft",
            )
            require(
                content[start:end] == source["text"],
                "source_text_not_actual_draft_range",
            )
            require(
                hashlib.sha256(source["text"].encode()).hexdigest()
                == source["range_hash"],
                "attached_range_hash_mismatch",
            )
            if cutoff:
                require(
                    (int(source["chapter_index"]), end)
                    <= (cutoff["chapter_index"], cutoff["end_offset"]),
                    "future_source_attached",
                )
        if unit.get("full_source_scope"):
            chapters = sorted(
                c for c in latest if not cutoff or c <= cutoff["chapter_index"]
            )
            require(bool(chapters), "full_source_scope_has_no_chapters")
            for chapter in chapters:
                draft = latest[chapter]
                end = (
                    cutoff["end_offset"]
                    if cutoff and chapter == cutoff["chapter_index"]
                    else len(draft["content"])
                )
                require(0 <= end <= len(draft["content"]), "invalid_full_scope_cutoff")
                ranges = sorted(
                    (s["start_offset"], s["end_offset"])
                    for s in unit["sources"]
                    if str(s["draft_id"]) == str(draft["id"])
                )
                covered = 0
                for start, stop in ranges:
                    require(start <= covered, "full_source_scope_gap")
                    covered = max(covered, stop)
                require(covered >= end, "full_source_scope_not_fully_attached")
    return {
        "actual_rows_bound": len(case["units"]),
        "actual_draft_sources_bound": True,
        "cutoff_enforcement_scope": "caller horizon; requires domain binding",
    }
