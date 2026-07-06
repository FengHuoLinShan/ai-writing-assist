#!/usr/bin/env python3
"""Analyze DeepSeek scene probe runs."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
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
    output_path = args.output or run_dir / "analysis.md"
    output_path.write_text(report, encoding="utf-8")
    print(report)
    print(f"\nanalysis={output_path}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze a DeepSeek probe run.")
    parser.add_argument(
        "run_dir",
        nargs="?",
        type=Path,
        default=None,
        help="Run directory. Defaults to tools/deepseek_scene_probe/runs/latest.",
    )
    parser.add_argument("--output", type=Path, default=None)
    return parser.parse_args()


def resolve_run_dir(path: Path | None) -> Path:
    if path is not None:
        return path
    latest = DEFAULT_RUNS / "latest"
    if not latest.exists():
        raise SystemExit(f"latest pointer not found: {latest}")
    return Path(latest.read_text(encoding="utf-8").strip())


def read_summary(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise SystemExit(f"summary not found: {path}")
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    if not rows:
        raise SystemExit(f"summary is empty: {path}")
    return rows


def build_report(run_dir: Path, rows: list[dict[str, Any]]) -> str:
    grouped: dict[tuple[str, int, int], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[group_key(row)].append(row)

    lines = [
        "# DeepSeek Scene Probe Analysis",
        "",
        f"- run: `{run_dir}`",
        f"- calls: {len(rows)}",
        "",
        "## Summary By Parameter Combo",
        "",
        "| prompt | batch size | overlap | calls | errors | avg seconds | avg scenes | avg density | avg cache hit | avg cache miss | length finishes |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    scored: list[tuple[float, str]] = []
    for key, group in sorted(grouped.items()):
        prompt, batch_size, overlap = key
        errors = [row for row in group if row.get("error_kind")]
        seconds = numeric_values(group, "elapsed_seconds")
        scenes = numeric_values(group, "scene_count")
        density = numeric_values(group, "scene_density")
        cache_hits = usage_values(group, "prompt_cache_hit_tokens")
        cache_misses = usage_values(group, "prompt_cache_miss_tokens")
        length_finishes = sum(1 for row in group if row.get("finish_reason") == "length")
        avg_density = mean(density) if density else 0.0
        avg_seconds = mean(seconds) if seconds else 0.0
        score = avg_density - (len(errors) * 0.5) - (length_finishes * 0.25)
        scored.append((score, f"{prompt} b={batch_size} o={overlap}"))
        lines.append(
            "| {prompt} | {batch_size} | {overlap} | {calls} | {errors} | "
            "{avg_seconds:.2f} | {avg_scenes:.2f} | {avg_density:.3f} | "
            "{avg_cache_hit:.0f} | {avg_cache_miss:.0f} | "
            "{length_finishes} |".format(
                prompt=prompt,
                batch_size=batch_size,
                overlap=overlap,
                calls=len(group),
                errors=len(errors),
                avg_seconds=avg_seconds,
                avg_scenes=mean(scenes) if scenes else 0.0,
                avg_density=avg_density,
                avg_cache_hit=mean(cache_hits) if cache_hits else 0.0,
                avg_cache_miss=mean(cache_misses) if cache_misses else 0.0,
                length_finishes=length_finishes,
            ),
        )

    lines.extend(["", "## Heuristic Ranking", ""])
    for score, label in sorted(scored, reverse=True):
        lines.append(f"- score={score:.3f}: {label}")

    lines.extend(["", "## Quality Samples", ""])
    for key, group in sorted(grouped.items()):
        prompt, batch_size, overlap = key
        lines.append(f"### {prompt} b{batch_size} o{overlap}")
        for row in sorted(group, key=row_sort_key):
            lines.append(
                "- {combo} {batch}: scenes={scenes} density={density} response=`{response}`".format(
                    combo=row.get("combo_label") or f"b{batch_size}_o{overlap}",
                    batch=row.get("batch_id"),
                    scenes=row.get("scene_count"),
                    density=row.get("scene_density"),
                    response=row.get("response_path"),
                ),
            )
            sample = scene_sample(row)
            if sample:
                lines.append(f"  sample: {sample}")

    low_density = [
        row
        for row in rows
        if row.get("scene_density") is not None and float(row["scene_density"]) < 0.6
    ]
    if low_density:
        lines.extend(["", "## Low Density Calls", ""])
        for row in low_density:
            lines.append(
                "- {combo} {prompt} {batch}: scenes={scenes} density={density} response={response}".format(
                    combo=row.get("combo_label"),
                    prompt=row.get("prompt_level"),
                    batch=row.get("batch_id"),
                    scenes=row.get("scene_count"),
                    density=row.get("scene_density"),
                    response=row.get("response_path"),
                ),
            )

    errors = [row for row in rows if row.get("error_kind")]
    if errors:
        lines.extend(["", "## Errors", ""])
        for row in errors:
            lines.append(
                "- {combo} {prompt} {batch}: {kind} {message}".format(
                    combo=row.get("combo_label"),
                    prompt=row.get("prompt_level"),
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
            "- `avg density` is `scene_count / owned_chapter_count`.",
            "- Density below `0.6` usually means the model summarized instead of slicing.",
            "- `finish_reason=length` means raise max tokens or simplify the prompt.",
            "- `avg cache hit/miss` comes from DeepSeek prompt cache usage fields.",
            "- Quality samples show the first few parsed scenes for each response.",
        ],
    )
    return "\n".join(lines) + "\n"


def group_key(row: dict[str, Any]) -> tuple[str, int, int]:
    input_range = row.get("input_range") or [0, 0]
    input_count = int(input_range[1]) - int(input_range[0]) + 1
    batch_size = int(row.get("batch_size") or input_count)
    overlap = int(row.get("overlap") or 0)
    return (str(row.get("prompt_level")), batch_size, overlap)


def row_sort_key(row: dict[str, Any]) -> tuple[int, str]:
    return (int(row.get("job_index") or 0), str(row.get("batch_id") or ""))


def scene_sample(row: dict[str, Any], *, limit: int = 4) -> str:
    scenes = scenes_from_row(row)
    if not scenes:
        return ""
    parts = []
    for scene in scenes[:limit]:
        if not isinstance(scene, dict):
            continue
        title = str(scene.get("title") or "untitled")
        start = scene.get("start_chapter") or scene.get("chapter_index") or "?"
        end = scene.get("end_chapter") or start
        status = scene.get("boundary_status") or ""
        suffix = f" {status}" if status else ""
        parts.append(f"{title}({start}-{end}{suffix})")
    return "; ".join(parts)


def scenes_from_row(row: dict[str, Any]) -> list[Any]:
    parsed = load_parsed(row.get("parsed_path"))
    if parsed is None:
        parsed = parse_response_file(row.get("response_path"))
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict) and isinstance(parsed.get("scenes"), list):
        return parsed["scenes"]
    return []


def load_parsed(path_value: Any) -> Any:
    if not path_value:
        return None
    path = Path(str(path_value))
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def parse_response_file(path_value: Any) -> Any:
    if not path_value:
        return None
    path = Path(str(path_value))
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8").strip()
    if text.startswith("```"):
        text = text.removeprefix("```json").removeprefix("```").strip()
        text = text.removesuffix("```").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def numeric_values(rows: list[dict[str, Any]], key: str) -> list[float]:
    values: list[float] = []
    for row in rows:
        value = row.get(key)
        if isinstance(value, int | float):
            values.append(float(value))
    return values


def usage_values(rows: list[dict[str, Any]], key: str) -> list[float]:
    values: list[float] = []
    for row in rows:
        usage = row.get("usage") or {}
        if not isinstance(usage, dict):
            continue
        value = usage.get(key)
        if isinstance(value, int | float):
            values.append(float(value))
    return values


if __name__ == "__main__":
    raise SystemExit(main())
