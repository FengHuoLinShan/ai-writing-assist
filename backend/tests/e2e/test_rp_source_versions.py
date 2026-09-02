from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from modules.account.models import Account
from modules.evidence.compilation.models import ContextSnapshot
from modules.evidence.indexing.models import RagChunk
from modules.interaction.models import InteractionJourney, InteractionSourceRevision
from modules.project.models import Project
from tests.e2e.config import DATABASE_URL

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]


def _source_revision(
    *,
    source_novel_id: uuid.UUID,
    owner_id: uuid.UUID,
    version_number: int,
    manifest_hash: str,
) -> InteractionSourceRevision:
    return InteractionSourceRevision(
        source_novel_id=source_novel_id,
        owner_id=owner_id,
        version_number=version_number,
        title="PG RP source",
        status="ready",
        source_manifest=[],
        anchor_manifest=[],
        reference_manifest=[],
        ambiguities=[],
        resolutions={},
        readiness_summary={},
        manifest_hash=manifest_hash,
        fingerprint="f" * 64,
    )


async def test_postgresql_source_fk_history_and_consumer_snapshot_lifecycle(
    db_session,
) -> None:
    owner = Account(
        id=uuid.uuid4(),
        status="active",
        support_code=f"rp-source-{uuid.uuid4().hex[:12]}",
    )
    source = Project(
        id=uuid.uuid4(),
        owner_id=owner.id,
        project_kind="author",
        title="Source",
    )
    consumer = Project(
        id=uuid.uuid4(),
        owner_id=owner.id,
        project_kind="interaction",
        title="Journey",
    )
    db_session.add_all([owner, source, consumer])
    await db_session.flush()
    revision = _source_revision(
        source_novel_id=source.id,
        owner_id=owner.id,
        version_number=1,
        manifest_hash="a" * 64,
    )
    db_session.add(revision)
    await db_session.flush()
    invalid_ready = _source_revision(
        source_novel_id=source.id,
        owner_id=owner.id,
        version_number=2,
        manifest_hash="9" * 64,
    )
    invalid_ready.fingerprint = None
    savepoint = await db_session.begin_nested()
    with pytest.raises(IntegrityError):
        db_session.add(invalid_ready)
        await db_session.flush()
    await savepoint.rollback()
    journey = InteractionJourney(
        novel_id=consumer.id,
        owner_id=owner.id,
        title="Journey",
        title_source="fallback",
        opening_text="start",
        status="active",
        latest_activity_at=datetime.now(UTC),
        source_revision_id=revision.id,
    )
    snapshot = ContextSnapshot(
        novel_id=source.id,
        consumer_novel_id=consumer.id,
        phase="interaction_story",
        operation="compile_source_context",
        context_mode="canonical",
        include_pending_objects=False,
        status="succeeded",
        attempt=1,
        prompt_hash="b" * 64,
        prompt_name="interaction-story-v3",
        model="test",
        compile_options={},
        included_asset_ids={},
        excluded_asset_ids={},
        context_summary={},
        section_metadata={},
        token_metadata={},
        result_refs=[],
    )
    db_session.add_all([journey, snapshot])
    old_draft_id, new_draft_id = uuid.uuid4(), uuid.uuid4()
    db_session.add_all(
        [
            RagChunk(
                novel_id=source.id,
                source_type="chapter_text",
                source_id=draft_id,
                content_mode="canonical",
                source_content_hash=source_hash,
                chapter_index=1,
                chunk_index=0,
                text=text,
                index_version="cn-novel-v1",
            )
            for draft_id, source_hash, text in (
                (old_draft_id, "c" * 64, "old"),
                (new_draft_id, "d" * 64, "new"),
            )
        ]
    )
    await db_session.flush()

    chunk_count = await db_session.scalar(
        select(func.count(RagChunk.id)).where(RagChunk.novel_id == source.id)
    )
    assert chunk_count == 2

    savepoint = await db_session.begin_nested()
    with pytest.raises(IntegrityError):
        await db_session.execute(delete(Project).where(Project.id == source.id))
        await db_session.flush()
    await savepoint.rollback()

    await db_session.execute(delete(Project).where(Project.id == consumer.id))
    await db_session.flush()
    assert (
        await db_session.scalar(
            select(func.count(ContextSnapshot.id)).where(
                ContextSnapshot.id == snapshot.id
            )
        )
        == 0
    )
    assert (
        await db_session.scalar(
            select(func.count(InteractionJourney.id)).where(
                InteractionJourney.id == journey.id
            )
        )
        == 0
    )

    await db_session.execute(delete(Project).where(Project.id == source.id))
    await db_session.flush()
    assert (
        await db_session.scalar(
            select(func.count(InteractionSourceRevision.id)).where(
                InteractionSourceRevision.id == revision.id
            )
        )
        == 0
    )


async def test_postgresql_concurrent_source_version_unique_constraint() -> None:
    engine = create_async_engine(DATABASE_URL, pool_size=3, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    owner_id = uuid.uuid4()
    project_id = uuid.uuid4()
    try:
        async with sessions.begin() as setup:
            setup.add(
                Account(
                    id=owner_id,
                    status="active",
                    support_code=f"rp-source-concurrent-{uuid.uuid4().hex[:8]}",
                )
            )
            setup.add(
                Project(
                    id=project_id,
                    owner_id=owner_id,
                    project_kind="author",
                    title="Concurrent source",
                )
            )

        ready = asyncio.Event()
        entered = 0
        entered_lock = asyncio.Lock()

        async def insert_revision(manifest_hash: str) -> bool:
            nonlocal entered
            async with entered_lock:
                entered += 1
                if entered == 2:
                    ready.set()
            await ready.wait()
            try:
                async with sessions.begin() as db:
                    db.add(
                        _source_revision(
                            source_novel_id=project_id,
                            owner_id=owner_id,
                            version_number=1,
                            manifest_hash=manifest_hash,
                        )
                    )
                    await db.flush()
                return True
            except IntegrityError:
                return False

        outcomes = await asyncio.gather(
            insert_revision("e" * 64),
            insert_revision("f" * 64),
        )
        assert sorted(outcomes) == [False, True]
        async with sessions() as verify:
            count = await verify.scalar(
                select(func.count(InteractionSourceRevision.id)).where(
                    InteractionSourceRevision.source_novel_id == project_id
                )
            )
            assert count == 1
    finally:
        async with sessions.begin() as cleanup:
            await cleanup.execute(delete(Account).where(Account.id == owner_id))
        await engine.dispose()
