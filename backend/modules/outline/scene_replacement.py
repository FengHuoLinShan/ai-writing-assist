"""Transactional deep-import Scene replacement policy owned by outline."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections import defaultdict, deque
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.outline.models import Scene
from modules.outline.repositories import SceneFusionSuggestionRepository, SceneRepository
from modules.outline.schemas import SceneCreate, SceneUpdate
from shared.utils import parse_uuid

ACTIVE_STATUSES = ("candidate", "draft", "canonical")
EXACT_MAPPING_STATUSES = {"exact", "reanchored"}


def replacement_source_fingerprint(
    scenes: list[Scene],
    proposed_scene: dict[str, Any],
) -> str:
    payload = {
        "source_scenes": [_scene_fingerprint_payload(scene) for scene in scenes],
        "draft_scenes": proposed_scene.get("draft_scenes") or [],
    }
    return _hash_payload(payload)


def replacement_source_scene_fingerprint(scenes: list[Scene]) -> str:
    return _hash_payload([_scene_fingerprint_payload(scene) for scene in scenes])


class DeepImportSceneCommitService:
    """Replace unreviewed import Scenes while protecting author-owned assets."""

    def __init__(self) -> None:
        self.repo = SceneRepository()
        self.suggestion_repo = SceneFusionSuggestionRepository()

    async def commit(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        workflow_id: str,
        start_chapter: int,
        end_chapter: int,
        candidates: list[dict[str, Any]],
        fusion_suggestions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        nid = parse_uuid(novel_id, "novel_id")
        active = await self._lock_active_scenes(db, nid)
        scoped = [
            scene
            for scene in active
            if _scene_overlaps_chapter_range(scene, start_chapter, end_chapter)
        ]
        cleanable = [scene for scene in scoped if _is_cleanable(scene)]
        protected = [scene for scene in scoped if scene not in cleanable]

        protected_spans = {
            scene.id: await self.repo.get_scene_spans_for_scene(
                db,
                nid,
                scene.id,
                statuses=ACTIVE_STATUSES,
            )
            for scene in protected
        }
        components, candidate_evidence = _replacement_components(
            protected,
            protected_spans,
            candidates,
        )
        replacement_candidate_indexes = {
            candidate_index
            for _, candidate_indexes in components
            for candidate_index in candidate_indexes
        }

        now = datetime.now(UTC).isoformat()
        for scene in cleanable:
            meta = {
                **dict(scene.structure_meta or {}),
                "previous_status": scene.status,
                "deprecated_reason": "scene_reextraction",
                "deprecated_at": now,
                "deprecated_by_workflow_id": workflow_id,
            }
            await self.repo.update(
                db,
                scene.id,
                SceneUpdate(status="deprecated", structure_meta=meta),
            )

        result: dict[str, Any] = {
            "created_count": 0,
            "skipped_count": 0,
            "conflict_count": 0,
            "adopted_count": 0,
            "review_count": 0,
            "replacement_suggestion_count": 0,
            "created_scene_ids": [],
            "skipped_provenance_keys": [],
            "conflict_provenance_keys": [],
            "scene_ids_by_candidate_id": {},
            "suggestion_ids": [],
            "effective_scene_ids": [],
            "effective_scene_count": 0,
            "effective_coverage": {},
            "active_scene_changed": bool(cleanable),
        }

        provenance_keys = [str(item.get("provenance_key") or "") for item in candidates]
        existing = await self.repo.get_by_provenance_keys(db, nid, provenance_keys)
        existing_by_key: dict[str, list[Scene]] = defaultdict(list)
        for scene in existing:
            key = str((scene.structure_meta or {}).get("provenance_key"))
            existing_by_key[key].append(scene)

        next_index = max((scene.scene_index for scene in active), default=-1) + 1
        for index, candidate in enumerate(candidates):
            if index in replacement_candidate_indexes:
                continue
            key = str(candidate.get("provenance_key") or "")
            same_key = existing_by_key.get(key, [])
            active_existing = [
                scene for scene in same_key if scene.status != "deprecated"
            ]
            if active_existing:
                scene = active_existing[0]
                result["skipped_count"] += 1
                result["skipped_provenance_keys"].append(key)
                result["scene_ids_by_candidate_id"][candidate["candidate_id"]] = str(
                    scene.id
                )
                if bool((scene.structure_meta or {}).get("needs_review")):
                    result["review_count"] += 1
                else:
                    result["adopted_count"] += 1
                continue
            if same_key:
                result["conflict_count"] += 1
                result["conflict_provenance_keys"].append(key)
                continue
            scene_data = dict(candidate["scene_data"])
            scene_data["scene_index"] = next_index
            created = await self.repo.create(db, nid, SceneCreate(**scene_data))
            next_index += 1
            result["created_count"] += 1
            result["active_scene_changed"] = True
            result["created_scene_ids"].append(str(created.id))
            result["scene_ids_by_candidate_id"][candidate["candidate_id"]] = str(
                created.id
            )
            if bool((created.structure_meta or {}).get("needs_review")):
                result["review_count"] += 1
            else:
                result["adopted_count"] += 1

        for protected_indexes, candidate_indexes in components:
            source_scenes = [protected[index] for index in protected_indexes]
            draft_scenes = [
                dict(candidates[index]["scene_data"]) for index in candidate_indexes
            ]
            for draft in draft_scenes:
                draft.pop("scene_index", None)
                draft.pop("status", None)
            overlap_evidence = [
                evidence
                for candidate_index in candidate_indexes
                for evidence in candidate_evidence[candidate_index]
                if evidence["source_scene_id"]
                in {str(scene.id) for scene in source_scenes}
            ]
            proposed_scene = {
                "draft_scenes": draft_scenes,
                "overlap_evidence": overlap_evidence,
                "source_scenes": [
                    {
                        "id": str(scene.id),
                        "title": scene.title,
                        "status": scene.status,
                        "source": scene.source,
                        "chapter_ids": list(scene.chapter_ids or []),
                        "goal": scene.goal,
                        "core_conflict": scene.core_conflict,
                    }
                    for scene in source_scenes
                ],
                "source_scene_fingerprint": replacement_source_scene_fingerprint(
                    source_scenes
                ),
            }
            source_fingerprint = replacement_source_fingerprint(
                source_scenes,
                proposed_scene,
            )
            candidate_keys = sorted(
                str(candidates[index].get("provenance_key") or "")
                for index in candidate_indexes
            )
            suggestion_key = _hash_payload(
                {
                    "kind": "replacement",
                    "source_scene_ids": sorted(str(scene.id) for scene in source_scenes),
                    "candidate_provenance_keys": candidate_keys,
                    "source_fingerprint": source_fingerprint,
                }
            )
            stored = await self.suggestion_repo.upsert_pending(
                db,
                novel_id=nid,
                source_workflow_id=workflow_id,
                suggestion_key=suggestion_key,
                source_fingerprint=source_fingerprint,
                payload={
                    "suggestion_kind": "replacement",
                    "proposed_action": "replace",
                    "source_scene_ids": [str(scene.id) for scene in source_scenes],
                    "chapter_span": sorted(
                        {
                            int(chapter)
                            for draft in draft_scenes
                            for chapter in draft.get("chapter_ids") or []
                        }
                    ),
                    "proposed_scene": proposed_scene,
                    "scan_trace": overlap_evidence,
                    "reason": "New extraction overlaps protected active Scenes.",
                },
            )
            result["suggestion_ids"].append(str(stored.id))
            result["replacement_suggestion_count"] += 1
            result["review_count"] += len(candidate_indexes)

        await self._persist_fusion_suggestions(
            db,
            nid=nid,
            workflow_id=workflow_id,
            suggestions=fusion_suggestions,
            scene_ids_by_candidate_id=result["scene_ids_by_candidate_id"],
            result=result,
        )

        effective = await self.repo.get_by_chapter_range(
            db,
            nid,
            start_chapter,
            end_chapter,
            statuses=ACTIVE_STATUSES,
        )
        covered = sorted(
            {
                chapter
                for scene in effective
                for chapter in _scene_chapter_indices(scene)
                if start_chapter <= chapter <= end_chapter
            }
        )
        missing = [
            chapter
            for chapter in range(start_chapter, end_chapter + 1)
            if chapter not in set(covered)
        ]
        result["effective_scene_ids"] = [str(scene.id) for scene in effective]
        result["effective_scene_count"] = len(effective)
        result["effective_coverage"] = {
            "start_chapter": start_chapter,
            "end_chapter": end_chapter,
            "covered_chapters": covered,
            "missing_chapters": missing,
            "coverage_complete": not missing,
        }
        return result

    async def _lock_active_scenes(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
    ) -> list[Scene]:
        stmt = (
            select(Scene)
            .where(Scene.novel_id == novel_id, Scene.status.in_(ACTIVE_STATUSES))
            .order_by(Scene.scene_index, Scene.id)
            .with_for_update()
        )
        return list((await db.execute(stmt)).scalars().all())

    async def _persist_fusion_suggestions(
        self,
        db: AsyncSession,
        *,
        nid: uuid.UUID,
        workflow_id: str,
        suggestions: list[dict[str, Any]],
        scene_ids_by_candidate_id: dict[str, str],
        result: dict[str, Any],
    ) -> None:
        from modules.outline.scene_workbench import SceneWorkbenchService

        payloads: list[dict[str, Any]] = []
        for raw in suggestions:
            payload = dict(raw)
            source_ids = [
                scene_ids_by_candidate_id.get(str(candidate_id))
                for candidate_id in payload.pop("source_candidate_ids", [])
            ]
            if len(source_ids) < 2 or any(scene_id is None for scene_id in source_ids):
                continue
            payload["source_scene_ids"] = source_ids
            payloads.append(payload)
        if not payloads:
            return
        ids = await SceneWorkbenchService().persist_fusion_suggestions(
            db,
            novel_id=str(nid),
            source_workflow_id=workflow_id,
            suggestions=payloads,
        )
        result["suggestion_ids"].extend(ids)


def _is_cleanable(scene: Scene) -> bool:
    meta = dict(scene.structure_meta or {})
    owned = scene.source == "deep_import" and bool(
        meta.get("workflow_id") or meta.get("auto_ingested") is True
    )
    return (
        owned
        and scene.status in {"candidate", "draft"}
        and meta.get("user_edited") is not True
    )


def _scene_overlaps_chapter_range(scene: Scene, start: int, end: int) -> bool:
    return any(start <= chapter <= end for chapter in _scene_chapter_indices(scene))


def _scene_chapter_indices(scene: Scene) -> list[int]:
    values = list(scene.chapter_ids or [])
    values.extend(
        chunk.get("chapter_index")
        for chunk in scene.scene_chunks or []
        if isinstance(chunk, dict)
    )
    indices: set[int] = set()
    for value in values:
        try:
            indices.add(int(value))
        except (TypeError, ValueError):
            continue
    return sorted(indices)


def _replacement_components(
    protected: list[Scene],
    protected_spans: dict[uuid.UUID, list[Any]],
    candidates: list[dict[str, Any]],
) -> tuple[list[tuple[list[int], list[int]]], dict[int, list[dict[str, Any]]]]:
    old_to_candidates: dict[int, set[int]] = defaultdict(set)
    candidate_to_old: dict[int, set[int]] = defaultdict(set)
    evidence_by_candidate: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for old_index, scene in enumerate(protected):
        for candidate_index, candidate in enumerate(candidates):
            evidence = _overlap_evidence(
                scene,
                protected_spans.get(scene.id, []),
                candidate["scene_data"],
            )
            if not evidence:
                continue
            old_to_candidates[old_index].add(candidate_index)
            candidate_to_old[candidate_index].add(old_index)
            evidence_by_candidate[candidate_index].extend(evidence)

    components: list[tuple[list[int], list[int]]] = []
    seen_old: set[int] = set()
    seen_candidates: set[int] = set()
    for seed in sorted(candidate_to_old):
        if seed in seen_candidates:
            continue
        queue: deque[tuple[str, int]] = deque([("candidate", seed)])
        old_component: set[int] = set()
        candidate_component: set[int] = set()
        while queue:
            kind, index = queue.popleft()
            if kind == "candidate":
                if index in seen_candidates:
                    continue
                seen_candidates.add(index)
                candidate_component.add(index)
                queue.extend(("old", old) for old in candidate_to_old[index])
            else:
                if index in seen_old:
                    continue
                seen_old.add(index)
                old_component.add(index)
                queue.extend(
                    ("candidate", candidate)
                    for candidate in old_to_candidates[index]
                )
        components.append((sorted(old_component), sorted(candidate_component)))
    return components, evidence_by_candidate


def _overlap_evidence(
    scene: Scene,
    spans: list[Any],
    candidate: dict[str, Any],
) -> list[dict[str, Any]]:
    old_by_chapter: dict[int, list[Any]] = defaultdict(list)
    for span in spans:
        old_by_chapter[int(span.chapter_index)].append(span)
    candidate_by_chapter: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for chunk in candidate.get("scene_chunks") or []:
        if not isinstance(chunk, dict) or chunk.get("chapter_index") is None:
            continue
        candidate_by_chapter[int(chunk["chapter_index"])].append(chunk)
    common = sorted(set(_scene_chapter_indices(scene)) & set(candidate_by_chapter))
    evidence: list[dict[str, Any]] = []
    for chapter in common:
        old_parts = old_by_chapter.get(chapter, [])
        new_parts = candidate_by_chapter[chapter]
        exact_comparison = bool(old_parts) and all(
            part.mapping_status in EXACT_MAPPING_STATUSES
            and part.source_content_hash
            and part.start_offset is not None
            and part.end_offset is not None
            for part in old_parts
        ) and all(
            part.get("source_content_hash")
            and part.get("start_offset") is not None
            and part.get("end_offset") is not None
            for part in new_parts
        )
        if exact_comparison:
            matching_hash = all(
                old.source_content_hash == new.get("source_content_hash")
                for old in old_parts
                for new in new_parts
            )
            intersects = matching_hash and any(
                max(int(old.start_offset), int(new["start_offset"]))
                < min(int(old.end_offset), int(new["end_offset"]))
                for old in old_parts
                for new in new_parts
            )
            if not intersects and matching_hash:
                continue
            mode = "exact_offset" if intersects else "conservative_hash_mismatch"
        else:
            mode = "conservative_chapter"
        evidence.append(
            {
                "source_scene_id": str(scene.id),
                "chapter_index": chapter,
                "mode": mode,
            }
        )
    return evidence


def _scene_fingerprint_payload(scene: Scene) -> dict[str, Any]:
    return {
        "id": str(scene.id),
        "status": scene.status,
        "title": scene.title,
        "goal": scene.goal,
        "core_conflict": scene.core_conflict,
        "emotional_beat": scene.emotional_beat,
        "must_happen": scene.must_happen,
        "must_not_happen": scene.must_not_happen,
        "narrative_tag": scene.narrative_tag,
        "chapter_ids": list(scene.chapter_ids or []),
        "scene_chunks": list(scene.scene_chunks or []),
        "updated_at": scene.updated_at.isoformat() if scene.updated_at else None,
    }


def _hash_payload(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
