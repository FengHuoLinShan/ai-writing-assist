"""Reproducible saved-writing feed load, without any provider or worker execution."""

import json
import math
import platform
from time import perf_counter
from uuid import UUID, uuid4

from sqlalchemy import func, insert, select

from infrastructure.llm.providers import OpenAIProvider
from infrastructure.tasks.models import AsyncTask
from modules.assistant.forecast import runtime, service
from modules.assistant.forecast.contracts import (
    EvaluateRequest,
    FeedRequest,
    FocusRequest,
)
from modules.assistant.forecast.models import ForecastCandidate, ForecastDependency
from modules.assistant.forecast.tests.test_forecasts import settings_on
from modules.assistant.models import AssistantRun
from modules.story.outline_state.models import Scene
from modules.world.models import CoreEntity
from modules.writing.facade import create_draft_only
from modules.writing.models import WritingDraft


async def test_saved_writing_feed_under_retained_history_load(
    db_session, test_project_id, monkeypatch
):
    db, nid = db_session, test_project_id
    settings_on(monkeypatch)

    async def forbidden_provider(*args, **kwargs):
        raise AssertionError("Feed/enqueue must never call the provider")

    monkeypatch.setattr(OpenAIProvider, "generate", forbidden_provider)
    await db.execute(
        insert(WritingDraft),
        [
            {
                "novel_id": UUID(nid),
                "chapter_index": index,
                "title": f"合成章 {index}",
                "content": "仅用于性能负载的合成文字。",
                "content_hash": "a" * 64,
            }
            for index in range(1, 300)
        ],
    )
    draft = await create_draft_only(db, nid, 300, "当前章", "她把杯子放回桌上。")
    await db.execute(
        insert(Scene),
        [
            {"novel_id": UUID(nid), "scene_index": index, "title": f"场景 {index}"}
            for index in range(1500)
        ],
    )
    for start in range(0, 5000, 1000):
        await db.execute(
            insert(CoreEntity),
            [
                {
                    "novel_id": UUID(nid),
                    "entity_type": "item",
                    "name": f"物品 {index}",
                    "status": "canonical",
                }
                for index in range(start, start + 1000)
            ],
        )
    focus = FocusRequest(
        client_context_id=uuid4(), focus_seq=1, page="writing", draft_id=draft.id
    )
    request = EvaluateRequest(
        operation_id=uuid4(),
        context=focus,
        horizon={"unit": "scene"},
        requested_capabilities=["account.readiness.v1"],
    )
    submitted = await runtime.submit(db, nid, request)
    run = await db.get(AssistantRun, submitted.run_id)
    task = await db.get(AsyncTask, run.task_id)
    db.task_checkpoint_enabled = True
    await runtime.execute(db, task)
    candidate = await db.scalar(
        select(ForecastCandidate).where(ForecastCandidate.run_id == submitted.run_id)
    )
    template = {
        column.name: getattr(candidate, column.name)
        for column in ForecastCandidate.__table__.columns
    }
    dependency_rows = (
        await db.scalars(
            select(ForecastDependency).where(
                ForecastDependency.candidate_id == candidate.id
            )
        )
    ).all()
    dependencies = [
        {
            column.name: getattr(row, column.name)
            for column in ForecastDependency.__table__.columns
        }
        for row in dependency_rows
    ]
    run_ids = [uuid4() for _ in range(313)]
    await db.execute(
        insert(AssistantRun),
        [
            {
                "id": value,
                "novel_id": UUID(nid),
                "owner_id": run.owner_id,
                "mode": "author",
                "status": "completed",
                "request_hash": "b" * 64,
            }
            for value in run_ids
        ],
    )
    for start in range(1, 20000, 500):
        values = [
            {
                **template,
                "id": uuid4(),
                "run_id": run_ids[index // 64],
                "ordinal": index % 64,
                "issue_key": template["issue_key"]
                if index % 500 == 0
                else f"synthetic-issue-{index % 500}",
            }
            for index in range(start, min(start + 500, 20000))
        ]
        await db.execute(insert(ForecastCandidate), values)
        await db.execute(
            insert(ForecastDependency),
            [
                {**dependency, "candidate_id": row["id"]}
                for row in values
                for dependency in dependencies
            ],
        )
    await db.commit()
    before = await db.scalar(select(func.count()).select_from(AsyncTask))
    feed_times, enqueue_times = [], []
    for index in range(33):
        started = perf_counter()
        value = await service.feed(db, nid, FeedRequest(context=focus))
        elapsed = (perf_counter() - started) * 1000
        assert value.coverage.enumerated_total == 500
        if index >= 3:
            feed_times.append(elapsed)
    assert await db.scalar(select(func.count()).select_from(AsyncTask)) == before
    for index in range(33):
        started = perf_counter()
        await runtime.submit(
            db, nid, request.model_copy(update={"operation_id": uuid4()})
        )
        await db.commit()
        if index >= 3:
            enqueue_times.append((perf_counter() - started) * 1000)

    def p95(values):
        return round(sorted(values)[math.ceil(0.95 * len(values)) - 1], 2)

    result = {
        "environment": platform.platform(),
        "measurement": "domain service incl. PostgreSQL; HTTP overhead excluded",
        "chapters": 300,
        "scenes": 1500,
        "objects": 5000,
        "retained_assessments": 20000,
        "active_issues": 500,
        "samples": 30,
        "warmups": 3,
        "provider_calls": 0,
        "feed_p95_ms": p95(feed_times),
        "enqueue_p95_ms": p95(enqueue_times),
        "quality_acceptance": "not_run",
    }
    print("FORECAST_PERFORMANCE=" + json.dumps(result, ensure_ascii=False))
    assert result["feed_p95_ms"] <= 500
    assert result["enqueue_p95_ms"] <= 500
