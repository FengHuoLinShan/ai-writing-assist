"""PostgreSQL: author CAS, project lock order and exact operation replay."""

import asyncio
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.errors import ConflictError
from modules.evolution.facade import switch_project_engine
from modules.evolution.ledger import persist_discovery_claim, save_ledger_decision
from modules.evolution.models import EvolutionLedgerEntry
from modules.evolution.tests.test_ledger_persistence import prepared
from modules.project.models import Project
from tests.e2e.config import DATABASE_URL

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]


@pytest_asyncio.fixture
async def ledger_project():
    engine = create_async_engine(DATABASE_URL, pool_size=3, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    nid = str(uuid4())
    try:
        async with sessions() as db:
            db.add(Project(id=UUID(nid), title="第三阶段并发合成验收"))
            await db.flush()
            await switch_project_engine(db, nid, to_engine="evolution", expected_epoch=1)
            claim, change = await prepared(db, nid)
            first = await persist_discovery_claim(
                db,
                nid,
                change,
                claim,
                operation_key="seed",
                review={"verdict": "supported"},
            )
            await db.commit()
        yield sessions, nid, first["entry_id"]
    finally:
        async with sessions() as db:
            await db.execute(delete(Project).where(Project.id == UUID(nid)))
            await db.commit()
        await engine.dispose()


@pytest.mark.parametrize("same_operation", [False, True])
async def test_author_decisions_serialize_without_lock_upgrade_deadlock(
    ledger_project, same_operation
):
    sessions, nid, entry_id = ledger_project
    operation = str(uuid4())

    async def decide(number):
        async with sessions() as db:
            try:
                result = await save_ledger_decision(
                    db,
                    nid,
                    entry_id,
                    {
                        "operation_id": operation if same_operation else str(uuid4()),
                        "expected_revision": 1,
                        "decision": "keep",
                        "note": "同一次判断" if same_operation else f"判断{number}",
                    },
                )
                await db.commit()
                return result
            except ConflictError as error:
                await db.rollback()
                return error

    results = await asyncio.wait_for(asyncio.gather(decide(1), decide(2)), 10)
    successes = [item for item in results if isinstance(item, dict)]
    if same_operation:
        assert len(successes) == 2 and sum(item["replayed"] for item in successes) == 1
    else:
        assert len(successes) == 1
        assert (
            next(item for item in results if isinstance(item, ConflictError)).code
            == "ledger_revision_conflict"
        )
    async with sessions() as db:
        entry = await db.scalar(
            select(EvolutionLedgerEntry).where(EvolutionLedgerEntry.id == UUID(entry_id))
        )
        assert entry.head_revision == 2
        assert entry.author_decision_json["decision"] == "keep"
