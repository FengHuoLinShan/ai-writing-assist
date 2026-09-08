"""Real PostgreSQL transaction boundaries for focused completion and undo."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.errors import ConflictError
from modules.project.models import Project
from modules.world.facade import (
    apply_focused_world_package,
    rollback_focused_world_package,
    submit_focused_world_package,
)
from modules.world.models import CoreEntity
from modules.world.tests.test_focused_completion import apply_request, setup_run
from tests.e2e.config import DATABASE_URL

pytestmark = pytest.mark.e2e


async def test_postgres_focused_apply_refreshes_before_comparing_author_edit():
    engine = create_async_engine(DATABASE_URL, pool_size=3, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    novel_id = uuid.uuid4()
    try:
        async with sessions.begin() as db:
            db.add(Project(id=novel_id, title="Focused completion CAS E2E"))
            await db.flush()
            entity, _task, _draft, request = await setup_run(db, str(novel_id))
            entity_id = entity.id
            submitted = await submit_focused_world_package(db, request)

        async with sessions() as worker:
            # The worker has already loaded the old object before an author saves.
            old = await worker.get(CoreEntity, entity_id)
            assert old.summary is None
            await worker.commit()
            async with sessions.begin() as author:
                current = await author.get(CoreEntity, entity_id)
                current.summary = "作者在另一个连接补上的内容"
            with pytest.raises(ConflictError):
                await apply_focused_world_package(
                    worker, apply_request(request, submitted)
                )
            await worker.rollback()

        async with sessions() as db:
            current = await db.get(CoreEntity, entity_id)
            assert current.summary == "作者在另一个连接补上的内容"
    finally:
        async with sessions.begin() as db:
            await db.execute(delete(Project).where(Project.id == novel_id))
        await engine.dispose()


async def test_postgres_focused_undo_preserves_later_committed_changes():
    engine = create_async_engine(DATABASE_URL, pool_size=3, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    novel_id = uuid.uuid4()
    try:
        async with sessions.begin() as db:
            db.add(Project(id=novel_id, title="Focused completion undo E2E"))
            await db.flush()
            entity, _task, _draft, request = await setup_run(db, str(novel_id))
            entity_id = entity.id
            submitted = await submit_focused_world_package(db, request)
            await apply_focused_world_package(db, apply_request(request, submitted))
        async with sessions.begin() as author:
            entity = await author.get(CoreEntity, entity_id)
            entity.summary = "作者后来的正式修订"
        async with sessions.begin() as db:
            result = await rollback_focused_world_package(
                db, novel_id=str(novel_id), suggestion_id=submitted["suggestion_id"]
            )
            assert result["results"][0]["status"] == "conflict"
        async with sessions() as db:
            assert (
                await db.scalar(
                    select(CoreEntity.summary).where(CoreEntity.id == entity_id)
                )
                == "作者后来的正式修订"
            )
    finally:
        async with sessions.begin() as db:
            await db.execute(delete(Project).where(Project.id == novel_id))
        await engine.dispose()
