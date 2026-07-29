from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import get_args
from unittest.mock import patch

import pytest

from modules.interaction import api
from modules.interaction.streaming import stream_attempt_events

pytestmark = pytest.mark.asyncio


class _Result:
    def __init__(self, row) -> None:
        self._row = row

    def one_or_none(self):
        return self._row


class _Session:
    def __init__(self, row) -> None:
        self._row = row

    async def execute(self, _statement):
        return _Result(self._row)


class _SessionContext:
    def __init__(self, row) -> None:
        self._session = _Session(row)

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *_args):
        return False


class _Manager:
    def __init__(self, row) -> None:
        self._row = row

    def session_factory(self):
        return _SessionContext(self._row)


def _row(*, text: str, status: str = "completed"):
    return SimpleNamespace(
        visible_text=text,
        visible_offset=len(text),
        status=status,
        finish_reason="stop",
        error_kind=None,
        error_message=None,
        result_node_id=uuid.uuid4(),
    )


async def _collect(*, row, offset: int) -> list[str]:
    with patch(
        "modules.interaction.streaming.get_manager",
        autospec=True,
        return_value=_Manager(row),
    ):
        return [
            event
            async for event in stream_attempt_events(
                owner_id=uuid.uuid4(),
                journey_id=uuid.uuid4(),
                attempt_id=uuid.uuid4(),
                offset=offset,
            )
        ]


async def test_stream_emits_persisted_chunk_status_and_done() -> None:
    events = await _collect(row=_row(text="雾中的钟声"), offset=0)

    assert [event.splitlines()[1] for event in events] == [
        "event: chunk",
        "event: status",
        "event: done",
    ]
    assert '"text":"雾中的钟声"' in events[0]
    assert events[0].startswith(f"id: {len('雾中的钟声')}\n")


async def test_stream_reconnect_resumes_from_persisted_offset() -> None:
    events = await _collect(row=_row(text="abcdef"), offset=2)

    assert '"text":"cdef"' in events[0]
    assert events[0].startswith("id: 6\n")
    assert "event: reset" not in "".join(events)


async def test_stream_offset_ahead_resets_then_replays() -> None:
    events = await _collect(row=_row(text="正文"), offset=99)

    assert events[0] == 'event: reset\ndata: {"offset":0}\n\n'
    assert '"text":"正文"' in events[1]
    assert "event: done" in events[-1]


async def test_stream_missing_attempt_returns_safe_not_found() -> None:
    events = await _collect(row=None, offset=0)

    assert events == ['event: error\ndata: {"code":"not_found"}\n\n']


async def test_stream_route_prefers_last_event_id_and_uses_function_db_scope() -> None:
    captured = {}

    async def event_source(**kwargs):
        captured.update(kwargs)
        yield "event: done\ndata: {}\n\n"

    journey_id = uuid.uuid4()
    attempt_id = uuid.uuid4()
    owner_id = uuid.uuid4()
    request = SimpleNamespace(headers={"last-event-id": "8"})
    with (
        patch.object(
            api._service,
            "get_attempt_state",
            autospec=True,
            return_value=SimpleNamespace(),
        ),
        patch(
            "modules.interaction.api.current_account_id",
            autospec=True,
            return_value=owner_id,
        ),
        patch(
            "modules.interaction.api.stream_attempt_events",
            autospec=True,
            side_effect=event_source,
        ),
    ):
        response = await api.stream_attempt(
            request,
            object(),
            str(journey_id),
            str(attempt_id),
            offset=3,
        )
        chunks = [chunk async for chunk in response.body_iterator]
        body = "".join(
            chunk.decode() if isinstance(chunk, bytes) else chunk
            for chunk in chunks
        )

    dependency = get_args(api.StreamDbSession)[1]
    assert dependency.scope == "function"
    assert captured == {
        "owner_id": owner_id,
        "journey_id": journey_id,
        "attempt_id": attempt_id,
        "offset": 8,
    }
    assert "event: done" in body
    assert response.headers["cache-control"] == "no-cache, no-transform"
