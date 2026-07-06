"""Shared helpers for Phase2/Phase3 probe scripts.

These helpers are intentionally local to the isolated DeepSeek probe tool. They
do not import backend modules and do not write the application database.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from probe import Batch, Chapter, render_chapters


TARGET_INPUT_CHARS = 72_000
MAX_WINDOW_CHAPTERS = 20
RIGHT_OVERLAP_CHAPTERS = 2


@dataclass(frozen=True)
class ProbeScene:
    scene_id: str
    source_index: int
    title: str
    goal: str
    core_conflict: str
    start_chapter: int
    end_chapter: int
    boundary_status: str
    emotional_beat: str
    must_happen: str
    must_not_happen: str
    narrative_tag: str
    confidence: float
    needs_review: bool
    review_reason: str
    source_payload: dict[str, Any]


def load_phase1b_final_scenes(
    run_dir: Path,
    *,
    repair_run_dirs: list[Path] | None = None,
    chapter_start: int | None = None,
    chapter_end: int | None = None,
) -> list[ProbeScene]:
    scenes_by_id = load_phase1b_final_scene_map(run_dir)
    for repair_dir in repair_run_dirs or []:
        scenes_by_id.update(load_phase1b_final_scene_map(repair_dir))
    scenes = list(scenes_by_id.values())
    if chapter_start is not None and chapter_end is not None:
        scenes = [
            scene
            for scene in scenes
            if ranges_overlap(
                scene.start_chapter,
                scene.end_chapter,
                chapter_start,
                chapter_end,
            )
        ]
    return sorted(scenes, key=lambda scene: (scene.source_index, scene.scene_id))


def load_phase1b_final_scene_map(run_dir: Path) -> dict[str, ProbeScene]:
    summary_path = run_dir / "summary.jsonl"
    if not summary_path.exists():
        raise SystemExit(f"Phase1b summary not found: {summary_path}")
    result: dict[str, ProbeScene] = {}
    for row in read_jsonl(summary_path):
        final_path = row.get("final_path")
        if not final_path:
            continue
        path = Path(str(final_path))
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        scene = normalize_phase1b_scene(payload, row)
        if scene is not None:
            result[scene.scene_id] = scene
    return result


def normalize_phase1b_scene(
    payload: dict[str, Any],
    row: dict[str, Any],
) -> ProbeScene | None:
    scene_id = short_text(payload.get("scene_id") or row.get("scene_id"))
    if not scene_id:
        return None
    start = int_or_none(payload.get("start_chapter"))
    end = int_or_none(payload.get("end_chapter"))
    if start is None or end is None:
        chapter_range = row.get("chapter_range") or []
        if len(chapter_range) >= 2:
            start = int_or_none(chapter_range[0])
            end = int_or_none(chapter_range[1])
    if start is None or end is None:
        return None
    source_index = int_or_none(row.get("source_index"))
    if source_index is None:
        source_index = scene_index_from_id(scene_id) or 0
    confidence = confidence_value(payload.get("confidence"))
    return ProbeScene(
        scene_id=scene_id,
        source_index=source_index,
        title=short_text(payload.get("title")),
        goal=short_text(payload.get("goal")),
        core_conflict=short_text(payload.get("core_conflict")),
        start_chapter=min(start, end),
        end_chapter=max(start, end),
        boundary_status=short_text(payload.get("boundary_status") or "complete"),
        emotional_beat=short_text(payload.get("emotional_beat")),
        must_happen=short_text(payload.get("must_happen")),
        must_not_happen=short_text(payload.get("must_not_happen")),
        narrative_tag=short_text(payload.get("narrative_tag")),
        confidence=confidence,
        needs_review=bool_value(payload.get("needs_review")),
        review_reason=short_text(payload.get("review_reason")),
        source_payload=dict(payload),
    )


def build_phase0_charbudget_windows(
    chapters: list[Chapter],
    *,
    chapter_start: int,
    chapter_end: int,
    target_input_chars: int = TARGET_INPUT_CHARS,
    max_window_chapters: int = MAX_WINDOW_CHAPTERS,
    overlap_chapters: int = RIGHT_OVERLAP_CHAPTERS,
) -> list[Batch]:
    chapter_by_index = {chapter.index: chapter for chapter in chapters}
    windows: list[Batch] = []
    current = chapter_start
    index = 1
    while current <= chapter_end:
        included: list[Chapter] = []
        cursor = current
        while cursor <= chapter_end and len(included) < max_window_chapters:
            chapter = chapter_by_index.get(cursor)
            if chapter is None:
                cursor += 1
                continue
            candidate = [*included, chapter]
            candidate_chars = len(render_chapters(candidate))
            if included and candidate_chars > target_input_chars:
                break
            included = candidate
            cursor += 1
        if not included:
            break
        input_start = included[0].index
        input_end = included[-1].index
        if input_end >= chapter_end:
            owned_end = input_end
        else:
            owned_end = max(input_start, input_end - overlap_chapters)
        overlap_start = owned_end + 1 if owned_end < input_end else None
        overlap_end = input_end if overlap_start is not None else None
        windows.append(
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
    return windows


def build_windows(
    chapters: list[Chapter],
    *,
    mode: str,
    chapter_start: int,
    chapter_end: int,
) -> list[Batch]:
    if mode == "phase0_charbudget":
        return build_phase0_charbudget_windows(
            chapters,
            chapter_start=chapter_start,
            chapter_end=chapter_end,
        )
    if mode == "single_range":
        return [
            Batch(
                batch_id=f"B0001-{chapter_start}-{chapter_end}",
                input_start=chapter_start,
                input_end=chapter_end,
                owned_start=chapter_start,
                owned_end=chapter_end,
                overlap_start=None,
                overlap_end=None,
            ),
        ]
    raise SystemExit(f"unknown window mode: {mode}")


def scenes_in_range(
    scenes: list[ProbeScene],
    *,
    start: int,
    end: int,
) -> list[ProbeScene]:
    return [
        scene
        for scene in scenes
        if ranges_overlap(scene.start_chapter, scene.end_chapter, start, end)
    ]


def scenes_owned_by_window(scenes: list[ProbeScene], batch: Batch) -> list[ProbeScene]:
    return [
        scene
        for scene in scenes
        if batch.owned_start <= scene.start_chapter <= batch.owned_end
    ]


def render_scene_cards(scenes: list[ProbeScene]) -> str:
    cards = [
        {
            "scene_id": scene.scene_id,
            "title": scene.title,
            "goal": scene.goal,
            "core_conflict": scene.core_conflict,
            "start_chapter": scene.start_chapter,
            "end_chapter": scene.end_chapter,
            "boundary_status": scene.boundary_status,
            "emotional_beat": scene.emotional_beat,
            "must_happen": scene.must_happen,
            "must_not_happen": scene.must_not_happen,
            "narrative_tag": scene.narrative_tag,
            "needs_review": scene.needs_review,
        }
        for scene in scenes
    ]
    return json.dumps(cards, ensure_ascii=False, indent=2)


def render_world_summary(payload: dict[str, Any]) -> str:
    compact = {
        "objects": payload.get("objects") or [],
        "relations": payload.get("relations") or [],
        "deltas": payload.get("deltas") or [],
        "uncertain_items": payload.get("uncertain_items") or [],
    }
    return json.dumps(compact, ensure_ascii=False, indent=2)


def valid_scene_ids(scenes: list[ProbeScene]) -> set[str]:
    return {scene.scene_id for scene in scenes}


def chapter_range_for_scene_ids(
    scene_ids: list[str],
    scenes_by_id: dict[str, ProbeScene],
) -> list[int] | None:
    chapters: list[int] = []
    for scene_id in scene_ids:
        scene = scenes_by_id.get(scene_id)
        if scene is None:
            continue
        chapters.extend([scene.start_chapter, scene.end_chapter])
    if not chapters:
        return None
    return [min(chapters), max(chapters)]


def normalize_scene_refs(
    value: Any,
    allowed_scene_ids: set[str],
) -> tuple[list[str], int]:
    raw_values: list[Any]
    if isinstance(value, list):
        raw_values = value
    elif value in (None, ""):
        raw_values = []
    else:
        raw_values = [value]
    normalized: list[str] = []
    invalid_count = 0
    for raw in raw_values:
        scene_id = short_text(raw)
        if not scene_id:
            continue
        if scene_id in allowed_scene_ids:
            normalized.append(scene_id)
        else:
            invalid_count += 1
    return dedupe_keep_order(normalized), invalid_count


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def ranges_overlap(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    return max(a_start, b_start) <= min(a_end, b_end)


def dedupe_keep_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def normalized_name(value: Any) -> str:
    return re.sub(r"\s+", "", short_text(value)).casefold()


def duplicate_name_ratio(items: list[dict[str, Any]]) -> float:
    names = [normalized_name(item.get("name")) for item in items if item.get("name")]
    if not names:
        return 0.0
    unique_count = len(set(names))
    return round((len(names) - unique_count) / len(names), 3)


def scene_index_from_id(scene_id: str) -> int | None:
    match = re.search(r"(\d+)$", scene_id)
    if not match:
        return None
    return int(match.group(1))


def short_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list | tuple):
        return "；".join(str(item).strip() for item in value if str(item).strip())
    return str(value).strip()


def list_text(value: Any) -> list[str]:
    if isinstance(value, list):
        return [short_text(item) for item in value if short_text(item)]
    text = short_text(value)
    return [text] if text else []


def int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def confidence_value(value: Any, *, default: float = 0.6) -> float:
    if isinstance(value, bool) or value in (None, ""):
        return default
    try:
        score = float(value)
    except (TypeError, ValueError):
        return default
    if score > 1:
        score /= 100
    return max(0.0, min(score, 1.0))


def bool_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "y", "1", "是", "需要"}
    return bool(value)
