"""Concurrent freeze retries and author progress use one durable PG scope."""

import asyncio
import uuid

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.errors import ConflictError
from modules.account.context import bind_principal, reset_principal
from modules.account.contracts import AccountPrincipal
from modules.account.models import Account
from modules.project.models import Project
from modules.world import review_scope as scope
from modules.world.models import CoreEntity, WorldEntityReviewScope
from tests.e2e.config import require_e2e_database_url

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]


async def test_concurrent_freeze_retries_keep_one_manifest_and_progress_cas():
    engine = create_async_engine(require_e2e_database_url(), pool_size=4)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    owner, novel, entity = (uuid.uuid4() for _ in range(3))
    principal = AccountPrincipal(
        account_id=owner,
        status="active",
        identity_type="email",
        support_code="scope-" + owner.hex[:12],
    )
    token = bind_principal(principal)
    try:
        async with sessions.begin() as db:
            db.add(
                Account(id=owner, status="active", support_code=principal.support_code)
            )
            await db.flush()
            db.add(Project(id=novel, owner_id=owner, title="冻结清单并发合成项目"))
            await db.flush()
            db.add(
                CoreEntity(
                    id=entity,
                    novel_id=novel,
                    name="沈砚",
                    entity_type="character",
                    status="canonical",
                )
            )
        data = scope.ScopeCreate(
            operation_id=uuid.uuid4(), filters={"display_state": "active"}
        )

        async def freeze():
            async with sessions.begin() as db:
                return await scope.freeze(db, str(novel), data)

        first, second = await asyncio.gather(freeze(), freeze())
        assert (
            first["id"] == second["id"] and first["fingerprint"] == second["fingerprint"]
        )
        async with sessions() as db:
            assert (
                await db.scalar(
                    select(func.count())
                    .select_from(WorldEntityReviewScope)
                    .where(WorldEntityReviewScope.novel_id == novel)
                )
                == 1
            )

        async def mark(disposition):
            try:
                async with sessions.begin() as db:
                    return await scope.decide(
                        db,
                        str(novel),
                        first["id"],
                        scope.ScopeDecision(
                            expected_revision=1,
                            entity_ids=[entity],
                            disposition=disposition,
                        ),
                    )
            except ConflictError:
                return "conflict"

        results = await asyncio.gather(mark("checked"), mark("deferred"))
        assert sum(item == "conflict" for item in results) == 1
        async with sessions() as db:
            actual = await scope.read_scope(db, str(novel), first["id"])
            assert actual["revision"] == 2 and actual["checked"] + actual["deferred"] == 1
    finally:
        async with sessions.begin() as db:
            await db.execute(delete(Project).where(Project.id == novel))
            await db.execute(delete(Account).where(Account.id == owner))
        reset_principal(token)
        await engine.dispose()
