"""Event lifecycle races use real transactions and retain deleted history."""

import asyncio
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.errors import ConflictError, NotFoundError
from modules.imports.models import ImportedChapter, ImportRecord
from modules.project.models import Project
from modules.world.models import CoreEntity, Event
from modules.world.repositories import EventRepository
from modules.world.schemas import EventCreate, EventUpdate
from modules.world.services.core.event_service import EventService
from modules.world.tests.helpers import _create_project
from tests.e2e.config import DATABASE_URL

pytestmark = pytest.mark.e2e


@pytest_asyncio.fixture
async def event_data():
    engine = create_async_engine(DATABASE_URL, pool_size=4, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    nid, eid, lid, rid, cid = (uuid.uuid4() for _ in range(5))
    data = EventCreate(
        entity_id=str(eid),
        location_entity_id=str(lid),
        source_chapter_id=str(cid),
        timeline_order=1,
    )
    try:
        async with sessions.begin() as db:
            await _create_project(db, nid)
            db.add_all(
                [
                    CoreEntity(
                        id=eid,
                        novel_id=nid,
                        entity_type="event",
                        name="测试事件",
                        status="canonical",
                    ),
                    CoreEntity(
                        id=lid,
                        novel_id=nid,
                        entity_type="location",
                        name="测试地点",
                        status="canonical",
                    ),
                    ImportRecord(
                        id=rid, novel_id=nid, file_name="event.txt", file_type="txt"
                    ),
                ]
            )
            await db.flush()
            db.add(
                ImportedChapter(
                    id=cid,
                    novel_id=nid,
                    import_record_id=rid,
                    chapter_index=1,
                    title="测试章",
                    content="事件证据",
                )
            )
        yield sessions, nid, data
    finally:
        async with sessions.begin() as db:
            await db.execute(delete(Project).where(Project.id == nid))
        await engine.dispose()


@pytest.mark.parametrize("initial_status", [None, "deprecated"])
async def test_concurrent_create_or_restore_has_one_winner(event_data, initial_status):
    sessions, nid, data = event_data
    eid = uuid.UUID(data.entity_id)
    if initial_status:
        async with sessions.begin() as db:
            db.add(
                Event(
                    novel_id=nid,
                    entity_id=eid,
                    source_chapter_id=uuid.UUID(data.source_chapter_id),
                    location_entity_id=uuid.UUID(data.location_entity_id),
                    timeline_order=0,
                    status=initial_status,
                )
            )
    ready = asyncio.Barrier(2)

    async def worker(order):
        async with sessions.begin() as db:
            # Keep the old identity-map object alive: a locking read must refresh it.
            old = await db.get(Event, eid)
            if initial_status:
                assert old.status == initial_status
            await ready.wait()
            try:
                result = await EventService().create(
                    db, str(nid), data.model_copy(update={"timeline_order": order})
                )
                return 201, result.timeline_order
            except ConflictError as exc:
                return exc.status_code, order

    outcomes = await asyncio.wait_for(asyncio.gather(worker(3), worker(7)), timeout=15)
    assert sorted(code for code, _ in outcomes) == [201, 409]
    winner = next(order for code, order in outcomes if code == 201)
    async with sessions() as db:
        rows = (await db.scalars(select(Event).where(Event.novel_id == nid))).all()
        assert len(rows) == 1
        assert (rows[0].status, rows[0].timeline_order) == ("canonical", winner)


async def test_deleted_event_cannot_be_updated_from_stale_session(event_data):
    sessions, nid, data = event_data
    service = EventService()
    eid = uuid.UUID(data.entity_id)
    async with sessions.begin() as db:
        await service.create(db, str(nid), data)
    async with sessions.begin() as stale_db:
        old = await stale_db.get(Event, eid)
        assert old.status == "canonical"
        async with sessions.begin() as deleting_db:
            await service.delete(deleting_db, str(eid), novel_id=str(nid))
            await service.delete(deleting_db, str(eid), novel_id=str(nid))
        with pytest.raises(NotFoundError):
            await service.update(
                stale_db, str(eid), EventUpdate(timeline_order=99), novel_id=str(nid)
            )
    async with sessions() as db:
        preserved = await db.get(Event, eid)
        assert (preserved.status, preserved.timeline_order) == ("deprecated", 1)
        assert (await db.get(CoreEntity, eid)).status == "canonical"
        assert await service.list(db, str(nid)) == ([], 0)
        assert (
            await service.get_events_for_chapter(db, str(nid), data.source_chapter_id)
            == []
        )
        assert await service.get_events_in_order(db, str(nid)) == []


async def test_other_project_cannot_delete_event(event_data):
    sessions, nid, data = event_data
    service = EventService()
    async with sessions.begin() as db:
        await service.create(db, str(nid), data)
    async with sessions.begin() as db:
        with pytest.raises(NotFoundError):
            await service.delete(db, data.entity_id, novel_id=str(uuid.uuid4()))
        row = await db.get(Event, uuid.UUID(data.entity_id))
        assert row.status == "canonical"


async def test_delete_between_update_read_and_lock_is_rejected(event_data, monkeypatch):
    sessions, nid, data = event_data
    service = EventService()
    service.repo = EventRepository()
    async with sessions.begin() as db:
        await service.create(db, str(nid), data)
    first_read = asyncio.Event()
    deletion_committed = asyncio.Event()
    read = service.repo.get

    async def pause_first_read(db, eid):
        row = await read(db, eid)
        if not first_read.is_set():
            first_read.set()
            await deletion_committed.wait()
        return row

    monkeypatch.setattr(service.repo, "get", pause_first_read)

    async def updating():
        async with sessions.begin() as db:
            with pytest.raises(NotFoundError):
                await service.update(
                    db, data.entity_id, EventUpdate(timeline_order=99), novel_id=str(nid)
                )

    async def deleting():
        await first_read.wait()
        async with sessions.begin() as db:
            await EventService().delete(db, data.entity_id, novel_id=str(nid))
        deletion_committed.set()

    await asyncio.wait_for(asyncio.gather(updating(), deleting()), timeout=15)
    async with sessions() as db:
        row = await db.get(Event, uuid.UUID(data.entity_id))
        assert (row.status, row.timeline_order) == ("deprecated", 1)
