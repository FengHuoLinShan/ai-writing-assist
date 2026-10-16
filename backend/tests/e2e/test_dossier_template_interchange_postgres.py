"""Real PostgreSQL coverage for borrowed facets and dossier interchange writes."""

from __future__ import annotations

from copy import deepcopy

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.assistant.operation_trace_models import AssistantOperationTrace
from modules.imports.tests.spreadsheet_fixtures import build_xlsx
from modules.world.models import CoreEntity, WorldObjectDossierEntry


async def test_borrowed_facets_csv_manifest_roundtrip_and_receipt_rollback(
    async_client,
    db_session: AsyncSession,
) -> None:
    project_response = await async_client.post(
        "/api/projects", json={"title": "PG 档案互通"}
    )
    assert project_response.status_code == 201, project_response.text
    novel_id = project_response.json()["id"]

    source_term = await async_client.post(
        f"/api/world/project-vocabulary/{novel_id}/terms",
        json={"kind": "dossier_facing", "name": "修行境界"},
    )
    assert source_term.status_code == 201, source_term.text
    custom = await async_client.post(
        "/api/world/entities",
        params={"novel_id": novel_id},
        json={"entity_type": "spirit_beast", "name": "云角", "status": "canonical"},
    )
    assert custom.status_code == 201, custom.text
    custom_id = custom.json()["id"]
    template = await async_client.put(
        "/api/world/dossier-templates/spirit_beast/author",
        params={"novel_id": novel_id},
        json={
            "fields": [],
            "borrowed_facings": [
                {"kind": "core", "key": "borrowed:character:appearance"},
                {"kind": "core", "key": "borrowed:species:appearance"},
                {"kind": "core", "key": "borrowed:species:physiology_lifespan"},
            ],
        },
    )
    assert template.status_code == 200, template.text
    for source_type, text in (
        ("character", "总会先护住幼崽"),
        ("species", "换季时会褪下银色细鳞"),
    ):
        created = await async_client.post(
            f"/api/world/entities/{custom_id}/dossier/entries",
            params={"novel_id": novel_id},
            json={
                "facing": {
                    "kind": "core",
                    "key": f"borrowed:{source_type}:appearance",
                },
                "content": text,
            },
        )
        assert created.status_code == 201, created.text
    custom_row = await db_session.get(CoreEntity, custom_id)
    assert custom_row is not None and custom_row.entity_type == "spirit_beast"

    custom_csv = await async_client.post(
        "/api/imports/migrations",
        data={"novel_id": novel_id},
        files={
            "files": (
                "灵兽档案.csv",
                "姓名,类型,种族观察\n云角,spirit_beast,冬季会长出银色护鳞\n".encode(),
                "text/csv",
            )
        },
    )
    assert custom_csv.status_code == 201, custom_csv.text
    custom_sheet = custom_csv.json()["sheets"][0]
    custom_mapping = await async_client.put(
        f"/api/imports/migrations/{custom_csv.json()['id']}/mapping",
        json={
            "novel_id": novel_id,
            "expected_revision": custom_csv.json()["revision"],
            "sheets": [
                {
                    "sheet_key": custom_sheet["sheet_key"],
                    "kind": "characters",
                    "header_row": 0,
                    "default_entity_type": "spirit_beast",
                    "dossier_profile_type": "spirit_beast",
                    "columns": {
                        "c0": "name",
                        "c1": "entity_type",
                        "c2": "dossier_facing",
                    },
                    "facing_mappings": {
                        "c2": {
                            "kind": "core",
                            "key": "physiology_lifespan",
                            "source_entity_type": "species",
                            "visibility": "public",
                        }
                    },
                }
            ],
            "options": {
                "written_chapter_policy": "reference_only",
                "outline_head_policy": "skip",
            },
        },
    )
    assert custom_mapping.status_code == 200, custom_mapping.text
    custom_apply = await async_client.post(
        f"/api/imports/migrations/{custom_csv.json()['id']}/apply",
        json={
            "novel_id": novel_id,
            "expected_preview_hash": custom_mapping.json()["preview"]["preview_hash"],
            "confirmed": True,
        },
    )
    assert custom_apply.status_code == 200, custom_apply.text
    custom_import_entry = await db_session.scalar(
        select(WorldObjectDossierEntry).where(
            WorldObjectDossierEntry.novel_id == custom_row.novel_id,
            WorldObjectDossierEntry.entity_id == custom_row.id,
            WorldObjectDossierEntry.status == "active",
            WorldObjectDossierEntry.content == "冬季会长出银色护鳞",
        )
    )
    assert custom_import_entry is not None
    assert custom_import_entry.facing_key == "borrowed:species:physiology_lifespan"
    custom_rollback = await async_client.post(
        f"/api/imports/migrations/{custom_csv.json()['id']}/rollback",
        json={"novel_id": novel_id, "confirmed": True},
    )
    assert custom_rollback.status_code == 200, custom_rollback.text
    assert custom_rollback.json()["reverted_count"] >= 1

    uploaded = await async_client.post(
        "/api/imports/migrations",
        data={"novel_id": novel_id},
        files={
            "files": (
                "人物档案.csv",
                "姓名,简介,档案内容\n云岚,沉着的剑修,已至金丹初期\n".encode(),
                "text/csv",
            )
        },
    )
    assert uploaded.status_code == 201, uploaded.text
    sheet = uploaded.json()["sheets"][0]
    mapping = await async_client.put(
        f"/api/imports/migrations/{uploaded.json()['id']}/mapping",
        json={
            "novel_id": novel_id,
            "expected_revision": uploaded.json()["revision"],
            "sheets": [
                {
                    "sheet_key": sheet["sheet_key"],
                    "kind": "characters",
                    "header_row": 0,
                    "default_entity_type": "character",
                    "dossier_profile_type": "character",
                    "columns": {"c0": "name", "c1": "summary", "c2": "dossier_facing"},
                    "facing_mappings": {
                        "c2": {
                            "kind": "project",
                            "term_id": source_term.json()["id"],
                            "visibility": "secret",
                        }
                    },
                }
            ],
            "options": {
                "written_chapter_policy": "reference_only",
                "outline_head_policy": "skip",
            },
        },
    )
    assert mapping.status_code == 200, mapping.text
    migration_id = uploaded.json()["id"]
    applied = await async_client.post(
        f"/api/imports/migrations/{migration_id}/apply",
        json={
            "novel_id": novel_id,
            "expected_preview_hash": mapping.json()["preview"]["preview_hash"],
            "confirmed": True,
        },
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["counts"]["dossier_entries"] == 1
    source_entity = await db_session.scalar(
        select(CoreEntity).where(
            CoreEntity.novel_id == custom_row.novel_id, CoreEntity.name == "云岚"
        )
    )
    assert source_entity is not None

    xlsx_bytes = build_xlsx(
        [
            {
                "name": "人物档案",
                "rows": [["姓名", "简介", "档案内容"], ["白", "新人物", "尚未筑基"]],
            }
        ]
    )
    xlsx_upload = await async_client.post(
        "/api/imports/migrations",
        data={"novel_id": novel_id},
        files={
            "files": (
                "人物档案.xlsx",
                xlsx_bytes,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert xlsx_upload.status_code == 201, xlsx_upload.text
    xlsx_sheet = xlsx_upload.json()["sheets"][0]
    xlsx_mapping = await async_client.put(
        f"/api/imports/migrations/{xlsx_upload.json()['id']}/mapping",
        json={
            "novel_id": novel_id,
            "expected_revision": xlsx_upload.json()["revision"],
            "sheets": [
                {
                    "sheet_key": xlsx_sheet["sheet_key"],
                    "kind": "characters",
                    "header_row": 0,
                    "default_entity_type": "character",
                    "dossier_profile_type": "character",
                    "columns": {"c0": "name", "c1": "summary", "c2": "dossier_facing"},
                    "facing_mappings": {
                        "c2": {
                            "kind": "project",
                            "term_id": source_term.json()["id"],
                            "visibility": "secret",
                        }
                    },
                }
            ],
            "options": {
                "written_chapter_policy": "reference_only",
                "outline_head_policy": "skip",
            },
        },
    )
    assert xlsx_mapping.status_code == 200, xlsx_mapping.text
    assert xlsx_mapping.json()["preview"]["world_items"][0]["action"] == "create"
    xlsx_apply = await async_client.post(
        f"/api/imports/migrations/{xlsx_upload.json()['id']}/apply",
        json={
            "novel_id": novel_id,
            "expected_preview_hash": xlsx_mapping.json()["preview"]["preview_hash"],
            "confirmed": True,
        },
    )
    assert xlsx_apply.status_code == 200, xlsx_apply.text
    assert xlsx_apply.json()["counts"]["dossier_entries"] == 1
    xlsx_entity = await db_session.scalar(
        select(CoreEntity).where(
            CoreEntity.novel_id == custom_row.novel_id, CoreEntity.name == "白"
        )
    )
    assert xlsx_entity is not None
    xlsx_entry = await db_session.scalar(
        select(WorldObjectDossierEntry).where(
            WorldObjectDossierEntry.novel_id == custom_row.novel_id,
            WorldObjectDossierEntry.entity_id == xlsx_entity.id,
            WorldObjectDossierEntry.status == "active",
        )
    )
    assert xlsx_entry is not None and xlsx_entry.content == "尚未筑基"
    xlsx_rollback = await async_client.post(
        f"/api/imports/migrations/{xlsx_upload.json()['id']}/rollback",
        json={"novel_id": novel_id, "confirmed": True},
    )
    assert xlsx_rollback.status_code == 200, xlsx_rollback.text
    assert xlsx_rollback.json()["reverted_count"] >= 2

    conflict_upload = await async_client.post(
        "/api/imports/migrations",
        data={"novel_id": novel_id},
        files={
            "files": (
                "冲突档案.csv",
                "姓名,简介,档案内容\n云岚,相互冲突的简介,新境界\n".encode(),
                "text/csv",
            )
        },
    )
    assert conflict_upload.status_code == 201, conflict_upload.text
    conflict_sheet = conflict_upload.json()["sheets"][0]
    conflict_mapping = await async_client.put(
        f"/api/imports/migrations/{conflict_upload.json()['id']}/mapping",
        json={
            "novel_id": novel_id,
            "expected_revision": conflict_upload.json()["revision"],
            "sheets": [
                {
                    "sheet_key": conflict_sheet["sheet_key"],
                    "kind": "characters",
                    "header_row": 0,
                    "default_entity_type": "character",
                    "dossier_profile_type": "character",
                    "columns": {"c0": "name", "c1": "summary", "c2": "dossier_facing"},
                    "facing_mappings": {
                        "c2": {
                            "kind": "project",
                            "term_id": source_term.json()["id"],
                            "visibility": "secret",
                        }
                    },
                }
            ],
            "options": {
                "written_chapter_policy": "reference_only",
                "outline_head_policy": "skip",
            },
        },
    )
    assert conflict_mapping.status_code == 200, conflict_mapping.text
    assert conflict_mapping.json()["preview"]["world_items"][0]["action"] == "conflict"
    conflict_apply = await async_client.post(
        f"/api/imports/migrations/{conflict_upload.json()['id']}/apply",
        json={
            "novel_id": novel_id,
            "expected_preview_hash": conflict_mapping.json()["preview"]["preview_hash"],
            "confirmed": True,
        },
    )
    assert conflict_apply.status_code == 200, conflict_apply.text
    original_active = await db_session.scalar(
        select(WorldObjectDossierEntry).where(
            WorldObjectDossierEntry.novel_id == custom_row.novel_id,
            WorldObjectDossierEntry.entity_id == source_entity.id,
            WorldObjectDossierEntry.status == "active",
        )
    )
    assert original_active is not None and original_active.content == "已至金丹初期"

    manifest_response = await async_client.get(
        f"/api/world/entities/{source_entity.id}/dossier/manifest",
        params={"novel_id": novel_id},
    )
    assert manifest_response.status_code == 200, manifest_response.text
    manifest = manifest_response.json()
    assert manifest["entries"][0]["source"] == "spreadsheet_migration"

    forged = deepcopy(manifest)
    forged["entries"][0]["content"] = "伪造来源内容"
    forged_preview = await async_client.post(
        f"/api/world/entities/{source_entity.id}/dossier/manifest/preview",
        params={"novel_id": novel_id},
        json={"manifest": forged},
    )
    assert forged_preview.status_code == 409, forged_preview.text

    copy_entity = await async_client.post(
        "/api/world/entities",
        params={"novel_id": novel_id},
        json={"entity_type": "character", "name": "云岚副本", "status": "canonical"},
    )
    assert copy_entity.status_code == 201, copy_entity.text
    copy_id = copy_entity.json()["id"]
    preview_request = {"manifest": manifest}
    preview = await async_client.post(
        f"/api/world/entities/{copy_id}/dossier/manifest/preview",
        params={"novel_id": novel_id},
        json=preview_request,
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["create_count"] == 1
    imported = await async_client.post(
        f"/api/world/entities/{copy_id}/dossier/manifest/apply",
        params={"novel_id": novel_id},
        json={
            **preview_request,
            "expected_preview_hash": preview.json()["preview_hash"],
            "confirmed": True,
        },
    )
    assert imported.status_code == 200, imported.text
    assert imported.json()["applied_count"] == 1
    replay_preview = await async_client.post(
        f"/api/world/entities/{copy_id}/dossier/manifest/preview",
        params={"novel_id": novel_id},
        json=preview_request,
    )
    assert replay_preview.status_code == 200, replay_preview.text
    assert replay_preview.json()["already_imported_count"] == 1
    stale_apply = await async_client.post(
        f"/api/world/entities/{copy_id}/dossier/manifest/apply",
        params={"novel_id": novel_id},
        json={
            **preview_request,
            "expected_preview_hash": preview.json()["preview_hash"],
            "confirmed": True,
        },
    )
    assert stale_apply.status_code == 409, stale_apply.text
    replay_apply = await async_client.post(
        f"/api/world/entities/{copy_id}/dossier/manifest/apply",
        params={"novel_id": novel_id},
        json={
            **preview_request,
            "expected_preview_hash": replay_preview.json()["preview_hash"],
            "confirmed": True,
        },
    )
    assert replay_apply.status_code == 200, replay_apply.text
    assert replay_apply.json()["applied_count"] == 0
    traces = list(
        (
            await db_session.scalars(
                select(AssistantOperationTrace).where(
                    AssistantOperationTrace.novel_id == custom_row.novel_id,
                )
            )
        ).all()
    )
    assert {(row.op_id, row.event_type) for row in traces} >= {
        ("world.dossier.template.borrowed.edit", "executed"),
        ("world.dossier.manifest.preview", "previewed"),
        ("world.dossier.manifest.apply", "executed"),
    }

    rollback = await async_client.post(
        f"/api/imports/migrations/{migration_id}/rollback",
        json={"novel_id": novel_id, "confirmed": True},
    )
    assert rollback.status_code == 200, rollback.text
    assert rollback.json()["reverted_count"] >= 2
    original_rows = list(
        (
            await db_session.scalars(
                select(WorldObjectDossierEntry).where(
                    WorldObjectDossierEntry.novel_id == custom_row.novel_id,
                    WorldObjectDossierEntry.entity_id == source_entity.id,
                )
            )
        ).all()
    )
    assert any(row.status == "cleared" for row in original_rows)
    imported_read = await async_client.get(
        f"/api/world/entities/{copy_id}/dossier", params={"novel_id": novel_id}
    )
    assert imported_read.json()["entries"][0]["visibility"] == "secret"


async def test_manifest_apply_rechecks_source_revision_after_preview(
    async_client,
) -> None:
    project = await async_client.post("/api/projects", json={"title": "来源修订并发门禁"})
    assert project.status_code == 201, project.text
    novel_id = project.json()["id"]
    source = await async_client.post(
        "/api/world/entities",
        params={"novel_id": novel_id},
        json={"entity_type": "character", "name": "来源", "status": "canonical"},
    )
    target = await async_client.post(
        "/api/world/entities",
        params={"novel_id": novel_id},
        json={"entity_type": "character", "name": "目标", "status": "canonical"},
    )
    assert source.status_code == target.status_code == 201
    source_id, target_id = source.json()["id"], target.json()["id"]
    entry = await async_client.post(
        f"/api/world/entities/{source_id}/dossier/entries",
        params={"novel_id": novel_id},
        json={"facing": {"kind": "core", "key": "appearance"}, "content": "银发"},
    )
    assert entry.status_code == 201, entry.text
    exported = await async_client.get(
        f"/api/world/entities/{source_id}/dossier/manifest",
        params={"novel_id": novel_id},
    )
    assert exported.status_code == 200, exported.text
    request = {"manifest": exported.json()}
    preview = await async_client.post(
        f"/api/world/entities/{target_id}/dossier/manifest/preview",
        params={"novel_id": novel_id},
        json=request,
    )
    assert preview.status_code == 200, preview.text
    edit = await async_client.patch(
        f"/api/world/entities/{source_id}/dossier/entries/{entry.json()['id']}",
        params={"novel_id": novel_id},
        json={"expected_revision_id": entry.json()["id"], "content": "黑发"},
    )
    assert edit.status_code == 200, edit.text
    stale = await async_client.post(
        f"/api/world/entities/{target_id}/dossier/manifest/apply",
        params={"novel_id": novel_id},
        json={
            **request,
            "expected_preview_hash": preview.json()["preview_hash"],
            "confirmed": True,
        },
    )
    assert stale.status_code == 409, stale.text
    target_read = await async_client.get(
        f"/api/world/entities/{target_id}/dossier", params={"novel_id": novel_id}
    )
    assert target_read.status_code == 200
    assert target_read.json()["entries"] == []


async def test_strong_profile_manifest_v2_roundtrips_array_across_projects_on_postgres(
    async_client,
) -> None:
    source_project = await async_client.post(
        "/api/projects", json={"title": "强档案manifest来源"}
    )
    target_project = await async_client.post(
        "/api/projects", json={"title": "强档案manifest目标"}
    )
    assert source_project.status_code == target_project.status_code == 201
    source_novel_id = source_project.json()["id"]
    target_novel_id = target_project.json()["id"]
    source = await async_client.post(
        "/api/world/entities",
        params={"novel_id": source_novel_id},
        json={"entity_type": "species", "name": "来源灵族", "status": "canonical"},
    )
    target = await async_client.post(
        "/api/world/entities",
        params={"novel_id": target_novel_id},
        json={"entity_type": "species", "name": "目标灵族", "status": "canonical"},
    )
    assert source.status_code == target.status_code == 201
    source_id, target_id = source.json()["id"], target.json()["id"]
    original = [{"name": "夜视", "range": ["月下", "洞穴"]}, {"name": "耐寒"}]
    saved = await async_client.put(
        f"/api/world/profiles/{source_id}",
        params={"novel_id": source_novel_id},
        json={"status": "canonical", "abilities_json": original},
    )
    assert saved.status_code == 200, saved.text
    exported = await async_client.get(
        f"/api/world/entities/{source_id}/dossier/manifest",
        params={"novel_id": source_novel_id},
    )
    assert exported.status_code == 200, exported.text
    manifest = exported.json()
    assert manifest["format_version"] == 2
    compatibility = next(
        entry["compatibility"]
        for entry in manifest["entries"]
        if entry.get("compatibility")
    )
    assert compatibility["legacy_field_key"] == "species_profiles.abilities_json"
    assert compatibility["legacy_value"] == original

    request = {"manifest": manifest}
    preview = await async_client.post(
        f"/api/world/entities/{target_id}/dossier/manifest/preview",
        params={"novel_id": target_novel_id},
        json=request,
    )
    assert preview.status_code == 200, preview.text
    applied = await async_client.post(
        f"/api/world/entities/{target_id}/dossier/manifest/apply",
        params={"novel_id": target_novel_id},
        json={
            **request,
            "expected_preview_hash": preview.json()["preview_hash"],
            "confirmed": True,
        },
    )
    assert applied.status_code == 200, applied.text
    profile = await async_client.get(
        f"/api/world/profiles/{target_id}", params={"novel_id": target_novel_id}
    )
    assert profile.status_code == 200, profile.text
    assert profile.json()["fields"]["abilities_json"] == original


async def test_generic_manifest_rejects_existing_target_field_chain_on_postgres(
    async_client,
    db_session: AsyncSession,
) -> None:
    project = await async_client.post("/api/projects", json={"title": "PG 通用字段冲突"})
    assert project.status_code == 201, project.text
    params = {"novel_id": project.json()["id"]}
    entities = []
    for name, values in (("来源山灵", ["来源内容"]), ("目标山灵", ["第一版", "第二版"])):
        created = await async_client.post(
            "/api/world/entities",
            params=params,
            json={"entity_type": "spirit_beast", "name": name, "status": "canonical"},
        )
        assert created.status_code == 201, created.text
        entity_id = created.json()["id"]
        entities.append(entity_id)
        for value in values:
            saved = await async_client.put(
                f"/api/world/profiles/{entity_id}",
                params=params,
                json={"data_json": {"private_extension": value}},
            )
            assert saved.status_code == 200, saved.text
    source_id, target_id = entities
    exported = await async_client.get(
        f"/api/world/entities/{source_id}/dossier/manifest",
        params=params,
    )
    assert exported.status_code == 200, exported.text
    base_url = f"/api/world/entities/{target_id}/dossier/manifest"
    request = {"manifest": exported.json()}
    preview = await async_client.post(f"{base_url}/preview", params=params, json=request)
    assert preview.status_code == 200, preview.text
    assert preview.json()["can_apply"] is False
    assert preview.json()["conflicts"][0]["reason"] == "target_group_collision"
    applied = await async_client.post(
        f"{base_url}/apply",
        params=params,
        json={
            **request,
            "confirmed": True,
            "expected_preview_hash": preview.json()["preview_hash"],
        },
    )
    assert applied.status_code == 409, applied.text
    profile = await async_client.get(f"/api/world/profiles/{target_id}", params=params)
    assert profile.json()["data_json"] == {"private_extension": "第二版"}
    rows = list(
        (
            await db_session.scalars(
                select(WorldObjectDossierEntry).where(
                    WorldObjectDossierEntry.entity_id == target_id
                )
            )
        ).all()
    )
    assert len(rows) == 2
    assert len({row.entry_group_id for row in rows}) == 1
