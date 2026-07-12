"""Repair Scene eval gold into canonical chapter-local source ranges."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from evals.cache import EvalCache
from evals.codex_executor import CodexExecutionError, CodexStructuredExecutor
from evals.corpus import build_corpus_snapshot
from evals.schemas import DatasetCase, EvalSuite, LogicalSourceRef


class SceneGoldSegment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chapter_index: int = Field(ge=1)
    start_anchor: str = Field(min_length=8, max_length=80)
    end_anchor: str = Field(min_length=8, max_length=80)


class SceneGoldLocation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1)
    segments: list[SceneGoldSegment] = Field(min_length=1)
    reason: str = Field(min_length=1)


class SceneGoldLocationBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    locations: list[SceneGoldLocation] = Field(min_length=1)


async def repair_scene_gold_cases(
    cases: list[DatasetCase],
    *,
    source_path: Path,
    source_alias: str,
    cache: EvalCache,
    primary_executor: CodexStructuredExecutor,
    fallback_executor: CodexStructuredExecutor | None = None,
    cache_only: bool = False,
) -> tuple[list[DatasetCase], dict[str, Any]]:
    """Locate accepted Scene references in frozen canonical chapter text."""
    snapshot = build_corpus_snapshot(source_path, source_alias=source_alias)
    source_text = source_path.read_text(encoding="utf-8-sig")
    chapters = {
        chapter.chapter_index: (
            chapter,
            source_text[chapter.start_offset : chapter.end_offset],
        )
        for chapter in snapshot.chapters
    }
    grouped: dict[str, list[DatasetCase]] = defaultdict(list)
    for case in cases:
        if case.suite == EvalSuite.scene:
            grouped[case.source_group_id].append(case)

    repaired_by_id: dict[str, DatasetCase] = {}
    runs: list[dict[str, Any]] = []
    for source_group_id, group_cases in sorted(grouped.items()):
        chapter_indices = sorted(
            {index for case in group_cases for index in _case_chapter_indices(case)}
        )
        chapter_payload = [
            {
                "chapter_index": index,
                "content": chapters[index][1],
            }
            for index in chapter_indices
        ]
        case_payload = [
            {
                "case_id": case.case_id,
                "scenario": case.scenario,
                "allowed_chapter_indices": _case_chapter_indices(case),
                "input": case.input,
                "reference": case.reference,
            }
            for case in group_cases
        ]
        prompt = _repair_prompt(chapter_payload, case_payload)
        prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        cache_payload = {
            "step": "scene_gold_canonical_range_v1",
            "source_file_hash": snapshot.file_hash,
            "source_group_id": source_group_id,
            "prompt_hash": prompt_hash,
            "primary_model": primary_executor.model,
            "fallback_model": fallback_executor.model if fallback_executor else None,
        }
        cache_key = cache.key(cache_payload)
        cached = cache.get("scene-gold", cache_key)
        used_executor = primary_executor
        if cached is not None:
            batch = SceneGoldLocationBatch.model_validate(cached["result"])
            used_model = str(cached["model"])
            cached_result = True
        elif cache_only:
            raise RuntimeError(
                f"scene gold cache miss for source group {source_group_id}"
            )
        else:
            try:
                batch = await primary_executor.generate_structured(
                    prompt,
                    SceneGoldLocationBatch,
                    step_name="scene_gold_canonical_range",
                )
            except CodexExecutionError:
                if fallback_executor is None:
                    raise
                used_executor = fallback_executor
                batch = await fallback_executor.generate_structured(
                    prompt,
                    SceneGoldLocationBatch,
                    step_name="scene_gold_canonical_range_fallback",
                )
            used_model = used_executor.model
            cached_result = False
            cache.put(
                "scene-gold",
                cache_key,
                {
                    "model": used_model,
                    "result": batch.model_dump(mode="json"),
                },
            )

        expected_ids = {case.case_id for case in group_cases}
        actual_ids = {location.case_id for location in batch.locations}
        if actual_ids != expected_ids or len(batch.locations) != len(expected_ids):
            raise ValueError(
                f"scene gold case IDs mismatch for {source_group_id}: "
                f"missing={sorted(expected_ids - actual_ids)}, "
                f"extra={sorted(actual_ids - expected_ids)}"
            )
        locations = {location.case_id: location for location in batch.locations}
        for case in group_cases:
            repaired_by_id[case.case_id] = _materialize_case_ranges(
                case,
                locations[case.case_id],
                chapters=chapters,
                corpus_id=snapshot.corpus_id,
                source_alias=source_alias,
                model=used_model,
                prompt_hash=prompt_hash,
            )
        runs.append(
            {
                "source_group_id": source_group_id,
                "case_count": len(group_cases),
                "chapter_indices": chapter_indices,
                "model": used_model,
                "reasoning_effort": used_executor.reasoning_effort,
                "prompt_hash": prompt_hash,
                "cache_key": cache_key,
                "cached": cached_result,
            }
        )

    repaired = [repaired_by_id.get(case.case_id, case) for case in cases]
    return repaired, {
        "repair_version": "scene-gold-canonical-range-v1",
        "source_alias": source_alias,
        "source_file_hash": snapshot.file_hash,
        "scene_case_count": len(repaired_by_id),
        "runs": runs,
    }


def _repair_prompt(
    chapters: list[dict[str, Any]],
    cases: list[dict[str, Any]],
) -> str:
    return (
        "你是小说 Scene 边界标注员。输入包含冻结的完整章节正文和若干已通过语义"
        "审核的 Scene 评测 case。请把每个 case 所描述的叙事 Scene 定位回 canonical"
        "正文。这里要标注的是完整 Scene 的起止边界，不只是答案中的单个事实句。\n\n"
        "规则：\n"
        "1. 每个 case_id 恰好输出一次，不得遗漏或新增。\n"
        "2. segments 只可使用 allowed_chapter_indices；跨章 Scene 每章一个 segment，"
        "不得把不连续章节合并成一段。\n"
        "3. start_anchor 是该章内 Scene 段落开始处逐字复制的 8-80 个连续字符；"
        "end_anchor 是段落结束处逐字复制的 8-80 个连续字符，并包含 Scene 最后字符。\n"
        "4. anchor 必须在对应章节正文中唯一出现；不得概括、改字、删字、使用省略号"
        "代替原文。保留原标点；可选择不含换行的连续短句。\n"
        "5. 同一 reference 的不同 persona 问法应返回相同 segments。\n"
        "6. 只做只读定位，不修改 input/reference 的语义结论。\n\n"
        f"chapters={json.dumps(chapters, ensure_ascii=False)}\n\n"
        f"cases={json.dumps(cases, ensure_ascii=False, sort_keys=True)}"
    )


def _materialize_case_ranges(
    case: DatasetCase,
    location: SceneGoldLocation,
    *,
    chapters: dict[int, tuple[Any, str]],
    corpus_id: str,
    source_alias: str,
    model: str,
    prompt_hash: str,
) -> DatasetCase:
    allowed = set(_case_chapter_indices(case))
    refs: list[LogicalSourceRef] = []
    for segment in location.segments:
        if segment.chapter_index not in allowed:
            raise ValueError(
                f"{case.case_id}: chapter {segment.chapter_index} is outside source refs"
            )
        chapter, content = chapters[segment.chapter_index]
        start_matches = _anchor_ranges(content, segment.start_anchor)
        end_matches = _anchor_ranges(content, segment.end_anchor)
        if len(start_matches) != 1 or len(end_matches) != 1:
            raise ValueError(
                f"{case.case_id}: anchors must be unique in chapter "
                f"{segment.chapter_index}; starts={len(start_matches)}, "
                f"ends={len(end_matches)}"
            )
        start_offset = start_matches[0][0]
        end_offset = end_matches[0][1]
        if start_offset >= end_offset:
            raise ValueError(
                f"{case.case_id}: anchors are reversed in chapter {segment.chapter_index}"
            )
        range_text = content[start_offset:end_offset]
        refs.append(
            LogicalSourceRef(
                corpus_id=corpus_id,
                source_alias=source_alias,
                source_group_id=chapter.source_group_id,
                chapter_index=segment.chapter_index,
                content_hash=chapter.content_hash,
                range_hash=hashlib.sha256(range_text.encode("utf-8")).hexdigest(),
                start_offset=start_offset,
                end_offset=end_offset,
            )
        )
    refs.sort(key=lambda ref: (ref.chapter_index, ref.start_offset or 0))
    reference = dict(case.reference)
    reference["boundary_coordinate_system"] = "canonical_chapter_offset_v1"
    reference["canonical_range_meta"] = {
        "model": model,
        "prompt_hash": prompt_hash,
        "reason": location.reason,
    }
    return case.model_copy(update={"source_refs": refs, "reference": reference})


def _case_chapter_indices(case: DatasetCase) -> list[int]:
    indices = {ref.chapter_index for ref in case.source_refs}
    indices.update(int(value) for value in case.reference.get("chapter_indices", []))
    return sorted(indices)


def _anchor_ranges(content: str, anchor: str) -> list[tuple[int, int]]:
    for variant in _anchor_variants(anchor):
        matches = _normalized_anchor_ranges(content, variant)
        if matches:
            return matches
    return []


def _anchor_variants(anchor: str) -> list[str]:
    normalized = anchor.strip()
    if not normalized:
        return []
    variants = [normalized]
    quote_pairs = (("“", "”"), ("‘", "’"), ('"', '"'), ("'", "'"))
    for opening, closing in quote_pairs:
        if normalized.startswith(opening) and normalized.endswith(closing):
            inner = normalized[len(opening) : -len(closing)].strip()
            if inner and inner not in variants:
                variants.append(inner)
    return variants


def _normalized_anchor_ranges(content: str, anchor: str) -> list[tuple[int, int]]:
    matches = _ranges_with_normalizer(content, anchor, ignore_punctuation=False)
    if matches:
        return matches
    matches = _ranges_with_normalizer(content, anchor, ignore_punctuation=True)
    if matches:
        return matches
    return _approximate_anchor_ranges(content, anchor)


def _approximate_anchor_ranges(content: str, anchor: str) -> list[tuple[int, int]]:
    normalized_content, positions = _normalize_with_positions(
        content,
        ignore_punctuation=True,
    )
    normalized_anchor, _ = _normalize_with_positions(
        anchor,
        ignore_punctuation=True,
    )
    anchor_length = len(normalized_anchor)
    if anchor_length < 8 or not normalized_content:
        return []
    candidates: list[tuple[float, int, int]] = []
    for window_length in range(max(8, anchor_length - 4), anchor_length + 5):
        for start in range(0, len(normalized_content) - window_length + 1):
            end = start + window_length
            ratio = SequenceMatcher(
                None,
                normalized_anchor,
                normalized_content[start:end],
                autojunk=False,
            ).ratio()
            if ratio >= 0.92:
                candidates.append((ratio, start, end))
    if not candidates:
        return []
    candidates.sort(reverse=True)
    best_ratio, best_start, best_end = candidates[0]
    competing = [
        ratio
        for ratio, start, end in candidates[1:]
        if end <= best_start or start >= best_end
    ]
    if competing and best_ratio - max(competing) < 0.05:
        return []
    return [(positions[best_start], positions[best_end - 1] + 1)]


def _ranges_with_normalizer(
    content: str,
    anchor: str,
    *,
    ignore_punctuation: bool,
) -> list[tuple[int, int]]:
    normalized_content, positions = _normalize_with_positions(
        content,
        ignore_punctuation=ignore_punctuation,
    )
    normalized_anchor, _ = _normalize_with_positions(
        anchor,
        ignore_punctuation=ignore_punctuation,
    )
    if not normalized_anchor:
        return []
    matches: list[tuple[int, int]] = []
    start = 0
    while True:
        index = normalized_content.find(normalized_anchor, start)
        if index < 0:
            break
        matches.append(
            (positions[index], positions[index + len(normalized_anchor) - 1] + 1)
        )
        start = index + 1
    return matches


def _normalize_with_positions(
    content: str,
    *,
    ignore_punctuation: bool = False,
) -> tuple[str, list[int]]:
    characters: list[str] = []
    positions: list[int] = []
    for index, character in enumerate(content):
        if character.isspace():
            continue
        if ignore_punctuation and unicodedata.category(character).startswith("P"):
            continue
        characters.append(character)
        positions.append(index)
    return "".join(characters), positions
