"""World dossier revision and legacy Character compatibility regressions."""

import uuid
from copy import deepcopy

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from core.errors import NotFoundError
from modules.account.context import bind_principal, reset_principal
from modules.account.contracts import AccountPrincipal
from modules.account.models import Account
from modules.project.models import Project
from modules.world.dossier_service import WorldObjectDossierService
from modules.world.models import (
    Character,
    CoreEntity,
    GenericEntityProfile,
    WorldObjectDossierEntry,
)
from modules.world.project_vocabulary_schemas import VocabularyTermCreate
from modules.world.project_vocabulary_service import (
    archive_project_vocabulary_term,
    create_project_vocabulary_term,
)
from modules.world.schemas.dossier import (
    DossierEntryCreate,
    DossierFacingRef,
    DossierTemplateAuthorUpsert,
    DossierTemplateUpsert,
)


async def _project_and_character(async_client: AsyncClient) -> tuple[str, dict]:
    project = await async_client.post("/api/projects", json={"title": "对象档案测试"})
    assert project.status_code == 201, project.text
    novel_id = project.json()["id"]
    entity = await async_client.post(
        "/api/world/entities",
        params={"novel_id": novel_id},
        json={"entity_type": "character", "name": "测试人物", "status": "canonical"},
    )
    assert entity.status_code == 201, entity.text
    return novel_id, entity.json()


@pytest.mark.asyncio
async def test_character_legacy_fields_coalesce_and_null_clears(
    async_client: AsyncClient,
) -> None:
    novel_id, entity = await _project_and_character(async_client)
    entity_id = entity["id"]

    create_url = f"/api/world/entities/{entity_id}/dossier/entries"
    params = {"novel_id": novel_id}
    first = await async_client.post(
        create_url,
        params=params,
        json={
            "facing": {"kind": "core", "key": "appearance"},
            "legacy_field_key": "appearance",
            "content": "眼尾上挑",
        },
    )
    second = await async_client.post(
        create_url,
        params=params,
        json={
            "facing": {"kind": "core", "key": "appearance"},
            "legacy_field_key": "appearance",
            "content": "左眉有浅疤",
        },
    )
    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text

    character_url = f"/api/world/characters/{entity_id}"
    current = await async_client.get(character_url, params=params)
    assert current.status_code == 200, current.text
    assert current.json()["appearance"] == "眼尾上挑\n左眉有浅疤"

    read_first_page = await async_client.get(
        f"/api/world/entities/{entity_id}/dossier",
        params={**params, "limit": 1, "offset": 0},
    )
    read_second_page = await async_client.get(
        f"/api/world/entities/{entity_id}/dossier",
        params={**params, "limit": 1, "offset": 1},
    )
    assert read_first_page.json()["total_count"] == 2
    assert read_first_page.json()["omitted_count"] == 1
    assert read_second_page.json()["entries"][0]["content"] == "左眉有浅疤"
    beyond_end = await async_client.get(
        f"/api/world/entities/{entity_id}/dossier",
        params={**params, "limit": 1, "offset": 100},
    )
    assert beyond_end.status_code == 200
    assert beyond_end.json()["entries"] == []
    assert beyond_end.json()["total_count"] == 2
    assert beyond_end.json()["unknown"] is False

    note = await async_client.put(
        character_url,
        params=params,
        json={
            "current_goal": "作者备注：寻找失踪的妹妹",
            "expected_updated_at": current.json()["updated_at"],
        },
    )
    assert note.status_code == 200, note.text
    assert note.json()["current_goal"] == "作者备注：寻找失踪的妹妹"

    same = await async_client.put(
        character_url,
        params=params,
        json={
            "appearance": current.json()["appearance"],
            "expected_updated_at": note.json()["updated_at"],
        },
    )
    assert same.status_code == 200, same.text
    assert same.json()["current_goal"] == "作者备注：寻找失踪的妹妹"
    history_url = f"/api/world/entities/{entity_id}/dossier/history"
    history = await async_client.get(history_url, params=params)
    assert history.status_code == 200, history.text
    assert history.json()["total_count"] == 2

    rewritten = await async_client.put(
        character_url,
        params=params,
        json={
            "appearance": "短发，左眉有疤",
            "expected_updated_at": same.json()["updated_at"],
        },
    )
    assert rewritten.status_code == 200, rewritten.text
    assert rewritten.json()["appearance"] == "短发，左眉有疤"
    history = await async_client.get(history_url, params=params)
    assert history.json()["total_count"] == 3
    active = [
        item
        for item in history.json()["entries"]
        if item["legacy_field_key"] == "appearance" and item["status"] == "active"
    ]
    assert len(active) == 1
    assert active[0]["content"] == "短发，左眉有疤"

    cleared = await async_client.put(
        character_url,
        params=params,
        json={"appearance": None, "expected_updated_at": rewritten.json()["updated_at"]},
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["appearance"] is None
    history = await async_client.get(history_url, params=params)
    assert history.json()["total_count"] == 4
    assert any(item["status"] == "cleared" for item in history.json()["entries"])

    # A shared core facing does not guess whether a free entry belongs to desire
    # or fear; callers opt into the old-field projection with legacy_field_key.
    free_entry = await async_client.post(
        create_url,
        params=params,
        json={
            "facing": {"kind": "core", "key": "desire_fear"},
            "content": "独立档案条目",
        },
    )
    assert free_entry.status_code == 201, free_entry.text
    character = await async_client.get(character_url, params=params)
    assert character.json()["desire"] is None
    assert character.json()["fear"] is None


@pytest.mark.asyncio
async def test_dossier_patch_null_stale_cas_and_restore(
    async_client: AsyncClient,
) -> None:
    novel_id, entity = await _project_and_character(async_client)
    entity_id = entity["id"]
    params = {"novel_id": novel_id}
    create_url = f"/api/world/entities/{entity_id}/dossier/entries"
    created = await async_client.post(
        create_url,
        params=params,
        json={
            "facing": {"kind": "core", "key": "personality"},
            "content": "遇事先核对证据",
            "tags": ["习惯"],
        },
    )
    assert created.status_code == 201, created.text
    original = created.json()

    patch_url = f"/api/world/entities/{entity_id}/dossier/entries/{original['id']}"
    tagged = await async_client.patch(
        patch_url,
        params=params,
        json={"expected_revision_id": original["id"], "tags": None},
    )
    assert tagged.status_code == 200, tagged.text
    assert tagged.json()["content"] == "遇事先核对证据"
    assert tagged.json()["tags"] == []
    current_id = tagged.json()["id"]

    no_op = await async_client.patch(
        f"/api/world/entities/{entity_id}/dossier/entries/{current_id}",
        params=params,
        json={"expected_revision_id": current_id, "tags": []},
    )
    assert no_op.status_code == 200, no_op.text
    assert no_op.json()["id"] == current_id

    stale = await async_client.patch(
        patch_url,
        params=params,
        json={"expected_revision_id": original["id"], "content": "覆盖"},
    )
    assert stale.status_code == 409, stale.text

    cleared = await async_client.patch(
        f"/api/world/entities/{entity_id}/dossier/entries/{current_id}",
        params=params,
        json={"expected_revision_id": current_id, "content": None},
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["status"] == "cleared"
    assert cleared.json()["content"] == ""

    restore = await async_client.post(
        f"/api/world/entities/{entity_id}/dossier/groups/{original['entry_group_id']}/restore",
        params=params,
        json={"revision_id": current_id, "expected_current_revision_id": None},
    )
    assert restore.status_code == 200, restore.text
    assert restore.json()["content"] == "遇事先核对证据"
    assert restore.json()["restored_from_id"] == current_id


@pytest.mark.asyncio
async def test_dossier_template_is_versioned_and_same_value_is_idempotent(
    async_client: AsyncClient,
) -> None:
    project = await async_client.post("/api/projects", json={"title": "档案模板测试"})
    assert project.status_code == 201, project.text
    novel_id = project.json()["id"]
    params = {"novel_id": novel_id}
    url = "/api/world/dossier-templates/character"
    body = {
        "fields": [
            {
                "facing": {"kind": "core", "key": "appearance"},
                "label": "外貌",
                "required": True,
                "value_kind": "text",
            }
        ],
        "display_schema": {"layout": "compact"},
    }
    created = await async_client.put(url, params=params, json=body)
    assert created.status_code == 200, created.text
    assert created.json()["version_number"] == 1

    same = await async_client.put(
        url,
        params=params,
        json={**body, "expected_version_number": 1},
    )
    assert same.status_code == 200, same.text
    assert same.json()["revision_id"] == created.json()["revision_id"]

    changed_body = {
        **body,
        "expected_version_number": 1,
        "display_schema": {"layout": "editorial"},
    }
    changed = await async_client.put(url, params=params, json=changed_body)
    assert changed.status_code == 200, changed.text
    assert changed.json()["version_number"] == 2

    stale = await async_client.put(url, params=params, json=changed_body)
    assert stale.status_code == 409, stale.text
    history = await async_client.get(f"{url}/history", params=params)
    assert history.status_code == 200, history.text
    assert history.json()["total_count"] == 2


@pytest.mark.asyncio
async def test_custom_type_borrows_namespaced_core_facings_without_type_conversion(
    async_client: AsyncClient,
    db_session,
) -> None:
    assert set(DossierFacingRef.model_json_schema()["properties"]) == {
        "kind",
        "key",
        "term_id",
    }
    assert (
        "borrowed_facings" not in DossierTemplateUpsert.model_json_schema()["properties"]
    )
    assert (
        "borrowed_facings"
        in DossierTemplateAuthorUpsert.model_json_schema()["properties"]
    )
    project = await async_client.post("/api/projects", json={"title": "灵兽档案"})
    assert project.status_code == 201, project.text
    novel_id = project.json()["id"]
    params = {"novel_id": novel_id}
    entity_response = await async_client.post(
        "/api/world/entities",
        params=params,
        json={"entity_type": "spirit_beast", "name": "照夜", "status": "canonical"},
    )
    assert entity_response.status_code == 201, entity_response.text
    entity = entity_response.json()

    create_url = f"/api/world/entities/{entity['id']}/dossier/entries"
    rejected = await async_client.post(
        create_url,
        params=params,
        json={"facing": {"kind": "core", "key": "appearance"}, "content": "月白鳞片"},
    )
    assert rejected.status_code == 400

    template_url = "/api/world/dossier-templates/spirit_beast"
    author_template_url = f"{template_url}/author"
    saved = await async_client.put(
        author_template_url,
        params=params,
        json={
            "fields": [],
            "borrowed_facings": [
                {"kind": "core", "key": "borrowed:character:appearance"},
                {"kind": "core", "key": "borrowed:species:appearance"},
            ],
        },
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["version_number"] == 1

    old_ai_edit = await WorldObjectDossierService().upsert_template(
        db_session,
        novel_id,
        "spirit_beast",
        DossierTemplateUpsert(
            expected_version_number=1,
            fields=[],
            display_schema={"legacy_ai_edit": True},
        ),
    )
    assert "borrowed_facings" not in old_ai_edit.model_dump(mode="json")
    author_read = await async_client.get(author_template_url, params=params)
    assert author_read.status_code == 200, author_read.text
    assert {item["key"] for item in author_read.json()["borrowed_facings"]} == {
        "borrowed:character:appearance",
        "borrowed:species:appearance",
    }
    history = await async_client.get(f"{template_url}/history", params=params)
    assert history.json()["items"][0]["snapshot"]["format_version"] == 2

    facets = await async_client.get(
        f"/api/world/entities/{entity['id']}/dossier/facets", params=params
    )
    borrowed = [
        item
        for item in facets.json()["items"]
        if str(item["facing"].get("key", "")).startswith("borrowed:")
    ]
    assert {item["facing"]["key"] for item in borrowed} == {
        "borrowed:character:appearance",
        "borrowed:species:appearance",
    }

    for source_type, content in (
        ("character", "主人曾救下一名幼崽"),
        ("species", "夜间能辨认灵脉纹路"),
    ):
        response = await async_client.post(
            create_url,
            params=params,
            json={
                "facing": {
                    "kind": "core",
                    "key": f"borrowed:{source_type}:appearance",
                },
                "content": content,
            },
        )
        assert response.status_code == 201, response.text
        assert response.json()["facing"]["key"] == f"borrowed:{source_type}:appearance"

    core_entity = await db_session.get(CoreEntity, uuid.UUID(entity["id"]))
    assert core_entity is not None and core_entity.entity_type == "spirit_beast"
    character = await db_session.scalar(
        select(Character).where(
            Character.novel_id == uuid.UUID(novel_id),
            Character.entity_id == uuid.UUID(entity["id"]),
        )
    )
    assert character is None

    template_update = await async_client.put(
        author_template_url,
        params=params,
        json={
            "expected_version_number": 2,
            "fields": [],
            "borrowed_facings": [{"kind": "core", "key": "borrowed:species:appearance"}],
        },
    )
    assert template_update.status_code == 400, template_update.text
    dossier = await async_client.get(
        f"/api/world/entities/{entity['id']}/dossier", params=params
    )
    character_entry = next(
        item
        for item in dossier.json()["entries"]
        if item["facing"]["key"] == "borrowed:character:appearance"
    )
    clear_character = await async_client.patch(
        f"/api/world/entities/{entity['id']}/dossier/entries/{character_entry['id']}",
        params=params,
        json={"expected_revision_id": character_entry["id"], "content": ""},
    )
    assert clear_character.status_code == 200, clear_character.text
    template_update = await async_client.put(
        author_template_url,
        params=params,
        json={
            "expected_version_number": 2,
            "fields": [],
            "borrowed_facings": [{"kind": "core", "key": "borrowed:species:appearance"}],
        },
    )
    assert template_update.status_code == 200, template_update.text
    rejected_restore = await async_client.post(
        f"/api/world/entities/{entity['id']}/dossier/groups/{character_entry['entry_group_id']}/restore",
        params=params,
        json={
            "revision_id": character_entry["id"],
            "expected_current_revision_id": clear_character.json()["id"],
        },
    )
    assert rejected_restore.status_code == 400, rejected_restore.text
    rejected_removed_face = await async_client.post(
        create_url,
        params=params,
        json={
            "facing": {
                "kind": "core",
                "key": "borrowed:character:appearance",
            },
            "content": "不能再新增这类面向",
        },
    )
    assert rejected_removed_face.status_code == 400
    dossier = await async_client.get(
        f"/api/world/entities/{entity['id']}/dossier", params=params
    )
    assert len(dossier.json()["entries"]) == 1


@pytest.mark.asyncio
async def test_dossier_manifest_roundtrip_requires_cross_project_maps(
    async_client: AsyncClient,
) -> None:
    source_project = await async_client.post(
        "/api/projects", json={"title": "清单来源项目"}
    )
    assert source_project.status_code == 201, source_project.text
    source_novel_id = source_project.json()["id"]
    source_term = await async_client.post(
        f"/api/world/project-vocabulary/{source_novel_id}/terms",
        json={"kind": "dossier_facing", "name": "修行境界"},
    )
    assert source_term.status_code == 201, source_term.text
    source_entity = await async_client.post(
        "/api/world/entities",
        params={"novel_id": source_novel_id},
        json={"entity_type": "character", "name": "清单人物", "status": "canonical"},
    )
    assert source_entity.status_code == 201, source_entity.text
    source_entity_id = source_entity.json()["id"]
    template = await async_client.put(
        "/api/world/dossier-templates/character",
        params={"novel_id": source_novel_id},
        json={
            "fields": [
                {
                    "facing": {"kind": "project", "term_id": source_term.json()["id"]},
                    "label": "修行境界",
                }
            ]
        },
    )
    assert template.status_code == 200, template.text
    source_entry = await async_client.post(
        f"/api/world/entities/{source_entity_id}/dossier/entries",
        params={"novel_id": source_novel_id},
        json={
            "facing": {"kind": "project", "term_id": source_term.json()["id"]},
            "content": "已至筑基后期",
            "visibility": "secret",
        },
    )
    assert source_entry.status_code == 201, source_entry.text

    exported = await async_client.get(
        f"/api/world/entities/{source_entity_id}/dossier/manifest",
        params={"novel_id": source_novel_id},
    )
    assert exported.status_code == 200, exported.text
    manifest = exported.json()
    assert manifest["format"] == "novelcraft.world.dossier-manifest"
    assert manifest["source_entity_id"] == source_entity_id
    assert manifest["template"]["source_version_number"] == 1
    assert manifest["entries"][0]["visibility"] == "secret"
    assert manifest["entries"][0]["source_revision_id"] == source_entry.json()["id"]

    same_project_target = await async_client.post(
        "/api/world/entities",
        params={"novel_id": source_novel_id},
        json={"entity_type": "character", "name": "清单副本", "status": "canonical"},
    )
    assert same_project_target.status_code == 201, same_project_target.text
    same_project_request = {
        "manifest": manifest,
        "expected_template_version_number": 1,
        "template_mapping_confirmed": True,
        "confirmed": True,
    }
    preview_url = (
        f"/api/world/entities/{same_project_target.json()['id']}/dossier/manifest/preview"
    )
    apply_url = (
        f"/api/world/entities/{same_project_target.json()['id']}/dossier/manifest/apply"
    )
    preview = await async_client.post(
        preview_url,
        params={"novel_id": source_novel_id},
        json={
            key: value
            for key, value in same_project_request.items()
            if key != "confirmed"
        },
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["can_apply"] is True
    assert preview.json()["create_count"] == 1
    first_apply = await async_client.post(
        apply_url,
        params={"novel_id": source_novel_id},
        json={
            **same_project_request,
            "expected_preview_hash": preview.json()["preview_hash"],
        },
    )
    assert first_apply.status_code == 200, first_apply.text
    assert first_apply.json()["applied_count"] == 1

    repeated_preview = await async_client.post(
        preview_url,
        params={"novel_id": source_novel_id},
        json={
            key: value
            for key, value in same_project_request.items()
            if key != "confirmed"
        },
    )
    assert repeated_preview.status_code == 200, repeated_preview.text
    assert repeated_preview.json()["already_imported_count"] == 1
    repeated_apply = await async_client.post(
        apply_url,
        params={"novel_id": source_novel_id},
        json={
            **same_project_request,
            "expected_preview_hash": repeated_preview.json()["preview_hash"],
        },
    )
    assert repeated_apply.status_code == 200, repeated_apply.text
    assert repeated_apply.json()["applied_count"] == 0

    target_entity_id = same_project_target.json()["id"]
    target_read = await async_client.get(
        f"/api/world/entities/{target_entity_id}/dossier",
        params={"novel_id": source_novel_id},
    )
    imported_entry = target_read.json()["entries"][0]
    edited = await async_client.patch(
        f"/api/world/entities/{target_entity_id}/dossier/entries/{imported_entry['id']}",
        params={"novel_id": source_novel_id},
        json={
            "expected_revision_id": imported_entry["id"],
            "content": "作者已经改过的内容",
        },
    )
    assert edited.status_code == 200, edited.text
    changed_preview_request = {
        key: value for key, value in same_project_request.items() if key != "confirmed"
    }
    changed_preview = await async_client.post(
        preview_url,
        params={"novel_id": source_novel_id},
        json=changed_preview_request,
    )
    assert changed_preview.status_code == 200, changed_preview.text
    assert changed_preview.json()["can_apply"] is False
    assert changed_preview.json()["conflicts"][0]["reason"] == "already_changed"
    skipped_request = {
        **changed_preview_request,
        "skip_conflicts": [source_entry.json()["id"]],
    }
    skipped_preview = await async_client.post(
        preview_url,
        params={"novel_id": source_novel_id},
        json=skipped_request,
    )
    assert skipped_preview.status_code == 200, skipped_preview.text
    assert skipped_preview.json()["can_apply"] is True
    assert skipped_preview.json()["skipped_count"] == 1
    skipped_apply = await async_client.post(
        apply_url,
        params={"novel_id": source_novel_id},
        json={
            **skipped_request,
            "confirmed": True,
            "expected_preview_hash": skipped_preview.json()["preview_hash"],
        },
    )
    assert skipped_apply.status_code == 200, skipped_apply.text
    assert skipped_apply.json()["updated_count"] == 0

    target_project = await async_client.post(
        "/api/projects", json={"title": "清单目标项目"}
    )
    assert target_project.status_code == 201, target_project.text
    target_novel_id = target_project.json()["id"]
    target_term = await async_client.post(
        f"/api/world/project-vocabulary/{target_novel_id}/terms",
        json={"kind": "dossier_facing", "name": "修行境界"},
    )
    assert target_term.status_code == 201, target_term.text
    target_entity = await async_client.post(
        "/api/world/entities",
        params={"novel_id": target_novel_id},
        json={"entity_type": "character", "name": "跨项目副本", "status": "canonical"},
    )
    assert target_entity.status_code == 201, target_entity.text
    target_template = await async_client.put(
        "/api/world/dossier-templates/character",
        params={"novel_id": target_novel_id},
        json={
            "fields": [
                {
                    "facing": {"kind": "project", "term_id": target_term.json()["id"]},
                    "label": "修行境界",
                }
            ]
        },
    )
    assert target_template.status_code == 200, target_template.text
    cross_preview_url = (
        f"/api/world/entities/{target_entity.json()['id']}/dossier/manifest/preview"
    )
    cross_apply_url = (
        f"/api/world/entities/{target_entity.json()['id']}/dossier/manifest/apply"
    )
    unmapped = await async_client.post(
        cross_preview_url,
        params={"novel_id": target_novel_id},
        json={
            "manifest": manifest,
            "expected_template_version_number": 1,
            "template_mapping_confirmed": True,
        },
    )
    assert unmapped.status_code == 400

    cross_request = {
        "manifest": manifest,
        "facing_mappings": [
            {
                "source": {"kind": "project", "term_id": source_term.json()["id"]},
                "target": {"kind": "project", "term_id": target_term.json()["id"]},
            }
        ],
        "expected_template_version_number": 1,
        "template_mapping_confirmed": True,
    }
    cross_preview = await async_client.post(
        cross_preview_url,
        params={"novel_id": target_novel_id},
        json=cross_request,
    )
    assert cross_preview.status_code == 200, cross_preview.text
    assert cross_preview.json()["can_apply"] is True
    cross_apply = await async_client.post(
        cross_apply_url,
        params={"novel_id": target_novel_id},
        json={
            **cross_request,
            "confirmed": True,
            "expected_preview_hash": cross_preview.json()["preview_hash"],
        },
    )
    assert cross_apply.status_code == 200, cross_apply.text
    read_target = await async_client.get(
        f"/api/world/entities/{target_entity.json()['id']}/dossier",
        params={"novel_id": target_novel_id},
    )
    imported = read_target.json()["entries"][0]
    assert imported["content"] == "已至筑基后期"
    assert imported["visibility"] == "secret"
    assert imported["facing"]["term_id"] == target_term.json()["id"]


@pytest.mark.asyncio
async def test_generic_profile_unmapped_json_roundtrips_through_cross_project_manifest(
    async_client: AsyncClient,
    db_session,
) -> None:
    source_project = await async_client.post(
        "/api/projects", json={"title": "通用旧档案来源"}
    )
    target_project = await async_client.post(
        "/api/projects", json={"title": "通用旧档案目标"}
    )
    assert source_project.status_code == 201, source_project.text
    assert target_project.status_code == 201, target_project.text
    source_novel_id = source_project.json()["id"]
    target_novel_id = target_project.json()["id"]
    source_entity = await async_client.post(
        "/api/world/entities",
        params={"novel_id": source_novel_id},
        json={"entity_type": "spirit_beast", "name": "来源山灵", "status": "canonical"},
    )
    target_entity = await async_client.post(
        "/api/world/entities",
        params={"novel_id": target_novel_id},
        json={"entity_type": "spirit_beast", "name": "目标山灵", "status": "canonical"},
    )
    assert source_entity.status_code == 201, source_entity.text
    assert target_entity.status_code == 201, target_entity.text
    raw_value = {"nested": [None, 1, {"ok": True}]}
    saved_profile = await async_client.put(
        f"/api/world/profiles/{source_entity.json()['id']}",
        params={"novel_id": source_novel_id},
        json={"data_json": {"unregistered_extension": raw_value}},
    )
    assert saved_profile.status_code == 200, saved_profile.text
    exported = await async_client.get(
        f"/api/world/entities/{source_entity.json()['id']}/dossier/manifest",
        params={"novel_id": source_novel_id},
    )
    assert exported.status_code == 200, exported.text
    manifest = exported.json()
    compatibility_entry = next(
        item for item in manifest["entries"] if item.get("compatibility")
    )
    assert compatibility_entry["compatibility"]["legacy_value"] == raw_value
    assert compatibility_entry["compatibility"]["generic_unmapped"] is True
    assert compatibility_entry["visibility"] == "secret"

    preview_url = (
        f"/api/world/entities/{target_entity.json()['id']}/dossier/manifest/preview"
    )
    apply_url = (
        f"/api/world/entities/{target_entity.json()['id']}/dossier/manifest/apply"
    )
    preview = await async_client.post(
        preview_url,
        params={"novel_id": target_novel_id},
        json={"manifest": manifest},
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["can_apply"] is True
    applied = await async_client.post(
        apply_url,
        params={"novel_id": target_novel_id},
        json={
            "manifest": manifest,
            "confirmed": True,
            "expected_preview_hash": preview.json()["preview_hash"],
        },
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["applied_count"] == len(manifest["entries"])
    legacy_read = await async_client.get(
        f"/api/world/profiles/{target_entity.json()['id']}",
        params={"novel_id": target_novel_id},
    )
    assert legacy_read.status_code == 200, legacy_read.text
    assert legacy_read.json()["data_json"]["unregistered_extension"] == raw_value
    public_dossier = await WorldObjectDossierService().read(
        db_session,
        target_novel_id,
        target_entity.json()["id"],
        visibility_filter="public",
    )
    assert all(
        item.get("legacy_field_key")
        != compatibility_entry["compatibility"]["legacy_field_key"]
        for item in public_dossier.entries
    )


@pytest.mark.asyncio
async def test_strong_profile_json_and_v1_manifest_roundtrip(
    async_client: AsyncClient,
) -> None:
    source_project = await async_client.post(
        "/api/projects", json={"title": "强档案来源"}
    )
    target_project = await async_client.post(
        "/api/projects", json={"title": "强档案目标"}
    )
    assert source_project.status_code == target_project.status_code == 201
    source_novel_id = source_project.json()["id"]
    target_novel_id = target_project.json()["id"]
    source_entity = await async_client.post(
        "/api/world/entities",
        params={"novel_id": source_novel_id},
        json={"entity_type": "species", "name": "来源灵族", "status": "canonical"},
    )
    target_entity = await async_client.post(
        "/api/world/entities",
        params={"novel_id": target_novel_id},
        json={"entity_type": "species", "name": "目标灵族", "status": "canonical"},
    )
    assert source_entity.status_code == target_entity.status_code == 201
    value = [{"name": "夜视", "range": ["月下", "洞穴"]}, {"name": "耐寒"}]
    saved = await async_client.put(
        f"/api/world/profiles/{source_entity.json()['id']}",
        params={"novel_id": source_novel_id},
        json={"status": "canonical", "abilities_json": value},
    )
    assert saved.status_code == 200, saved.text
    exported = await async_client.get(
        f"/api/world/entities/{source_entity.json()['id']}/dossier/manifest",
        params={"novel_id": source_novel_id},
    )
    assert exported.status_code == 200, exported.text
    manifest = exported.json()
    strong_entry = next(
        item for item in manifest["entries"] if item.get("compatibility")
    )
    assert strong_entry["compatibility"]["legacy_value"] == value
    assert (
        strong_entry["compatibility"]["legacy_field_key"]
        == "species_profiles.abilities_json"
    )

    # Version 1 remains readable with the old entry shape.
    v1_manifest = {**deepcopy(manifest), "format_version": 1}
    for item in v1_manifest["entries"]:
        item.pop("compatibility", None)
    from modules.world.schemas.dossier_manifest import DossierManifest

    assert DossierManifest.model_validate(v1_manifest).format_version == 1
    preview_url = (
        f"/api/world/entities/{target_entity.json()['id']}/dossier/manifest/preview"
    )
    apply_url = (
        f"/api/world/entities/{target_entity.json()['id']}/dossier/manifest/apply"
    )
    preview = await async_client.post(
        preview_url,
        params={"novel_id": target_novel_id},
        json={"manifest": manifest},
    )
    assert preview.status_code == 200, preview.text
    applied = await async_client.post(
        apply_url,
        params={"novel_id": target_novel_id},
        json={
            "manifest": manifest,
            "confirmed": True,
            "expected_preview_hash": preview.json()["preview_hash"],
        },
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["applied_count"] == len(manifest["entries"])
    target_dossier = await async_client.get(
        f"/api/world/entities/{target_entity.json()['id']}/dossier",
        params={"novel_id": target_novel_id},
    )
    assert target_dossier.status_code == 200, target_dossier.text
    assert target_dossier.json()["entries"], target_dossier.json()
    assert any(
        item["legacy_field_key"] == "species_profiles.abilities_json"
        for item in target_dossier.json()["entries"]
    ), repr(target_dossier.json()["entries"][0])
    target_profile = await async_client.get(
        f"/api/world/profiles/{target_entity.json()['id']}",
        params={"novel_id": target_novel_id},
    )
    assert target_profile.status_code == 200, target_profile.text
    assert target_profile.json()["fields"].get("abilities_json") == value, (
        target_profile.json()
    )


@pytest.mark.asyncio
async def test_generic_profile_fields_map_by_template_key_and_keep_unknown_values(
    async_client: AsyncClient,
    db_session,
) -> None:
    project = await async_client.post("/api/projects", json={"title": "通用档案映射"})
    assert project.status_code == 201, project.text
    novel_id = project.json()["id"]
    entity_response = await async_client.post(
        "/api/world/entities",
        params={"novel_id": novel_id},
        json={"entity_type": "spirit_beast", "name": "山灵", "status": "canonical"},
    )
    assert entity_response.status_code == 201, entity_response.text
    entity = entity_response.json()
    term_response = await async_client.post(
        f"/api/world/project-vocabulary/{novel_id}/terms",
        json={"kind": "dossier_facing", "name": "栖居地"},
    )
    assert term_response.status_code == 201, term_response.text
    term_id = term_response.json()["id"]
    template_url = "/api/world/dossier-templates/spirit_beast"
    template = await async_client.put(
        template_url,
        params={"novel_id": novel_id},
        json={
            "fields": [
                {
                    "key": "origin_place",
                    "facing": {"kind": "project", "term_id": term_id},
                    "label": "起源地点",
                }
            ]
        },
    )
    assert template.status_code == 200, template.text
    profile = await async_client.put(
        f"/api/world/profiles/{entity['id']}",
        params={"novel_id": novel_id},
        json={
            "status": "canonical",
            "data_json": {
                "origin_place": "被废弃的根洞",
                "legacy_unknown": {"untouched": [1, 2]},
            },
        },
    )
    assert profile.status_code == 200, profile.text
    expected_revision = profile.json()["expected_dossier_revision"]
    assert len(expected_revision) == 64

    dossier = await async_client.get(
        f"/api/world/entities/{entity['id']}/dossier",
        params={"novel_id": novel_id},
    )
    assert dossier.status_code == 200, dossier.text
    fields = {item["field_key"]: item for item in dossier.json()["legacy_profile_fields"]}
    assert fields["legacy_unknown"]["mapped"] is False
    assert fields["legacy_unknown"]["value"] == {"untouched": [1, 2]}
    mapped_entry = next(
        item
        for item in dossier.json()["entries"]
        if (item["legacy_field_key"] or "").startswith("generic_profile:")
        and item["facing"]["kind"] == "project"
    )
    assert mapped_entry["facing"]["term_id"] == term_id
    assert mapped_entry["content"] == "被废弃的根洞"
    assert mapped_entry["visibility"] == "secret"
    unknown_row = await db_session.scalar(
        select(WorldObjectDossierEntry).where(
            WorldObjectDossierEntry.novel_id == uuid.UUID(novel_id),
            WorldObjectDossierEntry.entity_id == uuid.UUID(entity["id"]),
            WorldObjectDossierEntry.facing_key == "legacy_unmapped",
        )
    )
    assert unknown_row is not None and unknown_row.visibility == "secret"

    second_term = await async_client.post(
        f"/api/world/project-vocabulary/{novel_id}/terms",
        json={"kind": "dossier_facing", "name": "迁徙地"},
    )
    assert second_term.status_code == 201, second_term.text
    changed_mapping = await async_client.put(
        template_url,
        params={"novel_id": novel_id},
        json={
            "expected_version_number": 1,
            "fields": [
                {
                    "key": "origin_place",
                    "facing": {
                        "kind": "project",
                        "term_id": second_term.json()["id"],
                    },
                    "label": "错误重绑",
                }
            ],
        },
    )
    assert changed_mapping.status_code == 400, changed_mapping.text

    raw_profile = await async_client.get(
        f"/api/world/profiles/{entity['id']}", params={"novel_id": novel_id}
    )
    assert raw_profile.status_code == 200, raw_profile.text
    assert raw_profile.json()["data_json"]["origin_place"] == "被废弃的根洞"
    assert raw_profile.json()["data_json"]["legacy_unknown"] == {"untouched": [1, 2]}
    assert raw_profile.json()["expected_dossier_revision"] == expected_revision
    metadata_patch = await async_client.put(
        f"/api/world/profiles/{entity['id']}",
        params={"novel_id": novel_id},
        json={
            "expected_dossier_revision": expected_revision,
            "confidence": 0.81,
        },
    )
    assert metadata_patch.status_code == 200, metadata_patch.text
    assert metadata_patch.json()["data_json"] == raw_profile.json()["data_json"]
    expected_revision = metadata_patch.json()["expected_dossier_revision"]

    draft_profile = await async_client.put(
        f"/api/world/profiles/{entity['id']}",
        params={"novel_id": novel_id},
        json={
            "expected_dossier_revision": expected_revision,
            "status": "draft",
        },
    )
    assert draft_profile.status_code == 200, draft_profile.text
    draft_dossier = await async_client.get(
        f"/api/world/entities/{entity['id']}/dossier",
        params={"novel_id": novel_id},
    )
    projected_entry = next(
        item
        for item in draft_dossier.json()["entries"]
        if (item["legacy_field_key"] or "").startswith("generic_profile:")
    )
    assert (
        projected_entry["source_metadata"]["generic_profile_metadata"]["profile_status"]
        == "draft"
    )

    restored_profile = await async_client.put(
        f"/api/world/profiles/{entity['id']}",
        params={"novel_id": novel_id},
        json={
            "expected_dossier_revision": draft_profile.json()[
                "expected_dossier_revision"
            ],
            "status": "canonical",
        },
    )
    assert restored_profile.status_code == 200, restored_profile.text
    expected_revision = restored_profile.json()["expected_dossier_revision"]

    edited = await async_client.patch(
        f"/api/world/entities/{entity['id']}/dossier/entries/{mapped_entry['id']}",
        params={"novel_id": novel_id},
        json={
            "expected_revision_id": mapped_entry["id"],
            "content": "迁徙后的石窟",
        },
    )
    assert edited.status_code == 200, edited.text
    reread = await async_client.get(
        f"/api/world/profiles/{entity['id']}", params={"novel_id": novel_id}
    )
    assert reread.json()["data_json"]["origin_place"] == "迁徙后的石窟"
    stale = await async_client.put(
        f"/api/world/profiles/{entity['id']}",
        params={"novel_id": novel_id},
        json={
            "expected_dossier_revision": expected_revision,
            "data_json": {"origin_place": "旧值复活"},
        },
    )
    assert stale.status_code == 409, stale.text
    assert stale.json()["error"] == "world_profile_revision_stale"

    current_revision = reread.json()["expected_dossier_revision"]
    cleared = await async_client.put(
        f"/api/world/profiles/{entity['id']}",
        params={"novel_id": novel_id},
        json={
            "expected_dossier_revision": current_revision,
            "data_json": None,
        },
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["data_json"] == {}
    cleared_dossier = await async_client.get(
        f"/api/world/entities/{entity['id']}/dossier",
        params={"novel_id": novel_id},
    )
    assert cleared_dossier.status_code == 200, cleared_dossier.text
    assert all(
        not (item["legacy_field_key"] or "").startswith("generic_profile:")
        for item in cleared_dossier.json()["entries"]
    )
    history = await async_client.get(
        f"/api/world/entities/{entity['id']}/dossier/history",
        params={"novel_id": novel_id, "entry_group_id": mapped_entry["entry_group_id"]},
    )
    assert history.status_code == 200, history.text
    assert history.json()["total_count"] == 3


@pytest.mark.asyncio
async def test_strong_profile_and_dossier_stay_in_sync(
    async_client: AsyncClient,
    db_session,
) -> None:
    project = await async_client.post("/api/projects", json={"title": "强档案双向同步"})
    assert project.status_code == 201, project.text
    novel_id = project.json()["id"]
    cases = [
        ("species", "origin_summary", "history", "起源于雾海"),
        (
            "faction",
            "resources_json",
            "resources",
            [{"name": "盐铁", "amount": 3}],
        ),
        ("location", "climate", "sensory_details", "潮湿的冷风"),
        ("rule", "rule_domain", "known_scope", "只限北境"),
        ("item", "powers_json", "abilities_limits", [{"label": "照明"}]),
        ("secret", "truth_summary", "truth", "盟主仍然在世"),
    ]
    dossier_rows = {}
    for entity_type, field, facing, value in cases:
        entity = await async_client.post(
            "/api/world/entities",
            params={"novel_id": novel_id},
            json={"entity_type": entity_type, "name": entity_type, "status": "canonical"},
        )
        assert entity.status_code == 201, entity.text
        entity_id = entity.json()["id"]
        profile = await async_client.put(
            f"/api/world/profiles/{entity_id}",
            params={"novel_id": novel_id},
            json={"status": "canonical", field: value},
        )
        assert profile.status_code == 200, profile.text
        dossier = await async_client.get(
            f"/api/world/entities/{entity_id}/dossier",
            params={"novel_id": novel_id},
        )
        assert dossier.status_code == 200, dossier.text
        row = next(
            item
            for item in dossier.json()["entries"]
            if item["legacy_field_key"]
            == f"{entity_type}_profiles.{field}"
        )
        assert row["facing"]["key"] == facing
        assert row["visibility"] == ("secret" if entity_type == "secret" else "public")
        assert row["legacy_value"] == (value if field.endswith("_json") else None)
        dossier_rows[field] = (entity_id, row)

    array_entity_id, array_row = dossier_rows["resources_json"]
    prose_only = await async_client.patch(
        f"/api/world/entities/{array_entity_id}/dossier/entries/{array_row['id']}",
        params={"novel_id": novel_id},
        json={"expected_revision_id": array_row["id"], "content": "盐铁：4"},
    )
    assert prose_only.status_code == 400, prose_only.text
    unchanged_dossier = await async_client.get(
        f"/api/world/entities/{array_entity_id}/dossier",
        params={"novel_id": novel_id},
    )
    current_array_row = next(
        item
        for item in unchanged_dossier.json()["entries"]
        if item["legacy_field_key"] == "faction_profiles.resources_json"
    )
    assert current_array_row["id"] == array_row["id"]
    changed_value = [{"name": "盐铁", "amount": 4}]
    updated = await async_client.patch(
        f"/api/world/entities/{array_entity_id}/dossier/entries/{current_array_row['id']}",
        params={"novel_id": novel_id},
        json={
            "expected_revision_id": current_array_row["id"],
            "legacy_value": changed_value,
        },
    )
    assert updated.status_code == 200, updated.text
    profile = await async_client.get(
        f"/api/world/profiles/{array_entity_id}", params={"novel_id": novel_id}
    )
    assert profile.json()["fields"]["resources_json"] == changed_value

    scalar_entity_id, scalar_row = dossier_rows["origin_summary"]
    edited = await async_client.patch(
        f"/api/world/entities/{scalar_entity_id}/dossier/entries/{scalar_row['id']}",
        params={"novel_id": novel_id},
        json={
            "expected_revision_id": scalar_row["id"],
            "content": "起源于远古森林",
        },
    )
    assert edited.status_code == 200, edited.text
    unchanged = await async_client.put(
        f"/api/world/profiles/{scalar_entity_id}",
        params={"novel_id": novel_id},
        json={"origin_summary": None},
    )
    assert unchanged.status_code == 200, unchanged.text
    assert unchanged.json()["fields"]["origin_summary"] == "起源于远古森林"
    cleared = await async_client.patch(
        f"/api/world/entities/{scalar_entity_id}/dossier/entries/{edited.json()['id']}",
        params={"novel_id": novel_id},
        json={
            "expected_revision_id": edited.json()["id"],
            "content": "",
        },
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["status"] == "cleared"
    profile = await async_client.get(
        f"/api/world/profiles/{scalar_entity_id}", params={"novel_id": novel_id}
    )
    assert profile.json()["fields"]["origin_summary"] is None

    secret_entity_id, secret_row = dossier_rows["truth_summary"]
    public = await WorldObjectDossierService().read(
        db_session,
        novel_id,
        secret_entity_id,
        visibility_filter="public",
    )
    assert all(item.id != uuid.UUID(secret_row["id"]) for item in public.entries)


@pytest.mark.asyncio
async def test_draft_strong_profile_needs_explicit_status_adoption(
    async_client: AsyncClient,
) -> None:
    project = await async_client.post("/api/projects", json={"title": "强档案状态同步"})
    assert project.status_code == 201, project.text
    novel_id = project.json()["id"]
    entity = await async_client.post(
        "/api/world/entities",
        params={"novel_id": novel_id},
        json={"entity_type": "species", "name": "待审种族", "status": "canonical"},
    )
    assert entity.status_code == 201, entity.text
    entity_id = entity.json()["id"]
    draft = await async_client.put(
        f"/api/world/profiles/{entity_id}",
        params={"novel_id": novel_id},
        json={"status": "draft", "origin_summary": "候选起源"},
    )
    assert draft.status_code == 200, draft.text
    dossier = await async_client.get(
        f"/api/world/entities/{entity_id}/dossier", params={"novel_id": novel_id}
    )
    assert all(
        item["legacy_field_key"] != "species_profiles.origin_summary"
        for item in dossier.json()["entries"]
    )
    history = await async_client.get(
        f"/api/world/entities/{entity_id}/dossier/history",
        params={"novel_id": novel_id},
    )
    assert history.json()["entries"][0]["status"] == "needs_review"

    adopted = await async_client.put(
        f"/api/world/profiles/{entity_id}",
        params={"novel_id": novel_id},
        json={"status": "canonical"},
    )
    assert adopted.status_code == 200, adopted.text
    history = await async_client.get(
        f"/api/world/entities/{entity_id}/dossier/history",
        params={"novel_id": novel_id},
    )
    current = next(
        item
        for item in history.json()["entries"]
        if item["legacy_field_key"] == "species_profiles.origin_summary"
    )
    assert current["status"] == "active"
    assert current["content"] == "候选起源"


@pytest.mark.asyncio
async def test_generic_profile_get_does_not_materialize_legacy_json(
    async_client: AsyncClient,
    db_session,
) -> None:
    project = await async_client.post(
        "/api/projects", json={"title": "GET 不物化通用档案"}
    )
    assert project.status_code == 201, project.text
    novel_id = project.json()["id"]
    entity = await async_client.post(
        "/api/world/entities",
        params={"novel_id": novel_id},
        json={
            "entity_type": "custom_species",
            "name": "未登记种族",
            "status": "canonical",
        },
    )
    assert entity.status_code == 201, entity.text
    legacy = GenericEntityProfile(
        novel_id=uuid.UUID(novel_id),
        entity_id=uuid.UUID(entity.json()["id"]),
        profile_type="custom_species",
        status="canonical",
        data_json={"unknown": {"keep": [1, 2]}},
    )
    db_session.add(legacy)
    await db_session.flush()
    before = await db_session.scalar(
        select(WorldObjectDossierEntry.id).where(
            WorldObjectDossierEntry.entity_id == legacy.entity_id
        )
    )
    response = await async_client.get(
        f"/api/world/profiles/{legacy.entity_id}", params={"novel_id": novel_id}
    )
    after = await db_session.scalar(
        select(WorldObjectDossierEntry.id).where(
            WorldObjectDossierEntry.entity_id == legacy.entity_id
        )
    )
    assert response.status_code == 200, response.text
    assert response.json()["data_json"] == {"unknown": {"keep": [1, 2]}}
    assert before is None and after is None


@pytest.mark.asyncio
async def test_generic_profile_compatibility_routes_reject_another_novel(
    async_client: AsyncClient,
) -> None:
    project = await async_client.post("/api/projects", json={"title": "档案所属项目"})
    other = await async_client.post("/api/projects", json={"title": "无权读取项目"})
    assert project.status_code == other.status_code == 201
    novel_id = project.json()["id"]
    other_novel_id = other.json()["id"]
    entity = await async_client.post(
        "/api/world/entities",
        params={"novel_id": novel_id},
        json={"entity_type": "custom_species", "name": "雾生族", "status": "canonical"},
    )
    assert entity.status_code == 201, entity.text
    created = await async_client.put(
        f"/api/world/profiles/{entity.json()['id']}",
        params={"novel_id": novel_id},
        json={"data_json": {"origin": "北方雾海"}},
    )
    assert created.status_code == 200, created.text

    read = await async_client.get(
        f"/api/world/profiles/{entity.json()['id']}",
        params={"novel_id": other_novel_id},
    )
    write = await async_client.put(
        f"/api/world/profiles/{entity.json()['id']}",
        params={"novel_id": other_novel_id},
        json={"data_json": {"origin": "跨项目覆盖"}},
    )
    still_owned = await async_client.get(
        f"/api/world/profiles/{entity.json()['id']}",
        params={"novel_id": novel_id},
    )
    assert read.status_code == write.status_code == 404
    assert still_owned.json()["data_json"] == {"origin": "北方雾海"}


@pytest.mark.asyncio
async def test_invalid_temporal_cutoff_fails_closed(async_client: AsyncClient) -> None:
    novel_id, entity = await _project_and_character(async_client)
    response = await async_client.get(
        f"/api/world/entities/{entity['id']}/dossier",
        params={
            "novel_id": novel_id,
            "as_of_scene_id": str(uuid.uuid4()),
        },
    )
    assert response.status_code == 400, response.text


@pytest.mark.asyncio
async def test_restore_rechecks_scene_anchor_after_source_disappears(
    async_client: AsyncClient, db_session
) -> None:
    novel_id, entity = await _project_and_character(async_client)
    url = f"/api/world/entities/{entity['id']}/dossier/entries"
    params = {"novel_id": novel_id}
    original = await async_client.post(
        url,
        params=params,
        json={"facing": {"kind": "core", "key": "history"}, "content": "旧设定"},
    )
    assert original.status_code == 201, original.text
    first = original.json()
    updated = await async_client.patch(
        f"{url}/{first['id']}",
        params=params,
        json={"expected_revision_id": first["id"], "content": "新设定"},
    )
    assert updated.status_code == 200, updated.text
    old_row = await db_session.scalar(
        select(WorldObjectDossierEntry).where(
            WorldObjectDossierEntry.id == uuid.UUID(first["id"])
        )
    )
    old_row.start_anchor_kind = "scene"
    old_row.start_anchor_id = uuid.uuid4()
    await db_session.flush()
    rejected = await async_client.post(
        f"/api/world/entities/{entity['id']}/dossier/groups/{first['entry_group_id']}/restore",
        params=params,
        json={
            "revision_id": first["id"],
            "expected_current_revision_id": updated.json()["id"],
        },
    )
    assert rejected.status_code == 400, rejected.text
    history = await async_client.get(
        f"/api/world/entities/{entity['id']}/dossier/history", params=params
    )
    assert history.json()["total_count"] == 2


@pytest.mark.asyncio
async def test_restore_preserves_structured_legacy_character_value(
    async_client: AsyncClient,
) -> None:
    novel_id, entity = await _project_and_character(async_client)
    params = {"novel_id": novel_id}
    character_url = f"/api/world/characters/{entity['id']}"
    current = await async_client.get(character_url, params=params)
    first = await async_client.put(
        character_url,
        params=params,
        json={
            "behavior_rules": [{"description": "先听后答"}],
            "expected_updated_at": current.json()["updated_at"],
        },
    )
    assert first.status_code == 200, first.text
    history_url = f"/api/world/entities/{entity['id']}/dossier/history"
    history = await async_client.get(history_url, params=params)
    first_revision = next(
        row
        for row in history.json()["entries"]
        if row["legacy_field_key"] == "behavior_rules"
    )
    second = await async_client.put(
        character_url,
        params=params,
        json={
            "behavior_rules": [{"description": "先答后听"}],
            "expected_updated_at": first.json()["updated_at"],
        },
    )
    assert second.status_code == 200, second.text
    history = await async_client.get(history_url, params=params)
    current_revision = next(
        row
        for row in history.json()["entries"]
        if row["legacy_field_key"] == "behavior_rules" and row["status"] == "active"
    )
    restored = await async_client.post(
        f"/api/world/entities/{entity['id']}/dossier/groups/{first_revision['entry_group_id']}/restore",
        params=params,
        json={
            "revision_id": first_revision["id"],
            "expected_current_revision_id": current_revision["id"],
        },
    )
    assert restored.status_code == 200, restored.text
    response = await async_client.get(character_url, params=params)
    assert response.json()["behavior_rules"] == [{"description": "先听后答"}]


@pytest.mark.asyncio
async def test_restore_does_not_reactivate_archived_project_facing(
    async_client: AsyncClient, db_session
) -> None:
    novel_id, entity = await _project_and_character(async_client)
    term = await create_project_vocabulary_term(
        db_session,
        novel_id,
        VocabularyTermCreate(kind="dossier_facing", name="私人约定"),
    )
    params = {"novel_id": novel_id}
    url = f"/api/world/entities/{entity['id']}/dossier/entries"
    created = await async_client.post(
        url,
        params=params,
        json={
            "facing": {"kind": "project", "term_id": str(term.id)},
            "content": "旧约定",
        },
    )
    assert created.status_code == 201, created.text
    first = created.json()
    updated = await async_client.patch(
        f"{url}/{first['id']}",
        params=params,
        json={"expected_revision_id": first["id"], "content": "新约定"},
    )
    assert updated.status_code == 200, updated.text
    await archive_project_vocabulary_term(
        db_session, novel_id, str(term.id), term.revision_id
    )
    rejected = await async_client.post(
        f"/api/world/entities/{entity['id']}/dossier/groups/{first['entry_group_id']}/restore",
        params=params,
        json={
            "revision_id": first["id"],
            "expected_current_revision_id": updated.json()["id"],
        },
    )
    assert rejected.status_code == 409, rejected.text


@pytest.mark.asyncio
async def test_demo_readonly_identity_cannot_write_dossier(db_session) -> None:
    owner = Account(status="active", support_code="DOSSIER-DEMO")
    db_session.add(owner)
    await db_session.flush()
    project = Project(
        owner_id=owner.id,
        title="演示作品",
        language="zh",
        default_reveal_policy="author_safe",
        settings={},
    )
    db_session.add(project)
    await db_session.flush()
    token = bind_principal(
        AccountPrincipal(
            account_id=owner.id,
            status="active",
            identity_type="demo_readonly",
            support_code=owner.support_code,
            access_scope="demo_readonly",
            demo_project_id=project.id,
        )
    )
    try:
        service = WorldObjectDossierService()
        with pytest.raises(NotFoundError):
            await service.create_entry(
                db_session,
                str(project.id),
                str(uuid.uuid4()),
                DossierEntryCreate(
                    facing=DossierFacingRef(kind="core", key="history"),
                    content="不得写入",
                ),
            )
        with pytest.raises(NotFoundError):
            await service.upsert_template(
                db_session,
                str(project.id),
                "character",
                DossierTemplateUpsert(fields=[]),
            )
    finally:
        reset_principal(token)


@pytest.mark.asyncio
async def test_role_dossier_rejects_oversize_update_and_preserves_revision(async_client):
    novel_id, entity = await _project_and_character(async_client)
    base = f"/api/world/entities/{entity['id']}/dossier"
    params = {"novel_id": novel_id}
    created = await async_client.post(
        base + "/entries",
        params=params,
        json={
            "facing": {"kind": "core", "key": "identity_position"},
            "legacy_field_key": "role",
            "content": "甲" * 64,
        },
    )
    assert created.status_code == 201, created.text
    entry = created.json()
    response = await async_client.patch(
        base + "/entries/" + entry["id"],
        params=params,
        json={"expected_revision_id": entry["id"], "content": "乙" * 65},
    )
    assert response.status_code == 400, response.text
    assert response.json()["error"] == "dossier_role_too_long"
    current = await async_client.get(base, params=params)
    assert [(item["id"], item["content"]) for item in current.json()["entries"]] == [
        (entry["id"], "甲" * 64)
    ]


@pytest.mark.asyncio
async def test_character_merge_updates_visible_dossier(async_client, db_session):
    from modules.world.services.core.dedup_service import EntityDedupService

    novel_id, target = await _project_and_character(async_client)
    created = await async_client.post(
        "/api/world/entities",
        params={"novel_id": novel_id},
        json={"entity_type": "character", "name": "另一个人物", "status": "canonical"},
    )
    assert created.status_code == 201, created.text
    candidate = created.json()
    for entity, appearance in [(target, "短发"), (candidate, "左眉有疤")]:
        response = await async_client.post(
            f"/api/world/entities/{entity['id']}/dossier/entries",
            params={"novel_id": novel_id},
            json={
                "facing": {"kind": "core", "key": "appearance"},
                "legacy_field_key": "appearance",
                "content": appearance,
            },
        )
        assert response.status_code == 201, response.text
    assert await EntityDedupService()._sync_character_on_merge(
        db_session, novel_id, candidate["id"], target["id"]
    )
    current = await async_client.get(
        f"/api/world/characters/{target['id']}", params={"novel_id": novel_id}
    )
    assert current.status_code == 200, current.text
    assert "短发" in current.json()["appearance"]
    assert "左眉有疤" in current.json()["appearance"]


@pytest.mark.asyncio
async def test_role_dossier_visibility_requires_matching_field_not_just_content(
    async_client, db_session
):
    novel_id, entity = await _project_and_character(async_client)
    service = WorldObjectDossierService()
    for field, facing in [("appearance", "appearance"), ("personality", "personality")]:
        await service.create_entry(
            db_session,
            novel_id,
            entity["id"],
            DossierEntryCreate(
                facing=DossierFacingRef(kind="core", key=facing),
                legacy_field_key=field,
                content="同一句话",
            ),
        )
    view = await service.read(
        db_session,
        novel_id,
        entity["id"],
        visibility_filter="public",
        visible_fields={"appearance": ["同一句话"]},
    )
    assert [item.legacy_field_key for item in view.entries] == ["appearance"]
