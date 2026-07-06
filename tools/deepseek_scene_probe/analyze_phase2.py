#!/usr/bin/env python3
"""Analyze Phase2 world-extraction probe runs."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any

from phase23_common import duplicate_name_ratio


ROOT = Path(__file__).resolve().parent
DEFAULT_RUNS = ROOT / "runs"


def main() -> int:
    args = parse_args()
    run_dir = resolve_run_dir(args.run_dir)
    rows = read_summary(run_dir / "summary.jsonl")
    report = build_report(run_dir, rows)
    output_path = args.output or run_dir / "analysis_phase2.md"
    output_path.write_text(report, encoding="utf-8")
    print(report)
    print(f"\nanalysis={output_path}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze a Phase2 probe run.")
    parser.add_argument("run_dir", nargs="?", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    return parser.parse_args()


def resolve_run_dir(path: Path | None) -> Path:
    if path is not None:
        return path
    latest = DEFAULT_RUNS / "latest-phase2"
    if not latest.exists():
        raise SystemExit(f"latest pointer not found: {latest}")
    return Path(latest.read_text(encoding="utf-8").strip())


def read_summary(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise SystemExit(f"summary not found: {path}")
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    if not rows:
        raise SystemExit(f"summary is empty: {path}")
    return rows


def build_report(run_dir: Path, rows: list[dict[str, Any]]) -> str:
    errors = [row for row in rows if row.get("error_kind")]
    length_finishes = [row for row in rows if row.get("finish_reason") == "length"]
    parse_ok = [row for row in rows if row.get("parse_ok")]
    seconds = [
        float(row["elapsed_seconds"])
        for row in rows
        if isinstance(row.get("elapsed_seconds"), int | float)
    ]
    lines = [
        "# DeepSeek Phase2 Probe Analysis",
        "",
        f"- run: `{run_dir}`",
        f"- requests: {len(rows)}",
        f"- parse_ok: {len(parse_ok)}",
        f"- errors: {len(errors)}",
        f"- length_finishes: {len(length_finishes)}",
        f"- avg_seconds: {mean(seconds):.2f}" if seconds else "- avg_seconds: 0.00",
        "",
        "## By Combination",
        "",
        (
            "| combo | rows | ok | errors | length | objects | relations | deltas | "
            "invalid_refs | low_conf | dup_ratio | avg_s |"
        ),
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for combo, group in grouped(rows).items():
        payload = aggregate_group_payload(group)
        group_seconds = [
            float(row["elapsed_seconds"])
            for row in group
            if isinstance(row.get("elapsed_seconds"), int | float)
        ]
        lines.append(
            "| {combo} | {rows} | {ok} | {errors} | {length} | {objects} | "
            "{relations} | {deltas} | {invalid_refs} | {low_conf} | {dup} | {avg_s} |".format(
                combo=combo,
                rows=len(group),
                ok=sum(1 for row in group if row.get("parse_ok")),
                errors=sum(1 for row in group if row.get("error_kind")),
                length=sum(1 for row in group if row.get("finish_reason") == "length"),
                objects=len(payload.get("objects") or []),
                relations=len(payload.get("relations") or []),
                deltas=len(payload.get("deltas") or []),
                invalid_refs=sum(int(row.get("invalid_scene_ref_count") or 0) for row in group),
                low_conf=sum(int(row.get("low_confidence_count") or 0) for row in group),
                dup=duplicate_name_ratio(payload.get("objects") or []),
                avg_s=f"{mean(group_seconds):.2f}" if group_seconds else "0.00",
            ),
        )

    lines.extend(["", "## Quality Samples", ""])
    for combo, group in grouped(rows).items():
        lines.append(f"### {combo}")
        for row in sorted(group, key=lambda item: int(item.get("job_index") or 0))[:4]:
            payload = load_json_or_none(row.get("final_path")) or {}
            sample = phase2_sample(payload)
            input_range = row.get("input_range") or ["?", "?"]
            lines.append(
                "- batch={batch} input={start}-{end} ok={ok} finish={finish} "
                "final=`{final}` response=`{response}`".format(
                    batch=row.get("batch_id"),
                    start=input_range[0],
                    end=input_range[1],
                    ok=row.get("parse_ok"),
                    finish=row.get("finish_reason"),
                    final=row.get("final_path"),
                    response=row.get("response_path"),
                ),
            )
            if sample:
                lines.append(f"  sample: {sample}")
        lines.append("")

    if errors:
        lines.extend(["## Errors", ""])
        for row in errors:
            lines.append(
                "- {combo} {batch}: {kind} {message}".format(
                    combo=row.get("combo_label"),
                    batch=row.get("batch_id"),
                    kind=row.get("error_kind"),
                    message=(row.get("error_message") or "")[:240],
                ),
            )

    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- Prefer combinations with zero errors, zero `length`, and valid Scene refs.",
            "- `duplicate_name_ratio` is only a quick smoke signal, not final dedup quality.",
            "- Manual review should inspect whether objects are durable assets, not NER noise.",
        ],
    )
    return "\n".join(lines) + "\n"


def grouped(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[str(row.get("combo_label") or "unknown")].append(row)
    return dict(sorted(groups.items()))


def aggregate_group_payload(group: list[dict[str, Any]]) -> dict[str, list[Any]]:
    payload = {"objects": [], "relations": [], "deltas": [], "uncertain_items": []}
    for row in group:
        final = load_json_or_none(row.get("final_path"))
        if not isinstance(final, dict):
            continue
        for key in payload:
            values = final.get(key)
            if isinstance(values, list):
                payload[key].extend(values)
    return payload


def phase2_sample(payload: dict[str, Any]) -> str:
    parts = []
    objects = payload.get("objects") or []
    relations = payload.get("relations") or []
    deltas = payload.get("deltas") or []
    if objects:
        names = [str(item.get("name") or "") for item in objects[:5]]
        parts.append("objects=" + ", ".join(name for name in names if name))
    if relations:
        rels = [
            f"{item.get('source_name')}->{item.get('target_name')}"
            for item in relations[:3]
        ]
        parts.append("relations=" + ", ".join(rels))
    if deltas:
        names = [str(item.get("subject_name") or "") for item in deltas[:3]]
        parts.append("deltas=" + ", ".join(name for name in names if name))
    return "; ".join(parts)


def load_json_or_none(path_value: Any) -> Any:
    if not path_value:
        return None
    path = Path(str(path_value))
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


if __name__ == "__main__":
    raise SystemExit(main())
