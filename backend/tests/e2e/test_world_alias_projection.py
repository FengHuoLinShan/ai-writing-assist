"""Real PostgreSQL coverage for the shared inline-alias read projection."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import event

from modules.account.contracts import BOOTSTRAP_ACCOUNT_ID
from modules.account.models import Account
from modules.project.models import Project
from modules.world.models import CoreEntity
from modules.world.repositories import CoreEntityRepository
from modules.world.services.core.entity_alias_service import EntityAliasService

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]


async def test_alias_projection_keeps_full_pages_evidence_and_isolation(
    db_session, async_client
) -> None:
    novel_id, other_id, foreign_id = (uuid.uuid4() for _ in range(3))
    foreign_owner = Account(support_code=f"ALIAS-{uuid.uuid4().hex[:10]}")
    db_session.add(foreign_owner)
    await db_session.flush()
    db_session.add_all(
        [
            Project(id=novel_id, owner_id=BOOTSTRAP_ACCOUNT_ID, title="别名投影"),
            Project(id=other_id, owner_id=BOOTSTRAP_ACCOUNT_ID, title="同账户另一项目"),
            Project(id=foreign_id, owner_id=foreign_owner.id, title="另一账户"),
        ]
    )
    await db_session.flush()
    entities = [
        CoreEntity(
            novel_id=novel_id,
            name=f"河港{i:04d}",
            entity_type="location",
            importance=0.0,
            status="deprecated" if i == 1001 else "canonical",
            summary="不应随别名返回的正文" * 100,
            content_json={
                "description": "未投影正文" * 100,
                "_meta": {"compatibility_shadow": True, "suggestion_id": "synthetic"},
                "aliases": [
                    f"旧港{i:04d}",
                    {
                        "alias": f"别称{i:04d}",
                        "type": "name",
                        "kind": "name",
                        "status": "candidate",
                        "needs_review": True,
                        "confidence": 0.0,
                        "source": "deep_import",
                        "quote": "共同航路",
                        "evidence_refs": [{"id": "e1"}],
                    },
                ],
            },
        )
        for i in range(1002)
    ]
    db_session.add_all(
        entities
        + [
            CoreEntity(
                novel_id=novel_id,
                name="空别名",
                entity_type="location",
                content_json={"aliases": []},
            ),
            CoreEntity(
                novel_id=other_id,
                name="跨项目",
                entity_type="location",
                content_json={"aliases": ["不可见"]},
            ),
            CoreEntity(
                novel_id=foreign_id,
                name="跨账户",
                entity_type="location",
                content_json={"aliases": ["不可见"]},
            ),
        ]
    )
    await db_session.flush()
    repo = CoreEntityRepository()
    legacy = await repo.list_by_novel(
        db_session, novel_id, include_archived=True, limit=2000
    )
    statements = []

    def capture(_conn, _cursor, statement, _params, _context, _many):
        statements.append(statement)

    connection = db_session.get_bind()
    event.listen(connection, "before_cursor_execute", capture)
    try:
        rows = await repo.list_alias_sources(db_session, novel_id)
    finally:
        event.remove(connection, "before_cursor_execute", capture)
    assert len(statements) == 1
    assert rows == [
        {
            "id": e.id,
            "name": e.name,
            "status": e.status,
            "aliases": (e.content_json or {}).get("aliases"),
            "owner_meta": (e.content_json or {}).get("_meta"),
        }
        for e in legacy
    ]
    assert len(rows) == 1003
    service = EntityAliasService(repo=repo)
    page = await service.list_aliases_page(db_session, str(novel_id), skip=2000, limit=20)
    assert page["total"] == 2002
    assert [item["alias"] for item in page["items"]] == ["旧港1000", "别称1000"]
    filtered = await service.list_aliases_page(
        db_session,
        str(novel_id),
        q="别称0500",
        confidence_min=0.0,
        confidence_max=0.0,
        display_state="review",
        skip=0,
        limit=1,
    )
    assert filtered["total"] == 1
    item = filtered["items"][0]
    assert item["confidence"] == 0.0
    assert item["managed_by_suggestion"] is True
    assert item["evidence_refs"] == [{"id": "e1"}]
    assert item["execution_fingerprint"] == service._alias_execution_fingerprint(
        entities[500].id, entities[500].content_json["aliases"][1]
    )
    history = await service.list_aliases_page(
        db_session, str(novel_id), display_state="archived"
    )
    assert history["total"] == 2
    groups = await service.list_review_groups(
        db_session, str(novel_id), skip=1000, limit=20
    )
    assert groups.group_total == groups.item_total == 1001
    assert len(groups.groups) == 1
    # Exercise the actual HTTP project gate with the closed-test bootstrap principal.
    own = await async_client.get(
        "/api/world/aliases",
        params={"novel_id": str(novel_id), "display_state": "review", "limit": 1},
    )
    assert own.status_code == 200
    assert own.json()["total"] == 1001
    foreign = await async_client.get(
        "/api/world/aliases", params={"novel_id": str(foreign_id)}
    )
    assert foreign.status_code == 404
