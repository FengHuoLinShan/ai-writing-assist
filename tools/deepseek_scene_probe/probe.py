#!/usr/bin/env python3
"""Standalone DeepSeek scene-extraction probe.

This tool is intentionally isolated from the project backend. It does not import
application modules, does not write the database, and keeps benchmark output
under this tool's ignored ``runs/`` directory by default.
"""

from __future__ import annotations

import argparse
import json
import re
import ssl
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

try:
    import certifi
except ImportError:  # pragma: no cover - optional local CA helper.
    certifi = None


ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG = ROOT / "config.example.json"
DEFAULT_PROMPTS = ROOT / "prompts"
DEFAULT_OUTPUT_DIR = ROOT / "runs"
CHAPTER_RE = re.compile(
    r"^第([一二三四五六七八九十百千万零〇0-9]+)章[ \t]*(.*)$",
    re.MULTILINE,
)


@dataclass(frozen=True)
class Chapter:
    index: int
    title: str
    body: str


@dataclass(frozen=True)
class Batch:
    batch_id: str
    input_start: int
    input_end: int
    owned_start: int
    owned_end: int
    overlap_start: int | None
    overlap_end: int | None


@dataclass(frozen=True)
class ProbeJob:
    job_index: int
    batch_size: int
    overlap: int
    combo_label: str
    prompt_level: str
    prompt_template: str
    batch: Batch
    round_label: str


def main() -> int:
    args = parse_args()
    config = load_json(args.config)
    chapters = read_chapters(args.source)
    selected = [
        chapter
        for chapter in chapters
        if args.chapter_start <= chapter.index <= args.chapter_end
    ]
    if not selected:
        raise SystemExit(
            f"no chapters found in range {args.chapter_start}-{args.chapter_end}",
        )

    prompt_levels = split_csv(args.prompt_levels)
    batch_sizes = [int(item) for item in split_csv(args.batch_sizes)]
    overlaps = [int(item) for item in split_csv(args.overlaps)]
    concurrency = int(args.concurrency)
    if concurrency < 1:
        raise SystemExit("concurrency must be >= 1")
    if args.print_stream and concurrency > 1:
        raise SystemExit("--print-stream requires --concurrency 1")
    rounds = args.rounds or int(config.get("rounds") or 1)
    if rounds < 1:
        raise SystemExit("rounds must be >= 1")
    fusion_enabled = bool(config.get("fusion_enabled")) or bool(args.fusion)
    if args.no_fusion:
        fusion_enabled = False
    fusion_prompt_name = args.fusion_prompt or str(
        config.get("fusion_prompt") or "fusion",
    )
    fusion_max_tokens = args.fusion_max_tokens or int(
        config.get("fusion_max_tokens") or 0,
    )
    run_id = args.run_name or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    config["_run_user_id"] = run_user_id(config, run_id)
    output_dir = args.output_dir / safe_filename(run_id)
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output_dir / "summary.jsonl"
    summary_path.write_text("", encoding="utf-8")
    write_latest_pointer(args.output_dir / "latest", output_dir)
    api_key = str(config.get("api_key") or "").strip()

    write_run_metadata(
        output_dir / "run_meta.json",
        args=args,
        config=config,
        run_id=run_id,
        chapters=selected,
        batch_sizes=batch_sizes,
        overlaps=overlaps,
        prompt_levels=prompt_levels,
        rounds=rounds,
        fusion_enabled=fusion_enabled,
        fusion_prompt_name=fusion_prompt_name,
        fusion_max_tokens=fusion_max_tokens,
        concurrency=concurrency,
    )

    print(f"probe_run={run_id}")
    print(f"chapters={selected[0].index}-{selected[-1].index} count={len(selected)}")
    print(f"dry_run={args.dry_run}")
    print(f"rounds={rounds} fusion={fusion_enabled} concurrency={concurrency}")
    print(f"summary={summary_path}")

    prompt_templates = {
        prompt_level: load_prompt(prompt_level, args.prompt_dir)
        for prompt_level in prompt_levels
    }
    jobs = build_probe_jobs(
        chapter_start=args.chapter_start,
        chapter_end=args.chapter_end,
        batch_sizes=batch_sizes,
        overlaps=overlaps,
        prompt_templates=prompt_templates,
        rounds=rounds,
        limit_batches=args.limit_batches,
        matrix_filter=args.matrix_filter,
    )
    print(f"jobs={len(jobs)}")

    metrics = execute_probe_jobs(
        jobs,
        config=config,
        api_key=api_key,
        chapters=chapters,
        output_dir=output_dir,
        max_tokens_override=args.max_tokens,
        dry_run=args.dry_run,
        print_stream=args.print_stream,
        concurrency=concurrency,
        summary_path=summary_path,
    )

    if fusion_enabled and rounds >= 2:
        fusion_template = load_prompt(fusion_prompt_name, args.prompt_dir)
        fusion_metrics = execute_fusion_jobs(
            metrics,
            config=config,
            api_key=api_key,
            fusion_template=fusion_template,
            output_dir=output_dir,
            max_tokens_override=fusion_max_tokens,
            dry_run=args.dry_run,
            print_stream=args.print_stream,
            concurrency=concurrency,
            summary_path=summary_path,
        )
        metrics.extend(fusion_metrics)

    metrics = sorted(metrics, key=metric_sort_key)
    write_jsonl(summary_path, metrics)
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark DeepSeek scene extraction prompts on chapter ranges.",
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--chapter-start", type=int, default=1)
    parser.add_argument("--chapter-end", type=int, default=20)
    parser.add_argument("--batch-sizes", default="20")
    parser.add_argument("--overlaps", default="3")
    parser.add_argument("--prompt-levels", default="minimal,medium,detailed")
    parser.add_argument("--prompt-dir", type=Path, default=DEFAULT_PROMPTS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--run-name",
        default="",
        help="Optional stable run directory name under --output-dir.",
    )
    parser.add_argument("--limit-batches", type=int, default=0)
    parser.add_argument("--max-tokens", type=int, default=0)
    parser.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help="Number of independent probe requests to run concurrently.",
    )
    parser.add_argument(
        "--matrix-filter",
        choices=["phase1a-overlap", "none"],
        default="phase1a-overlap",
        help=(
            "Filter low-value parameter combinations. phase1a-overlap skips "
            "overlap=2 for batch sizes above 20."
        ),
    )
    parser.add_argument(
        "--rounds",
        type=int,
        default=0,
        help="Repeat each prompt/batch N times. Defaults to config.rounds or 1.",
    )
    parser.add_argument(
        "--fusion",
        action="store_true",
        help="After 2+ rounds, ask the model to fuse candidate scene lists.",
    )
    parser.add_argument(
        "--no-fusion",
        action="store_true",
        help="Disable config.fusion_enabled for this run.",
    )
    parser.add_argument(
        "--fusion-prompt",
        default="",
        help="Prompt template name or path for fusion. Defaults to config.fusion_prompt.",
    )
    parser.add_argument(
        "--fusion-max-tokens",
        type=int,
        default=0,
        help="Override max_tokens for fusion calls.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build prompts and metrics without calling DeepSeek.",
    )
    parser.add_argument(
        "--print-stream",
        action="store_true",
        help="Print streamed model text while receiving it.",
    )
    return parser.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise SystemExit(f"config must be a JSON object: {path}")
    return data


def split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def read_chapters(source: Path) -> list[Chapter]:
    text = source.read_text(encoding="utf-8", errors="ignore")
    matches = list(CHAPTER_RE.finditer(text))
    if not matches:
        raise SystemExit(f"no chapter headings matched in {source}")
    chapters: list[Chapter] = []
    for pos, match in enumerate(matches):
        start = match.start()
        end = matches[pos + 1].start() if pos + 1 < len(matches) else len(text)
        raw = text[start:end].strip()
        first_newline = raw.find("\n")
        body = raw[first_newline + 1 :].strip() if first_newline >= 0 else ""
        chapters.append(
            Chapter(
                index=chinese_int(match.group(1)),
                title=match.group(2).strip(),
                body=body,
            ),
        )
    return chapters


def chinese_int(value: str) -> int:
    if value.isdigit():
        return int(value)
    digits = {
        "零": 0,
        "〇": 0,
        "一": 1,
        "二": 2,
        "两": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
    }
    units = {"十": 10, "百": 100, "千": 1000, "万": 10000}
    total = 0
    section = 0
    number = 0
    for char in value:
        if char in digits:
            number = digits[char]
        elif char in units:
            unit = units[char]
            if unit == 10000:
                total += (section + number) * unit
                section = 0
            else:
                section += (number or 1) * unit
            number = 0
    return total + section + number


def build_batches(
    start: int,
    end: int,
    *,
    batch_size: int,
    overlap: int,
) -> list[Batch]:
    if batch_size < 1:
        raise SystemExit("batch size must be positive")
    if overlap < 0:
        raise SystemExit("overlap must be >= 0")
    if overlap >= batch_size:
        raise SystemExit("overlap must be smaller than batch size")
    batches: list[Batch] = []
    current = start
    index = 1
    while current <= end:
        input_start = current
        input_end = min(current + batch_size - 1, end)
        if input_end == end:
            owned_end = input_end
        else:
            owned_end = max(input_start, input_end - overlap)
        overlap_start = owned_end + 1 if owned_end < input_end else None
        overlap_end = input_end if overlap_start is not None else None
        batches.append(
            Batch(
                batch_id=f"B{index:04d}-{input_start}-{input_end}",
                input_start=input_start,
                input_end=input_end,
                owned_start=input_start,
                owned_end=owned_end,
                overlap_start=overlap_start,
                overlap_end=overlap_end,
            ),
        )
        current = owned_end + 1
        index += 1
    return batches


def build_probe_jobs(
    *,
    chapter_start: int,
    chapter_end: int,
    batch_sizes: list[int],
    overlaps: list[int],
    prompt_templates: dict[str, str],
    rounds: int,
    limit_batches: int,
    matrix_filter: str,
) -> list[ProbeJob]:
    jobs: list[ProbeJob] = []
    job_index = 1
    for batch_size in batch_sizes:
        for overlap in overlaps:
            if not should_run_combo(batch_size, overlap, matrix_filter):
                continue
            batches = build_batches(
                chapter_start,
                chapter_end,
                batch_size=batch_size,
                overlap=overlap,
            )
            if limit_batches:
                batches = batches[:limit_batches]
            combo_label = combo_label_for(batch_size, overlap)
            for prompt_level, prompt_template in prompt_templates.items():
                for batch in batches:
                    for round_index in range(1, rounds + 1):
                        round_label = f"r{round_index:02d}" if rounds > 1 else ""
                        jobs.append(
                            ProbeJob(
                                job_index=job_index,
                                batch_size=batch_size,
                                overlap=overlap,
                                combo_label=combo_label,
                                prompt_level=prompt_level,
                                prompt_template=prompt_template,
                                batch=batch,
                                round_label=round_label,
                            ),
                        )
                        job_index += 1
    return jobs


def should_run_combo(batch_size: int, overlap: int, matrix_filter: str) -> bool:
    if matrix_filter == "none":
        return True
    if matrix_filter == "phase1a-overlap":
        return batch_size <= 20 or overlap != 2
    raise SystemExit(f"unknown matrix filter: {matrix_filter}")


def combo_label_for(batch_size: int, overlap: int) -> str:
    return f"b{batch_size}_o{overlap}"


def execute_probe_jobs(
    jobs: list[ProbeJob],
    *,
    config: dict[str, Any],
    api_key: str,
    chapters: list[Chapter],
    output_dir: Path,
    max_tokens_override: int,
    dry_run: bool,
    print_stream: bool,
    concurrency: int,
    summary_path: Path,
) -> list[dict[str, Any]]:
    if concurrency == 1:
        metrics: list[dict[str, Any]] = []
        for job in jobs:
            item = execute_probe_job(
                job,
                config=config,
                api_key=api_key,
                chapters=chapters,
                output_dir=output_dir,
                max_tokens_override=max_tokens_override,
                dry_run=dry_run,
                print_stream=print_stream,
            )
            metrics.append(item)
            append_jsonl(summary_path, item)
            print_metrics(item)
        return metrics

    metrics = []
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [
            executor.submit(
                execute_probe_job,
                job,
                config=config,
                api_key=api_key,
                chapters=chapters,
                output_dir=output_dir,
                max_tokens_override=max_tokens_override,
                dry_run=dry_run,
                print_stream=print_stream,
            )
            for job in jobs
        ]
        for future in as_completed(futures):
            item = future.result()
            metrics.append(item)
            append_jsonl(summary_path, item)
            print_metrics(item)
    return metrics


def execute_probe_job(
    job: ProbeJob,
    *,
    config: dict[str, Any],
    api_key: str,
    chapters: list[Chapter],
    output_dir: Path,
    max_tokens_override: int,
    dry_run: bool,
    print_stream: bool,
) -> dict[str, Any]:
    payload = build_payload(
        config=config,
        prompt_level=job.prompt_level,
        prompt_template=job.prompt_template,
        batch=job.batch,
        chapters=chapters,
        max_tokens_override=max_tokens_override,
    )
    return run_one(
        config=config,
        api_key=api_key,
        payload=payload,
        batch=job.batch,
        prompt_level=job.prompt_level,
        output_dir=output_dir,
        dry_run=dry_run,
        print_stream=print_stream,
        round_label=job.round_label,
        job_index=job.job_index,
        batch_size=job.batch_size,
        overlap=job.overlap,
        combo_label=job.combo_label,
    )


def execute_fusion_jobs(
    metrics: list[dict[str, Any]],
    *,
    config: dict[str, Any],
    api_key: str,
    fusion_template: str,
    output_dir: Path,
    max_tokens_override: int,
    dry_run: bool,
    print_stream: bool,
    concurrency: int,
    summary_path: Path,
) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for item in metrics:
        key = (
            str(item.get("combo_label")),
            str(item.get("prompt_level")),
            str(item.get("batch_id")),
            str(item.get("batch_size")),
            str(item.get("overlap")),
        )
        groups.setdefault(key, []).append(item)

    jobs: list[tuple[int, list[dict[str, Any]]]] = []
    next_index = max((int(item.get("job_index") or 0) for item in metrics), default=0)
    for group in groups.values():
        if len(group) < 2:
            continue
        next_index += 1
        jobs.append((next_index, sorted(group, key=metric_sort_key)))

    if concurrency == 1:
        results = []
        for job_index, group in jobs:
            item = execute_fusion_job(
                job_index,
                group,
                config=config,
                api_key=api_key,
                fusion_template=fusion_template,
                output_dir=output_dir,
                max_tokens_override=max_tokens_override,
                dry_run=dry_run,
                print_stream=print_stream,
            )
            results.append(item)
            append_jsonl(summary_path, item)
            print_metrics(item)
        return results

    results = []
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [
            executor.submit(
                execute_fusion_job,
                job_index,
                group,
                config=config,
                api_key=api_key,
                fusion_template=fusion_template,
                output_dir=output_dir,
                max_tokens_override=max_tokens_override,
                dry_run=dry_run,
                print_stream=print_stream,
            )
            for job_index, group in jobs
        ]
        for future in as_completed(futures):
            item = future.result()
            results.append(item)
            append_jsonl(summary_path, item)
            print_metrics(item)
    return results


def execute_fusion_job(
    job_index: int,
    round_metrics: list[dict[str, Any]],
    *,
    config: dict[str, Any],
    api_key: str,
    fusion_template: str,
    output_dir: Path,
    max_tokens_override: int,
    dry_run: bool,
    print_stream: bool,
) -> dict[str, Any]:
    first = round_metrics[0]
    batch = Batch(
        batch_id=str(first["batch_id"]),
        input_start=int(first["input_range"][0]),
        input_end=int(first["input_range"][1]),
        owned_start=int(first["owned_range"][0]),
        owned_end=int(first["owned_range"][1]),
        overlap_start=(
            int(first["overlap_range"][0]) if first.get("overlap_range") else None
        ),
        overlap_end=(
            int(first["overlap_range"][1]) if first.get("overlap_range") else None
        ),
    )
    source_prompt_level = str(first.get("prompt_level") or "")
    payload = build_fusion_payload(
        config=config,
        source_prompt_level=source_prompt_level,
        fusion_template=fusion_template,
        batch=batch,
        round_metrics=round_metrics,
        max_tokens_override=max_tokens_override,
    )
    return run_one(
        config=config,
        api_key=api_key,
        payload=payload,
        batch=batch,
        prompt_level=f"{source_prompt_level}_fusion",
        output_dir=output_dir,
        dry_run=dry_run,
        print_stream=print_stream,
        round_label="fusion",
        source_round_labels=[
            str(item.get("round_label") or "") for item in round_metrics
        ],
        job_index=job_index,
        batch_size=int(first.get("batch_size") or 0),
        overlap=int(first.get("overlap") or 0),
        combo_label=str(first.get("combo_label") or ""),
    )


def load_prompt(prompt_level: str, prompt_dir: Path) -> str:
    candidate = Path(prompt_level)
    path = candidate if candidate.exists() else prompt_dir / f"{prompt_level}.txt"
    if not path.exists():
        raise SystemExit(f"unknown prompt level: {prompt_level} ({path} not found)")
    return path.read_text(encoding="utf-8")


def build_payload(
    *,
    config: dict[str, Any],
    prompt_level: str,
    prompt_template: str,
    batch: Batch,
    chapters: list[Chapter],
    max_tokens_override: int,
) -> dict[str, Any]:
    chapter_text = render_chapters(
        [
            chapter
            for chapter in chapters
            if batch.input_start <= chapter.index <= batch.input_end
        ],
    )
    prompt = fill_prompt_template(
        prompt_template,
        {
            "START": str(batch.input_start),
            "END": str(batch.input_end),
            "OWNED_START": str(batch.owned_start),
            "OWNED_END": str(batch.owned_end),
            "OVERLAP_RANGE_TEXT": overlap_text(batch),
            "TEXT": chapter_text,
        },
    )
    max_tokens = max_tokens_override or int(
        (config.get("max_tokens_by_prompt") or {}).get(prompt_level)
        or config.get("max_tokens")
        or 8192,
    )
    request: dict[str, Any] = {
        "model": config.get("model") or "deepseek-v4-flash",
        "messages": [
            {
                "role": "system",
                "content": "你只输出可解析 JSON。不要 Markdown，不要解释。",
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": float(config.get("temperature", 0.2)),
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
        "user_id": user_id(config),
    }
    apply_deepseek_optional_fields(request, config)
    if bool(config.get("stream")):
        request["stream"] = True
        if bool(config.get("stream_options_include_usage", True)):
            request["stream_options"] = {"include_usage": True}
    return request


def build_fusion_payload(
    *,
    config: dict[str, Any],
    source_prompt_level: str,
    fusion_template: str,
    batch: Batch,
    round_metrics: list[dict[str, Any]],
    max_tokens_override: int,
) -> dict[str, Any]:
    candidates = render_fusion_candidates(round_metrics)
    prompt = fill_prompt_template(
        fusion_template,
        {
            "SOURCE_PROMPT_LEVEL": source_prompt_level,
            "ROUND_COUNT": str(len(round_metrics)),
            "START": str(batch.input_start),
            "END": str(batch.input_end),
            "OWNED_START": str(batch.owned_start),
            "OWNED_END": str(batch.owned_end),
            "OVERLAP_RANGE_TEXT": overlap_text(batch),
            "CANDIDATES": candidates,
        },
    )
    max_tokens = max_tokens_override or int(
        (config.get("max_tokens_by_prompt") or {}).get("fusion")
        or config.get("max_tokens")
        or 8192,
    )
    request: dict[str, Any] = {
        "model": config.get("model") or "deepseek-v4-flash",
        "messages": [
            {
                "role": "system",
                "content": "你只输出可解析 JSON。不要 Markdown，不要解释。",
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": float(config.get("temperature", 0.2)),
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
        "user_id": user_id(config),
    }
    apply_deepseek_optional_fields(request, config)
    if bool(config.get("stream")):
        request["stream"] = True
        if bool(config.get("stream_options_include_usage", True)):
            request["stream_options"] = {"include_usage": True}
    return request


def apply_deepseek_optional_fields(
    request: dict[str, Any],
    config: dict[str, Any],
) -> None:
    if "thinking" in config and config["thinking"] is not None:
        request["thinking"] = config["thinking"]
    reasoning_effort = config.get("reasoning_effort")
    if reasoning_effort:
        request["reasoning_effort"] = reasoning_effort


def user_id(config: dict[str, Any]) -> str:
    return str(config.get("_run_user_id") or run_user_id(config, str(uuid.uuid4())))


def run_user_id(config: dict[str, Any], run_id: str) -> str:
    prefix = str(config.get("user_id_prefix", "deep-import-probe"))
    value = f"{prefix}-{run_id}"
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "-", value.strip())
    return cleaned.strip("-") or "deep-import-probe"


def render_fusion_candidates(round_metrics: list[dict[str, Any]]) -> str:
    candidates: list[dict[str, Any]] = []
    for metrics in round_metrics:
        response_text = ""
        response_path = metrics.get("response_path")
        if response_path:
            path = Path(str(response_path))
            if path.exists():
                response_text = path.read_text(encoding="utf-8")
        candidates.append(
            {
                "round_label": metrics.get("round_label"),
                "finish_reason": metrics.get("finish_reason"),
                "error_kind": metrics.get("error_kind"),
                "scene_count": metrics.get("scene_count"),
                "response": response_text,
            },
        )
    return json.dumps(candidates, ensure_ascii=False, indent=2)


def render_chapters(chapters: list[Chapter]) -> str:
    rendered: list[str] = []
    for chapter in chapters:
        title = f"第{chapter.index}章 {chapter.title}".strip()
        rendered.append(f"\n\n{title}\n{chapter.body.strip()}")
    return "".join(rendered).strip()


def overlap_text(batch: Batch) -> str:
    if batch.overlap_start is None or batch.overlap_end is None:
        return "无"
    return f"第{batch.overlap_start}章-第{batch.overlap_end}章"


def fill_prompt_template(template: str, values: dict[str, str]) -> str:
    """Replace probe placeholders without interpreting JSON braces."""

    result = template
    for key, value in values.items():
        result = result.replace("{" + key + "}", value)
    return result


def user_prompt(payload: dict[str, Any]) -> str:
    for message in payload.get("messages", []):
        if message.get("role") == "user":
            return str(message.get("content") or "")
    return ""


def run_one(
    *,
    config: dict[str, Any],
    api_key: str,
    payload: dict[str, Any],
    batch: Batch,
    prompt_level: str,
    output_dir: Path,
    dry_run: bool,
    print_stream: bool,
    round_label: str = "",
    source_round_labels: list[str] | None = None,
    job_index: int = 0,
    batch_size: int = 0,
    overlap: int = 0,
    combo_label: str = "",
) -> dict[str, Any]:
    started = time.monotonic()
    raw_response = ""
    error_kind = None
    error_message = None
    response_payload: dict[str, Any] | None = None
    usage: dict[str, Any] = {}
    finish_reason = None

    if dry_run:
        raw_response = ""
    elif not api_key:
        error_kind = "missing_api_key"
        error_message = (
            "config api_key is blank; copy config.example.json to "
            "config.local.json and fill it"
        )
    else:
        try:
            if payload.get("stream"):
                raw_response, finish_reason, usage = call_deepseek_stream(
                    config,
                    api_key,
                    payload,
                    print_stream=print_stream,
                )
            else:
                response_payload = call_deepseek(config, api_key, payload)
                raw_response = extract_response_text(response_payload)
                finish_reason = extract_finish_reason(response_payload)
                usage = response_payload.get("usage") or {}
        except HTTPError as exc:
            error_kind = "http_error"
            error_message = f"{exc.code}: {safe_read_error(exc)}"
        except URLError as exc:
            error_kind = "url_error"
            error_message = str(exc)
        except TimeoutError as exc:
            error_kind = "timeout"
            error_message = str(exc)
        except Exception as exc:  # noqa: BLE001 - probe should record failures.
            error_kind = type(exc).__name__
            error_message = str(exc)

    elapsed = round(time.monotonic() - started, 3)
    parsed = parse_model_json(raw_response) if raw_response else None
    scene_count = count_scenes(parsed)
    owned_count = batch.owned_end - batch.owned_start + 1
    scene_density = round(scene_count / owned_count, 3) if scene_count else None
    base_name_parts = [
        safe_filename(combo_label) if combo_label else "",
        safe_filename(prompt_level),
        batch.batch_id,
    ]
    base_name = "_".join(part for part in base_name_parts if part)
    if round_label:
        base_name = f"{base_name}_{safe_filename(round_label)}"
    request_path = output_dir / f"{base_name}.request.json"
    prompt_path = output_dir / f"{base_name}.prompt.txt"
    response_path = output_dir / f"{base_name}.response.txt"
    parsed_path = output_dir / f"{base_name}.parsed.json"
    prompt_path.write_text(user_prompt(payload), encoding="utf-8")
    write_json(
        request_path,
        {
            **payload,
            "messages": [
                {**msg, "content": summarize_prompt(msg.get("content", ""))}
                for msg in payload.get("messages", [])
            ],
        },
    )
    if raw_response:
        response_path.write_text(raw_response, encoding="utf-8")
    if parsed is not None:
        write_json(parsed_path, parsed)

    return {
        "job_index": job_index or None,
        "batch_size": batch_size or None,
        "overlap": overlap,
        "combo_label": combo_label or None,
        "prompt_level": prompt_level,
        "round_label": round_label or None,
        "source_round_labels": source_round_labels or None,
        "batch_id": batch.batch_id,
        "input_range": [batch.input_start, batch.input_end],
        "owned_range": [batch.owned_start, batch.owned_end],
        "overlap_range": (
            [batch.overlap_start, batch.overlap_end]
            if batch.overlap_start is not None
            else None
        ),
        "dry_run": dry_run,
        "elapsed_seconds": elapsed,
        "request_chars": sum(
            len(str(msg.get("content", ""))) for msg in payload.get("messages", [])
        ),
        "estimated_input_tokens": round(
            sum(len(str(msg.get("content", ""))) for msg in payload.get("messages", []))
            * 1.7,
        ),
        "max_tokens": payload.get("max_tokens"),
        "stream": bool(payload.get("stream")),
        "finish_reason": finish_reason,
        "usage": usage,
        "scene_count": scene_count,
        "scene_density": scene_density,
        "error_kind": error_kind,
        "error_message": error_message,
        "prompt_path": str(prompt_path),
        "request_path": str(request_path),
        "response_path": str(response_path) if raw_response else None,
        "parsed_path": str(parsed_path) if parsed is not None else None,
        "response_preview": summarize_response(raw_response) if raw_response else None,
    }


def print_metrics(metrics: dict[str, Any]) -> None:
    round_label = metrics.get("round_label") or "-"
    input_range = metrics.get("input_range") or ["?", "?"]
    owned_range = metrics.get("owned_range") or ["?", "?"]
    print(
        " ".join(
            [
                f"combo={metrics.get('combo_label')}",
                f"prompt={metrics.get('prompt_level')}",
                f"round={round_label}",
                f"batch={metrics.get('batch_id')}",
                f"input={input_range[0]}-{input_range[1]}",
                f"owned={owned_range[0]}-{owned_range[1]}",
                f"dry={metrics['dry_run']}",
                f"elapsed={metrics.get('elapsed_seconds')}",
                f"scenes={metrics.get('scene_count')}",
                f"finish={metrics.get('finish_reason')}",
                f"error={metrics.get('error_kind')}",
            ],
        ),
        flush=True,
    )


def call_deepseek(
    config: dict[str, Any],
    api_key: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    request = Request(
        chat_completions_url(str(config.get("base_url") or "")),
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    timeout = float(config.get("timeout_seconds") or 300)
    with urlopen(request, timeout=timeout, context=ssl_context(config)) as response:
        return json.loads(response.read().decode("utf-8"))


def call_deepseek_stream(
    config: dict[str, Any],
    api_key: str,
    payload: dict[str, Any],
    *,
    print_stream: bool,
) -> tuple[str, str | None, dict[str, Any]]:
    request = Request(
        chat_completions_url(str(config.get("base_url") or "")),
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    timeout = float(config.get("timeout_seconds") or 300)
    chunks: list[str] = []
    finish_reason = None
    usage: dict[str, Any] = {}
    with urlopen(request, timeout=timeout, context=ssl_context(config)) as response:
        for raw_line in response:
            line = raw_line.decode("utf-8", errors="ignore").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            event = json.loads(data)
            if event.get("usage"):
                usage = event["usage"]
            choices = event.get("choices") or []
            if not choices:
                continue
            choice = choices[0]
            finish_reason = choice.get("finish_reason") or finish_reason
            content = ((choice.get("delta") or {}).get("content")) or ""
            if content:
                chunks.append(content)
                if print_stream:
                    print(content, end="", flush=True)
    if print_stream and chunks:
        print()
    return "".join(chunks), finish_reason, usage


def chat_completions_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    return f"{base}/chat/completions"


def ssl_context(config: dict[str, Any]) -> ssl.SSLContext | None:
    if config.get("ssl_verify") is False:
        return ssl._create_unverified_context()  # noqa: S323 - explicit local probe opt-out.
    ca_bundle = str(config.get("ca_bundle") or "").strip()
    if ca_bundle:
        return ssl.create_default_context(cafile=ca_bundle)
    if certifi is not None:
        return ssl.create_default_context(cafile=certifi.where())
    return None


def safe_read_error(exc: HTTPError) -> str:
    try:
        return exc.read().decode("utf-8", errors="replace")[:1000]
    except Exception:  # noqa: BLE001
        return str(exc)


def extract_response_text(response: dict[str, Any]) -> str:
    choices = response.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    return str(message.get("content") or "")


def extract_finish_reason(response: dict[str, Any]) -> str | None:
    choices = response.get("choices") or []
    if not choices:
        return None
    return choices[0].get("finish_reason")


def parse_model_json(raw: str) -> Any:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def count_scenes(parsed: Any) -> int | None:
    if parsed is None:
        return None
    if isinstance(parsed, list):
        return len(parsed)
    if isinstance(parsed, dict) and isinstance(parsed.get("scenes"), list):
        return len(parsed["scenes"])
    return None


def summarize_prompt(content: str, *, limit: int = 1200) -> str:
    if len(content) <= limit:
        return content
    return f"{content[:limit]}\n\n...[truncated {len(content) - limit} chars]..."


def summarize_response(content: str, *, limit: int = 1000) -> str:
    if len(content) <= limit:
        return content
    return f"{content[:limit]}\n\n...[truncated {len(content) - limit} chars]..."


def metric_sort_key(item: dict[str, Any]) -> tuple[int, str, str]:
    return (
        int(item.get("job_index") or 0),
        str(item.get("combo_label") or ""),
        str(item.get("batch_id") or ""),
    )


def write_json(path: Path, data: Any) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def safe_filename(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip())
    return cleaned.strip("-") or "run"


def write_latest_pointer(path: Path, output_dir: Path) -> None:
    try:
        path.write_text(str(output_dir.resolve()) + "\n", encoding="utf-8")
    except OSError:
        return


def write_run_metadata(
    path: Path,
    *,
    args: argparse.Namespace,
    config: dict[str, Any],
    run_id: str,
    chapters: list[Chapter],
    batch_sizes: list[int],
    overlaps: list[int],
    prompt_levels: list[str],
    rounds: int,
    fusion_enabled: bool,
    fusion_prompt_name: str,
    fusion_max_tokens: int,
    concurrency: int,
) -> None:
    sanitized_config = {
        key: ("<configured>" if key == "api_key" and value else value)
        for key, value in config.items()
        if key != "api_key" or value
    }
    write_json(
        path,
        {
            "run_id": run_id,
            "created_at": datetime.now(UTC).isoformat(),
            "source": str(args.source),
            "chapter_range": [args.chapter_start, args.chapter_end],
            "chapter_count": len(chapters),
            "batch_sizes": batch_sizes,
            "overlaps": overlaps,
            "prompt_levels": prompt_levels,
            "rounds": rounds,
            "fusion_enabled": fusion_enabled,
            "fusion_prompt": fusion_prompt_name,
            "fusion_max_tokens": fusion_max_tokens,
            "concurrency": concurrency,
            "matrix_filter": str(args.matrix_filter),
            "prompt_dir": str(args.prompt_dir),
            "dry_run": bool(args.dry_run),
            "limit_batches": int(args.limit_batches),
            "max_tokens_override": int(args.max_tokens),
            "config": sanitized_config,
        },
    )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        raise SystemExit(130)
