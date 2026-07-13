from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from infrastructure.tasks.enqueuer import enqueue_task
from infrastructure.tasks.facade import cancel_unfinished_tasks_for_novel
from infrastructure.tasks.models import AsyncTask
from infrastructure.tasks.registry import TaskRegistry
from infrastructure.tasks.worker import TaskWorker
from modules.project.facade import require_active_project
from modules.project.models import Project
from modules.project.repositories import ProjectRepository
from modules.project.services import ProjectService
from run_worker import (
    _guard_active_task_project_finalize,
    _require_active_task_project,
)
from tests.e2e.conftest import DATABASE_URL

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]


async def test_guarded_enqueue_is_cancelled_by_waiting_soft_delete() -> None:
    """FOR SHARE closes guard -> delete -> enqueue TOCTOU on PostgreSQL."""
    engine = create_async_engine(DATABASE_URL, pool_size=3, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    project_id = uuid.uuid4()
    task_id: str | None = None
    delete_task: asyncio.Task[None] | None = None

    try:
        async with sessions.begin() as setup_db:
            setup_db.add(
                Project(
                    id=project_id,
                    title="project gate concurrency",
                    language="zh",
                    default_reveal_policy="author_safe",
                    settings={},
                )
            )

        delete_started = asyncio.Event()

        async def soft_delete_project() -> None:
            async with sessions.begin() as delete_db:
                delete_started.set()
                await ProjectService().delete_project(delete_db, str(project_id))

        async with sessions() as guarded_db:
            await guarded_db.begin()
            await require_active_project(guarded_db, str(project_id))

            delete_task = asyncio.create_task(soft_delete_project())
            await delete_started.wait()
            done, _pending = await asyncio.wait({delete_task}, timeout=0.1)
            assert not done, "soft delete must wait for the guarded transaction"

            task_id = enqueue_task(
                guarded_db,
                "rag_reindex_novel",
                meta={"novel_id": str(project_id)},
            )
            await guarded_db.flush()
            await guarded_db.commit()

        await asyncio.wait_for(delete_task, timeout=2.0)

        async with sessions() as verify_db:
            deleted_project = await ProjectRepository().get_deleted(
                verify_db,
                project_id,
            )
            task = await verify_db.get(AsyncTask, uuid.UUID(task_id))
            assert deleted_project is not None
            assert task is not None
            assert task.status == "cancelled"
            assert task.transition_reason == "project_soft_deleted"
            assert task.lease_id is None

            restored = await ProjectRepository().restore(verify_db, project_id)
            assert restored is True
            await verify_db.commit()

        async with sessions() as restored_db:
            task = await restored_db.get(AsyncTask, uuid.UUID(task_id))
            assert task is not None
            assert task.status == "cancelled"
    finally:
        if delete_task is not None and not delete_task.done():
            delete_task.cancel()
            await asyncio.gather(delete_task, return_exceptions=True)
        async with sessions.begin() as cleanup_db:
            await cleanup_db.execute(
                delete(AsyncTask).where(
                    AsyncTask.meta["novel_id"].as_string() == str(project_id)
                )
            )
            await cleanup_db.execute(delete(Project).where(Project.id == project_id))
        await engine.dispose()


async def test_delete_rejects_later_handler_commit_and_preserves_checkpoint() -> None:
    """Only commits linearized before project deletion remain durable."""
    engine = create_async_engine(DATABASE_URL, pool_size=5, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    project_id = uuid.uuid4()
    task_id = uuid.uuid4()
    checkpoint_side_effect_id = uuid.uuid4()
    rejected_side_effect_id = uuid.uuid4()
    task_type = f"project-delete-race-{uuid.uuid4()}"
    handler_committed = asyncio.Event()
    release_handler = asyncio.Event()
    project_marked_deleted = asyncio.Event()
    allow_task_cancel = asyncio.Event()
    finalize_started = asyncio.Event()
    registry = TaskRegistry()

    class E2EManager:
        def __init__(self) -> None:
            self.engine = engine
            self.session_factory = sessions

    async def committing_handler(*, db, task):
        db.add(
            AsyncTask(
                id=checkpoint_side_effect_id,
                task_type="checkpoint-handler-write",
                status="pending",
                meta={"source_task_id": str(task.id)},
            )
        )
        task.result = {"checkpoint": "before_project_delete"}
        task.update_progress(0.5)
        await db.commit()
        handler_committed.set()
        await release_handler.wait()
        db.add(
            AsyncTask(
                id=rejected_side_effect_id,
                task_type="post-delete-handler-write",
                status="pending",
                meta={"source_task_id": str(task.id)},
            )
        )
        await db.commit()
        return {"handler": "done"}

    async def paused_task_canceller(db, *, novel_id, transition_reason):
        project_marked_deleted.set()
        await allow_task_cancel.wait()
        return await cancel_unfinished_tasks_for_novel(
            db,
            novel_id=novel_id,
            transition_reason=transition_reason,
        )

    async def signalling_finalize_guard(db, task) -> bool:
        finalize_started.set()
        return await _guard_active_task_project_finalize(db, task)

    registry.register(task_type, committing_handler)
    worker = TaskWorker(
        db_manager=E2EManager(),
        heartbeat_interval=60.0,
        task_preflight=_require_active_task_project,
        task_commit_guard=signalling_finalize_guard,
    )
    worker_task: asyncio.Task[AsyncTask | None] | None = None
    delete_task: asyncio.Task[None] | None = None

    try:
        async with sessions.begin() as setup_db:
            setup_db.add_all(
                [
                    Project(
                        id=project_id,
                        title="project delete finalize race",
                        language="zh",
                        default_reveal_policy="author_safe",
                        settings={},
                    ),
                    AsyncTask(
                        id=task_id,
                        task_type=task_type,
                        status="pending",
                        meta={"novel_id": str(project_id)},
                    ),
                ]
            )

        worker_task = asyncio.create_task(worker.run_once())
        await asyncio.wait_for(handler_committed.wait(), timeout=2.0)
        finalize_started.clear()

        async def delete_project() -> None:
            service = ProjectService(task_canceller=paused_task_canceller)
            async with sessions.begin() as delete_db:
                await service.delete_project(delete_db, str(project_id))

        delete_task = asyncio.create_task(delete_project())
        await asyncio.wait_for(project_marked_deleted.wait(), timeout=2.0)

        release_handler.set()
        await asyncio.wait_for(finalize_started.wait(), timeout=2.0)
        done, _pending = await asyncio.wait({worker_task}, timeout=0.1)
        assert not done, "finalize must wait behind the project's delete lock"

        allow_task_cancel.set()
        await asyncio.wait_for(delete_task, timeout=2.0)
        await asyncio.wait_for(worker_task, timeout=2.0)

        async with sessions() as verify_db:
            original_task = await verify_db.get(AsyncTask, task_id)
            checkpoint_write = await verify_db.get(
                AsyncTask,
                checkpoint_side_effect_id,
            )
            rejected_write = await verify_db.get(
                AsyncTask,
                rejected_side_effect_id,
            )
            assert original_task is not None
            assert original_task.status == "cancelled"
            assert original_task.transition_reason == "project_soft_deleted"
            assert original_task.progress == 0.5
            assert original_task.result == {"checkpoint": "before_project_delete"}
            assert checkpoint_write is not None
            assert rejected_write is None
    finally:
        allow_task_cancel.set()
        release_handler.set()
        for pending_task in (worker_task, delete_task):
            if pending_task is not None and not pending_task.done():
                pending_task.cancel()
        await asyncio.gather(
            *(task for task in (worker_task, delete_task) if task is not None),
            return_exceptions=True,
        )
        registry.unregister(task_type)
        async with sessions.begin() as cleanup_db:
            await cleanup_db.execute(
                delete(AsyncTask).where(
                    AsyncTask.id.in_(
                        (
                            task_id,
                            checkpoint_side_effect_id,
                            rejected_side_effect_id,
                        )
                    )
                )
            )
            await cleanup_db.execute(delete(Project).where(Project.id == project_id))
        await engine.dispose()
