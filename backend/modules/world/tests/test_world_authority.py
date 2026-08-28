from __future__ import annotations

import json
import uuid
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import TypeAdapter
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import func, select

from core.errors import DomainError
from modules.account.contracts import BOOTSTRAP_ACCOUNT_ID
from modules.world.authority import (
    CanonAdmissionPreviewRequest,
    CanonAdmissionReceiptV1,
    CanonAdmissionRequest,
    CanonManifestV1,
    DecimalScalarV1,
    EnumScalarV1,
    ExactResourceRevisionRef,
    PageDraftSnapshotV1,
    PagePublishPreviewInputV1,
    ResourceRef,
    RevertPreviewInputV1,
    StatementClaimRefV1,
    StatementValueV1,
    TargetRefV1,
    WholeSelector,
    WorldBiblePageSectionSelectorPayload,
    canonical_digest,
    canonical_json,
    legacy_resource_revision_digest,
    resource_revision_digest,
)
from modules.world.models import (
    WorldBiblePageDraft,
    WorldBiblePageRevision,
    WorldCanonHead,
    WorldCanonRevision,
)
from modules.world.schemas import WorldBiblePageDraftCreate
from modules.world.services.worldbuilding.world_authority_service import (
    WorldAuthorityService,
)
from modules.world.services.worldbuilding.world_bible_lifecycle_service import (
    WorldBibleLifecycleService,
)

_FIXTURES_PATH = (
    Path(__file__).parents[4]
    / "docs"
    / "references"
    / "world-authority-canonical-fixtures-v1.json"
)


def test_canonical_fixtures_are_executable() -> None:
    fixtures = json.loads(_FIXTURES_PATH.read_text())
    for case in fixtures["cases"]:
        assert canonical_json(case["normalized"]) == case["expected_canonical_json"]
        assert canonical_digest(case["normalized"]) == case["expected_sha256"]


def test_fixture_wire_shapes_match_closed_models() -> None:
    cases = {
        case["name"]: case for case in json.loads(_FIXTURES_PATH.read_text())["cases"]
    }
    target = TargetRefV1.model_validate(cases["page_section_target_ref"]["normalized"])
    adapter = TypeAdapter(StatementValueV1)
    adapter.validate_python(cases["entity_name_statement"]["normalized"])
    adapter.validate_python(cases["entity_decimal_statement"]["normalized"])
    adapter.validate_python(cases["entity_relation_statement"]["normalized"])
    StatementClaimRefV1.model_validate(cases["statement_claim_ref"]["normalized"])
    CanonManifestV1.model_validate(cases["empty_c0_manifest"]["normalized"])
    receipt = CanonAdmissionReceiptV1.model_validate(
        cases["empty_c0_receipt"]["normalized"]
    )
    assert canonical_json(receipt) == cases["empty_c0_receipt"]["expected_canonical_json"]
    assert DecimalScalarV1(value="+001.7800").value == "1.78"
    with pytest.raises(PydanticValidationError):
        adapter.validate_python(cases["statement_claim_ref"]["normalized"])
    duplicate_manifest = {
        **cases["empty_c0_manifest"]["normalized"],
        "active_resources": [
            target.revision.model_dump(mode="json"),
            target.revision.model_dump(mode="json"),
        ],
    }
    with pytest.raises(PydanticValidationError):
        CanonManifestV1.model_validate(duplicate_manifest)


def test_canonical_model_datetime_is_utc_and_identifiers_are_ascii() -> None:
    snapshot = PageDraftSnapshotV1(
        draft_id=uuid.uuid4(),
        title="中文标题",
        page_type=" background ",
        page_meta_json={},
        sections_json=[],
        linked_asset_refs_json=[],
        sort_order=0,
        template_version=1,
        updated_at=datetime(
            2026,
            8,
            27,
            8,
            tzinfo=timezone(timedelta(hours=8)),
        ),
    )
    assert snapshot.page_type == "background"
    assert '"updated_at":"2026-08-27T00:00:00Z"' in canonical_json(snapshot)

    naive = snapshot.model_copy(
        update={"updated_at": datetime(2026, 8, 27, 0, 0)}
    )
    with pytest.raises(ValueError, match="timezone"):
        canonical_json(naive)
    with pytest.raises(ValueError, match="floats"):
        resource_revision_digest(
            ResourceRef(
                kind="world_bible_page",
                novel_id=uuid.uuid4(),
                resource_id=uuid.uuid4(),
            ),
            uuid.uuid4(),
            {"weight": 0.5},
        )
    with pytest.raises(PydanticValidationError):
        WorldBiblePageSectionSelectorPayload(section_id="中文分区")
    with pytest.raises(PydanticValidationError):
        EnumScalarV1(value="中文枚举")


async def test_page_admission_is_idempotent_and_revert_is_append_only(
    db_session,
    project_novel_id: str,
) -> None:
    authority = WorldAuthorityService()
    lifecycle = WorldBibleLifecycleService()
    c0 = await authority.initialize_empty_canon(db_session, project_novel_id)
    assert c0.version_number == 0
    assert await authority.initialize_empty_canon(db_session, project_novel_id) is c0
    valid_c0_receipt = deepcopy(c0.receipt_json)
    valid_c0_decision_id = c0.decision_id
    tampered_c0_decision_id = uuid.uuid4()
    tampered_c0_receipt = deepcopy(valid_c0_receipt)
    tampered_c0_receipt["decision"]["id"] = str(tampered_c0_decision_id)
    c0.receipt_json = tampered_c0_receipt
    c0.decision_id = tampered_c0_decision_id
    await db_session.flush()
    with pytest.raises(DomainError) as bootstrap_error:
        await authority.get_revision(db_session, project_novel_id, str(c0.id))
    assert bootstrap_error.value.code == "canon_revision_digest_mismatch"
    c0.receipt_json = valid_c0_receipt
    c0.decision_id = valid_c0_decision_id
    await db_session.flush()

    draft = await lifecycle.create_draft(
        db_session,
        WorldBiblePageDraftCreate(
            novel_id=project_novel_id,
            title="北境贸易",
            page_type="background",
            free_text="以盐票结算。",
        ),
    )
    preview = await authority.preview(
        db_session,
        CanonAdmissionPreviewRequest(
            novel_id=project_novel_id,
            expected_previous_head=c0.id,
            input=PagePublishPreviewInputV1(
                novel_id=project_novel_id,
                draft_id=draft.id,
            ),
        ),
    )
    decision_id = uuid.uuid4()
    request = CanonAdmissionRequest(
        novel_id=project_novel_id,
        decision_id=decision_id,
        expected_previous_head=c0.id,
        confirmed=True,
        input=preview.normalized_input,
    )
    admitted = await authority.admit(
        db_session,
        request,
        authorizer_id=BOOTSTRAP_ACCOUNT_ID,
    )
    assert admitted.version_number == 1
    assert admitted.parent_revision_id == c0.id
    assert admitted.changes["resource_count"] == 1
    assert await db_session.get(WorldBiblePageDraft, uuid.UUID(draft.id)) is None

    admitted_model = await db_session.get(WorldCanonRevision, admitted.id)
    assert admitted_model is not None
    await authority.get_revision(db_session, project_novel_id, str(admitted_model.id))
    valid_receipt = deepcopy(admitted_model.receipt_json)
    invalid_receipt = {**valid_receipt, "manifest_digest": "0" * 64}
    admitted_model.receipt_json = invalid_receipt
    await db_session.flush()
    with pytest.raises(DomainError) as receipt_error:
        await authority.get_revision(db_session, project_novel_id, str(admitted_model.id))
    assert receipt_error.value.code == "canon_revision_digest_mismatch"
    admitted_model.receipt_json = valid_receipt
    await db_session.flush()
    unbound_receipt = deepcopy(valid_receipt)
    unbound_receipt["affected_resources"] = []
    admitted_model.receipt_json = unbound_receipt
    await db_session.flush()
    with pytest.raises(DomainError) as transition_error:
        await authority.get_revision(db_session, project_novel_id, str(admitted_model.id))
    assert transition_error.value.code == "canon_revision_digest_mismatch"
    admitted_model.receipt_json = valid_receipt
    await db_session.flush()
    exact = ExactResourceRevisionRef.model_validate(
        admitted_model.manifest_json["active_resources"][0]
    )
    snapshot = await authority.resolve_target(
        db_session,
        TargetRefV1(revision=exact, selector=WholeSelector()),
        novel_id=uuid.UUID(project_novel_id),
    )
    assert snapshot["title"] == "北境贸易"
    page_revision = await db_session.get(WorldBiblePageRevision, exact.revision_id)
    original_snapshot = deepcopy(page_revision.snapshot_json)
    legacy_snapshot = deepcopy(original_snapshot)
    legacy_snapshot["page_meta_json"] = {"weight": 0.5}
    legacy_digest = legacy_resource_revision_digest(
        exact.resource,
        exact.revision_id,
        legacy_snapshot,
    )
    page_revision.snapshot_json = legacy_snapshot
    page_revision.revision_digest = legacy_digest
    await db_session.flush()
    legacy_exact = exact.model_copy(update={"revision_digest": legacy_digest})
    assert (
        await authority.resolve_target(
            db_session,
            TargetRefV1(revision=legacy_exact, selector=WholeSelector()),
            novel_id=uuid.UUID(project_novel_id),
        )
    )["page_meta_json"] == {"weight": 0.5}
    page_revision.snapshot_json = original_snapshot
    page_revision.revision_digest = exact.revision_digest
    await db_session.flush()
    wrong_digest = exact.model_copy(update={"revision_digest": "0" * 64})
    with pytest.raises(DomainError) as digest_error:
        await authority.resolve_target(
            db_session,
            TargetRefV1(revision=wrong_digest, selector=WholeSelector()),
            novel_id=uuid.UUID(project_novel_id),
        )
    assert digest_error.value.code == "canon_revision_digest_mismatch"

    retried = await authority.admit(
        db_session,
        request,
        authorizer_id=BOOTSTRAP_ACCOUNT_ID,
    )
    assert retried.id == admitted.id
    assert await db_session.scalar(select(func.count(WorldCanonRevision.id))) == 2
    recovered = await authority.get_admitted_page_publish(
        db_session,
        project_novel_id,
        decision_id,
        expected_previous_head=c0.id,
        draft_id=draft.id,
    )
    assert recovered is not None and recovered.id == admitted.id
    with pytest.raises(DomainError) as reused_error:
        await authority.get_admitted_page_publish(
            db_session,
            project_novel_id,
            decision_id,
            expected_previous_head=c0.id,
            draft_id=uuid.uuid4(),
        )
    assert reused_error.value.code == "canon_decision_id_reused"

    revert_preview = await authority.preview(
        db_session,
        CanonAdmissionPreviewRequest(
            novel_id=project_novel_id,
            expected_previous_head=admitted.id,
            input=RevertPreviewInputV1(
                novel_id=project_novel_id,
                target_revision_id=c0.id,
            ),
        ),
    )
    assert revert_preview.normalized_input.expected_previous_head == admitted.id
    assert (
        revert_preview.normalized_input.compatibility_judgment.current_manifest_digest
        == admitted_model.manifest_digest
    )
    assert (
        revert_preview.normalized_input.compatibility_judgment.target_manifest_digest
        == c0.manifest_digest
    )
    reverted = await authority.admit(
        db_session,
        CanonAdmissionRequest(
            novel_id=project_novel_id,
            decision_id=uuid.uuid4(),
            expected_previous_head=admitted.id,
            confirmed=True,
            input=revert_preview.normalized_input,
        ),
        authorizer_id=BOOTSTRAP_ACCOUNT_ID,
    )
    assert reverted.version_number == 2
    assert reverted.parent_revision_id == admitted.id
    assert reverted.changes["resource_count"] == 0
    await authority.get_revision(db_session, project_novel_id, str(reverted.id))

    reverted_model = await db_session.get(WorldCanonRevision, reverted.id)
    assert reverted_model is not None
    valid_revert_receipt = deepcopy(reverted_model.receipt_json)
    invalid_affected_resources = deepcopy(valid_revert_receipt)
    invalid_affected_resources["affected_resources"] = [
        exact.model_dump(mode="json")
    ]
    reverted_model.receipt_json = invalid_affected_resources
    await db_session.flush()
    with pytest.raises(DomainError) as affected_error:
        await authority.get_revision(db_session, project_novel_id, str(reverted.id))
    assert affected_error.value.code == "canon_revision_digest_mismatch"
    reverted_model.receipt_json = valid_revert_receipt
    await db_session.flush()
    invalid_revert_receipt = deepcopy(valid_revert_receipt)
    invalid_input = invalid_revert_receipt["admission_input"]
    invalid_input["compatibility_judgment"]["target_manifest_digest"] = (
        admitted_model.manifest_digest
    )
    invalid_input_digest = canonical_digest(invalid_input)
    invalid_revert_receipt["admission_input_digest"] = invalid_input_digest
    invalid_decision_digest = authority._decision_digest(invalid_input, admitted.id)
    invalid_revert_receipt["decision"]["digest"] = invalid_decision_digest
    reverted_model.receipt_json = invalid_revert_receipt
    reverted_model.decision_digest = invalid_decision_digest
    await db_session.flush()
    with pytest.raises(DomainError) as replay_error:
        await authority.get_revision(db_session, project_novel_id, str(reverted.id))
    assert replay_error.value.code == "canon_revision_digest_mismatch"
    reverted_model.receipt_json = valid_revert_receipt


async def test_admission_rejects_changed_draft_without_advancing_head(
    db_session,
    project_novel_id: str,
) -> None:
    authority = WorldAuthorityService()
    lifecycle = WorldBibleLifecycleService()
    c0 = await authority.initialize_empty_canon(db_session, project_novel_id)
    draft = await lifecycle.create_draft(
        db_session,
        WorldBiblePageDraftCreate(
            novel_id=project_novel_id,
            title="旧标题",
            page_type="background",
        ),
    )
    preview = await authority.preview(
        db_session,
        CanonAdmissionPreviewRequest(
            novel_id=project_novel_id,
            expected_previous_head=c0.id,
            input=PagePublishPreviewInputV1(
                novel_id=project_novel_id,
                draft_id=draft.id,
            ),
        ),
    )
    model = await db_session.get(WorldBiblePageDraft, uuid.UUID(draft.id))
    assert model is not None
    model.title = "新标题"
    await db_session.flush()

    with pytest.raises(DomainError) as error:
        await authority.admit(
            db_session,
            CanonAdmissionRequest(
                novel_id=project_novel_id,
                decision_id=uuid.uuid4(),
                expected_previous_head=c0.id,
                confirmed=True,
                input=preview.normalized_input,
            ),
            authorizer_id=BOOTSTRAP_ACCOUNT_ID,
        )
    assert error.value.code == "canon_admission_stale"
    head = await db_session.get(WorldCanonHead, uuid.UUID(project_novel_id))
    assert head is not None and head.current_revision_id == c0.id
    assert await db_session.get(WorldBiblePageDraft, uuid.UUID(draft.id)) is model


async def test_assert_admission_rejects_unregistered_calendar(
    db_session,
    project_novel_id: str,
) -> None:
    authority = WorldAuthorityService()
    c0 = await authority.initialize_empty_canon(db_session, project_novel_id)
    nid = uuid.UUID(project_novel_id)
    with pytest.raises(DomainError) as error:
        await authority.admit(
            db_session,
            CanonAdmissionRequest(
                novel_id=nid,
                decision_id=uuid.uuid4(),
                expected_previous_head=c0.id,
                confirmed=True,
                input={
                    "kind": "assert_batch",
                    "version": 1,
                    "novel_id": str(nid),
                    "assertions": [
                        {
                            "novel_id": str(nid),
                            "regime": "objective_world.v1",
                            "polarity": "positive",
                            "statement": {
                                "kind": "entity_name",
                                "version": 1,
                                "subject": {
                                    "novel_id": str(nid),
                                    "referent_id": str(uuid.uuid4()),
                                },
                                "name": "沈岚",
                            },
                            "schema_ref": {
                                "artifact_id": "world.statement-schema",
                                "version": 1,
                                "digest": (
                                    "3eda28fd8a246e2c44cfd36683b754b221de5a340ce0c04"
                                    "be58a85f186c6c81e"
                                ),
                            },
                            "time_scope": {
                                "kind": "point",
                                "version": 1,
                                "calendar_ref": {
                                    "artifact_id": "example.story-calendar",
                                    "version": 1,
                                    "digest": "6" * 64,
                                },
                                "value": 1,
                            },
                        }
                    ],
                    "candidate_snapshot": {},
                    "selected_item_keys": ["name"],
                    "source_refs": [],
                },
            ),
            authorizer_id=BOOTSTRAP_ACCOUNT_ID,
        )
    assert error.value.code == "unsupported_calendar"


async def test_page_preview_rejects_invalid_card_subject_without_writes(
    db_session,
    project_novel_id: str,
) -> None:
    authority = WorldAuthorityService()
    c0 = await authority.initialize_empty_canon(db_session, project_novel_id)
    draft = await WorldBibleLifecycleService().create_draft(
        db_session,
        WorldBiblePageDraftCreate(
            novel_id=project_novel_id,
            title="错误对象引用",
            page_type="background",
            page_meta_json={
                "card_subject_ref_v1": {
                    "kind": "core_entity",
                    "entity_id": str(uuid.uuid4()),
                }
            },
        ),
    )

    with pytest.raises(DomainError) as error:
        await authority.preview(
            db_session,
            CanonAdmissionPreviewRequest(
                novel_id=project_novel_id,
                expected_previous_head=c0.id,
                input=PagePublishPreviewInputV1(
                    novel_id=project_novel_id,
                    draft_id=draft.id,
                ),
            ),
        )
    assert error.value.code == "canon_reference_unavailable"
    head = await db_session.get(WorldCanonHead, uuid.UUID(project_novel_id))
    assert head is not None and head.current_revision_id == c0.id
    assert await db_session.get(WorldBiblePageDraft, uuid.UUID(draft.id)) is not None


async def test_owner_api_creates_c0_and_admits_exact_page_publish(async_client) -> None:
    created = await async_client.post("/api/projects", json={"title": "正典事务"})
    assert created.status_code == 201
    novel_id = created.json()["id"]

    head_response = await async_client.get(
        "/api/world/canon/head", params={"novel_id": novel_id}
    )
    assert head_response.status_code == 200
    c0_id = head_response.json()["current_revision"]["id"]

    draft_response = await async_client.post(
        "/api/world/bible/drafts",
        json={
            "novel_id": novel_id,
            "title": "北境贸易",
            "page_type": "background",
            "free_text": "以盐票结算。",
        },
    )
    assert draft_response.status_code == 201
    draft_id = draft_response.json()["id"]
    preview_response = await async_client.post(
        "/api/world/canon/admissions/preview",
        json={
            "novel_id": novel_id,
            "expected_previous_head": c0_id,
            "input": {
                "kind": "page_publish",
                "version": 1,
                "novel_id": novel_id,
                "draft_id": draft_id,
            },
        },
    )
    assert preview_response.status_code == 200
    preview = preview_response.json()
    admitted = await async_client.post(
        "/api/world/canon/admissions",
        json={
            "novel_id": novel_id,
            "decision_id": str(uuid.uuid4()),
            "expected_previous_head": c0_id,
            "confirmed": True,
            "input": preview["normalized_input"],
        },
    )
    assert admitted.status_code == 200
    assert admitted.json()["version_number"] == 1
    assert admitted.json()["changes"]["resource_count"] == 1
