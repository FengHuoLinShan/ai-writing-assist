from __future__ import annotations

import hashlib
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ConflictError
from modules.account.context import bind_principal, reset_principal
from modules.account.contracts import AccountPrincipal
from modules.account.models import Account
from modules.project.schemas import ProjectCreate
from modules.project.services import ProjectService
from modules.world.models.core import CoreEntity, EntityRelation
from modules.world.schemas import (
    CoreEntityCreate,
    EntityRelationCreate,
    WorldAdoptionPackageApplyRequest,
    WorldAdoptionPackagePayload,
    WorldAdoptionPackageSaveRequest,
    WorldCoreCheckpointPayload,
    WorldCoreCheckpointSaveRequest,
)
from modules.world.services.core.entity_relation_service import EntityRelationService
from modules.world.services.core.entity_service import WorldEntityService
from modules.world.services.worldbuilding.adoption_package_service import (
    WorldAdoptionPackageService,
)


@pytest.mark.asyncio
async def test_package_preview_apply_is_idempotent_and_ignores_open_items(
    db_session: AsyncSession,
    project_novel_id: str,
) -> None:
    service = WorldAdoptionPackageService()
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
    assert applied.result_ref_json["local_ref_map"].keys() == {"city", "guild"}
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
        await db_session.execute(
            select(CoreEntity).where(
                CoreEntity.novel_id == uuid.UUID(project_novel_id),
                CoreEntity.name == "重复港",
            )
        )
    ).scalars().all()
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
        await db_session.execute(
            select(CoreEntity).where(CoreEntity.name == "失效港")
        )
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
                "round_no": 0,
                "action": "consolidate",
                "source_manifest_hash": manifest,
            },
        },
    )
    assert checkpoint.status_code == 201, checkpoint.text
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
