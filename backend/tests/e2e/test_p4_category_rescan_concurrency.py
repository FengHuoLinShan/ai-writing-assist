"""Native PostgreSQL confirms exactly one category-rescan start and root budget."""

import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.errors import ConflictError
from infrastructure.tasks.models import AsyncTask
from modules.evolution.category_rescan import (
    CategoryRescanRequest,
    CategoryRescanStart,
    preview_category_rescan,
    start_category_rescan,
)
from modules.evolution.facade import switch_project_engine
from modules.evolution.sampler import register_scene_sampler
from modules.evolution.store import PostgresAttemptStore
from modules.evolution.tasks import handle_evolution_scene_step
from modules.evolution.tests.test_discovery import task_for
from modules.project.models import Project
from tests.e2e.config import DATABASE_URL

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]


@pytest.mark.parametrize("same_operation", [True, False])
async def test_two_connections_confirm_one_rescan(same_operation):
    engine = create_async_engine(DATABASE_URL, pool_size=4, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    nid = uuid4()
    provider = "p4-native-" + str(nid)

    class Sampler:
        async def sample(self, **inputs):
            return {
                "observations": [
                    {"predicate": inputs["scene_text"], "quote": inputs["scene_text"]}
                ],
                "scene_events": [],
                "paid_call_receipt": {
                    "provider": "fixture",
                    "usage": {"total_tokens": 1},
                },
            }

    register_scene_sampler(provider, lambda db, novel_id: Sampler())
    try:
        async with sessions() as db:
            db.add(Project(id=nid, title="类别补扫并发合成作品"))
            await db.flush()
            await switch_project_engine(
                db, str(nid), to_engine="evolution", expected_epoch=1
            )
            await db.commit()
            task = await task_for(
                db,
                str(nid),
                0,
                "林舟左脸有一道疤。",
                provider=provider,
                budget=1,
                discovery=False,
            )
            result = await handle_evolution_scene_step(db, task)
            store = PostgresAttemptStore(db, str(nid))
            frozen = await store.load_frozen("discovery-test", result["attempt_id"])
            run = await store.load_run("discovery-test")
            run.llm_snapshot_json = {
                "profile": {"provider_id": "fixture", "model": "fixture"}
            }
            run.reading_plan_json = {
                "steps": [
                    {
                        "scene_index": 0,
                        "scene_id": frozen.payload["scene_id"],
                        "source_binding": frozen.payload["source_binding"],
                    }
                ]
            }
            await db.commit()
            requests = [
                CategoryRescanRequest(
                    operation_id=uuid4(),
                    from_scene_index=0,
                    through_scene_index=0,
                    categories=["external_appearance"],
                    request_limit=4,
                )
            ]
            requests.append(
                requests[0]
                if same_operation
                else requests[0].model_copy(update={"operation_id": uuid4()})
            )
            starts = []
            for request in requests:
                preview = await preview_category_rescan(
                    db, str(nid), "discovery-test", request
                )
                starts.append(
                    CategoryRescanStart(
                        **request.model_dump(),
                        expected_fingerprint=preview["fingerprint"],
                        authorization_confirmed=True,
                    )
                )

        async def start(request):
            async with sessions() as db:
                try:
                    return await start_category_rescan(
                        db, str(nid), "discovery-test", request
                    )
                except ConflictError:
                    await db.rollback()
                    return None

        results = await asyncio.wait_for(
            asyncio.gather(*(start(request) for request in starts)), timeout=15
        )
        if same_operation:
            assert results[0]["task_id"] == results[1]["task_id"]
        else:
            assert sum(result is None for result in results) == 1
        async with sessions() as db:
            run = await PostgresAttemptStore(db, str(nid)).load_run("discovery-test")
            assert len(run.reading_plan_json["category_rescans"]) == 1
            assert run.budget_remaining == 4 and run.budget_total == 5
            assert (
                await db.scalar(
                    select(func.count())
                    .select_from(AsyncTask)
                    .where(
                        AsyncTask.novel_id == nid,
                        AsyncTask.task_type == "evolution_category_rescan_v1",
                    )
                )
                == 1
            )
    finally:
        async with sessions.begin() as db:
            await db.execute(delete(Project).where(Project.id == nid))
        await engine.dispose()
