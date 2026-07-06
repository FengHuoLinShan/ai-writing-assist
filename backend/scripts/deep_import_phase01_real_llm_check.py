#!/usr/bin/env python3
"""Run real DeepSeek validation for the new Phase0/1a/1b Scene path.

This script intentionally avoids database writes. It reads an ignored DeepSeek
probe config, builds the deterministic Phase0 plan from a source text, then
executes the production Phase1a and Phase1b adapters against the real provider.
The output artifact stores only stats and parsed candidate summaries; it never
stores the API key or raw chapter text.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from modules.imports import workflow_llm_adapters as llm_adapters  # noqa: E402
from modules.imports.scene_enrichment import Phase1bSceneEnricher  # noqa: E402
from modules.imports.scene_planning import build_scene_import_plan  # noqa: E402
from modules.imports.scene_slicing import Phase1aSceneSlicer  # noqa: E402
from modules.imports.service_phase_artifacts import (  # noqa: E402
    candidate_chapter_coverage,
    coverage_summary,
)
from modules.imports.workflow_llm_adapters import (  # noqa: E402
    _Phase1aSceneSlicingLLM,
    _Phase1bSceneEnrichmentLLM,
)

CHAPTER_RE = re.compile(
    r"^第([一二三四五六七八九十百千万零〇0-9]+)章[ \t]*(.*)$",
    re.MULTILINE,
)


def main() -> int:
    args = parse_args()
    result = asyncio.run(run(args))
    print(json.dumps(result["console_summary"], ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Real LLM validation for Phase0+Phase1 Scene refactor.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=REPO_ROOT / "tools/deepseek_scene_probe/config.local.json",
    )
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--chapter-start", type=int, default=1)
    parser.add_argument("--chapter-end", type=int, default=60)
    parser.add_argument("--phase1a-concurrency", type=int, default=50)
    parser.add_argument("--phase1b-concurrency", type=int, default=200)
    parser.add_argument("--phase1b-max-tokens", type=int, default=4096)
    parser.add_argument("--high-quality-window-start", type=int, default=1)
    parser.add_argument("--high-quality-window-end", type=int, default=20)
    parser.add_argument(
        "--skip-high-quality",
        action="store_true",
        help="Only run the standard full-range validation.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT / ".test-logs/deep_import_real_llm",
    )
    parser.add_argument("--run-name", default="")
    return parser.parse_args()


async def run(args: argparse.Namespace) -> dict[str, Any]:
    config = load_config(args.config)
    project_settings = project_settings_from_probe_config(config)
    chapters = select_chapters(
        read_chapters(args.source),
        args.chapter_start,
        args.chapter_end,
    )
    if not chapters:
        raise SystemExit("no chapters found for requested range")

    run_name = args.run_name or datetime.now(UTC).strftime(
        "phase01_real_llm_%Y%m%dT%H%M%SZ",
    )
    output_dir = args.output_dir / run_name
    output_dir.mkdir(parents=True, exist_ok=True)
    request_log: list[dict[str, Any]] = []
    original_call_structured = llm_adapters._call_structured
    real_call_structured = llm_adapters._run_deep_import_structured_call

    async def traced_call_structured(client, request, schema, **kwargs):
        request_log.append(
            {
                "step_name": kwargs.get("step_name"),
                "schema": schema.__name__,
                "model": request.model,
                "max_tokens": request.max_tokens,
                "temperature": request.temperature,
                "extra_keys": sorted((request.extra or {}).keys()),
                "thinking_enabled": bool((request.extra or {}).get("thinking")),
                "reasoning_effort": (request.extra or {}).get("reasoning_effort"),
            }
        )
        return await real_call_structured(client, request, schema, **kwargs)

    llm_adapters._call_structured = traced_call_structured
    try:
        standard = await run_phase01(
            chapters=chapters,
            project_settings=project_settings,
            high_quality=False,
            phase1a_concurrency=args.phase1a_concurrency,
            phase1b_concurrency=args.phase1b_concurrency,
            phase1b_max_tokens=args.phase1b_max_tokens,
        )
        high_quality = None
        if not args.skip_high_quality:
            hq_chapters = select_chapters(
                chapters,
                args.high_quality_window_start,
                args.high_quality_window_end,
            )
            high_quality = await run_phase01(
                chapters=hq_chapters,
                project_settings=project_settings,
                high_quality=True,
                phase1a_concurrency=1,
                phase1b_concurrency=args.phase1b_concurrency,
                phase1b_max_tokens=args.phase1b_max_tokens,
            )
    finally:
        llm_adapters._call_structured = original_call_structured

    artifact = {
        "run_name": run_name,
        "created_at": datetime.now(UTC).isoformat(),
        "source_path": str(args.source),
        "chapter_range": [args.chapter_start, args.chapter_end],
        "provider": provider_summary(config),
        "standard": standard,
        "high_quality": high_quality,
        "request_log": request_log,
    }
    ok = validation_ok(artifact)
    artifact["ok"] = ok
    artifact_path = output_dir / "phase01_real_llm_artifact.json"
    summary_path = output_dir / "phase01_real_llm_summary.md"
    artifact_path.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    summary_path.write_text(render_summary(artifact, artifact_path), encoding="utf-8")
    write_latest_pointer(args.output_dir / "latest-phase01", output_dir)
    return {
        "ok": ok,
        "console_summary": {
            "ok": ok,
            "run_name": run_name,
            "artifact": str(artifact_path),
            "summary": str(summary_path),
            "standard": compact_console_result(standard),
            "high_quality": compact_console_result(high_quality)
            if high_quality
            else None,
        },
    }


async def run_phase01(
    *,
    chapters: list[dict[str, Any]],
    project_settings: dict[str, Any],
    high_quality: bool,
    phase1a_concurrency: int,
    phase1b_concurrency: int,
    phase1b_max_tokens: int,
) -> dict[str, Any]:
    start = int(chapters[0]["chapter_index"])
    end = int(chapters[-1]["chapter_index"])
    started_at = time.monotonic()
    phase0 = build_scene_import_plan(
        chapters,
        start_chapter=start,
        end_chapter=end,
    )
    phase1a = await Phase1aSceneSlicer(
        _Phase1aSceneSlicingLLM(
            project_settings=project_settings,
            high_quality=high_quality,
        ),
        concurrency=phase1a_concurrency,
    ).run(phase0)
    phase1a_coverage = candidate_chapter_coverage(
        phase1a.candidates,
        start,
        end,
    )
    phase1b = await Phase1bSceneEnricher(
        _Phase1bSceneEnrichmentLLM(
            project_settings=project_settings,
            high_quality=high_quality,
        ),
        concurrency=phase1b_concurrency,
        max_tokens=phase1b_max_tokens,
    ).run(
        scenes=phase1a.candidates,
        chapters=phase0.chapters,
    )
    phase1b_coverage = candidate_chapter_coverage(
        phase1b.candidates,
        start,
        end,
    )
    return {
        "chapter_range": [start, end],
        "duration_seconds": round(time.monotonic() - started_at, 2),
        "high_quality": high_quality,
        "phase0": {
            "quality_stats": phase0.quality_stats,
            "coverage": coverage_summary(
                {int(chapter["chapter_index"]) for chapter in phase0.chapters},
                start,
                end,
            ),
            "windows": [
                window.model_dump(
                    mode="json",
                    exclude={"chapter_indices", "owned_chapter_indices"},
                )
                for window in phase0.windows
            ],
        },
        "phase1a": {
            "quality_stats": phase1a.quality_stats,
            "coverage": phase1a_coverage,
            "diagnostics": phase1a.diagnostics,
            "scene_count": len(phase1a.candidates),
            "sample_scenes": [
                {
                    "title": scene.title,
                    "start_chapter": scene.start_chapter,
                    "end_chapter": scene.end_chapter,
                    "boundary_status": scene.boundary_status,
                    "needs_review": scene.needs_review,
                }
                for scene in phase1a.candidates[:10]
            ],
        },
        "phase1b": {
            "quality_stats": phase1b.quality_stats,
            "coverage": phase1b_coverage,
            "diagnostics": phase1b.diagnostics,
            "scene_count": len(phase1b.candidates),
            "sample_scenes": [
                {
                    "title": scene.title,
                    "start_chapter": min(scene.source_chapter_indices or [0]),
                    "end_chapter": max(scene.source_chapter_indices or [0]),
                    "narrative_tag": scene.narrative_tag,
                    "confidence": scene.confidence,
                    "needs_review": scene.needs_review,
                    "fallback_required": scene.fallback_required,
                }
                for scene in phase1b.candidates[:10]
            ],
        },
    }


def validation_ok(artifact: dict[str, Any]) -> bool:
    standard = artifact["standard"]
    if not phase_result_ok(standard):
        return False
    high_quality = artifact.get("high_quality")
    if high_quality is not None:
        if not phase_result_ok(high_quality):
            return False
        hq_models = [
            entry["model"]
            for entry in artifact["request_log"]
            if entry.get("model") == "deepseek-v4-pro"
        ]
        if not hq_models:
            return False
    return True


def phase_result_ok(result: dict[str, Any]) -> bool:
    return bool(
        result["phase0"]["coverage"]["coverage_complete"]
        and result["phase1a"]["coverage"]["coverage_complete"]
        and result["phase1b"]["coverage"]["coverage_complete"]
        and result["phase1a"]["quality_stats"].get("failed", 0) == 0
        and result["phase1b"]["quality_stats"].get("fallback_count", 0) == 0
    )


def compact_console_result(result: dict[str, Any] | None) -> dict[str, Any] | None:
    if result is None:
        return None
    return {
        "chapter_range": result["chapter_range"],
        "duration_seconds": result["duration_seconds"],
        "phase0_windows": result["phase0"]["quality_stats"].get("window_count"),
        "phase1a_scene_count": result["phase1a"]["scene_count"],
        "phase1a_failed": result["phase1a"]["quality_stats"].get("failed"),
        "phase1a_fallback_count": result["phase1a"]["quality_stats"].get(
            "fallback_count",
        ),
        "phase1b_scene_count": result["phase1b"]["scene_count"],
        "phase1b_fallback_count": result["phase1b"]["quality_stats"].get(
            "fallback_count",
        ),
        "phase1b_coverage_complete": result["phase1b"]["coverage"][
            "coverage_complete"
        ],
    }


def render_summary(artifact: dict[str, Any], artifact_path: Path) -> str:
    standard = compact_console_result(artifact["standard"]) or {}
    high_quality = compact_console_result(artifact.get("high_quality")) or {}
    hq_models = sorted(
        {
            entry["model"]
            for entry in artifact["request_log"]
            if entry.get("model") == "deepseek-v4-pro"
        }
    )
    return "\n".join(
        [
            "# Phase0/1 Real LLM Validation",
            "",
            f"- OK: `{artifact['ok']}`",
            f"- Artifact: `{artifact_path}`",
            f"- Provider model: `{artifact['provider']['model']}`",
            f"- Standard range: `{standard.get('chapter_range')}`",
            f"- Standard Phase0 windows: `{standard.get('phase0_windows')}`",
            f"- Standard Phase1a scenes: `{standard.get('phase1a_scene_count')}`",
            f"- Standard Phase1b fallbacks: `{standard.get('phase1b_fallback_count')}`",
            f"- Standard duration seconds: `{standard.get('duration_seconds')}`",
            f"- High-quality range: `{high_quality.get('chapter_range')}`",
            f"- High-quality Phase1a scenes: `{high_quality.get('phase1a_scene_count')}`",
            "- High-quality Phase1b fallbacks: "
            f"`{high_quality.get('phase1b_fallback_count')}`",
            f"- High-quality request models: `{hq_models}`",
            "",
        ]
    )


def read_chapters(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8-sig")
    matches = list(CHAPTER_RE.finditer(text))
    chapters: list[dict[str, Any]] = []
    for offset, match in enumerate(matches):
        start = match.end()
        end = matches[offset + 1].start() if offset + 1 < len(matches) else len(text)
        index = parse_chinese_chapter_number(match.group(1))
        title_suffix = match.group(2).strip()
        title = f"第{match.group(1)}章"
        if title_suffix:
            title += f" {title_suffix}"
        chapters.append(
            {
                "chapter_index": index,
                "title": title,
                "content": text[start:end].strip(),
            }
        )
    return chapters


def select_chapters(
    chapters: list[dict[str, Any]],
    start: int,
    end: int,
) -> list[dict[str, Any]]:
    return [
        chapter
        for chapter in chapters
        if start <= int(chapter["chapter_index"]) <= end
    ]


def parse_chinese_chapter_number(raw: str) -> int:
    raw = raw.strip()
    if raw.isdigit():
        return int(raw)
    digits = {"零": 0, "〇": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
              "六": 6, "七": 7, "八": 8, "九": 9}
    units = {"十": 10, "百": 100, "千": 1000, "万": 10000}
    total = 0
    section = 0
    number = 0
    for char in raw:
        if char in digits:
            number = digits[char]
        elif char in units:
            unit = units[char]
            if unit == 10000:
                section = (section + number) * unit
                total += section
                section = 0
            else:
                section += (number or 1) * unit
            number = 0
    return total + section + number


def load_config(path: Path) -> dict[str, Any]:
    config = json.loads(path.read_text(encoding="utf-8"))
    if not str(config.get("api_key") or "").strip():
        raise SystemExit(f"api_key is empty in {path}")
    return config


def project_settings_from_probe_config(config: dict[str, Any]) -> dict[str, Any]:
    extra: dict[str, Any] = {}
    if config.get("thinking") is not None:
        extra["thinking"] = config["thinking"]
    if config.get("reasoning_effort") is not None:
        extra["reasoning_effort"] = config["reasoning_effort"]
    return {
        "llm": {
            "provider_id": "deepseek",
            "label": "DeepSeek",
            "api_key": str(config.get("api_key") or ""),
            "base_url": str(config.get("base_url") or "https://api.deepseek.com"),
            "model": str(config.get("model") or "deepseek-v4-flash"),
            "timeout": int(config.get("timeout_seconds") or 300),
            "max_tokens": int(config.get("max_tokens") or 4096),
            "temperature": float(config.get("temperature") or 0.2),
            "extra": extra,
        }
    }


def provider_summary(config: dict[str, Any]) -> dict[str, Any]:
    parsed = urlparse(str(config.get("base_url") or ""))
    return {
        "base_url_host": parsed.netloc,
        "model": config.get("model"),
        "api_key_configured": bool(str(config.get("api_key") or "").strip()),
        "thinking_configured": bool(config.get("thinking")),
        "reasoning_effort": config.get("reasoning_effort"),
    }


def write_latest_pointer(pointer_path: Path, output_dir: Path) -> None:
    try:
        pointer_path.parent.mkdir(parents=True, exist_ok=True)
        pointer_path.write_text(str(output_dir), encoding="utf-8")
    except OSError:
        pass


if __name__ == "__main__":
    raise SystemExit(main())
