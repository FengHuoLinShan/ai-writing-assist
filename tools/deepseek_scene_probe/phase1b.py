#!/usr/bin/env python3
"""Standalone DeepSeek Phase1b scene-enrichment probe.

This tool stays isolated from the backend. It consumes Phase1a scene candidates,
calls DeepSeek once per scene, and writes merged enrichment artifacts under the
ignored ``runs/`` directory.
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
from typing import Any, Callable
from urllib.error import HTTPError, URLError

from probe import (
    DEFAULT_CONFIG,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_PROMPTS,
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
    run_user_id,
    safe_filename,
    safe_read_error,
    summarize_prompt,
    summarize_response,
    user_id,
    write_json,
    write_jsonl,
    write_latest_pointer,
)


LOCKED_FIELDS = {
    "title",
    "goal",
    "core_conflict",
    "start_chapter",
    "end_chapter",
    "boundary_status",
    "scene_chunks",
}
ENRICHMENT_FIELDS = {
    "emotional_beat",
    "must_happen",
    "must_not_happen",
    "narrative_tag",
    "confidence",
    "needs_review",
    "review_reason",
}


@dataclass(frozen=True)
class Phase1aScene:
    scene_id: str
    source_index: int
    title: str
    goal: str
    core_conflict: str
    start_chapter: int
    end_chapter: int
    boundary_status: str
    source_payload: dict[str, Any]


@dataclass(frozen=True)
class Phase1bJob:
    job_index: int
    scene: Phase1aScene
    prompt_template: str


def main() -> int:
    args = parse_args()
    config = load_json(args.config)
    chapters = read_chapters(args.source)
    scenes = load_phase1a_scenes(
        artifact_path=args.phase1a_artifact,
        run_dir=args.phase1a_run_dir,
        prompt_level=args.phase1a_prompt_level,
        combo_label=args.phase1a_combo_label,
    )
    scenes = select_scenes(scenes, scene_ids=args.scene_ids, sample_size=args.sample_size)
    if args.limit_scenes:
        scenes = scenes[: args.limit_scenes]
    if not scenes:
        raise SystemExit("no Phase1a scenes selected")

    run_id = args.run_name or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    config["_run_user_id"] = run_user_id(config, run_id)
    output_dir = args.output_dir / safe_filename(run_id)
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output_dir / "summary.jsonl"
    summary_path.write_text("", encoding="utf-8")
    write_latest_pointer(args.output_dir / "latest-phase1b", output_dir)

    prompt_template = load_prompt(args.prompt, args.prompt_dir)
    jobs = [
        Phase1bJob(job_index=index, scene=scene, prompt_template=prompt_template)
        for index, scene in enumerate(scenes, start=1)
    ]
    api_key = str(config.get("api_key") or "").strip()
    write_run_metadata(
        output_dir / "run_meta.json",
        args=args,
        config=config,
        run_id=run_id,
        scene_count=len(scenes),
        concurrency=args.concurrency,
    )

    print(f"phase1b_run={run_id}")
    print(f"scenes={len(scenes)} dry_run={args.dry_run} concurrency={args.concurrency}")
    print(f"summary={summary_path}")

    metrics = execute_phase1b_jobs(
        jobs,
        config=config,
        api_key=api_key,
        chapters=chapters,
        output_dir=output_dir,
        max_tokens_override=args.max_tokens,
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
        description="Benchmark Phase1b per-scene enrichment prompts.",
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--phase1a-artifact", type=Path, default=None)
    parser.add_argument("--phase1a-run-dir", type=Path, default=None)
    parser.add_argument("--phase1a-prompt-level", default="minimal")
    parser.add_argument("--phase1a-combo-label", default="b20_o3")
    parser.add_argument("--prompt", default="phase1b_enrich")
    parser.add_argument("--prompt-dir", type=Path, default=DEFAULT_PROMPTS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--run-name", default="")
    parser.add_argument("--sample-size", type=int, default=0)
    parser.add_argument("--limit-scenes", type=int, default=0)
    parser.add_argument("--scene-ids", default="")
    parser.add_argument("--max-tokens", type=int, default=0)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--print-stream", action="store_true")
    args = parser.parse_args()
    if not args.phase1a_artifact and not args.phase1a_run_dir:
        raise SystemExit("provide --phase1a-artifact or --phase1a-run-dir")
    if args.concurrency < 1:
        raise SystemExit("concurrency must be >= 1")
    if args.print_stream and args.concurrency > 1:
        raise SystemExit("--print-stream requires --concurrency 1")
    return args


def load_phase1a_scenes(
    *,
    artifact_path: Path | None,
    run_dir: Path | None,
    prompt_level: str,
    combo_label: str,
) -> list[Phase1aScene]:
    if artifact_path:
        return load_phase1a_artifact_scenes(artifact_path)
    if run_dir:
        return load_phase1a_probe_run_scenes(
            run_dir,
            prompt_level=prompt_level,
            combo_label=combo_label,
        )
    return []


def load_phase1a_artifact_scenes(path: Path) -> list[Phase1aScene]:
    payload = load_json(path)
    phase1a = payload.get("phase1a_result") or {}
    raw_scenes: list[dict[str, Any]] = []
    for candidate in phase1a.get("candidates", []) or []:
        if not isinstance(candidate, dict):
            continue
        candidate_chapters = candidate.get("source_chapter_indices") or []
        candidate_payload = candidate.get("payload") or {}
        scenes = candidate_payload.get("scenes") if isinstance(candidate_payload, dict) else None
        for scene in scenes or []:
            if isinstance(scene, dict):
                raw_scenes.append(
                    {
                        **scene,
                        "_fallback_chapters": candidate_chapters,
                    },
                )
    return normalize_phase1a_scenes(raw_scenes)


def load_phase1a_probe_run_scenes(
    run_dir: Path,
    *,
    prompt_level: str,
    combo_label: str,
) -> list[Phase1aScene]:
    summary_path = run_dir / "summary.jsonl"
    if not summary_path.exists():
        raise SystemExit(f"summary not found: {summary_path}")
    rows = []
    with summary_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    rows = [
        row
        for row in rows
        if row.get("prompt_level") == prompt_level
        and row.get("combo_label") == combo_label
        and not str(row.get("prompt_level") or "").endswith("_fusion")
    ]
    raw_scenes: list[dict[str, Any]] = []
    for row in sorted(rows, key=lambda item: int(item.get("job_index") or 0)):
        parsed_path = row.get("parsed_path")
        if not parsed_path:
            continue
        parsed = load_json(Path(str(parsed_path)))
        scenes = parsed if isinstance(parsed, list) else parsed.get("scenes")
        for scene in scenes or []:
            if isinstance(scene, dict):
                raw_scenes.append(scene)
    return normalize_phase1a_scenes(raw_scenes)


def normalize_phase1a_scenes(raw_scenes: list[dict[str, Any]]) -> list[Phase1aScene]:
    scenes: list[Phase1aScene] = []
    for index, raw in enumerate(raw_scenes, start=1):
        start, end = chapter_range_for(raw)
        if start is None or end is None:
            continue
        scenes.append(
            Phase1aScene(
                scene_id=str(raw.get("scene_id") or f"S{index:04d}"),
                source_index=index,
                title=short_text(raw.get("title")),
                goal=short_text(raw.get("goal")),
                core_conflict=short_text(raw.get("core_conflict")),
                start_chapter=start,
                end_chapter=end,
                boundary_status=short_text(raw.get("boundary_status") or "complete"),
                source_payload=dict(raw),
            ),
        )
    return scenes


def chapter_range_for(raw: dict[str, Any]) -> tuple[int | None, int | None]:
    start = int_or_none(raw.get("start_chapter"))
    end = int_or_none(raw.get("end_chapter"))
    if start is not None and end is not None:
        return min(start, end), max(start, end)
    chunk_indices = [
        int_or_none(chunk.get("chapter_index"))
        for chunk in raw.get("scene_chunks", []) or []
        if isinstance(chunk, dict)
    ]
    chapter_indices = [item for item in chunk_indices if item is not None]
    fallback = [
        int_or_none(item)
        for item in raw.get("_fallback_chapters", []) or []
    ]
    chapter_indices.extend(item for item in fallback if item is not None)
    if not chapter_indices:
        return None, None
    return min(chapter_indices), max(chapter_indices)


def select_scenes(
    scenes: list[Phase1aScene],
    *,
    scene_ids: str,
    sample_size: int,
) -> list[Phase1aScene]:
    requested = [item.strip() for item in scene_ids.split(",") if item.strip()]
    if requested:
        requested_set = set(requested)
        return [scene for scene in scenes if scene.scene_id in requested_set]
    if sample_size <= 0 or sample_size >= len(scenes):
        return scenes
    selected: dict[str, Phase1aScene] = {}
    add_scene(
        selected,
        first_scene(scenes, lambda scene: scene.start_chapter == scene.end_chapter),
        limit=sample_size,
    )
    add_scene(
        selected,
        first_scene(scenes, lambda scene: scene.start_chapter != scene.end_chapter),
        limit=sample_size,
    )
    add_scene(selected, same_chapter_duplicate(scenes), limit=sample_size)
    add_scene(selected, scenes[-1], limit=sample_size)
    if len(selected) < sample_size:
        step = max(1, len(scenes) // sample_size)
        for scene in scenes[::step]:
            add_scene(selected, scene, limit=sample_size)
            if len(selected) >= sample_size:
                break
    for scene in scenes:
        if len(selected) >= sample_size:
            break
        add_scene(selected, scene, limit=sample_size)
    return sorted(selected.values(), key=lambda scene: scene.source_index)


def first_scene(
    scenes: list[Phase1aScene],
    predicate: Callable[[Phase1aScene], bool],
) -> Phase1aScene | None:
    for scene in scenes:
        if predicate(scene):
            return scene
    return None


def same_chapter_duplicate(scenes: list[Phase1aScene]) -> Phase1aScene | None:
    seen: set[tuple[int, int]] = set()
    for scene in scenes:
        key = (scene.start_chapter, scene.end_chapter)
        if key in seen:
            return scene
        seen.add(key)
    return None


def add_scene(
    target: dict[str, Phase1aScene],
    scene: Phase1aScene | None,
    *,
    limit: int | None = None,
) -> None:
    if limit is not None and len(target) >= limit:
        return
    if scene is not None:
        target[scene.scene_id] = scene


def execute_phase1b_jobs(
    jobs: list[Phase1bJob],
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
            item = execute_phase1b_job(
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
                execute_phase1b_job,
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


def execute_phase1b_job(
    job: Phase1bJob,
    *,
    config: dict[str, Any],
    api_key: str,
    chapters: list[Chapter],
    output_dir: Path,
    max_tokens_override: int,
    dry_run: bool,
    print_stream: bool,
) -> dict[str, Any]:
    payload = build_phase1b_payload(
        config=config,
        prompt_template=job.prompt_template,
        scene=job.scene,
        chapters=chapters,
        max_tokens_override=max_tokens_override,
    )
    return run_phase1b_one(
        config=config,
        api_key=api_key,
        payload=payload,
        scene=job.scene,
        output_dir=output_dir,
        dry_run=dry_run,
        print_stream=print_stream,
        job_index=job.job_index,
    )


def build_phase1b_payload(
    *,
    config: dict[str, Any],
    prompt_template: str,
    scene: Phase1aScene,
    chapters: list[Chapter],
    max_tokens_override: int,
) -> dict[str, Any]:
    selected_chapters = [
        chapter
        for chapter in chapters
        if scene.start_chapter <= chapter.index <= scene.end_chapter
    ]
    prompt = fill_prompt_template(
        prompt_template,
        {
            "TEXT": render_chapters(selected_chapters),
            "SCENE_JSON": json.dumps(locked_scene_payload(scene), ensure_ascii=False, indent=2),
        },
    )
    max_tokens = max_tokens_override or int(
        (config.get("max_tokens_by_prompt") or {}).get("phase1b_enrich")
        or (config.get("max_tokens_by_prompt") or {}).get("phase1b")
        or config.get("max_tokens")
        or 2048,
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


def render_chapters(chapters: list[Chapter]) -> str:
    rendered: list[str] = []
    for chapter in chapters:
        title = f"第{chapter.index}章 {chapter.title}".strip()
        rendered.append(f"\n\n{title}\n{chapter.body.strip()}")
    return "".join(rendered).strip()


def run_phase1b_one(
    *,
    config: dict[str, Any],
    api_key: str,
    payload: dict[str, Any],
    scene: Phase1aScene,
    output_dir: Path,
    dry_run: bool,
    print_stream: bool,
    job_index: int,
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

    parsed_json = parse_model_json(raw_response) if raw_response else None
    enrichment, parse_error = parse_enrichment(parsed_json, source_scene=scene)
    fallback_reason = None
    if dry_run:
        enrichment = fallback_enrichment(scene, "dry_run")
        fallback_reason = "dry_run"
    elif error_kind:
        enrichment = fallback_enrichment(scene, str(error_kind))
        fallback_reason = str(error_kind)
    elif parsed_json is None:
        enrichment = fallback_enrichment(scene, "invalid_json")
        fallback_reason = "invalid_json"
        error_kind = error_kind or "schema_error"
        error_message = error_message or "response did not parse as JSON"
    elif parse_error:
        if not enrichment:
            enrichment = fallback_enrichment(scene, parse_error)
        fallback_reason = parse_error
        error_kind = error_kind or "schema_error"
        error_message = error_message or parse_error

    final_scene = merge_scene(scene, enrichment)
    elapsed = round(time.monotonic() - started, 3)
    base_name = f"phase1b_{scene.scene_id}_{scene.start_chapter}-{scene.end_chapter}"
    base_name = safe_filename(base_name)
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
    if parsed_json is not None:
        write_json(parsed_path, enrichment)
    write_json(final_path, final_scene)

    scene_chunks_match = final_scene.get("scene_chunks") == deterministic_scene_chunks(
        scene.start_chapter,
        scene.end_chapter,
    )
    return {
        "job_index": job_index,
        "phase": "phase1b_enrich",
        "scene_id": scene.scene_id,
        "source_index": scene.source_index,
        "title": scene.title,
        "chapter_range": [scene.start_chapter, scene.end_chapter],
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
        "parse_ok": fallback_reason is None,
        "fallback": fallback_reason is not None,
        "fallback_reason": fallback_reason,
        "needs_review": bool(final_scene.get("needs_review")),
        "scene_chunks_match": scene_chunks_match,
        "scene_chunks_mismatch_count": 0 if scene_chunks_match else 1,
        "error_kind": error_kind,
        "error_message": error_message,
        "prompt_path": str(prompt_path),
        "request_path": str(request_path),
        "response_path": str(response_path) if raw_response else None,
        "parsed_path": str(parsed_path) if parsed_json is not None else None,
        "final_path": str(final_path),
        "response_preview": summarize_response(raw_response) if raw_response else None,
    }


def parse_enrichment(
    parsed: Any,
    *,
    source_scene: Phase1aScene | None = None,
) -> tuple[dict[str, Any], str | None]:
    if not isinstance(parsed, dict):
        return {}, "invalid_json_object"
    candidate = parsed.get("enrichment") if isinstance(parsed.get("enrichment"), dict) else parsed
    if not isinstance(candidate, dict):
        return {}, "invalid_enrichment_object"
    enrichment = {
        "emotional_beat": short_text(candidate.get("emotional_beat")),
        "must_happen": short_text(candidate.get("must_happen")),
        "must_not_happen": short_text(candidate.get("must_not_happen")),
        "narrative_tag": short_text(candidate.get("narrative_tag") or "draft"),
        "confidence": confidence_value(candidate.get("confidence")),
        "needs_review": bool_value(candidate.get("needs_review")),
        "review_reason": short_text(candidate.get("review_reason")),
    }
    missing = [
        field
        for field in ("emotional_beat", "must_happen", "must_not_happen")
        if not enrichment[field]
    ]
    if missing and source_scene is not None:
        fallback = fallback_enrichment(source_scene, "missing_" + ",".join(missing))
        fallback.update({key: value for key, value in enrichment.items() if value})
        fallback["needs_review"] = True
        fallback["review_reason"] = fallback.get("review_reason") or "missing_fields"
        return strip_locked_fields(fallback), "missing_fields"
    return strip_locked_fields(enrichment), None


def fallback_enrichment(scene: Phase1aScene, reason: str) -> dict[str, Any]:
    return {
        "emotional_beat": "",
        "must_happen": scene.goal,
        "must_not_happen": scene.core_conflict,
        "narrative_tag": "draft",
        "confidence": 0.6,
        "needs_review": True,
        "review_reason": reason,
    }


def merge_scene(scene: Phase1aScene, enrichment: dict[str, Any]) -> dict[str, Any]:
    final = locked_scene_payload(scene)
    final.update(strip_locked_fields(enrichment))
    final["scene_chunks"] = deterministic_scene_chunks(
        scene.start_chapter,
        scene.end_chapter,
    )
    return final


def strip_locked_fields(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key in ENRICHMENT_FIELDS}


def locked_scene_payload(scene: Phase1aScene) -> dict[str, Any]:
    return {
        "scene_id": scene.scene_id,
        "title": scene.title,
        "goal": scene.goal,
        "core_conflict": scene.core_conflict,
        "start_chapter": scene.start_chapter,
        "end_chapter": scene.end_chapter,
        "boundary_status": scene.boundary_status,
    }


def deterministic_scene_chunks(start_chapter: int, end_chapter: int) -> list[dict[str, int]]:
    return [
        {"chapter_index": chapter_index}
        for chapter_index in range(start_chapter, end_chapter + 1)
    ]


def user_prompt(payload: dict[str, Any]) -> str:
    for message in payload.get("messages", []):
        if message.get("role") == "user":
            return str(message.get("content") or "")
    return ""


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def print_metrics(metrics: dict[str, Any]) -> None:
    chapter_range = metrics.get("chapter_range") or ["?", "?"]
    print(
        " ".join(
            [
                f"scene={metrics.get('scene_id')}",
                f"chapters={chapter_range[0]}-{chapter_range[1]}",
                f"dry={metrics['dry_run']}",
                f"elapsed={metrics.get('elapsed_seconds')}",
                f"parse_ok={metrics.get('parse_ok')}",
                f"fallback={metrics.get('fallback')}",
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
    scene_count: int,
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
            "phase1a_artifact": str(args.phase1a_artifact) if args.phase1a_artifact else None,
            "phase1a_run_dir": str(args.phase1a_run_dir) if args.phase1a_run_dir else None,
            "scene_count": scene_count,
            "sample_size": int(args.sample_size),
            "limit_scenes": int(args.limit_scenes),
            "prompt": str(args.prompt),
            "prompt_dir": str(args.prompt_dir),
            "dry_run": bool(args.dry_run),
            "max_tokens_override": int(args.max_tokens),
            "concurrency": concurrency,
            "config": sanitized_config,
        },
    )


def short_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list | tuple):
        return "；".join(str(item).strip() for item in value if str(item).strip())
    return str(value).strip()


def int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def confidence_value(value: Any) -> float:
    if isinstance(value, bool) or value in (None, ""):
        return 0.6
    try:
        score = float(value)
    except (TypeError, ValueError):
        return 0.6
    if score > 1:
        score /= 100
    return max(0.0, min(score, 1.0))


def bool_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "y", "1", "是", "需要"}
    return bool(value)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        raise SystemExit(130)
