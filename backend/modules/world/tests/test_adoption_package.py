from __future__ import annotations

import hashlib
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ConflictError, ValidationError
from modules.account.context import bind_principal, reset_principal
from modules.account.contracts import AccountPrincipal
from modules.account.models import Account
from modules.project.schemas import ProjectCreate
from modules.project.services import ProjectService
from modules.world.contracts import (
    PostImportSceneSourceContract,
    PostImportWorldAdoptionRequestContract,
)
from modules.world.models import (
    WorldBiblePage,
    WorldBiblePageDraft,
    WorldBiblePageRevision,
)
from modules.world.models.core import CoreEntity, EntityRelation
from modules.world.schemas import (
    CoreEntityCreate,
    EntityRelationCreate,
    WorldAdoptionPackageApplyRequest,
    WorldAdoptionPackagePayload,
    WorldAdoptionPackageSaveRequest,
    WorldBiblePageCreate,
    WorldBiblePageUpdate,
    WorldCoreCheckpointPayload,
    WorldCoreCheckpointSaveRequest,
)
from modules.world.services.core.entity_relation_service import EntityRelationService
from modules.world.services.core.entity_service import WorldEntityService
from modules.world.services.worldbuilding.adoption_package_service import (
    WorldAdoptionPackageService,
)
from modules.world.services.worldbuilding.world_bible_lifecycle_service import (
    WorldBibleLifecycleService,
)
from shared.target_ref import TargetRef


@pytest.mark.asyncio
async def test_package_preview_apply_is_idempotent_and_ignores_open_items(
    db_session: AsyncSession,
    project_novel_id: str,
) -> None:
    service = WorldAdoptionPackageService()
    revisions_before = (
        (await db_session.execute(select(WorldBiblePageRevision))).scalars().all()
    )
    manifest = hashlib.sha256(b"manifest").hexdigest()
    checkpoint = await service.save_checkpoint(
        db_session,
        WorldCoreCheckpointSaveRequest(
            novel_id=project_novel_id,
            checkpoint=WorldCoreCheckpointPayload(
                schema_version="world_core_checkpoint.v1",
                round_no=0,
                action="consolidate",
                source_manifest_hash=manifest,
                seeds=[],
            ),
        ),
    )
    package = WorldAdoptionPackagePayload(
        schema_version="world_adoption_package.v1",
        checkpoint_suggestion_id=checkpoint.id,
        checkpoint_manifest_hash=manifest,
        source_manifest_hash=manifest,
        items=[
            {
                "item_key": "city",
                "kind": "core_entity",
                "disposition": "include",
                "authority_kind": "author_seed",
                "source_refs": [_source_ref(manifest)],
                "payload": {
                    "operation": "create",
                    "entity": {"entity_type": "location", "name": "雾港"},
                },
            },
            {
                "item_key": "unused",
                "kind": "core_entity",
                "disposition": "open",
                "authority_kind": "author_seed",
                "source_refs": [],
                "payload": {
                    "operation": "create",
                    "entity": {"entity_type": "concept", "name": "不应写入"},
                },
            },
            {
                "item_key": "guild",
                "kind": "core_entity",
                "disposition": "include",
                "authority_kind": "author_seed",
                "source_refs": [_source_ref(manifest)],
                "payload": {
                    "operation": "create",
                    "entity": {"entity_type": "organization", "name": "潮汐同盟"},
                },
            },
            {
                "item_key": "alliance",
                "kind": "entity_relation",
                "disposition": "include",
                "authority_kind": "generated_bridge",
                "source_refs": [_source_ref(manifest)],
                "payload": {
                    "source_ref": "local:city",
                    "target_ref": "local:guild",
                    "relation_type": "governed_by",
                },
            },
        ],
    )
    saved = await service.save(
        db_session,
        WorldAdoptionPackageSaveRequest(novel_id=project_novel_id, package=package),
    )
    preview = await service.preview(db_session, project_novel_id, saved.id)
    preview_alliance = next(
        item for item in preview.canon_diff if item["item_key"] == "alliance"
    )
    assert preview_alliance["action"] == "create"
    assert preview.omissions == []
    assert [item["item_key"] for item in preview.canon_diff] == [
        "city",
        "guild",
        "alliance",
    ]

    applied = await service.apply(
        db_session,
        project_novel_id,
        saved.id,
        WorldAdoptionPackageApplyRequest(
            expected_preview_hash=preview.expected_preview_hash
        ),
    )
    assert applied.status == "accepted"
    assert applied.result_ref_json["local_ref_map"].keys() == {
        "city",
        "guild",
        "alliance",
    }
    assert len(applied.result_ref_json["result_refs"]) == 3
    repeated = await service.apply(
        db_session,
        project_novel_id,
        saved.id,
        WorldAdoptionPackageApplyRequest(
            expected_preview_hash=preview.expected_preview_hash
        ),
    )
    assert repeated.result_ref_json == applied.result_ref_json
    revisions_after = (
        (await db_session.execute(select(WorldBiblePageRevision))).scalars().all()
    )
    assert len(revisions_after) == len(revisions_before)


def test_package_rejects_unknown_or_untyped_item_payload() -> None:
    manifest = hashlib.sha256(b"manifest").hexdigest()
    with pytest.raises(ValueError, match="extra"):
        WorldAdoptionPackagePayload(
            schema_version="world_adoption_package.v1",
            source_manifest_hash=manifest,
            items=[
                {
                    "item_key": "edge",
                    "kind": "entity_relation",
                    "authority_kind": "generated_bridge",
                    "source_refs": [_source_ref(manifest)],
                    "payload": {
                        "source_ref": "local:a",
                        "target_ref": "local:b",
                        "relation_type": "allied_with",
                        "unknown": "no",
                    },
                }
            ],
        )
    with pytest.raises(ValueError, match="extra"):
        WorldAdoptionPackagePayload(
            schema_version="world_adoption_package.v1",
            source_manifest_hash=manifest,
            items=[
                {
                    "item_key": "seed",
                    "kind": "core_entity",
                    "authority_kind": "author_seed",
                    "source_refs": [{**_source_ref(manifest), "unknown": "no"}],
                    "payload": {
                        "operation": "create",
                        "entity": {"entity_type": "location", "name": "雾港"},
                    },
                }
            ],
        )


@pytest.mark.asyncio
async def test_promote_rejects_server_baseline_content_drift(
    db_session: AsyncSession,
    project_novel_id: str,
) -> None:
    manifest = hashlib.sha256(b"baseline").hexdigest()
    entity = await WorldEntityService().create(
        db_session,
        project_novel_id,
        CoreEntityCreate(
            entity_type="location",
            name="旧雾港",
            summary="before",
            status="candidate",
            force_create=True,
        ),
    )
    service = WorldAdoptionPackageService()
    saved = await service.save(
        db_session,
        WorldAdoptionPackageSaveRequest(
            novel_id=project_novel_id,
            package=WorldAdoptionPackagePayload(
                schema_version="world_adoption_package.v1",
                source_manifest_hash=manifest,
                items=[
                    {
                        "item_key": "promote-city",
                        "kind": "core_entity",
                        "disposition": "include",
                        "authority_kind": "canonical_baseline",
                        "source_refs": [_source_ref(manifest)],
                        "baseline": {"expected_status": "candidate"},
                        "payload": {"operation": "promote", "entity_id": entity.id},
                    }
                ],
            ),
        ),
    )
    preview = await service.preview(db_session, project_novel_id, saved.id)
    stored = (
        await db_session.execute(
            select(CoreEntity).where(CoreEntity.id == uuid.UUID(entity.id))
        )
    ).scalar_one()
    stored.summary = "changed without changing status"
    await db_session.flush()

    with pytest.raises(ConflictError, match="preview again"):
        await service.apply(
            db_session,
            project_novel_id,
            saved.id,
            WorldAdoptionPackageApplyRequest(
                expected_preview_hash=preview.expected_preview_hash
            ),
        )


@pytest.mark.asyncio
async def test_promote_writes_provenance_and_is_idempotent(
    db_session: AsyncSession,
    project_novel_id: str,
) -> None:
    manifest = hashlib.sha256(b"promote-success").hexdigest()
    candidate = await WorldEntityService().create(
        db_session,
        project_novel_id,
        CoreEntityCreate(
            entity_type="location",
            name="待采用港",
            content_json={"_meta": {"keep": "value"}},
            status="candidate",
            force_create=True,
        ),
    )
    service = WorldAdoptionPackageService()
    saved = await service.save(
        db_session,
        WorldAdoptionPackageSaveRequest(
            novel_id=project_novel_id,
            package=WorldAdoptionPackagePayload(
                schema_version="world_adoption_package.v1",
                source_manifest_hash=manifest,
                items=[
                    {
                        "item_key": "promote-port",
                        "kind": "core_entity",
                        "disposition": "include",
                        "authority_kind": "canonical_baseline",
                        "source_refs": [_source_ref(manifest)],
                        "baseline": {"expected_status": "candidate"},
                        "payload": {"operation": "promote", "entity_id": candidate.id},
                    }
                ],
            ),
        ),
    )
    preview = await service.preview(db_session, project_novel_id, saved.id)
    applied = await service.apply(
        db_session,
        project_novel_id,
        saved.id,
        WorldAdoptionPackageApplyRequest(
            expected_preview_hash=preview.expected_preview_hash
        ),
    )
    entity = (
        await db_session.execute(
            select(CoreEntity).where(CoreEntity.id == uuid.UUID(candidate.id))
        )
    ).scalar_one()
    assert entity.status == "canonical"
    assert entity.approved_by == applied.result_ref_json["authorization_actor"]
    assert entity.content_json["_meta"]["keep"] == "value"
    assert entity.content_json["_meta"]["world_adoption"]["package_id"] == saved.id
    assert applied.result_ref_json["local_ref_map"] == {"promote-port": candidate.id}
    repeated = await service.apply(
        db_session,
        project_novel_id,
        saved.id,
        WorldAdoptionPackageApplyRequest(
            expected_preview_hash=preview.expected_preview_hash
        ),
    )
    assert repeated.result_ref_json == applied.result_ref_json


@pytest.mark.asyncio
async def test_package_creates_entity_and_publishes_new_world_bible_page(
    db_session: AsyncSession,
    project_novel_id: str,
) -> None:
    manifest = hashlib.sha256(b"package-page").hexdigest()
    local_hash = TargetRef(
        target_type="core_entity", target_id="local:city"
    ).target_hash()
    relation_hash = TargetRef(
        target_type="entity_relation", target_id="local:alliance"
    ).target_hash()
    service = WorldAdoptionPackageService()
    saved = await service.save(
        db_session,
        WorldAdoptionPackageSaveRequest(
            novel_id=project_novel_id,
            package=WorldAdoptionPackagePayload(
                schema_version="world_adoption_package.v1",
                source_manifest_hash=manifest,
                items=[
                    {
                        "item_key": "city",
                        "kind": "core_entity",
                        "disposition": "include",
                        "authority_kind": "author_seed",
                        "source_refs": [_source_ref(manifest)],
                        "payload": {
                            "operation": "create",
                            "entity": {"entity_type": "location", "name": "页面港"},
                        },
                    },
                    {
                        "item_key": "guild",
                        "kind": "core_entity",
                        "disposition": "include",
                        "authority_kind": "author_seed",
                        "source_refs": [_source_ref(manifest)],
                        "payload": {
                            "operation": "create",
                            "entity": {"entity_type": "organization", "name": "页面同盟"},
                        },
                    },
                    {
                        "item_key": "alliance",
                        "kind": "entity_relation",
                        "disposition": "include",
                        "authority_kind": "generated_bridge",
                        "source_refs": [_source_ref(manifest)],
                        "payload": {
                            "source_ref": "local:city",
                            "target_ref": "local:guild",
                            "relation_type": "allied_with",
                        },
                    },
                    {
                        "item_key": "city-page",
                        "kind": "world_bible_page",
                        "disposition": "include",
                        "authority_kind": "generated_bridge",
                        "source_refs": [_source_ref(manifest)],
                        "payload": {
                            "operation": "create",
                            "title": "页面港",
                            "page_type": "location",
                            "sections_json": [
                                {
                                    "section_id": "overview",
                                    "title": "local:city",
                                    "body_markdown": "页面港是潮汐都市。",
                                    "linked_asset_ref_hashes": [
                                        local_hash,
                                        relation_hash,
                                    ],
                                }
                            ],
                            "linked_asset_refs_json": [
                                {"target_type": "core_entity", "target_id": "local:city"},
                                {
                                    "target_type": "entity_relation",
                                    "target_id": "local:alliance",
                                },
                            ],
                            "claim_mappings": [
                                {
                                    "content_key": "overview",
                                    "claim": "页面港是潮汐都市。",
                                    "item_key": "city",
                                    "source_ref": _source_ref(manifest),
                                }
                            ],
                        },
                    },
                ],
            ),
        ),
    )
    preview = await service.preview(db_session, project_novel_id, saved.id)
    applied = await service.apply(
        db_session,
        project_novel_id,
        saved.id,
        WorldAdoptionPackageApplyRequest(
            expected_preview_hash=preview.expected_preview_hash
        ),
    )
    page_ref = next(
        item
        for item in applied.result_ref_json["result_refs"]
        if item["type"] == "world_bible_page"
    )
    assert page_ref["revision"] == "1"
    receipt_alliance = next(
        item
        for item in applied.result_ref_json["canon_diff"]
        if item["item_key"] == "alliance"
    )
    assert receipt_alliance["action"] == "create"
    page = (
        await db_session.execute(
            select(WorldBiblePage).where(WorldBiblePage.id == uuid.UUID(page_ref["id"]))
        )
    ).scalar_one()
    target_id = page.linked_asset_refs_json[0]["target_id"]
    relation_id = page.linked_asset_refs_json[1]["target_id"]
    assert target_id == applied.result_ref_json["local_ref_map"]["city"]
    assert relation_id == applied.result_ref_json["local_ref_map"]["alliance"]
    assert page.sections_json[0]["linked_asset_ref_hashes"] == [
        TargetRef(target_type="core_entity", target_id=target_id).target_hash(),
        TargetRef(target_type="entity_relation", target_id=relation_id).target_hash(),
    ]
    assert page.sections_json[0]["title"] == "local:city"
    repeated = await service.apply(
        db_session,
        project_novel_id,
        saved.id,
        WorldAdoptionPackageApplyRequest(
            expected_preview_hash=preview.expected_preview_hash
        ),
    )
    assert repeated.result_ref_json == applied.result_ref_json
    assert (
        len((await db_session.execute(select(WorldBiblePageRevision))).scalars().all())
        == 1
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["unmapped", "extra", "wrong_item"])
async def test_page_claim_coverage_rejects_invalid_blocks(
    db_session: AsyncSession, project_novel_id: str, mode: str
) -> None:
    manifest = hashlib.sha256(b"claims").hexdigest()
    mappings: list[dict] = []
    if mode == "extra":
        mappings = [
            {
                "content_key": "extra",
                "claim": "额外。",
                "item_key": "city",
                "source_ref": _source_ref(manifest),
            }
        ]
    if mode == "wrong_item":
        mappings = [
            {
                "content_key": "body",
                "claim": "港口。",
                "item_key": "page",
                "source_ref": _source_ref(manifest),
            }
        ]
    service = WorldAdoptionPackageService()
    saved = await service.save(
        db_session,
        WorldAdoptionPackageSaveRequest(
            novel_id=project_novel_id,
            package=WorldAdoptionPackagePayload(
                schema_version="world_adoption_package.v1",
                source_manifest_hash=manifest,
                items=[
                    {
                        "item_key": "city",
                        "kind": "core_entity",
                        "disposition": "include",
                        "authority_kind": "author_seed",
                        "source_refs": [_source_ref(manifest)],
                        "payload": {
                            "operation": "create",
                            "entity": {"entity_type": "location", "name": "不写入港"},
                        },
                    },
                    {
                        "item_key": "page",
                        "kind": "world_bible_page",
                        "disposition": "include",
                        "authority_kind": "generated_bridge",
                        "source_refs": [_source_ref(manifest)],
                        "payload": {
                            "operation": "create",
                            "title": "页",
                            "page_type": "location",
                            "sections_json": [
                                {
                                    "section_id": "body",
                                    "title": "B",
                                    "body_markdown": "港口。",
                                }
                            ],
                            "claim_mappings": mappings,
                        },
                    },
                ],
            ),
        ),
    )
    with pytest.raises(ValidationError):
        await service.preview(db_session, project_novel_id, saved.id)
    assert (
        await db_session.execute(select(CoreEntity).where(CoreEntity.name == "不写入港"))
    ).scalars().all() == []


@pytest.mark.asyncio
async def test_duplicate_create_rolls_back_package_and_keeps_it_retryable(
    db_session: AsyncSession,
    project_novel_id: str,
) -> None:
    manifest = hashlib.sha256(b"duplicate").hexdigest()
    service = WorldAdoptionPackageService()
    saved = await service.save(
        db_session,
        WorldAdoptionPackageSaveRequest(
            novel_id=project_novel_id,
            package=WorldAdoptionPackagePayload(
                schema_version="world_adoption_package.v1",
                source_manifest_hash=manifest,
                items=[
                    {
                        "item_key": "first",
                        "kind": "core_entity",
                        "disposition": "include",
                        "authority_kind": "author_seed",
                        "source_refs": [_source_ref(manifest)],
                        "payload": {
                            "operation": "create",
                            "entity": {"entity_type": "location", "name": "重复港"},
                        },
                    },
                    {
                        "item_key": "second",
                        "kind": "core_entity",
                        "disposition": "include",
                        "authority_kind": "author_seed",
                        "source_refs": [_source_ref(manifest)],
                        "payload": {
                            "operation": "create",
                            "entity": {"entity_type": "location", "name": "重复港"},
                        },
                    },
                ],
            ),
        ),
    )
    preview = await service.preview(db_session, project_novel_id, saved.id)
    with pytest.raises(ConflictError):
        async with db_session.begin_nested():
            await service.apply(
                db_session,
                project_novel_id,
                saved.id,
                WorldAdoptionPackageApplyRequest(
                    expected_preview_hash=preview.expected_preview_hash
                ),
            )
    remaining = (
        (
            await db_session.execute(
                select(CoreEntity).where(
                    CoreEntity.novel_id == uuid.UUID(project_novel_id),
                    CoreEntity.name == "重复港",
                )
            )
        )
        .scalars()
        .all()
    )
    assert remaining == []
    assert (await service.get(db_session, project_novel_id, saved.id)).status == "pending"


@pytest.mark.asyncio
async def test_existing_canonical_relation_is_receipted_without_mutation(
    db_session: AsyncSession,
    project_novel_id: str,
) -> None:
    source = await WorldEntityService().create(
        db_session,
        project_novel_id,
        CoreEntityCreate(entity_type="location", name="源港", force_create=True),
    )
    target = await WorldEntityService().create(
        db_session,
        project_novel_id,
        CoreEntityCreate(entity_type="location", name="目标港", force_create=True),
    )
    relation = await EntityRelationService().create(
        db_session,
        project_novel_id,
        EntityRelationCreate(
            source_id=source.id,
            target_id=target.id,
            relation_type="allied_with",
            description="original",
            review_meta={"keep": "unchanged"},
        ),
    )
    manifest = hashlib.sha256(b"existing-edge").hexdigest()
    service = WorldAdoptionPackageService()
    saved = await service.save(
        db_session,
        WorldAdoptionPackageSaveRequest(
            novel_id=project_novel_id,
            package=WorldAdoptionPackagePayload(
                schema_version="world_adoption_package.v1",
                source_manifest_hash=manifest,
                items=[
                    {
                        "item_key": "same-edge",
                        "kind": "entity_relation",
                        "disposition": "include",
                        "authority_kind": "generated_bridge",
                        "source_refs": [_source_ref(manifest)],
                        "payload": {
                            "source_ref": source.id,
                            "target_ref": target.id,
                            "relation_type": "allied_with",
                            "description": "must not overwrite",
                        },
                    }
                ],
            ),
        ),
    )
    preview = await service.preview(db_session, project_novel_id, saved.id)
    assert preview.canon_diff == [
        {"item_key": "same-edge", "kind": "entity_relation", "action": "existing_ref"}
    ]
    applied = await service.apply(
        db_session,
        project_novel_id,
        saved.id,
        WorldAdoptionPackageApplyRequest(
            expected_preview_hash=preview.expected_preview_hash
        ),
    )
    unchanged = (
        await db_session.execute(
            select(EntityRelation).where(EntityRelation.id == uuid.UUID(relation.id))
        )
    ).scalar_one()
    assert unchanged.description == "original"
    assert unchanged.review_meta == {"keep": "unchanged"}
    assert applied.result_ref_json["result_refs"] == [
        {
            "item_key": "same-edge",
            "type": "entity_relation",
            "id": relation.id,
            "action": "existing_ref",
        }
    ]
    assert applied.result_ref_json["canon_diff"] == preview.canon_diff


@pytest.mark.asyncio
async def test_candidate_relation_is_promoted_instead_of_recreated(
    db_session: AsyncSession,
    project_novel_id: str,
) -> None:
    source = await WorldEntityService().create(
        db_session,
        project_novel_id,
        CoreEntityCreate(entity_type="location", name="关系源", force_create=True),
    )
    target = await WorldEntityService().create(
        db_session,
        project_novel_id,
        CoreEntityCreate(entity_type="location", name="关系目标", force_create=True),
    )
    relation = await EntityRelationService().create(
        db_session,
        project_novel_id,
        EntityRelationCreate(
            source_id=source.id,
            target_id=target.id,
            relation_type="supports",
            description="待确认关系",
            status="candidate",
        ),
    )
    manifest = hashlib.sha256(b"promote-edge").hexdigest()
    package = WorldAdoptionPackagePayload(
        schema_version="world_adoption_package.v1",
        source_manifest_hash=manifest,
        items=[
            {
                "item_key": "source",
                "kind": "core_entity",
                "disposition": "include",
                "authority_kind": "canonical_baseline",
                "source_refs": [_source_ref(manifest)],
                "payload": {"operation": "existing_ref", "entity_id": source.id},
            },
            {
                "item_key": "target",
                "kind": "core_entity",
                "disposition": "include",
                "authority_kind": "canonical_baseline",
                "source_refs": [_source_ref(manifest)],
                "payload": {"operation": "existing_ref", "entity_id": target.id},
            },
            {
                "item_key": "edge",
                "kind": "entity_relation",
                "disposition": "include",
                "authority_kind": "manuscript_observation",
                "source_refs": [_source_ref(manifest)],
                "payload": {
                    "operation": "promote",
                    "relation_id": relation.id,
                    "source_ref": "local:source",
                    "target_ref": "local:target",
                    "relation_type": "supports",
                    "description": "待确认关系",
                },
            },
        ],
    )
    service = WorldAdoptionPackageService()
    saved = await service.save(
        db_session,
        WorldAdoptionPackageSaveRequest(novel_id=project_novel_id, package=package),
    )
    preview = await service.preview(db_session, project_novel_id, saved.id)
    await service.apply(
        db_session,
        project_novel_id,
        saved.id,
        WorldAdoptionPackageApplyRequest(
            expected_preview_hash=preview.expected_preview_hash
        ),
    )
    promoted = (
        await db_session.execute(
            select(EntityRelation).where(EntityRelation.id == uuid.UUID(relation.id))
        )
    ).scalar_one()
    assert promoted.status == "canonical"


@pytest.mark.asyncio
async def test_post_import_package_is_idempotent_and_keeps_existing_separate(
    db_session: AsyncSession,
    project_novel_id: str,
) -> None:
    workflow_id = str(uuid.uuid4())
    scene_id = str(uuid.uuid4())
    scene_hash = hashlib.sha256(b"scene").hexdigest()
    canonical = await WorldEntityService().create(
        db_session,
        project_novel_id,
        CoreEntityCreate(
            entity_type="location",
            name="已写入",
            force_create=True,
            content_json={"_meta": {"workflow_id": workflow_id, "scene_id": scene_id}},
        ),
    )
    candidate = await WorldEntityService().create(
        db_session,
        project_novel_id,
        CoreEntityCreate(
            entity_type="location",
            name="待确认",
            status="candidate",
            force_create=True,
            content_json={"_meta": {"workflow_id": workflow_id, "scene_id": scene_id}},
        ),
    )
    await EntityRelationService().create(
        db_session,
        project_novel_id,
        EntityRelationCreate(
            source_id=canonical.id,
            target_id=candidate.id,
            relation_type="supports",
            status="candidate",
            review_meta={"workflow_id": workflow_id, "scene_id": scene_id},
        ),
    )
    request = PostImportWorldAdoptionRequestContract(
        novel_id=project_novel_id,
        workflow_id=workflow_id,
        authorization_ref="2026-08-13T00:00:00Z",
        scene_sources=[
            PostImportSceneSourceContract(scene_id=scene_id, source_hash=scene_hash)
        ],
    )
    service = WorldAdoptionPackageService()
    first = await service.assemble_post_import(db_session, request)
    second = await service.assemble_post_import(db_session, request)
    assert first.created is True
    assert second == type(second)(suggestion_id=first.suggestion_id, created=False)
    package = (
        await service.get(db_session, project_novel_id, first.suggestion_id)
    ).payload_json
    entity_items = {
        item["payload"]["operation"]
        for item in package["items"]
        if item["kind"] == "core_entity"
    }
    assert entity_items == {"existing_ref", "promote"}
    assert any(
        item["payload"].get("operation") == "promote"
        for item in package["items"]
        if item["kind"] == "entity_relation"
    )


@pytest.mark.asyncio
async def test_context_marker_failure_rolls_back_package(
    db_session: AsyncSession,
    project_novel_id: str,
) -> None:
    async def fail_marker(
        _db: AsyncSession, _novel_id: str, _entity_ids: set[str]
    ) -> None:
        raise RuntimeError("marker unavailable")

    manifest = hashlib.sha256(b"marker-failure").hexdigest()
    service = WorldAdoptionPackageService(context_marker=fail_marker)
    saved = await service.save(
        db_session,
        WorldAdoptionPackageSaveRequest(
            novel_id=project_novel_id,
            package=WorldAdoptionPackagePayload(
                schema_version="world_adoption_package.v1",
                source_manifest_hash=manifest,
                items=[
                    {
                        "item_key": "marker-city",
                        "kind": "core_entity",
                        "disposition": "include",
                        "authority_kind": "author_seed",
                        "source_refs": [_source_ref(manifest)],
                        "payload": {
                            "operation": "create",
                            "entity": {"entity_type": "location", "name": "失效港"},
                        },
                    }
                ],
            ),
        ),
    )
    preview = await service.preview(db_session, project_novel_id, saved.id)
    with pytest.raises(RuntimeError, match="marker unavailable"):
        async with db_session.begin_nested():
            await service.apply(
                db_session,
                project_novel_id,
                saved.id,
                WorldAdoptionPackageApplyRequest(
                    expected_preview_hash=preview.expected_preview_hash
                ),
            )
    assert (
        await db_session.execute(select(CoreEntity).where(CoreEntity.name == "失效港"))
    ).scalars().all() == []
    assert (await service.get(db_session, project_novel_id, saved.id)).status == "pending"


@pytest.mark.asyncio
async def test_adoption_package_api_uses_project_scoped_artifacts(
    async_client: AsyncClient,
    project_novel_id: str,
) -> None:
    manifest = hashlib.sha256(b"api-manifest").hexdigest()
    checkpoint = await async_client.post(
        "/api/world/core-checkpoints",
        json={
            "novel_id": project_novel_id,
            "checkpoint": {
                "schema_version": "world_core_checkpoint.v1",
                "round_no": 3,
                "action": "consolidate",
                "source_manifest_hash": manifest,
                "seeds": [
                    {
                        "seed_key": "tide_city",
                        "source_ref": _source_ref(manifest),
                        "disposition": "included",
                    }
                ],
                "world_core": {
                    "author_seeds": [
                        {
                            "source_key": "conversation:seed:1",
                            "disposition": "included",
                        }
                    ],
                    "rule_atoms": [
                        {
                            "rule_key": "tide_rule",
                            "title": "潮门通行",
                            "source_keys": ["conversation:seed:1"],
                            "can": "借潮过门",
                            "cannot": "逆潮连续过门",
                            "cost": "消耗配额",
                            "failure": "断供",
                            "maintenance": "每日校准",
                        }
                    ],
                    "blocking_contradictions": [],
                    "vertical_slice": {
                        "rule_key": "tide_rule",
                        "daily_consequence": "居民按潮通勤",
                        "failure_consequence": "失准后街区断供",
                    },
                },
                "decisions": [
                    {
                        "item_key": "tide_rule",
                        "text": "采纳潮门通行规则",
                        "disposition": "locked",
                        "rule_key": "tide_rule",
                        "source_keys": ["conversation:seed:1"],
                    }
                ],
            },
        },
    )
    assert checkpoint.status_code == 201, checkpoint.text
    loaded_checkpoint = await async_client.get(
        f"/api/world/adoption-packages/{checkpoint.json()['id']}",
        params={"novel_id": project_novel_id},
    )
    assert loaded_checkpoint.status_code == 200, loaded_checkpoint.text
    checkpoint_payload = loaded_checkpoint.json()["payload_json"]
    assert checkpoint_payload["round_no"] == 3
    assert checkpoint_payload["seeds"][0]["seed_key"] == "tide_city"
    assert checkpoint_payload["world_core"]["rule_atoms"][0]["rule_key"] == ("tide_rule")
    assert checkpoint_payload["decisions"][0]["disposition"] == "locked"
    checkpoint_apply = await async_client.post(
        f"/api/world/adoption-packages/{checkpoint.json()['id']}/apply",
        params={"novel_id": project_novel_id},
        json={"expected_preview_hash": manifest},
    )
    assert checkpoint_apply.status_code == 400
    saved = await async_client.post(
        "/api/world/adoption-packages",
        json={
            "novel_id": project_novel_id,
            "package": {
                "schema_version": "world_adoption_package.v1",
                "checkpoint_suggestion_id": checkpoint.json()["id"],
                "checkpoint_manifest_hash": manifest,
                "source_manifest_hash": manifest,
                "items": [
                    {
                        "item_key": "city",
                        "kind": "core_entity",
                        "disposition": "include",
                        "authority_kind": "author_seed",
                        "source_refs": [_source_ref(manifest)],
                        "payload": {
                            "operation": "create",
                            "entity": {"entity_type": "location", "name": "雾港"},
                        },
                    }
                ],
            },
        },
    )
    assert saved.status_code == 201, saved.text
    preview = await async_client.get(
        f"/api/world/adoption-packages/{saved.json()['id']}/preview",
        params={"novel_id": project_novel_id},
    )
    assert preview.status_code == 200, preview.text
    applied = await async_client.post(
        f"/api/world/adoption-packages/{saved.json()['id']}/apply",
        params={"novel_id": project_novel_id},
        json={"expected_preview_hash": preview.json()["expected_preview_hash"]},
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["status"] == "accepted"


@pytest.mark.asyncio
async def test_api_apply_duplicate_rolls_back_package(
    async_client: AsyncClient,
    project_novel_id: str,
) -> None:
    manifest = hashlib.sha256(b"api-rollback").hexdigest()
    saved = await async_client.post(
        "/api/world/adoption-packages",
        json={
            "novel_id": project_novel_id,
            "package": {
                "schema_version": "world_adoption_package.v1",
                "source_manifest_hash": manifest,
                "items": [
                    {
                        "item_key": "first",
                        "kind": "core_entity",
                        "disposition": "include",
                        "authority_kind": "author_seed",
                        "source_refs": [_source_ref(manifest)],
                        "payload": {
                            "operation": "create",
                            "entity": {"entity_type": "location", "name": "回滚港"},
                        },
                    },
                    {
                        "item_key": "second",
                        "kind": "core_entity",
                        "disposition": "include",
                        "authority_kind": "author_seed",
                        "source_refs": [_source_ref(manifest)],
                        "payload": {
                            "operation": "create",
                            "entity": {"entity_type": "location", "name": "回滚港"},
                        },
                    },
                ],
            },
        },
    )
    assert saved.status_code == 201, saved.text
    suggestion_id = saved.json()["id"]
    preview = await async_client.get(
        f"/api/world/adoption-packages/{suggestion_id}/preview",
        params={"novel_id": project_novel_id},
    )
    assert preview.status_code == 200, preview.text
    failed = await async_client.post(
        f"/api/world/adoption-packages/{suggestion_id}/apply",
        params={"novel_id": project_novel_id},
        json={"expected_preview_hash": preview.json()["expected_preview_hash"]},
    )
    assert failed.status_code == 409, failed.text
    artifact = await async_client.get(
        f"/api/world/adoption-packages/{suggestion_id}",
        params={"novel_id": project_novel_id},
    )
    assert artifact.status_code == 200, artifact.text
    assert artifact.json()["status"] == "pending"
    entities = await async_client.get(
        "/api/world/entities",
        params={"novel_id": project_novel_id, "q": "回滚港"},
    )
    assert entities.status_code == 200, entities.text
    assert entities.json()["items"] == []


@pytest.mark.asyncio
async def test_api_page_publish_failure_rolls_back_package(
    async_client: AsyncClient,
    db_session: AsyncSession,
    project_novel_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modules.world.services.worldbuilding.world_bible_lifecycle_service import (
        WorldBibleLifecycleService,
    )

    async def fail_publish(*_args, **_kwargs):
        raise RuntimeError("publish failed")

    monkeypatch.setattr(WorldBibleLifecycleService, "publish_draft", fail_publish)
    before = {
        model: len(
            (
                await db_session.execute(
                    select(model).where(model.novel_id == uuid.UUID(project_novel_id))
                )
            )
            .scalars()
            .all()
        )
        for model in (
            WorldBiblePage,
            WorldBiblePageDraft,
            WorldBiblePageRevision,
            CoreEntity,
        )
    }
    manifest = hashlib.sha256(b"publish-failure").hexdigest()
    saved = await async_client.post(
        "/api/world/adoption-packages",
        json={
            "novel_id": project_novel_id,
            "package": {
                "schema_version": "world_adoption_package.v1",
                "source_manifest_hash": manifest,
                "items": [
                    {
                        "item_key": "city",
                        "kind": "core_entity",
                        "disposition": "include",
                        "authority_kind": "author_seed",
                        "source_refs": [_source_ref(manifest)],
                        "payload": {
                            "operation": "create",
                            "entity": {"entity_type": "location", "name": "失败港"},
                        },
                    },
                    {
                        "item_key": "page",
                        "kind": "world_bible_page",
                        "disposition": "include",
                        "authority_kind": "generated_bridge",
                        "source_refs": [_source_ref(manifest)],
                        "payload": {
                            "operation": "create",
                            "title": "失败港",
                            "page_type": "location",
                            "sections_json": [
                                {
                                    "section_id": "s",
                                    "title": "S",
                                    "body_markdown": "失败港。",
                                }
                            ],
                            "claim_mappings": [
                                {
                                    "content_key": "s",
                                    "claim": "失败港。",
                                    "item_key": "city",
                                    "source_ref": _source_ref(manifest),
                                }
                            ],
                        },
                    },
                ],
            },
        },
    )
    preview = await async_client.get(
        f"/api/world/adoption-packages/{saved.json()['id']}/preview",
        params={"novel_id": project_novel_id},
    )
    with pytest.raises(RuntimeError, match="publish failed"):
        await async_client.post(
            f"/api/world/adoption-packages/{saved.json()['id']}/apply",
            params={"novel_id": project_novel_id},
            json={"expected_preview_hash": preview.json()["expected_preview_hash"]},
        )
    artifact = await async_client.get(
        f"/api/world/adoption-packages/{saved.json()['id']}",
        params={"novel_id": project_novel_id},
    )
    assert artifact.json()["status"] == "pending"
    assert (
        await async_client.get(
            "/api/world/entities", params={"novel_id": project_novel_id, "q": "失败港"}
        )
    ).json()["items"] == []
    for model, count in before.items():
        assert (
            len(
                (
                    await db_session.execute(
                        select(model).where(model.novel_id == uuid.UUID(project_novel_id))
                    )
                )
                .scalars()
                .all()
            )
            == count
        )


@pytest.mark.asyncio
async def test_adoption_package_api_hides_artifacts_from_other_owner(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    owner = Account(status="active", support_code="U-ADOPTOWNER")
    other = Account(status="active", support_code="U-ADOPTOTHER")
    db_session.add_all([owner, other])
    await db_session.flush()
    owner_token = bind_principal(_principal(owner))
    try:
        project = await ProjectService().create_project(
            db_session, ProjectCreate(title="私有采用项目")
        )
        manifest = hashlib.sha256(b"owner-isolation").hexdigest()
        saved = await async_client.post(
            "/api/world/adoption-packages",
            json={
                "novel_id": project.id,
                "package": {
                    "schema_version": "world_adoption_package.v1",
                    "source_manifest_hash": manifest,
                    "items": [
                        {
                            "item_key": "private-city",
                            "kind": "core_entity",
                            "disposition": "include",
                            "authority_kind": "author_seed",
                            "source_refs": [_source_ref(manifest)],
                            "payload": {
                                "operation": "create",
                                "entity": {"entity_type": "location", "name": "私港"},
                            },
                        }
                    ],
                },
            },
        )
        assert saved.status_code == 201, saved.text
    finally:
        reset_principal(owner_token)

    other_token = bind_principal(_principal(other))
    try:
        for method, path, kwargs in (
            ("get", f"/api/world/adoption-packages/{saved.json()['id']}", {}),
            ("get", f"/api/world/adoption-packages/{saved.json()['id']}/preview", {}),
            (
                "post",
                f"/api/world/adoption-packages/{saved.json()['id']}/apply",
                {"json": {"expected_preview_hash": "0" * 64}},
            ),
        ):
            response = await getattr(async_client, method)(
                path, params={"novel_id": project.id}, **kwargs
            )
            assert response.status_code == 404, response.text
    finally:
        reset_principal(other_token)


@pytest.mark.asyncio
async def test_replace_page_drift_keeps_package_pending(
    db_session: AsyncSession, project_novel_id: str
) -> None:
    lifecycle = WorldBibleLifecycleService()
    page = await lifecycle.create_page(
        db_session,
        WorldBiblePageCreate(
            novel_id=project_novel_id,
            page_type="location",
            title="旧页",
            status="canonical",
        ),
    )
    manifest = hashlib.sha256(b"replace-drift").hexdigest()
    package = _replace_package(project_novel_id, page.id, page.version_number, manifest)
    service = WorldAdoptionPackageService()
    saved = await service.save(
        db_session,
        WorldAdoptionPackageSaveRequest(novel_id=project_novel_id, package=package),
    )
    preview = await service.preview(db_session, project_novel_id, saved.id)
    await lifecycle.update_page(
        db_session, project_novel_id, page.id, WorldBiblePageUpdate(title="外部更新")
    )
    external = (
        await db_session.execute(
            select(WorldBiblePage).where(WorldBiblePage.id == uuid.UUID(page.id))
        )
    ).scalar_one()
    revision_count = len(
        (
            await db_session.execute(
                select(WorldBiblePageRevision).where(
                    WorldBiblePageRevision.page_id == uuid.UUID(page.id)
                )
            )
        )
        .scalars()
        .all()
    )
    with pytest.raises(ConflictError):
        await service.apply(
            db_session,
            project_novel_id,
            saved.id,
            WorldAdoptionPackageApplyRequest(
                expected_preview_hash=preview.expected_preview_hash
            ),
        )
    assert (await service.get(db_session, project_novel_id, saved.id)).status == "pending"
    assert (
        await db_session.execute(select(CoreEntity).where(CoreEntity.name == "不得创建"))
    ).scalars().all() == []
    current = (
        await db_session.execute(
            select(WorldBiblePage).where(WorldBiblePage.id == uuid.UUID(page.id))
        )
    ).scalar_one()
    assert (current.title, current.version_number) == (
        external.title,
        external.version_number,
    )
    assert (
        len(
            (
                await db_session.execute(
                    select(WorldBiblePageRevision).where(
                        WorldBiblePageRevision.page_id == uuid.UUID(page.id)
                    )
                )
            )
            .scalars()
            .all()
        )
        == revision_count
    )


def _replace_package(novel_id, page_id, version, manifest):
    return WorldAdoptionPackagePayload(
        schema_version="world_adoption_package.v1",
        source_manifest_hash=manifest,
        items=[
            {
                "item_key": "new-city",
                "kind": "core_entity",
                "disposition": "include",
                "authority_kind": "author_seed",
                "source_refs": [_source_ref(manifest)],
                "payload": {
                    "operation": "create",
                    "entity": {"entity_type": "location", "name": "不得创建"},
                },
            },
            {
                "item_key": "replace",
                "kind": "world_bible_page",
                "disposition": "include",
                "authority_kind": "generated_bridge",
                "source_refs": [_source_ref(manifest)],
                "payload": {
                    "operation": "replace",
                    "page_id": page_id,
                    "expected_page_version": version,
                    "title": "替换页",
                    "page_type": "location",
                    "sections_json": [
                        {"section_id": "s", "title": "S", "body_markdown": "替换内容。"}
                    ],
                    "claim_mappings": [
                        {
                            "content_key": "s",
                            "claim": "替换内容。",
                            "item_key": "new-city",
                            "source_ref": _source_ref(manifest),
                        }
                    ],
                },
            },
        ],
    )


def _source_ref(source_hash: str) -> dict[str, str]:
    return {
        "source_type": "conversation",
        "source_id": "conversation-1",
        "source_hash": source_hash,
    }


def _principal(account: Account) -> AccountPrincipal:
    return AccountPrincipal(
        account_id=account.id,
        status="active",
        identity_type="email",
        support_code=account.support_code,
    )
