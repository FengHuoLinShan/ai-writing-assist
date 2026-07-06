#!/usr/bin/env python3
"""Analyze Phase3 narrative-structure probe runs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean
from typing import Any


ROOT = Path(__file__).resolve().parent
DEFAULT_RUNS = ROOT / "runs"


def main() -> int:
    args = parse_args()
    run_dir = resolve_run_dir(args.run_dir)
    rows = read_summary(run_dir / "summary.jsonl")
    report = build_report(run_dir, rows)
    output_path = args.output or run_dir / "analysis_phase3.md"
    output_path.write_text(report, encoding="utf-8")
    print(report)
    print(f"\nanalysis={output_path}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze a Phase3 probe run.")
    parser.add_argument("run_dir", nargs="?", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    return parser.parse_args()


def resolve_run_dir(path: Path | None) -> Path:
    if path is not None:
        return path
    latest = DEFAULT_RUNS / "latest-phase3"
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
        "# DeepSeek Phase3 Probe Analysis",
        "",
        f"- run: `{run_dir}`",
        f"- requests: {len(rows)}",
        f"- parse_ok: {len(parse_ok)}",
        f"- errors: {len(errors)}",
        f"- length_finishes: {len(length_finishes)}",
        f"- avg_seconds: {mean(seconds):.2f}" if seconds else "- avg_seconds: 0.00",
        "",
        "## Combination Summary",
        "",
        (
            "| combo | ok | errors | length | threads | arcs | foreshadowing | "
            "reveals | turns | invalid_refs | low_conf | seconds |"
        ),
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in sorted(rows, key=lambda item: int(item.get("job_index") or 0)):
        lines.append(
            "| {combo} | {ok} | {errors} | {length} | {threads} | {arcs} | "
            "{foreshadowing} | {reveals} | {turns} | {invalid_refs} | "
            "{low_conf} | {seconds} |".format(
                combo=row.get("combo_label"),
                ok=1 if row.get("parse_ok") else 0,
                errors=1 if row.get("error_kind") else 0,
                length=1 if row.get("finish_reason") == "length" else 0,
                threads=row.get("plot_thread_count"),
                arcs=row.get("arc_count"),
                foreshadowing=row.get("foreshadowing_count"),
                reveals=row.get("reveal_count"),
                turns=row.get("turning_point_count"),
                invalid_refs=row.get("invalid_scene_ref_count"),
                low_conf=row.get("low_confidence_count"),
                seconds=row.get("elapsed_seconds"),
            ),
        )

    lines.extend(["", "## Quality Samples", ""])
    for row in sorted(rows, key=lambda item: int(item.get("job_index") or 0)):
        payload = load_json_or_none(row.get("final_path")) or {}
        sample = phase3_sample(payload)
        lines.append(
            "- {combo} ok={ok} finish={finish} final=`{final}` response=`{response}`".format(
                combo=row.get("combo_label"),
                ok=row.get("parse_ok"),
                finish=row.get("finish_reason"),
                final=row.get("final_path"),
                response=row.get("response_path"),
            ),
        )
        if sample:
            lines.append(f"  sample: {sample}")

    if errors:
        lines.extend(["", "## Errors", ""])
        for row in errors:
            lines.append(
                "- {combo}: {kind} {message}".format(
                    combo=row.get("combo_label"),
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
            "- Manual review should check for future spoilers beyond the input range.",
            "- `scenes_plus_world` is only better if it adds structure without hallucination.",
        ],
    )
    return "\n".join(lines) + "\n"


def phase3_sample(payload: dict[str, Any]) -> str:
    parts = []
    for key, label in (
        ("plot_threads", "threads"),
        ("arcs", "arcs"),
        ("foreshadowing", "foreshadowing"),
        ("reveals", "reveals"),
        ("turning_points", "turns"),
    ):
        items = payload.get(key) or []
        if items:
            titles = [
                str(item.get("title") or item.get("character_name") or "")
                for item in items[:4]
            ]
            parts.append(f"{label}=" + ", ".join(title for title in titles if title))
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
