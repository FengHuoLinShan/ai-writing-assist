from __future__ import annotations

import uuid

import pytest
from pydantic import TypeAdapter
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import func, select, update

from core.errors import ConflictError, ValidationError
from modules.world.authority_schemas import (
    EntityProfileFieldSchemaV1,
    EntityProfileRelationSchemaV1,
    EntityProfileTemplateAdoptRequest,
    EntityProfileTemplateCreateRequest,
    EntityProfileTemplateRevisionCreateRequest,
    PointScopeV1,
    ResourceRevisionRefV1,
    StatementValueV1,
    WorldCanonInitializePreviewRequest,
    WorldCanonInitializeRequest,
    WorldCanonManifestV1,
    WorldCanonRevertRequest,
    WorldFormalQueryRequest,
    WorldPromotionApplyRequest,
    WorldPromotionCandidateV1,
    WorldPromotionPreviewRequest,
)
from modules.world.models import (
    CoreEntity,
    EntityRevision,
    WorldAssertion,
    WorldBiblePageRevision,
    WorldCanonHead,
    WorldCanonRevision,
)
from modules.world.schemas import (
    CoreEntityCreate,
    CoreEntityUpdate,
    WorldBiblePageCreate,
    WorldBiblePageUpdate,
    WorldBibleSection,
    WorldProfileUpsertRequest,
)
from modules.world.services.core.entity_service import WorldEntityService
from modules.world.services.worldbuilding.profile_service import WorldProfileService
from modules.world.services.worldbuilding.world_authority_service import (
    WorldAuthorityService,
)
from modules.world.services.worldbuilding.world_bible_lifecycle_service import (
    WorldBibleLifecycleService,
)
from modules.world.tests.helpers import _create_project


def test_closed_authority_wires_reject_mutable_or_unknown_values() -> None:
    with pytest.raises(PydanticValidationError):
        ResourceRevisionRefV1(
            resource_kind="world_bible_page",
            resource_id=uuid.uuid4(),
            revision_kind="entity_revision",
            revision_id=uuid.uuid4(),
            selector="whole",
        )
    with pytest.raises(PydanticValidationError):
        ResourceRevisionRefV1(
            resource_kind="world_bible_page",
            resource_id=uuid.uuid4(),
            revision_kind="world_bible_page_revision",
            revision_id=uuid.uuid4(),
            selector="latest",
        )
    with pytest.raises(PydanticValidationError):
        TypeAdapter(StatementValueV1).validate_python(
            {"kind": "statement_ref", "version": 1, "digest": "a" * 64}
        )
    with pytest.raises(PydanticValidationError):
        TypeAdapter(StatementValueV1).validate_python(
            {
                "kind": "typed_scalar",
                "version": 1,
                "subject_entity_id": str(uuid.uuid4()),
                "field_key": "height",
                "value_type": "decimal",
                "value": "01.0",
            }
        )


@pytest.mark.asyncio
async def test_c0_is_empty_scoped_and_project_creation_initializes_it(
    async_client,
    db_session,
) -> None:
    created = await async_client.post("/api/projects", json={"title": "Canon C0"})
    assert created.status_code == 201
    novel_id = created.json()["id"]

    response = await async_client.get("/api/world/canon", params={"novel_id": novel_id})

    assert response.status_code == 200
    assert response.json()["resource_count"] == 0
    assert response.json()["assertion_count"] == 0
    assert response.json()["parent_id"] is None
    assert response.json()["head_version"] == 0
    head_count = await db_session.scalar(
        select(func.count())
        .select_from(WorldCanonHead)
        .where(WorldCanonHead.novel_id == uuid.UUID(novel_id))
    )
    assert head_count == 1


@pytest.mark.asyncio
async def test_page_publish_selects_exact_revision_without_promoting_facts(
    db_session,
    project_novel_id: str,
) -> None:
    lifecycle = WorldBibleLifecycleService()
    authority = WorldAuthorityService()
    c0 = await authority.current_summary(db_session, project_novel_id)

    page = await lifecycle.create_page(
        db_session,
        WorldBiblePageCreate(
            novel_id=project_novel_id,
            title="北境律法",
            page_type="rule",
            status="canonical",
            free_text="冬季禁航。",
        ),
    )
    current = await authority.current_summary(db_session, project_novel_id)
    c1 = await db_session.get(WorldCanonRevision, current.canon_revision_id)
    assert c1 is not None
    manifest = WorldCanonManifestV1.model_validate(c1.manifest_json)
    revision = await db_session.scalar(
        select(WorldBiblePageRevision).where(
            WorldBiblePageRevision.page_id == uuid.UUID(page.id)
        )
    )

    assert current.parent_id == c0.canon_revision_id
    assert current.head_version == 1
    assert current.resource_count == 1
    assert current.assertion_count == 0
    assert manifest.resources[0].revision_id == revision.id
    assert manifest.resources[0].selector == "whole"
    assert c0.resource_count == 0
    assert await db_session.scalar(select(func.count()).select_from(WorldAssertion)) == 0


@pytest.mark.asyncio
async def test_archiving_page_moves_its_exact_revision_to_inactive_manifest(
    db_session,
    project_novel_id: str,
) -> None:
    lifecycle = WorldBibleLifecycleService()
    page = await lifecycle.create_page(
        db_session,
        WorldBiblePageCreate(
            novel_id=project_novel_id,
            title="旧律",
            status="canonical",
        ),
    )

    await lifecycle.update_page(
        db_session,
        project_novel_id,
        page.id,
        WorldBiblePageUpdate(status="archived"),
    )

    head = await db_session.get(WorldCanonHead, uuid.UUID(project_novel_id))
    canon = await db_session.get(WorldCanonRevision, head.canon_revision_id)
    manifest = WorldCanonManifestV1.model_validate(canon.manifest_json)
    page_revision_id = await db_session.scalar(
        select(WorldBiblePageRevision.id)
        .where(WorldBiblePageRevision.page_id == uuid.UUID(page.id))
        .order_by(WorldBiblePageRevision.version_number.desc())
    )
    assert manifest.resources == []
    assert [ref.revision_id for ref in manifest.inactive_resource_refs] == [
        page_revision_id
    ]


@pytest.mark.asyncio
async def test_entity_name_create_and_rename_advance_exact_authority(
    db_session,
    project_novel_id: str,
) -> None:
    service = WorldEntityService()
    entity = await service.create(
        db_session,
        project_novel_id,
        CoreEntityCreate(entity_type="location", name="旧港"),
    )
    first_head = await db_session.get(
        WorldCanonHead, uuid.UUID(project_novel_id)
    )
    first_canon_id = first_head.canon_revision_id

    await service.update(
        db_session,
        entity.id,
        CoreEntityUpdate(name="新港"),
        novel_id=project_novel_id,
    )

    head = await db_session.get(WorldCanonHead, uuid.UUID(project_novel_id))
    current = await db_session.get(WorldCanonRevision, head.canon_revision_id)
    previous = await db_session.get(WorldCanonRevision, first_canon_id)
    manifest = WorldCanonManifestV1.model_validate(current.manifest_json)
    previous_manifest = WorldCanonManifestV1.model_validate(previous.manifest_json)
    assertion = await db_session.get(
        WorldAssertion, manifest.selected_assertion_ids[0]
    )
    entity_revision = await db_session.get(
        EntityRevision, manifest.resources[0].revision_id
    )

    assert head.canon_revision_id != first_canon_id
    assert assertion.statement_payload_json["kind"] == "name"
    assert assertion.statement_payload_json["value"] == "新港"
    assert previous_manifest.selected_assertion_ids != manifest.selected_assertion_ids
    assert manifest.resources[0].resource_kind == "core_entity"
    assert entity_revision.snapshot["name"] == "新港"


@pytest.mark.asyncio
async def test_generic_blank_draft_creates_no_referent_or_assertion(
    db_session,
    project_novel_id: str,
) -> None:
    authority = WorldAuthorityService()
    c0 = await authority.current_summary(db_session, project_novel_id)

    await WorldBibleLifecycleService().create_page(
        db_session,
        WorldBiblePageCreate(
            novel_id=project_novel_id,
            page_type="custom",
            title="未命名资料",
            status="draft",
        ),
    )

    current = await authority.current_summary(db_session, project_novel_id)
    assert current.canon_revision_id == c0.canon_revision_id
    assert current.resource_count == 0
    assert current.assertion_count == 0


@pytest.mark.asyncio
async def test_template_default_is_documentary_until_explicit_b_promotion(
    db_session,
    project_novel_id: str,
) -> None:
    authority = WorldAuthorityService()
    profiles = WorldProfileService()
    entities = WorldEntityService()
    entity = await entities.create(
        db_session,
        project_novel_id,
        CoreEntityCreate(entity_type="starship", name="远航号"),
    )
    template = await profiles.create_template(
        db_session,
        EntityProfileTemplateCreateRequest(
            novel_id=project_novel_id,
            profile_type="starship",
            fields=[
                EntityProfileFieldSchemaV1(
                    key="crew_count",
                    label="船员数",
                    value_type="integer",
                    default=30,
                )
            ],
        ),
    )
    before_adopt = await authority.current_summary(db_session, project_novel_id)
    await profiles.adopt_template(
        db_session,
        project_novel_id,
        str(template.template_id),
        EntityProfileTemplateAdoptRequest(
            revision_id=template.revision_id,
            confirmed=True,
        ),
    )
    profile = await profiles.upsert_profile(
        db_session,
        project_novel_id,
        entity.id,
        WorldProfileUpsertRequest(data_json={}),
    )
    after_default = await authority.current_summary(db_session, project_novel_id)

    assert profile.data_json == {"crew_count": 30}
    assert after_default.canon_revision_id == before_adopt.canon_revision_id
    assert after_default.assertion_count == 1  # primary Name only

    revision_v2 = await profiles.add_template_revision(
        db_session,
        project_novel_id,
        str(template.template_id),
        EntityProfileTemplateRevisionCreateRequest(
            fields=[
                EntityProfileFieldSchemaV1(
                    key="capacity",
                    label="载重",
                    value_type="integer",
                    default=40,
                )
            ]
        ),
    )
    await profiles.adopt_template(
        db_session,
        project_novel_id,
        str(template.template_id),
        EntityProfileTemplateAdoptRequest(
            revision_id=revision_v2.revision_id,
            confirmed=True,
        ),
    )
    old_profile = await profiles.upsert_profile(
        db_session,
        project_novel_id,
        entity.id,
        WorldProfileUpsertRequest(data_json={"crew_count": 31}),
    )
    new_entity = await entities.create(
        db_session,
        project_novel_id,
        CoreEntityCreate(entity_type="starship", name="归航号"),
    )
    new_profile = await profiles.upsert_profile(
        db_session,
        project_novel_id,
        new_entity.id,
        WorldProfileUpsertRequest(data_json={}),
    )

    assert old_profile.data_json == {"crew_count": 31}
    assert old_profile.extra_json["_schema_revision_ref_v1"]["revision_id"] == str(
        template.revision_id
    )
    assert new_profile.data_json == {"capacity": 40}
    assert new_profile.extra_json["_schema_revision_ref_v1"]["revision_id"] == str(
        revision_v2.revision_id
    )


@pytest.mark.asyncio
async def test_b_promotion_and_formal_query_replay_signed_ground_facts(
    db_session,
    project_novel_id: str,
) -> None:
    authority = WorldAuthorityService()
    profiles = WorldProfileService()
    entity = await WorldEntityService().create(
        db_session,
        project_novel_id,
        CoreEntityCreate(entity_type="starship", name="远航号"),
    )
    template = await profiles.create_template(
        db_session,
        EntityProfileTemplateCreateRequest(
            novel_id=project_novel_id,
            profile_type="starship",
            fields=[
                EntityProfileFieldSchemaV1(
                    key="crew_count",
                    label="船员数",
                    value_type="integer",
                )
            ],
            relations=[
                EntityProfileRelationSchemaV1(
                    relation_type="docked_at",
                    label="停靠于",
                    relation_kind="spatial",
                    target_entity_types=["location"],
                )
            ],
        ),
    )
    harbor = await WorldEntityService().create(
        db_session,
        project_novel_id,
        CoreEntityCreate(entity_type="location", name="北港"),
    )
    page = await WorldBibleLifecycleService().create_page(
        db_session,
        WorldBiblePageCreate(
            novel_id=project_novel_id,
            title="远航号编制",
            status="canonical",
            free_text="核定船员三十人。",
        ),
    )
    page_revision = await db_session.scalar(
        select(WorldBiblePageRevision)
        .where(WorldBiblePageRevision.page_id == uuid.UUID(page.id))
        .order_by(WorldBiblePageRevision.version_number.desc())
    )
    statement = TypeAdapter(StatementValueV1).validate_python(
        {
            "kind": "typed_scalar",
            "version": 1,
            "subject_entity_id": entity.id,
            "field_key": "crew_count",
            "value_type": "integer",
            "value": 30,
        }
    )
    schema_ref = ResourceRevisionRefV1(
        resource_kind="entity_profile_template",
        resource_id=template.template_id,
        revision_kind="entity_profile_template_revision",
        revision_id=template.revision_id,
        selector="whole",
    )
    source_ref = ResourceRevisionRefV1(
        resource_kind="world_bible_page",
        resource_id=uuid.UUID(page.id),
        revision_kind="world_bible_page_revision",
        revision_id=page_revision.id,
        selector="free_text",
    )
    positive = WorldPromotionCandidateV1(
        statement=statement,
        schema_revision_ref=schema_ref,
        source_revision_ref=source_ref,
    )
    preview = await authority.promotion_preview(
        db_session,
        project_novel_id,
        WorldPromotionPreviewRequest(items=[positive]),
    )
    promoted = await authority.promote(
        db_session,
        project_novel_id,
        WorldPromotionApplyRequest(
            items=[positive],
            expected_previous_head=preview.expected_previous_head,
            preview_digest=preview.preview_digest,
            confirmed=True,
        ),
    )
    true_result = await authority.formal_query(
        db_session,
        project_novel_id,
        WorldFormalQueryRequest(statement=statement),
    )
    negative = positive.model_copy(update={"polarity": "negative"})
    negative_preview = await authority.promotion_preview(
        db_session,
        project_novel_id,
        WorldPromotionPreviewRequest(items=[negative]),
    )
    await authority.promote(
        db_session,
        project_novel_id,
        WorldPromotionApplyRequest(
            items=[negative],
            expected_previous_head=negative_preview.expected_previous_head,
            preview_digest=negative_preview.preview_digest,
            confirmed=True,
        ),
    )
    both = await authority.formal_query(
        db_session,
        project_novel_id,
        WorldFormalQueryRequest(statement=statement),
    )
    replay = await authority.formal_query(
        db_session,
        project_novel_id,
        WorldFormalQueryRequest(
            statement=statement,
            canon_revision_id=promoted.canon_revision_id,
        ),
    )
    unknown_statement = statement.model_copy(update={"value": 31})
    unknown = await authority.formal_query(
        db_session,
        project_novel_id,
        WorldFormalQueryRequest(statement=unknown_statement),
    )
    before_invalid = await authority.current_summary(db_session, project_novel_id)
    invalid_item = positive.model_copy(
        update={"statement": statement.model_copy(update={"field_key": "fuel"})}
    )
    with pytest.raises(ValidationError):
        await authority.promotion_preview(
            db_session,
            project_novel_id,
            WorldPromotionPreviewRequest(items=[positive, invalid_item]),
        )
    after_invalid = await authority.current_summary(db_session, project_novel_id)

    false_statement = statement.model_copy(update={"value": 31})
    false_candidate = positive.model_copy(
        update={"statement": false_statement, "polarity": "negative"}
    )
    false_preview = await authority.promotion_preview(
        db_session,
        project_novel_id,
        WorldPromotionPreviewRequest(items=[false_candidate]),
    )
    await authority.promote(
        db_session,
        project_novel_id,
        WorldPromotionApplyRequest(
            items=[false_candidate],
            expected_previous_head=false_preview.expected_previous_head,
            preview_digest=false_preview.preview_digest,
            confirmed=True,
        ),
    )
    false_result = await authority.formal_query(
        db_session,
        project_novel_id,
        WorldFormalQueryRequest(statement=false_statement),
    )
    relation_statement = TypeAdapter(StatementValueV1).validate_python(
        {
            "kind": "binary_relation",
            "version": 1,
            "source_entity_id": entity.id,
            "target_entity_id": harbor.id,
            "relation_kind": "spatial",
            "relation_type": "docked_at",
        }
    )
    relation_candidate = positive.model_copy(update={"statement": relation_statement})
    relation_preview = await authority.promotion_preview(
        db_session,
        project_novel_id,
        WorldPromotionPreviewRequest(items=[relation_candidate]),
    )
    await authority.promote(
        db_session,
        project_novel_id,
        WorldPromotionApplyRequest(
            items=[relation_candidate],
            expected_previous_head=relation_preview.expected_previous_head,
            preview_digest=relation_preview.preview_digest,
            confirmed=True,
        ),
    )
    relation_result = await authority.formal_query(
        db_session,
        project_novel_id,
        WorldFormalQueryRequest(statement=relation_statement),
    )
    context = await authority.canon_context(
        db_session,
        project_novel_id,
        entity_ids=[entity.id],
    )
    truncated = await authority.formal_query(
        db_session,
        project_novel_id,
        WorldFormalQueryRequest(statement=statement, max_assertions=1),
    )
    unsupported = await authority.formal_query(
        db_session,
        project_novel_id,
        WorldFormalQueryRequest(
            statement=statement,
            time_scope=PointScopeV1(time_ref=source_ref, phase="at"),
        ),
    )

    assert true_result.verdict == "true"
    assert both.verdict == "both"
    assert replay.verdict == "true"
    assert unknown.verdict == "unknown"
    assert before_invalid.canon_revision_id == after_invalid.canon_revision_id
    assert false_result.verdict == "false"
    assert relation_result.verdict == "true"
    assert "crew_count = 30" in context.entities[0].summary
    assert "docked_at → 北港" in context.entities[0].summary
    assert context.entities[0].related_entity_ids == [harbor.id]
    assert truncated.product_verdict == "incomplete"
    assert truncated.obligations.execution == "budget-truncated"
    assert unsupported.obligations.execution == "unsupported-family"
    assert both.obligations.source_scope == "open"
    assert both.obligations.execution == "complete"
    assert both.obligations.model_dump(mode="json", by_alias=True) == {
        "S": "open",
        "F": "machine",
        "I": "machine",
        "X": "complete",
    }


@pytest.mark.asyncio
async def test_canon_context_is_exact_and_ignores_mutable_legacy_drift(
    db_session,
    project_novel_id: str,
) -> None:
    authority = WorldAuthorityService()
    entity = await WorldEntityService().create(
        db_session,
        project_novel_id,
        CoreEntityCreate(
            entity_type="location",
            name="北港",
            summary="结冰期仍可靠岸。",
        ),
    )
    await WorldBibleLifecycleService().create_page(
        db_session,
        WorldBiblePageCreate(
            novel_id=project_novel_id,
            title="北港水文",
            status="canonical",
            sections_json=[
                WorldBibleSection(
                    section_id="winter",
                    title="冬季",
                    body_markdown="港池中央不结冰。",
                )
            ],
        ),
    )
    first = await authority.canon_context(
        db_session,
        project_novel_id,
        reveal_mode="author_full",
    )
    entity_item = next(
        item for item in first.entities if item.entity_id == entity.id
    )
    page_item = next(
        item for item in first.entities if item.entity_type == "world_bible_page"
    )

    await db_session.execute(
        update(CoreEntity)
        .where(CoreEntity.id == uuid.UUID(entity.id))
        .values(name="漂移名称", summary="未封存的新摘要")
    )
    db_session.add(
        CoreEntity(
            novel_id=uuid.UUID(project_novel_id),
            entity_type="location",
            name="仅存在于旧表",
            status="canonical",
        )
    )
    await db_session.flush()
    replay = await authority.canon_context(
        db_session,
        project_novel_id,
        canon_revision_id=first.canon_revision_id,
        reveal_mode="author_full",
    )

    assert first.canon_revision_id
    assert first.canon_manifest_digest
    assert entity_item.name == "北港"
    assert entity_item.summary == "结冰期仍可靠岸。"
    assert entity_item.source_revision_id
    assert page_item.summary == "冬季\n港池中央不结冰。"
    assert [(item.name, item.summary) for item in replay.entities] == [
        (item.name, item.summary) for item in first.entities
    ]
    assert all(item.name != "仅存在于旧表" for item in replay.entities)


@pytest.mark.asyncio
async def test_history_replay_and_revert_append_without_moving_back(
    db_session,
    project_novel_id: str,
) -> None:
    lifecycle = WorldBibleLifecycleService()
    authority = WorldAuthorityService()
    page = await lifecycle.create_page(
        db_session,
        WorldBiblePageCreate(
            novel_id=project_novel_id,
            title="第一版",
            status="canonical",
        ),
    )
    first = await authority.current_summary(db_session, project_novel_id)
    await lifecycle.update_page(
        db_session,
        project_novel_id,
        page.id,
        WorldBiblePageUpdate(title="第二版"),
    )
    second = await authority.current_summary(db_session, project_novel_id)

    viewed = await authority.revision_summary(
        db_session, project_novel_id, first.canon_revision_id
    )
    unchanged = await authority.current_summary(db_session, project_novel_id)
    reverted = await authority.revert(
        db_session,
        project_novel_id,
        WorldCanonRevertRequest(
            expected_previous_head=second.canon_revision_id,
            target_canon_revision_id=first.canon_revision_id,
            confirmed=True,
        ),
    )

    assert viewed.current is False
    assert unchanged.canon_revision_id == second.canon_revision_id
    assert reverted.parent_id == second.canon_revision_id
    assert reverted.canon_revision_id not in {
        first.canon_revision_id,
        second.canon_revision_id,
    }
    first_row = await db_session.get(WorldCanonRevision, first.canon_revision_id)
    reverted_row = await db_session.get(WorldCanonRevision, reverted.canon_revision_id)
    assert first_row.manifest_digest == reverted_row.manifest_digest


@pytest.mark.asyncio
async def test_initialize_preview_is_exact_scoped_and_stale_safe(
    db_session,
) -> None:
    novel_id = str(uuid.uuid4())
    other_id = str(uuid.uuid4())
    await _create_project(db_session, novel_id)
    await _create_project(db_session, other_id)
    lifecycle = WorldBibleLifecycleService()
    authority = WorldAuthorityService()
    foreign = await lifecycle.create_page(
        db_session,
        WorldBiblePageCreate(
            novel_id=other_id,
            title="别处资料",
            status="canonical",
        ),
    )
    foreign_revision = await db_session.scalar(
        select(WorldBiblePageRevision).where(
            WorldBiblePageRevision.page_id == uuid.UUID(foreign.id)
        )
    )

    with pytest.raises(ValidationError) as caught:
        await authority.initialize_preview(
            db_session,
            novel_id,
            WorldCanonInitializePreviewRequest(page_revision_ids=[foreign_revision.id]),
        )
    assert caught.value.code == "world_canon_invalid_reference"

    preview = await authority.initialize_preview(
        db_session,
        novel_id,
        WorldCanonInitializePreviewRequest(page_revision_ids=[]),
    )
    await authority.initialize(
        db_session,
        novel_id,
        WorldCanonInitializeRequest(
            page_revision_ids=[],
            expected_previous_head=preview.expected_previous_head,
            preview_digest=preview.preview_digest,
            confirmed=True,
        ),
    )
    with pytest.raises(ConflictError):
        await authority.initialize(
            db_session,
            novel_id,
            WorldCanonInitializeRequest(
                page_revision_ids=[],
                expected_previous_head=preview.expected_previous_head,
                preview_digest=preview.preview_digest,
                confirmed=True,
            ),
        )


@pytest.mark.asyncio
async def test_tampered_receipt_fails_closed(db_session, project_novel_id: str) -> None:
    authority = WorldAuthorityService()
    current = await authority.current_summary(db_session, project_novel_id)
    await db_session.execute(
        update(WorldCanonRevision)
        .where(WorldCanonRevision.id == current.canon_revision_id)
        .values(admission_receipt_json={})
        .execution_options(synchronize_session=False)
    )
    db_session.expire_all()

    invalid = await authority.formal_query(
        db_session,
        project_novel_id,
        WorldFormalQueryRequest(
            statement={
                "kind": "name",
                "version": 1,
                "subject_entity_id": str(uuid.uuid4()),
                "value": "任意名称",
                "name_kind": "primary",
            }
        ),
    )
    assert invalid.product_verdict == "invalid"
    assert invalid.obligations.execution == "invalid-context"

    with pytest.raises(ValidationError) as caught:
        await authority.revision_summary(
            db_session, project_novel_id, current.canon_revision_id
        )
    assert caught.value.code == "world_canon_manifest_not_closed"


@pytest.mark.asyncio
async def test_immutable_canon_revision_rejects_orm_update(
    db_session, project_novel_id: str
) -> None:
    authority = WorldAuthorityService()
    current = await authority.current_summary(db_session, project_novel_id)
    revision = await db_session.get(WorldCanonRevision, current.canon_revision_id)
    revision.manifest_digest = "0" * 64

    with pytest.raises(ValueError, match="immutable"):
        await db_session.flush()


@pytest.mark.asyncio
async def test_canon_openapi_is_narrow_and_separate_from_ask_world(async_client) -> None:
    schema = (await async_client.get("/api/openapi.json")).json()
    paths = schema["paths"]
    assert "/api/world/canon" in paths
    assert "/api/world/canon/initialize/preview" in paths
    assert "/api/world/canon/initialize" in paths
    assert "/api/world/canon/revert" in paths
    assert "/api/world/canon/{canon_revision_id}" in paths
    assert "/api/world/formal-query" in paths
    assert "/api/world/canon/promotions/preview" in paths
    assert "/api/world/canon/promotions" in paths
    assert "/api/world/profile-templates" in paths
