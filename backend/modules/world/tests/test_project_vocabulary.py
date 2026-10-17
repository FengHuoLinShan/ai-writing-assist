from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError as SchemaValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ConflictError, NotFoundError
from modules.world.project_vocabulary_presets import preset_item_profile_type
from modules.world.project_vocabulary_schemas import (
    ModelVocabularyProposal,
    VocabularyEvidence,
    VocabularyMergeRequest,
    VocabularyReviewReceipt,
    VocabularySplitRequest,
    VocabularyTermCreate,
    VocabularyTermFields,
    VocabularyTermUpdate,
    vocabulary_evidence_hash,
    vocabulary_proposal_hash,
)
from modules.world.project_vocabulary_service import (
    apply_vocabulary_presets,
    archive_project_vocabulary_term,
    create_project_vocabulary_term,
    get_project_vocabulary_term,
    get_project_vocabulary_term_revision,
    invalidate_model_vocabulary_evidence,
    merge_project_vocabulary_terms,
    persist_reviewed_model_vocabulary_proposal,
    read_project_vocabulary,
    replace_model_vocabulary_evidence,
    resolve_vocabulary_type_revisions,
    restore_project_vocabulary_term,
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
        proposal_run_id=emerging["item"].proposal_run_id,
        proposal_hash=vocabulary_proposal_hash("relation", _proposal("传送门", both)),
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
            confirmed=True,
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
async def test_genre_preset_keeps_spatial_v1_and_adds_scoped_dossier_v2(
    db_session: AsyncSession, project_novel_id: str
) -> None:
    result = await apply_vocabulary_presets(
        db_session, project_novel_id, ["science_fiction"]
    )
    assert result.applied == 13
    versions = {item.preset_version for item in result.items}
    assert versions == {1, 2}
    dossier_items = [item for item in result.items if item.preset_version == 2]
    assert len(dossier_items) == 8
    assert {
        preset_item_profile_type(
            item.preset_id, item.preset_version, item.preset_item_key
        )
        for item in dossier_items
    } == {
        "character",
        "location",
        "item",
        "faction",
        "species",
        "rule",
        "secret",
        "event",
    }

    repeated = await apply_vocabulary_presets(
        db_session, project_novel_id, ["science_fiction"]
    )
    assert repeated.applied == 0
    assert repeated.already_applied == 13

    from modules.world.project_vocabulary_models import ProjectVocabularyTerm

    terms = list(
        (
            await db_session.scalars(
                select(ProjectVocabularyTerm).where(
                    ProjectVocabularyTerm.novel_id == uuid.UUID(project_novel_id),
                    ProjectVocabularyTerm.preset_id == "science_fiction",
                )
            )
        ).all()
    )
    assert sorted(term.preset_version for term in terms).count(1) == 5
    assert sorted(term.preset_version for term in terms).count(2) == 8


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


@pytest.mark.parametrize(
    "name,aliases", [("！…", ["星门"]), ("星门", ["！"]), ("　", [])]
)
def test_vocabulary_rejects_empty_identity_keys(name, aliases):
    with pytest.raises(SchemaValidationError):
        _term(name, aliases=aliases)


def _review_for(item, evidence, **overrides):
    fields = VocabularyTermFields(
        name=item.name,
        description=item.description,
        aliases=item.aliases,
        traits=item.traits,
    )
    return VocabularyReviewReceipt(
        **{
            "reviewer_run_id": uuid.uuid4(),
            "proposal_run_id": item.proposal_run_id,
            "proposal_hash": vocabulary_proposal_hash(item.kind, fields),
            "evidence_hash": vocabulary_evidence_hash(evidence),
            "verdict": "passed",
            **overrides,
        }
    )


@pytest.mark.asyncio
async def test_review_binds_meaning_generation_and_exact_evidence(
    db_session, project_novel_id
):
    evidence = [
        _evidence(uuid.uuid4(), "此处存在传送。"),
        _evidence(uuid.uuid4(), "两界可以传送。"),
    ]
    created = await persist_reviewed_model_vocabulary_proposal(
        db_session, project_novel_id, _proposal("传送", evidence)
    )
    item = created["item"]
    wrong_fields = VocabularyTermFields(name=item.name, traits={"geometry": ["area"]})
    wrong_hash = vocabulary_proposal_hash(item.kind, wrong_fields)
    for receipt in (
        _review_for(item, evidence, proposal_hash=wrong_hash),
        _review_for(item, evidence, proposal_run_id=uuid.uuid4()),
        _review_for(item, evidence, reviewer_run_id=item.proposal_run_id),
        _review_for(item, evidence[:1]),
    ):
        with pytest.raises(ConflictError):
            await replace_model_vocabulary_evidence(
                db_session,
                project_novel_id,
                str(item.id),
                item.revision_id,
                evidence,
                receipt,
            )
    with pytest.raises(ConflictError):
        await persist_reviewed_model_vocabulary_proposal(
            db_session,
            project_novel_id,
            _proposal(
                item.name,
                evidence,
                review=_review_for(item, evidence, proposal_hash=wrong_hash),
            ),
        )
    active = await replace_model_vocabulary_evidence(
        db_session,
        project_novel_id,
        str(item.id),
        item.revision_id,
        evidence,
        _review_for(item, evidence),
    )
    assert active.status == "active"
    assert active.proposal_run_id == item.proposal_run_id
    assert active.traits.connection == ["traversable", "cross_space"]
    changed = [evidence[0], evidence[1].model_copy(update={"source_hash": "a" * 64})]
    with pytest.raises(ConflictError):
        await replace_model_vocabulary_evidence(
            db_session,
            project_novel_id,
            str(item.id),
            active.revision_id,
            changed,
            _review_for(item, evidence),
        )
    emerging = await replace_model_vocabulary_evidence(
        db_session, project_novel_id, str(item.id), active.revision_id, changed, None
    )
    assert emerging.status == "emerging"
    assert emerging.revision_number == active.revision_number + 1


@pytest.mark.asyncio
async def test_merge_chain_edit_archive_restore_retains_history(
    db_session, project_novel_id
):
    terms = [
        await create_project_vocabulary_term(db_session, project_novel_id, _term(name))
        for name in ("甲门", "乙门", "丙门")
    ]
    first, second, final = terms

    async def merge(target, source):
        return await merge_project_vocabulary_terms(
            db_session,
            project_novel_id,
            VocabularyMergeRequest(
                confirmed=True,
                target_id=target.id,
                source_ids=[source.id],
                expected_revision_ids={
                    target.id: target.revision_id,
                    source.id: source.revision_id,
                },
            ),
        )

    second = await merge(second, first)
    final = await merge(final, second)
    edited = await update_project_vocabulary_term(
        db_session,
        project_novel_id,
        str(final.id),
        VocabularyTermUpdate(
            expected_revision_id=final.revision_id,
            name="终门",
            aliases=["甲门", "乙门", "丙门"],
        ),
    )

    async def propose():
        return await persist_reviewed_model_vocabulary_proposal(
            db_session,
            project_novel_id,
            _proposal("甲门", [_evidence(uuid.uuid4(), "甲门仍在。")], kind="feature"),
        )

    result = await propose()
    assert result["action"] == "reused" and result["item"].id == final.id
    archived = await archive_project_vocabulary_term(
        db_session, project_novel_id, str(final.id), edited.revision_id
    )
    result = await propose()
    assert (
        result["action"] == "restore_suggested"
        and result["existing_type_ref"] == final.id
    )
    restored = await restore_project_vocabulary_term(
        db_session, project_novel_id, str(final.id), archived.revision_id
    )
    assert restored.status == "active"
    pinned = await resolve_vocabulary_type_revisions(
        db_session, project_novel_id, {(first.id, first.revision_id)}
    )
    assert pinned[(first.id, first.revision_id)]["status"] == "merged"
    from modules.world.project_vocabulary_models import ProjectVocabularyRevision

    original = await db_session.scalar(
        select(ProjectVocabularyRevision).where(
            ProjectVocabularyRevision.id == first.revision_id
        )
    )
    assert (
        original.snapshot_json["name"] == "甲门"
        and original.snapshot_json["status"] == "active"
    )


@pytest.mark.asyncio
async def test_merge_alias_overflow_is_rejected_before_writing(
    db_session, project_novel_id
):
    from core.errors import ValidationError

    target = await create_project_vocabulary_term(
        db_session,
        project_novel_id,
        _term("目标", aliases=[f"原名{x}" for x in range(24)]),
    )
    source = await create_project_vocabulary_term(
        db_session, project_novel_id, _term("来源")
    )
    with pytest.raises(ValidationError):
        await merge_project_vocabulary_terms(
            db_session,
            project_novel_id,
            VocabularyMergeRequest(
                confirmed=True,
                target_id=target.id,
                source_ids=[source.id],
                expected_revision_ids={
                    target.id: target.revision_id,
                    source.id: source.revision_id,
                },
            ),
        )
    unchanged = await get_project_vocabulary_term(
        db_session, project_novel_id, str(target.id)
    )
    assert unchanged.revision_id == target.revision_id


@pytest.mark.asyncio
async def test_owner_guard_hides_vocabulary_reads_and_writes(
    db_session, project_novel_id
):
    from modules.account.context import bind_principal, reset_principal
    from modules.account.contracts import AccountPrincipal
    from modules.account.models import Account

    owner_term = await create_project_vocabulary_term(
        db_session, project_novel_id, _term("私有词条")
    )
    stranger = Account(status="active", support_code="U-VOCAB-STRANGER")
    db_session.add(stranger)
    await db_session.flush()
    token = bind_principal(
        AccountPrincipal(
            account_id=stranger.id,
            status="active",
            identity_type="email",
            support_code=stranger.support_code,
        )
    )
    try:
        with pytest.raises(NotFoundError):
            await read_project_vocabulary(db_session, project_novel_id)
        with pytest.raises(NotFoundError):
            await get_project_vocabulary_term(
                db_session, project_novel_id, str(owner_term.id)
            )
        with pytest.raises(NotFoundError):
            await create_project_vocabulary_term(
                db_session, project_novel_id, _term("越权词条")
            )
    finally:
        reset_principal(token)


@pytest.mark.asyncio
async def test_http_validates_confirmation_and_vocabulary_parameters(
    db_session, project_novel_id
):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from core.dependencies import get_db
    from modules.world.project_vocabulary_api import router

    app = FastAPI()
    app.include_router(router)

    async def database():
        yield db_session

    app.dependency_overrides[get_db] = database
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        base = f"/api/world/project-vocabulary/{project_novel_id}"
        created = await client.post(
            f"{base}/terms", json={"kind": "feature", "name": "已确认词条"}
        )
        assert created.status_code == 201
        item = created.json()
        first_revision_id = item["revision_id"]
        updated = await client.patch(
            f"{base}/terms/{item['id']}",
            json={"expected_revision_id": first_revision_id, "name": "修订词条"},
        )
        assert updated.status_code == 200, updated.text
        pinned = await client.get(
            f"{base}/terms/{item['id']}", params={"revision_id": first_revision_id}
        )
        assert pinned.status_code == 200, pinned.text
        assert pinned.json()["name"] == "已确认词条"
        item = updated.json()
        for suffix in ("?limit=0", "?limit=501", "?kind=not-a-kind"):
            assert (await client.get(base + suffix)).status_code == 422
        for confirmation in ({}, {"confirmed": False}):
            response = await client.post(
                f"{base}/terms/{item['id']}/archive",
                json={"expected_revision_id": item["revision_id"], **confirmation},
            )
            assert response.status_code == 422
        merge = {
            "target_id": item["id"],
            "source_ids": [str(uuid.uuid4())],
            "expected_revision_ids": {item["id"]: item["revision_id"]},
        }
        assert (await client.post(f"{base}/merge", json=merge)).status_code == 422
        archived = await client.post(
            f"{base}/terms/{item['id']}/archive",
            json={"expected_revision_id": item["revision_id"], "confirmed": True},
        )
        assert archived.status_code == 200 and archived.json()["status"] == "archived"
        page = await client.get(base + "?include_archived=false")
        assert page.status_code == 200 and page.json()["total_count"] == 0


@pytest.mark.asyncio
async def test_merge_rejects_cross_kind_and_cross_project_without_history_changes(
    db_session, two_projects
):
    from core.errors import ValidationError

    first_novel, second_novel = two_projects
    target = await create_project_vocabulary_term(
        db_session, first_novel, _term("地点类型")
    )
    cross_kind = await create_project_vocabulary_term(
        db_session, first_novel, _term("关系类型", kind="relation")
    )
    cross_project = await create_project_vocabulary_term(
        db_session, second_novel, _term("外部类型")
    )
    for source, error in ((cross_kind, ValidationError), (cross_project, NotFoundError)):
        with pytest.raises(error):
            await merge_project_vocabulary_terms(
                db_session,
                first_novel,
                VocabularyMergeRequest(
                    confirmed=True,
                    target_id=target.id,
                    source_ids=[source.id],
                    expected_revision_ids={
                        target.id: target.revision_id,
                        source.id: source.revision_id,
                    },
                ),
            )
    assert (
        await get_project_vocabulary_term(db_session, first_novel, str(target.id))
    ).revision_id == target.revision_id


@pytest.mark.asyncio
async def test_exact_project_vocabulary_revision_remains_readable(
    db_session, two_projects
):
    novel_id, _other_novel = two_projects
    created = await create_project_vocabulary_term(
        db_session, novel_id, _term("旧类型名")
    )
    updated = await update_project_vocabulary_term(
        db_session,
        novel_id,
        str(created.id),
        VocabularyTermUpdate(expected_revision_id=created.revision_id, name="新类型名"),
    )

    pinned = await get_project_vocabulary_term_revision(
        db_session, novel_id, str(created.id), str(created.revision_id)
    )
    assert pinned.name == "旧类型名"
    assert pinned.revision_number == 1
    assert updated.name == "新类型名"
