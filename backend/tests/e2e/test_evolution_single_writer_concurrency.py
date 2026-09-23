"""E2E（真实 PostgreSQL）：演化 run 单写者并发门禁（PR #158 评审 R5）。

两个会话并发注册不同 run_key 的 live run——部分唯一索引保证恰好一个
合法 owner；落败会话得到 single_writer_violation，而非两个都能写入。
排空/停止后的旧任务不能经重复注册重入。
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from modules.evolution.commit import CommitConflictError
from modules.evolution.models import EvolutionRun
from modules.evolution.store import PostgresAttemptStore
from modules.project.models import Project
from tests.e2e.config import DATABASE_URL

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]


async def test_concurrent_review_recovery_claims_one_provider_request():
    from modules.evolution.facade import switch_project_engine
    from modules.evolution.pipeline import SamplePendingReconciliationError
    from modules.evolution.sampler import register_scene_sampler
    from modules.evolution.store import BudgetExhaustedError
    from modules.evolution.tasks import handle_evolution_scene_step
    from modules.evolution.tests.test_state_review import setup

    engine = create_async_engine(DATABASE_URL, pool_size=4, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    nid = uuid.uuid4()
    try:
        async with sessions() as db:
            db.add(
                Project(
                    id=nid,
                    title="复核并发专用验收",
                    genre="奇幻",
                    tone="测试",
                    language="zh",
                    target_length="novel",
                    current_stage="writing",
                )
            )
            await db.flush()
            await switch_project_engine(
                db, str(nid), to_engine="evolution", expected_epoch=1
            )
            await db.commit()
            task, sampler, client, store = await setup(db, str(nid), budget=1)
            with pytest.raises(BudgetExhaustedError):
                await handle_evolution_scene_step(db, task)
            await db.rollback()
            run = await store.load_run(task.meta["run_key"])
            run.budget_total += 1
            run.budget_remaining += 1
            await db.commit()
            started, release = asyncio.Event(), asyncio.Event()
            original = sampler.verify_state_events

            async def paused_review(**inputs):
                started.set()
                await release.wait()
                return await original(**inputs)

            sampler.verify_state_events = paused_review
            register_scene_sampler("state-review-race", lambda db, novel_id: sampler)
            task.meta["sampler_provider"] = "state-review-race"
            first = asyncio.create_task(handle_evolution_scene_step(db, task))
            try:
                await asyncio.wait_for(started.wait(), timeout=10)
                async with sessions() as competitor:
                    with pytest.raises(SamplePendingReconciliationError):
                        await asyncio.wait_for(
                            handle_evolution_scene_step(competitor, task), timeout=10
                        )
                    await competitor.rollback()
            finally:
                release.set()
                await asyncio.wait_for(first, timeout=10)
            assert sampler.calls == len(client.inputs) == 1
            run = await store.load_run(task.meta["run_key"])
            assert run.budget_remaining == 0 and run.committed_scene_index == 0
    finally:
        async with sessions() as cleanup:
            await cleanup.execute(delete(Project).where(Project.id == nid))
            await cleanup.commit()
        await engine.dispose()


async def test_verified_recovery_releases_run_before_commit_advisory(monkeypatch):
    from modules.evolution import pipeline
    from modules.evolution.facade import switch_project_engine
    from modules.evolution.tasks import handle_evolution_scene_step
    from modules.evolution.tests.test_state_review import setup

    engine = create_async_engine(DATABASE_URL, pool_size=4, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    nid = uuid.uuid4()
    worker = None
    try:
        async with sessions() as db:
            db.add(Project(id=nid, title="复核提交锁序验收"))
            await db.flush()
            await switch_project_engine(
                db, str(nid), to_engine="evolution", expected_epoch=1
            )
            await db.commit()
            task, sampler, client, store = await setup(db, str(nid))
            original_save = PostgresAttemptStore.save_receipt

            async def fail_receipt(self, receipt):
                raise RuntimeError("receipt persistence failed")

            monkeypatch.setattr(PostgresAttemptStore, "save_receipt", fail_receipt)
            with pytest.raises(RuntimeError, match="receipt persistence"):
                await handle_evolution_scene_step(db, task)
            await db.rollback()
            monkeypatch.setattr(PostgresAttemptStore, "save_receipt", original_save)
            pending = await store.load_pending_frozen(task.meta["run_key"], 0)
            assert pending.payload["stage"] == "verified"
            await db.commit()
            entering_apply = asyncio.Event()
            original_apply = pipeline.apply_frozen

            async def apply_after_signal(*args, **kwargs):
                entering_apply.set()
                return await original_apply(*args, **kwargs)

            monkeypatch.setattr(pipeline, "apply_frozen", apply_after_signal)
            async with sessions() as holder:
                await holder.execute(
                    text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                    {"key": f"evolution_commit:{nid}:{task.meta['run_key']}"},
                )
                worker = asyncio.create_task(handle_evolution_scene_step(db, task))
                await asyncio.wait_for(entering_apply.wait(), 10)
                # The recovery must release its run claim before waiting for this
                # advisory lock; otherwise these two lock requests form a cycle.
                await asyncio.wait_for(
                    PostgresAttemptStore(holder, nid).load_run(
                        task.meta["run_key"], for_update=True
                    ),
                    5,
                )
                await holder.commit()
            result = await asyncio.wait_for(worker, 10)
            assert result["attempt_id"] == pending.attempt_id
            assert sampler.calls == len(client.inputs) == 1
    finally:
        if worker and not worker.done():
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)
        async with sessions() as cleanup:
            await cleanup.execute(delete(Project).where(Project.id == nid))
            await cleanup.commit()
        await engine.dispose()


async def test_first_sampling_does_not_lock_run_before_draft_version(monkeypatch):
    from modules.evolution.facade import switch_project_engine
    from modules.evolution.tasks import handle_evolution_scene_step
    from modules.evolution.tests.test_state_review import setup
    from modules.writing import facade as writing

    engine = create_async_engine(DATABASE_URL, pool_size=4, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    nid = uuid.uuid4()
    worker = None
    try:
        async with sessions() as db:
            db.add(Project(id=nid, title="采样与改稿锁序验收"))
            await db.flush()
            await switch_project_engine(
                db, str(nid), to_engine="evolution", expected_epoch=1
            )
            await db.commit()
            task, sampler, client, store = await setup(db, str(nid))
            await store.register_run(task.meta["run_key"], mode="append", budget_total=2)
            await db.commit()
            locking_chapter = asyncio.Event()
            original_lock = writing.lock_chapter_versions_for_revalidation

            async def signal_lock(*args, **kwargs):
                locking_chapter.set()
                return await original_lock(*args, **kwargs)

            async with sessions() as writer:
                await original_lock(writer, str(nid), [1])
                monkeypatch.setattr(
                    writing, "lock_chapter_versions_for_revalidation", signal_lock
                )
                worker = asyncio.create_task(handle_evolution_scene_step(db, task))
                await asyncio.wait_for(locking_chapter.wait(), 10)
                await asyncio.wait_for(
                    PostgresAttemptStore(writer, nid).load_run(
                        task.meta["run_key"], for_update=True
                    ),
                    5,
                )
                await writing.create_draft_only(
                    writer, str(nid), 1, content="正文已经修改。"
                )
                await writer.commit()
            with pytest.raises(CommitConflictError, match="source_changed"):
                await asyncio.wait_for(worker, 10)
            await db.rollback()
            assert sampler.calls == 0 and not client.inputs
    finally:
        if worker and not worker.done():
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)
        async with sessions() as cleanup:
            await cleanup.execute(delete(Project).where(Project.id == nid))
            await cleanup.commit()
        await engine.dispose()


async def test_two_sessions_race_exactly_one_live_writer_wins() -> None:
    engine = create_async_engine(DATABASE_URL, pool_size=4, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    novel_id = uuid.uuid4()

    async with sessions() as setup:
        setup.add(
            Project(
                id=novel_id,
                title="演化单写者并发 e2e",
                genre="奇幻",
                tone="测试",
                language="zh",
                target_length="novel",
                current_stage="writing",
            )
        )
        await setup.flush()
        from modules.evolution.facade import switch_project_engine

        await switch_project_engine(
            setup, str(novel_id), to_engine="evolution", expected_epoch=1
        )
        await setup.commit()

    async def _register(run_key: str) -> tuple[bool, str | None]:
        async with sessions() as session:
            store = PostgresAttemptStore(session, novel_id)
            try:
                await store.register_run(
                    run_key, mode="append", budget_total=5, execution_mode="live"
                )
                await session.commit()
                return True, None
            except CommitConflictError as exc:
                await session.rollback()
                return False, exc.code

    try:
        outcomes = await asyncio.gather(
            _register("run-race-a"),
            _register("run-race-b"),
        )
        winners = [ok for ok, _ in outcomes if ok]
        assert len(winners) == 1, f"恰好一个合法 owner，实际 {outcomes}"
        loser_code = next(code for ok, code in outcomes if not ok)
        assert loser_code == "single_writer_violation"

        async with sessions() as verify:
            live_rows = await verify.execute(
                select(EvolutionRun).where(
                    EvolutionRun.novel_id == novel_id,
                    EvolutionRun.execution_mode == "live",
                    EvolutionRun.status == "active",
                )
            )
            rows = live_rows.scalars().all()
            assert len(rows) == 1

            # 排空释放写入位；排空后的 run 不能经重复注册复活。
            drained = await PostgresAttemptStore(verify, novel_id).drain_run(
                rows[0].run_key
            )
            assert drained.status == "drained"
            await verify.commit()

        ok, code = await _register("run-race-c")
        assert ok and code is None  # 排空后新 live run 可注册

        store_check = PostgresAttemptStore
        async with sessions() as revive:
            with pytest.raises(CommitConflictError, match="run_not_active"):
                await store_check(revive, novel_id).register_run(
                    rows[0].run_key, mode="append", budget_total=5
                )
            await revive.rollback()
    finally:
        async with sessions() as cleanup:
            await cleanup.execute(
                delete(EvolutionRun).where(EvolutionRun.novel_id == novel_id)
            )
            await cleanup.execute(delete(Project).where(Project.id == novel_id))
            await cleanup.commit()
        await engine.dispose()


async def test_review_finalize_preserves_later_paid_call_journal(monkeypatch):
    from modules.evolution import pipeline
    from modules.evolution.facade import switch_project_engine
    from modules.evolution.store import BudgetExhaustedError
    from modules.evolution.tasks import handle_evolution_scene_step
    from modules.evolution.tests.test_state_review import setup

    engine = create_async_engine(DATABASE_URL, pool_size=4, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    nid = uuid.uuid4()
    workers = []
    release_review, release_next = asyncio.Event(), asyncio.Event()
    try:
        async with sessions() as db, sessions() as other:
            db.add(Project(id=nid, title="复核收尾不覆盖后续计费记录"))
            await db.flush()
            await switch_project_engine(
                db, str(nid), to_engine="evolution", expected_epoch=1
            )
            await db.commit()
            task, sampler, client, store = await setup(db, str(nid), budget=1)
            with pytest.raises(BudgetExhaustedError):
                await handle_evolution_scene_step(db, task)
            await db.rollback()
            run = await store.load_run(task.meta["run_key"])
            run.budget_total += 2
            run.budget_remaining += 2
            frozen = await store.load_pending_frozen(run.run_key, 0)
            source = pipeline.SceneSourceBinding.model_validate(
                frozen.payload["source_binding"]
            )
            await db.commit()
            sampled, next_started = asyncio.Event(), asyncio.Event()
            original = pipeline._run_scene_call

            async def pause_after_sample(session, *args, **kwargs):
                result = await original(session, *args, **kwargs)
                if session is db and kwargs["journal_key"] == "state_review":
                    sampled.set()
                    await release_review.wait()
                return result

            monkeypatch.setattr(pipeline, "_run_scene_call", pause_after_sample)
            first = asyncio.create_task(
                pipeline._finish_state_review(
                    db, store, frozen, source, sampler.verify_state_events
                )
            )
            workers.append(first)
            await asyncio.wait_for(sampled.wait(), 10)
            other_store = PostgresAttemptStore(other, nid)
            latest = await pipeline._finish_state_review(
                other, other_store, frozen, source, sampler.verify_state_events
            )

            async def next_call():
                next_started.set()
                await release_next.wait()
                return {"result": {"candidate": "retained"}}

            second = asyncio.create_task(
                original(
                    other,
                    other_store,
                    latest,
                    source,
                    journal_key="scene_enrichment",
                    inputs={"method": "fixture.enrich"},
                    call_inputs={},
                    call=next_call,
                )
            )
            workers.append(second)
            await asyncio.wait_for(next_started.wait(), 10)
            release_review.set()
            result = await asyncio.wait_for(first, 10)
            assert result.payload["scene_enrichment"]["stage"] == "sampling"
            persisted = await store.load_frozen(frozen.run_id, frozen.attempt_id)
            assert persisted.payload["scene_enrichment"]["stage"] == "sampling"
            await db.commit()
            release_next.set()
            await asyncio.wait_for(second, 10)
            assert len(client.inputs) == 1
            assert (await store.load_run(frozen.run_id)).budget_remaining == 0
    finally:
        release_review.set()
        release_next.set()
        for worker in workers:
            if not worker.done():
                worker.cancel()
        await asyncio.gather(*workers, return_exceptions=True)
        async with sessions() as cleanup:
            await cleanup.execute(delete(Project).where(Project.id == nid))
            await cleanup.commit()
        await engine.dispose()


async def test_scene_commit_waits_for_author_before_acquiring_run(monkeypatch):
    from modules.evolution.facade import switch_project_engine
    from modules.evolution.tasks import handle_evolution_scene_step
    from modules.evolution.tests.test_state_review import setup
    from modules.project import facade as projects
    from modules.story.outline_state.schemas import SceneUpdate
    from modules.story.outline_state.services import SceneService

    engine = create_async_engine(DATABASE_URL, pool_size=4, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    nid = uuid.uuid4()
    worker = None
    try:
        async with sessions() as db:
            db.add(Project(id=nid, title="作者修改与整理提交锁序"))
            await db.flush()
            await switch_project_engine(
                db, str(nid), to_engine="evolution", expected_epoch=1
            )
            await db.commit()
            task, sampler, client, store = await setup(db, str(nid))
            original_save = PostgresAttemptStore.save_receipt

            async def fail_receipt(self, receipt):
                raise RuntimeError("freeze before domain commit")

            monkeypatch.setattr(PostgresAttemptStore, "save_receipt", fail_receipt)
            with pytest.raises(RuntimeError, match="freeze before"):
                await handle_evolution_scene_step(db, task)
            await db.rollback()
            monkeypatch.setattr(PostgresAttemptStore, "save_receipt", original_save)
            entering_commit = asyncio.Event()
            original_lock = projects.require_active_project_exclusive

            async def commit_lock(session, novel_id):
                if session is db:
                    entering_commit.set()
                await original_lock(session, novel_id)

            monkeypatch.setattr(projects, "require_active_project_exclusive", commit_lock)
            async with sessions() as author:
                await projects.require_active_project(author, str(nid))
                await SceneService().repo.get_for_update(
                    author, uuid.UUID(task.meta["scene_id"])
                )
                worker = asyncio.create_task(handle_evolution_scene_step(db, task))
                await asyncio.wait_for(entering_commit.wait(), 10)
                # This mutation locks Scene before invalidating run; the worker
                # must still be waiting at Project, without holding that run.
                await asyncio.wait_for(
                    SceneService().update(
                        author,
                        task.meta["scene_id"],
                        SceneUpdate(scene_index=1),
                        novel_id=str(nid),
                    ),
                    5,
                )
                await author.commit()
            with pytest.raises(CommitConflictError, match="source_changed"):
                await asyncio.wait_for(worker, 10)
            await db.rollback()
            pending = await store.load_pending_frozen(task.meta["run_key"], 0)
            assert pending.payload["stage"] == "verified"
            assert sampler.calls == len(client.inputs) == 1
    finally:
        if worker and not worker.done():
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)
        async with sessions() as cleanup:
            await cleanup.execute(delete(Project).where(Project.id == nid))
            await cleanup.commit()
        await engine.dispose()
