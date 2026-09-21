"""Bounded parent reads using existing immutable manuscript ranges and Scene spans."""

from dataclasses import asdict

from core.errors import NotFoundError, ValidationError


def bounded_ranges(start, end, *, allowed=None, excluded=()):
    """Intersect authorized intervals, then subtract exclusions; never bridge a gap."""
    ranges = (
        [(start, end)]
        if allowed is None
        else [(max(start, left), min(end, right)) for left, right in allowed]
    )
    merged = []
    for left, right in sorted((a, b) for a, b in ranges if a < b):
        if merged and left <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(right, merged[-1][1]))
        else:
            merged.append((left, right))
    for cut_start, cut_end in excluded:
        remaining = []
        for left, right in merged:
            if cut_end <= left or cut_start >= right:
                remaining.append((left, right))
            else:
                if left < cut_start:
                    remaining.append((left, cut_start))
                if cut_end < right:
                    remaining.append((cut_end, right))
        merged = remaining
    return merged


async def read_parent_context(
    reader,
    db,
    *,
    novel_id,
    source_ref,
    visibility,
    source_manifest=None,
    allowed_ranges=None,
    excluded_ranges=(),
    max_characters=12000,
):
    """Only callers holding the original confirmation may supply its frozen scope.

    Browser reads have no confirmation and use the current source manifest. A
    character's range expansion is deliberately withheld: a Scene mapping alone
    does not prove the character knows all of its contents.
    """
    from modules.story.facade import get_scene_spans_by_chapter, get_scene_spans_for_scene
    from modules.writing.facade import (
        build_manuscript_range_ref,
        get_draft,
        get_manuscript_source_manifest,
    )

    if not 0 < max_characters <= 12000:
        raise ValueError("parent read budget must be between 1 and 12000 characters")
    result = {"policy": "scene-or-paragraph-v1", "segments": [], "omissions": []}
    omissions = result["omissions"]
    if visibility.mode == "character":
        omissions.append("character_knowledge_unproven")
        return {**result, "complete": False}
    manifest_rows = await get_manuscript_source_manifest(
        db,
        novel_id,
        content_mode=source_ref.content_mode,
        source_manifest=source_manifest,
    )
    manifest = {row["draft_id"]: row["source_hash"] for row in manifest_rows}
    if manifest.get(source_ref.draft_id) != source_ref.source_hash:
        raise ValidationError("父级原文来源已变化，请重新查找证据")
    spans = await get_scene_spans_by_chapter(
        db,
        novel_id,
        source_ref.chapter_index,
        content_mode=source_ref.content_mode,
    )
    matching = [
        span
        for span in spans
        if span.mapping_status in {"exact", "reanchored"}
        and span.source_draft_id == source_ref.draft_id
        and span.source_content_hash == source_ref.source_hash
        and span.start_offset is not None
        and span.end_offset is not None
        and span.start_offset < source_ref.end_offset
        and span.end_offset > source_ref.start_offset
    ]
    parents = []
    if matching:
        for scene_id in dict.fromkeys(span.scene_id for span in matching):
            for span in await get_scene_spans_for_scene(
                db,
                novel_id,
                scene_id,
                content_mode=source_ref.content_mode,
            ):
                if (
                    span.mapping_status not in {"exact", "reanchored"}
                    or span.start_offset is None
                    or span.end_offset is None
                ):
                    omissions.append("scene_mapping_unresolved")
                    continue
                parents.append(
                    (
                        span.chapter_index,
                        str(span.source_draft_id),
                        span.source_content_hash,
                        span.start_offset,
                        span.end_offset,
                    )
                )
    else:
        draft = await get_draft(db, novel_id, source_ref.draft_id)
        if draft is None or draft.content_hash != source_ref.source_hash:
            raise ValidationError("父级原文来源已变化，请重新查找证据")
        text = draft.content or ""
        left = text.rfind("\n", 0, source_ref.start_offset) + 1
        right = text.find("\n", source_ref.end_offset)
        parents.append(
            (
                source_ref.chapter_index,
                source_ref.draft_id,
                source_ref.source_hash,
                left,
                len(text) if right < 0 else right,
            )
        )

    used = 0
    # Original chapter first, then neighboring chapters; deterministic and bounded.
    parents = sorted(set(parents), key=lambda p: (p[0] != source_ref.chapter_index, p))
    for chapter, draft_id, source_hash, start, end in parents:
        if manifest.get(draft_id) != source_hash:
            omissions.append("source_outside_manifest_or_stale")
            continue
        if visibility.cutoff_chapter is not None and chapter > visibility.cutoff_chapter:
            omissions.append("visibility_cutoff")
            continue
        original_end = end
        if chapter == visibility.cutoff_chapter and visibility.cutoff_offset is not None:
            end = min(end, visibility.cutoff_offset)
        allowed = (
            None
            if allowed_ranges is None
            else [
                (ref["start_offset"], ref["end_offset"])
                for ref in allowed_ranges
                if ref.get("draft_id") == draft_id
                and ref.get("source_hash") == source_hash
                and ref.get("content_mode") == source_ref.content_mode
            ]
        )
        excluded = [
            (ref["start_offset"], ref["end_offset"])
            for ref in excluded_ranges
            if ref.get("draft_id") == draft_id
        ]
        ranges = bounded_ranges(start, end, allowed=allowed, excluded=excluded)
        if ranges != [(start, original_end)]:
            omissions.append("scope_clipped")
        for left, right in ranges:
            remaining = max_characters - used
            if remaining <= 0:
                omissions.append("character_budget")
                break
            if right - left > remaining:
                right = left + remaining
                omissions.append("character_budget")
            try:
                ref = await build_manuscript_range_ref(
                    db,
                    novel_id,
                    draft_id=draft_id,
                    start_offset=left,
                    end_offset=right,
                    content_mode=source_ref.content_mode,
                )
                if ref.source_hash != source_hash:
                    raise ValidationError("parent source changed during read")
                read = await reader.read(
                    db,
                    novel_id=novel_id,
                    source_ref=ref,
                    visibility=visibility,
                    before=0,
                    after=0,
                )
            except (NotFoundError, ValidationError, ValueError):
                omissions.append("parent_source_unavailable")
                continue
            used += len(read["text"])
            result["segments"].append(
                {
                    "source_ref": asdict(ref),
                    "text": read["text"],
                    "title": read.get("title"),
                }
            )
    result["omissions"] = list(dict.fromkeys(omissions))
    result["complete"] = not omissions
    return result
