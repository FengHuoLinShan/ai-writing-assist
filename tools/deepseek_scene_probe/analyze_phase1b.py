#!/usr/bin/env python3
"""Analyze Phase1b enrichment probe runs."""

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
    output_path = args.output or run_dir / "analysis_phase1b.md"
    output_path.write_text(report, encoding="utf-8")
    print(report)
    print(f"\nanalysis={output_path}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze a Phase1b probe run.")
    parser.add_argument("run_dir", nargs="?", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    return parser.parse_args()


def resolve_run_dir(path: Path | None) -> Path:
    if path is not None:
        return path
    latest = DEFAULT_RUNS / "latest-phase1b"
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
    fallbacks = [row for row in rows if row.get("fallback")]
    parse_ok = [row for row in rows if row.get("parse_ok")]
    length_finishes = [row for row in rows if row.get("finish_reason") == "length"]
    mismatches = sum(int(row.get("scene_chunks_mismatch_count") or 0) for row in rows)
    seconds = [
        float(row["elapsed_seconds"])
        for row in rows
        if isinstance(row.get("elapsed_seconds"), int | float)
    ]

    lines = [
        "# DeepSeek Phase1b Probe Analysis",
        "",
        f"- run: `{run_dir}`",
        f"- scenes: {len(rows)}",
        f"- parse_ok: {len(parse_ok)}",
        f"- errors: {len(errors)}",
        f"- fallbacks: {len(fallbacks)}",
        f"- length_finishes: {len(length_finishes)}",
        f"- scene_chunks_mismatch_count: {mismatches}",
        f"- avg_seconds: {mean(seconds):.2f}" if seconds else "- avg_seconds: 0.00",
        "",
        "## Quality Samples",
        "",
    ]
    for row in sorted(rows, key=lambda item: int(item.get("job_index") or 0))[:12]:
        final_scene = load_json_or_none(row.get("final_path")) or {}
        chapter_range = row.get("chapter_range") or ["?", "?"]
        lines.append(
            "- {scene_id} ch={start}-{end} parse_ok={parse_ok} fallback={fallback} "
            "review={review} final=`{final_path}`".format(
                scene_id=row.get("scene_id"),
                start=chapter_range[0],
                end=chapter_range[1],
                parse_ok=row.get("parse_ok"),
                fallback=row.get("fallback"),
                review=row.get("needs_review"),
                final_path=row.get("final_path"),
            ),
        )
        sample = enrichment_sample(final_scene)
        if sample:
            lines.append(f"  sample: {sample}")

    if fallbacks:
        lines.extend(["", "## Fallback Scenes", ""])
        for row in fallbacks:
            chapter_range = row.get("chapter_range") or ["?", "?"]
            lines.append(
                "- {scene_id} ch={start}-{end}: {reason}".format(
                    scene_id=row.get("scene_id"),
                    start=chapter_range[0],
                    end=chapter_range[1],
                    reason=row.get("fallback_reason"),
                ),
            )

    if errors:
        lines.extend(["", "## Errors", ""])
        for row in errors:
            lines.append(
                "- {scene_id}: {kind} {message}".format(
                    scene_id=row.get("scene_id"),
                    kind=row.get("error_kind"),
                    message=(row.get("error_message") or "")[:240],
                ),
            )

    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- Phase1b parses only enrichment fields.",
            "- Locked Scene fields and `scene_chunks` are copied/generated outside LLM output.",
            "- `scene_chunks_mismatch_count` should stay `0`.",
            "- Fallback scenes should enter manual review.",
        ],
    )
    return "\n".join(lines) + "\n"


def enrichment_sample(scene: dict[str, Any]) -> str:
    if not scene:
        return ""
    parts = []
    for key in ("emotional_beat", "must_happen", "must_not_happen", "narrative_tag"):
        value = str(scene.get(key) or "").strip()
        if value:
            parts.append(f"{key}={value[:40]}")
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
