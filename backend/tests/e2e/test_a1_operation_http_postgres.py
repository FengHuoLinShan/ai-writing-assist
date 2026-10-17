"""A1 bound HTTP operations commit business and trace data on real PostgreSQL."""

from uuid import uuid4

import pytest
from httpx import ASGITransport
from sqlalchemy import select

from app.main import app
from core.database import get_manager
from modules.account.contracts import BOOTSTRAP_ACCOUNT_ID
from modules.account.models import Account
from modules.assistant.operation_trace_models import (
    AssistantOperationTrace,
    AssistantOperationTraceProjectSalt,
)
from modules.project.models import Project
from modules.world.models import CoreEntity, EntityRevision, WorldRevisionNote
from tests.support.http import XhrAsyncClient

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]


async def test_bound_note_commits_with_trace_and_foreign_project_writes_nothing():
    manager = get_manager()
    novel_id, foreign_id, owner_id = uuid4(), uuid4(), uuid4()
    revision_id, foreign_revision_id = uuid4(), uuid4()
    async with manager.session_factory() as db:
        if await db.get(Account, BOOTSTRAP_ACCOUNT_ID) is None:
            db.add(Account(id=BOOTSTRAP_ACCOUNT_ID, support_code=uuid4().hex))
        db.add(Account(id=owner_id, support_code=uuid4().hex))
        db.add_all(
            [
                Project(id=novel_id, owner_id=BOOTSTRAP_ACCOUNT_ID, title="A1 trace"),
                Project(id=foreign_id, owner_id=owner_id, title="foreign A1"),
            ]
        )
        await db.flush()
        for project_id, revision in (
            (novel_id, revision_id),
            (foreign_id, foreign_revision_id),
        ):
            entity = CoreEntity(
                id=uuid4(),
                novel_id=project_id,
                entity_type="character",
                name="测试人物",
                status="canonical",
            )
            db.add(entity)
            await db.flush()
            db.add(
                EntityRevision(
                    id=revision,
                    novel_id=project_id,
                    entity_id=entity.id,
                    snapshot={"entity_type": "character", "name": "测试人物"},
                    revision_reason="manual_update",
                )
            )
        await db.commit()

    async with XhrAsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        searched = await client.post(
            "/api/assistant/operation-http/evidence/search",
            params={"novel_id": str(novel_id)},
            json={"arguments": {"query": "测试人物", "scopes": ["world"]}},
        )
        written = await client.put(
            "/api/world/revision-notes",
            params={"novel_id": str(novel_id)},
            json={
                "target_kind": "entity",
                "revision_id": str(revision_id),
                "note": "私有审查文字",
            },
        )
        denied = await client.put(
            "/api/world/revision-notes",
            params={"novel_id": str(foreign_id)},
            json={
                "target_kind": "entity",
                "revision_id": str(foreign_revision_id),
                "note": "禁止越界",
            },
        )
    assert searched.status_code == 200, searched.text
    assert written.status_code == 200, written.text
    assert denied.status_code == 404, denied.text
    async with manager.session_factory() as db:
        notes = (await db.scalars(select(WorldRevisionNote))).all()
        traces = (await db.scalars(select(AssistantOperationTrace))).all()
        salts = (await db.scalars(select(AssistantOperationTraceProjectSalt))).all()
    assert len([note for note in notes if note.novel_id == novel_id]) == 1
    assert not [note for note in notes if note.novel_id == foreign_id]
    assert {trace.event_type for trace in traces if trace.novel_id == novel_id} >= {
        "confirmed",
        "executed",
    }
    assert any(
        trace.op_id == "evidence.project.search" and trace.event_type == "executed"
        for trace in traces
    )
    assert not [trace for trace in traces if trace.novel_id == foreign_id]
    assert not [salt for salt in salts if salt.novel_id == foreign_id]
    assert "私有审查文字" not in str([trace.parameter_summary for trace in traces])


async def test_narrow_type_transition_requires_current_preview_and_commits():
    manager = get_manager()
    novel_id, entity_id = uuid4(), uuid4()
    async with manager.session_factory() as db:
        if await db.get(Account, BOOTSTRAP_ACCOUNT_ID) is None:
            db.add(Account(id=BOOTSTRAP_ACCOUNT_ID, support_code=uuid4().hex))
        db.add(Project(id=novel_id, owner_id=BOOTSTRAP_ACCOUNT_ID, title="A1 narrow"))
        db.add(
            CoreEntity(
                id=entity_id,
                novel_id=novel_id,
                entity_type="character",
                name="身份迁移测试",
                status="canonical",
            )
        )
        await db.commit()

    arguments = {"entity_id": str(entity_id), "new_type": "location"}
    async with XhrAsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        prepared = await client.post(
            "/api/assistant/operation-http/previews/world/entity/transition-type",
            params={"novel_id": str(novel_id)},
            json={"arguments": arguments},
        )
        assert prepared.status_code == 200, prepared.text
        stale = await client.post(
            "/api/assistant/operation-http/world/entity/transition-type",
            params={"novel_id": str(novel_id)},
            json={
                "arguments": arguments,
                "expected_preview_hash": "0" * 64,
                "confirmed": True,
            },
        )
        assert stale.status_code == 409, stale.text
        applied = await client.post(
            "/api/assistant/operation-http/world/entity/transition-type",
            params={"novel_id": str(novel_id)},
            json={
                "arguments": arguments,
                "expected_preview_hash": prepared.json()["preview_hash"],
                "confirmed": True,
            },
        )
    assert applied.status_code == 200, applied.text
    async with manager.session_factory() as db:
        entity = await db.get(CoreEntity, entity_id)
        traces = (
            await db.scalars(
                select(AssistantOperationTrace).where(
                    AssistantOperationTrace.novel_id == novel_id,
                    AssistantOperationTrace.op_id == "world.entity.transition_type",
                )
            )
        ).all()
    assert entity.entity_type == "location"
    assert {trace.event_type for trace in traces} >= {
        "previewed",
        "confirmed",
        "failed",
        "executed",
    }
    preview_call = min(traces, key=lambda trace: trace.id).call_id
    assert {trace.event_type for trace in traces if trace.call_id == preview_call} == {
        "proposed",
        "previewed",
    }
