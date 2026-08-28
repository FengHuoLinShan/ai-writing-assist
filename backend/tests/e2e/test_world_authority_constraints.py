from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.errors import DomainError
from modules.account.contracts import BOOTSTRAP_ACCOUNT_ID
from modules.project.models import Project
from modules.world.authority import (
    CanonAdmissionPreviewRequest,
    CanonAdmissionRequest,
    PagePublishPreviewInputV1,
)
from modules.world.models import (
    WorldBiblePageDraft,
    WorldBiblePageRevision,
    WorldCanonHead,
    WorldCanonRevision,
)
from modules.world.schemas import WorldBiblePageDraftCreate
from modules.world.services.worldbuilding.world_authority_service import (
    WorldAuthorityService,
)
from modules.world.services.worldbuilding.world_bible_lifecycle_service import (
    WorldBibleLifecycleService,
)
from tests.e2e.config import DATABASE_URL


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
async def test_postgresql_rejects_cross_novel_page_revision(
    async_client, db_session
) -> None:
    first = await async_client.post("/api/projects", json={"title": "Page A"})
    second = await async_client.post("/api/projects", json={"title": "Page B"})
    page = await async_client.post(
        "/api/world/bible/pages",
        json={
            "novel_id": first.json()["id"],
            "title": "Project A page",
            "status": "draft",
        },
    )
    assert page.status_code == 201
    db_session.add(
        WorldBiblePageRevision(
            novel_id=uuid.UUID(second.json()["id"]),
            page_id=uuid.UUID(page.json()["id"]),
            version_number=1,
            snapshot_json={},
            revision_digest="0" * 64,
            revision_reason="cross_novel_probe",
        )
    )

    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_same_decision_converges_after_waiting_for_the_head_lock() -> None:
    engine = create_async_engine(DATABASE_URL, pool_size=3, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    novel_id = uuid.uuid4()

    class BarrierAuthority(WorldAuthorityService):
        def __init__(self) -> None:
            self._barrier = asyncio.Barrier(2)
            self._calls: dict[asyncio.Task, int] = {}

        async def _existing_decision_response(
            self, *args, **kwargs  # noqa: ANN002, ANN003
        ):
            response = await super()._existing_decision_response(*args, **kwargs)
            task = asyncio.current_task()
            assert task is not None
            self._calls[task] = self._calls.get(task, 0) + 1
            if self._calls[task] == 1 and response is None:
                await self._barrier.wait()
            return response

    authority = BarrierAuthority()
    try:
        async with sessions.begin() as setup_db:
            setup_db.add(Project(id=novel_id, title="Canon decision concurrency"))
            await setup_db.flush()
            c0 = await authority.initialize_empty_canon(setup_db, novel_id)
            draft = await WorldBibleLifecycleService().create_draft(
                setup_db,
                WorldBiblePageDraftCreate(
                    novel_id=str(novel_id),
                    title="Concurrent page",
                    page_type="background",
                ),
            )
            preview = await authority.preview(
                setup_db,
                CanonAdmissionPreviewRequest(
                    novel_id=novel_id,
                    expected_previous_head=c0.id,
                    input=PagePublishPreviewInputV1(
                        novel_id=novel_id,
                        draft_id=uuid.UUID(draft.id),
                    ),
                ),
            )

        decision_id = uuid.uuid4()
        request = CanonAdmissionRequest(
            novel_id=novel_id,
            decision_id=decision_id,
            expected_previous_head=c0.id,
            confirmed=True,
            input=preview.normalized_input,
        )

        async def admit_once():
            async with sessions.begin() as db:
                return await authority.admit(
                    db,
                    request,
                    authorizer_id=BOOTSTRAP_ACCOUNT_ID,
                )

        left, right = await asyncio.gather(admit_once(), admit_once())
        assert left.id == right.id
        async with sessions() as verify_db:
            assert (
                await verify_db.scalar(
                    select(func.count(WorldCanonRevision.id)).where(
                        WorldCanonRevision.novel_id == novel_id
                    )
                )
                == 2
            )
            assert await verify_db.get(WorldBiblePageDraft, uuid.UUID(draft.id)) is None
    finally:
        async with sessions.begin() as cleanup_db:
            await cleanup_db.execute(delete(Project).where(Project.id == novel_id))
        await engine.dispose()


@pytest.mark.asyncio
async def test_admission_reloads_draft_after_waiting_for_its_lock() -> None:
    engine = create_async_engine(DATABASE_URL, pool_size=3, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    novel_id = uuid.uuid4()
    observed = asyncio.Event()
    proceed = asyncio.Event()

    class PausingAuthority(WorldAuthorityService):
        pause_before_lock = False

        async def _get_draft(self, *args, for_update=False, **kwargs):  # noqa: ANN002, ANN003
            draft = await super()._get_draft(
                *args,
                for_update=for_update,
                **kwargs,
            )
            if self.pause_before_lock and not for_update:
                self.pause_before_lock = False
                observed.set()
                await proceed.wait()
            return draft

    authority = PausingAuthority()
    try:
        async with sessions.begin() as setup_db:
            setup_db.add(Project(id=novel_id, title="Canon draft refresh"))
            await setup_db.flush()
            c0 = await authority.initialize_empty_canon(setup_db, novel_id)
            draft = await WorldBibleLifecycleService().create_draft(
                setup_db,
                WorldBiblePageDraftCreate(
                    novel_id=str(novel_id),
                    title="Original title",
                    page_type="background",
                ),
            )
            preview = await authority.preview(
                setup_db,
                CanonAdmissionPreviewRequest(
                    novel_id=novel_id,
                    expected_previous_head=c0.id,
                    input=PagePublishPreviewInputV1(
                        novel_id=novel_id,
                        draft_id=uuid.UUID(draft.id),
                    ),
                ),
            )

        request = CanonAdmissionRequest(
            novel_id=novel_id,
            decision_id=uuid.uuid4(),
            expected_previous_head=c0.id,
            confirmed=True,
            input=preview.normalized_input,
        )
        authority.pause_before_lock = True

        async def admit_once():
            async with sessions.begin() as db:
                return await authority.admit(
                    db,
                    request,
                    authorizer_id=BOOTSTRAP_ACCOUNT_ID,
                )

        admission = asyncio.create_task(admit_once())
        await asyncio.wait_for(observed.wait(), timeout=5)
        async with sessions.begin() as writer:
            await writer.execute(
                update(WorldBiblePageDraft)
                .where(WorldBiblePageDraft.id == uuid.UUID(draft.id))
                .values(
                    title="Changed while admission waited",
                    updated_at=datetime.now(UTC),
                )
            )
        proceed.set()
        with pytest.raises(DomainError) as exc_info:
            await admission
        assert exc_info.value.code == "canon_admission_stale"

        async with sessions() as verify_db:
            current_head = await verify_db.get(WorldCanonHead, novel_id)
            current_draft = await verify_db.get(
                WorldBiblePageDraft,
                uuid.UUID(draft.id),
            )
            assert current_head.current_revision_id == c0.id
            assert current_draft.title == "Changed while admission waited"
    finally:
        proceed.set()
        async with sessions.begin() as cleanup_db:
            await cleanup_db.execute(delete(Project).where(Project.id == novel_id))
        await engine.dispose()


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
