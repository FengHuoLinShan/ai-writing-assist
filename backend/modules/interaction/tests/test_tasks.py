from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from infrastructure.llm.errors import (
    LLMConnectionError,
    LLMInvalidResponseError,
)
from infrastructure.llm.schemas import LLMMessage, LLMStreamChunk
from modules.interaction import tasks
from modules.interaction.generation import (
    PreparedStoryGeneration,
    PreparedSummaryGeneration,
)
from modules.interaction.schemas import (
    InteractionOverviewSections,
    InteractionSummaryOutput,
)
from modules.project.contracts import ProjectLLMConfigurationError

pytestmark = pytest.mark.asyncio


def _task():
    value = SimpleNamespace(id=uuid.uuid4(), meta={}, progress=0.0)
    value.update_progress = lambda progress: setattr(value, "progress", progress)
    return value


def _summary_prepared() -> PreparedSummaryGeneration:
    return PreparedSummaryGeneration(
        novel_id=str(uuid.uuid4()),
        journey_id=str(uuid.uuid4()),
        path_hash="a" * 64,
        node_ids=[str(uuid.uuid4())],
        segment_node_ids=[str(uuid.uuid4())],
        started_overview_epoch=0,
        messages=[LLMMessage(role="user", content="整理")],
        executable_settings={"llm": {"model": "deepseek-v4-flash"}},
    )


def _summary_output() -> InteractionSummaryOutput:
    return InteractionSummaryOutput(
        segment_summary="本段发生了一次转折。",
        overview=InteractionOverviewSections(current_situation="新的局面。"),
    )


class _StructuredClient:
    def __init__(self, outcomes) -> None:
        self._outcomes = list(outcomes)
        self.calls = 0
        self.closed = False

    async def generate_structured(self, *_args, **_kwargs):
        self.calls += 1
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    async def close(self) -> None:
        self.closed = True


async def test_summary_handler_retries_one_transient_failure() -> None:
    prepared = _summary_prepared()
    output = _summary_output()
    client = _StructuredClient([LLMConnectionError(), output])
    with (
        patch.object(
            tasks._workflow,
            "prepare_summary_task",
            autospec=True,
            return_value=prepared,
        ),
        patch.object(
            tasks._workflow,
            "finalize_summary_task",
            autospec=True,
            return_value={"status": "completed"},
        ) as finalize,
        patch.object(
            tasks._workflow,
            "mark_summary_failed",
            autospec=True,
        ) as mark_failed,
        patch(
            "modules.interaction.tasks.create_project_snapshot_llm_client",
            autospec=True,
            return_value=client,
        ),
        patch(
            "infrastructure.llm.retry.asyncio.sleep",
            autospec=True,
        ),
    ):
        result = await tasks.handle_interaction_summary_refresh(
            object(),
            _task(),
        )

    assert result == {"status": "completed"}
    assert client.calls == 2
    assert client.closed is True
    mark_failed.assert_not_awaited()
    finalize.assert_awaited_once()


async def test_summary_handler_does_not_task_retry_invalid_schema() -> None:
    prepared = _summary_prepared()
    client = _StructuredClient([LLMInvalidResponseError()])
    with (
        patch.object(
            tasks._workflow,
            "prepare_summary_task",
            autospec=True,
            return_value=prepared,
        ),
        patch.object(
            tasks._workflow,
            "mark_summary_failed",
            autospec=True,
        ) as mark_failed,
        patch(
            "modules.interaction.tasks.create_project_snapshot_llm_client",
            autospec=True,
            return_value=client,
        ),
    ):
        with pytest.raises(LLMInvalidResponseError):
            await tasks.handle_interaction_summary_refresh(object(), _task())

    assert client.calls == 1
    assert client.closed is True
    mark_failed.assert_awaited_once()


async def test_summary_prepare_failure_is_latched_for_user_retry() -> None:
    with (
        patch.object(
            tasks._workflow,
            "prepare_summary_task",
            autospec=True,
            side_effect=ProjectLLMConfigurationError("missing key"),
        ),
        patch.object(
            tasks._workflow,
            "mark_summary_task_failed",
            autospec=True,
        ) as mark_failed,
        patch(
            "modules.interaction.tasks.create_project_snapshot_llm_client",
            autospec=True,
        ) as create_client,
    ):
        with pytest.raises(ProjectLLMConfigurationError):
            await tasks.handle_interaction_summary_refresh(object(), _task())

    mark_failed.assert_awaited_once()
    create_client.assert_not_called()


class _StreamingClient:
    def __init__(self) -> None:
        self.closed = False
        self.transport_retries: list[bool] = []

    async def generate_stream(self, _request, *, transport_retries: bool = True):
        self.transport_retries.append(transport_retries)
        yield LLMStreamChunk(content="文" * 600)
        yield LLMStreamChunk(content="结尾", finish_reason="stop")

    async def close(self) -> None:
        self.closed = True


async def test_story_handler_checkpoints_by_size_and_flushes_tail() -> None:
    prepared = PreparedStoryGeneration(
        novel_id=str(uuid.uuid4()),
        journey_id=str(uuid.uuid4()),
        attempt_id=str(uuid.uuid4()),
        request_kind="message",
        messages=[LLMMessage(role="user", content="继续")],
        executable_settings={"llm": {"model": "deepseek-v4-flash"}},
        existing_visible_text="",
    )
    client = _StreamingClient()
    with (
        patch.object(
            tasks._workflow,
            "prepare_story_task",
            autospec=True,
            return_value=prepared,
        ),
        patch.object(
            tasks._workflow,
            "checkpoint_story_task",
            autospec=True,
            return_value=0,
        ) as checkpoint,
        patch.object(
            tasks._workflow,
            "finalize_story_task",
            autospec=True,
            return_value={"status": "completed"},
        ) as finalize,
        patch(
            "modules.interaction.tasks.create_project_snapshot_llm_client",
            autospec=True,
            return_value=client,
        ),
    ):
        result = await tasks.handle_interaction_story_generate(
            object(),
            _task(),
        )

    assert result == {"status": "completed"}
    assert checkpoint.await_count == 2
    first_delta = checkpoint.await_args_list[0].kwargs["visible_delta"]
    second_delta = checkpoint.await_args_list[1].kwargs["visible_delta"]
    assert len(first_delta) >= 512
    assert first_delta + second_delta == "文" * 600 + "结尾"
    finalize.assert_awaited_once()
    assert client.closed is True
    assert client.transport_retries == [False]
