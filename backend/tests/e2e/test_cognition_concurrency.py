"""Native CAS, idempotency and project deletion for durable understanding."""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.errors import ConflictError, DomainError
from modules.assistant.facade import lock_background_slot
from modules.assistant.models import AssistantWatch
from modules.collaboration.cognition import commit_changes, read_head
from modules.collaboration.contracts import Grant
from modules.collaboration.models import CognitionCommit, CognitionHead, CognitionRecord
from modules.evidence.facade import (
    collect_creative_manifest,
    revalidate_creative_manifest,
)
from modules.project.facade import (
    require_active_project,
    require_active_project_exclusive,
)
from modules.project.models import Project
from modules.writing.facade import (
    create_draft_only,
    lock_chapter_versions_for_revalidation,
)
from tests.e2e.config import DATABASE_URL

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]


async def test_two_heads_race_and_project_cleanup():
    engine = create_async_engine(DATABASE_URL, pool_size=4, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    nid = uuid4()
    async with sessions() as setup:
        setup.add(Project(id=nid, title="认知 CAS 专用测试"))
        await setup.commit()
    operations = [uuid4(), uuid4()]
    changes = [
        {
            "record_id": str(uuid4()),
            "content": {"kind": "interpretation", "text": f"测试解释{i}"},
            "dependencies": [],
            "author_status": "derived",
        }
        for i in range(2)
    ]

    async def compete(index):
        async with sessions() as db:
            try:
                result = await commit_changes(
                    db,
                    str(nid),
                    operation_id=operations[index],
                    expected_commit_id=None,
                    changes=[changes[index]],
                    read_set=[],
                    method_version="test/v1",
                )
                await db.commit()
                return index, result
            except ConflictError as error:
                await db.rollback()
                assert error.code == "COGNITION_HEAD_CHANGED"
                return index, None

    try:
        results = await asyncio.wait_for(asyncio.gather(compete(0), compete(1)), 10)
        winners = [(index, result) for index, result in results if result]
        assert len(winners) == 1
        index, first = winners[0]
        _, replay = await compete(index)
        assert replay["replayed"] and replay["commit_id"] == first["commit_id"]
        async with sessions() as verify:
            assert (
                str((await read_head(verify, str(nid))).commit_id) == first["commit_id"]
            )
            for model in (CognitionHead, CognitionCommit, CognitionRecord):
                assert (
                    await verify.scalar(
                        select(func.count())
                        .select_from(model)
                        .where(model.novel_id == nid)
                    )
                    == 1
                )
            for statement in (
                update(CognitionCommit)
                .where(CognitionCommit.novel_id == nid)
                .values(outcome="no_change"),
                delete(CognitionCommit).where(CognitionCommit.novel_id == nid),
                update(CognitionRecord)
                .where(CognitionRecord.novel_id == nid)
                .values(content_json={"text": "篡改历史"}),
                delete(CognitionRecord).where(CognitionRecord.novel_id == nid),
            ):
                with pytest.raises(DBAPIError, match="immutable"):
                    async with verify.begin_nested():
                        await verify.execute(statement)
            await verify.execute(
                update(CognitionRecord)
                .where(CognitionRecord.novel_id == nid)
                .values(is_current=False)
            )
            with pytest.raises(DBAPIError, match="immutable"):
                async with verify.begin_nested():
                    await verify.execute(
                        update(CognitionRecord)
                        .where(CognitionRecord.novel_id == nid)
                        .values(is_current=True)
                    )
            await verify.commit()
    finally:
        async with sessions() as cleanup:
            await cleanup.execute(delete(Project).where(Project.id == nid))
            await cleanup.commit()
            for model in (CognitionHead, CognitionCommit, CognitionRecord):
                assert (
                    await cleanup.scalar(
                        select(func.count())
                        .select_from(model)
                        .where(model.novel_id == nid)
                    )
                    == 0
                )
        await engine.dispose()


async def test_source_finalizer_waits_for_writer_without_watch_chapter_deadlock():
    engine = create_async_engine(DATABASE_URL, pool_size=4, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    nid = str(uuid4())
    writer_locked, finalizing, release_writer = (
        asyncio.Event(),
        asyncio.Event(),
        asyncio.Event(),
    )
    try:
        async with sessions() as setup:
            setup.add(Project(id=UUID(nid), title="理解与正文并发专用测试"))
            await setup.flush()
            setup.add(AssistantWatch(novel_id=UUID(nid)))
            source = await create_draft_only(setup, nid, 1, content="她同意交换线索。")
            grant = Grant(
                resources=[{"kind": "writing_draft", "id": source.id}],
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            )
            manifest = await collect_creative_manifest(setup, nid, grant, 1)
            await setup.commit()

        async def writer():
            async with sessions() as db:
                await require_active_project(db, nid)
                await lock_chapter_versions_for_revalidation(db, nid, [1])
                writer_locked.set()
                await release_writer.wait()
                await create_draft_only(db, nid, 1, content="她拒绝交换线索。")
                await db.commit()

        async def finalizer():
            await writer_locked.wait()
            async with sessions() as db:
                # The runtime must enter this gate in a fresh transaction.
                finalizing.set()
                await require_active_project_exclusive(db, nid)
                await lock_background_slot(db, nid)
                await lock_chapter_versions_for_revalidation(db, nid, [1])
                with pytest.raises(DomainError):
                    await revalidate_creative_manifest(db, nid, grant, manifest)

        pending = asyncio.gather(writer(), finalizer())
        await finalizing.wait()
        release_writer.set()
        await asyncio.wait_for(pending, 5)
    finally:
        async with sessions() as cleanup:
            await cleanup.execute(delete(Project).where(Project.id == UUID(nid)))
            await cleanup.commit()
        await engine.dispose()
