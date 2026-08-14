from __future__ import annotations

import asyncio
import base64
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import modules.world.map_atlas_tasks  # noqa: F401
from infrastructure.llm.image_client import GeneratedImage
from infrastructure.tasks.enqueuer import enqueue_task
from infrastructure.tasks.facade import (
    cancel_unfinished_tasks_for_novel,
)
from infrastructure.tasks.models import AsyncTask
from infrastructure.tasks.registry import TaskRegistry
from infrastructure.tasks.worker import TaskWorker
from modules.project.facade import require_active_project
from modules.project.models import Project
from modules.project.repositories import ProjectRepository
from modules.project.services import ProjectService
from modules.world.map_atlas_facade import enqueue_map_atlas_project_cleanup
from modules.world.map_atlas_models import MapAtlasNode, MapAtlasPage, MapAtlasRun
from modules.world.map_atlas_storage import validate_png
from modules.world.map_atlas_tasks import handle_map_atlas_storage_cleanup
from modules.world.map_atlas_workflow import _generate_page
from run_worker import (
    _guard_active_task_project_finalize,
    _require_active_task_project,
)
from tests.e2e.config import DATABASE_URL

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]

_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4z8AAAAMBAQDJ/pLvAAAAAElFTkSuQmCC"
)


async def test_atlas_upload_lock_and_global_cleanup_close_permanent_delete_race() -> None:
    """A paused upload completes before deletion; global cleanup removes its object."""
    engine = create_async_engine(DATABASE_URL, pool_size=4, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    project_id = uuid.uuid4()
    task_id = uuid.uuid4()
    run_id = uuid.uuid4()
    node_id = uuid.uuid4()
    page_id = uuid.uuid4()
    objects: set[str] = set()
    upload_started = asyncio.Event()
    release_upload = asyncio.Event()
    finalizer: asyncio.Task[None] | None = None
    deletion: asyncio.Task[None] | None = None

    try:
        async with sessions.begin() as setup_db:
            setup_db.add(
                Project(
                    id=project_id,
                    title="map atlas delete race",
                    language="zh",
                    default_reveal_policy="author_safe",
                    settings={},
                )
            )
            await setup_db.flush()
            setup_db.add(
                AsyncTask(
                    id=task_id,
                    task_type="map_atlas_generate",
                    status="running",
                    attempt=1,
                    lease_id=str(uuid.uuid4()),
                    recovery_policy="manual_resume",
                    meta={"novel_id": str(project_id), "run_id": str(run_id)},
                )
            )
            await setup_db.flush()
            setup_db.add(
                MapAtlasRun(
                    id=run_id,
                    novel_id=project_id,
                    task_id=task_id,
                    run_kind="initial",
                    status="generating",
                )
            )
            await setup_db.flush()
            setup_db.add(
                MapAtlasNode(
                    id=node_id,
                    novel_id=project_id,
                    created_by_run_id=run_id,
                    semantic_key="world",
                    title="世界",
                    level="world",
                    status="provisional",
                )
            )
            await setup_db.flush()
            setup_db.add(
                MapAtlasPage(
                    id=page_id,
                    novel_id=project_id,
                    run_id=run_id,
                    node_id=node_id,
                    title="世界",
                    visual_brief="world",
                    prompt="no text",
                    generation_status="prepared",
                )
            )

        class MemoryStorage:
            async def put_png(self, key, payload):
                upload_started.set()
                await release_upload.wait()
                objects.add(key)
                return validate_png(payload)

            async def delete_object(self, key):
                objects.discard(key)

            async def delete_prefix(self, prefix):
                matching = {key for key in objects if key.startswith(prefix)}
                objects.difference_update(matching)
                return len(matching)

            async def get_png(self, key):
                assert key in objects
                return _PNG

            async def get_png_if_exists(self, key):
                return _PNG if key in objects else None

        image_client = SimpleNamespace(
            generate=AsyncMock(return_value=GeneratedImage(_PNG, "request-e2e")),
            edit=AsyncMock(return_value=GeneratedImage(_PNG, "request-e2e")),
        )

        @asynccontextmanager
        async def image_client_context(*_args, **_kwargs):
            yield image_client

        async def finalize_upload() -> None:
            async with sessions() as final_db:
                task = await final_db.get(AsyncTask, task_id)
                assert task is not None
                run = await final_db.get(MapAtlasRun, run_id)
                page = await final_db.get(MapAtlasPage, page_id)
                assert run is not None and page is not None
                with (
                    patch(
                        "modules.world.map_atlas_workflow.MapAtlasStorage",
                        return_value=MemoryStorage(),
                        autospec=True,
                    ),
                    patch(
                        "modules.world.map_atlas_workflow.open_project_image_client",
                        autospec=True,
                    ) as open_client,
                ):
                    open_client.side_effect = image_client_context
                    assert await _generate_page(final_db, task, run, page)
                page = await final_db.get(MapAtlasPage, page_id)
                assert page is not None and page.generation_status == "review_ready"

        async def permanently_delete() -> None:
            service = ProjectService(
                map_atlas_cleanup_enqueuer=enqueue_map_atlas_project_cleanup
            )
            async with sessions.begin() as soft_delete_db:
                await service.delete_project(soft_delete_db, str(project_id))
            async with sessions.begin() as permanent_delete_db:
                await service.permanent_delete_project(
                    permanent_delete_db,
                    str(project_id),
                    confirmed=True,
                )

        finalizer = asyncio.create_task(finalize_upload())
        try:
            await asyncio.wait_for(upload_started.wait(), timeout=2.0)
        except TimeoutError:
            if finalizer.done():
                finalizer.result()
            raise
        deletion = asyncio.create_task(permanently_delete())
        done, _pending = await asyncio.wait({deletion}, timeout=0.1)
        assert not done, "project deletion must wait for the upload share lock"

        release_upload.set()
        await asyncio.wait_for(finalizer, timeout=2.0)
        await asyncio.wait_for(deletion, timeout=2.0)

        async with sessions.begin() as cleanup_db:
            cleanup_task = (
                await cleanup_db.execute(
                    select(AsyncTask).where(
                        AsyncTask.task_type == "map_atlas_storage_cleanup",
                        AsyncTask.novel_id.is_(None),
                        AsyncTask.meta["object_prefix"].as_string()
                        == f"map-atlas/{project_id}/",
                    )
                )
            ).scalar_one()
            with patch(
                "modules.world.map_atlas_tasks.MapAtlasStorage",
                return_value=MemoryStorage(),
                autospec=True,
            ):
                result = await handle_map_atlas_storage_cleanup(
                    cleanup_db,
                    cleanup_task,
                )
            assert result["deleted_objects"] == 1
            await cleanup_db.delete(cleanup_task)

        async with sessions() as verify_db:
            assert await verify_db.get(Project, project_id) is None
            assert await verify_db.scalar(
                select(func.count(MapAtlasPage.id)).where(
                    MapAtlasPage.novel_id == project_id
                )
            ) == 0
            assert objects == set()
    finally:
        release_upload.set()
        for pending_task in (finalizer, deletion):
            if pending_task is not None and not pending_task.done():
                pending_task.cancel()
        await asyncio.gather(
            *(task for task in (finalizer, deletion) if task is not None),
            return_exceptions=True,
        )
        async with sessions.begin() as cleanup_db:
            await cleanup_db.execute(
                delete(AsyncTask).where(
                    (AsyncTask.novel_id == project_id)
                    | AsyncTask.task_type.in_(
                        {"map_atlas_storage_cleanup", "world_object_image_cleanup"}
                    )
                )
            )
            await cleanup_db.execute(delete(Project).where(Project.id == project_id))
        await engine.dispose()


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
                novel_id=str(project_id),
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
                delete(AsyncTask).where(AsyncTask.novel_id == project_id)
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
            setup_db.add(
                Project(
                    id=project_id,
                    title="project delete finalize race",
                    language="zh",
                    default_reveal_policy="author_safe",
                    settings={},
                )
            )
            await setup_db.flush()
            setup_db.add(
                AsyncTask(
                    id=task_id,
                    task_type=task_type,
                    status="pending",
                    meta={"novel_id": str(project_id)},
                )
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
        returned_task = await asyncio.wait_for(worker_task, timeout=2.0)
        assert returned_task is not None
        assert returned_task.status == "cancelled"
        assert returned_task.transition_reason == "project_soft_deleted"

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
