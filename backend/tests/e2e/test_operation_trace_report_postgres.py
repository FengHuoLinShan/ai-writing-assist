"""PostgreSQL transaction evidence for operation-trace retention and reports."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from httpx import ASGITransport
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.main import app
from core.database import get_manager
from modules.account.contracts import BOOTSTRAP_ACCOUNT_ID
from modules.account.models import Account
from modules.assistant.operation_trace_models import (
    AssistantOperationSequenceAggregate,
    AssistantOperationTrace,
    AssistantOperationTraceAggregate,
    AssistantOperationTraceArchiveDay,
    AssistantOperationTraceLifecycleAggregate,
    AssistantOperationTraceMetricAggregate,
    AssistantOperationTraceParameterAggregate,
)
from modules.assistant.operation_trace_report import (
    build_operation_trace_report,
    operation_trace_report_csv,
)
from modules.assistant.operation_trace_service import (
    archive_expired_operation_traces,
    operation_trace_cutoff,
)
from modules.project.models import Project
from tests.e2e.config import require_e2e_database_url
from tests.support.http import XhrAsyncClient

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]


def _trace(
    project_id,
    owner_id,
    occurred_at: datetime,
    event_type: str,
    call_id,
    *,
    op_id: str = "project.add_task",
    run_id=None,
    session_id=None,
    duration_ms: int | None = None,
    usage: dict | None = None,
) -> AssistantOperationTrace:
    return AssistantOperationTrace(
        call_id=call_id,
        parent_call_id=run_id,
        novel_id=project_id,
        owner_id=owner_id,
        occurred_at=occurred_at,
        actor_type="ui",
        entrypoint="assistant.test",
        run_id=run_id,
        session_id=session_id,
        op_id=op_id,
        op_version="1",
        risk_level="R2",
        fee_category="free",
        event_type=event_type,
        target_type="author_task",
        target_refs=[],
        parameter_summary={
            "fields": {"title": {"present": True, "type": "string", "length": 12}},
            "unknown_fields": {"present": False},
        },
        result_refs=[],
        duration_ms=duration_ms,
        usage=usage,
    )


async def _snapshot(db: AsyncSession, project_id) -> dict[str, list[tuple]]:
    models = {
        "events": AssistantOperationTraceAggregate,
        "archive_days": AssistantOperationTraceArchiveDay,
        "sequences": AssistantOperationSequenceAggregate,
        "metrics": AssistantOperationTraceMetricAggregate,
        "lifecycle": AssistantOperationTraceLifecycleAggregate,
        "parameters": AssistantOperationTraceParameterAggregate,
    }
    snapshot = {}
    for name, model in models.items():
        rows = (
            await db.scalars(
                select(model)
                .where(model.novel_id == project_id)
                .order_by(*model.__table__.primary_key.columns)
            )
        ).all()
        snapshot[name] = [
            tuple(
                json.dumps(value, sort_keys=True, separators=(",", ":"))
                if isinstance(value, (dict, list))
                else value.isoformat()
                if isinstance(value, datetime)
                else value
                for column, value in row.__dict__.items()
                if not column.startswith("_") and column != "novel_id"
            )
            for row in rows
        ]
    return snapshot


async def _create_owner_projects(sessions, count: int = 3):
    owner_id = uuid4()
    project_ids = [uuid4() for _ in range(count)]
    async with sessions.begin() as db:
        db.add(Account(id=owner_id, support_code=f"trace-{owner_id.hex[:16]}"))
        db.add_all(
            Project(
                id=project_id,
                owner_id=owner_id,
                title=f"Operation trace evidence {index}",
            )
            for index, project_id in enumerate(project_ids)
        )
    return owner_id, project_ids


def _old_trace_rows(project_id, owner_id, now: datetime) -> list[AssistantOperationTrace]:
    cutoff = operation_trace_cutoff(now)
    session_id, run_id = uuid4(), uuid4()
    events = []
    for day_offset in (2, 1):
        at = cutoff - timedelta(days=day_offset) + timedelta(hours=12)
        accepted_call = uuid4()
        failed_call = uuid4()
        events.extend(
            [
                _trace(
                    project_id,
                    owner_id,
                    at,
                    "proposed",
                    accepted_call,
                    run_id=run_id,
                    session_id=session_id,
                ),
                _trace(
                    project_id,
                    owner_id,
                    at + timedelta(seconds=1),
                    "edited",
                    accepted_call,
                    run_id=run_id,
                    session_id=session_id,
                ),
                _trace(
                    project_id,
                    owner_id,
                    at + timedelta(seconds=2),
                    "confirmed",
                    accepted_call,
                    run_id=run_id,
                    session_id=session_id,
                ),
                _trace(
                    project_id,
                    owner_id,
                    at + timedelta(seconds=3),
                    "executed",
                    accepted_call,
                    run_id=run_id,
                    session_id=session_id,
                    duration_ms=75,
                    usage={
                        "requests": 1,
                        "prompt_tokens": 12,
                        "completion_tokens": 6,
                        "usage_complete": True,
                    },
                ),
                _trace(
                    project_id,
                    owner_id,
                    at + timedelta(seconds=4),
                    "restored",
                    accepted_call,
                    run_id=run_id,
                    session_id=session_id,
                ),
                _trace(
                    project_id,
                    owner_id,
                    at,
                    "failed",
                    failed_call,
                    op_id="world.dossier.entry.edit",
                    run_id=run_id,
                    session_id=session_id,
                ),
            ]
        )
    return events


async def test_postgres_archive_batches_are_equivalent_and_report_keeps_real_coverage():
    engine = create_async_engine(require_e2e_database_url(), pool_size=4, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        owner_id, (one_shot_id, batched_id) = await _create_owner_projects(
            sessions, count=2
        )
        now = datetime.now(UTC)
        async with sessions.begin() as db:
            db.add_all(
                _old_trace_rows(one_shot_id, owner_id, now)
                + _old_trace_rows(batched_id, owner_id, now)
            )

        async with sessions.begin() as db:
            one_shot_count = await archive_expired_operation_traces(
                db, str(one_shot_id), now=now
            )
        batched_count = 0
        for _ in range(3):
            async with sessions.begin() as db:
                moved = await archive_expired_operation_traces(
                    db, str(batched_id), now=now, max_days=1
                )
            batched_count += moved
            if moved == 0:
                break

        assert one_shot_count == batched_count == 12
        async with sessions() as db:
            one_snapshot = await _snapshot(db, one_shot_id)
            batch_snapshot = await _snapshot(db, batched_id)
            report = await build_operation_trace_report(
                db,
                str(one_shot_id),
                period="all",
                collection_enabled=True,
            )
            remaining = await db.scalar(
                select(AssistantOperationTrace.id).where(
                    AssistantOperationTrace.novel_id == one_shot_id
                )
            )

        assert one_snapshot == batch_snapshot
        assert remaining is None
        assert report["coverage"]["status"] == "partial"
        assert report["coverage"]["missing_duration_event_count"] == 10
        assert report["coverage"]["unmeasured_usage_event_count"] == 10
        assert all(sequence["complete"] for sequence in report["sequences"])
        accepted = next(
            item
            for item in report["lifecycle"]
            if item["operation"] == "project.add_task"
        )
        assert accepted["proposals"] == 2
        assert accepted["accepted"] == 2
        assert accepted["edited_then_accepted"] == 2
        assert accepted["same_day_matched_restoration_groups"] == 2
        executed = next(
            item
            for item in report["metrics"]
            if item["operation"] == "project.add_task" and item["event"] == "executed"
        )
        assert executed["duration"]["average_ms"] == 75
        assert executed["usage"]["fields"]["requests"]["total"] == 2
        assert executed["usage"]["pending_total"] is None
        assert report["coverage"]["pending_usage_total"] is None
        serialized = json.dumps(report, sort_keys=True)
        csv_text = operation_trace_report_csv(report)
        assert "metadata,,,,,,,period,all," in csv_text
        assert "coverage,,,,,,,missing_duration_event_count,10," in csv_text
        for private_id in (str(one_shot_id), str(owner_id)):
            assert private_id not in serialized
            assert private_id not in csv_text
    finally:
        await engine.dispose()


async def test_cross_utc_day_restore_rate_uses_one_execution_receipt():
    project_id, call_id, replayed_call_id = uuid4(), uuid4(), uuid4()
    day = datetime.now(UTC).date() - timedelta(days=2)
    executed_at = datetime.combine(day, datetime.min.time(), tzinfo=UTC) + timedelta(
        hours=23, minutes=59
    )
    async with get_manager().session_factory() as db:
        if await db.get(Account, BOOTSTRAP_ACCOUNT_ID) is None:
            db.add(Account(id=BOOTSTRAP_ACCOUNT_ID, support_code="trace-rate-owner"))
        db.add(Project(id=project_id, owner_id=BOOTSTRAP_ACCOUNT_ID, title="trace rate"))
        await db.flush()
        db.add_all(
            [
                _trace(
                    project_id, BOOTSTRAP_ACCOUNT_ID, executed_at, "executed", call_id
                ),
                _trace(
                    project_id,
                    BOOTSTRAP_ACCOUNT_ID,
                    executed_at + timedelta(seconds=30),
                    "executed",
                    replayed_call_id,
                ),
                _trace(
                    project_id,
                    BOOTSTRAP_ACCOUNT_ID,
                    executed_at + timedelta(minutes=2),
                    "restored",
                    call_id,
                ),
                _trace(
                    project_id,
                    BOOTSTRAP_ACCOUNT_ID,
                    executed_at + timedelta(minutes=3),
                    "undone",
                    call_id,
                ),
                _trace(
                    project_id,
                    BOOTSTRAP_ACCOUNT_ID,
                    executed_at + timedelta(minutes=1),
                    "executed",
                    replayed_call_id,
                ),
                _trace(
                    project_id,
                    BOOTSTRAP_ACCOUNT_ID,
                    executed_at + timedelta(minutes=4),
                    "restored",
                    replayed_call_id,
                ),
            ]
        )
        await db.commit()
    async with get_manager().session_factory() as db:
        report = await build_operation_trace_report(
            db, str(project_id), period="30d", collection_enabled=True
        )
        row = next(
            item
            for item in report["lifecycle"]
            if item["operation"] == "project.add_task"
        )
        assert row["execution_groups"] == 2
        assert row["matched_restoration_groups"] == 2
        assert row["restoration_rate"] == 1
        assert row["restoration_rate_denominator"] == 2
        assert row["restoration_rate_status"] == "measurable"
        csv_text = operation_trace_report_csv(report)
        assert "restoration_rate,1.0,measurable" in csv_text


async def test_postgres_archive_and_owner_read_serialize_without_double_counting():
    engine = create_async_engine(require_e2e_database_url(), pool_size=3, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        owner_id, (project_id,) = await _create_owner_projects(sessions, count=1)
        now = datetime.now(UTC)
        async with sessions.begin() as db:
            db.add_all(_old_trace_rows(project_id, owner_id, now)[:6])

        lock_taken = asyncio.Event()
        allow_commit = asyncio.Event()

        async def archive_holding_transaction():
            async with sessions.begin() as db:
                assert (
                    await archive_expired_operation_traces(db, str(project_id), now=now)
                    == 6
                )
                lock_taken.set()
                await allow_commit.wait()

        async def read_report():
            async with sessions() as db:
                return await build_operation_trace_report(
                    db,
                    str(project_id),
                    period="all",
                    collection_enabled=True,
                )

        archive_task = asyncio.create_task(archive_holding_transaction())
        await asyncio.wait_for(lock_taken.wait(), timeout=5)
        report_task = asyncio.create_task(read_report())
        await asyncio.sleep(0.1)
        allow_commit.set()
        await asyncio.wait_for(archive_task, timeout=5)
        first = await asyncio.wait_for(report_task, timeout=5)
        second = await read_report()

        assert sum(row["count"] for row in first["events"]) == 6
        assert sum(row["count"] for row in second["events"]) == 6
    finally:
        await engine.dispose()


async def test_partial_utc_day_expires_at_exact_microsecond_and_keeps_one_sequence():
    engine = create_async_engine(require_e2e_database_url(), pool_size=3)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        owner_id, (staged_id, once_id) = await _create_owner_projects(sessions, count=2)
        first_now = datetime.now(UTC).replace(
            hour=18, minute=0, second=0, microsecond=0
        ) - timedelta(days=1)
        cutoff = operation_trace_cutoff(first_now)
        assert cutoff == first_now - timedelta(days=180)
        session_id = uuid4()
        moments = (
            cutoff - timedelta(microseconds=1),
            cutoff,
            cutoff + timedelta(microseconds=1),
            cutoff + timedelta(hours=1),
        )
        async with sessions.begin() as db:
            for project_id in (staged_id, once_id):
                db.add_all(
                    _trace(
                        project_id,
                        owner_id,
                        moment,
                        "executed",
                        uuid4(),
                        op_id=f"project.step_{index}",
                        session_id=session_id,
                    )
                    for index, moment in enumerate(moments)
                )

        async with sessions.begin() as db:
            assert (
                await archive_expired_operation_traces(db, str(staged_id), now=first_now)
                == 1
            )
        async with sessions() as db:
            remaining = (
                await db.scalars(
                    select(AssistantOperationTrace.occurred_at).where(
                        AssistantOperationTrace.novel_id == staged_id
                    )
                )
            ).all()
            assert sorted(remaining) == list(moments[1:])
            report = await build_operation_trace_report(
                db, str(staged_id), period="all", collection_enabled=True
            )
            assert sum(row["count"] for row in report["events"]) == 4
            assert report["sequences"] == [
                {
                    "date": cutoff.date().isoformat(),
                    "operations": [f"project.step_{index}" for index in range(4)],
                    "count": 1,
                    "complete": True,
                }
            ]
            # Report GET must not archive even the remaining overdue row.
            assert (
                await db.scalar(
                    select(AssistantOperationTrace.id).where(
                        AssistantOperationTrace.novel_id == staged_id,
                        AssistantOperationTrace.occurred_at == cutoff,
                    )
                )
                is not None
            )

        async with sessions.begin() as db:
            assert (
                await archive_expired_operation_traces(
                    db, str(staged_id), now=first_now + timedelta(microseconds=1)
                )
                == 1
            )
        async with sessions.begin() as db:
            assert (
                await archive_expired_operation_traces(
                    db, str(staged_id), now=first_now + timedelta(hours=2)
                )
                == 2
            )
        async with sessions.begin() as db:
            assert (
                await archive_expired_operation_traces(
                    db, str(once_id), now=first_now + timedelta(hours=2)
                )
                == 4
            )
        async with sessions() as db:
            assert await _snapshot(db, staged_id) == await _snapshot(db, once_id)
            assert (
                await db.scalar(
                    select(AssistantOperationTrace.id).where(
                        AssistantOperationTrace.novel_id == staged_id
                    )
                )
                is None
            )
    finally:
        await engine.dispose()


async def test_preexisting_fragment_is_not_reported_as_complete_day():
    engine = create_async_engine(require_e2e_database_url(), pool_size=2)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        owner_id, (project_id,) = await _create_owner_projects(sessions, count=1)
        now = datetime.now(UTC)
        old_time = now - timedelta(days=181)
        async with sessions.begin() as db:
            db.add(
                AssistantOperationTraceAggregate(
                    novel_id=project_id,
                    occurred_on=old_time.date(),
                    op_id="project.old_step",
                    event_type="executed",
                    event_count=1,
                )
            )
            db.add(
                AssistantOperationSequenceAggregate(
                    novel_id=project_id,
                    occurred_on=old_time.date(),
                    sequence_hash="a" * 64,
                    operation_sequence=["project.old_step"],
                    sequence_count=1,
                    sequence_complete=True,
                )
            )
            db.add(
                _trace(
                    project_id,
                    owner_id,
                    old_time + timedelta(seconds=1),
                    "executed",
                    uuid4(),
                    op_id="project.new_step",
                    session_id=uuid4(),
                )
            )
        async with sessions.begin() as db:
            assert (
                await archive_expired_operation_traces(db, str(project_id), now=now) == 1
            )
        async with sessions() as db:
            marker = await db.get(
                AssistantOperationTraceArchiveDay, (project_id, old_time.date())
            )
            assert marker is not None and marker.complete is False
            report = await build_operation_trace_report(
                db, str(project_id), period="all", collection_enabled=True
            )
            assert report["coverage"]["incomplete_sequence_count"] == 2
            assert all(not item["complete"] for item in report["sequences"])
            assert report["coverage"]["missing_metric_event_count"] == 1
    finally:
        await engine.dispose()


async def test_report_http_owner_active_project_export_and_read_only():
    owner_project, foreign_project, inactive_project, rp_project = (
        uuid4() for _ in range(4)
    )
    foreign_owner = uuid4()
    private_target = uuid4()
    private_trace = _trace(
        owner_project,
        BOOTSTRAP_ACCOUNT_ID,
        datetime.now(UTC) - timedelta(days=181),
        "executed",
        uuid4(),
    )
    private_trace.target_refs = [{"type": "author_task", "id": str(private_target)}]
    async with get_manager().session_factory() as db:
        if await db.get(Account, BOOTSTRAP_ACCOUNT_ID) is None:
            db.add(Account(id=BOOTSTRAP_ACCOUNT_ID, support_code=uuid4().hex))
        db.add(Account(id=foreign_owner, support_code=uuid4().hex))
        db.add_all(
            [
                Project(
                    id=owner_project, owner_id=BOOTSTRAP_ACCOUNT_ID, title="本人作品"
                ),
                Project(id=foreign_project, owner_id=foreign_owner, title="他人作品"),
                Project(
                    id=inactive_project,
                    owner_id=BOOTSTRAP_ACCOUNT_ID,
                    title="已删除作品",
                    deleted_at=datetime.now(UTC),
                ),
                Project(
                    id=rp_project,
                    owner_id=BOOTSTRAP_ACCOUNT_ID,
                    title="隔离旅程",
                    project_kind="interaction",
                ),
            ]
        )
        await db.flush()
        db.add(private_trace)
        await db.commit()

    base = "/api/assistant/operation-traces"
    async with XhrAsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        valid = await client.get(
            f"{base}/aggregate", params={"novel_id": str(owner_project), "period": "all"}
        )
        assert valid.status_code == 200, valid.text
        assert valid.json()["events"][0]["count"] == 1
        assert valid.json()["operation_labels"]["project.add_task"] == "记录作者待办"
        exported = await client.get(
            f"{base}/export",
            params={"novel_id": str(owner_project), "period": "all", "format": "csv"},
        )
        assert exported.status_code == 200, exported.text
        assert "text/csv" in exported.headers["content-type"]
        for private_value in (str(owner_project), str(private_target)):
            assert private_value not in exported.text
            assert private_value not in valid.text
        for denied_project in (foreign_project, inactive_project, rp_project):
            for path in ("aggregate", "export"):
                denied = await client.get(
                    f"{base}/{path}", params={"novel_id": str(denied_project)}
                )
                assert denied.status_code == 404, (path, denied.text)
        bad_period = await client.get(
            f"{base}/aggregate", params={"novel_id": str(owner_project), "period": "0d"}
        )
        assert bad_period.status_code == 422

    async with get_manager().session_factory() as db:
        assert (
            await db.scalar(
                select(AssistantOperationTrace.id).where(
                    AssistantOperationTrace.novel_id == owner_project
                )
            )
            is not None
        )
        assert (
            await db.scalar(
                select(AssistantOperationTraceAggregate.novel_id).where(
                    AssistantOperationTraceAggregate.novel_id == owner_project
                )
            )
            is None
        )


async def test_postgres_append_only_trigger_rejects_live_trace_updates():
    engine = create_async_engine(require_e2e_database_url(), pool_size=2, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        owner_id, (project_id,) = await _create_owner_projects(sessions, count=1)
        row = _trace(
            project_id,
            owner_id,
            datetime.now(UTC),
            "executed",
            uuid4(),
        )
        async with sessions.begin() as db:
            db.add(row)
        async with sessions() as db:
            stored = await db.scalar(
                select(AssistantOperationTrace).where(
                    AssistantOperationTrace.novel_id == project_id
                )
            )
            assert stored is not None
            stored.event_type = "failed"
            with pytest.raises(DBAPIError, match="append-only"):
                await db.commit()
            await db.rollback()
    finally:
        await engine.dispose()
