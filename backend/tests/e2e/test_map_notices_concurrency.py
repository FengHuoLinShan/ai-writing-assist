"""Dedicated PostgreSQL serializes map notice publication with authorization changes."""

import asyncio
from dataclasses import replace
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.config import get_settings
from infrastructure.tasks.models import AsyncTask
from modules.account.context import bind_principal, reset_principal
from modules.account.contracts import AccountPrincipal
from modules.account.models import Account
from modules.assistant import map_notices, proactive
from modules.assistant.models import AssistantNotice, AssistantRun
from modules.assistant.schemas import ProactivePolicy
from modules.project.models import Project
from modules.world.map_auto_draft_service import build_map_auto_drafts
from modules.world.tests.test_map_auto_draft_service import (
    _build_request,
    _stage_bound_clue,
)
from tests.e2e.config import DATABASE_URL

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]


@pytest_asyncio.fixture
async def notice_project(monkeypatch):
    engine = create_async_engine(DATABASE_URL, pool_size=4, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    owner, nid = uuid4(), uuid4()
    principal = AccountPrincipal(
        account_id=owner,
        status="active",
        identity_type="email",
        support_code="map-notice-" + owner.hex[:12],
    )
    token = bind_principal(principal)
    settings = replace(
        get_settings(),
        assistant_enabled=True,
        map_spatial_enabled_capabilities=("assistant.turn",),
    )
    monkeypatch.setattr(map_notices, "get_settings", lambda: settings)
    monkeypatch.setattr(proactive, "get_settings", lambda: settings)
    try:
        async with sessions.begin() as db:
            db.add(
                Account(id=owner, status="active", support_code=principal.support_code)
            )
            await db.flush()
            db.add(
                Project(
                    id=nid, owner_id=owner, title="Synthetic map notification concurrency"
                )
            )
            await db.flush()
            scene, _a, _b, clue = await _stage_bound_clue(db, str(nid))
            result = await build_map_auto_drafts(
                db, str(nid), _build_request(scene, clue)
            )
            await proactive.save_policy(
                db, str(nid), ProactivePolicy(enabled=True, categories=["world"])
            )
        yield sessions, str(nid), str(result.batch_id)
    finally:
        async with sessions.begin() as db:
            await db.execute(delete(Project).where(Project.id == nid))
            await db.execute(delete(Account).where(Account.id == owner))
        reset_principal(token)
        await engine.dispose()


async def publish(sessions, nid, batch_id):
    async with sessions.begin() as db:
        await proactive.mark_changed(db, nid, "map_auto_draft_batch", batch_id)


async def revoke(sessions, nid):
    async with sessions.begin() as db:
        await proactive.save_policy(db, nid, ProactivePolicy(enabled=False))


async def assert_blocked(task):
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(asyncio.shield(task), timeout=0.2)


async def test_same_generation_concurrent_events_coalesce_exactly_once(notice_project):
    sessions, nid, batch_id = notice_project
    await asyncio.wait_for(
        asyncio.gather(*(publish(sessions, nid, batch_id) for _ in range(3))), timeout=15
    )
    async with sessions() as db:
        notices = list(
            await db.scalars(
                select(AssistantNotice).where(AssistantNotice.novel_id == nid)
            )
        )
        assert len(notices) == 1
        assert len(notices[0].result_ref_json["events"]) == 1
        visible = (await proactive.list_notices(db, nid))["items"]
        assert len(visible) == 1 and "待审核草图" in visible[0]["summary"]
        for model in (AsyncTask, AssistantRun):
            assert (
                await db.scalar(
                    select(func.count()).select_from(model).where(model.novel_id == nid)
                )
                == 0
            )


async def test_revocation_commits_before_waiting_publication(notice_project):
    sessions, nid, batch_id = notice_project
    contender = None
    try:
        async with sessions.begin() as db:
            await proactive.save_policy(db, nid, ProactivePolicy(enabled=False))
            contender = asyncio.create_task(publish(sessions, nid, batch_id))
            await assert_blocked(contender)
        await asyncio.wait_for(contender, timeout=15)
        async with sessions() as db:
            assert (
                await db.scalar(
                    select(func.count())
                    .select_from(AssistantNotice)
                    .where(AssistantNotice.novel_id == nid)
                )
                == 0
            )
            assert (await proactive.list_notices(db, nid))["items"] == []
    finally:
        if contender is not None:
            await asyncio.wait_for(contender, timeout=15)


async def test_publication_commits_before_waiting_revocation_then_becomes_invisible(
    notice_project,
):
    sessions, nid, batch_id = notice_project
    contender = None
    try:
        async with sessions.begin() as db:
            await proactive.mark_changed(db, nid, "map_auto_draft_batch", batch_id)
            contender = asyncio.create_task(revoke(sessions, nid))
            await assert_blocked(contender)
        await asyncio.wait_for(contender, timeout=15)
        async with sessions() as db:
            assert (
                await db.scalar(
                    select(func.count())
                    .select_from(AssistantNotice)
                    .where(AssistantNotice.novel_id == nid)
                )
                == 1
            )
            assert (await proactive.list_notices(db, nid))["items"] == []
    finally:
        if contender is not None:
            await asyncio.wait_for(contender, timeout=15)
