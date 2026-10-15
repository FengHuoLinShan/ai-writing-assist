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


@pytest.mark.asyncio
@pytest.mark.parametrize("external_change", [False, True])
@pytest.mark.parametrize("operation_kind", ["create", "edit"])
async def test_vocabulary_batch_confirms_multiple_targets_and_replays_without_writes(
    db_session, test_project_id, external_change, operation_kind
):
    from uuid import UUID

    from modules.assistant.contracts import AssistantOperationContext
    from modules.assistant.evidence_tools import fingerprint
    from modules.assistant.models import AssistantActionBatch, AssistantRun
    from modules.assistant.operations import (
        decide_batch,
        operation_manifest,
        prepare_actions,
    )
    from modules.assistant.schemas import BatchDecision, ProposedAction
    from modules.world.project_vocabulary_service import read_project_vocabulary

    db, nid = db_session, test_project_id
    context = AssistantOperationContext(
        str(uuid4()), str(current_account_id()), WorkContext(scope="project")
    )
    targets = (
        [
            await create_project_vocabulary_term(
                db, nid, VocabularyTermCreate(kind="space", name=f"原名{i}")
            )
            for i in range(2)
        ]
        if operation_kind == "edit"
        else []
    )
    actions = await prepare_actions(
        db,
        nid,
        [
            ProposedAction(
                key=f"create-{i}",
                capability=f"world.vocabulary.{operation_kind}",
                title=name,
                arguments={"kind": "space", "name": name}
                if operation_kind == "create"
                else {
                    "type_ref": str(targets[i].id),
                    "expected_revision_id": str(targets[i].revision_id),
                    "name": name,
                },
            )
            for i, name in enumerate(["星港", "月城"])
        ],
        context=context,
    )
    run = AssistantRun(
        id=UUID(context.run_id),
        novel_id=UUID(nid),
        owner_id=current_account_id(),
        request_hash="a" * 64,
        status="waiting_approval",
        request_json={
            "runtime_version": "4",
            "operations": operation_manifest(),
            "context": context.work.model_dump(mode="json"),
        },
    )
    db.add(run)
    await db.flush()
    batch = AssistantActionBatch(
        novel_id=run.novel_id,
        run_id=run.id,
        fingerprint=fingerprint(actions),
        actions_json=actions,
    )
    db.add(batch)
    await db.flush()
    decision = BatchDecision(
        novel_id=nid,
        fingerprint=batch.fingerprint,
        selected=[item["key"] for item in actions],
        confirmed=True,
    )
    if external_change:
        await create_project_vocabulary_term(
            db, nid, VocabularyTermCreate(kind="space", name="外部改动")
        )
        with pytest.raises(ConflictError, match="资料已变化"):
            await decide_batch(db, str(batch.id), decision, context.owner_id)
        assert not batch.authorization_json
        assert not {"星港", "月城"}.intersection(
            item.name for item in (await read_project_vocabulary(db, nid)).items
        )
        return
    result = await decide_batch(db, str(batch.id), decision, context.owner_id)
    assert result["status"] == "completed", result
    assert len(result["results"]) == 2
    before = (await read_project_vocabulary(db, nid)).model_dump(mode="json")
    assert {item["name"] for item in before["items"]} == {"星港", "月城"}
    assert await decide_batch(db, str(batch.id), decision, context.owner_id) == result
    assert (await read_project_vocabulary(db, nid)).model_dump(mode="json") == before


@pytest.mark.asyncio
async def test_legacy_map_batch_keeps_frozen_schema_through_confirmation(
    db_session, test_project_id
):
    from uuid import UUID

    from modules.assistant.contracts import AssistantOperationContext
    from modules.assistant.evidence_tools import fingerprint
    from modules.assistant.models import AssistantActionBatch, AssistantRun
    from modules.assistant.operations import (
        decide_batch,
        prepare_actions,
        resolve_operations,
    )
    from modules.assistant.schemas import BatchDecision, ProposedAction

    manifest = {
        "map.create_node": {
            "schema_hash": (
                "afb6aa06a68c39a27026fc50565cdc87d72e266e569b362d95fdd23a428c2bc8"
            ),
            "revision": "1",
        }
    }
    context = AssistantOperationContext(
        str(uuid4()), str(current_account_id()), WorkContext(scope="project")
    )
    actions = await prepare_actions(
        db_session,
        test_project_id,
        [
            ProposedAction(
                key="map",
                capability="map.create_node",
                title="旧地图",
                arguments={"title": "旧地图"},
            )
        ],
        context=context,
        operations=resolve_operations(manifest),
    )
    assert "level_type_ref" not in actions[0]["arguments"]
    assert actions[0]["operation_manifest"] == manifest["map.create_node"]
    run = AssistantRun(
        id=UUID(context.run_id),
        novel_id=UUID(test_project_id),
        owner_id=current_account_id(),
        request_hash="a" * 64,
        request_json={
            "runtime_version": "3",
            "operations": manifest,
            "context": context.work.model_dump(mode="json"),
        },
    )
    db_session.add(run)
    await db_session.flush()
    batch = AssistantActionBatch(
        novel_id=run.novel_id,
        run_id=run.id,
        fingerprint=fingerprint(actions),
        actions_json=actions,
    )
    db_session.add(batch)
    await db_session.flush()
    result = await decide_batch(
        db_session,
        str(batch.id),
        BatchDecision(
            novel_id=test_project_id,
            fingerprint=batch.fingerprint,
            selected=["map"],
            confirmed=True,
        ),
        context.owner_id,
    )
    assert result["status"] == "completed", result


@pytest.mark.asyncio
async def test_vocabulary_batch_counts_split_targets_and_rejects_overlapping_merge(
    db_session, test_project_id
):
    from core.errors import ValidationError
    from modules.assistant.contracts import AssistantOperationContext
    from modules.assistant.operations import prepare_actions
    from modules.assistant.schemas import ProposedAction

    context = AssistantOperationContext(
        str(uuid4()), str(current_account_id()), WorkContext(scope="project")
    )
    terms = [
        await create_project_vocabulary_term(
            db_session,
            test_project_id,
            VocabularyTermCreate(kind="feature", name=f"星门{i}"),
        )
        for i in range(11)
    ]
    proposals = [
        ProposedAction(
            key=f"split-{i}",
            capability="world.vocabulary.split",
            title="拆分",
            arguments={
                "type_ref": str(term.id),
                "expected_revision_id": str(term.revision_id),
                "retained": {"name": term.name},
                "split_off": {"name": f"城市星门{i}"},
            },
        )
        for i, term in enumerate(terms)
    ]
    assert (
        len(
            await prepare_actions(
                db_session, test_project_id, proposals[:10], context=context
            )
        )
        == 10
    )
    with pytest.raises(ValidationError, match="20 项"):
        await prepare_actions(db_session, test_project_id, proposals, context=context)
    merge = ProposedAction(
        key="merge",
        capability="world.vocabulary.merge",
        title="合并",
        arguments={
            "target_id": str(terms[1].id),
            "source_ids": [str(terms[0].id)],
            "expected_revision_ids": {
                str(term.id): str(term.revision_id) for term in terms[:2]
            },
        },
    )
    with pytest.raises(ValidationError, match="同一资产"):
        await prepare_actions(
            db_session, test_project_id, [merge, proposals[0]], context=context
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
