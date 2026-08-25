"""Scene commit provenance and idempotency behavior."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.imports.llm_schemas import SceneChunk
from modules.imports.scene_fusion import FinalSceneCandidate
from modules.story.outline_state.repositories import SceneRepository
from modules.story.outline_state.schemas import SceneCreate, SceneUpdate


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
        core_conflict_status="present",
        phase1a_confidence=0.91,
        boundary_basis="The imported spans share one causal progression.",
        emotional_beat="uncertain",
        narrative_tag="draft",
        narrative_function="Preserve the imported causal progression.",
        phase1b_basis="The exact source spans support this reading.",
        phase1b_field_statuses={
            "emotional_beat": "present",
            "must_happen": "not_applicable",
            "must_not_happen": "not_applicable",
            "narrative_tag": "not_applicable",
            "narrative_function": "present",
        },
        phase1b_confidence=0.77,
        phase1b_context_fingerprint="c" * 64,
        phase1b_source_fingerprint="d" * 64,
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
    from modules.story.outline_state.facade import get_scenes_by_novel

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


@pytest.mark.asyncio
async def test_scene_commit_rejects_overlapping_exact_spans_before_writes(
    db_session: AsyncSession,
    sample_novel_id: str,
) -> None:
    from modules.imports.scene_commit import SceneCommitter

    first = make_final_scene_candidate(
        candidate_id="left",
        source_candidate_ids=["left"],
        source_chapter_indices=[1],
    )
    first.scene_chunks = [SceneChunk(chapter_index=1, start_offset=0, end_offset=20)]
    second = make_final_scene_candidate(
        candidate_id="right",
        source_candidate_ids=["right"],
        source_chapter_indices=[1],
    )
    second.scene_chunks = [SceneChunk(chapter_index=1, start_offset=12, end_offset=30)]

    with pytest.raises(ValueError, match="overlapping exact source spans"):
        await SceneCommitter().commit(
            db_session,
            sample_novel_id,
            [first, second],
            workflow_id="wf-overlap",
        )

    assert await count_scenes_by_novel(db_session, sample_novel_id) == 0


@pytest.mark.asyncio
async def test_scene_commit_rejects_gap_in_frozen_source_before_writes(
    db_session: AsyncSession,
    sample_novel_id: str,
) -> None:
    from modules.imports.scene_commit import SceneCommitter
    from modules.writing.facade import create_published_draft_only

    content = "甲" * 30
    draft = await create_published_draft_only(
        db_session,
        sample_novel_id,
        1,
        title="第一章",
        content=content,
    )
    first = make_final_scene_candidate(
        candidate_id="left",
        source_candidate_ids=["left"],
        source_chapter_indices=[1],
    )
    first.scene_chunks = [
        SceneChunk(
            chapter_index=1,
            start_offset=0,
            end_offset=10,
            source_draft_id=draft.id,
            source_content_hash=draft.content_hash,
        )
    ]
    second = make_final_scene_candidate(
        candidate_id="right",
        source_candidate_ids=["right"],
        source_chapter_indices=[1],
    )
    second.scene_chunks = [
        SceneChunk(
            chapter_index=1,
            start_offset=12,
            end_offset=len(content),
            source_draft_id=draft.id,
            source_content_hash=draft.content_hash,
        )
    ]

    with pytest.raises(ValueError, match="coverage_hole=10-12"):
        await SceneCommitter().commit(
            db_session,
            sample_novel_id,
            [first, second],
            workflow_id="wf-gap",
            start_chapter=1,
            end_chapter=1,
        )

    assert await count_scenes_by_novel(db_session, sample_novel_id) == 0


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
async def test_scene_commit_reuses_next_scene_index_for_batch(monkeypatch) -> None:
    from modules.imports.scene_commit import SceneCommitter
    from modules.story import facade as outline_facade

    single_provenance_calls = 0
    batch_provenance_calls = 0
    next_index_calls = 0
    created_indices: list[int] = []

    async def fake_get_scenes_by_provenance_key(*_args: object) -> list[dict]:
        nonlocal single_provenance_calls
        single_provenance_calls += 1
        return []

    async def fake_get_scenes_by_provenance_keys(
        _db: object,
        _novel_id: str,
        provenance_keys: list[str],
    ) -> dict[str, list[dict]]:
        nonlocal batch_provenance_calls
        batch_provenance_calls += 1
        return {key: [] for key in provenance_keys}

    async def fake_get_next_scene_index(*_args: object) -> int:
        nonlocal next_index_calls
        next_index_calls += 1
        return 5

    async def fake_create_scene(
        _db: object,
        _novel_id: str,
        data: dict,
    ) -> dict[str, str]:
        created_indices.append(data["scene_index"])
        return {"id": str(uuid.uuid4())}

    monkeypatch.setattr(
        outline_facade,
        "get_scenes_by_provenance_key",
        fake_get_scenes_by_provenance_key,
    )
    monkeypatch.setattr(
        outline_facade,
        "get_scenes_by_provenance_keys",
        fake_get_scenes_by_provenance_keys,
        raising=False,
    )
    monkeypatch.setattr(
        outline_facade,
        "get_next_scene_index",
        fake_get_next_scene_index,
    )
    monkeypatch.setattr(outline_facade, "create_scene", fake_create_scene)

    candidates = [
        make_final_scene_candidate(
            candidate_id=f"candidate-{index}",
            source_candidate_ids=[f"source-{index}"],
            source_chapter_indices=[index + 1],
        )
        for index in range(3)
    ]

    result = await SceneCommitter().commit(
        object(),  # type: ignore[arg-type]
        str(uuid.uuid4()),
        candidates,
        workflow_id="wf-batch-index",
    )

    assert result.created_count == 3
    assert result.review_count == 3
    assert result.adopted_count == 0
    assert single_provenance_calls == 0
    assert batch_provenance_calls == 1
    assert next_index_calls == 1
    assert created_indices == [5, 6, 7]


@pytest.mark.asyncio
async def test_scene_commit_writes_complete_structure_meta(
    db_session: AsyncSession,
    sample_novel_id: str,
) -> None:
    from modules.imports.scene_commit import SceneCommitter, build_scene_provenance_key
    from modules.story.outline_state.facade import get_scene

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
    assert scene["must_happen"] is None
    assert scene["must_not_happen"] is None

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
        "core_conflict_status": "present",
        "phase1a_confidence": 0.91,
        "boundary_basis": "The imported spans share one causal progression.",
        "phase1b_field_statuses": {
            "emotional_beat": "present",
            "must_happen": "not_applicable",
            "must_not_happen": "not_applicable",
            "narrative_tag": "not_applicable",
            "narrative_function": "present",
        },
        "phase1b_basis": "The exact source spans support this reading.",
        "narrative_function": "Preserve the imported causal progression.",
        "phase1b_uncertain_fields": [],
        "phase1b_confidence": 0.77,
        "phase1b_context_fingerprint": "c" * 64,
        "phase1b_source_fingerprint": "d" * 64,
        "semantic_field_statuses": {
            "emotional_beat": "present",
            "must_happen": "not_applicable",
            "must_not_happen": "not_applicable",
            "narrative_tag": "not_applicable",
            "narrative_function": "present",
            "core_conflict": "present",
        },
        "semantic_uncertain_fields": [],
        "semantic_basis": "The exact source spans support this reading.",
        "semantic_confidence": 0.77,
        "semantic_contract_version": "scene-semantic-state-v2",
        "semantic_origin": "phase1b_enrichment",
        "degraded_reason": None,
        "boundary_status": "uncertain",
        "boundary_reason": "The imported spans share one causal progression.",
        "boundary_workflow_reason": "Phase 1b kept a soft boundary.",
        "needs_review": True,
        "review_reason": "Boundary should be checked.",
        "provenance_key": provenance_key,
        "phase1a_fallback": True,
    }


def test_scene_commit_normalizes_legacy_imported_tag_to_draft() -> None:
    from modules.imports.scene_commit import _build_scene_data

    candidate = make_final_scene_candidate(source_chapter_indices=[1])
    candidate.narrative_tag = "imported"

    scene = _build_scene_data(
        candidate,
        workflow_id="wf-legacy-tag",
        provenance_key="legacy-tag-key",
        scene_index=0,
    )

    assert scene["narrative_tag"] == "draft"


@pytest.mark.asyncio
async def test_scene_commit_preserves_materialized_exact_source_span(
    db_session: AsyncSession,
    sample_novel_id: str,
) -> None:
    from modules.imports.scene_commit import SceneCommitter
    from modules.story.outline_state.facade import get_scene_spans_for_scene
    from modules.writing.facade import create_published_draft_only

    draft = await create_published_draft_only(
        db_session,
        sample_novel_id,
        1,
        title="第一章",
        content="正" * 100,
    )

    candidate = make_final_scene_candidate(source_chapter_indices=[1])
    candidate.scene_chunks = [
        SceneChunk(
            chapter_index=1,
            start_offset=12,
            end_offset=48,
            source_draft_id=draft.id,
            source_content_hash=draft.content_hash,
            anchor_hash="c" * 64,
            anchor_excerpt="唯一的正文起始锚点",
        )
    ]

    result = await SceneCommitter().commit(
        db_session,
        sample_novel_id,
        [candidate],
        workflow_id="wf-exact-span",
    )
    spans = await get_scene_spans_for_scene(
        db_session,
        sample_novel_id,
        result.created_scene_ids[0],
        content_mode="canonical",
    )

    assert len(spans) == 1
    assert spans[0].mapping_status == "exact"
    assert spans[0].start_offset == 12
    assert spans[0].end_offset == 48
    assert spans[0].source_draft_id == draft.id
    assert spans[0].source_content_hash == draft.content_hash
    assert spans[0].anchor_hash == "c" * 64


@pytest.mark.asyncio
async def test_scene_commit_truncates_long_narrative_tag(
    db_session: AsyncSession,
    sample_novel_id: str,
) -> None:
    from modules.imports.scene_commit import SceneCommitter
    from modules.story.outline_state.facade import get_scene

    candidate = make_final_scene_candidate()
    candidate.narrative_tag = "仪式与意外，灰雾与塔罗会相连，秘密组织雏形"

    result = await SceneCommitter().commit(
        db_session,
        sample_novel_id,
        [candidate],
        workflow_id="wf-long-tag",
    )

    scene = await get_scene(db_session, result.created_scene_ids[0])

    assert scene is not None
    assert scene["narrative_tag"] == candidate.narrative_tag[:32]
    assert len(scene["narrative_tag"]) <= 32


@pytest.mark.asyncio
async def test_scene_commit_creates_workbench_complete_setup(
    db_session: AsyncSession,
    sample_novel_id: str,
) -> None:
    from modules.imports.scene_commit import SceneCommitter
    from modules.story.outline_state.scene_workbench import SceneWorkbenchService

    candidate = make_final_scene_candidate(source_chapter_indices=[1])
    candidate.must_happen = "Commit the fused Scene."
    candidate.must_not_happen = "Do not contradict the imported source."
    candidate.phase1b_field_statuses["must_happen"] = "present"
    candidate.phase1b_field_statuses["must_not_happen"] = "present"
    result = await SceneCommitter().commit(
        db_session,
        sample_novel_id,
        [candidate],
        workflow_id="wf-workbench-health",
    )

    workbench = await SceneWorkbenchService().get_workbench(
        db_session,
        sample_novel_id,
    )
    item = next(
        entry
        for entry in workbench.items
        if entry.scene.id == result.created_scene_ids[0]
    )

    assert "missing_setup" not in item.health
    assert workbench.health["missing_setup"].count == 0


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
    repo = SceneRepository()
    legacy = await repo.create(
        db_session,
        uuid.UUID(sample_novel_id),
        SceneCreate(
            scene_index=0,
            title="Deprecated imported scene",
            source="deep_import",
            structure_meta={"provenance_key": provenance_key},
        ),
    )
    await repo.update(db_session, legacy.id, SceneUpdate(status="deprecated"))
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


@pytest.mark.asyncio
async def test_scene_commit_persists_phase1c_suggestions_with_formal_scene_ids(
    db_session: AsyncSession,
    sample_novel_id: str,
) -> None:
    from modules.imports.scene_commit import SceneCommitter
    from modules.story.outline_state.scene_workbench import SceneWorkbenchService

    first = make_final_scene_candidate(
        candidate_id="left",
        source_candidate_ids=["source-left"],
        source_chapter_indices=[1],
    )
    second = make_final_scene_candidate(
        candidate_id="right",
        source_candidate_ids=["source-right"],
        source_chapter_indices=[2],
    )

    result = await SceneCommitter().commit(
        db_session,
        sample_novel_id,
        [first, second],
        workflow_id="wf-phase1c",
        fusion_suggestions=[
            {
                "suggestion_kind": "cross_chapter",
                "source_candidate_ids": ["left", "right"],
                "proposed_action": "merge",
                "confidence": 0.81,
                "reason": "needs author review",
                "chapter_span": [1, 2],
            }
        ],
    )

    assert len(result.suggestion_ids) == 1
    listed = await SceneWorkbenchService().list_fusion_suggestions(
        db_session,
        sample_novel_id,
    )
    assert listed.total == 1
    assert listed.items[0].source_scene_ids == result.created_scene_ids


@pytest.mark.asyncio
async def test_reextract_protects_canonical_and_queues_replacement(
    db_session: AsyncSession,
    sample_novel_id: str,
) -> None:
    from modules.imports.scene_commit import SceneCommitter
    from modules.story.outline_state.facade import create_scene, get_scene
    from modules.story.outline_state.scene_workbench import SceneWorkbenchService

    protected = await create_scene(
        db_session,
        sample_novel_id,
        {
            "scene_index": 0,
            "title": "Author approved",
            "source": "deep_import",
            "scene_chunks": [{"chapter_index": 1}],
            "chapter_ids": ["1"],
            "structure_meta": {"auto_ingested": True, "workflow_id": "old"},
            "status": "canonical",
        },
    )
    disposable = await create_scene(
        db_session,
        sample_novel_id,
        {
            "scene_index": 1,
            "title": "Unreviewed",
            "source": "deep_import",
            "scene_chunks": [{"chapter_index": 1}],
            "chapter_ids": ["1"],
            "structure_meta": {"auto_ingested": True, "workflow_id": "old"},
            "status": "draft",
        },
    )

    result = await SceneCommitter().commit(
        db_session,
        sample_novel_id,
        [make_final_scene_candidate(source_chapter_indices=[1])],
        workflow_id="new-workflow",
        start_chapter=1,
        end_chapter=1,
        replace_existing=True,
    )

    assert result.created_count == 0
    assert result.replacement_suggestion_count == 1
    assert result.effective_scene_ids == [protected["id"]]
    assert result.effective_coverage["coverage_complete"] is True
    assert (await get_scene(db_session, protected["id"]))["status"] == "canonical"
    assert (await get_scene(db_session, disposable["id"]))["status"] == "deprecated"
    suggestions = await SceneWorkbenchService().list_fusion_suggestions(
        db_session,
        sample_novel_id,
    )
    assert suggestions.total == 1
    assert suggestions.items[0].suggestion_kind == "replacement"
    assert suggestions.items[0].source_scene_ids == [protected["id"]]


@pytest.mark.asyncio
async def test_reextract_allows_same_chapter_non_overlapping_exact_spans(
    db_session: AsyncSession,
    sample_novel_id: str,
) -> None:
    from modules.imports.scene_commit import SceneCommitter
    from modules.story.outline_state.facade import create_scene
    from modules.writing.facade import create_published_draft_only

    draft = await create_published_draft_only(
        db_session,
        sample_novel_id,
        1,
        content="x" * 100,
    )
    await create_scene(
        db_session,
        sample_novel_id,
        {
            "scene_index": 0,
            "title": "Protected first half",
            "source": "manual",
            "scene_chunks": [
                {
                    "chapter_index": 1,
                    "start_offset": 0,
                    "end_offset": 40,
                    "source_draft_id": draft.id,
                    "source_content_hash": draft.content_hash,
                }
            ],
            "chapter_ids": ["1"],
            "status": "canonical",
        },
    )
    candidate = make_final_scene_candidate(source_chapter_indices=[1])
    candidate.scene_chunks = [
        SceneChunk(
            chapter_index=1,
            start_offset=40,
            end_offset=100,
            source_draft_id=draft.id,
            source_content_hash=draft.content_hash,
        )
    ]

    result = await SceneCommitter().commit(
        db_session,
        sample_novel_id,
        [candidate],
        workflow_id="new-workflow",
        start_chapter=1,
        end_chapter=1,
        replace_existing=True,
    )

    assert result.created_count == 1
    assert result.replacement_suggestion_count == 0
    assert result.effective_scene_count == 2
