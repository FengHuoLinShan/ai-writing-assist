"""Real PostgreSQL HTTP transaction boundary for operation traces."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport
from pydantic import BaseModel
from sqlalchemy import event, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.main import _install_operation_trace_route_adapters, app
from core.database import get_manager
from core.dependencies import DbSession
from modules.account.contracts import BOOTSTRAP_ACCOUNT_ID
from modules.account.models import Account
from modules.assistant.operation_trace_models import (
    AssistantOperationTrace,
    AssistantOperationTraceAggregate,
)
from modules.assistant.operation_trace_service import archive_expired_operation_traces
from modules.assistant.proactive import schedule_due
from modules.project.models import Project
from modules.world.models import CoreEntity
from tests.support.http import XhrAsyncClient

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]


class TracePayload(BaseModel):
    novel_id: UUID


@pytest.mark.parametrize("fail_final_commit", [False, True])
async def test_http_operation_trace_follows_real_db_session_commit(fail_final_commit):
    novel_id = uuid4()
    spoof_id = uuid4()
    call_path = f"/api/_trace_review/{novel_id}"

    async with get_manager().session_factory() as db:
        if await db.get(Account, BOOTSTRAP_ACCOUNT_ID) is None:
            db.add(Account(id=BOOTSTRAP_ACCOUNT_ID, support_code="trace-review-owner"))
        db.add(Project(id=novel_id, owner_id=BOOTSTRAP_ACCOUNT_ID, title="before"))
        db.add(Project(id=spoof_id, owner_id=BOOTSTRAP_ACCOUNT_ID, title="other"))
        await db.commit()

    async def write_project(novel_id: UUID, db: DbSession, payload: TracePayload):
        assert payload.novel_id == spoof_id
        project = await db.get(Project, novel_id)
        project.title = "after"
        await db.flush()
        if fail_final_commit:
            db.sync_session.info["trace_review_fail_final_commit"] = True
        return {"type": "project", "id": str(novel_id)}

    def fail_commit(session):
        if (
            session.info.get("trace_review_fail_final_commit")
            and not session.in_nested_transaction()
        ):
            raise RuntimeError("synthetic final commit failure")

    app.add_api_route(
        "/api/_trace_review/{novel_id}",
        write_project,
        methods=["POST"],
        openapi_extra={"x-novelcraft-operation-id": "project.add_task"},
    )
    route = app.routes[-1]
    _install_operation_trace_route_adapters(app)
    event.listen(Session, "before_commit", fail_commit)
    try:
        async with XhrAsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        ) as client:
            response = await client.post(call_path, json={"novel_id": str(spoof_id)})
        assert response.status_code == (500 if fail_final_commit else 200)

        async with get_manager().session_factory() as db:
            project = await db.get(Project, novel_id)
            events = (
                await db.scalars(
                    select(AssistantOperationTrace.event_type)
                    .where(AssistantOperationTrace.novel_id == novel_id)
                    .order_by(AssistantOperationTrace.id)
                )
            ).all()
            spoof_events = (
                await db.scalars(
                    select(AssistantOperationTrace.id).where(
                        AssistantOperationTrace.novel_id == spoof_id
                    )
                )
            ).all()
        assert project.title == ("before" if fail_final_commit else "after")
        assert spoof_events == []
        assert ("executed" in events) is not fail_final_commit
        if fail_final_commit:
            assert "failed" in events
    finally:
        event.remove(Session, "before_commit", fail_commit)
        app.routes.remove(route)


async def test_dossier_http_route_records_committed_owner_write_without_content():
    novel_id, entity_id = uuid4(), uuid4()
    content = "合成档案秘密正文不得进入留痕"
    async with get_manager().session_factory() as db:
        if await db.get(Account, BOOTSTRAP_ACCOUNT_ID) is None:
            db.add(Account(id=BOOTSTRAP_ACCOUNT_ID, support_code="trace-review-owner"))
        db.add(Project(id=novel_id, owner_id=BOOTSTRAP_ACCOUNT_ID, title="dossier trace"))
        db.add(
            CoreEntity(
                id=entity_id,
                novel_id=novel_id,
                entity_type="location",
                name="合成地点",
                status="canonical",
            )
        )
        await db.commit()

    async with XhrAsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        response = await client.post(
            f"/api/world/entities/{entity_id}/dossier/entries",
            params={"novel_id": str(novel_id)},
            json={"facing": {"kind": "core", "key": "history"}, "content": content},
        )
    assert response.status_code == 201, response.text

    async with get_manager().session_factory() as db:
        traces = (
            await db.scalars(
                select(AssistantOperationTrace)
                .where(AssistantOperationTrace.novel_id == novel_id)
                .order_by(AssistantOperationTrace.id)
            )
        ).all()
    assert [row.event_type for row in traces] == ["confirmed", "executed"]
    assert all(row.owner_id == BOOTSTRAP_ACCOUNT_ID for row in traces)
    assert content not in str([row.parameter_summary for row in traces])
    assert content not in str([row.result_refs for row in traces])


async def test_trace_insert_failure_keeps_http_write_and_marks_response():
    novel_id, entity_id = uuid4(), uuid4()
    async with get_manager().session_factory() as db:
        if await db.get(Account, BOOTSTRAP_ACCOUNT_ID) is None:
            db.add(Account(id=BOOTSTRAP_ACCOUNT_ID, support_code="trace-review-owner"))
        db.add(Project(id=novel_id, owner_id=BOOTSTRAP_ACCOUNT_ID, title="trace fault"))
        db.add(
            CoreEntity(
                id=entity_id,
                novel_id=novel_id,
                entity_type="location",
                name="合成地点",
                status="canonical",
            )
        )
        await db.commit()

    def reject_trace(_session, _context, _instances):
        if any(isinstance(row, AssistantOperationTrace) for row in _session.new):
            raise RuntimeError("synthetic trace insert failure")

    event.listen(Session, "before_flush", reject_trace)
    try:
        async with XhrAsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        ) as client:
            response = await client.post(
                f"/api/world/entities/{entity_id}/dossier/entries",
                params={"novel_id": str(novel_id)},
                json={
                    "facing": {"kind": "core", "key": "history"},
                    "content": "合成正文",
                },
            )
    finally:
        event.remove(Session, "before_flush", reject_trace)
    assert response.status_code == 201, response.text
    assert response.headers["x-novelcraft-operation-trace-incomplete"] == "true"
    async with get_manager().session_factory() as db:
        assert (
            await db.scalar(
                select(AssistantOperationTrace.id).where(
                    AssistantOperationTrace.novel_id == novel_id
                )
            )
            is None
        )


async def test_pg_append_only_and_expired_detail_aggregation():
    novel_id = uuid4()
    owner_id = BOOTSTRAP_ACCOUNT_ID
    old_time = datetime.now(UTC) - timedelta(days=181)
    async with get_manager().session_factory() as db:
        if await db.get(Account, owner_id) is None:
            db.add(Account(id=owner_id, support_code="trace-review-owner"))
        db.add(Project(id=novel_id, owner_id=owner_id, title="retention trace"))
        await db.flush()
        for occurred_at in (old_time, datetime.now(UTC)):
            db.add(
                AssistantOperationTrace(
                    novel_id=novel_id,
                    owner_id=owner_id,
                    actor_type="ui",
                    entrypoint="trace.review",
                    op_id="project.add_task",
                    op_version="1",
                    risk_level="R2",
                    fee_category="free",
                    event_type="executed",
                    target_type="task",
                    target_refs=[],
                    parameter_summary={},
                    result_refs=[],
                    occurred_at=occurred_at,
                )
            )
        await db.commit()

    async with get_manager().session_factory() as db:
        recent = await db.scalar(
            select(AssistantOperationTrace.id).where(
                AssistantOperationTrace.novel_id == novel_id,
                AssistantOperationTrace.occurred_at
                > datetime.now(UTC) - timedelta(days=1),
            )
        )
        with pytest.raises(DBAPIError):
            await db.execute(
                text("DELETE FROM assistant_operation_traces WHERE id = :id"),
                {"id": recent},
            )
        await db.rollback()

    async with get_manager().session_factory() as db:
        assert await archive_expired_operation_traces(db, str(novel_id)) == 1
        await db.commit()
    async with get_manager().session_factory() as db:
        remaining = (
            await db.scalars(
                select(AssistantOperationTrace).where(
                    AssistantOperationTrace.novel_id == novel_id
                )
            )
        ).all()
        aggregates = (
            await db.scalars(
                select(AssistantOperationTraceAggregate).where(
                    AssistantOperationTraceAggregate.novel_id == novel_id
                )
            )
        ).all()
    assert len(remaining) == 1 and remaining[0].id == recent
    assert len(aggregates) == 1 and aggregates[0].event_count == 1


async def test_idle_worker_tick_archives_expired_trace_without_owner_read():
    novel_id = uuid4()
    async with get_manager().session_factory() as db:
        if await db.get(Account, BOOTSTRAP_ACCOUNT_ID) is None:
            db.add(Account(id=BOOTSTRAP_ACCOUNT_ID, support_code="trace-review-owner"))
        db.add(Project(id=novel_id, owner_id=BOOTSTRAP_ACCOUNT_ID, title="idle trace"))
        await db.flush()
        db.add(
            AssistantOperationTrace(
                novel_id=novel_id,
                owner_id=BOOTSTRAP_ACCOUNT_ID,
                actor_type="ui",
                entrypoint="trace.review",
                op_id="project.add_task",
                op_version="1",
                risk_level="R2",
                fee_category="free",
                event_type="executed",
                target_type="task",
                target_refs=[],
                parameter_summary={},
                result_refs=[],
                occurred_at=datetime.now(UTC) - timedelta(days=181),
            )
        )
        await db.commit()

    async with get_manager().session_factory() as db:
        await schedule_due(db)
        await db.commit()

    async with get_manager().session_factory() as db:
        detail = await db.scalar(
            select(AssistantOperationTrace.id).where(
                AssistantOperationTrace.novel_id == novel_id
            )
        )
        aggregate = await db.scalar(
            select(AssistantOperationTraceAggregate.event_count).where(
                AssistantOperationTraceAggregate.novel_id == novel_id
            )
        )
    assert detail is None
    assert aggregate == 1
