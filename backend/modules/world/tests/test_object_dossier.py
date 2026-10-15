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
from modules.world.models import WorldObjectDossierEntry
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
