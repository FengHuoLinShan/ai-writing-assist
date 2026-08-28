from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from modules.world.authority import STATEMENT_SCHEMA_REF


async def _canon_head(client: AsyncClient, novel_id: str) -> str:
    response = await client.get(
        "/api/world/canon/head",
        params={"novel_id": novel_id},
    )
    assert response.status_code == 200, response.text
    return response.json()["current_revision"]["id"]


@pytest.mark.asyncio
async def test_legacy_adapters_lock_canon_before_page_resources(
    async_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modules.world import api as world_api

    events: list[str] = []
    original_lock = world_api._world_authority_service.lock_head_for_admission
    original_create_page = world_api._bible_service.create_page
    original_create_draft = world_api._bible_lifecycle_service.create_draft

    async def lock_head(*args, **kwargs):
        events.append("head")
        return await original_lock(*args, **kwargs)

    async def create_page(*args, **kwargs):
        events.append("page")
        return await original_create_page(*args, **kwargs)

    async def create_draft(*args, **kwargs):
        events.append("draft")
        return await original_create_draft(*args, **kwargs)

    monkeypatch.setattr(
        world_api._world_authority_service,
        "lock_head_for_admission",
        lock_head,
    )
    monkeypatch.setattr(world_api._bible_service, "create_page", create_page)
    monkeypatch.setattr(
        world_api._bible_lifecycle_service,
        "create_draft",
        create_draft,
    )

    project = await async_client.post("/api/projects", json={"title": "锁序兼容"})
    novel_id = project.json()["id"]
    created = await async_client.post(
        "/api/world/bible/pages",
        json={
            "novel_id": novel_id,
            "page_type": "rule",
            "title": "锁序规则",
            "status": "canonical",
        },
    )
    assert created.status_code == 201, created.text
    assert events.index("head") < events.index("page") < events.index("draft")

    events.clear()
    updated = await async_client.patch(
        f"/api/world/bible/pages/{created.json()['id']}",
        params={"novel_id": novel_id},
        json={"free_text": "新版本"},
    )
    assert updated.status_code == 200, updated.text
    assert events.index("head") < events.index("draft")


@pytest.mark.asyncio
async def test_validation_policy_locks_canon_before_staging_page(
    async_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modules.world import api as world_api

    events: list[str] = []
    service = world_api._world_validation_service
    original_lock = service._authority.lock_head_for_admission
    original_create_page = service._lifecycle.create_page

    async def lock_head(*args, **kwargs):
        events.append("head")
        return await original_lock(*args, **kwargs)

    async def create_page(*args, **kwargs):
        events.append("page")
        return await original_create_page(*args, **kwargs)

    monkeypatch.setattr(service._authority, "lock_head_for_admission", lock_head)
    monkeypatch.setattr(service._lifecycle, "create_page", create_page)

    project = await async_client.post("/api/projects", json={"title": "策略锁序"})
    response = await async_client.post(
        "/api/world/bible/validation-policy/activate",
        params={"novel_id": project.json()["id"]},
    )
    assert response.status_code == 201, response.text
    assert events.index("head") < events.index("page")


@pytest.mark.asyncio
async def test_legacy_page_create_update_and_archive_preserve_canon(
    async_client: AsyncClient,
) -> None:
    project = await async_client.post("/api/projects", json={"title": "旧页面兼容"})
    novel_id = project.json()["id"]
    c0 = await _canon_head(async_client, novel_id)

    created = await async_client.post(
        "/api/world/bible/pages",
        json={
            "novel_id": novel_id,
            "page_key": "legacy-rule",
            "page_type": "rule",
            "title": "旧规则",
            "status": "canonical",
            "free_text": "第一版",
        },
    )
    assert created.status_code == 201, created.text
    page = created.json()
    assert page["page_key"] == "legacy-rule"
    assert page["status"] == "canonical"
    assert page["version_number"] == 1
    c1 = await _canon_head(async_client, novel_id)
    assert c1 != c0

    updated = await async_client.patch(
        f"/api/world/bible/pages/{page['id']}",
        params={"novel_id": novel_id},
        json={"title": "新规则", "free_text": "第二版"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["version_number"] == 2
    c2 = await _canon_head(async_client, novel_id)
    assert c2 != c1

    archived = await async_client.patch(
        f"/api/world/bible/pages/{page['id']}",
        params={"novel_id": novel_id},
        json={"status": "archived"},
    )
    assert archived.status_code == 200, archived.text
    assert archived.json()["status"] == "archived"
    assert archived.json()["version_number"] == 2
    assert await _canon_head(async_client, novel_id) == c2
    revisions = await async_client.get(
        f"/api/world/bible/pages/{page['id']}/revisions",
        params={"novel_id": novel_id},
    )
    assert revisions.status_code == 200, revisions.text
    assert len(revisions.json()) == 2

    confirmed = await async_client.post(
        "/api/world/bible/pages",
        json={
            "novel_id": novel_id,
            "page_type": "rule",
            "title": "旧 confirmed",
            "status": "confirmed",
        },
    )
    assert confirmed.status_code == 201, confirmed.text
    assert confirmed.json()["status"] == "canonical"
    assert await _canon_head(async_client, novel_id) != c2


@pytest.mark.asyncio
async def test_legacy_publish_wire_and_explicit_decision_replay(
    async_client: AsyncClient,
) -> None:
    project = await async_client.post("/api/projects", json={"title": "发布兼容"})
    novel_id = project.json()["id"]
    old_draft = await async_client.post(
        "/api/world/bible/drafts",
        json={"novel_id": novel_id, "page_type": "rule", "title": "旧调用"},
    )
    old_publish = await async_client.post(
        f"/api/world/bible/drafts/{old_draft.json()['id']}/publish",
        params={"novel_id": novel_id},
    )
    assert old_publish.status_code == 200, old_publish.text

    draft = await async_client.post(
        "/api/world/bible/drafts",
        json={"novel_id": novel_id, "page_type": "rule", "title": "可重放"},
    )
    expected_head = await _canon_head(async_client, novel_id)
    decision_id = str(uuid.uuid4())
    params = {
        "novel_id": novel_id,
        "expected_canon_head": expected_head,
        "canon_decision_id": decision_id,
    }
    first = await async_client.post(
        f"/api/world/bible/drafts/{draft.json()['id']}/publish",
        params=params,
    )
    replay = await async_client.post(
        f"/api/world/bible/drafts/{draft.json()['id']}/publish",
        params=params,
    )
    assert first.status_code == replay.status_code == 200
    assert replay.json()["id"] == first.json()["id"]
    assert replay.json()["version_number"] == first.json()["version_number"]
    admitted_head = await _canon_head(async_client, novel_id)
    assert admitted_head != expected_head
    assert await _canon_head(async_client, novel_id) == admitted_head


@pytest.mark.asyncio
async def test_policy_activation_admits_once_and_canon_body_errors_are_stable(
    async_client: AsyncClient,
) -> None:
    project = await async_client.post("/api/projects", json={"title": "策略正典"})
    novel_id = project.json()["id"]
    c0 = await _canon_head(async_client, novel_id)
    activated = await async_client.post(
        "/api/world/bible/validation-policy/activate",
        params={"novel_id": novel_id},
    )
    assert activated.status_code == 201, activated.text
    c1 = await _canon_head(async_client, novel_id)
    assert c1 != c0
    replay = await async_client.post(
        "/api/world/bible/validation-policy/activate",
        params={"novel_id": novel_id},
    )
    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == activated.json()["id"]
    assert await _canon_head(async_client, novel_id) == c1

    blocked = await async_client.post(
        "/api/world/bible/pages",
        json={
            "novel_id": novel_id,
            "page_type": "rule",
            "title": "没有验证回执",
            "status": "canonical",
        },
    )
    assert blocked.status_code == 409, blocked.text
    assert blocked.json()["error"] == "required_validation"
    pages = await async_client.get(
        "/api/world/bible/pages",
        params={"novel_id": novel_id},
    )
    assert "没有验证回执" not in {item["title"] for item in pages.json()["items"]}
    assert await _canon_head(async_client, novel_id) == c1

    invalid_requests = [
        (
            "/api/world/canon/admissions/preview",
            {
                "novel_id": novel_id,
                "expected_previous_head": c1,
                "input": {"kind": "unknown", "version": 1},
            },
        ),
        (
            "/api/world/canon/admissions",
            {
                "novel_id": novel_id,
                "decision_id": str(uuid.uuid4()),
                "expected_previous_head": c1,
                "confirmed": True,
                "input": {"kind": "page_publish", "version": 99},
            },
        ),
        (
            "/api/world/canon/revert",
            {
                "novel_id": novel_id,
                "decision_id": str(uuid.uuid4()),
                "expected_previous_head": c1,
                "confirmed": True,
            },
        ),
    ]
    for path, body in invalid_requests:
        response = await async_client.post(path, json=body)
        assert response.status_code == 422, response.text
        assert response.json()["error"] == "canon_reference_invalid"

    referent_id = str(uuid.uuid4())
    schema_revision_id = str(uuid.uuid4())

    def assertion_request(statement: dict) -> dict:
        return {
            "novel_id": novel_id,
            "decision_id": str(uuid.uuid4()),
            "expected_previous_head": c1,
            "confirmed": True,
            "input": {
                "kind": "assert_batch",
                "version": 1,
                "novel_id": novel_id,
                "assertions": [
                    {
                        "novel_id": novel_id,
                        "regime": "objective_world.v1",
                        "polarity": "positive",
                        "statement": statement,
                        "schema_ref": STATEMENT_SCHEMA_REF.model_dump(mode="json"),
                        "time_scope": {"kind": "timeless", "version": 1},
                        "source_refs": [],
                        "hard_grounds": [],
                    }
                ],
                "candidate_snapshot": {},
                "selected_item_keys": [],
                "source_refs": [],
            },
        }

    unknown_statement = await async_client.post(
        "/api/world/canon/admissions",
        json=assertion_request({"kind": "statement_claim_ref", "version": 1}),
    )
    assert unknown_statement.status_code == 422, unknown_statement.text
    assert unknown_statement.json()["error"] == "unsupported_statement_kind"

    invalid_scalar = await async_client.post(
        "/api/world/canon/admissions",
        json=assertion_request(
            {
                "kind": "entity_scalar",
                "version": 1,
                "subject": {
                    "novel_id": novel_id,
                    "referent_id": referent_id,
                },
                "field": {
                    "schema_revision": {
                        "resource": {
                            "kind": "entity_profile_template",
                            "version": 1,
                            "novel_id": novel_id,
                            "resource_id": schema_revision_id,
                        },
                        "revision_id": schema_revision_id,
                        "revision_digest": "0" * 64,
                    },
                    "field_key": "population",
                },
                "value": {"kind": "decimal", "version": 1, "value": "NaN"},
            }
        ),
    )
    assert invalid_scalar.status_code == 422, invalid_scalar.text
    assert invalid_scalar.json()["error"] == "invalid_statement_value"
    assert await _canon_head(async_client, novel_id) == c1
