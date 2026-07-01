"""Idempotent formal Scene writes for resilient deep import candidates."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from modules.imports.scene_fusion import FinalSceneCandidate
from modules.outline import facade as outline_facade


class SceneCommitResult(BaseModel):
    """Summary of formal Scene writes performed by one commit call."""

    created_count: int = 0
    skipped_count: int = 0
    conflict_count: int = 0
    created_scene_ids: list[str] = Field(default_factory=list)
    skipped_provenance_keys: list[str] = Field(default_factory=list)
    conflict_provenance_keys: list[str] = Field(default_factory=list)


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
    ) -> SceneCommitResult:
        result = SceneCommitResult()
        for candidate in candidates:
            provenance_key = build_scene_provenance_key(
                workflow_id,
                candidate.source_candidate_ids,
                candidate.operation,
                candidate.source_chapter_indices,
                candidate.candidate_id,
            )
            existing_scenes = await outline_facade.get_scenes_by_provenance_key(
                db,
                novel_id,
                provenance_key,
            )
            active_existing = [
                scene
                for scene in existing_scenes
                if scene.get("status") != "deprecated"
            ]
            if active_existing:
                result.skipped_count += 1
                result.skipped_provenance_keys.append(provenance_key)
                continue
            if existing_scenes:
                result.conflict_count += 1
                result.conflict_provenance_keys.append(provenance_key)
                continue

            scene_index = await outline_facade.get_next_scene_index(db, novel_id)
            created = await outline_facade.create_scene(
                db,
                novel_id,
                _build_scene_data(
                    candidate,
                    workflow_id=workflow_id,
                    provenance_key=provenance_key,
                    scene_index=scene_index,
                ),
            )
            result.created_count += 1
            result.created_scene_ids.append(created["id"])
        return result


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
        "narrative_tag": candidate.narrative_tag,
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


def _build_structure_meta(
    candidate: FinalSceneCandidate,
    *,
    workflow_id: str,
    provenance_key: str,
) -> dict[str, Any]:
    return {
        "auto_ingested": True,
        "workflow_id": workflow_id,
        "phase": candidate.phase or "phase1b_fusion",
        "source_candidate_ids": list(candidate.source_candidate_ids),
        "source_rounds": list(candidate.source_rounds),
        "source_chapter_indices": list(candidate.source_chapter_indices),
        "fusion_operation": candidate.operation,
        "confidence": candidate.confidence,
        "degraded_reason": getattr(candidate, "degraded_reason", None),
        "boundary_status": candidate.boundary_status,
        "boundary_reason": candidate.boundary_reason,
        "needs_review": candidate.needs_review,
        "review_reason": candidate.review_reason,
        "provenance_key": provenance_key,
        "phase1a_fallback": (
            candidate.phase == "phase1a_fallback" or candidate.fallback_required
        ),
    }
