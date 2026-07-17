"""Deterministic Phase 0 planning for deep import Scene extraction."""

from __future__ import annotations

import math
from typing import Any

from pydantic import BaseModel, Field

from shared.deep_import_settings import (
    deep_import_float_setting,
    deep_import_int_setting,
)

PHASE0_TARGET_INPUT_CHARS = 72_000
PHASE0_MAX_CHAPTERS_PER_WINDOW = 20
PHASE0_RIGHT_OVERLAP_CHAPTERS = 2
PHASE0_MAX_TOKENS_PER_INPUT_CHAR = 1.0
PHASE0_MIN_MAX_TOKENS = 13_000
PHASE0_MAX_MAX_TOKENS = 32_768


class SceneWindowPlan(BaseModel):
    """One Phase 1a request window with deterministic ownership."""

    window_index: int = Field(..., ge=1)
    window_id: str
    covered_start: int = Field(..., ge=1)
    covered_end: int = Field(..., ge=1)
    owned_start: int = Field(..., ge=1)
    owned_end: int = Field(..., ge=1)
    chapter_indices: list[int] = Field(default_factory=list)
    owned_chapter_indices: list[int] = Field(default_factory=list)
    input_chars: int = Field(default=0, ge=0)
    max_tokens: int = Field(default=PHASE0_MIN_MAX_TOKENS, ge=1)
    batch_size: int = Field(default=PHASE0_MAX_CHAPTERS_PER_WINDOW, ge=1)
    overlap: int = Field(default=PHASE0_RIGHT_OVERLAP_CHAPTERS, ge=0)
    left_boundary_context: str = ""
    reference_context: dict[str, Any] = Field(default_factory=dict)


class ScenePlanResult(BaseModel):
    """Phase 0 output kept in task state only; chapters may include full text."""

    chapters: list[dict[str, Any]] = Field(default_factory=list)
    windows: list[SceneWindowPlan] = Field(default_factory=list)
    quality_stats: dict[str, Any] = Field(default_factory=dict)
    diagnostics: list[dict[str, Any]] = Field(default_factory=list)
    phase1a_context: dict[str, Any] = Field(default_factory=dict)
    blocked: bool = False
    block_reason: str | None = None


def build_scene_import_plan(
    chapters: list[dict[str, Any]],
    *,
    start_chapter: int,
    end_chapter: int,
    project_settings: dict[str, Any] | None = None,
) -> ScenePlanResult:
    """Build deterministic Phase 1a windows from loaded chapter text."""

    chapters = [
        chapter
        for chapter in sorted(chapters, key=lambda item: int(item["chapter_index"]))
        if start_chapter <= int(chapter["chapter_index"]) <= end_chapter
    ]
    if not chapters:
        return ScenePlanResult(
            quality_stats={
                "parameter_version": "phase0_plan_v1",
                "total_chapters": 0,
                "total_batches": 0,
                "completed_batches": 0,
                "blocked": True,
            },
            diagnostics=[
                {
                    "final_status": "failed",
                    "final_error_type": "empty_result",
                    "message": "no chapter content found for requested range",
                }
            ],
            blocked=True,
            block_reason="no_chapter_content",
        )

    chapter_char_counts = {
        int(chapter["chapter_index"]): len(str(chapter.get("content") or ""))
        for chapter in chapters
    }
    total_chars = sum(chapter_char_counts.values())
    avg_chars = total_chars / len(chapters) if chapters else 0
    overlap = _right_overlap_chapters(project_settings)
    windows = _build_windows(
        chapters,
        chapter_char_counts=chapter_char_counts,
        start_chapter=start_chapter,
        end_chapter=end_chapter,
        overlap=overlap,
        project_settings=project_settings,
    )
    max_tokens_values = [window.max_tokens for window in windows]
    window_chapter_counts = [len(window.chapter_indices) for window in windows]
    quality_stats = {
        "parameter_version": "phase0_plan_v2_char_budget",
        "target_input_chars": _target_input_chars(project_settings),
        "max_chapters_per_window": _max_chapters_per_window(project_settings),
        "selected_batch_size": max(window_chapter_counts) if window_chapter_counts else 0,
        "selected_window_chapter_counts": window_chapter_counts,
        "overlap": overlap,
        "selected_overlap": overlap,
        "max_tokens_per_input_char": _max_tokens_per_input_char(project_settings),
        "min_max_tokens": _min_max_tokens(project_settings),
        "max_max_tokens": _max_max_tokens(project_settings),
        "total_chapters": len(chapters),
        "total_chars": total_chars,
        "avg_chars_per_chapter": round(avg_chars, 2),
        "min_chars_per_chapter": min(chapter_char_counts.values()),
        "max_chars_per_chapter": max(chapter_char_counts.values()),
        "total_batches": len(windows),
        "completed_batches": len(windows),
        "window_count": len(windows),
        "window_input_chars": [window.input_chars for window in windows],
        "window_max_tokens": max_tokens_values,
        "min_window_max_tokens": min(max_tokens_values) if max_tokens_values else 0,
        "max_window_max_tokens": max(max_tokens_values) if max_tokens_values else 0,
        "llm_calls": 0,
    }
    diagnostics = [
        {
            "final_status": "success",
            "source_batch_id": window.window_id,
            "chapter_indices": window.chapter_indices,
            "owned_chapter_indices": window.owned_chapter_indices,
            "input_chars": window.input_chars,
            "max_tokens": window.max_tokens,
        }
        for window in windows
    ]
    return ScenePlanResult(
        chapters=chapters,
        windows=windows,
        quality_stats=quality_stats,
        diagnostics=diagnostics,
        blocked=False,
    )


def _build_windows(
    chapters: list[dict[str, Any]],
    *,
    chapter_char_counts: dict[int, int],
    start_chapter: int,
    end_chapter: int,
    overlap: int,
    project_settings: dict[str, Any] | None,
) -> list[SceneWindowPlan]:
    chapter_by_index = {int(chapter["chapter_index"]): chapter for chapter in chapters}
    windows: list[SceneWindowPlan] = []
    owned_start = start_chapter
    window_index = 1
    target_input_chars = _target_input_chars(project_settings)
    max_chapters = _max_chapters_per_window(project_settings)
    while owned_start <= end_chapter:
        covered_start = owned_start
        chapter_indices: list[int] = []
        input_chars = 0
        for chapter_index in range(covered_start, end_chapter + 1):
            if chapter_index not in chapter_by_index:
                continue
            next_chars = chapter_char_counts.get(chapter_index, 0)
            if chapter_indices and input_chars + next_chars > target_input_chars:
                break
            if len(chapter_indices) >= max_chapters:
                break
            chapter_indices.append(chapter_index)
            input_chars += next_chars

        if not chapter_indices:
            for chapter_index in range(covered_start, end_chapter + 1):
                if chapter_index in chapter_by_index:
                    chapter_indices.append(chapter_index)
                    input_chars = chapter_char_counts.get(chapter_index, 0)
                    break
        if not chapter_indices:
            break

        covered_end = chapter_indices[-1]
        is_last_window = covered_end >= end_chapter
        owned_end = (
            end_chapter if is_last_window else max(covered_start, covered_end - overlap)
        )
        owned_chapter_indices = [
            index
            for index in range(owned_start, owned_end + 1)
            if index in chapter_by_index
        ]
        windows.append(
            SceneWindowPlan(
                window_index=window_index,
                window_id=(
                    f"B{window_index:04d}-{covered_start}-{covered_end}"
                    f"-owned-{owned_start}-{owned_end}"
                ),
                covered_start=covered_start,
                covered_end=covered_end,
                owned_start=owned_start,
                owned_end=owned_end,
                chapter_indices=chapter_indices,
                owned_chapter_indices=owned_chapter_indices,
                input_chars=input_chars,
                max_tokens=_window_max_tokens(input_chars, project_settings),
                batch_size=len(chapter_indices),
                overlap=0 if is_last_window and len(windows) == 0 else overlap,
            )
        )
        if owned_end >= end_chapter:
            break
        owned_start = owned_end + 1
        window_index += 1
    return windows


def _window_max_tokens(
    input_chars: int,
    project_settings: dict[str, Any] | None = None,
) -> int:
    estimated = _round_half_up(input_chars * _max_tokens_per_input_char(project_settings))
    return _clamp(
        estimated,
        _min_max_tokens(project_settings),
        _max_max_tokens(project_settings),
    )


def _round_half_up(value: float) -> int:
    return int(math.floor(value + 0.5))


def _clamp(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(value, maximum))


def _target_input_chars(project_settings: dict[str, Any] | None = None) -> int:
    return deep_import_int_setting(
        project_settings,
        "phase0",
        "target_input_chars",
        env_name="PHASE0_TARGET_INPUT_CHARS",
        default=PHASE0_TARGET_INPUT_CHARS,
    )


def _max_chapters_per_window(project_settings: dict[str, Any] | None = None) -> int:
    return deep_import_int_setting(
        project_settings,
        "phase0",
        "max_chapters_per_window",
        env_name="PHASE0_MAX_CHAPTERS_PER_WINDOW",
        default=PHASE0_MAX_CHAPTERS_PER_WINDOW,
    )


def _right_overlap_chapters(project_settings: dict[str, Any] | None = None) -> int:
    return deep_import_int_setting(
        project_settings,
        "phase0",
        "right_overlap_chapters",
        env_name="PHASE0_RIGHT_OVERLAP_CHAPTERS",
        default=PHASE0_RIGHT_OVERLAP_CHAPTERS,
    )


def _max_tokens_per_input_char(project_settings: dict[str, Any] | None = None) -> float:
    return deep_import_float_setting(
        project_settings,
        "phase0",
        "max_tokens_per_input_char",
        env_name="PHASE0_MAX_TOKENS_PER_INPUT_CHAR",
        default=PHASE0_MAX_TOKENS_PER_INPUT_CHAR,
    )


def _min_max_tokens(project_settings: dict[str, Any] | None = None) -> int:
    return deep_import_int_setting(
        project_settings,
        "phase0",
        "min_max_tokens",
        env_name="PHASE0_MIN_MAX_TOKENS",
        default=PHASE0_MIN_MAX_TOKENS,
    )


def _max_max_tokens(project_settings: dict[str, Any] | None = None) -> int:
    return deep_import_int_setting(
        project_settings,
        "phase0",
        "max_max_tokens",
        env_name="PHASE0_MAX_MAX_TOKENS",
        default=PHASE0_MAX_MAX_TOKENS,
    )
