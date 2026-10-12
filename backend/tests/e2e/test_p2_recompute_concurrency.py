"""真实 PG：重算互斥、不可变回执、正文写入与最终来源重验共用锁。"""

from __future__ import annotations

import asyncio
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.errors import ConflictError
from infrastructure.tasks.models import AsyncTask
from modules.project.models import Project
from modules.writing.models import WritingRecomputeOperation
from modules.writing.recompute import WritingRecomputeService
from modules.writing.repositories import WritingDraftRepository
from modules.writing.schemas import (
    WritingDraftUpdate,
    WritingRecomputeAdoptRequest,
    WritingRecomputeRequest,
    WritingRecomputeTarget,
)
from modules.writing.tests.test_p2c_recompute import _scene, _working_draft
from tests.e2e.config import DATABASE_URL

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]


@pytest_asyncio.fixture
async def committed_recompute_project():
    engine = create_async_engine(DATABASE_URL, pool_size=3, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    nid = uuid.uuid4()
    try:
        async with sessions() as db:
            db.add(Project(id=nid, title="重算并发合成验收"))
            await db.flush()
            drafts = [
                await _working_draft(db, str(nid), chapter, 1, f"第{chapter}章正文。")
                for chapter in (1, 2)
            ]
            for index, chapter in enumerate((1, 2)):
                await _scene(db, str(nid), scene_index=index, chapter_index=chapter)
            await db.commit()
        yield sessions, str(nid), [item.id for item in drafts]
    finally:
        async with sessions() as cleanup:
            await cleanup.execute(delete(Project).where(Project.id == nid))
            await cleanup.commit()
        await engine.dispose()


@pytest.mark.parametrize("other_target", [False, True])
async def test_same_operation_concurrent_requests(
    committed_recompute_project, other_target
):
    sessions, nid, _ = committed_recompute_project
    service = WritingRecomputeService()
    operation = f"op-{uuid.uuid4()}"
    requests = []
    async with sessions() as db:
        for chapter in (1, 2 if other_target else 1):
            request = WritingRecomputeRequest(
                novel_id=nid,
                operation_id=operation,
                scope="reload_evidence",
                targets=[WritingRecomputeTarget(chapter_index=chapter)],
            )
            preview = await service.preview(db, request)
            requests.append(
                WritingRecomputeAdoptRequest(
                    **request.model_dump(),
                    confirmed=True,
                    expected_source_digest=preview.source_digest,
                )
            )

    async def execute(request):
        async with sessions() as db:
            try:
                outcome = await service.adopt(db, request)
                await db.commit()
                return outcome
            except ConflictError as error:
                await db.rollback()
                return error

    results = await asyncio.wait_for(asyncio.gather(*(execute(r) for r in requests)), 10)
    successes = [r for r in results if not isinstance(r, ConflictError)]
    assert sum(r.domain_write_performed for r in successes) == 1
    if other_target:
        assert len(successes) == 1
        assert (
            next(r for r in results if isinstance(r, ConflictError)).code
            == "recompute_operation_conflict"
        )
    else:
        assert len(successes) == 2 and sum(r.replayed for r in successes) == 1
        assert successes[0].results == successes[1].results
    async with sessions() as db:
        assert (
            await db.scalar(
                select(func.count())
                .select_from(WritingRecomputeOperation)
                .where(WritingRecomputeOperation.novel_id == uuid.UUID(nid))
            )
            == 1
        )
        assert (
            await db.scalar(
                select(func.count())
                .select_from(AsyncTask)
                .where(AsyncTask.novel_id == uuid.UUID(nid))
            )
            == 1
        )


async def test_waiting_recompute_rechecks_same_draft_update(
    committed_recompute_project, monkeypatch
):
    sessions, nid, drafts = committed_recompute_project
    service = WritingRecomputeService()
    repo = WritingDraftRepository()
    reached = asyncio.Event()
    original = service._draft_repo.lock_version_chapters_for_revalidation

    async def observed_lock(*args):
        reached.set()
        return await original(*args)

    request = WritingRecomputeRequest(
        novel_id=nid,
        operation_id=f"op-{uuid.uuid4()}",
        scope="reload_evidence",
        targets=[WritingRecomputeTarget(chapter_index=1)],
    )
    worker = None
    async with sessions() as db:
        preview = await service.preview(db, request)
        adopt = WritingRecomputeAdoptRequest(
            **request.model_dump(),
            confirmed=True,
            expected_source_digest=preview.source_digest,
        )
        async with sessions() as writer:
            await repo.lock_version_chapters_for_revalidation(writer, uuid.UUID(nid), [1])
            monkeypatch.setattr(
                service._draft_repo,
                "lock_version_chapters_for_revalidation",
                observed_lock,
            )
            worker = asyncio.create_task(service.adopt(db, adopt))
            try:
                await asyncio.wait_for(reached.wait(), 5)
                await repo.update(
                    writer, drafts[0], WritingDraftUpdate(content="同一草稿已经改写。")
                )
                await writer.commit()
                with pytest.raises(ConflictError) as exc:
                    await asyncio.wait_for(worker, 5)
                assert exc.value.code == "recompute_source_drift"
            finally:
                if worker and not worker.done():
                    worker.cancel()
                    await asyncio.gather(worker, return_exceptions=True)
                await db.rollback()


async def test_busy_scene_writer_rejects_adoption_without_waiting(
    committed_recompute_project,
):
    from modules.story.outline_state.repositories import SceneRepository
    from modules.story.outline_state.schemas import SceneUpdate

    sessions, nid, _ = committed_recompute_project
    service = WritingRecomputeService()
    request = WritingRecomputeRequest(
        novel_id=nid,
        operation_id=f"op-{uuid.uuid4()}",
        scope="rebuild_derived_state",
        targets=[WritingRecomputeTarget(scene_index=0)],
    )
    async with sessions() as db:
        preview = await service.preview(db, request)
        scene_id = preview.actions[0].scene_id
        async with sessions() as writer:
            await SceneRepository().update(
                writer, uuid.UUID(scene_id), SceneUpdate(title="正在编辑")
            )
            with pytest.raises(ConflictError) as exc:
                await asyncio.wait_for(
                    service.adopt(
                        db,
                        WritingRecomputeAdoptRequest(
                            **request.model_dump(),
                            confirmed=True,
                            expected_source_digest=preview.source_digest,
                        ),
                    ),
                    3,
                )
            assert exc.value.code == "recompute_source_drift"
            await db.rollback()
            await writer.rollback()


async def test_roster_reloaded_after_waiting_for_chapter_lock(
    committed_recompute_project, monkeypatch
):
    from modules.story.outline_state.repositories import SceneRepository

    sessions, nid, _ = committed_recompute_project
    service = WritingRecomputeService()
    reached = asyncio.Event()
    original = service._draft_repo.lock_version_chapters_for_revalidation

    async def observed_lock(*args):
        reached.set()
        return await original(*args)

    request = WritingRecomputeRequest(
        novel_id=nid,
        operation_id=f"op-{uuid.uuid4()}",
        scope="rebuild_derived_state",
        targets=[WritingRecomputeTarget(scene_index=0)],
    )
    async with sessions() as db:
        preview = await service.preview(db, request)
        async with sessions() as writer:
            scenes = await service._scene_roster(writer, nid)
            await WritingDraftRepository().lock_version_chapters_for_revalidation(
                writer, uuid.UUID(nid), [1]
            )
            monkeypatch.setattr(
                service._draft_repo,
                "lock_version_chapters_for_revalidation",
                observed_lock,
            )
            worker = asyncio.create_task(
                service.adopt(
                    db,
                    WritingRecomputeAdoptRequest(
                        **request.model_dump(),
                        confirmed=True,
                        expected_source_digest=preview.source_digest,
                    ),
                )
            )
            try:
                await asyncio.wait_for(reached.wait(), 3)
                await SceneRepository().reorder(
                    writer,
                    uuid.UUID(nid),
                    [uuid.UUID(scene["id"]) for scene in reversed(scenes)],
                )
                await writer.commit()
                with pytest.raises(ConflictError) as exc:
                    await asyncio.wait_for(worker, 5)
                assert exc.value.code == "recompute_source_drift"
            finally:
                if not worker.done():
                    worker.cancel()
                    await asyncio.gather(worker, return_exceptions=True)
                await db.rollback()
