"""Dedicated PostgreSQL budgets: atomic reservations and safe migration downgrade."""

import asyncio
import os
import subprocess
import sys
from uuid import uuid4

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from infrastructure.llm.tests.test_luna_context_scope import luna_snapshot
from modules.evolution.models import EvolutionRun
from modules.evolution.store import BudgetExhaustedError, PostgresAttemptStore
from modules.project.models import Project
from tests.e2e.config import DATABASE_URL

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]


def project(nid):
    return Project(
        id=nid,
        title="范围预算合成验收",
        genre="奇幻",
        tone="测试",
        language="zh",
        target_length="novel",
        current_stage="writing",
    )


async def test_concurrent_finite_and_scope_reservations():
    engine = create_async_engine(DATABASE_URL, pool_size=8, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    nid = uuid4()
    try:
        async with sessions() as db:
            db.add(project(nid))
            await db.flush()
            store = PostgresAttemptStore(db, str(nid))
            await store.register_run(
                "finite", mode="bootstrap", execution_mode="shadow", budget_total=8
            )
            scope = await store.register_run(
                "scope",
                mode="bootstrap",
                execution_mode="shadow",
                budget_total=None,
                llm_snapshot=luna_snapshot(),
            )
            scope.reading_plan_json = {"budget_mode": "confirmed_scope"}
            await db.commit()

        async def reserve(key):
            async with sessions() as db:
                try:
                    value = await PostgresAttemptStore(db, str(nid)).reserve_budget(
                        key, 1
                    )
                    await db.commit()
                    return True, value
                except BudgetExhaustedError:
                    await db.rollback()
                    return False, None

        finite = await asyncio.gather(*(reserve("finite") for _ in range(16)))
        assert sum(ok for ok, _ in finite) == 8
        scope = await asyncio.gather(*(reserve("scope") for _ in range(24)))
        assert all(ok and value is None for ok, value in scope)
        async with sessions() as db:
            rows = (
                await db.scalars(select(EvolutionRun).where(EvolutionRun.novel_id == nid))
            ).all()
            assert {row.run_key: row.budget_remaining for row in rows} == {
                "finite": 0,
                "scope": None,
            }
    finally:
        async with sessions() as db:
            await db.execute(delete(Project).where(Project.id == nid))
            await db.commit()
        await engine.dispose()


def migrate(direction, revision):
    return subprocess.run(
        [sys.executable, "-m", "alembic", direction, revision],
        env={**os.environ, "DATABASE_URL": DATABASE_URL, "APP_ENV": "test"},
        capture_output=True,
        text=True,
        timeout=120,
    )


async def test_migration_keeps_legacy_quota_and_refuses_null_downgrade():
    engine = create_async_engine(DATABASE_URL, pool_size=1, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    nid = uuid4()
    try:
        async with sessions() as db:
            db.add(project(nid))
            await db.flush()
            run = await PostgresAttemptStore(db, str(nid)).register_run(
                "legacy", mode="bootstrap", execution_mode="shadow", budget_total=9
            )
            run.budget_remaining = 4
            await db.commit()
        result = await asyncio.to_thread(
            migrate, "downgrade", "20261013_delta_category_text"
        )
        assert result.returncode == 0, result.stderr
        result = await asyncio.to_thread(migrate, "upgrade", "head")
        assert result.returncode == 0, result.stderr
        async with sessions() as db:
            store = PostgresAttemptStore(db, str(nid))
            run = await store.load_run("legacy")
            assert (run.budget_total, run.budget_remaining) == (9, 4)
            run = await store.register_run(
                "scope",
                mode="bootstrap",
                execution_mode="shadow",
                budget_total=None,
                llm_snapshot=luna_snapshot(),
            )
            run.reading_plan_json = {"budget_mode": "confirmed_scope"}
            await db.commit()
        result = await asyncio.to_thread(
            migrate, "downgrade", "20261013_delta_category_text"
        )
        assert result.returncode != 0 and "downgrade refused" in result.stderr
        async with sessions() as db:
            assert (
                await db.execute(text("SELECT version_num FROM alembic_version"))
            ).scalar_one() == "20261014_model_scope_budget"
            assert (
                await PostgresAttemptStore(db, str(nid)).load_run("scope")
            ).budget_remaining is None
    finally:
        async with sessions() as db:
            await db.execute(delete(Project).where(Project.id == nid))
            await db.commit()
        result = await asyncio.to_thread(migrate, "upgrade", "head")
        assert result.returncode == 0, result.stderr
        await engine.dispose()


async def test_native_reading_finishes_confirmed_range_beyond_old_quota(
    monkeypatch, tmp_path
):
    import json
    from unittest.mock import patch
    from uuid import UUID

    from infrastructure.llm.codex_provider import CodexProvider
    from infrastructure.llm.schemas import LLMCallResponse, LLMUsage
    from infrastructure.llm.workflow_budget import AIRunEnvelope, ai_run_scope
    from infrastructure.tasks.models import AsyncTask
    from infrastructure.tasks.registry import TaskRegistry
    from infrastructure.tasks.worker import TaskRunEnvelopeKeeper
    from modules.evolution.facade import switch_project_engine
    from modules.evolution.tasks import handle_evolution_scene_step
    from modules.evolution.tests.test_workflow import (
        request_start,
        seed,
        structure_response,
    )
    from modules.evolution.workflow import reading_status, start_reading
    from modules.project.tests.test_codex_runtime import seed as seed_codex

    engine = create_async_engine(DATABASE_URL, pool_size=4, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    nid, calls = uuid4(), []

    async def provider(self, request, *, complete_stream=False):
        title = request.response_format["json_schema"]["name"]
        calls.append(title)
        data = {}
        if title == "SceneSample":
            message = next(
                item.content for item in request.messages if item.role == "user"
            )
            prose = message.split("正文】\n", 1)[1].split("\n", 1)[0]
            data = {
                "observations": [{"predicate": prose, "quote": prose}],
                "scene_events": [],
            }
        elif title == "DiscoveryOutput":
            data = {"changes": [], "coverage": "inspected", "coverage_note": "合成输入"}
        elif response := structure_response(request):
            return response
        return LLMCallResponse(
            content=json.dumps(data),
            model="gpt-6-luna",
            provider="codex",
            finish_reason="stop",
            usage=LLMUsage(prompt_tokens=10, completion_tokens=10, total_tokens=20),
        )

    monkeypatch.setattr(CodexProvider, "generate", provider)
    monkeypatch.setattr(
        "infrastructure.llm.codex_identity.codex_login_identity",
        lambda: "synthetic-range",
    )
    monkeypatch.setattr(
        "infrastructure.llm.model_admission._admission_directory", lambda: tmp_path
    )
    try:
        with (
            patch(
                "infrastructure.llm.codex_provider.codex_text_enabled",
                autospec=True,
                return_value=True,
            ),
            patch(
                "infrastructure.llm.codex_provider.codex_connection_fingerprint",
                autospec=True,
                return_value="test-host",
            ),
        ):
            async with sessions() as db:
                db.add(project(nid))
                await db.flush()
                await switch_project_engine(
                    db, str(nid), to_engine="evolution", expected_epoch=1
                )
                await seed_codex(db)
                for index in range(1, 13):
                    await seed(db, str(nid), index, f"第{index}场天亮了。")
                request = await request_start(
                    db,
                    str(nid),
                    end_chapter=12,
                    request_limit=None,
                    discover_details=True,
                )
                state = await start_reading(db, str(nid), request)
                task_id = state["run"]["task_id"]
                while task_id:
                    task = await db.get(AsyncTask, UUID(task_id))
                    keeper = TaskRunEnvelopeKeeper(
                        task=task,
                        lease_id="",
                        registry=TaskRegistry(),
                        session_factory=None,
                    )
                    ledger = AIRunEnvelope(keeper.open().snapshot())
                    assert ledger.snapshot().version == 2 and ledger.request_limit is None
                    with ai_run_scope(ledger):
                        result = await handle_evolution_scene_step(db, task)
                    task.mark_done(result)
                    await db.commit()
                    task_id = result.get("next_task_id")
                final = await reading_status(db, str(nid))
                assert final["run"]["status"] == "completed"
                assert final["run"]["budget_remaining"] is None and len(calls) > 20
                assert final["run"]["discovery_enabled"]
    finally:
        async with sessions() as db:
            await db.execute(delete(Project).where(Project.id == nid))
            await db.commit()
        await engine.dispose()
