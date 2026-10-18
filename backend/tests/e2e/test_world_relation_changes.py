"""Two real PostgreSQL writers cannot apply one stale relation preview twice."""

import asyncio
import uuid

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.errors import ConflictError
from infrastructure.stable_hash import stable_hash
from modules.account.context import bind_principal, reset_principal
from modules.account.contracts import AccountPrincipal
from modules.account.models import Account
from modules.project.models import Project
from modules.world.models import CoreEntity
from modules.world.relation_changes import (
    RelationChange,
    apply_change,
    change_history,
    preview_change,
)
from modules.world.schemas import EntityRelationCreate
from modules.world.services.core.entity_relation_service import EntityRelationService
from tests.e2e.config import require_e2e_database_url

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]


@pytest.mark.parametrize("description", [None, "第一位作者确认的关系"])
async def test_same_relation_preview_has_one_winner_and_one_stale_receipt(description):
    engine = create_async_engine(require_e2e_database_url(), pool_size=4, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    owner, novel, first_id, second_id = (uuid.uuid4() for _ in range(4))
    principal = AccountPrincipal(
        account_id=owner,
        status="active",
        identity_type="email",
        support_code="rel-" + owner.hex[:12],
    )
    token = bind_principal(principal)
    written, release, competing = asyncio.Event(), asyncio.Event(), asyncio.Event()
    tasks = []
    try:
        async with sessions.begin() as db:
            db.add(
                Account(id=owner, status="active", support_code=principal.support_code)
            )
            await db.flush()
            db.add(Project(id=novel, owner_id=owner, title="关系并发合成项目"))
            await db.flush()
            db.add_all(
                [
                    CoreEntity(
                        id=first_id,
                        novel_id=novel,
                        name="沈砚",
                        entity_type="character",
                        status="canonical",
                    ),
                    CoreEntity(
                        id=second_id,
                        novel_id=novel,
                        name="船医",
                        entity_type="character",
                        status="canonical",
                    ),
                ]
            )
            await db.flush()
            row = await EntityRelationService().create(
                db,
                str(novel),
                EntityRelationCreate(
                    source_id=str(first_id),
                    target_id=str(second_id),
                    relation_type="ally_of",
                    relation_kind="social",
                    description="原关系",
                ),
            )
            relation_id = str(row.id)
            args = RelationChange(
                relation_id=relation_id,
                action="edit",
                changes={"description": description},
            )
            preview = await preview_change(db, str(novel), args)
        preview_hash, operation_id = stable_hash(preview), str(uuid.uuid4())

        async def winner():
            async with sessions.begin() as db:
                receipt = await apply_change(
                    db,
                    str(novel),
                    args,
                    operation_id=operation_id,
                    expected_preview_hash=preview_hash,
                    actor=str(owner),
                )
                written.set()
                await asyncio.wait_for(release.wait(), 10)
                return receipt

        async def loser():
            async with sessions.begin() as db:
                competing.set()
                return await apply_change(
                    db,
                    str(novel),
                    args,
                    operation_id=str(uuid.uuid4()),
                    expected_preview_hash=preview_hash,
                    actor=str(owner),
                )

        tasks.append(asyncio.create_task(winner()))
        await asyncio.wait_for(written.wait(), 10)
        tasks.append(asyncio.create_task(loser()))
        await asyncio.wait_for(competing.wait(), 10)
        await asyncio.sleep(0.1)
        assert not tasks[1].done()
        release.set()
        first_receipt = await tasks[0]
        with pytest.raises(ConflictError, match="重新预览"):
            await tasks[1]
        async with sessions.begin() as db:
            history = await change_history(db, str(novel), uuid.UUID(relation_id))
            assert len(history["items"]) == 1
            assert history["current"]["description"] == description
            assert (
                await apply_change(
                    db,
                    str(novel),
                    args,
                    operation_id=operation_id,
                    expected_preview_hash=preview_hash,
                    actor=str(owner),
                )
                == first_receipt
            )
            edit = RelationChange(
                relation_id=relation_id,
                action="edit",
                changes={"description": "后加说明"},
            )
            receipt = await apply_change(
                db,
                str(novel),
                edit,
                operation_id=str(uuid.uuid4()),
                expected_preview_hash=stable_hash(
                    await preview_change(db, str(novel), edit)
                ),
                actor=str(owner),
            )
            restore = RelationChange(
                relation_id=relation_id,
                action="restore",
                history_id=receipt["history_id"],
            )
            await apply_change(
                db,
                str(novel),
                restore,
                operation_id=str(uuid.uuid4()),
                expected_preview_hash=stable_hash(
                    await preview_change(db, str(novel), restore)
                ),
                actor=str(owner),
            )
        async with sessions() as db:
            actual = await change_history(db, str(novel), uuid.UUID(relation_id))
            assert actual["current"]["description"] == description
            assert actual["items"][0]["after"]["description"] == description
    finally:
        release.set()
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        async with sessions.begin() as db:
            await db.execute(delete(Project).where(Project.id == novel))
            await db.execute(delete(Account).where(Account.id == owner))
        reset_principal(token)
        await engine.dispose()
