"""Native PG races and old SQL prove project-wide ownership survives rollback."""

import asyncio
import os
import subprocess
import sys
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, select, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.errors import ConflictError
from infrastructure.tasks.lifecycle import TaskLifecycleService
from infrastructure.tasks.models import AsyncTask
from modules.evolution.facade import switch_project_engine
from modules.evolution.models import EvolutionRun
from modules.evolution.store import PostgresAttemptStore
from modules.imports.models import ImportWorkflowRun
from modules.imports.orchestrator import DeepImportOrchestrator
from modules.imports.workflow_runs import (
    ImportWorkflowOwnershipLost,
    ImportWorkflowRunService,
)
from modules.project.facade import get_understanding_engine, project_task_commit_guard
from modules.project.models import Project
from modules.story.continuity.models import MemoryEvent
from tests.e2e.config import DATABASE_URL

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]


@pytest.mark.parametrize("scenario", ["identity", "history"])
async def test_scene_world_identity_and_receipt_history_on_postgres(
    project, monkeypatch, scenario
):
    """Reuse real handler assertions with PG transactions; provider stays synthetic."""
    import json

    from infrastructure.llm.providers import OpenAIProvider
    from infrastructure.llm.schemas import LLMMessage
    from modules.evolution import sampler, workflow
    from modules.evolution.llm_sampler import ProjectLLMSampler
    from modules.evolution.tests.test_world import (
        test_first_scene_identity_is_reviewed_before_atomic_presence_commit,
        test_relation_history_uses_real_prefix_and_not_mutated_world_rows,
    )

    async def snapshot(db, novel_id):
        return {"profile": {"model": "synthetic-no-network"}}

    class Client:
        async def generate_structured(self, request, schema, **kwargs):
            request = request.model_copy(
                update={
                    "model": "synthetic-no-network",
                    "messages": [
                        *request.messages,
                        LLMMessage(
                            role="system",
                            content="schema: " + json.dumps(schema.model_json_schema()),
                        ),
                    ],
                }
            )
            response = await OpenAIProvider.generate(None, request)
            return schema.model_validate_json(response.content)

    @asynccontextmanager
    async def resolve(**kwargs):
        yield ProjectLLMSampler(Client())

    monkeypatch.setattr(workflow, "build_project_llm_execution_snapshot", snapshot)
    monkeypatch.setattr(sampler, "resolve_scene_sampler", resolve)
    sessions, nid = project
    async with sessions() as db:
        await switch_project_engine(db, nid, to_engine="evolution", expected_epoch=1)
        await db.commit()
        if scenario == "identity":
            await test_first_scene_identity_is_reviewed_before_atomic_presence_commit(
                db, nid, None, monkeypatch, "domain_write"
            )
        else:
            await test_relation_history_uses_real_prefix_and_not_mutated_world_rows(
                db, nid, None, monkeypatch
            )


@pytest_asyncio.fixture
async def project():
    engine = create_async_engine(DATABASE_URL, pool_size=4, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    nid = uuid4()
    async with sessions() as db:
        db.add(Project(id=nid, title="理解主链迁移专用测试"))
        await db.commit()
    try:
        yield sessions, str(nid)
    finally:
        async with sessions() as db:
            await db.execute(delete(Project).where(Project.id == nid))
            await db.commit()
        await engine.dispose()


async def legacy_start(db, nid):
    return await DeepImportOrchestrator()._enqueue_workflow(
        db,
        novel_id=nid,
        task_type="deep_import",
        start_chapter=1,
        end_chapter=2,
        stage=None,
        context_mode="working",
        include_pending_objects=True,
        high_quality=False,
        replace_existing=False,
        authorization_snapshot={
            "adoption_policy": "user_authorized_pipeline",
            "authorization_confirmed": True,
        },
        llm_execution_snapshot={"provider": "fixture", "model": "no-network"},
    )


async def test_legacy_admission_races_canary_exactly_one_owner(project):
    sessions, nid = project

    async def legacy():
        async with sessions() as db:
            try:
                await legacy_start(db, nid)
                await db.commit()
                return "legacy"
            except ConflictError:
                await db.rollback()
                return None

    async def evolution():
        async with sessions() as db:
            try:
                await switch_project_engine(
                    db, nid, to_engine="evolution", expected_epoch=1
                )
                await PostgresAttemptStore(db, nid).register_run(
                    "canary", mode="append", budget_total=3
                )
                await db.commit()
                return "evolution"
            except ConflictError:
                await db.rollback()
                return None

    outcomes = await asyncio.wait_for(asyncio.gather(legacy(), evolution()), 10)
    assert len([x for x in outcomes if x]) == 1
    async with sessions() as db:
        state = await get_understanding_engine(db, nid)
        assert state["engine"] == next(x for x in outcomes if x)
        imports = list(
            await db.scalars(
                select(ImportWorkflowRun).where(
                    ImportWorkflowRun.novel_id == nid,
                    ImportWorkflowRun.status.in_(["pending", "running"]),
                )
            )
        )
        evolved = list(
            await db.scalars(
                select(EvolutionRun).where(
                    EvolutionRun.novel_id == nid, EvolutionRun.status == "active"
                )
            )
        )
        assert len(imports) + len(evolved) == 1


async def test_reading_double_submit_and_unsampled_source_invalidation(
    project, monkeypatch
):
    from modules.evolution import workflow
    from modules.story.facade import create_scene
    from modules.writing.facade import create_draft_only

    sessions, nid = project

    async def snapshot(db, novel_id):
        return {"profile": {"model": "synthetic-no-network"}}

    monkeypatch.setattr(workflow, "build_project_llm_execution_snapshot", snapshot)
    async with sessions() as db:
        await switch_project_engine(db, nid, to_engine="evolution", expected_epoch=1)
        await create_draft_only(db, nid, 1, "第一章", "天亮了。")
        await create_scene(db, nid, {"scene_index": 0, "chapter_ids": ["1"]})
        request = workflow.ReadingRequest(
            operation_id=uuid4(), end_chapter=1, request_limit=1
        )
        preview = await workflow.preview_reading(db, nid, request)
        start = workflow.ReadingStart(
            **request.model_dump(),
            expected_fingerprint=preview["fingerprint"],
            authorization_confirmed=True,
        )
        await db.commit()

    async def submit():
        async with sessions() as db:
            result = await workflow.start_reading(db, nid, start)
            await db.commit()
            return result["run"]

    first, second = await asyncio.wait_for(asyncio.gather(submit(), submit()), 10)
    assert first["task_id"] == second["task_id"]
    async with sessions() as db:
        await create_draft_only(db, nid, 1, "第一章", "天黑了。")
        await db.commit()
        run = await PostgresAttemptStore(db, nid).load_run(first["run_key"])
        assert run.status == "source_stale" and run.budget_remaining == 1
        assert run.committed_scene_index == -1


@pytest.mark.parametrize("failure", ["apply", "sampling", "shutdown", "owner_stop"])
@pytest.mark.parametrize("phase", ["understanding", "preparation"])
async def test_reading_worker_persists_recovery_without_resampling(
    project, monkeypatch, failure, phase
):
    from contextlib import asynccontextmanager
    from types import SimpleNamespace

    from infrastructure.tasks.worker import TaskWorker
    from modules.evolution import preparation, sampler, workflow
    from modules.imports import facade as imports
    from modules.story import facade as story
    from modules.writing.facade import create_draft_only

    sessions, nid = project
    calls = []
    call_limit = 2 if phase == "understanding" and failure != "sampling" else 1

    async def snapshot(db, novel_id):
        return {"profile": {"model": "synthetic-no-network"}}

    class Sampler:
        async def execute_world_request(self, **inputs):
            assert inputs["schema_name"] == "Phase2aSceneExtractionOutput"
            calls.append("world")
            return {"result": {}}

        async def sample(self, *, scene_text, input_manifest):
            calls.append(scene_text)
            if failure == "sampling":
                raise RuntimeError("provider result unknown")
            return {"observations": [], "scene_events": []}

    async def factory(db, novel_id, **kwargs):
        return Sampler()

    original_apply = (
        imports.commit_scene_boundaries
        if phase == "preparation"
        else story.replace_scene_memory_events
    )
    apply_calls = 0

    async def apply_once(*args, **kwargs):
        nonlocal apply_calls
        apply_calls += 1
        if apply_calls == 1:
            if failure == "owner_stop":
                await args[0].rollback()
                async with sessions() as control:
                    await switch_project_engine(
                        control,
                        nid,
                        to_engine="read_only",
                        expected_epoch=2,
                        stop_active=True,
                    )
                    await control.commit()
            if failure in {"shutdown", "owner_stop"}:
                raise asyncio.CancelledError
            raise RuntimeError("apply interrupted after durable sampling")
        return await original_apply(*args, **kwargs)

    monkeypatch.setattr(workflow, "build_project_llm_execution_snapshot", snapshot)
    monkeypatch.setitem(sampler._SAMPLER_REGISTRY, "project_llm", factory)
    if phase == "preparation":

        class Client:
            async def generate_structured(self, request, schema, **kwargs):
                calls.append(request)
                if failure == "sampling":
                    raise RuntimeError("provider result unknown")
                return schema.model_validate(
                    {
                        "window_edges": {
                            "leading_relation": "new_scene",
                            "trailing_relation": "ends_in_input",
                        },
                        "scenes": [
                            {
                                "title": "天亮",
                                "goal": "迎接清晨",
                                "core_conflict_status": "not_applicable",
                                "start_chapter": 1,
                                "end_chapter": 1,
                                "start_anchor": "天亮了。",
                                "end_anchor": "天亮了。",
                                "boundary_status": "complete",
                                "confidence": 0.95,
                            }
                        ],
                    }
                )

        @asynccontextmanager
        async def client(*args):
            yield Client()

        monkeypatch.setattr(preparation, "open_project_snapshot_llm_client", client)
        monkeypatch.setattr(imports, "commit_scene_boundaries", apply_once)
    else:
        monkeypatch.setattr(story, "replace_scene_memory_events", apply_once)
    async with sessions() as db:
        await switch_project_engine(db, nid, to_engine="evolution", expected_epoch=1)
        await create_draft_only(db, nid, 1, "第一章", "天亮了。")
        if phase != "preparation":
            await story.create_scene(db, nid, {"scene_index": 0, "chapter_ids": ["1"]})
        request = workflow.ReadingRequest(
            operation_id=uuid4(), end_chapter=1, request_limit=call_limit
        )
        preview = await workflow.preview_reading(db, nid, request)
        result = await workflow.start_reading(
            db,
            nid,
            workflow.ReadingStart(
                **request.model_dump(),
                expected_fingerprint=preview["fingerprint"],
                authorization_confirmed=True,
            ),
        )
        key, task_id = result["run"]["run_key"], result["run"]["task_id"]
        await db.commit()
    worker = TaskWorker(
        db_manager=SimpleNamespace(engine=sessions.kw["bind"], session_factory=sessions),
        task_commit_guard=project_task_commit_guard,
    )
    failed = await worker.run_once(task_id=task_id, novel_id=nid)
    assert failed.status == ("cancelled" if failure == "owner_stop" else "failed")
    assert len(calls) == call_limit
    async with sessions() as db:
        # Read independently of the handler's detached task and rollback session.
        task = await db.get(AsyncTask, UUID(task_id))
        state = (await workflow.reading_status(db, nid, key))["run"]
        if failure == "owner_stop":
            assert not state["can_resume"] and state["status"] == "stopped"
            assert state["budget_remaining"] == 0
            with pytest.raises(ConflictError):
                await workflow.resume_reading(db, nid, key)
            return
        recoverable = failure in {"apply", "shutdown"}
        assert task.meta["recovery_required"] is recoverable
        assert task.result["lifecycle"]["recovery_required"] is recoverable
        assert state["can_resume"] is recoverable
        store = PostgresAttemptStore(db, nid)
        pending = await store.load_pending_frozen(key, 0)
        attempt_id = pending.attempt_id if pending else None
        if phase == "preparation":
            original_calls = deepcopy(
                (await store.load_run(key)).reading_plan_json["preparation"]["calls"]
            )
        assert state["budget_remaining"] == 0
        if failure == "sampling":
            assert state["status"] == "needs_reconciliation"
            with pytest.raises(ConflictError):
                await workflow.resume_reading(db, nid, key)
            return
        await workflow.resume_reading(db, nid, key)
        await db.commit()
    completed = await worker.run_once(task_id=task_id, novel_id=nid)
    assert completed.status == "done" and len(calls) == call_limit
    if phase != "preparation":
        assert completed.result["attempt_id"] == attempt_id
    async with sessions() as db:
        state = (await workflow.reading_status(db, nid, key))["run"]
        assert (
            state["status"] == ("needs_budget" if phase == "preparation" else "completed")
            and state["budget_remaining"] == 0
        )
        assert state["budget_total"] == call_limit
        if phase == "preparation":
            stored = await PostgresAttemptStore(db, nid).load_run(key)
            assert stored.reading_plan_json["preparation"]["calls"] == original_calls


async def test_boundary_response_and_source_edit_keep_project_first_lock_order(
    project, monkeypatch
):
    from contextlib import asynccontextmanager
    from types import SimpleNamespace

    from infrastructure.tasks.worker import TaskWorker
    from modules.evolution import preparation, workflow
    from modules.project.facade import require_active_project_exclusive
    from modules.story.facade import get_scenes_by_novel
    from modules.writing.facade import create_draft_only

    sessions, nid = project
    returned, editing = asyncio.Event(), asyncio.Event()
    calls = []

    async def snapshot(db, novel_id):
        return {"profile": {"model": "synthetic-no-network"}}

    async def generate(request, schema, **kwargs):
        calls.append(request)
        return schema.model_validate(
            {
                "window_edges": {
                    "leading_relation": "new_scene",
                    "trailing_relation": "ends_in_input",
                },
                "scenes": [
                    {
                        "title": "天亮",
                        "goal": "迎接清晨",
                        "core_conflict_status": "not_applicable",
                        "start_chapter": 1,
                        "end_chapter": 1,
                        "start_anchor": "天亮了。",
                        "end_anchor": "天亮了。",
                        "boundary_status": "complete",
                        "confidence": 0.95,
                    }
                ],
            }
        )

    @asynccontextmanager
    async def client(*args):
        yield SimpleNamespace(generate_structured=generate)

    original_save = preparation._save_call

    async def interleaved(*args):
        returned.set()
        await editing.wait()
        await original_save(*args)

    monkeypatch.setattr(workflow, "build_project_llm_execution_snapshot", snapshot)
    monkeypatch.setattr(preparation, "open_project_snapshot_llm_client", client)
    monkeypatch.setattr(preparation, "_save_call", interleaved)
    async with sessions() as db:
        await switch_project_engine(db, nid, to_engine="evolution", expected_epoch=1)
        await create_draft_only(db, nid, 1, "第一章", "天亮了。")
        request = workflow.ReadingRequest(
            operation_id=uuid4(), end_chapter=1, request_limit=1
        )
        preview = await workflow.preview_reading(db, nid, request)
        run = (
            await workflow.start_reading(
                db,
                nid,
                workflow.ReadingStart(
                    **request.model_dump(),
                    expected_fingerprint=preview["fingerprint"],
                    authorization_confirmed=True,
                ),
            )
        )["run"]
        await db.commit()

    async def edit():
        await returned.wait()
        async with sessions() as db:
            await require_active_project_exclusive(db, nid)
            editing.set()
            await asyncio.sleep(0.1)
            await create_draft_only(db, nid, 1, "第一章", "天黑了。")
            await db.commit()

    worker = TaskWorker(
        db_manager=SimpleNamespace(engine=sessions.kw["bind"], session_factory=sessions),
        task_commit_guard=project_task_commit_guard,
    )
    completed, _ = await asyncio.wait_for(
        asyncio.gather(worker.run_once(task_id=run["task_id"], novel_id=nid), edit()), 10
    )
    assert completed.status == "failed" and len(calls) == 1
    async with sessions() as db:
        stored = await PostgresAttemptStore(db, nid).load_run(run["run_key"])
        assert stored.status == "source_stale" and stored.budget_remaining == 0
        assert all(
            item["stage"] == "sampled"
            for item in stored.reading_plan_json["preparation"]["calls"].values()
        )
        assert not await get_scenes_by_novel(
            db, nid, status_filter=["draft", "canonical"]
        )


async def test_stop_fences_old_worker_and_old_sql_preserving_history(project):
    sessions, nid = project
    service = ImportWorkflowRunService()
    async with sessions() as db:
        queued = await legacy_start(db, nid)
        task = await db.get(AsyncTask, UUID(queued.task_id))
        task.status, task.attempt, task.lease_id = "running", 1, str(uuid4())
        await db.flush()
        attempt = await service.claim_attempt(
            db,
            task_id=queued.task_id,
            workflow_type="deep_import",
            attempt=1,
            lease_id=task.lease_id,
        )
        run = await service.get_by_task(db, task_id=queued.task_id)
        run.checkpoints = {
            "completed": ["scene-0"],
            "paid_call_receipts": [{"request": "already-paid", "tokens": 37}],
        }
        task.meta = {**task.meta, "accounting_fixture": {"remaining": 2, "used": 1}}
        retained_checkpoints, retained_meta = (
            deepcopy(run.checkpoints),
            deepcopy(task.meta),
        )
        await db.commit()

    async with sessions() as db:
        with pytest.raises(ConflictError, match="排空"):
            await switch_project_engine(db, nid, to_engine="evolution", expected_epoch=1)
        await db.rollback()
        result = await switch_project_engine(
            db, nid, to_engine="evolution", expected_epoch=1, stop_active=True
        )
        assert result["stopped_imports"] == 1 and result["cancelled_tasks"] == 1
        await db.commit()

    async with sessions() as db:
        assert not await project_task_commit_guard(db, task)
        with pytest.raises(ImportWorkflowOwnershipLost):
            await service.require_owner(db, attempt.owner)
        await db.rollback()
        with pytest.raises(ImportWorkflowOwnershipLost):
            await service.resume(db, task_id=queued.task_id)
        await db.rollback()
        await service.reconcile_scoped_task_owners(db, task_id=queued.task_id)
        run = await service.get_by_task(db, task_id=queued.task_id)
        assert (
            run.status == "cancelled" and run.generation == attempt.owner.generation + 1
        )
        assert run.checkpoints == retained_checkpoints
        saved = await db.get(AsyncTask, task.id)
        assert (
            saved.status == "cancelled"
            and saved.lease_id is None
            and saved.meta == retained_meta
        )
        await db.commit()

    # Simulate an old binary: no new Python gate, flushed business mutation,
    # then its old task checkpoint tries to retain running/commit ownership.
    event_id = uuid4()
    for status in ("running", "done"):
        async with sessions() as old:
            old.add(
                MemoryEvent(
                    id=event_id,
                    novel_id=nid,
                    chapter_index=1,
                    sequence=999,
                    dimension="timeline",
                    event_type="timeline_changed",
                    source="deep_import",
                    snapshot_after={"text_state": "不得留下的旧写入"},
                )
            )
            await old.flush()
            with pytest.raises(DBAPIError, match="understanding writer fenced"):
                await old.execute(
                    update(AsyncTask)
                    .where(AsyncTask.id == task.id)
                    .values(status=status, lease_id="old-lease")
                )
            await old.rollback()

    async with sessions() as db:
        assert await db.get(MemoryEvent, event_id) is None
        for sql, params in [
            (
                "UPDATE projects SET understanding_engine='legacy', "
                "understanding_epoch=understanding_epoch+1, "
                "understanding_schema_floor=1 WHERE id=:nid",
                {"nid": nid},
            ),
            (
                "INSERT INTO async_tasks(id, novel_id, task_type, status, meta, "
                "progress, attempt) VALUES (:id,:nid,'deep_import','pending',"
                "json_build_object('novel_id',CAST(:nid_text AS text)),0,0)",
                {"id": str(uuid4()), "nid": nid, "nid_text": nid},
            ),
        ]:
            with pytest.raises(DBAPIError, match="understanding"):
                await db.execute(text(sql), params)
            await db.rollback()
        with pytest.raises(ConflictError, match="旧引擎"):
            await switch_project_engine(db, nid, to_engine="legacy", expected_epoch=2)
        await db.rollback()
        owner = {"engine": "evolution", "epoch": 2, "schema": 2}
        old_protocol = AsyncTask(
            novel_id=nid,
            task_type="evolution_scene_step",
            status="pending",
            meta={
                "novel_id": nid,
                "_understanding_owner": owner,
                "execution_mode": "live",
            },
        )
        db.add(old_protocol)
        with pytest.raises(DBAPIError, match="requires v2 protocol"):
            await db.flush()
        await db.rollback()
        current_task = AsyncTask(
            novel_id=nid,
            task_type="evolution_scene_step_v2",
            status="pending",
            meta={
                "novel_id": nid,
                "_understanding_owner": owner,
                "execution_mode": "live",
            },
        )
        db.add(current_task)
        await db.commit()
        with pytest.raises(DBAPIError, match="protocol is immutable"):
            await db.execute(
                update(AsyncTask)
                .where(AsyncTask.id == current_task.id)
                .values(task_type="evolution_scene_step")
            )
        await db.rollback()
        store = PostgresAttemptStore(db, nid)
        await store.register_run("new-owner", mode="append", budget_total=3)
        await store.reserve_budget("new-owner", 1)
        await db.commit()
        paused = await switch_project_engine(
            db, nid, to_engine="read_only", expected_epoch=2, stop_active=True
        )
        await db.commit()
        assert paused["schema_floor"] == 2
        run = await store.load_run("new-owner")
        assert run.status == "stopped" and run.budget_remaining == 2


async def test_switch_and_old_heartbeat_do_not_deadlock(project):
    sessions, nid = project
    from modules.project.facade import require_active_project_exclusive

    async with sessions() as db:
        queued = await legacy_start(db, nid)
        await db.execute(
            update(AsyncTask)
            .where(AsyncTask.id == UUID(queued.task_id))
            .values(status="running", attempt=1, lease_id="old-heartbeat")
        )
        await db.commit()

    async def heartbeat():
        async with sessions() as db:
            with pytest.raises(DBAPIError, match="could not obtain lock"):
                await db.execute(
                    update(AsyncTask)
                    .where(AsyncTask.id == UUID(queued.task_id))
                    .values(progress=0.5)
                )
            await db.rollback()

    async with sessions() as switch:
        await require_active_project_exclusive(switch, nid)
        await asyncio.wait_for(heartbeat(), 2)
        await switch_project_engine(
            switch, nid, to_engine="evolution", expected_epoch=1, stop_active=True
        )
        await switch.commit()


async def test_pre_migration_legacy_checkpoint_keeps_missing_token(project):
    sessions, nid = project
    async with sessions() as db:
        task = AsyncTask(
            id=uuid4(),
            novel_id=nid,
            task_type="deep_import",
            status="running",
            meta={"novel_id": nid},
            attempt=1,
            lease_id="pre-migration",
            result={},
        )
        db.add(task)
        await db.flush()
        run = ImportWorkflowRun(
            id=task.id,
            task_id=task.id,
            novel_id=nid,
            workflow_type="deep_import",
            start_chapter=1,
            end_chapter=2,
            status="pending",
            generation=1,
            authorization_snapshot={},
            llm_execution_snapshot={},
            prepare_checkpoint={},
            checkpoints={"costs": {"used": 1}},
            progress={},
        )
        db.add(run)
        await db.flush()
        service = ImportWorkflowRunService()
        attempt = await service.claim_attempt(
            db,
            task_id=str(task.id),
            workflow_type="deep_import",
            attempt=1,
            lease_id="pre-migration",
        )
        await service.checkpoint(
            db,
            owner=attempt.owner,
            progress={"phase": "checkpoint"},
            prepare_checkpoint={"source": "retained"},
        )
        assert "_understanding_owner" not in run.prepare_checkpoint
        assert run.checkpoints["costs"]["used"] == 1
        assert await project_task_commit_guard(db, task)
        await db.commit()


async def test_migration_retires_old_queue_without_starving_other_projects():
    """Real old-schema -> new-schema upgrade in a new disposable database."""
    url = make_url(DATABASE_URL)
    database = f"ai_novel_agent_e2e_v4_migration_{uuid4().hex[:12]}"
    admin = create_async_engine(
        url.set(database="postgres"), isolation_level="AUTOCOMMIT"
    )
    probe_url = url.set(database=database)
    probe = create_async_engine(probe_url)
    sessions = async_sessionmaker(probe, expire_on_commit=False)
    env = dict(os.environ, DATABASE_URL=probe_url.render_as_string(hide_password=False))
    backend = Path(__file__).resolve().parents[2]

    async def migrate(revision):
        result = await asyncio.to_thread(
            subprocess.run,
            [sys.executable, "-m", "alembic", "upgrade", revision],
            env=env,
            cwd=backend,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr

    async with admin.connect() as connection:
        await connection.execute(text(f'CREATE DATABASE "{database}"'))
    try:
        await migrate("20260922_cognition_history_guard")
        first, other = uuid4(), uuid4()
        async with sessions() as db:
            for nid in (first, other):
                await db.execute(
                    text(
                        "INSERT INTO projects "
                        "(id,owner_id,title,language,settings,project_kind,"
                        "default_reveal_policy) SELECT :id,id,'迁移夹具',"
                        "'zh','{}','author','author_safe' FROM accounts LIMIT 1"
                    ),
                    {"id": nid},
                )
            await db.execute(
                text(
                    "INSERT INTO evolution_runs "
                    "(id,novel_id,run_key,mode,owner_epoch,active_engine,execution_mode,status,"
                    "committed_scene_index,committed_source_revision,"
                    "budget_total,budget_remaining) VALUES "
                    "(:id,:nid,'old-live','append',1,'evolution','live','active',-1,0,5,4)"
                ),
                {"id": uuid4(), "nid": first},
            )
            old = AsyncTask(
                novel_id=first,
                task_type="evolution_scene_step",
                status="pending",
                meta={
                    "novel_id": str(first),
                    "execution_mode": "shadow",
                    "run_key": "old-live",
                },
                result={"costs": "retained"},
                created_at=datetime(2000, 1, 1, tzinfo=UTC),
            )
            good = AsyncTask(
                novel_id=other,
                task_type="rag_index_chapter",
                status="pending",
                meta={"novel_id": str(other)},
                created_at=datetime(2010, 1, 1, tzinfo=UTC),
            )
            db.add_all([old, good])
            await db.commit()
            old_id, good_id = old.id, good.id
        await migrate("head")
        async with sessions() as db:
            old = await db.get(AsyncTask, old_id)
            assert old.status == "cancelled" and old.result == {"costs": "retained"}
            project = await db.get(Project, first)
            assert (
                project.understanding_engine == "read_only"
                and project.understanding_schema_floor == 2
            )
            run = await db.scalar(
                select(EvolutionRun).where(EvolutionRun.novel_id == first)
            )
            assert run.status == "stopped" and run.budget_remaining == 4
            claimed = await TaskLifecycleService().claim_next(db)
            assert claimed.id == good_id
    finally:
        await probe.dispose()
        async with admin.connect() as connection:
            await connection.execute(text(f'DROP DATABASE "{database}"'))
        await admin.dispose()


async def test_scene_recompute_inherits_original_receipt_on_postgres(
    project, monkeypatch
):
    from modules.evolution import sampler, workflow
    from modules.evolution.commit import CommitConflictError
    from modules.evolution.facade import read_committed_understanding
    from modules.evolution.tasks import handle_evolution_scene_step
    from modules.story.facade import create_scene
    from modules.writing.facade import create_draft_only

    sessions, nid = project
    calls = []
    world_calls = []

    async def snapshot(db, novel_id):
        return {"profile": {"model": "synthetic-no-network"}}

    class Sampler:
        async def execute_world_request(self, **inputs):
            world_calls.append(inputs)
            return {"result": {}}

        async def sample(self, *, scene_text, input_manifest):
            calls.append((scene_text, input_manifest))
            quote = "他没有提起封锁。" if len(calls) == 2 else scene_text
            return {
                "observations": [
                    {
                        "predicate": quote,
                        "quote": quote,
                        "modality": "event_observed",
                    }
                ],
                "scene_events": [],
            }

    @asynccontextmanager
    async def resolve(**kwargs):
        yield Sampler()

    monkeypatch.setattr(workflow, "build_project_llm_execution_snapshot", snapshot)
    monkeypatch.setattr(sampler, "resolve_scene_sampler", resolve)
    async with sessions() as db:
        await switch_project_engine(db, nid, to_engine="evolution", expected_epoch=1)
        for index, content in enumerate(["天亮了。", "也没有提起封锁。"]):
            await create_draft_only(db, nid, index + 1, f"第{index + 1}章", content)
            await create_scene(
                db, nid, {"scene_index": index, "chapter_ids": [str(index + 1)]}
            )
        await db.commit()
        original = workflow.ReadingRequest(
            operation_id=uuid4(), end_chapter=2, request_limit=3
        )
        preview = await workflow.preview_reading(db, nid, original)
        started = await workflow.start_reading(
            db,
            nid,
            workflow.ReadingStart(
                **original.model_dump(),
                expected_fingerprint=preview["fingerprint"],
                authorization_confirmed=True,
            ),
        )
        old = started["run"]["run_key"]
        first_task = await db.get(AsyncTask, UUID(started["run"]["task_id"]))
        first = await handle_evolution_scene_step(db, first_task)
        second_task = await db.get(AsyncTask, UUID(first["next_task_id"]))
        with pytest.raises(CommitConflictError, match="invalid_observation_source"):
            await handle_evolution_scene_step(db, second_task)
        second_task.status = "failed"
        await db.commit()
        repair = workflow.ReadingRequest(
            operation_id=uuid4(),
            mode="scoped_recompute",
            run_key=old,
            from_scene_index=1,
            end_chapter=2,
            request_limit=2,
        )
        preview = await workflow.preview_reading(db, nid, repair)
        assert preview["inherited_scene_count"] == 1
        restarted = await workflow.start_reading(
            db,
            nid,
            workflow.ReadingStart(
                **repair.model_dump(),
                expected_fingerprint=preview["fingerprint"],
                authorization_confirmed=True,
            ),
        )
        new = restarted["run"]["run_key"]
        inherited = await PostgresAttemptStore(db, nid).load_head_receipt(new)
        assert inherited.run_id == old and inherited.attempt_id == first["attempt_id"]
        task = await db.get(AsyncTask, UUID(restarted["run"]["task_id"]))
        await handle_evolution_scene_step(db, task)
        await db.commit()
    async with sessions() as db:
        run = await PostgresAttemptStore(db, nid).load_run(new)
        assert run.committed_scene_index == 1 and run.budget_remaining == 0
        assert len(calls) == 3 and len(world_calls) == 2
        assert calls[-1][1]["previous_scene_attempt_id"] == first["attempt_id"]
        hashes = {
            step["source_binding"]["draft_id"]: step["source_binding"]["content_hash"]
            for step in run.reading_plan_json["steps"]
        }
        refs, omissions = await read_committed_understanding(db, nid, hashes)
        assert [(ref.run_key, ref.scene_index) for ref in refs] == [(old, 0), (new, 1)]
        assert not omissions


async def test_invalid_quote_requires_new_authorized_run_on_worker(project, monkeypatch):
    from types import SimpleNamespace

    from infrastructure.tasks.worker import TaskWorker
    from modules.evolution import sampler, workflow
    from modules.story.facade import create_scene
    from modules.writing.facade import create_draft_only

    sessions, nid = project
    calls = []

    async def snapshot(db, novel_id):
        return {"profile": {"model": "synthetic-no-network"}}

    class Sampler:
        async def sample(self, *, scene_text, input_manifest):
            calls.append(scene_text)
            quote = "他没有提起封锁。" if len(calls) == 1 else scene_text
            return {
                "observations": [
                    {
                        "predicate": quote,
                        "quote": quote,
                        "modality": "event_observed",
                    }
                ],
                "scene_events": [],
            }

    async def factory(db, novel_id, **kwargs):
        return Sampler()

    monkeypatch.setattr(workflow, "build_project_llm_execution_snapshot", snapshot)
    monkeypatch.setitem(sampler._SAMPLER_REGISTRY, "project_llm", factory)
    async with sessions() as db:
        await switch_project_engine(db, nid, to_engine="evolution", expected_epoch=1)
        await create_draft_only(db, nid, 1, "第一章", "也没有提起封锁。")
        await create_scene(db, nid, {"scene_index": 0, "chapter_ids": ["1"]})
        request = workflow.ReadingRequest(
            operation_id=uuid4(), end_chapter=1, request_limit=1
        )
        preview = await workflow.preview_reading(db, nid, request)
        started = await workflow.start_reading(
            db,
            nid,
            workflow.ReadingStart(
                **request.model_dump(),
                expected_fingerprint=preview["fingerprint"],
                authorization_confirmed=True,
            ),
        )
        old, task_id = started["run"]["run_key"], started["run"]["task_id"]
        await db.commit()
    worker = TaskWorker(
        db_manager=SimpleNamespace(engine=sessions.kw["bind"], session_factory=sessions),
        task_commit_guard=project_task_commit_guard,
    )
    failed = await worker.run_once(task_id=task_id, novel_id=nid)
    assert failed.status == "failed" and len(calls) == 1
    async with sessions() as db:
        state = (await workflow.reading_status(db, nid, old))["run"]
        task = await db.get(AsyncTask, UUID(task_id))
        assert state["status"] == "failed" and not state["can_resume"]
        assert task.meta["recovery_required"] is False
        assert task.result["lifecycle"]["recovery_required"] is False
        frozen = await PostgresAttemptStore(db, nid).load_pending_frozen(old, 0)
        assert frozen.payload["stage"] == "sampled"
        repair = workflow.ReadingRequest(
            operation_id=uuid4(),
            mode="scoped_recompute",
            run_key=old,
            from_scene_index=0,
            end_chapter=1,
            request_limit=1,
        )
        preview = await workflow.preview_reading(db, nid, repair)
        started = await workflow.start_reading(
            db,
            nid,
            workflow.ReadingStart(
                **repair.model_dump(),
                expected_fingerprint=preview["fingerprint"],
                authorization_confirmed=True,
            ),
        )
        await db.commit()
    done = await worker.run_once(task_id=started["run"]["task_id"], novel_id=nid)
    assert done.status == "done" and len(calls) == 2


async def test_candidate_adoption_project_upgrade_never_waits_behind_author(project):
    """NOWAIT avoids domain→Project lock cycles and closes check/commit races."""
    from modules.project.facade import require_active_project
    from modules.world.services.common import require_fresh_understanding_source

    sessions, nid = project
    async with sessions() as author, sessions() as adopter:
        await require_active_project(author, nid)
        await require_active_project(adopter, nid)
        with pytest.raises(ConflictError, match="正在更新"):
            await asyncio.wait_for(
                require_fresh_understanding_source(
                    adopter,
                    nid,
                    {
                        "evolution_ref": {
                            "run_key": "not-read-while-author-locks",
                            "attempt_id": "none",
                        }
                    },
                ),
                2,
            )
        await adopter.rollback()
        await author.rollback()
