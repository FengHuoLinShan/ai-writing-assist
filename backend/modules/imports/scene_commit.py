"""Idempotent formal Scene writes for resilient deep import candidates."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from modules.imports.scene_fusion import FinalSceneCandidate
from modules.story import facade as outline_facade
from modules.writing import facade as writing_facade

MAX_NARRATIVE_TAG_LENGTH = 32


class SceneCommitResult(BaseModel):
    """Summary of formal Scene writes performed by one commit call."""

    created_count: int = 0
    skipped_count: int = 0
    conflict_count: int = 0
    adopted_count: int = 0
    review_count: int = 0
    created_scene_ids: list[str] = Field(default_factory=list)
    skipped_provenance_keys: list[str] = Field(default_factory=list)
    conflict_provenance_keys: list[str] = Field(default_factory=list)
    scene_ids_by_candidate_id: dict[str, str] = Field(default_factory=dict)
    suggestion_ids: list[str] = Field(default_factory=list)
    replacement_suggestion_count: int = 0
    effective_scene_ids: list[str] = Field(default_factory=list)
    effective_scene_count: int = 0
    effective_coverage: dict[str, Any] = Field(default_factory=dict)
    active_scene_changed: bool = False


def build_scene_provenance_key(
    workflow_id: str,
    source_candidate_ids: Sequence[str],
    fusion_operation: str,
    source_chapter_indices: Sequence[int],
    candidate_id: str = "",
) -> str:
    """Build a stable key for one reducer output regardless of source ordering."""

    raw = {
        "workflow_id": workflow_id,
        "candidate_id": candidate_id,
        "source_candidate_ids": sorted(
            str(source_id) for source_id in source_candidate_ids
        ),
        "fusion_operation": fusion_operation,
        "source_chapter_indices": sorted(int(index) for index in source_chapter_indices),
    }
    payload = json.dumps(raw, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class SceneCommitter:
    """Commit post-reducer candidates as formal Scene rows through outline facade."""

    async def commit(
        self,
        db: AsyncSession,
        novel_id: str,
        candidates: Sequence[FinalSceneCandidate],
        workflow_id: str,
        fusion_suggestions: Sequence[Any] = (),
        start_chapter: int | None = None,
        end_chapter: int | None = None,
        replace_existing: bool = False,
    ) -> SceneCommitResult:
        _assert_non_overlapping_exact_spans(candidates)
        if not replace_existing and start_chapter is not None and end_chapter is not None:
            await _assert_complete_frozen_source_coverage(
                db,
                novel_id=novel_id,
                candidates=candidates,
                start_chapter=start_chapter,
                end_chapter=end_chapter,
            )
        if replace_existing:
            chapter_indices = sorted(
                {
                    int(chapter)
                    for candidate in candidates
                    for chapter in candidate.source_chapter_indices
                }
            )
            effective_start = start_chapter or (
                chapter_indices[0] if chapter_indices else 1
            )
            effective_end = end_chapter or (
                chapter_indices[-1] if chapter_indices else effective_start
            )
            replacement_candidates = []
            for candidate in candidates:
                provenance_key = build_scene_provenance_key(
                    workflow_id,
                    candidate.source_candidate_ids,
                    candidate.operation,
                    candidate.source_chapter_indices,
                    candidate.candidate_id,
                )
                replacement_candidates.append(
                    {
                        "candidate_id": candidate.candidate_id,
                        "provenance_key": provenance_key,
                        "scene_data": _build_scene_data(
                            candidate,
                            workflow_id=workflow_id,
                            provenance_key=provenance_key,
                            scene_index=0,
                        ),
                    }
                )
            raw_suggestions = [
                item.model_dump(mode="json")
                if hasattr(item, "model_dump")
                else dict(item)
                for item in fusion_suggestions
            ]
            committed = await outline_facade.commit_deep_import_scene_candidates(
                db,
                novel_id=novel_id,
                workflow_id=workflow_id,
                start_chapter=effective_start,
                end_chapter=effective_end,
                candidates=replacement_candidates,
                fusion_suggestions=raw_suggestions,
            )
            if any(
                chunk.source_draft_id and chunk.source_content_hash
                for candidate in candidates
                for chunk in candidate.scene_chunks
            ):
                await _assert_complete_active_source_coverage(
                    db,
                    novel_id=novel_id,
                    start_chapter=effective_start,
                    end_chapter=effective_end,
                )
            return SceneCommitResult.model_validate(committed)

        result = SceneCommitResult()
        next_scene_index: int | None = None
        keyed_candidates = [
            (
                candidate,
                build_scene_provenance_key(
                    workflow_id,
                    candidate.source_candidate_ids,
                    candidate.operation,
                    candidate.source_chapter_indices,
                    candidate.candidate_id,
                ),
            )
            for candidate in candidates
        ]
        if not keyed_candidates:
            return result
        existing_by_key = await outline_facade.get_scenes_by_provenance_keys(
            db,
            novel_id,
            [provenance_key for _, provenance_key in keyed_candidates],
        )
        for candidate, provenance_key in keyed_candidates:
            existing_scenes = existing_by_key.get(provenance_key, [])
            active_existing = [
                scene for scene in existing_scenes if scene.get("status") != "deprecated"
            ]
            if active_existing:
                result.skipped_count += 1
                result.skipped_provenance_keys.append(provenance_key)
                if any(
                    bool((scene.get("structure_meta") or {}).get("needs_review"))
                    for scene in active_existing
                ):
                    result.review_count += 1
                else:
                    result.adopted_count += 1
                result.scene_ids_by_candidate_id[candidate.candidate_id] = str(
                    active_existing[0]["id"]
                )
                continue
            if existing_scenes:
                result.conflict_count += 1
                result.conflict_provenance_keys.append(provenance_key)
                continue

            if next_scene_index is None:
                next_scene_index = await outline_facade.get_next_scene_index(
                    db,
                    novel_id,
                )
            created = await outline_facade.create_scene(
                db,
                novel_id,
                _build_scene_data(
                    candidate,
                    workflow_id=workflow_id,
                    provenance_key=provenance_key,
                    scene_index=next_scene_index,
                ),
            )
            next_scene_index += 1
            result.created_count += 1
            if candidate.needs_review:
                result.review_count += 1
            else:
                result.adopted_count += 1
            result.created_scene_ids.append(created["id"])
            result.scene_ids_by_candidate_id[candidate.candidate_id] = created["id"]
            existing_by_key.setdefault(provenance_key, []).append(created)
        suggestion_payloads: list[dict[str, Any]] = []
        for suggestion in fusion_suggestions:
            payload = (
                suggestion.model_dump(mode="json")
                if hasattr(suggestion, "model_dump")
                else dict(suggestion)
            )
            source_scene_ids = [
                result.scene_ids_by_candidate_id.get(str(candidate_id))
                for candidate_id in payload.pop("source_candidate_ids", [])
            ]
            if any(scene_id is None for scene_id in source_scene_ids):
                continue
            payload["source_scene_ids"] = source_scene_ids
            suggestion_payloads.append(payload)
        if suggestion_payloads:
            result.suggestion_ids = (
                await outline_facade.persist_deep_import_fusion_suggestions(
                    db,
                    novel_id=novel_id,
                    source_workflow_id=workflow_id,
                    suggestions=suggestion_payloads,
                )
            )
        return result


def _assert_non_overlapping_exact_spans(
    candidates: Sequence[FinalSceneCandidate],
) -> None:
    """Fail closed before any write when exact source ownership overlaps."""

    occupied: dict[int, list[tuple[int, int, int, str]]] = {}
    for candidate_index, candidate in enumerate(candidates):
        for chunk in candidate.scene_chunks:
            if chunk.start_offset is None or chunk.end_offset is None:
                continue
            occupied.setdefault(chunk.chapter_index, []).append(
                (
                    int(chunk.start_offset),
                    int(chunk.end_offset),
                    candidate_index,
                    candidate.candidate_id,
                )
            )
    conflicts: list[str] = []
    for chapter_index, intervals in sorted(occupied.items()):
        ordered = sorted(intervals)
        for index, (start, end, owner_index, candidate_id) in enumerate(ordered):
            for other_start, other_end, other_owner_index, other_id in ordered[
                index + 1 :
            ]:
                if other_start >= end:
                    break
                if owner_index == other_owner_index or max(start, other_start) >= min(
                    end, other_end
                ):
                    continue
                conflicts.append(
                    "chapter="
                    f"{chapter_index},left={candidate_id or owner_index},"
                    f"right={other_id or other_owner_index}"
                )
    if conflicts:
        raise ValueError(
            "deep import Scene candidates contain overlapping exact source spans: "
            + ";".join(conflicts)
        )


async def _assert_complete_frozen_source_coverage(
    db: AsyncSession,
    *,
    novel_id: str,
    candidates: Sequence[FinalSceneCandidate],
    start_chapter: int,
    end_chapter: int,
) -> None:
    """Verify frozen draft hashes and exact, gap-free ownership before writes.

    Legacy callers that provide no frozen source metadata retain their historical
    behavior. Once a candidate set contains frozen deep-import spans, every chunk
    must be exact and source-bound, and the union must cover each referenced draft
    from offset zero through the final character.
    """

    chunks = [chunk for candidate in candidates for chunk in candidate.scene_chunks]
    frozen = [
        chunk for chunk in chunks if chunk.source_draft_id and chunk.source_content_hash
    ]
    if not frozen:
        return
    incomplete = [
        chunk
        for chunk in chunks
        if (
            chunk.start_offset is None
            or chunk.end_offset is None
            or not chunk.source_draft_id
            or not chunk.source_content_hash
        )
    ]
    if incomplete:
        raise ValueError(
            "deep import Scene candidates mix frozen exact spans with incomplete "
            "source mappings"
        )

    records = [
        (
            str(chunk.source_draft_id),
            int(chunk.start_offset),
            int(chunk.end_offset),
            int(chunk.chapter_index),
            str(chunk.source_content_hash),
        )
        for chunk in chunks
    ]
    await _assert_complete_frozen_intervals(
        db,
        novel_id=novel_id,
        records=records,
        start_chapter=start_chapter,
        end_chapter=end_chapter,
    )


async def _assert_complete_active_source_coverage(
    db: AsyncSession,
    *,
    novel_id: str,
    start_chapter: int,
    end_chapter: int,
) -> None:
    scenes = await outline_facade.get_scenes_by_novel(
        db,
        novel_id,
        status_filter=["candidate", "draft", "canonical"],
    )
    records: list[tuple[str, int, int, int, str]] = []
    for scene in scenes:
        for raw_chunk in scene.get("scene_chunks") or []:
            if not isinstance(raw_chunk, dict):
                continue
            chapter_index = int(raw_chunk.get("chapter_index") or 0)
            if not start_chapter <= chapter_index <= end_chapter:
                continue
            required = (
                raw_chunk.get("source_draft_id"),
                raw_chunk.get("start_offset"),
                raw_chunk.get("end_offset"),
                raw_chunk.get("source_content_hash"),
            )
            if any(value is None or value == "" for value in required):
                raise ValueError(
                    "active Scene coverage contains an incomplete frozen source mapping"
                )
            records.append(
                (
                    str(raw_chunk["source_draft_id"]),
                    int(raw_chunk["start_offset"]),
                    int(raw_chunk["end_offset"]),
                    chapter_index,
                    str(raw_chunk["source_content_hash"]),
                )
            )
    await _assert_complete_frozen_intervals(
        db,
        novel_id=novel_id,
        records=records,
        start_chapter=start_chapter,
        end_chapter=end_chapter,
    )


async def _assert_complete_frozen_intervals(
    db: AsyncSession,
    *,
    novel_id: str,
    records: Sequence[tuple[str, int, int, int, str]],
    start_chapter: int,
    end_chapter: int,
) -> None:
    by_draft: dict[str, list[tuple[int, int, int, str]]] = {}
    for draft_id, start, end, chapter_index, source_hash in records:
        by_draft.setdefault(draft_id, []).append((start, end, chapter_index, source_hash))

    problems: list[str] = []
    covered_chapters: set[int] = set()
    for draft_id, intervals in sorted(by_draft.items()):
        draft = await writing_facade.get_draft(db, novel_id, draft_id)
        if draft is None:
            problems.append(f"draft={draft_id}:missing_or_cross_novel")
            continue
        content = str(draft.content or "")
        expected_hash = str(draft.content_hash or "")
        covered_chapters.add(int(draft.chapter_index))
        cursor = 0
        chapter_indices: set[int] = set()
        for start, end, chapter_index, source_hash in sorted(intervals):
            chapter_indices.add(chapter_index)
            if source_hash != expected_hash:
                problems.append(f"draft={draft_id}:source_hash_drift")
                break
            if start != cursor:
                problems.append(f"draft={draft_id}:coverage_hole={cursor}-{start}")
                break
            if not 0 <= start < end <= len(content):
                problems.append(f"draft={draft_id}:invalid_span={start}-{end}")
                break
            cursor = end
        else:
            if len(chapter_indices) != 1 or next(iter(chapter_indices)) != int(
                draft.chapter_index
            ):
                problems.append(f"draft={draft_id}:chapter_mismatch")
            elif cursor != len(content):
                problems.append(f"draft={draft_id}:coverage_hole={cursor}-{len(content)}")
    expected_chapters = set(range(start_chapter, end_chapter + 1))
    if covered_chapters != expected_chapters:
        problems.append(
            "chapter_coverage_mismatch="
            f"expected:{sorted(expected_chapters)},actual:{sorted(covered_chapters)}"
        )
    if problems:
        raise ValueError(
            "deep import Scene candidates do not completely cover frozen sources: "
            + ";".join(problems)
        )


def _build_scene_data(
    candidate: FinalSceneCandidate,
    *,
    workflow_id: str,
    provenance_key: str,
    scene_index: int,
) -> dict[str, Any]:
    scene_chunks = [
        chunk.model_dump(mode="json") if hasattr(chunk, "model_dump") else dict(chunk)
        for chunk in candidate.scene_chunks
    ]
    source_chapter_indices = list(candidate.source_chapter_indices)
    return {
        "scene_index": scene_index,
        "title": candidate.title,
        "goal": candidate.goal,
        "core_conflict": candidate.core_conflict,
        "emotional_beat": candidate.emotional_beat,
        "must_happen": candidate.must_happen,
        "must_not_happen": candidate.must_not_happen,
        "narrative_tag": _safe_narrative_tag(candidate.narrative_tag),
        "source": "deep_import",
        "scene_chunks": scene_chunks,
        "chapter_ids": [str(index) for index in source_chapter_indices],
        "structure_meta": _build_structure_meta(
            candidate,
            workflow_id=workflow_id,
            provenance_key=provenance_key,
        ),
        "status": "draft",
    }


def _safe_narrative_tag(value: str | None) -> str:
    tag = " ".join(str(value or "").split()) or "draft"
    if tag == "imported":
        return "draft"
    return tag[:MAX_NARRATIVE_TAG_LENGTH]


def _build_structure_meta(
    candidate: FinalSceneCandidate,
    *,
    workflow_id: str,
    provenance_key: str,
) -> dict[str, Any]:
    boundary_reason = candidate.boundary_basis or candidate.boundary_reason
    boundary_workflow_reason = (
        candidate.boundary_reason
        if candidate.boundary_reason and candidate.boundary_reason != boundary_reason
        else None
    )
    semantic_statuses = dict(candidate.phase1b_field_statuses)
    semantic_statuses["core_conflict"] = candidate.core_conflict_status
    semantic_statuses["narrative_function"] = (
        "uncertain"
        if "narrative_function" in candidate.phase1b_uncertain_fields
        else "present"
        if candidate.narrative_function
        else "not_applicable"
    )
    semantic_uncertain_fields = list(
        dict.fromkeys(
            [
                *candidate.phase1b_uncertain_fields,
                *(
                    ["core_conflict"]
                    if candidate.core_conflict_status == "uncertain"
                    else []
                ),
            ]
        )
    )
    return {
        "auto_ingested": True,
        "workflow_id": workflow_id,
        "phase": candidate.phase or "phase1b_fusion",
        "source_candidate_ids": list(candidate.source_candidate_ids),
        "source_rounds": list(candidate.source_rounds),
        "source_chapter_indices": list(candidate.source_chapter_indices),
        "fusion_operation": candidate.operation,
        "confidence": candidate.confidence,
        "core_conflict_status": candidate.core_conflict_status,
        "phase1a_confidence": candidate.phase1a_confidence,
        "boundary_basis": candidate.boundary_basis,
        "phase1b_field_statuses": dict(candidate.phase1b_field_statuses),
        "phase1b_basis": candidate.phase1b_basis,
        "narrative_function": candidate.narrative_function,
        "phase1b_uncertain_fields": list(candidate.phase1b_uncertain_fields),
        "phase1b_confidence": candidate.phase1b_confidence,
        "phase1b_context_fingerprint": candidate.phase1b_context_fingerprint,
        "phase1b_source_fingerprint": candidate.phase1b_source_fingerprint,
        "semantic_field_statuses": semantic_statuses,
        "semantic_uncertain_fields": semantic_uncertain_fields,
        "semantic_basis": candidate.phase1b_basis,
        "semantic_confidence": candidate.phase1b_confidence,
        "semantic_contract_version": "scene-semantic-state-v2",
        "semantic_origin": (
            "phase1c_synthesis"
            if candidate.phase == "phase1c_fusion"
            else "phase1b_enrichment"
        ),
        "degraded_reason": getattr(candidate, "degraded_reason", None),
        "boundary_status": candidate.boundary_status,
        # Prompt contracts map Phase 1a boundary_basis to this durable field.
        # Keep a later reducer/fusion explanation separately instead of replacing
        # the source boundary judgment.
        "boundary_reason": boundary_reason,
        "boundary_workflow_reason": boundary_workflow_reason,
        "needs_review": candidate.needs_review,
        "review_reason": candidate.review_reason,
        "provenance_key": provenance_key,
        "phase1a_fallback": (
            candidate.phase == "phase1a_fallback" or candidate.fallback_required
        ),
    }
