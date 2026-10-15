"""All physical fields and observed JSON paths. Presence is never accuracy."""

import hashlib
import json
import re
from collections import Counter, defaultdict

DYNAMIC = re.compile(
    r"(?:[a-f0-9]{64}|[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}|[0-9]+)\Z",
    re.IGNORECASE,
)


def filled(v):
    return v is not None and v != "" and v != [] and v != {}


def decoded(v, column):
    return (
        json.loads(v)
        if isinstance(v, str) and column["data_type"] in {"json", "jsonb"}
        else v
    )


def json_paths(v, path=""):
    yield path, type(v).__name__, filled(v)
    if isinstance(v, dict):
        for k, item in v.items():
            key = (
                "*"
                if DYNAMIC.fullmatch(str(k))
                else str(k).replace("~", "~0").replace("/", "~1")
            )
            yield from json_paths(item, path + "/" + key)
    elif isinstance(v, list):
        for item in v:
            yield from json_paths(item, path + "/*")


def latest_drafts(rows):
    result = {}
    for row in rows:
        chapter = int(row["chapter_index"])
        version = int(row["version_number"])
        previous = result.get(chapter)
        if (
            previous
            and version == int(previous["version_number"])
            and str(row["id"]) != str(previous["id"])
        ):
            raise ValueError("ambiguous latest draft version")
        if previous is None or version > int(previous["version_number"]):
            result[chapter] = row
    return result


def collect(snapshot, inventory, *, projects):
    if not projects or len(set(projects.values())) != len(projects):
        raise ValueError("explicit distinct project identities required")
    tables = inventory["tables"]
    output = {
        "captured_at": snapshot["captured_at"],
        "schema_tables": len(tables),
        "schema_columns": sum(len(s["columns"]) for s in tables.values()),
        "scope": "physical rows, statuses, JSON paths and explicit FK bindings only",
        "semantic_quality_verified": False,
        "human_validated": False,
        "same_model_review": False,
    }
    for arm, nid in projects.items():
        data = snapshot[arm]
        missing = set(tables) - set(data)
        if missing:
            raise ValueError("missing domain tables: " + ",".join(sorted(missing)))
        for rows in data.values():
            if any(str(r.get("novel_id")) != nid for r in rows if "novel_id" in r):
                raise ValueError("cross-project snapshot")
        result = {
            "tables": {},
            "foreign_key_findings": [],
            "foreign_key_not_checked": [],
            "field_presence_is_accuracy": False,
        }
        for table, spec in tables.items():
            rows = data[table]
            expected = {c["column_name"] for c in spec["columns"]}
            if any(set(r) != expected for r in rows):
                raise ValueError("schema/row columns differ: " + table)
            fields = {}
            nested = {}
            columns = {c["column_name"]: c for c in spec["columns"]}
            for name, c in columns.items():
                values = [decoded(r[name], c) for r in rows]
                fields[name] = {
                    "rows": len(rows),
                    "nonempty_rows": sum(filled(v) for v in values),
                    "null_rows": sum(v is None for v in values),
                    "value_types": dict(Counter(type(v).__name__ for v in values)),
                }
                if c["data_type"] in {"json", "jsonb"}:
                    stats = defaultdict(
                        lambda: {
                            "occurrences": 0,
                            "nonempty_occurrences": 0,
                            "rows_present": 0,
                            "types": Counter(),
                        }
                    )
                    for v in values:
                        seen = set()
                        for path, kind, present in json_paths(v):
                            entry = stats[path]
                            entry["occurrences"] += 1
                            entry["nonempty_occurrences"] += present
                            entry["types"][kind] += 1
                            seen.add(path)
                        for path in seen:
                            stats[path]["rows_present"] += 1
                    nested[name] = {
                        k: {**v, "types": dict(v["types"])}
                        for k, v in sorted(stats.items())
                    }
                for ref in c.get("references", []):
                    target = ref["target_table"]
                    target_column = ref["target_column"]
                    if target not in data:
                        result["foreign_key_not_checked"].append(
                            {
                                "table": table,
                                "column": name,
                                "target_table": target,
                                "nonempty_rows": sum(r[name] is not None for r in rows),
                                "reason": "target table outside snapshot; unchecked",
                            }
                        )
                        continue
                    ids = {str(r[target_column]) for r in data[target]}
                    bad = [
                        str(r.get("id", r.get("entity_id", "")))
                        for r in rows
                        if r[name] is not None and str(r[name]) not in ids
                    ]
                    if bad:
                        result["foreign_key_findings"].append(
                            {
                                "table": table,
                                "column": name,
                                "target_table": target,
                                "unresolved_rows": bad,
                                "meaning": "missing from snapshot; accuracy unchecked",
                            }
                        )
            states = {
                key: dict(Counter(str(r[key]) for r in rows))
                for key in (
                    "status",
                    "source",
                    "source_stale",
                    "stale",
                    "is_current",
                    "confirmed",
                )
                if key in columns
            }
            result["tables"][table] = {
                "rows": len(rows),
                "physical_fields": fields,
                "json_paths": nested,
                "state_distributions": states,
                "empty_means": "check workflow coverage and source facts",
            }
        if "writing_drafts" in data:
            latest = latest_drafts(data["writing_drafts"])
            result["latest_source_chapters"] = len(latest)
            result["latest_source_characters"] = sum(
                len(r["content"]) for r in latest.values()
            )
            result["source_hashes_valid"] = all(
                hashlib.sha256(r["content"].encode()).hexdigest() == r["content_hash"]
                for r in latest.values()
            )
        output[arm] = result
    return output
