"""Two PostgreSQL sessions exercise source fences, commit order and Scene reorder."""

import asyncio
import uuid
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from modules.evolution import tasks
from modules.evolution.commit import CommitConflictError
from modules.evolution.models import EvolutionReceiptRecord
from modules.evolution.sampler import register_scene_sampler
from modules.evolution.store import PostgresAttemptStore
from modules.project.models import Project
from modules.story import facade as story_facade
from modules.story.continuity.models import MemoryEvent
from modules.story.outline_state.models import Scene
from modules.story.outline_state.services import SceneService
from modules.writing.facade import create_draft_only
from tests.e2e.config import DATABASE_URL
from tests.support.evolution_review import frozen_state_review

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]


class Sampler:
    verify_state_events = staticmethod(frozen_state_review)
    calls = 0
    pause = None
    resume = None

    async def sample(self, *, scene_text, input_manifest):
        self.calls += 1
        if self.pause:
            self.pause.set()
            await asyncio.wait_for(self.resume.wait(), 10)
        return {
            "observations": [
                {
                    "predicate": scene_text,
                    "quote": scene_text,
                    "modality": "event_observed",
                    "mentions": [],
                }
            ],
            "scene_events": [
                {
                    "dimension": "timeline",
                    "event_type": "timeline_changed",
                    "snapshot_after": {
                        "text_state": scene_text,
                        "meta": {"author_confirmed": True},
                    },
                    "source_observation_indices": [0],
                }
            ],
        }


@pytest_asyncio.fixture
async def scenario():
    engine = create_async_engine(DATABASE_URL, pool_size=4, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    nid = uuid.uuid4()
    sampler = Sampler()
    provider = f"invalidation-{nid}"
    register_scene_sampler(provider, lambda db, novel_id: sampler)
    try:
        async with sessions() as db:
            db.add(Project(id=nid, title="专用失效并发测试"))
            await db.flush()
            from modules.evolution.facade import switch_project_engine

            await switch_project_engine(
                db, str(nid), to_engine="evolution", expected_epoch=1
            )
            scenes = [
                Scene(
                    novel_id=nid,
                    scene_index=i,
                    chapter_ids=[i + 1],
                    scene_chunks=[],
                    title=f"场景{i}",
                    status="draft",
                )
                for i in range(2)
            ]
            db.add_all(scenes)
            await db.flush()
            ids = [str(scene.id) for scene in scenes]
            for i in range(2):
                await create_draft_only(
                    db, str(nid), i + 1, content=f"第{i + 1}日天亮了。"
                )
            await db.commit()

            def request(index):
                return SimpleNamespace(
                    meta={
                        "novel_id": str(nid),
                        "run_key": "chain",
                        "scene_index": index,
                        "scene_id": ids[index],
                        "chapter_index": index + 1,
                        "scene_text": f"第{index + 1}日天亮了。",
                        "budget_total": 4,
                        "state_review_version": 1,
                        "sampler_provider": provider,
                    }
                )

            await tasks.handle_evolution_scene_step(db, request(0))
        yield sessions, str(nid), ids, sampler, request
    finally:
        async with sessions() as cleanup:
            await cleanup.execute(delete(Project).where(Project.id == nid))
            await cleanup.commit()
        await engine.dispose()


async def test_edit_during_sampling_blocks_receipt_without_resampling(scenario):
    sessions, nid, _, sampler, request = scenario
    sampler.pause, sampler.resume = asyncio.Event(), asyncio.Event()

    async def consume():
        async with sessions() as db:
            with pytest.raises(CommitConflictError, match="source_changed"):
                await tasks.handle_evolution_scene_step(db, request(1))
            await db.rollback()

    worker = asyncio.create_task(consume())
    try:
        await asyncio.wait_for(sampler.pause.wait(), 10)
        async with sessions() as writer:
            await create_draft_only(writer, nid, 1, content="第一日入夜了。")
            await writer.commit()
        sampler.resume.set()
        await asyncio.wait_for(worker, 10)
        async with sessions() as verify:
            run = await PostgresAttemptStore(verify, nid).load_run("chain")
            assert run.status == "source_stale" and run.owner_epoch == 2
            assert run.committed_scene_index == 0
            assert (
                await verify.scalar(
                    select(func.count())
                    .select_from(EvolutionReceiptRecord)
                    .where(EvolutionReceiptRecord.novel_id == uuid.UUID(nid))
                )
                == 1
            )
            with pytest.raises(CommitConflictError, match="source_changed"):
                await tasks.handle_evolution_scene_step(verify, request(1))
        assert sampler.calls == 2
    finally:
        sampler.resume.set()
        await asyncio.gather(worker, return_exceptions=True)


@pytest.mark.parametrize("mutation", ["rewrite", "reorder"])
async def test_commit_serializes_author_mutation_before_event_locks(
    scenario, monkeypatch, mutation
):
    sessions, nid, ids, sampler, request = scenario
    applying, fencing = asyncio.Event(), asyncio.Event()
    original_apply = story_facade.replace_scene_memory_events

    async def delayed_apply(*args, **kwargs):
        applying.set()  # apply_frozen already holds its run row lock
        await asyncio.wait_for(fencing.wait(), 10)
        return await original_apply(*args, **kwargs)

    monkeypatch.setattr(story_facade, "replace_scene_memory_events", delayed_apply)
    # Replacing this previous event must contend with the reorder's same event row.
    async with sessions() as seed:
        seed.add(
            MemoryEvent(
                novel_id=uuid.UUID(nid),
                chapter_index=2,
                scene_id=uuid.UUID(ids[1]),
                scene_index=1,
                scene_sequence=1,
                sequence=2001,
                dimension="timeline",
                event_type="timeline_changed",
                source="evolution",
                snapshot_after={"text_state": "旧的派生解释"},
            )
        )
        await seed.commit()

    async def consume():
        async with sessions() as db:
            await tasks.handle_evolution_scene_step(db, request(1))

    async def mutate():
        await asyncio.wait_for(applying.wait(), 10)
        async with sessions() as writer:
            from modules.project.facade import require_active_project

            # Match the browser API: author mutations enter through Project
            # shared, while the short Evolution finalizer holds it exclusive.
            fencing.set()
            await require_active_project(writer, nid)
            if mutation == "rewrite":
                await create_draft_only(writer, nid, 1, content="第一日入夜了。")
            else:
                await SceneService().reorder(writer, nid, list(reversed(ids)))
            await writer.commit()

    await asyncio.wait_for(asyncio.gather(consume(), mutate()), 15)
    async with sessions() as verify:
        run = await PostgresAttemptStore(verify, nid).load_run("chain")
        assert run.status == "source_stale" and run.committed_scene_index == 1
        events = list(
            (
                await verify.scalars(
                    select(MemoryEvent).where(MemoryEvent.novel_id == uuid.UUID(nid))
                )
            ).all()
        )
        assert len(events) == 2 and all(event.source_stale for event in events)
        assert not any(
            event.snapshot_after.get("meta", {}).get("author_confirmed")
            for event in events
        )
        assert (
            await verify.scalar(
                select(func.count())
                .select_from(EvolutionReceiptRecord)
                .where(EvolutionReceiptRecord.novel_id == uuid.UUID(nid))
            )
            == 2
        )
    assert sampler.calls == 2
