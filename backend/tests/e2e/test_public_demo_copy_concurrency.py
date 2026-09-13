from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.config import get_settings
from modules.account.context import bind_principal, reset_principal
from modules.account.contracts import AccountPrincipal
from modules.account.models import Account
from modules.project.demo_copy import DemoProjectCopyService
from modules.project.models import DemoProjectCopy, Project
from tests.e2e.config import DATABASE_URL

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]


def _principal(account_id: uuid.UUID, support_code: str) -> AccountPrincipal:
    return AccountPrincipal(
        account_id=account_id,
        status="active",
        identity_type="email",
        support_code=support_code,
    )


async def test_demo_copy_serializes_first_copy_for_an_owner_without_projects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_async_engine(DATABASE_URL, pool_size=3, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    source_owner_id = uuid.uuid4()
    target_owner_id = uuid.uuid4()
    source_id = uuid.uuid4()
    support_code = f"DEMO-COPY-{target_owner_id.hex[:12]}"
    ready = 0
    ready_lock = asyncio.Lock()
    release = asyncio.Event()

    monkeypatch.setenv("AUTH_MODE", "public")
    monkeypatch.setenv("AUTH_SECRET_KEY", "e2e-public-demo-secret-key-32-bytes")
    monkeypatch.setenv("PUBLIC_DEMO_ENABLED", "true")
    monkeypatch.setenv("PUBLIC_DEMO_PROJECT_ID", str(source_id))
    monkeypatch.setenv("PUBLIC_DEMO_VERSION", "concurrency-v1")
    get_settings.cache_clear()

    try:
        async with sessions.begin() as setup_db:
            setup_db.add_all(
                [
                    Account(
                        id=source_owner_id,
                        status="active",
                        support_code=f"DEMO-SOURCE-{source_owner_id.hex[:12]}",
                    ),
                    Account(
                        id=target_owner_id,
                        status="active",
                        support_code=support_code,
                    ),
                ]
            )
            setup_db.add(
                Project(
                    id=source_id,
                    owner_id=source_owner_id,
                    title="并发演示源",
                    project_kind="author",
                    language="zh",
                    default_reveal_policy="author_safe",
                    settings={},
                )
            )

        async def copy_once():
            nonlocal ready
            async with ready_lock:
                ready += 1
                if ready == 2:
                    release.set()
            await release.wait()
            token = bind_principal(_principal(target_owner_id, support_code))
            try:
                async with sessions.begin() as db:
                    return await DemoProjectCopyService().copy(db)
            finally:
                reset_principal(token)

        first, second = await asyncio.gather(copy_once(), copy_once())

        assert {first.status, second.status} == {"created", "existing"}
        assert first.project.id == second.project.id
        async with sessions() as verify_db:
            receipts = list(
                (
                    await verify_db.execute(
                        select(DemoProjectCopy).where(
                            DemoProjectCopy.owner_id == target_owner_id
                        )
                    )
                ).scalars()
            )
            assert len(receipts) == 1
    finally:
        get_settings.cache_clear()
        async with sessions.begin() as cleanup_db:
            await cleanup_db.execute(
                delete(Account).where(Account.id.in_([source_owner_id, target_owner_id]))
            )
        await engine.dispose()
