"""B6 regressions for CoreEntity legacy text and dossier synchronization."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from core.errors import ValidationError
from modules.story.outline_state.models import Scene
from modules.world.contracts import (
    AuthorMigrationEntityInput,
    AuthorMigrationWorldRequest,
)
from modules.world.dossier_service import WorldObjectDossierService
from modules.world.facade import apply_author_migration_world, plan_author_migration_world
from modules.world.models import (
    CoreEntity,
    EntityRevision,
    TextArchive,
    WorldObjectDossierEntry,
)
from modules.world.schemas import (
    CoreEntityCreate,
    CoreEntityUpdate,
    DossierEntryCreate,
    DossierEntryRestore,
    DossierEntryUpdate,
    DossierFacingRef,
)
from modules.world.schemas.dossier import DossierValidity
from modules.world.services.core.dedup_service import EntityDedupService
from modules.world.services.core.entity_revision_service import EntityRevisionService
from modules.world.services.core.entity_service import WorldEntityService

pytestmark = pytest.mark.asyncio


async def _entries(db_session, novel_id: str, entity_id: uuid.UUID, field: str):
    return list(
        (
            await db_session.scalars(
                select(WorldObjectDossierEntry)
                .where(
                    WorldObjectDossierEntry.novel_id == uuid.UUID(novel_id),
                    WorldObjectDossierEntry.entity_id == entity_id,
                    WorldObjectDossierEntry.legacy_field_key == field,
                )
                .order_by(WorldObjectDossierEntry.revision_number)
            )
        ).all()
    )


async def test_core_entity_create_update_and_clear_sync_all_three_fields(
    db_session, project_novel_id
):
    service = WorldEntityService()
    entity = await service.create(
        db_session,
        project_novel_id,
        CoreEntityCreate(
            entity_type="location",
            name="档案同步对象",
            summary="初始概要",
            public_info="初始公开",
            hidden_truth="初始真相",
        ),
    )

    for field, expected_visibility in (
        ("summary", "public"),
        ("public_info", "public"),
        ("hidden_truth", "secret"),
    ):
        rows = await _entries(db_session, project_novel_id, uuid.UUID(entity.id), field)
        assert len(rows) == 1
        assert rows[0].content == getattr(entity, field)
        assert rows[0].status == "active"
        assert rows[0].visibility == expected_visibility

    await service.update(
        db_session,
        entity.id,
        CoreEntityUpdate(
            summary="更新概要", public_info="更新公开", hidden_truth="更新真相"
        ),
        novel_id=project_novel_id,
    )
    for field, expected_content in (
        ("summary", "更新概要"),
        ("public_info", "更新公开"),
        ("hidden_truth", "更新真相"),
    ):
        rows = await _entries(db_session, project_novel_id, uuid.UUID(entity.id), field)
        assert [row.status for row in rows] == ["superseded", "active"]
        assert rows[-1].content == expected_content

    cleared = await service.update(
        db_session,
        entity.id,
        CoreEntityUpdate(public_info=None),
        novel_id=project_novel_id,
        _clear_fields=frozenset({"public_info"}),
    )
    assert cleared.public_info is None
    public_rows = await _entries(
        db_session, project_novel_id, uuid.UUID(entity.id), "public_info"
    )
    assert [row.status for row in public_rows] == [
        "superseded",
        "superseded",
        "cleared",
    ]


async def test_core_entity_legacy_projection_keeps_other_groups_on_edit_clear_restore(
    db_session, project_novel_id
):
    entity = await WorldEntityService().create(
        db_session,
        project_novel_id,
        CoreEntityCreate(entity_type="location", name="多组档案对象"),
    )
    dossier = WorldObjectDossierService()

    async def create_group(content: str):
        return await dossier.create_entry(
            db_session,
            project_novel_id,
            entity.id,
            DossierEntryCreate(
                facing=DossierFacingRef(kind="core", key="public_info"),
                legacy_field_key="public_info",
                content=content,
                visibility="public",
            ),
        )

    first = await create_group("第一组公开信息")
    second = await create_group("第二组公开信息")
    current = await db_session.get(CoreEntity, uuid.UUID(entity.id))
    assert current is not None
    assert "第一组公开信息" in current.public_info
    assert "第二组公开信息" in current.public_info

    first_edit = await dossier.update_entry(
        db_session,
        project_novel_id,
        entity.id,
        str(first.id),
        DossierEntryUpdate(expected_revision_id=first.id, content="编辑后的第一组"),
    )
    await db_session.flush()
    await db_session.refresh(current)
    assert "编辑后的第一组" in current.public_info
    assert "第二组公开信息" in current.public_info

    await dossier.update_entry(
        db_session,
        project_novel_id,
        entity.id,
        str(second.id),
        DossierEntryUpdate(expected_revision_id=second.id, content=""),
    )
    await db_session.flush()
    await db_session.refresh(current)
    assert current.public_info == "编辑后的第一组"

    second_restore = await dossier.restore_entry(
        db_session,
        project_novel_id,
        entity.id,
        str(second.entry_group_id),
        DossierEntryRestore(revision_id=second.id),
    )
    await db_session.flush()
    await db_session.refresh(current)
    assert "编辑后的第一组" in current.public_info
    assert "第二组公开信息" in current.public_info

    await dossier.update_entry(
        db_session,
        project_novel_id,
        entity.id,
        str(first_edit.id),
        DossierEntryUpdate(expected_revision_id=first_edit.id, content=""),
    )
    await dossier.update_entry(
        db_session,
        project_novel_id,
        entity.id,
        str(second_restore.id),
        DossierEntryUpdate(expected_revision_id=second_restore.id, content=""),
    )
    await db_session.flush()
    await db_session.refresh(current)
    assert current.public_info is None

    first_rows = await _entries(
        db_session, project_novel_id, uuid.UUID(entity.id), "public_info"
    )
    assert all(row.status != "active" for row in first_rows)


async def test_core_entity_clear_supersedes_other_group_after_latest_was_cleared(
    db_session, project_novel_id
):
    entity = await WorldEntityService().create(
        db_session,
        project_novel_id,
        CoreEntityCreate(entity_type="location", name="清空多组档案对象"),
    )
    dossier = WorldObjectDossierService()
    groups = [
        await dossier.create_entry(
            db_session,
            project_novel_id,
            entity.id,
            DossierEntryCreate(
                facing=DossierFacingRef(kind="core", key="public_info"),
                legacy_field_key="public_info",
                content=value,
            ),
        )
        for value in ("仍有效的旧组", "最新组")
    ]
    await dossier.update_entry(
        db_session,
        project_novel_id,
        entity.id,
        str(groups[1].id),
        DossierEntryUpdate(expected_revision_id=groups[1].id, content=""),
    )

    await WorldEntityService().update(
        db_session,
        entity.id,
        CoreEntityUpdate(public_info=None),
        novel_id=project_novel_id,
        _clear_fields=frozenset({"public_info"}),
    )

    current = await db_session.get(CoreEntity, uuid.UUID(entity.id))
    rows = await _entries(
        db_session, project_novel_id, uuid.UUID(entity.id), "public_info"
    )
    assert current.public_info is None
    assert not [row for row in rows if row.status == "active"]


async def test_core_entity_edit_does_not_reuse_scene_bounded_legacy_group(
    db_session, project_novel_id
):
    scene = Scene(novel_id=uuid.UUID(project_novel_id), scene_index=1, status="draft")
    db_session.add(scene)
    await db_session.flush()
    entity = await WorldEntityService().create(
        db_session,
        project_novel_id,
        CoreEntityCreate(entity_type="location", name="时点档案对象"),
    )
    dossier = WorldObjectDossierService()
    unbounded = await dossier.create_entry(
        db_session,
        project_novel_id,
        entity.id,
        DossierEntryCreate(
            facing=DossierFacingRef(kind="core", key="public_info"),
            legacy_field_key="public_info",
            content="长期公开信息",
        ),
    )
    bounded = await dossier.create_entry(
        db_session,
        project_novel_id,
        entity.id,
        DossierEntryCreate(
            facing=DossierFacingRef(kind="core", key="public_info"),
            legacy_field_key="public_info",
            content="某场景有效的信息",
            validity=DossierValidity(start={"kind": "scene", "id": scene.id}),
        ),
    )

    updated = await WorldEntityService().update(
        db_session,
        entity.id,
        CoreEntityUpdate(public_info="实体面板的新公开信息"),
        novel_id=project_novel_id,
    )

    rows = await _entries(
        db_session, project_novel_id, uuid.UUID(entity.id), "public_info"
    )
    assert updated.public_info == "实体面板的新公开信息"
    assert next(row for row in rows if row.id == bounded.id).status == "active"
    assert sum(row.status == "active" for row in rows) == 2
    assert any(
        row.entry_group_id == unbounded.entry_group_id
        and row.status == "active"
        and row.content == "实体面板的新公开信息"
        for row in rows
    )


async def test_core_entity_edit_after_legacy_group_becomes_scene_bounded(
    db_session, project_novel_id
):
    scene = Scene(novel_id=uuid.UUID(project_novel_id), scene_index=1, status="draft")
    db_session.add(scene)
    await db_session.flush()
    entity = await WorldEntityService().create(
        db_session,
        project_novel_id,
        CoreEntityCreate(
            entity_type="location",
            name="长期档案改为时点档案",
            public_info="最初的长期信息",
        ),
    )
    dossier = WorldObjectDossierService()
    original = (await _entries(
        db_session, project_novel_id, uuid.UUID(entity.id), "public_info"
    ))[-1]
    bounded = await dossier.update_entry(
        db_session,
        project_novel_id,
        entity.id,
        str(original.id),
        DossierEntryUpdate(
            expected_revision_id=original.id,
            validity=DossierValidity(start={"kind": "scene", "id": scene.id}),
        ),
    )
    assert bounded.status == "active"
    bounded_row = await db_session.get(WorldObjectDossierEntry, bounded.id)
    assert bounded_row.start_anchor_id == scene.id

    updated = await WorldEntityService().update(
        db_session,
        entity.id,
        CoreEntityUpdate(public_info="新的长期信息"),
        novel_id=project_novel_id,
    )

    rows = await _entries(
        db_session, project_novel_id, uuid.UUID(entity.id), "public_info"
    )
    active = [row for row in rows if row.status == "active"]
    assert updated.public_info == "新的长期信息"
    assert len(active) == 2
    assert next(row for row in active if row.id == bounded.id).start_anchor_id == scene.id
    assert any(
        row.entry_group_id != bounded.entry_group_id
        and row.start_anchor_id is None
        and row.end_anchor_id is None
        and row.content == "新的长期信息"
        for row in active
    )


async def test_entity_revision_restore_appends_dossier_revisions_and_clears_null(
    db_session, project_novel_id
):
    service = WorldEntityService()
    entity = await service.create(
        db_session,
        project_novel_id,
        CoreEntityCreate(entity_type="location", name="恢复同步对象", summary="原概要"),
    )
    edited = await service.update(
        db_session,
        entity.id,
        CoreEntityUpdate(summary="新概要", public_info="临时公开"),
        novel_id=project_novel_id,
    )
    before = await db_session.scalar(
        select(EntityRevision)
        .where(EntityRevision.entity_id == uuid.UUID(entity.id))
        .order_by(EntityRevision.created_at.desc(), EntityRevision.id.desc())
    )
    assert before is not None

    restored = await service.rollback_to_revision(
        db_session,
        entity.id,
        str(before.id),
        novel_id=project_novel_id,
        expected_updated_at=edited.updated_at,
    )

    assert restored.summary == "原概要"
    assert restored.public_info is None
    summary_rows = await _entries(
        db_session, project_novel_id, uuid.UUID(entity.id), "summary"
    )
    assert [row.status for row in summary_rows] == [
        "superseded",
        "superseded",
        "active",
    ]
    assert summary_rows[-1].content == "原概要"
    public_rows = await _entries(
        db_session, project_novel_id, uuid.UUID(entity.id), "public_info"
    )
    assert [row.status for row in public_rows] == ["superseded", "cleared"]


async def test_scene_revision_restore_syncs_dossier_and_honors_null_archive(
    db_session, project_novel_id
):
    service = WorldEntityService()
    entity = await service.create(
        db_session,
        project_novel_id,
        CoreEntityCreate(entity_type="location", name="场景恢复对象", summary="原概要"),
    )
    await service.update(
        db_session,
        entity.id,
        CoreEntityUpdate(summary="新概要", public_info="临时公开"),
        novel_id=project_novel_id,
    )
    db_session.add(
        TextArchive(
            novel_id=uuid.UUID(project_novel_id),
            entity_id=uuid.UUID(entity.id),
            field_name="public_info",
            text_content=None,
            scene_index=5,
            source="manual_edit",
        )
    )
    await db_session.flush()

    await EntityRevisionService().rollback_to_scene_index(
        db_session,
        entity.id,
        target_scene_index=5,
        novel_id=project_novel_id,
    )

    current = await db_session.get(CoreEntity, uuid.UUID(entity.id))
    assert current is not None
    assert current.public_info is None
    rows = await _entries(
        db_session, project_novel_id, uuid.UUID(entity.id), "public_info"
    )
    assert [row.status for row in rows] == ["superseded", "cleared"]


async def test_scene_revision_fallback_restores_dossier_text(
    db_session, project_novel_id
):
    service = WorldEntityService()
    entity = await service.create(
        db_session,
        project_novel_id,
        CoreEntityCreate(entity_type="location", name="修订回退对象", summary="原概要"),
    )
    await service.update(
        db_session,
        entity.id,
        CoreEntityUpdate(summary="新概要"),
        novel_id=project_novel_id,
    )

    await EntityRevisionService().rollback_to_scene_index(
        db_session,
        entity.id,
        target_scene_index=0,
        novel_id=project_novel_id,
    )

    rows = await _entries(db_session, project_novel_id, uuid.UUID(entity.id), "summary")
    assert [row.status for row in rows] == ["superseded", "superseded", "active"]
    assert rows[-1].content == "原概要"


async def test_core_legacy_facings_include_custom_types_and_protect_secrets(
    db_session, project_novel_id
):
    entity = await WorldEntityService().create(
        db_session,
        project_novel_id,
        CoreEntityCreate(entity_type="custom_location", name="自定义档案对象"),
    )
    dossier = WorldObjectDossierService()
    facets = await dossier.list_facets(db_session, project_novel_id, "custom_location")
    keys = {item.facing.key for item in facets.items if item.facing.kind == "core"}
    assert {"overview", "public_info", "truth"} <= keys

    with pytest.raises(ValidationError, match="可见性"):
        await dossier.preview_create_entry(
            db_session,
            project_novel_id,
            entity.id,
            DossierEntryCreate(
                facing=DossierFacingRef(kind="core", key="truth"),
                legacy_field_key="hidden_truth",
                content="作者秘密",
                visibility="public",
            ),
        )


async def test_merge_syncs_merged_text_into_target_dossier(db_session, project_novel_id):
    service = WorldEntityService()
    target = await service.create(
        db_session,
        project_novel_id,
        CoreEntityCreate(
            entity_type="location",
            name="合并目标",
            summary="目标概要",
            public_info="目标公开",
            hidden_truth="目标真相",
        ),
    )
    candidate = await service.create(
        db_session,
        project_novel_id,
        CoreEntityCreate(
            entity_type="location",
            name="合并候选",
            summary="候选概要",
            public_info="候选公开",
            hidden_truth="候选真相",
            status="draft",
        ),
    )

    await EntityDedupService().merge_candidate_into_entity(
        db_session, project_novel_id, candidate.id, target.id
    )

    current = await db_session.scalar(
        select(CoreEntity).where(
            CoreEntity.novel_id == uuid.UUID(project_novel_id),
            CoreEntity.id == uuid.UUID(target.id),
        )
    )
    assert current is not None
    for field in ("summary", "public_info", "hidden_truth"):
        rows = await _entries(db_session, project_novel_id, current.id, field)
        assert rows[-1].status == "active"
        assert rows[-1].content == getattr(current, field)
        assert "候选" in rows[-1].content


async def test_author_migration_fill_empty_syncs_the_dossier(
    db_session, project_novel_id
):
    entity = await WorldEntityService().create(
        db_session,
        project_novel_id,
        CoreEntityCreate(entity_type="location", name="表格补空对象", summary="已有概要"),
    )
    request = AuthorMigrationWorldRequest(
        migration_id="b6-dossier-fill",
        entities=[
            AuthorMigrationEntityInput(
                item_key="location-1",
                source_ref="f0s0:r2",
                source_hash="a" * 64,
                name="表格补空对象",
                entity_type="location",
                public_info="由表格补入的公开信息",
            )
        ],
        relations=[],
    )
    plan = await plan_author_migration_world(db_session, project_novel_id, request)
    assert next(item for item in plan.items if item.item_key == "location-1").action == (
        "fill_empty"
    )

    receipt = await apply_author_migration_world(
        db_session,
        project_novel_id,
        request,
        expected_fingerprint=plan.fingerprint,
        authorized_by="owner-1",
    )

    rows = await _entries(
        db_session, project_novel_id, uuid.UUID(entity.id), "public_info"
    )
    assert len(rows) == 1
    assert rows[0].status == "active"
    assert rows[0].content == "由表格补入的公开信息"

    from modules.world.facade import rollback_author_migration_world

    await rollback_author_migration_world(
        db_session, project_novel_id, receipt, dry_run=False
    )
    current = await db_session.get(CoreEntity, uuid.UUID(entity.id))
    rows = await _entries(
        db_session, project_novel_id, uuid.UUID(entity.id), "public_info"
    )
    assert current.public_info is None
    assert [row.status for row in rows] == ["superseded", "cleared"]
