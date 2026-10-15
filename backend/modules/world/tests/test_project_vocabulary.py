from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ConflictError, NotFoundError
from modules.world.project_vocabulary_schemas import (
    ModelVocabularyProposal,
    VocabularyEvidence,
    VocabularyMergeRequest,
    VocabularyReviewReceipt,
    VocabularySplitRequest,
    VocabularyTermCreate,
    VocabularyTermUpdate,
    vocabulary_evidence_hash,
)
from modules.world.project_vocabulary_service import (
    apply_vocabulary_presets,
    archive_project_vocabulary_term,
    create_project_vocabulary_term,
    get_project_vocabulary_term,
    invalidate_model_vocabulary_evidence,
    merge_project_vocabulary_terms,
    persist_reviewed_model_vocabulary_proposal,
    read_project_vocabulary,
    resolve_vocabulary_type_revisions,
    split_project_vocabulary_term,
    update_project_vocabulary_term,
)


def _term(name: str, *, kind: str = "feature", aliases=None, traits=None):
    return VocabularyTermCreate(
        kind=kind,
        name=name,
        aliases=aliases or [],
        traits=traits or {},
    )


def _evidence(scene_id: uuid.UUID, quote: str) -> VocabularyEvidence:
    return VocabularyEvidence(
        scene_id=scene_id,
        quote=quote,
        source_hash=uuid.uuid5(scene_id, "scene-source").hex * 2,
    )


def _proposal(
    name: str,
    evidence: list[VocabularyEvidence],
    *,
    review=None,
    kind: str = "relation",
):
    return ModelVocabularyProposal(
        kind=kind,
        name=name,
        proposal_run_id=uuid.uuid4(),
        evidence=evidence,
        independent_review=review,
        traits={"connection": ["traversable", "cross_space"]},
    )


@pytest.mark.asyncio
async def test_author_crud_uses_stable_identity_cas_and_tombstones(
    db_session: AsyncSession, project_novel_id: str
) -> None:
    created = await create_project_vocabulary_term(
        db_session,
        project_novel_id,
        _term(
            "跨界传送",
            aliases=["传送 门", "传送门"],
            traits={"connection": ["cross_space"]},
        ),
    )
    assert created.aliases == ["传送 门"]
    assert created.revision_number == 1

    updated = await update_project_vocabulary_term(
        db_session,
        project_novel_id,
        str(created.id),
        VocabularyTermUpdate(
            expected_revision_id=created.revision_id,
            name="星门",
            aliases=["跨界传送"],
            traits={"connection": ["cross_space", "traversable"]},
        ),
    )
    assert updated.id == created.id
    assert updated.revision_number == 2
    assert updated.previous_revision_id == created.revision_id
    assert updated.content_hash != created.content_hash

    with pytest.raises(ConflictError):
        await update_project_vocabulary_term(
            db_session,
            project_novel_id,
            str(created.id),
            VocabularyTermUpdate(
                expected_revision_id=created.revision_id,
                name="过期修改",
            ),
        )

    with pytest.raises(ConflictError):
        await create_project_vocabulary_term(
            db_session, project_novel_id, _term("星门！")
        )

    archived = await archive_project_vocabulary_term(
        db_session, project_novel_id, str(created.id), updated.revision_id
    )
    assert archived.status == "archived"
    assert archived.id == created.id
    page = await read_project_vocabulary(db_session, project_novel_id, limit=1)
    assert page.total_count == page.omitted_count + 1
    assert page.items[0].status == "archived"


@pytest.mark.asyncio
async def test_model_type_requires_two_scenes_and_review_and_respects_tombstones(
    db_session: AsyncSession, project_novel_id: str
) -> None:
    first_scene, second_scene, third_scene = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    first_evidence = [_evidence(first_scene, "两界之间有一道传送门。")]
    emerging = await persist_reviewed_model_vocabulary_proposal(
        db_session, project_novel_id, _proposal("传送门", first_evidence)
    )
    assert emerging["item"].status == "emerging"

    both = first_evidence + [
        _evidence(second_scene, "通过传送门即可抵达另一界。"),
        _evidence(third_scene, "传送门另一端连接着异界。"),
    ]
    still_emerging = await persist_reviewed_model_vocabulary_proposal(
        db_session, project_novel_id, _proposal("传送 门", both)
    )
    assert still_emerging["action"] == "updated"
    assert still_emerging["item"].id == emerging["item"].id
    assert still_emerging["item"].status == "emerging"

    review = VocabularyReviewReceipt(
        reviewer_run_id=uuid.uuid4(),
        evidence_hash=vocabulary_evidence_hash(both),
        verdict="passed",
    )
    active = await persist_reviewed_model_vocabulary_proposal(
        db_session, project_novel_id, _proposal("传送门", both, review=review)
    )
    assert active["item"].id == emerging["item"].id
    assert active["item"].status == "active"

    changed = await invalidate_model_vocabulary_evidence(
        db_session, project_novel_id, {first_scene}
    )
    assert len(changed) == 1
    assert changed[0].id == emerging["item"].id
    assert changed[0].status == "active"
    assert len(changed[0].evidence) == 2

    changed = await invalidate_model_vocabulary_evidence(
        db_session, project_novel_id, {second_scene}
    )
    assert len(changed) == 1
    assert changed[0].status == "emerging"
    assert len(changed[0].evidence) == 1

    archived = await archive_project_vocabulary_term(
        db_session,
        project_novel_id,
        str(changed[0].id),
        changed[0].revision_id,
    )
    tombstone_proposal = await persist_reviewed_model_vocabulary_proposal(
        db_session, project_novel_id, _proposal("传送门", both)
    )
    assert tombstone_proposal["action"] == "restore_suggested"
    assert tombstone_proposal["existing_type_ref"] == archived.id

    terms = await read_project_vocabulary(
        db_session, project_novel_id, kind="relation", limit=10
    )
    assert terms.total_count == 1


@pytest.mark.asyncio
async def test_author_types_are_reused_without_model_mutation(
    db_session: AsyncSession, project_novel_id: str
) -> None:
    author_type = await create_project_vocabulary_term(
        db_session,
        project_novel_id,
        _term("传送门", kind="relation", traits={"connection": ["cross_space"]}),
    )
    result = await persist_reviewed_model_vocabulary_proposal(
        db_session,
        project_novel_id,
        _proposal("传送 门", [_evidence(uuid.uuid4(), "传送门。")]),
    )
    assert result["action"] == "reused"
    assert result["item"].id == author_type.id
    assert result["item"].revision_id == author_type.revision_id
    assert result["item"].traits.connection == ["cross_space"]


@pytest.mark.asyncio
async def test_merge_split_keep_redirects_and_pin_type_revisions(
    db_session: AsyncSession, project_novel_id: str
) -> None:
    target = await create_project_vocabulary_term(
        db_session, project_novel_id, _term("星门", traits={"geometry": ["point"]})
    )
    source = await create_project_vocabulary_term(
        db_session, project_novel_id, _term("跃迁门", traits={"geometry": ["point"]})
    )
    merged = await merge_project_vocabulary_terms(
        db_session,
        project_novel_id,
        VocabularyMergeRequest(
            target_id=target.id,
            source_ids=[source.id],
            expected_revision_ids={
                target.id: target.revision_id,
                source.id: source.revision_id,
            },
        ),
    )
    assert "跃迁门" in merged.aliases
    source_now = await get_project_vocabulary_term(
        db_session, project_novel_id, str(source.id)
    )
    assert source_now.status == "merged"
    assert source_now.redirect_to_id == target.id
    redirected_proposal = await persist_reviewed_model_vocabulary_proposal(
        db_session,
        project_novel_id,
        _proposal(
            "跃迁门",
            [_evidence(uuid.uuid4(), "此处可经跃迁门到达。")],
            kind="feature",
        ),
    )
    assert redirected_proposal["action"] == "reused"
    assert redirected_proposal["item"].id == target.id

    updated = await update_project_vocabulary_term(
        db_session,
        project_novel_id,
        str(merged.id),
        VocabularyTermUpdate(
            expected_revision_id=merged.revision_id,
            name="星际之门",
            aliases=["星门", "跃迁门"],
            traits={"geometry": ["area"]},
        ),
    )
    pinned = await resolve_vocabulary_type_revisions(
        db_session,
        project_novel_id,
        {(updated.id, merged.revision_id), (updated.id, updated.revision_id)},
    )
    assert pinned[(updated.id, merged.revision_id)]["traits"]["geometry"] == ["point"]
    assert pinned[(updated.id, updated.revision_id)]["traits"]["geometry"] == [
        "area",
    ]

    retained, split_off = await split_project_vocabulary_term(
        db_session,
        project_novel_id,
        str(updated.id),
        VocabularySplitRequest(
            expected_revision_id=updated.revision_id,
            retained={"name": "星际之门", "aliases": ["星门"]},
            split_off={"name": "折跃门", "aliases": ["超空间门"]},
        ),
    )
    assert retained.id == updated.id
    assert retained.revision_number == updated.revision_number + 1
    assert split_off.id != retained.id


@pytest.mark.asyncio
async def test_versioned_presets_are_mixable_idempotent_and_report_omissions(
    db_session: AsyncSession, project_novel_id: str
) -> None:
    selected = ["xianxia", "urban", "mystery"]
    first = await apply_vocabulary_presets(db_session, project_novel_id, selected)
    assert first.applied > 0
    assert first.already_applied == 0

    repeated = await apply_vocabulary_presets(db_session, project_novel_id, selected)
    assert repeated.applied == 0
    assert repeated.already_applied == first.applied
    assert repeated.duplicate_skipped == 0

    capped = await read_project_vocabulary(
        db_session, project_novel_id, limit=2, include_archived=True
    )
    assert capped.total_count == first.applied
    assert capped.omitted_count == capped.total_count - len(capped.items)


@pytest.mark.asyncio
async def test_pinned_revision_resolver_fails_closed_across_novels(
    db_session: AsyncSession, two_projects: tuple[str, str]
) -> None:
    owner_novel, other_novel = two_projects
    foreign_type = await create_project_vocabulary_term(
        db_session, other_novel, _term("异项目地点")
    )
    with pytest.raises(NotFoundError):
        await resolve_vocabulary_type_revisions(
            db_session,
            owner_novel,
            {(foreign_type.id, foreign_type.revision_id)},
        )
