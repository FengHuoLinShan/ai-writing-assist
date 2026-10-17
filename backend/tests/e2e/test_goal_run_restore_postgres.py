"""Run the real R2 domain restore and CAS contracts on separate PostgreSQL sessions."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.main import app as _app  # noqa: F401 - register production operations
from modules.account.facade import current_account_id
from modules.account.models import Account
from modules.assistant.models import AssistantRun
from modules.assistant.tests import test_goal_runs as goal_cases
from modules.project.models import Project, ProjectAuthorTask
from modules.world.models import CoreEntity
from modules.world.models.dossier import WorldObjectDossierEntry
from tests.e2e.config import DATABASE_URL

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]


@pytest.mark.parametrize(
    ("scenario", "needs_entity"),
    [
        (
            "test_goal_r2_project_task_update_restores_through_real_domain_operation",
            False,
        ),
        ("test_goal_r2_project_restore_uses_cas_after_author_edits", False),
        ("test_goal_r2_dossier_edit_restores_through_real_domain_history", True),
        ("test_goal_r2_dossier_restore_uses_revision_cas_after_author_edits", True),
    ],
)
async def test_goal_r2_domain_restore_on_postgres(monkeypatch, scenario, needs_entity):
    engine = create_async_engine(DATABASE_URL, pool_size=3, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    owner_id = current_account_id()
    project_id, entity_id = uuid.uuid4(), uuid.uuid4()
    case = getattr(goal_cases, scenario)
    try:
        async with sessions.begin() as db:
            if await db.get(Account, owner_id) is None:
                db.add(Account(id=owner_id, support_code=owner_id.hex[:16]))
            db.add(Project(id=project_id, owner_id=owner_id, title="Goal R2 PG"))
            if needs_entity:
                db.add(
                    CoreEntity(
                        id=entity_id,
                        novel_id=project_id,
                        entity_type="item",
                        name="Goal PG 对象",
                        status="canonical",
                    )
                )
        async with sessions() as db:
            if needs_entity:
                await case(db, str(project_id), str(entity_id), monkeypatch)
            else:
                await case(db, str(project_id), monkeypatch)
        # A new connection must see the exact final domain value after restore
        # or after an intervening author edit blocks the restore CAS.
        async with sessions() as db:
            if needs_entity:
                entry = await db.scalar(
                    select(WorldObjectDossierEntry).where(
                        WorldObjectDossierEntry.novel_id == project_id,
                        WorldObjectDossierEntry.entity_id == entity_id,
                        WorldObjectDossierEntry.status == "active",
                    )
                )
                assert entry is not None
                expected = "作者后来修订" if "cas_after" in scenario else "原始来源"
                assert entry.content == expected
            else:
                task = await db.scalar(
                    select(ProjectAuthorTask).where(
                        ProjectAuthorTask.novel_id == project_id
                    )
                )
                assert task is not None
                expected = "作者后来修改" if "cas_after" in scenario else "原始任务"
                assert task.title == expected
    finally:
        await engine.dispose()


async def test_goal_partial_unique_blocks_second_active_run_across_connections():
    engine = create_async_engine(DATABASE_URL, pool_size=2, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    owner_id, project_id = uuid.uuid4(), uuid.uuid4()

    def run(status: str) -> AssistantRun:
        return AssistantRun(
            novel_id=project_id,
            owner_id=owner_id,
            mode="goal",
            status=status,
            request_hash=uuid.uuid4().hex,
            request_json={},
            budget_json={},
            checkpoint_json={},
            result_json={},
        )

    try:
        async with sessions.begin() as db:
            db.add(Account(id=owner_id, support_code=owner_id.hex[:16]))
            db.add(Project(id=project_id, owner_id=owner_id, title="Goal unique PG"))
        first = run("waiting_approval")
        async with sessions.begin() as db:
            db.add(first)
        second = run("running")
        async with sessions() as db:
            db.add(second)
            with pytest.raises(IntegrityError, match="uq_assistant_goal_run_active"):
                await db.commit()
            await db.rollback()
        async with sessions.begin() as db:
            stored = await db.get(AssistantRun, first.id)
            assert stored is not None
            stored.status = "completed"
        async with sessions.begin() as db:
            db.add(run("running"))
    finally:
        await engine.dispose()
