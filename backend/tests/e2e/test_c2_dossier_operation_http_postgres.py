"""C2 catalog HTTP reads and previews use real owner/trace boundaries."""

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
from modules.story.outline_state.models import Scene
from modules.world.models import CoreEntity
from tests.support.http import XhrAsyncClient

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]


async def test_c2_narrow_read_and_previews_are_scoped_traced_and_queue_no_task(
    monkeypatch,
):
    from infrastructure.tasks.models import AsyncTask
    from modules.evidence.compilation import facade as evidence_facade

    async def skip_retrieval_diagnostic(*_args, **_kwargs):
        # The E2E fixture uses a one-connection manager; this diagnostic normally
        # uses a side session while the request owns that connection.
        return None

    monkeypatch.setattr(
        evidence_facade._confirmation_service._compiler._loaders["rag_chunks"],
        "_record",
        skip_retrieval_diagnostic,
    )

    manager = get_manager()
    novel_id, foreign_id, foreign_owner = uuid4(), uuid4(), uuid4()
    scene_id, character_id, foreign_character_id = uuid4(), uuid4(), uuid4()
    async with manager.session_factory() as db:
        if await db.get(Account, BOOTSTRAP_ACCOUNT_ID) is None:
            db.add(Account(id=BOOTSTRAP_ACCOUNT_ID, support_code=uuid4().hex))
        db.add(Account(id=foreign_owner, support_code=uuid4().hex))
        db.add_all(
            [
                Project(id=novel_id, owner_id=BOOTSTRAP_ACCOUNT_ID, title="C2 catalog"),
                Project(id=foreign_id, owner_id=foreign_owner, title="C2 foreign"),
            ]
        )
        db.add(Scene(id=scene_id, novel_id=novel_id, scene_index=0))
        db.add(
            CoreEntity(
                id=character_id,
                novel_id=novel_id,
                entity_type="character",
                name="候选人物",
                status="canonical",
            )
        )
        db.add(
            CoreEntity(
                id=foreign_character_id,
                novel_id=foreign_id,
                entity_type="character",
                name="他人对象",
                status="canonical",
            )
        )
        await db.commit()

    async with XhrAsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        read = await client.post(
            "/api/assistant/operation-http/evidence/object-dossier-brief",
            params={"novel_id": str(novel_id)},
            json={
                "arguments": {
                    "scene_id": str(scene_id),
                    "entity_ids": [str(character_id)],
                }
            },
        )
        denied = await client.post(
            "/api/assistant/operation-http/evidence/object-dossier-brief",
            params={"novel_id": str(foreign_id)},
            json={
                "arguments": {
                    "scene_id": str(scene_id),
                    "entity_ids": [str(character_id)],
                }
            },
        )
        foreign_entity = await client.post(
            "/api/assistant/operation-http/evidence/object-dossier-brief",
            params={"novel_id": str(novel_id)},
            json={
                "arguments": {
                    "scene_id": str(scene_id),
                    "entity_ids": [str(foreign_character_id)],
                }
            },
        )
        card = await client.post(
            "/api/assistant/operation-http/previews/story/character-card",
            params={"novel_id": str(novel_id)},
            json={
                "arguments": {
                    "scene_id": str(scene_id),
                    "character_id": str(character_id),
                }
            },
        )
        reactions = await client.post(
            "/api/assistant/operation-http/previews/story/reactions",
            params={"novel_id": str(novel_id)},
            json={
                "arguments": {
                    "scene_id": str(scene_id),
                    "character_ids": [str(character_id)],
                }
            },
        )
    assert read.status_code == 200, read.text
    assert denied.status_code == 404, denied.text
    assert foreign_entity.status_code == 404, foreign_entity.text
    assert card.status_code == 200, card.text
    assert reactions.status_code == 200, reactions.text
    assert card.json()["preview"]["context_confirmation_id"] is None
    assert reactions.json()["preview"]["context_confirmation_id"] is None

    async with manager.session_factory() as db:
        traces = (await db.scalars(select(AssistantOperationTrace))).all()
        salts = (await db.scalars(select(AssistantOperationTraceProjectSalt))).all()
        tasks = (
            await db.scalars(select(AsyncTask).where(AsyncTask.novel_id == novel_id))
        ).all()
    assert not tasks
    assert not [item for item in traces if item.novel_id == foreign_id]
    assert not [item for item in salts if item.novel_id == foreign_id]
    assert {
        (item.op_id, item.event_type) for item in traces if item.novel_id == novel_id
    } >= {
        ("evidence.object_dossier_brief.read", "executed"),
        ("story.character_card.generate", "previewed"),
        ("story.reaction.generate", "previewed"),
    }
