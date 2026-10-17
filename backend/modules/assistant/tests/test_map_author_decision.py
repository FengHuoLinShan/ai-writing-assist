import hashlib
from types import SimpleNamespace
from uuid import uuid4

import pytest

from core.errors import ConflictError
from modules.assistant import map_author_decision_service as service


@pytest.mark.asyncio
async def test_reader_returns_hash_and_identity_for_current_run_author_message(
    monkeypatch,
):
    novel_id, run_id, message_id = uuid4(), uuid4(), uuid4()
    owner_id, session_id, task_id = uuid4(), uuid4(), uuid4()
    project = SimpleNamespace(project_kind="author", owner_id=owner_id)
    run = SimpleNamespace(
        id=run_id,
        owner_id=owner_id,
        mode="author",
        session_id=session_id,
        task_id=task_id,
    )
    message = SimpleNamespace(id=message_id, content="黑港在东海群岛里")

    async def require_active(*_args, **_kwargs):
        return None

    class ReaderDB:
        async def scalar(self, query):
            if "assistant_runs" in str(query):
                return run
            if "world_cocreation_messages" in str(query):
                return message
            raise AssertionError("unexpected lookup")

    reader_db = ReaderDB()

    async def get_project_context(_db, _novel_id):
        return project

    monkeypatch.setattr(service, "require_active_project", require_active)
    monkeypatch.setattr(service, "get_any_project_context", get_project_context)
    decision = await service.read_map_author_decision(
        reader_db, str(novel_id), str(run_id)
    )
    assert decision["origin"] == "assistant"
    assert decision["run_id"] == str(run_id)
    assert decision["message_id"] == str(message_id)
    assert (
        decision["statement_hash"]
        == hashlib.sha256(message.content.encode("utf-8")).hexdigest()
    )


@pytest.mark.asyncio
async def test_reader_rejects_message_outside_the_bound_assistant_turn(monkeypatch):
    novel_id, run_id, message_id = uuid4(), uuid4(), uuid4()
    owner_id = uuid4()
    project = SimpleNamespace(project_kind="author", owner_id=owner_id)
    run = SimpleNamespace(
        id=run_id,
        owner_id=owner_id,
        mode="author",
        session_id=uuid4(),
        task_id=uuid4(),
    )
    message = SimpleNamespace(id=uuid4(), content="另一轮的安排")

    async def require_active(*_args, **_kwargs):
        return None

    async def get_project(*_args, **_kwargs):
        return project

    class ReaderDB:
        async def scalar(self, query):
            if "assistant_runs" in str(query):
                return run
            if "world_cocreation_messages" in str(query):
                return message
            raise AssertionError("unexpected lookup")

    monkeypatch.setattr(service, "require_active_project", require_active)
    monkeypatch.setattr(service, "get_any_project_context", get_project)
    with pytest.raises(ConflictError, match="不属于这次助手运行"):
        await service.read_map_author_decision(
            ReaderDB(), str(novel_id), str(run_id), message_id=str(message_id)
        )
