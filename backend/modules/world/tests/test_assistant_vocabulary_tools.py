from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError as PydanticValidationError

from core.errors import ConflictError, NotFoundError
from modules.account.facade import current_account_id
from modules.assistant.schemas import WorkContext
from modules.world.assistant_vocabulary_tools import (
    OPERATIONS_SPEC,
    ApplyVocabularyPresets,
    EditVocabularyTerm,
    MergeVocabularyTerms,
    SplitVocabularyTerm,
    VocabularyTermRef,
)
from modules.world.project_vocabulary_schemas import (
    ModelVocabularyProposal,
    VocabularyTermCreate,
    VocabularyTermFields,
)
from modules.world.project_vocabulary_service import (
    create_project_vocabulary_term,
    get_project_vocabulary_term,
    persist_reviewed_model_vocabulary_proposal,
)


def _context():
    return SimpleNamespace(
        run_id=str(uuid4()),
        owner_id=str(current_account_id()),
        work=WorkContext(page="world", scope="project"),
    )


@pytest.mark.asyncio
async def test_assistant_vocabulary_create_edit_and_rejects_full_baseline_drift(
    db_session, test_project_id
):
    spec = OPERATIONS_SPEC["world.vocabulary.create"]
    context = _context()
    create = VocabularyTermCreate(
        kind="space", name="雾港", traits={"geometry": ["area"]}
    )
    preview = await spec["prepare"](db_session, test_project_id, create, context=context)
    assert preview["total_count"] == 0
    assert preview["omitted_count"] == 0
    assert preview["revision_manifest"] == []
    await create_project_vocabulary_term(
        db_session,
        test_project_id,
        VocabularyTermCreate(kind="level", name="外城"),
    )
    with pytest.raises(ConflictError, match="词表已变化"):
        await spec["apply"](db_session, test_project_id, create, preview, context=context)

    spec = OPERATIONS_SPEC["world.vocabulary.create"]
    preview = await spec["prepare"](db_session, test_project_id, create, context=context)
    created = await spec["apply"](
        db_session, test_project_id, create, preview, context=context
    )
    item = await get_project_vocabulary_term(db_session, test_project_id, created["id"])
    assert item.source == "author" and item.author_confirmed

    edit = EditVocabularyTerm(
        type_ref=item.id,
        expected_revision_id=item.revision_id,
        name="雾港新名",
        description=item.description,
        aliases=item.aliases,
        traits={"geometry": ["area"]},
    )
    spec = OPERATIONS_SPEC["world.vocabulary.edit"]
    preview = await spec["prepare"](db_session, test_project_id, edit, context=context)
    assert preview["baseline_hash"] != ""
    assert any(
        entry["type_ref"] == str(item.id)
        and entry["revision_id"] == str(item.revision_id)
        for entry in preview["revision_manifest"]
    )
    updated = await spec["apply"](
        db_session, test_project_id, edit, preview, context=context
    )
    renamed = await get_project_vocabulary_term(
        db_session, test_project_id, updated["id"]
    )
    assert renamed.id == item.id
    assert renamed.name == "雾港新名"
    assert renamed.revision_id != item.revision_id


@pytest.mark.asyncio
async def test_archive_restore_keeps_author_tombstone_and_model_cannot_recreate(
    db_session, test_project_id
):
    context = _context()
    term = await create_project_vocabulary_term(
        db_session,
        test_project_id,
        VocabularyTermCreate(kind="feature", name="潮汐门", aliases=["海門"]),
    )
    ref = VocabularyTermRef(type_ref=term.id, expected_revision_id=term.revision_id)
    spec = OPERATIONS_SPEC["world.vocabulary.archive"]
    preview = await spec["prepare"](db_session, test_project_id, ref, context=context)
    assert preview["after"] == {"status": "archived"}
    archived_ref = await spec["apply"](
        db_session, test_project_id, ref, preview, context=context
    )
    archived = await get_project_vocabulary_term(
        db_session, test_project_id, archived_ref["id"]
    )
    assert archived.id == term.id and archived.status == "archived"
    assert archived.revision_id != term.revision_id

    proposal = ModelVocabularyProposal(
        kind="feature",
        name="潮汐门",
        aliases=["海門"],
        proposal_run_id=uuid4(),
        evidence=[
            {
                "scene_id": uuid4(),
                "quote": "潮汐门在月落时开启",
                "source_hash": "a" * 64,
            }
        ],
    )
    model_result = await persist_reviewed_model_vocabulary_proposal(
        db_session, test_project_id, proposal
    )
    assert model_result["action"] == "restore_suggested"
    assert model_result["existing_type_ref"] == term.id

    ref = VocabularyTermRef(type_ref=term.id, expected_revision_id=archived.revision_id)
    spec = OPERATIONS_SPEC["world.vocabulary.restore"]
    preview = await spec["prepare"](db_session, test_project_id, ref, context=context)
    restored_ref = await spec["apply"](
        db_session, test_project_id, ref, preview, context=context
    )
    restored = await get_project_vocabulary_term(
        db_session, test_project_id, restored_ref["id"]
    )
    assert restored.id == term.id and restored.status == "active"
    assert restored.revision_id != archived.revision_id

    with pytest.raises(ConflictError):
        await create_project_vocabulary_term(
            db_session,
            test_project_id,
            VocabularyTermCreate(kind="feature", name="潮汐门"),
        )


@pytest.mark.asyncio
async def test_merge_split_and_mixed_presets_use_confirmed_domain_services(
    db_session, test_project_id
):
    context = _context()
    first = await create_project_vocabulary_term(
        db_session,
        test_project_id,
        VocabularyTermCreate(kind="relation", name="海路"),
    )
    second = await create_project_vocabulary_term(
        db_session,
        test_project_id,
        VocabularyTermCreate(kind="relation", name="航道"),
    )
    merge = MergeVocabularyTerms(
        target_id=first.id,
        source_ids=[second.id],
        expected_revision_ids={
            first.id: first.revision_id,
            second.id: second.revision_id,
        },
    )
    spec = OPERATIONS_SPEC["world.vocabulary.merge"]
    preview = await spec["prepare"](db_session, test_project_id, merge, context=context)
    assert preview["after"]["redirects"] == [
        {"type_ref": str(second.id), "redirect_to_id": str(first.id)}
    ]
    await spec["apply"](db_session, test_project_id, merge, preview, context=context)
    merged = await get_project_vocabulary_term(
        db_session, test_project_id, str(second.id)
    )
    assert merged.status == "merged" and merged.redirect_to_id == first.id

    retained = VocabularyTermFields(name="海路", aliases=["沿岸航线"])
    split_off = VocabularyTermFields(name="空中航道")
    split = SplitVocabularyTerm(
        type_ref=first.id,
        expected_revision_id=(
            await get_project_vocabulary_term(db_session, test_project_id, str(first.id))
        ).revision_id,
        retained=retained,
        split_off=split_off,
    )
    spec = OPERATIONS_SPEC["world.vocabulary.split"]
    preview = await spec["prepare"](db_session, test_project_id, split, context=context)
    split_result = await spec["apply"](
        db_session, test_project_id, split, preview, context=context
    )
    assert split_result["created_type_ref"] != str(first.id)

    presets = ApplyVocabularyPresets(preset_ids=["xianxia", "urban"])
    spec = OPERATIONS_SPEC["world.vocabulary.apply_presets"]
    preview = await spec["prepare"](db_session, test_project_id, presets, context=context)
    result = await spec["apply"](
        db_session, test_project_id, presets, preview, context=context
    )
    assert result["applied"] > 0 and result["applied"] <= 20
    preview = await spec["prepare"](db_session, test_project_id, presets, context=context)
    repeated = await spec["apply"](
        db_session, test_project_id, presets, preview, context=context
    )
    assert repeated["applied"] == 0
    assert repeated["already_applied"] > 0


@pytest.mark.asyncio
async def test_assistant_vocab_operations_fail_closed_on_owner_or_scope(
    db_session, test_project_id
):
    spec = OPERATIONS_SPEC["world.vocabulary.create"]
    args = VocabularyTermCreate(kind="space", name="隔离星域")
    context = _context()
    context.owner_id = str(uuid4())
    with pytest.raises(NotFoundError):
        await spec["prepare"](db_session, test_project_id, args, context=context)

    context = _context()
    context.work = WorkContext(
        page="world", scope="project", excluded_targets=[f"term:{uuid4()}"]
    )
    with pytest.raises(ConflictError):
        await spec["prepare"](db_session, test_project_id, args, context=context)

    with pytest.raises(PydanticValidationError):
        VocabularyTermRef.model_validate(
            {
                "type_ref": str(uuid4()),
                "expected_revision_id": str(uuid4()),
                "confirmed": True,
            }
        )
