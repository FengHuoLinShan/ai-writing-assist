"""World adoption and appended structure must retain their real dependencies."""

from types import SimpleNamespace
from uuid import UUID

import pytest
from sqlalchemy import select

from core.errors import ConflictError
from infrastructure.tasks.models import AsyncTask
from modules.evolution.models import EvolutionFrozenAttempt
from modules.evolution.reading import require_current_world_candidate
from modules.evolution.sampler import register_scene_sampler
from modules.evolution.store import PostgresAttemptStore
from modules.evolution.tasks import handle_evolution_scene_step
from modules.evolution.tests.test_workflow import request_start, seed
from modules.evolution.workflow import start_reading
from modules.story.facade import get_scenes_by_novel
from modules.writing.facade import create_draft_only, get_latest_draft_for_chapter


@pytest.mark.parametrize("status", ["drained", "stopped"])
async def test_world_adoption_rechecks_ancestor_sources(
    db_session, evolution_project_id, status
):
    db, nid = db_session, evolution_project_id
    for chapter, text in enumerate(["钟声响了。", "林舟继续等候。"], 1):
        await seed(db, nid, chapter, text)
    scenes = await get_scenes_by_novel(db, nid)

    class Sampler:
        async def sample(self, *, scene_text, input_manifest):
            return {"observations": [{"predicate": scene_text, "quote": scene_text}]}

    provider = "prefix-adoption-" + nid
    register_scene_sampler(provider, lambda db, novel_id: Sampler())
    for index, scene in enumerate(scenes):
        draft = await get_latest_draft_for_chapter(db, nid, index + 1)
        await handle_evolution_scene_step(
            db,
            SimpleNamespace(
                meta={
                    "novel_id": nid,
                    "run_key": "original",
                    "scene_index": index,
                    "scene_id": scene["id"],
                    "chapter_index": index + 1,
                    "scene_text": draft.content,
                    "sampler_provider": provider,
                    "budget_total": 4,
                }
            ),
        )
        await db.commit()
    store = PostgresAttemptStore(db, nid)
    head = await store.load_head_receipt("original")
    row = await db.scalar(
        select(EvolutionFrozenAttempt).where(
            EvolutionFrozenAttempt.novel_id == UUID(nid),
            EvolutionFrozenAttempt.attempt_key == head.attempt_id,
        )
    )
    row.payload_json = {**row.payload_json, "world_result": {"fixture_candidate": True}}
    run = await store.load_run("original")
    run.status = status
    await db.commit()
    reference = {"run_key": "original", "attempt_id": head.attempt_id}
    await require_current_world_candidate(db, nid, reference)
    await create_draft_only(db, nid, 1, content="钟声没有响。")
    await db.commit()
    assert (await store.load_run("original")).status == status
    with pytest.raises(ConflictError, match="前序"):
        await require_current_world_candidate(db, nid, reference)


async def test_append_reopens_structure_without_losing_old_batches(
    db_session, evolution_project_id, account_llm_connection
):
    db, nid = db_session, evolution_project_id
    await seed(db, nid, 1, "第一场。")
    original = await start_reading(db, nid, await request_start(db, nid, end_chapter=1))
    key = original["run"]["run_key"]
    store = PostgresAttemptStore(db, nid)
    run = await store.load_run(key)
    run.committed_scene_index = 0
    old_batches = [{"batch_key": "retained"}]
    run.reading_plan_json = {
        **run.reading_plan_json,
        "structure": {
            "version": 1,
            "complete": True,
            "through_scene_index": 0,
            "batches": old_batches,
            "current": None,
        },
    }
    task = await db.get(AsyncTask, UUID(original["run"]["task_id"]))
    task.status = "done"
    await seed(db, nid, 2, "第二场。")
    await db.commit()
    await start_reading(
        db, nid, await request_start(db, nid, mode="append", run_key=key, end_chapter=2)
    )
    run = await store.load_run(key)
    stage = run.reading_plan_json["structure"]
    assert not stage["complete"]
    assert stage["through_scene_index"] == 0 and stage["batches"] == old_batches
    assert len(run.reading_plan_json["steps"]) == 2
