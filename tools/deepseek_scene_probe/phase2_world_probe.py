#!/usr/bin/env python3
"""Standalone DeepSeek Phase2 world-extraction probe.

This script tests a simplified Phase2 design outside the backend workflow. It
consumes Phase1b final scenes, optionally includes chapter text, and asks the
model to extract durable story assets, relations, and state changes.
"""

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
    build_windows,
    chapter_range_for_scene_ids,
    confidence_value,
    duplicate_name_ratio,
    list_text,
    load_phase1b_final_scenes,
    normalize_scene_refs,
    render_scene_cards,
    scenes_in_range,
    scenes_owned_by_window,
    short_text,
    valid_scene_ids,
)
from probe import (
    DEFAULT_CONFIG,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_PROMPTS,
    Batch,
    Chapter,
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
    render_chapters,
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
class Phase2Job:
    job_index: int
    window_mode: str
    input_mode: str
    prompt_level: str
    max_tokens: int
    combo_label: str
    batch: Batch
    prompt_template: str


def main() -> int:
    args = parse_args()
    config = load_json(args.config)
    chapters = read_chapters(args.source)
    scenes = load_phase1b_final_scenes(
        args.phase1b_run_dir,
        repair_run_dirs=args.phase1b_repair_run_dir,
        chapter_start=args.chapter_start,
        chapter_end=args.chapter_end,
    )
    if not scenes:
        raise SystemExit("no Phase1b final scenes selected")

    run_id = args.run_name or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    config["_run_user_id"] = run_user_id(config, run_id)
    output_dir = args.output_dir / safe_filename(run_id)
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output_dir / "summary.jsonl"
    summary_path.write_text("", encoding="utf-8")
    write_latest_pointer(args.output_dir / "latest-phase2", output_dir)

    window_modes = split_csv(args.window_modes)
    input_modes = split_csv(args.input_modes)
    prompt_levels = split_csv(args.prompt_levels)
    max_tokens_values = [int(value) for value in split_csv(args.max_tokens_list)]
    prompt_templates = {
        level: load_phase_prompt("phase2_world", level, args.prompt_dir)
        for level in prompt_levels
    }
    jobs = build_phase2_jobs(
        chapters=chapters,
        chapter_start=args.chapter_start,
        chapter_end=args.chapter_end,
        window_modes=window_modes,
        input_modes=input_modes,
        prompt_templates=prompt_templates,
        max_tokens_values=max_tokens_values,
    )
    if args.limit_jobs:
        jobs = jobs[: args.limit_jobs]
    if not jobs:
        raise SystemExit("no Phase2 jobs built")

    write_run_metadata(
        output_dir / "run_meta.json",
        args=args,
        config=config,
        run_id=run_id,
        scenes=scenes,
        jobs=jobs,
    )

    print(f"phase2_run={run_id}")
    print(f"scenes={len(scenes)} jobs={len(jobs)} dry_run={args.dry_run}")
    print(f"concurrency={args.concurrency} summary={summary_path}")

    api_key = str(config.get("api_key") or "").strip()
    metrics = execute_phase2_jobs(
        jobs,
        config=config,
        api_key=api_key,
        chapters=chapters,
        scenes=scenes,
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
        description="Benchmark simplified Phase2 world extraction prompts.",
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--phase1b-run-dir", type=Path, required=True)
    parser.add_argument(
        "--phase1b-repair-run-dir",
        type=Path,
        action="append",
        default=[],
        help="Optional Phase1b repair run directory. Can be passed multiple times.",
    )
    parser.add_argument("--chapter-start", type=int, default=1)
    parser.add_argument("--chapter-end", type=int, default=60)
    parser.add_argument(
        "--window-modes",
        default="phase0_charbudget,single_range",
    )
    parser.add_argument(
        "--input-modes",
        default="scenes_plus_text,scenes_only",
    )
    parser.add_argument("--prompt-levels", default="minimal,strict")
    parser.add_argument("--prompt-dir", type=Path, default=DEFAULT_PROMPTS)
    parser.add_argument("--max-tokens-list", default="8192,12288,16384")
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


def build_phase2_jobs(
    *,
    chapters: list[Chapter],
    chapter_start: int,
    chapter_end: int,
    window_modes: list[str],
    input_modes: list[str],
    prompt_templates: dict[str, str],
    max_tokens_values: list[int],
) -> list[Phase2Job]:
    jobs: list[Phase2Job] = []
    job_index = 1
    for window_mode in window_modes:
        windows = build_windows(
            chapters,
            mode=window_mode,
            chapter_start=chapter_start,
            chapter_end=chapter_end,
        )
        for input_mode in input_modes:
            if input_mode not in {"scenes_only", "scenes_plus_text"}:
                raise SystemExit(f"unknown input mode: {input_mode}")
            for prompt_level, prompt_template in prompt_templates.items():
                for max_tokens in max_tokens_values:
                    for batch in windows:
                        combo_label = phase2_combo_label(
                            window_mode,
                            input_mode,
                            prompt_level,
                            max_tokens,
                        )
                        jobs.append(
                            Phase2Job(
                                job_index=job_index,
                                window_mode=window_mode,
                                input_mode=input_mode,
                                prompt_level=prompt_level,
                                max_tokens=max_tokens,
                                combo_label=combo_label,
                                batch=batch,
                                prompt_template=prompt_template,
                            ),
                        )
                        job_index += 1
    return jobs


def phase2_combo_label(
    window_mode: str,
    input_mode: str,
    prompt_level: str,
    max_tokens: int,
) -> str:
    return f"{window_mode}_{input_mode}_{prompt_level}_mt{max_tokens}"


def execute_phase2_jobs(
    jobs: list[Phase2Job],
    *,
    config: dict[str, Any],
    api_key: str,
    chapters: list[Chapter],
    scenes: list[ProbeScene],
    output_dir: Path,
    dry_run: bool,
    print_stream: bool,
    concurrency: int,
    summary_path: Path,
) -> list[dict[str, Any]]:
    if concurrency == 1:
        metrics: list[dict[str, Any]] = []
        for job in jobs:
            item = execute_phase2_job(
                job,
                config=config,
                api_key=api_key,
                chapters=chapters,
                scenes=scenes,
                output_dir=output_dir,
                dry_run=dry_run,
                print_stream=print_stream,
            )
            metrics.append(item)
            append_jsonl(summary_path, item)
            print_phase2_metrics(item)
        return metrics

    metrics = []
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [
            executor.submit(
                execute_phase2_job,
                job,
                config=config,
                api_key=api_key,
                chapters=chapters,
                scenes=scenes,
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
            print_phase2_metrics(item)
    return metrics


def execute_phase2_job(
    job: Phase2Job,
    *,
    config: dict[str, Any],
    api_key: str,
    chapters: list[Chapter],
    scenes: list[ProbeScene],
    output_dir: Path,
    dry_run: bool,
    print_stream: bool,
) -> dict[str, Any]:
    selected_scenes = scenes_in_range(
        scenes,
        start=job.batch.input_start,
        end=job.batch.input_end,
    )
    owned_scenes = scenes_owned_by_window(selected_scenes, job.batch)
    payload = build_phase2_payload(
        config=config,
        job=job,
        chapters=chapters,
        selected_scenes=selected_scenes,
        owned_scenes=owned_scenes,
    )
    return run_phase2_one(
        config=config,
        api_key=api_key,
        payload=payload,
        job=job,
        scenes=selected_scenes,
        owned_scenes=owned_scenes,
        output_dir=output_dir,
        dry_run=dry_run,
        print_stream=print_stream,
    )


def build_phase2_payload(
    *,
    config: dict[str, Any],
    job: Phase2Job,
    chapters: list[Chapter],
    selected_scenes: list[ProbeScene],
    owned_scenes: list[ProbeScene],
) -> dict[str, Any]:
    selected_chapters = [
        chapter
        for chapter in chapters
        if job.batch.input_start <= chapter.index <= job.batch.input_end
    ]
    input_block = render_phase2_input_block(
        input_mode=job.input_mode,
        chapters=selected_chapters,
        scenes=selected_scenes,
    )
    prompt = fill_prompt_template(
        job.prompt_template,
        {
            "INPUT_BLOCK": input_block,
            "START": str(job.batch.input_start),
            "END": str(job.batch.input_end),
            "OWNED_START": str(job.batch.owned_start),
            "OWNED_END": str(job.batch.owned_end),
            "OVERLAP_RANGE_TEXT": overlap_text(job.batch),
            "INPUT_MODE": job.input_mode,
            "OWNED_SCENE_IDS": ", ".join(scene.scene_id for scene in owned_scenes),
            "ALL_SCENE_IDS": ", ".join(scene.scene_id for scene in selected_scenes),
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


def render_phase2_input_block(
    *,
    input_mode: str,
    chapters: list[Chapter],
    scenes: list[ProbeScene],
) -> str:
    scene_cards = render_scene_cards(scenes)
    if input_mode == "scenes_only":
        return f"【Scene卡片 JSON】\n{scene_cards}"
    chapter_text = render_chapters(chapters)
    return "\n\n".join(
        [
            f"【章节正文】\n{chapter_text}",
            f"【Scene卡片 JSON】\n{scene_cards}",
        ],
    )


def run_phase2_one(
    *,
    config: dict[str, Any],
    api_key: str,
    payload: dict[str, Any],
    job: Phase2Job,
    scenes: list[ProbeScene],
    owned_scenes: list[ProbeScene],
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
    owned_scene_ids = {scene.scene_id for scene in owned_scenes}
    final_payload, parse_error, invalid_ref_count = parse_phase2_output(
        parsed,
        scenes_by_id=scenes_by_id,
        allowed_scene_ids=valid_scene_ids(scenes),
        owned_scene_ids=owned_scene_ids,
    )
    if dry_run:
        final_payload = empty_phase2_payload("dry_run")
    elif error_kind:
        final_payload = empty_phase2_payload(str(error_kind))
    elif parsed is None:
        final_payload = empty_phase2_payload("invalid_json")
        error_kind = error_kind or "schema_error"
        error_message = error_message or "response did not parse as JSON"
    elif parse_error:
        error_kind = error_kind or "schema_error"
        error_message = error_message or parse_error

    elapsed = round(time.monotonic() - started, 3)
    base_name = safe_filename(
        "_".join([job.combo_label, job.batch.batch_id]),
    )
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

    counts = phase2_counts(final_payload)
    low_confidence_count = count_low_confidence(final_payload)
    return {
        "job_index": job.job_index,
        "phase": "phase2_world_extraction",
        "combo_label": job.combo_label,
        "window_mode": job.window_mode,
        "input_mode": job.input_mode,
        "prompt_level": job.prompt_level,
        "max_tokens": job.max_tokens,
        "batch_id": job.batch.batch_id,
        "input_range": [job.batch.input_start, job.batch.input_end],
        "owned_range": [job.batch.owned_start, job.batch.owned_end],
        "overlap_range": (
            [job.batch.overlap_start, job.batch.overlap_end]
            if job.batch.overlap_start is not None
            else None
        ),
        "scene_count": len(scenes),
        "owned_scene_count": len(owned_scenes),
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
        "object_count": counts["objects"],
        "relation_count": counts["relations"],
        "delta_count": counts["deltas"],
        "uncertain_count": counts["uncertain_items"],
        "low_confidence_count": low_confidence_count,
        "invalid_scene_ref_count": invalid_ref_count,
        "duplicate_name_ratio": duplicate_name_ratio(final_payload.get("objects") or []),
        "prompt_path": str(prompt_path),
        "request_path": str(request_path),
        "response_path": str(response_path) if raw_response else None,
        "parsed_path": str(parsed_path) if parsed is not None else None,
        "final_path": str(final_path),
        "response_preview": summarize_response(raw_response) if raw_response else None,
    }


def parse_phase2_output(
    parsed: Any,
    *,
    scenes_by_id: dict[str, ProbeScene],
    allowed_scene_ids: set[str],
    owned_scene_ids: set[str],
) -> tuple[dict[str, Any], str | None, int]:
    if not isinstance(parsed, dict):
        return empty_phase2_payload("invalid_json_object"), "invalid_json_object", 0
    candidate = parsed.get("phase2") if isinstance(parsed.get("phase2"), dict) else parsed
    objects_raw = first_list(candidate, "objects", "entities", "assets")
    relations_raw = first_list(candidate, "relations", "entity_relations")
    deltas_raw = first_list(candidate, "deltas", "delta_events", "state_changes")
    uncertain_raw = first_list(candidate, "uncertain_items", "needs_review_items")
    invalid_refs = 0

    objects: list[dict[str, Any]] = []
    for item in objects_raw:
        if not isinstance(item, dict):
            continue
        normalized, invalid_count = normalize_phase2_object(
            item,
            scenes_by_id=scenes_by_id,
            allowed_scene_ids=allowed_scene_ids,
            owned_scene_ids=owned_scene_ids,
        )
        invalid_refs += invalid_count
        if normalized:
            objects.append(normalized)

    relations: list[dict[str, Any]] = []
    for item in relations_raw:
        if not isinstance(item, dict):
            continue
        normalized, invalid_count = normalize_phase2_relation(
            item,
            scenes_by_id=scenes_by_id,
            allowed_scene_ids=allowed_scene_ids,
            owned_scene_ids=owned_scene_ids,
        )
        invalid_refs += invalid_count
        if normalized:
            relations.append(normalized)

    deltas: list[dict[str, Any]] = []
    for item in deltas_raw:
        if not isinstance(item, dict):
            continue
        normalized, invalid_count = normalize_phase2_delta(
            item,
            scenes_by_id=scenes_by_id,
            allowed_scene_ids=allowed_scene_ids,
            owned_scene_ids=owned_scene_ids,
        )
        invalid_refs += invalid_count
        if normalized:
            deltas.append(normalized)

    uncertain_items = [normalize_uncertain_item(item) for item in uncertain_raw]
    return (
        {
            "objects": objects,
            "relations": relations,
            "deltas": deltas,
            "uncertain_items": [item for item in uncertain_items if item],
        },
        None,
        invalid_refs,
    )


def normalize_phase2_object(
    item: dict[str, Any],
    *,
    scenes_by_id: dict[str, ProbeScene],
    allowed_scene_ids: set[str],
    owned_scene_ids: set[str],
) -> tuple[dict[str, Any] | None, int]:
    name = short_text(item.get("name") or item.get("entity_name"))
    if not name:
        return None, 0
    scene_ids, invalid_count = normalize_scene_refs(
        item.get("supporting_scene_ids") or item.get("scene_ids"),
        allowed_scene_ids,
    )
    needs_review = bool(item.get("needs_review")) or not scene_ids
    if scene_ids and not any(scene_id in owned_scene_ids for scene_id in scene_ids):
        needs_review = True
    chapter_range = chapter_range_for_scene_ids(scene_ids, scenes_by_id)
    return (
        {
            "name": name,
            "entity_type": short_text(item.get("entity_type") or item.get("type")),
            "summary": short_text(item.get("summary") or item.get("description")),
            "aliases": list_text(item.get("aliases")),
            "suggested_action": short_text(item.get("suggested_action") or "create"),
            "suggested_existing_name": short_text(
                item.get("suggested_existing_name")
                or item.get("suggested_existing_entity_name"),
            ),
            "importance": short_text(item.get("importance") or "medium"),
            "confidence": confidence_value(item.get("confidence")),
            "needs_review": needs_review,
            "review_reason": short_text(item.get("review_reason")),
            "supporting_scene_ids": scene_ids,
            "chapter_range": chapter_range,
        },
        invalid_count,
    )


def normalize_phase2_relation(
    item: dict[str, Any],
    *,
    scenes_by_id: dict[str, ProbeScene],
    allowed_scene_ids: set[str],
    owned_scene_ids: set[str],
) -> tuple[dict[str, Any] | None, int]:
    source_name = short_text(item.get("source_name") or item.get("source"))
    target_name = short_text(item.get("target_name") or item.get("target"))
    relation_type = short_text(item.get("relation_type") or item.get("type"))
    description = short_text(item.get("description") or item.get("summary"))
    if not (source_name and target_name and (relation_type or description)):
        return None, 0
    scene_ids, invalid_count = normalize_scene_refs(
        item.get("supporting_scene_ids") or item.get("scene_ids"),
        allowed_scene_ids,
    )
    needs_review = bool(item.get("needs_review")) or not scene_ids
    if scene_ids and not any(scene_id in owned_scene_ids for scene_id in scene_ids):
        needs_review = True
    return (
        {
            "source_name": source_name,
            "target_name": target_name,
            "relation_type": relation_type,
            "description": description,
            "confidence": confidence_value(item.get("confidence")),
            "needs_review": needs_review,
            "review_reason": short_text(item.get("review_reason")),
            "supporting_scene_ids": scene_ids,
            "chapter_range": chapter_range_for_scene_ids(scene_ids, scenes_by_id),
        },
        invalid_count,
    )


def normalize_phase2_delta(
    item: dict[str, Any],
    *,
    scenes_by_id: dict[str, ProbeScene],
    allowed_scene_ids: set[str],
    owned_scene_ids: set[str],
) -> tuple[dict[str, Any] | None, int]:
    subject_name = short_text(item.get("subject_name") or item.get("entity_name"))
    description = short_text(item.get("description") or item.get("summary"))
    if not (subject_name and description):
        return None, 0
    scene_ids, invalid_count = normalize_scene_refs(
        item.get("supporting_scene_ids") or item.get("scene_ids"),
        allowed_scene_ids,
    )
    needs_review = bool(item.get("needs_review")) or not scene_ids
    if scene_ids and not any(scene_id in owned_scene_ids for scene_id in scene_ids):
        needs_review = True
    return (
        {
            "subject_name": subject_name,
            "category": short_text(item.get("category") or item.get("delta_type")),
            "field": short_text(item.get("field")),
            "old": short_text(item.get("old") or item.get("before")),
            "new": short_text(item.get("new") or item.get("after")),
            "description": description,
            "confidence": confidence_value(item.get("confidence")),
            "needs_review": needs_review,
            "review_reason": short_text(item.get("review_reason")),
            "supporting_scene_ids": scene_ids,
            "chapter_range": chapter_range_for_scene_ids(scene_ids, scenes_by_id),
        },
        invalid_count,
    )


def normalize_uncertain_item(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        return {
            "description": short_text(item.get("description") or item.get("summary")),
            "reason": short_text(item.get("reason") or item.get("review_reason")),
            "supporting_scene_ids": list_text(item.get("supporting_scene_ids")),
        }
    text = short_text(item)
    return {"description": text, "reason": "", "supporting_scene_ids": []} if text else {}


def first_list(payload: dict[str, Any], *keys: str) -> list[Any]:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, list):
            return value
    return []


def empty_phase2_payload(reason: str) -> dict[str, Any]:
    return {
        "objects": [],
        "relations": [],
        "deltas": [],
        "uncertain_items": [
            {
                "description": "Phase2 extraction did not produce usable JSON.",
                "reason": reason,
                "supporting_scene_ids": [],
            },
        ],
    }


def phase2_counts(payload: dict[str, Any]) -> dict[str, int]:
    return {
        "objects": len(payload.get("objects") or []),
        "relations": len(payload.get("relations") or []),
        "deltas": len(payload.get("deltas") or []),
        "uncertain_items": len(payload.get("uncertain_items") or []),
    }


def count_low_confidence(payload: dict[str, Any]) -> int:
    count = 0
    for key in ("objects", "relations", "deltas"):
        for item in payload.get(key) or []:
            if float(item.get("confidence") or 0) < 0.7 or item.get("needs_review"):
                count += 1
    return count


def overlap_text(batch: Batch) -> str:
    if batch.overlap_start is None or batch.overlap_end is None:
        return "无"
    return f"第{batch.overlap_start}章-第{batch.overlap_end}章"


def user_prompt(payload: dict[str, Any]) -> str:
    for message in payload.get("messages", []):
        if message.get("role") == "user":
            return str(message.get("content") or "")
    return ""


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def print_phase2_metrics(metrics: dict[str, Any]) -> None:
    input_range = metrics.get("input_range") or ["?", "?"]
    print(
        " ".join(
            [
                f"combo={metrics.get('combo_label')}",
                f"batch={metrics.get('batch_id')}",
                f"input={input_range[0]}-{input_range[1]}",
                f"dry={metrics.get('dry_run')}",
                f"elapsed={metrics.get('elapsed_seconds')}",
                f"parse_ok={metrics.get('parse_ok')}",
                f"objects={metrics.get('object_count')}",
                f"relations={metrics.get('relation_count')}",
                f"deltas={metrics.get('delta_count')}",
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
    jobs: list[Phase2Job],
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
            "chapter_start": args.chapter_start,
            "chapter_end": args.chapter_end,
            "scene_count": len(scenes),
            "job_count": len(jobs),
            "window_modes": split_csv(args.window_modes),
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
