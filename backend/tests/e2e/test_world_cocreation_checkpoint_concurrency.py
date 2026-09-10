"""The co-creation pointer must reject a concurrent advance from the same base."""

import asyncio
import uuid

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.errors import ConflictError, ValidationError
from modules.project.models import Project
from modules.world.models import CoreEntity, CreationSuggestion
from modules.world.models.cocreation import WorldCocreationSession
from modules.world.schemas import (
    WorldCocreationCheckpointAdvanceRequest,
    WorldLibraryTopicCreate,
    WorldLibraryTopicMoveRequest,
)
from modules.world.services.worldbuilding.cocreation_session_service import (
    WorldCocreationSessionService,
)
from modules.world.services.worldbuilding.world_library_service import WorldLibraryService
from tests.e2e.config import DATABASE_URL


@pytest.mark.asyncio
async def test_checkpoint_advance_serializes_and_refreshes_loaded_pointer():
    engine = create_async_engine(DATABASE_URL, pool_size=3, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    nid, sid = uuid.uuid4(), uuid.uuid4()
    suggestions = [uuid.uuid4(), uuid.uuid4()]
    barrier = asyncio.Barrier(2)
    service = WorldCocreationSessionService()

    async def advance(suggestion_id):
        async with sessions.begin() as db:
            # Both requests have observed the same base; retaining the ORM instance
            # also verifies that the lock query refreshes the identity map.
            observed = await service._require_session(db, str(nid), str(sid))
            assert observed.current_checkpoint_id is None
            await barrier.wait()
            try:
                await service.advance_checkpoint(
                    db,
                    str(nid),
                    str(sid),
                    WorldCocreationCheckpointAdvanceRequest(
                        novel_id=str(nid),
                        checkpoint_suggestion_id=str(suggestion_id),
                        expected_checkpoint_id=None,
                    ),
                )
                return "advanced"
            except ConflictError as exc:
                return exc.code

    try:
        async with sessions.begin() as db:
            db.add(Project(id=nid, title="checkpoint concurrency synthetic test"))
            await db.flush()
            db.add(
                WorldCocreationSession(
                    id=sid, novel_id=nid, title="test", source_kind="project"
                )
            )
            for suggestion_id in suggestions:
                db.add(
                    CreationSuggestion(
                        id=suggestion_id,
                        novel_id=nid,
                        source_module="world",
                        review_group="world_adoption",
                        target_type="world_design_checkpoint",
                        payload_json={},
                        status="pending",
                    )
                )
        assert sorted(await asyncio.gather(*(advance(s) for s in suggestions))) == [
            "advanced",
            "checkpoint_pointer_drift",
        ]
    finally:
        async with sessions.begin() as db:
            await db.execute(delete(Project).where(Project.id == nid))
        await engine.dispose()


@pytest.mark.asyncio
async def test_library_concurrent_moves_and_favorites():
    engine = create_async_engine(DATABASE_URL, pool_size=3, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    nid, eid = uuid.uuid4(), uuid.uuid4()
    service = WorldLibraryService()
    barrier = asyncio.Barrier(2)

    async def move(topic, parent):
        async with sessions.begin() as db:
            await barrier.wait()
            try:
                await service.move_topic(
                    db,
                    str(nid),
                    topic.id,
                    WorldLibraryTopicMoveRequest(novel_id=str(nid), parent_id=parent.id),
                )
                return "moved"
            except ValidationError as exc:
                return exc.code

    async def favorite():
        async with sessions.begin() as db:
            return await service.set_favorite(
                db, str(nid), "entity", str(eid), favorited=True
            )

    try:
        async with sessions.begin() as db:
            db.add(Project(id=nid, title="library concurrent metadata test"))
            await db.flush()
            db.add(
                CoreEntity(
                    id=eid,
                    novel_id=nid,
                    name="同一对象",
                    entity_type="location",
                    status="canonical",
                )
            )
            a = await service.create_topic(
                db, str(nid), WorldLibraryTopicCreate(novel_id=str(nid), name="A")
            )
            b = await service.create_topic(
                db, str(nid), WorldLibraryTopicCreate(novel_id=str(nid), name="B")
            )
        assert sorted(await asyncio.gather(move(a, b), move(b, a))) == [
            "moved",
            "topic_cycle",
        ]
        results = await asyncio.gather(favorite(), favorite())
        assert all(result.favorited for result in results)
        async with sessions() as db:
            topics = await service.list_topic_tree(db, str(nid))
            assert len(topics) == 1
            assert len(topics[0].children) == 1
    finally:
        async with sessions.begin() as db:
            await db.execute(delete(Project).where(Project.id == nid))
        await engine.dispose()
