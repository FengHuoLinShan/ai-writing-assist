#!/usr/bin/env python3
"""Standalone DeepSeek Phase3 narrative-structure probe."""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError

from phase23_common import (
    ProbeScene,
    chapter_range_for_scene_ids,
    confidence_value,
    list_text,
    load_phase1b_final_scenes,
    normalize_scene_refs,
    read_jsonl,
    render_scene_cards,
    render_world_summary,
    short_text,
    valid_scene_ids,
)
from probe import (
    DEFAULT_CONFIG,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_PROMPTS,
    apply_deepseek_optional_fields,
    call_deepseek,
    call_deepseek_stream,
    extract_finish_reason,
    extract_response_text,
    fill_prompt_template,
    load_json,
    load_prompt,
    parse_model_json,
    read_chapters,
    run_user_id,
    safe_filename,
    safe_read_error,
    split_csv,
    summarize_prompt,
    summarize_response,
    user_id,
    write_json,
    write_jsonl,
    write_latest_pointer,
)


@dataclass(frozen=True)
class Phase3Job:
    job_index: int
    input_mode: str
    prompt_level: str
    max_tokens: int
    combo_label: str
    prompt_template: str


def main() -> int:
    args = parse_args()
    config = load_json(args.config)
    read_chapters(args.source)  # Validate source/chapter headings early.
    scenes = load_phase1b_final_scenes(
        args.phase1b_run_dir,
        repair_run_dirs=args.phase1b_repair_run_dir,
        chapter_start=args.chapter_start,
        chapter_end=args.chapter_end,
    )
    if not scenes:
        raise SystemExit("no Phase1b final scenes selected")
    phase2_payload, phase2_selection = load_phase2_selection(
        args.phase2_run_dir,
        combo_label=args.phase2_combo_label,
    )

    run_id = args.run_name or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    config["_run_user_id"] = run_user_id(config, run_id)
    output_dir = args.output_dir / safe_filename(run_id)
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output_dir / "summary.jsonl"
    summary_path.write_text("", encoding="utf-8")
    write_latest_pointer(args.output_dir / "latest-phase3", output_dir)

    input_modes = split_csv(args.input_modes)
    prompt_levels = split_csv(args.prompt_levels)
    max_tokens_values = [int(value) for value in split_csv(args.max_tokens_list)]
    prompt_templates = {
        level: load_phase_prompt("phase3_structure", level, args.prompt_dir)
        for level in prompt_levels
    }
    jobs = build_phase3_jobs(
        input_modes=input_modes,
        prompt_templates=prompt_templates,
        max_tokens_values=max_tokens_values,
    )
    if args.limit_jobs:
        jobs = jobs[: args.limit_jobs]
    if not jobs:
        raise SystemExit("no Phase3 jobs built")

    write_run_metadata(
        output_dir / "run_meta.json",
        args=args,
        config=config,
        run_id=run_id,
        scenes=scenes,
        jobs=jobs,
        phase2_selection=phase2_selection,
    )

    print(f"phase3_run={run_id}")
    print(f"scenes={len(scenes)} jobs={len(jobs)} dry_run={args.dry_run}")
    print(f"phase2_combo={phase2_selection.get('combo_label')}")
    print(f"concurrency={args.concurrency} summary={summary_path}")

    api_key = str(config.get("api_key") or "").strip()
    metrics = execute_phase3_jobs(
        jobs,
        config=config,
        api_key=api_key,
        scenes=scenes,
        phase2_payload=phase2_payload,
        phase2_selection=phase2_selection,
        output_dir=output_dir,
        dry_run=args.dry_run,
        print_stream=args.print_stream,
        concurrency=args.concurrency,
        summary_path=summary_path,
    )
    metrics = sorted(metrics, key=lambda item: int(item.get("job_index") or 0))
    write_jsonl(summary_path, metrics)
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark simplified Phase3 narrative-structure prompts.",
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--phase1b-run-dir", type=Path, required=True)
    parser.add_argument(
        "--phase1b-repair-run-dir",
        type=Path,
        action="append",
        default=[],
    )
    parser.add_argument("--phase2-run-dir", type=Path, required=True)
    parser.add_argument(
        "--phase2-combo-label",
        default="",
        help="Optional exact Phase2 combo label. Defaults to an automatic choice.",
    )
    parser.add_argument("--chapter-start", type=int, default=1)
    parser.add_argument("--chapter-end", type=int, default=60)
    parser.add_argument("--input-modes", default="scenes_plus_world,scenes_only")
    parser.add_argument("--prompt-levels", default="minimal,thread_arc")
    parser.add_argument("--prompt-dir", type=Path, default=DEFAULT_PROMPTS)
    parser.add_argument("--max-tokens-list", default="8192,12288")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--run-name", default="")
    parser.add_argument("--limit-jobs", type=int, default=0)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--print-stream", action="store_true")
    args = parser.parse_args()
    if args.concurrency < 1:
        raise SystemExit("concurrency must be >= 1")
    if args.print_stream and args.concurrency > 1:
        raise SystemExit("--print-stream requires --concurrency 1")
    return args


def load_phase_prompt(phase_prefix: str, level: str, prompt_dir: Path) -> str:
    candidate = prompt_dir / f"{phase_prefix}_{level}.txt"
    if candidate.exists():
        return candidate.read_text(encoding="utf-8")
    return load_prompt(level, prompt_dir)


def load_phase2_selection(
    phase2_run_dir: Path,
    *,
    combo_label: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    summary_path = phase2_run_dir / "summary.jsonl"
    if not summary_path.exists():
        raise SystemExit(f"Phase2 summary not found: {summary_path}")
    rows = read_jsonl(summary_path)
    if combo_label:
        selected = [row for row in rows if row.get("combo_label") == combo_label]
    else:
        selected = auto_select_phase2_rows(rows)
    if not selected:
        raise SystemExit("no Phase2 rows selected")
    selected = sorted(selected, key=lambda row: int(row.get("job_index") or 0))
    payload = aggregate_phase2_payload(selected)
    selection = {
        "combo_label": selected[0].get("combo_label"),
        "row_count": len(selected),
        "final_paths": [row.get("final_path") for row in selected if row.get("final_path")],
        "window_mode": selected[0].get("window_mode"),
        "input_mode": selected[0].get("input_mode"),
        "prompt_level": selected[0].get("prompt_level"),
        "max_tokens": selected[0].get("max_tokens"),
    }
    return payload, selection


def auto_select_phase2_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        combo = str(row.get("combo_label") or "")
        if not combo:
            continue
        groups.setdefault(combo, []).append(row)
    if not groups:
        return []

    def group_score(
        item: tuple[str, list[dict[str, Any]]],
    ) -> tuple[float, float, float, int, int]:
        _combo, group = item
        first = group[0]
        group_size = max(1, len(group))
        error_rate = sum(1 for row in group if row.get("error_kind")) / group_size
        length_rate = (
            sum(1 for row in group if row.get("finish_reason") == "length")
            / group_size
        )
        parse_fail_rate = sum(1 for row in group if not row.get("parse_ok")) / group_size
        preferred = 0
        if first.get("window_mode") == "phase0_charbudget":
            preferred -= 8
        if first.get("input_mode") == "scenes_plus_text":
            preferred -= 4
        if first.get("prompt_level") == "minimal":
            preferred -= 2
        if int(first.get("max_tokens") or 0) == 12288:
            preferred -= 1
        return (
            error_rate,
            length_rate,
            parse_fail_rate,
            preferred,
            int(first.get("job_index") or 0),
        )

    return sorted(groups.items(), key=group_score)[0][1]


def aggregate_phase2_payload(rows: list[dict[str, Any]]) -> dict[str, Any]:
    aggregate = {
        "objects": [],
        "relations": [],
        "deltas": [],
        "uncertain_items": [],
    }
    for row in rows:
        path_value = row.get("final_path")
        if not path_value:
            continue
        path = Path(str(path_value))
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        for key in aggregate:
            values = payload.get(key)
            if isinstance(values, list):
                aggregate[key].extend(values)
    return aggregate


def build_phase3_jobs(
    *,
    input_modes: list[str],
    prompt_templates: dict[str, str],
    max_tokens_values: list[int],
) -> list[Phase3Job]:
    jobs: list[Phase3Job] = []
    job_index = 1
    for input_mode in input_modes:
        if input_mode not in {"scenes_only", "scenes_plus_world"}:
            raise SystemExit(f"unknown input mode: {input_mode}")
        for prompt_level, prompt_template in prompt_templates.items():
            for max_tokens in max_tokens_values:
                combo_label = f"{input_mode}_{prompt_level}_mt{max_tokens}"
                jobs.append(
                    Phase3Job(
                        job_index=job_index,
                        input_mode=input_mode,
                        prompt_level=prompt_level,
                        max_tokens=max_tokens,
                        combo_label=combo_label,
                        prompt_template=prompt_template,
                    ),
                )
                job_index += 1
    return jobs


def execute_phase3_jobs(
    jobs: list[Phase3Job],
    *,
    config: dict[str, Any],
    api_key: str,
    scenes: list[ProbeScene],
    phase2_payload: dict[str, Any],
    phase2_selection: dict[str, Any],
    output_dir: Path,
    dry_run: bool,
    print_stream: bool,
    concurrency: int,
    summary_path: Path,
) -> list[dict[str, Any]]:
    if concurrency == 1:
        metrics: list[dict[str, Any]] = []
        for job in jobs:
            item = execute_phase3_job(
                job,
                config=config,
                api_key=api_key,
                scenes=scenes,
                phase2_payload=phase2_payload,
                phase2_selection=phase2_selection,
                output_dir=output_dir,
                dry_run=dry_run,
                print_stream=print_stream,
            )
            metrics.append(item)
            append_jsonl(summary_path, item)
            print_phase3_metrics(item)
        return metrics

    metrics = []
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [
            executor.submit(
                execute_phase3_job,
                job,
                config=config,
                api_key=api_key,
                scenes=scenes,
                phase2_payload=phase2_payload,
                phase2_selection=phase2_selection,
                output_dir=output_dir,
                dry_run=dry_run,
                print_stream=print_stream,
            )
            for job in jobs
        ]
        for future in as_completed(futures):
            item = future.result()
            metrics.append(item)
            append_jsonl(summary_path, item)
            print_phase3_metrics(item)
    return metrics


def execute_phase3_job(
    job: Phase3Job,
    *,
    config: dict[str, Any],
    api_key: str,
    scenes: list[ProbeScene],
    phase2_payload: dict[str, Any],
    phase2_selection: dict[str, Any],
    output_dir: Path,
    dry_run: bool,
    print_stream: bool,
) -> dict[str, Any]:
    payload = build_phase3_payload(
        config=config,
        job=job,
        scenes=scenes,
        phase2_payload=phase2_payload,
        phase2_selection=phase2_selection,
    )
    return run_phase3_one(
        config=config,
        api_key=api_key,
        payload=payload,
        job=job,
        scenes=scenes,
        phase2_selection=phase2_selection,
        output_dir=output_dir,
        dry_run=dry_run,
        print_stream=print_stream,
    )


def build_phase3_payload(
    *,
    config: dict[str, Any],
    job: Phase3Job,
    scenes: list[ProbeScene],
    phase2_payload: dict[str, Any],
    phase2_selection: dict[str, Any],
) -> dict[str, Any]:
    input_block = render_phase3_input_block(
        input_mode=job.input_mode,
        scenes=scenes,
        phase2_payload=phase2_payload,
        phase2_selection=phase2_selection,
    )
    prompt = fill_prompt_template(
        job.prompt_template,
        {
            "INPUT_BLOCK": input_block,
            "START": str(min(scene.start_chapter for scene in scenes)),
            "END": str(max(scene.end_chapter for scene in scenes)),
            "SCENE_IDS": ", ".join(scene.scene_id for scene in scenes),
            "INPUT_MODE": job.input_mode,
            "PHASE2_COMBO_LABEL": str(phase2_selection.get("combo_label") or ""),
        },
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
        "max_tokens": job.max_tokens,
        "response_format": {"type": "json_object"},
        "user_id": user_id(config),
    }
    apply_deepseek_optional_fields(request, config)
    if bool(config.get("stream")):
        request["stream"] = True
        if bool(config.get("stream_options_include_usage", True)):
            request["stream_options"] = {"include_usage": True}
    return request


def render_phase3_input_block(
    *,
    input_mode: str,
    scenes: list[ProbeScene],
    phase2_payload: dict[str, Any],
    phase2_selection: dict[str, Any],
) -> str:
    scene_cards = f"【Scene卡片 JSON】\n{render_scene_cards(scenes)}"
    if input_mode == "scenes_only":
        return scene_cards
    world_summary = (
        "【Phase2世界资产摘要 JSON】\n"
        f"来源组合：{phase2_selection.get('combo_label')}\n"
        f"{render_world_summary(phase2_payload)}"
    )
    return "\n\n".join([scene_cards, world_summary])


def run_phase3_one(
    *,
    config: dict[str, Any],
    api_key: str,
    payload: dict[str, Any],
    job: Phase3Job,
    scenes: list[ProbeScene],
    phase2_selection: dict[str, Any],
    output_dir: Path,
    dry_run: bool,
    print_stream: bool,
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

    parsed = parse_model_json(raw_response) if raw_response else None
    scenes_by_id = {scene.scene_id: scene for scene in scenes}
    final_payload, parse_error, invalid_ref_count = parse_phase3_output(
        parsed,
        scenes_by_id=scenes_by_id,
        allowed_scene_ids=valid_scene_ids(scenes),
    )
    if dry_run:
        final_payload = empty_phase3_payload("dry_run")
    elif error_kind:
        final_payload = empty_phase3_payload(str(error_kind))
    elif parsed is None:
        final_payload = empty_phase3_payload("invalid_json")
        error_kind = error_kind or "schema_error"
        error_message = error_message or "response did not parse as JSON"
    elif parse_error:
        error_kind = error_kind or "schema_error"
        error_message = error_message or parse_error

    elapsed = round(time.monotonic() - started, 3)
    base_name = safe_filename(job.combo_label)
    request_path = output_dir / f"{base_name}.request.json"
    prompt_path = output_dir / f"{base_name}.prompt.txt"
    response_path = output_dir / f"{base_name}.response.txt"
    parsed_path = output_dir / f"{base_name}.parsed.json"
    final_path = output_dir / f"{base_name}.final.json"
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
    write_json(final_path, final_payload)

    counts = phase3_counts(final_payload)
    return {
        "job_index": job.job_index,
        "phase": "phase3_structure",
        "combo_label": job.combo_label,
        "input_mode": job.input_mode,
        "prompt_level": job.prompt_level,
        "max_tokens": job.max_tokens,
        "phase2_combo_label": phase2_selection.get("combo_label"),
        "scene_count": len(scenes),
        "dry_run": dry_run,
        "elapsed_seconds": elapsed,
        "request_chars": sum(
            len(str(msg.get("content", ""))) for msg in payload.get("messages", [])
        ),
        "estimated_input_tokens": round(
            sum(len(str(msg.get("content", ""))) for msg in payload.get("messages", []))
            * 1.7,
        ),
        "stream": bool(payload.get("stream")),
        "finish_reason": finish_reason,
        "usage": usage,
        "parse_ok": parsed is not None and not parse_error and not error_kind,
        "error_kind": error_kind,
        "error_message": error_message,
        "plot_thread_count": counts["plot_threads"],
        "arc_count": counts["arcs"],
        "foreshadowing_count": counts["foreshadowing"],
        "reveal_count": counts["reveals"],
        "turning_point_count": counts["turning_points"],
        "uncertain_count": counts["uncertain_items"],
        "low_confidence_count": count_low_confidence(final_payload),
        "invalid_scene_ref_count": invalid_ref_count,
        "prompt_path": str(prompt_path),
        "request_path": str(request_path),
        "response_path": str(response_path) if raw_response else None,
        "parsed_path": str(parsed_path) if parsed is not None else None,
        "final_path": str(final_path),
        "response_preview": summarize_response(raw_response) if raw_response else None,
    }


def parse_phase3_output(
    parsed: Any,
    *,
    scenes_by_id: dict[str, ProbeScene],
    allowed_scene_ids: set[str],
) -> tuple[dict[str, Any], str | None, int]:
    if not isinstance(parsed, dict):
        return empty_phase3_payload("invalid_json_object"), "invalid_json_object", 0
    candidate = parsed.get("phase3") if isinstance(parsed.get("phase3"), dict) else parsed
    invalid_refs = 0
    plot_threads: list[dict[str, Any]] = []
    for item in first_list(candidate, "plot_threads", "threads"):
        normalized, invalid_count = normalize_thread_item(
            item,
            scenes_by_id=scenes_by_id,
            allowed_scene_ids=allowed_scene_ids,
        )
        invalid_refs += invalid_count
        if normalized:
            plot_threads.append(normalized)

    arcs: list[dict[str, Any]] = []
    for item in first_list(candidate, "arcs", "character_arcs"):
        normalized, invalid_count = normalize_arc_item(
            item,
            scenes_by_id=scenes_by_id,
            allowed_scene_ids=allowed_scene_ids,
        )
        invalid_refs += invalid_count
        if normalized:
            arcs.append(normalized)

    foreshadowing: list[dict[str, Any]] = []
    for item in first_list(candidate, "foreshadowing", "foreshadowing_items"):
        normalized, invalid_count = normalize_supported_item(
            item,
            scenes_by_id=scenes_by_id,
            allowed_scene_ids=allowed_scene_ids,
            title_keys=("title", "setup"),
            summary_keys=("summary", "payoff", "description"),
        )
        invalid_refs += invalid_count
        if normalized:
            foreshadowing.append(normalized)

    reveals: list[dict[str, Any]] = []
    for item in first_list(candidate, "reveals", "reveal_items"):
        normalized, invalid_count = normalize_supported_item(
            item,
            scenes_by_id=scenes_by_id,
            allowed_scene_ids=allowed_scene_ids,
            title_keys=("title", "name"),
            summary_keys=("summary", "description"),
        )
        invalid_refs += invalid_count
        if normalized:
            reveals.append(normalized)

    turning_points: list[dict[str, Any]] = []
    for item in first_list(candidate, "turning_points", "key_turning_points"):
        normalized, invalid_count = normalize_supported_item(
            item,
            scenes_by_id=scenes_by_id,
            allowed_scene_ids=allowed_scene_ids,
            title_keys=("title", "name"),
            summary_keys=("summary", "description"),
        )
        invalid_refs += invalid_count
        if normalized:
            turning_points.append(normalized)

    uncertain_items = [
        normalize_uncertain_item(item)
        for item in first_list(candidate, "uncertain_items", "needs_review_items")
    ]
    return (
        {
            "plot_threads": plot_threads,
            "arcs": arcs,
            "foreshadowing": foreshadowing,
            "reveals": reveals,
            "turning_points": turning_points,
            "uncertain_items": [item for item in uncertain_items if item],
        },
        None,
        invalid_refs,
    )


def normalize_thread_item(
    item: Any,
    *,
    scenes_by_id: dict[str, ProbeScene],
    allowed_scene_ids: set[str],
) -> tuple[dict[str, Any] | None, int]:
    if not isinstance(item, dict):
        return None, 0
    return normalize_supported_item(
        item,
        scenes_by_id=scenes_by_id,
        allowed_scene_ids=allowed_scene_ids,
        title_keys=("title", "name"),
        summary_keys=("summary", "description", "goal"),
        extra={
            "status": short_text(item.get("status") or "active"),
            "thread_type": short_text(item.get("thread_type") or item.get("type")),
        },
    )


def normalize_arc_item(
    item: Any,
    *,
    scenes_by_id: dict[str, ProbeScene],
    allowed_scene_ids: set[str],
) -> tuple[dict[str, Any] | None, int]:
    if not isinstance(item, dict):
        return None, 0
    character_name = short_text(item.get("character_name") or item.get("name"))
    normalized, invalid_count = normalize_supported_item(
        item,
        scenes_by_id=scenes_by_id,
        allowed_scene_ids=allowed_scene_ids,
        title_keys=("title", "arc_title"),
        summary_keys=("summary", "description"),
        extra={"character_name": character_name},
    )
    return normalized, invalid_count


def normalize_supported_item(
    item: Any,
    *,
    scenes_by_id: dict[str, ProbeScene],
    allowed_scene_ids: set[str],
    title_keys: tuple[str, ...],
    summary_keys: tuple[str, ...],
    extra: dict[str, Any] | None = None,
) -> tuple[dict[str, Any] | None, int]:
    if not isinstance(item, dict):
        return None, 0
    title = first_text(item, title_keys)
    summary = first_text(item, summary_keys)
    if not (title or summary):
        return None, 0
    scene_ids, invalid_count = normalize_scene_refs(
        item.get("supporting_scene_ids")
        or item.get("scene_ids")
        or item.get("key_scene_ids"),
        allowed_scene_ids,
    )
    needs_review = bool(item.get("needs_review")) or not scene_ids
    payload = {
        "title": title,
        "summary": summary,
        "confidence": confidence_value(item.get("confidence")),
        "needs_review": needs_review,
        "review_reason": short_text(item.get("review_reason")),
        "supporting_scene_ids": scene_ids,
        "chapter_range": chapter_range_for_scene_ids(scene_ids, scenes_by_id),
    }
    if extra:
        payload.update(extra)
    return payload, invalid_count


def normalize_uncertain_item(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        return {
            "description": short_text(item.get("description") or item.get("summary")),
            "reason": short_text(item.get("reason") or item.get("review_reason")),
            "supporting_scene_ids": list_text(item.get("supporting_scene_ids")),
        }
    text = short_text(item)
    return {"description": text, "reason": "", "supporting_scene_ids": []} if text else {}


def first_text(item: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = short_text(item.get(key))
        if value:
            return value
    return ""


def first_list(payload: dict[str, Any], *keys: str) -> list[Any]:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, list):
            return value
    return []


def empty_phase3_payload(reason: str) -> dict[str, Any]:
    return {
        "plot_threads": [],
        "arcs": [],
        "foreshadowing": [],
        "reveals": [],
        "turning_points": [],
        "uncertain_items": [
            {
                "description": "Phase3 structure extraction did not produce usable JSON.",
                "reason": reason,
                "supporting_scene_ids": [],
            },
        ],
    }


def phase3_counts(payload: dict[str, Any]) -> dict[str, int]:
    return {
        "plot_threads": len(payload.get("plot_threads") or []),
        "arcs": len(payload.get("arcs") or []),
        "foreshadowing": len(payload.get("foreshadowing") or []),
        "reveals": len(payload.get("reveals") or []),
        "turning_points": len(payload.get("turning_points") or []),
        "uncertain_items": len(payload.get("uncertain_items") or []),
    }


def count_low_confidence(payload: dict[str, Any]) -> int:
    count = 0
    for key in ("plot_threads", "arcs", "foreshadowing", "reveals", "turning_points"):
        for item in payload.get(key) or []:
            if float(item.get("confidence") or 0) < 0.7 or item.get("needs_review"):
                count += 1
    return count


def user_prompt(payload: dict[str, Any]) -> str:
    for message in payload.get("messages", []):
        if message.get("role") == "user":
            return str(message.get("content") or "")
    return ""


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def print_phase3_metrics(metrics: dict[str, Any]) -> None:
    print(
        " ".join(
            [
                f"combo={metrics.get('combo_label')}",
                f"dry={metrics.get('dry_run')}",
                f"elapsed={metrics.get('elapsed_seconds')}",
                f"parse_ok={metrics.get('parse_ok')}",
                f"threads={metrics.get('plot_thread_count')}",
                f"arcs={metrics.get('arc_count')}",
                f"reveals={metrics.get('reveal_count')}",
                f"finish={metrics.get('finish_reason')}",
                f"error={metrics.get('error_kind')}",
            ],
        ),
        flush=True,
    )


def write_run_metadata(
    path: Path,
    *,
    args: argparse.Namespace,
    config: dict[str, Any],
    run_id: str,
    scenes: list[ProbeScene],
    jobs: list[Phase3Job],
    phase2_selection: dict[str, Any],
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
            "phase1b_run_dir": str(args.phase1b_run_dir),
            "phase1b_repair_run_dir": [
                str(path) for path in args.phase1b_repair_run_dir
            ],
            "phase2_run_dir": str(args.phase2_run_dir),
            "phase2_selection": phase2_selection,
            "chapter_start": args.chapter_start,
            "chapter_end": args.chapter_end,
            "scene_count": len(scenes),
            "job_count": len(jobs),
            "input_modes": split_csv(args.input_modes),
            "prompt_levels": split_csv(args.prompt_levels),
            "max_tokens_list": [
                int(value) for value in split_csv(args.max_tokens_list)
            ],
            "dry_run": bool(args.dry_run),
            "concurrency": int(args.concurrency),
            "config": sanitized_config,
        },
    )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        raise SystemExit(130)
