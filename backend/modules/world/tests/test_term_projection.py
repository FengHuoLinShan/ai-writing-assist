"""Alias dictionaries preserve bounded ordering and never hydrate whole entities."""

import uuid

from sqlalchemy import event

from modules.world.models import CoreEntity
from modules.world.repositories import CoreEntityRepository
from modules.world.services.core.entity_context_service import EntityContextService


async def test_term_projection_keeps_status_aliases_order_and_limit(
    db_session, test_project_id
):
    nid = uuid.UUID(test_project_id)
    values = [
        ("已采用", "canonical", 3, ["别名", {"alias": "旧称", "status": "ignored"}]),
        ("待审", "draft", 2, ["待审别名"]),
        ("另一个已采用", "canonical", 1, None),
    ]
    for name, status, importance, aliases in values:
        db_session.add(
            CoreEntity(
                novel_id=nid,
                name=name,
                entity_type="character",
                status=status,
                importance=importance,
                content_json={"aliases": aliases, "large": "x" * 100_000},
            )
        )
    await db_session.flush()
    db_session.expunge_all()
    hydrated = []

    def loaded(session, instance):
        if isinstance(instance, CoreEntity):
            hydrated.append(instance.id)

    event.listen(db_session.sync_session, "loaded_as_persistent", loaded)
    try:
        repo = CoreEntityRepository()
        service = EntityContextService(repo)
        limited = await service.list_entity_terms(db_session, test_project_id, limit=2)
        review = await service.list_entity_terms(
            db_session, test_project_id, limit=2, include_review=True
        )
        other = await repo.list_term_candidates(db_session, uuid.uuid4(), limit=10)
    finally:
        event.remove(db_session.sync_session, "loaded_as_persistent", loaded)
    assert [row["name"] for row in limited] == ["已采用"]
    assert limited[0]["terms"] == ["已采用", "别名"]
    assert [row["name"] for row in review] == ["已采用", "待审"]
    assert not other
    assert not hydrated
