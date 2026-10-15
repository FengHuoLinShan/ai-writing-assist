"""World dossier revision and legacy Character compatibility regressions."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from core.errors import NotFoundError
from modules.account.context import bind_principal, reset_principal
from modules.account.contracts import AccountPrincipal
from modules.account.models import Account
from modules.project.models import Project
from modules.world.dossier_service import WorldObjectDossierService
from modules.world.models import GenericEntityProfile, WorldObjectDossierEntry
from modules.world.project_vocabulary_schemas import VocabularyTermCreate
from modules.world.project_vocabulary_service import (
    archive_project_vocabulary_term,
    create_project_vocabulary_term,
)
from modules.world.schemas.dossier import (
    DossierEntryCreate,
    DossierFacingRef,
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
