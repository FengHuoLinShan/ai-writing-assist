"""Dedicated PostgreSQL confirmation fencing; no provider or manuscript IO."""

import asyncio
import os
from uuid import uuid4

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.errors import ConflictError
from modules.account.facade import current_account_id
from modules.assistant.contracts import AssistantOperationContext
from modules.assistant.evidence_tools import fingerprint
from modules.assistant.models import AssistantActionBatch, AssistantRun
from modules.assistant.operations import decide_batch, operation_manifest, prepare_actions
from modules.assistant.schemas import BatchDecision, ProposedAction, WorkContext
from modules.project.facade import require_active_project
from modules.project.models import Project
from modules.world.project_vocabulary_service import read_project_vocabulary
from tests.e2e.config import require_e2e_database_url
from tests.utils import _create_project

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        os.getenv("RUN_E2E_TESTS") != "1", reason="requires explicit dedicated PostgreSQL"
    ),
]


async def test_confirmed_vocabulary_batch_rejects_lock_upgrade_then_completes_once():
    engine = create_async_engine(require_e2e_database_url(), pool_size=3, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    nid, run_id = uuid4(), uuid4()
    owner = str(current_account_id())
    try:
        async with sessions.begin() as db:
            await _create_project(db, nid)
            context = AssistantOperationContext(
                str(run_id), owner, WorkContext(scope="project")
            )
            actions = await prepare_actions(
                db,
                str(nid),
                [
                    ProposedAction(
                        key=f"term-{i}",
                        capability="world.vocabulary.create",
                        title=name,
                        arguments={"kind": "space", "name": name},
                    )
                    for i, name in enumerate(["星港", "月城"])
                ],
                context=context,
            )
            run = AssistantRun(
                id=run_id,
                novel_id=nid,
                owner_id=current_account_id(),
                request_hash="a" * 64,
                request_json={
                    "runtime_version": "4",
                    "operations": operation_manifest(),
                    "context": context.work.model_dump(mode="json"),
                },
            )
            db.add(run)
            await db.flush()
            batch = AssistantActionBatch(
                novel_id=nid,
                run_id=run_id,
                actions_json=actions,
                fingerprint=fingerprint(actions),
            )
            db.add(batch)
            await db.flush()
            batch_id = str(batch.id)
            decision = BatchDecision(
                novel_id=nid,
                fingerprint=batch.fingerprint,
                selected=[item["key"] for item in actions],
                confirmed=True,
            )

        async with sessions() as blocker, sessions() as contender:
            await require_active_project(blocker, str(nid))
            with pytest.raises(ConflictError):
                await asyncio.wait_for(
                    decide_batch(contender, batch_id, decision, owner), timeout=3
                )
            await contender.rollback()
            await blocker.rollback()

        async with sessions.begin() as db:
            result = await decide_batch(db, batch_id, decision, owner)
            assert result["status"] == "completed", result
        async with sessions.begin() as db:
            assert await decide_batch(db, batch_id, decision, owner) == result
            vocabulary = await read_project_vocabulary(db, str(nid))
            assert {item.name for item in vocabulary.items} == {"星港", "月城"}
            assert all(item.revision_number == 1 for item in vocabulary.items)
    finally:
        async with sessions.begin() as db:
            await db.execute(delete(Project).where(Project.id == nid))
        await engine.dispose()
