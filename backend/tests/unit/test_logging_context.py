from __future__ import annotations

import asyncio
import uuid
from unittest.mock import MagicMock, patch

import pytest

from core.logging_context import (
    bind_validated_novel_id,
    current_novel_id_for_log,
    novel_id_for_log,
    novel_log_scope,
)


def test_log_scope_binds_only_valid_ids_and_restores_outer_context() -> None:
    outer_id = str(uuid.uuid4())
    inner_id = str(uuid.uuid4())

    assert current_novel_id_for_log() == "<none>"
    assert bind_validated_novel_id(outer_id) is False

    with novel_log_scope():
        assert bind_validated_novel_id(outer_id) is True
        assert current_novel_id_for_log() == outer_id
        with novel_log_scope(inner_id):
            assert current_novel_id_for_log() == inner_id
        assert current_novel_id_for_log() == outer_id

    assert current_novel_id_for_log() == "<none>"


def test_log_scope_does_not_echo_invalid_or_conflicting_ids() -> None:
    first_id = str(uuid.uuid4())
    secret = "private\nproject"

    assert novel_id_for_log(secret) == "<invalid>"
    assert secret not in novel_id_for_log(secret)
    with novel_log_scope():
        assert bind_validated_novel_id(secret) is False
        assert current_novel_id_for_log() == "<none>"
        assert bind_validated_novel_id(first_id) is True
        assert bind_validated_novel_id(uuid.uuid4()) is False
        assert current_novel_id_for_log() == "<multiple>"


def test_novel_id_for_log_does_not_stringify_untrusted_values() -> None:
    class ExplodingValue:
        def __str__(self) -> str:
            raise AssertionError("untrusted values must not be stringified")

    assert novel_id_for_log(ExplodingValue()) == "<invalid>"
    assert novel_id_for_log("a" * 65) == "<invalid>"


def test_log_scope_restores_context_after_exception() -> None:
    novel_id = str(uuid.uuid4())

    with pytest.raises(RuntimeError, match="stop"):
        with novel_log_scope():
            assert bind_validated_novel_id(novel_id) is True
            raise RuntimeError("stop")

    assert current_novel_id_for_log() == "<none>"


@pytest.mark.asyncio
async def test_log_scopes_are_isolated_across_concurrent_tasks() -> None:
    first_id = str(uuid.uuid4())
    second_id = str(uuid.uuid4())
    release = asyncio.Event()
    ready = [asyncio.Event(), asyncio.Event()]

    async def observe(novel_id: str, signal: asyncio.Event) -> str:
        with novel_log_scope():
            assert bind_validated_novel_id(novel_id) is True
            signal.set()
            await release.wait()
            return current_novel_id_for_log()

    tasks = [
        asyncio.create_task(observe(first_id, ready[0])),
        asyncio.create_task(observe(second_id, ready[1])),
    ]
    await asyncio.gather(*(signal.wait() for signal in ready))
    release.set()

    assert await asyncio.gather(*tasks) == [first_id, second_id]
    assert current_novel_id_for_log() == "<none>"


@pytest.mark.asyncio
async def test_log_scope_restores_context_after_cancellation() -> None:
    novel_id = str(uuid.uuid4())
    entered = asyncio.Event()
    observed_after_scope: list[str] = []

    async def wait_forever() -> None:
        try:
            with novel_log_scope():
                assert bind_validated_novel_id(novel_id) is True
                entered.set()
                await asyncio.Event().wait()
        finally:
            observed_after_scope.append(current_novel_id_for_log())

    task = asyncio.create_task(wait_forever())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert observed_after_scope == ["<none>"]
    assert current_novel_id_for_log() == "<none>"


@pytest.mark.asyncio
async def test_project_facade_binds_only_after_active_project_validation() -> None:
    from core.errors import NotFoundError
    from modules.project import facade

    novel_id = str(uuid.uuid4())
    with novel_log_scope():
        with patch.object(
            facade._service,
            "require_active_project",
            autospec=True,
        ) as guard:
            await facade.require_active_project(object(), novel_id)

        guard.assert_awaited_once()
        assert current_novel_id_for_log() == novel_id

    with novel_log_scope():
        with patch.object(
            facade._service,
            "require_active_project",
            autospec=True,
            side_effect=NotFoundError("missing"),
        ):
            with pytest.raises(NotFoundError):
                await facade.require_active_project(object(), novel_id)

        assert current_novel_id_for_log() == "<none>"


@pytest.mark.asyncio
async def test_project_context_lookup_binds_only_after_project_is_found() -> None:
    from modules.project import facade

    novel_id = str(uuid.uuid4())
    project_context = MagicMock(settings={})

    with novel_log_scope():
        with patch.object(
            facade._service,
            "get_project_context",
            autospec=True,
            return_value=project_context,
        ):
            assert await facade.get_project_context(object(), novel_id) is project_context
        assert current_novel_id_for_log() == novel_id

    with novel_log_scope():
        with patch.object(
            facade._service,
            "get_project_context",
            autospec=True,
            return_value=None,
        ):
            assert await facade.get_project_context(object(), novel_id) is None
        assert current_novel_id_for_log() == "<none>"
