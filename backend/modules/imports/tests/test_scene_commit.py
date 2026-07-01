"""Scene commit provenance and idempotency behavior."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.imports.llm_schemas import SceneChunk
from modules.imports.scene_fusion import FinalSceneCandidate
from modules.outline.repositories import SceneRepository
from modules.outline.schemas import SceneCreate


def make_final_scene_candidate(
    *,
    candidate_id: str = "",
    source_candidate_ids: list[str] | None = None,
    source_rounds: list[str] | None = None,
    source_chapter_indices: list[int] | None = None,
    fusion_operation: str = "merged",
    phase: str = "phase1b_fusion",
    fallback_required: bool = False,
    needs_review: bool = True,
) -> FinalSceneCandidate:
    chapters = source_chapter_indices or [1, 2]
    return FinalSceneCandidate(
        candidate_id=candidate_id,
        phase=phase,
        title="Fused opening",
        goal="Commit the fused scene",
        core_conflict="Two observations describe one scene",
        emotional_beat="uncertain",
        narrative_tag="imported",
        scene_chunks=[SceneChunk(chapter_index=chapters[0], start_paragraph=0)],
        source_candidate_ids=source_candidate_ids or ["a", "b"],
        source_rounds=source_rounds or ["A", "B"],
        source_chapter_indices=chapters,
        operation=fusion_operation,
        confidence=0.86,
        fallback_required=fallback_required,
        boundary_status="uncertain",
        boundary_reason="Phase 1b kept a soft boundary.",
        needs_review=needs_review,
        review_reason="Boundary should be checked.",
    )


async def count_scenes_by_novel(db: AsyncSession, novel_id: str) -> int:
    from modules.outline.facade import get_scenes_by_novel

    return len(await get_scenes_by_novel(db, novel_id))


@pytest.mark.asyncio
async def test_scene_commit_writes_provenance_and_skips_existing_key(
    db_session: AsyncSession,
    sample_novel_id: str,
) -> None:
    from modules.imports.scene_commit import SceneCommitter

    candidate = make_final_scene_candidate(
        source_candidate_ids=["a", "b"],
        source_chapter_indices=[1, 2],
        fusion_operation="merged",
    )

    first = await SceneCommitter().commit(
        db_session,
        sample_novel_id,
        [candidate],
        workflow_id="wf-1",
    )
    second = await SceneCommitter().commit(
        db_session,
        sample_novel_id,
        [candidate],
        workflow_id="wf-1",
    )

    assert first.created_count == 1
    assert first.created_scene_ids
    assert second.skipped_count == 1
    assert second.skipped_provenance_keys
    assert await count_scenes_by_novel(db_session, sample_novel_id) == 1


def test_provenance_key_normalizes_source_order() -> None:
    from modules.imports.scene_commit import build_scene_provenance_key

    first = build_scene_provenance_key(
        "wf-1",
        ["b", "a"],
        "merged",
        [2, 1],
    )
    second = build_scene_provenance_key(
        "wf-1",
        ["a", "b"],
        "merged",
        [1, 2],
    )

    assert first == second


@pytest.mark.asyncio
async def test_scene_commit_writes_complete_structure_meta(
    db_session: AsyncSession,
    sample_novel_id: str,
) -> None:
    from modules.imports.scene_commit import SceneCommitter, build_scene_provenance_key
    from modules.outline.facade import get_scene

    candidate = make_final_scene_candidate(fallback_required=True)

    result = await SceneCommitter().commit(
        db_session,
        sample_novel_id,
        [candidate],
        workflow_id="wf-meta",
    )

    scene = await get_scene(db_session, result.created_scene_ids[0])
    assert scene is not None
    assert scene["source"] == "deep_import"
    assert scene["status"] == "draft"
    assert scene["scene_index"] == 0

    provenance_key = build_scene_provenance_key(
        "wf-meta",
        candidate.source_candidate_ids,
        candidate.operation,
        candidate.source_chapter_indices,
        candidate.candidate_id,
    )
    assert scene["structure_meta"] == {
        "auto_ingested": True,
        "workflow_id": "wf-meta",
        "phase": "phase1b_fusion",
        "source_candidate_ids": ["a", "b"],
        "source_rounds": ["A", "B"],
        "source_chapter_indices": [1, 2],
        "fusion_operation": "merged",
        "confidence": 0.86,
        "degraded_reason": None,
        "boundary_status": "uncertain",
        "boundary_reason": "Phase 1b kept a soft boundary.",
        "needs_review": True,
        "review_reason": "Boundary should be checked.",
        "provenance_key": provenance_key,
        "phase1a_fallback": True,
    }


@pytest.mark.asyncio
async def test_deprecated_same_key_conflicts_without_revival_or_create(
    db_session: AsyncSession,
    sample_novel_id: str,
) -> None:
    from modules.imports.scene_commit import SceneCommitter, build_scene_provenance_key

    candidate = make_final_scene_candidate()
    provenance_key = build_scene_provenance_key(
        "wf-conflict",
        candidate.source_candidate_ids,
        candidate.operation,
        candidate.source_chapter_indices,
        candidate.candidate_id,
    )
    await SceneRepository().create(
        db_session,
        uuid.UUID(sample_novel_id),
        SceneCreate(
            scene_index=0,
            title="Deprecated imported scene",
            source="deep_import",
            status="deprecated",
            structure_meta={"provenance_key": provenance_key},
        ),
    )
    await db_session.flush()

    result = await SceneCommitter().commit(
        db_session,
        sample_novel_id,
        [candidate],
        workflow_id="wf-conflict",
    )

    assert result.created_count == 0
    assert result.skipped_count == 0
    assert result.conflict_count == 1
    assert result.conflict_provenance_keys == [provenance_key]
    assert await count_scenes_by_novel(db_session, sample_novel_id) == 0


@pytest.mark.asyncio
async def test_scene_commit_idempotency_is_scoped_by_novel_id(
    db_session: AsyncSession,
    sample_novel_id: str,
) -> None:
    from modules.imports.scene_commit import SceneCommitter

    other_novel_id = str(uuid.uuid4())
    candidate = make_final_scene_candidate()
    committer = SceneCommitter()

    other_result = await committer.commit(
        db_session,
        other_novel_id,
        [candidate],
        workflow_id="wf-shared",
    )
    current_result = await committer.commit(
        db_session,
        sample_novel_id,
        [candidate],
        workflow_id="wf-shared",
    )

    assert other_result.created_count == 1
    assert current_result.created_count == 1
    assert current_result.skipped_count == 0
    assert await count_scenes_by_novel(db_session, other_novel_id) == 1
    assert await count_scenes_by_novel(db_session, sample_novel_id) == 1


@pytest.mark.asyncio
async def test_scene_commit_allows_same_source_split_scenes_by_candidate_id(
    db_session: AsyncSession,
    sample_novel_id: str,
) -> None:
    from modules.imports.scene_commit import SceneCommitter

    first = make_final_scene_candidate(
        candidate_id="phase1a-fallback-a-1",
        source_candidate_ids=["a"],
        source_chapter_indices=[1],
    )
    second = make_final_scene_candidate(
        candidate_id="phase1a-fallback-a-2",
        source_candidate_ids=["a"],
        source_chapter_indices=[1],
    )

    result = await SceneCommitter().commit(
        db_session,
        sample_novel_id,
        [first, second],
        workflow_id="wf-split",
    )

    assert result.created_count == 2
    assert result.skipped_count == 0
    assert await count_scenes_by_novel(db_session, sample_novel_id) == 2
