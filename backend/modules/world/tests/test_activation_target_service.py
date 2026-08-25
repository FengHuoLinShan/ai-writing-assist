from __future__ import annotations

import uuid

import pytest
from sqlalchemy import event

from modules.world.models import CoreEntity, EntityRelation
from modules.world.services.worldbuilding.activation_target_service import (
    WorldBibleActivationTargetService,
)


@pytest.mark.asyncio
async def test_activation_bfs_queries_by_depth_not_entity_count(
    db_session,
    project_novel_id: str,
) -> None:
    novel_id = uuid.UUID(project_novel_id)
    entities = [
        CoreEntity(
            novel_id=novel_id,
            entity_type="location",
            name=f"地点 {index:04d}",
            status="canonical",
        )
        for index in range(1000)
    ]
    db_session.add_all(entities)
    await db_session.flush()
    db_session.add_all(
        [
            EntityRelation(
                novel_id=novel_id,
                source_id=entities[index].id,
                target_id=entities[index + 1].id,
                relation_type="route_to",
                relation_kind="spatial",
                status="canonical",
            )
            for index in range(2)
        ]
    )
    await db_session.flush()

    statements: list[str] = []

    def count_selects(_conn, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    bind = db_session.get_bind()
    event.listen(bind, "before_cursor_execute", count_selects)
    try:
        result = await WorldBibleActivationTargetService().resolve(
            db_session,
            project_novel_id,
            [{"target_type": "core_entity", "target_id": str(entities[0].id)}],
            relation_types=["route_to"],
            max_depth=2,
        )
    finally:
        event.remove(bind, "before_cursor_execute", count_selects)

    assert [item.target["target_id"] for item in result.items] == [
        str(entities[0].id),
        str(entities[1].id),
        str(entities[2].id),
    ]
    assert len(statements) == 5
