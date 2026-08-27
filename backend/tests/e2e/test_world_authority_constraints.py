from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import DBAPIError, IntegrityError

from modules.project.models import Project
from modules.world.models import WorldCanonHead, WorldCanonRevision


@pytest.mark.asyncio
async def test_postgresql_rejects_direct_canon_revision_mutation(
    async_client, db_session
) -> None:
    created = await async_client.post("/api/projects", json={"title": "Immutable Canon"})
    novel_id = uuid.UUID(created.json()["id"])
    head = await db_session.get(WorldCanonHead, novel_id)

    with pytest.raises(DBAPIError, match="immutable"):
        await db_session.execute(
            update(WorldCanonRevision)
            .where(WorldCanonRevision.id == head.current_revision_id)
            .values(manifest_digest="0" * 64)
        )


@pytest.mark.asyncio
async def test_postgresql_rejects_cross_novel_canon_parent(
    async_client, db_session
) -> None:
    first = await async_client.post("/api/projects", json={"title": "Canon A"})
    second = await async_client.post("/api/projects", json={"title": "Canon B"})
    first_id = uuid.UUID(first.json()["id"])
    second_id = uuid.UUID(second.json()["id"])
    first_head = await db_session.get(WorldCanonHead, first_id)
    first_revision = await db_session.get(
        WorldCanonRevision, first_head.current_revision_id
    )
    invalid = WorldCanonRevision(
        id=uuid.uuid4(),
        novel_id=second_id,
        version_number=1,
        parent_revision_id=first_revision.id,
        manifest_json=first_revision.manifest_json,
        manifest_digest=first_revision.manifest_digest,
        receipt_json=first_revision.receipt_json,
        decision_id=uuid.uuid4(),
        decision_digest="0" * 64,
        created_at=datetime.now(UTC),
    )
    db_session.add(invalid)

    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_project_delete_cascades_the_complete_canon_chain(
    async_client, db_session
) -> None:
    created = await async_client.post("/api/projects", json={"title": "Cascade Canon"})
    novel_id = uuid.UUID(created.json()["id"])
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(WorldCanonRevision)
            .where(WorldCanonRevision.novel_id == novel_id)
        )
        == 1
    )

    await db_session.execute(delete(Project).where(Project.id == novel_id))
    await db_session.flush()

    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(WorldCanonHead)
            .where(WorldCanonHead.novel_id == novel_id)
        )
        == 0
    )
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(WorldCanonRevision)
            .where(WorldCanonRevision.novel_id == novel_id)
        )
        == 0
    )
