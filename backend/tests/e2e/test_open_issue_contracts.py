"""Issue #111/#210: native schema parity and concurrent public operations."""

import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import delete, func, inspect, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from infrastructure.tasks.models import AsyncTask
from modules.account.context import bind_principal, reset_principal
from modules.account.contracts import AccountPrincipal
from modules.account.models import Account
from modules.interaction.api import create_source_from_project
from modules.interaction.models import (
    InteractionGenerationAttempt,
    InteractionJourney,
    InteractionSourceRevision,
)
from modules.interaction.schemas import InteractionSourceFromProjectRequest
from modules.project.models import Project
from modules.writing.models import WritingInvalidationNotice
from modules.writing.repositories import WritingRecomputeRepository
from tests.e2e.config import DATABASE_URL

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]


async def test_notice_concurrent_replay_keeps_transaction_usable():
    engine = create_async_engine(DATABASE_URL, pool_size=3, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    nid = uuid.uuid4()
    release = asyncio.Event()
    arrived = 0

    async def save():
        nonlocal arrived
        async with sessions.begin() as db:
            arrived += 1
            if arrived == 2:
                release.set()
            await release.wait()
            row = await WritingRecomputeRepository.save_notice(
                db,
                novel_id=nid,
                receipt_id="same-receipt",
                chapter_index=1,
                notice={"message": "synthetic"},
            )
            assert await db.scalar(text("SELECT 1")) == 1
            return row.id

    try:
        async with sessions.begin() as db:
            db.add(Project(id=nid, title="Concurrent notice"))
        results = await asyncio.wait_for(asyncio.gather(save(), save()), timeout=15)
        assert results[0] == results[1]
        async with sessions() as db:
            assert (
                await db.scalar(
                    select(func.count())
                    .select_from(WritingInvalidationNotice)
                    .where(WritingInvalidationNotice.novel_id == nid)
                )
                == 1
            )
    finally:
        async with sessions.begin() as db:
            await db.execute(delete(Project).where(Project.id == nid))
        await engine.dispose()


@pytest.mark.parametrize("retry", [False, True])
async def test_concurrent_source_api_reuses_revision_and_enqueues_once(retry):
    engine = create_async_engine(DATABASE_URL, pool_size=3, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    nid, owner_id, draft_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    principal = AccountPrincipal(
        account_id=owner_id,
        status="active",
        identity_type="email",
        support_code=f"issue111-{owner_id.hex[:12]}",
    )
    release = asyncio.Event()
    arrived = 0
    submitted = 0

    async def submit(db, project_id, *_args, **_kwargs):
        nonlocal submitted
        submitted += 1
        task = AsyncTask(
            novel_id=uuid.UUID(project_id),
            task_type="import_deep_import",
            status="pending",
        )
        db.add(task)
        await db.flush()
        return {"task_id": str(task.id)}

    async def create():
        nonlocal arrived
        token = bind_principal(principal)
        try:
            async with sessions.begin() as db:
                arrived += 1
                if arrived == 2:
                    release.set()
                await release.wait()
                return await create_source_from_project(
                    db,
                    InteractionSourceFromProjectRequest(
                        project_id=str(nid), authorization_confirmed=True
                    ),
                )
        finally:
            reset_principal(token)

    try:
        async with sessions.begin() as db:
            db.add(
                Account(id=owner_id, status="active", support_code=principal.support_code)
            )
            await db.flush()
            db.add(
                Project(
                    id=nid,
                    owner_id=owner_id,
                    project_kind="author",
                    title="Synthetic source",
                )
            )
        with (
            patch(
                "modules.interaction.source_service.list_effective_chapter_indices",
                autospec=True,
                return_value=[1],
            ),
            patch(
                "modules.interaction.source_service.list_manuscript_sources",
                autospec=True,
                return_value=[
                    SimpleNamespace(
                        id=str(draft_id),
                        chapter_index=1,
                        version_number=1,
                        content_hash="a" * 64,
                        title="第一章",
                        content="合成文本",
                    )
                ],
            ),
            patch(
                "modules.interaction.source_service.start_deep_import",
                autospec=True,
                side_effect=submit,
            ),
        ):
            results = await asyncio.wait_for(
                asyncio.gather(create(), create()), timeout=15
            )
            if retry:
                async with sessions.begin() as db:
                    task = await db.scalar(
                        select(AsyncTask).where(AsyncTask.novel_id == nid)
                    )
                    task.status = "failed"
                token = bind_principal(principal)
                try:
                    async with sessions() as db:
                        from modules.interaction.source_service import (
                            InteractionSourceService,
                        )

                        view = await InteractionSourceService().get_source(
                            db, results[0].id
                        )
                        assert view.status == "failed"
                        revision = await db.get(
                            InteractionSourceRevision, uuid.UUID(view.id)
                        )
                        assert revision.status == "organizing"
                        assert not db.dirty
                finally:
                    reset_principal(token)
                arrived = 0
                release.clear()
                results = await asyncio.wait_for(
                    asyncio.gather(create(), create()), timeout=15
                )
                assert results[0].status == results[1].status == "organizing"
        assert results[0].id == results[1].id
        assert submitted == (2 if retry else 1)
        async with sessions() as db:
            assert (
                await db.scalar(
                    select(func.count())
                    .select_from(InteractionSourceRevision)
                    .where(InteractionSourceRevision.source_novel_id == nid)
                )
                == 1
            )
    finally:
        async with sessions.begin() as db:
            await db.execute(delete(Project).where(Project.id == nid))
            await db.execute(delete(Account).where(Account.id == owner_id))
        await engine.dispose()


async def test_source_orm_matches_migrated_jsonb_and_server_defaults(db_session):
    groups = [
        (
            InteractionSourceRevision,
            {
                name: None
                for name in (
                    "source_manifest",
                    "anchor_manifest",
                    "reference_manifest",
                    "ambiguities",
                    "resolutions",
                    "readiness_summary",
                )
            },
        ),
        (
            InteractionJourney,
            {
                "source_anchor": "{}",
                "player_identity": "{}",
                "reference_policy": "{}",
                "source_context_epoch": "0",
            },
        ),
        (
            InteractionGenerationAttempt,
            {"reference_trace": "[]", "started_source_context_epoch": "0"},
        ),
    ]
    connection = await db_session.connection()
    for model, fields in groups:
        columns = await connection.run_sync(
            lambda conn: inspect(conn).get_columns(model.__tablename__)
        )
        actual = {column["name"]: column for column in columns}
        for name, expected in fields.items():
            metadata = model.__table__.c[name]
            if "epoch" not in name:
                assert isinstance(actual[name]["type"], JSONB)
                assert isinstance(metadata.type.dialect_impl(connection.dialect), JSONB)
            if expected is None:
                assert metadata.server_default is None
                assert actual[name]["default"] is None
            else:
                assert str(metadata.server_default.arg) == expected
                assert actual[name]["default"].split("::")[0].strip("'") == expected
