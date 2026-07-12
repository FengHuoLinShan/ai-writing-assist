"""PostgreSQL generated-column regressions for world entities."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def test_create_entity_leaves_search_text_to_database(
    db_session: AsyncSession,
) -> None:
    from modules.project.schemas import ProjectCreate
    from modules.project.services import ProjectService
    from modules.world.facade import create_entity

    project = await ProjectService().create_project(
        db_session,
        ProjectCreate(title="Generated Column Regression", language="zh"),
    )
    novel_id = str(project.id)

    created = await create_entity(
        db_session,
        novel_id,
        {
            "name": "克莱恩·莫雷蒂",
            "entity_type": "character",
            "summary": "测试实体",
            "content_json": {"aliases": [{"alias": "周明瑞", "type": "前世身份"}]},
            "status": "candidate",
            "created_by": "ai_import",
        },
    )
    await db_session.flush()

    row = (
        await db_session.execute(
            text(
                """
                SELECT search_text
                FROM core_entities
                WHERE id = :entity_id
                """
            ),
            {"entity_id": created["id"]},
        )
    ).scalar_one()

    assert "克莱恩·莫雷蒂" in row
    assert "alias" in row
