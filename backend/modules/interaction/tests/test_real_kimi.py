"""Explicit paid Kimi K3 compatibility gate for the complete RP seam."""

from __future__ import annotations

import json
import os
import uuid
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.tasks.models import AsyncTask
from modules.account.settings_models import AccountLLMCredential
from modules.account.settings_service import SettingsService
from modules.interaction.framing import META_END, META_START
from modules.interaction.models import (
    InteractionGenerationAttempt,
    InteractionJourney,
    InteractionMessageNode,
)
from modules.interaction.repositories import InteractionRepository
from modules.interaction.schemas import (
    InteractionOverviewSections,
    JourneyCreateRequest,
)
from modules.interaction.services import InteractionService, path_hash
from modules.interaction.streaming import stream_attempt_events
from modules.interaction.tasks import (
    handle_interaction_story_generate,
    handle_interaction_summary_refresh,
)
from modules.project.contracts import ProjectLLMConfigurationError

_REQUIRED_ENV = (
    os.getenv("RUN_INTERACTION_REAL_KIMI") == "1"
    and os.getenv("ENABLE_ACCOUNT_KIMI_K3") == "1"
    and bool(os.getenv("KIMI_API_KEY"))
    and bool(os.getenv("DEEPSEEK_API_KEY"))
)

pytestmark = [
    pytest.mark.real_llm,
    pytest.mark.skipif(
        not _REQUIRED_ENV,
        reason=(
            "requires RUN_INTERACTION_REAL_KIMI=1, "
            "ENABLE_ACCOUNT_KIMI_K3=1, and temporary KIMI_API_KEY / "
            "DEEPSEEK_API_KEY process variables"
        ),
    ),
]


class _BorrowedSessionContext:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def __aenter__(self) -> AsyncSession:
        return self._db

    async def __aexit__(self, *_args) -> bool:
        return False


class _BorrowedManager:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    def session_factory(self) -> _BorrowedSessionContext:
        return _BorrowedSessionContext(self._db)


def _assert_secret_free(value: object, *secrets: str) -> None:
    serialized = json.dumps(value, ensure_ascii=False, default=str)
    if any(secret and secret in serialized for secret in secrets):
        pytest.fail("real-model gate found a plaintext API key in persisted metadata")


async def _run_story_task(
    db: AsyncSession,
    *,
    task_id: str,
) -> dict:
    task = await db.get(AsyncTask, uuid.UUID(task_id))
    assert task is not None
    task.mark_running()
    await db.flush()
    db.expunge(task)
    db.task_checkpoint_enabled = True  # type: ignore[attr-defined]
    return await handle_interaction_story_generate(db, task)


async def _run_summary_task(
    db: AsyncSession,
    *,
    task_id: str,
) -> dict:
    task = await db.get(AsyncTask, uuid.UUID(task_id))
    assert task is not None
    task.mark_running()
    await db.flush()
    db.expunge(task)
    db.task_checkpoint_enabled = True  # type: ignore[attr-defined]
    return await handle_interaction_summary_refresh(db, task)


async def _attempt(
    db: AsyncSession,
    attempt_id: str,
) -> InteractionGenerationAttempt:
    value = await db.get(InteractionGenerationAttempt, uuid.UUID(attempt_id))
    assert value is not None
    return value


async def _story_node(
    db: AsyncSession,
    result: dict,
) -> InteractionMessageNode:
    node_id = result.get("node_id")
    assert node_id
    node = await db.get(InteractionMessageNode, uuid.UUID(str(node_id)))
    assert node is not None
    assert node.role == "assistant"
    assert node.message_kind == "story"
    assert node.completion_state in {"complete", "partial"}
    assert node.content.strip()
    assert META_START not in node.content
    assert META_END not in node.content
    return node


async def _persisted_sse_events(
    db: AsyncSession,
    *,
    journey: InteractionJourney,
    attempt: InteractionGenerationAttempt,
    offset: int,
) -> list[str]:
    with patch(
        "modules.interaction.streaming.get_manager",
        autospec=True,
        return_value=_BorrowedManager(db),
    ):
        return [
            event
            async for event in stream_attempt_events(
                owner_id=journey.owner_id,
                journey_id=journey.id,
                attempt_id=attempt.id,
                offset=offset,
            )
        ]


async def test_kimi_k3_multiturn_branch_summary_and_hot_switch_gate(
    db_session: AsyncSession,
) -> None:
    """Prove the paid Kimi template without weakening its default-off gate."""

    kimi_key = os.environ["KIMI_API_KEY"]
    deepseek_key = os.environ["DEEPSEEK_API_KEY"]
    settings = SettingsService()
    interaction = InteractionService()

    with pytest.raises(ValueError):
        await settings.connect_account_llm_provider(
            db_session,
            "kimi",
            "invalid-kimi-key-for-real-gate",
        )
    invalid_row = (
        await db_session.execute(
            select(AccountLLMCredential).where(AccountLLMCredential.provider_id == "kimi")
        )
    ).scalar_one_or_none()
    assert invalid_row is None

    await settings.connect_account_llm_provider(
        db_session,
        "deepseek",
        deepseek_key,
    )
    created = await interaction.create_journey(
        db_session,
        JourneyCreateRequest(
            opening_text=(
                "进入一个原创雾港幻想世界。我是一名追查失踪钟表匠的年轻信使，"
                "请直接开始一段约四百字、可以继续发展的故事。"
            ),
            action_options_enabled=True,
            see_sea_enabled=False,
            idempotency_key=f"real-kimi-opening-{uuid.uuid4()}",
        ),
    )
    assert created.attempt is not None
    deepseek_result = await _run_story_task(
        db_session,
        task_id=created.attempt.task_id,
    )
    deepseek_node = await _story_node(db_session, deepseek_result)
    deepseek_attempt = await _attempt(db_session, created.attempt.id)
    assert deepseek_attempt.llm_execution_snapshot["profile"]["provider_id"] == (
        "deepseek"
    )
    _assert_secret_free(
        deepseek_attempt.llm_execution_snapshot,
        deepseek_key,
        kimi_key,
    )
    deepseek_summary_task_id = deepseek_result.get("summary_task_id")
    assert deepseek_summary_task_id
    deepseek_summary = await _run_summary_task(
        db_session,
        task_id=str(deepseek_summary_task_id),
    )
    assert deepseek_summary["status"] == "completed"

    connections = await settings.connect_account_llm_provider(
        db_session,
        "kimi",
        kimi_key,
    )
    assert connections.active_provider_id == "kimi"
    kimi_state = next(
        item for item in connections.providers if item.provider_id == "kimi"
    )
    assert kimi_state.connected is True
    assert kimi_state.model == "kimi-k3"

    balances = await settings.get_account_llm_balances(db_session)
    kimi_balance = next(item for item in balances.items if item.provider_id == "kimi")
    assert kimi_balance.status in {"available", "unavailable"}
    if kimi_balance.status == "available":
        assert kimi_balance.amount is not None
        assert kimi_balance.currency == "CNY"
    else:
        assert kimi_balance.amount is None
        assert kimi_balance.currency is None

    journey = await db_session.get(
        InteractionJourney,
        uuid.UUID(created.journey.id),
    )
    assert journey is not None
    first_kimi = await interaction.send_message(
        db_session,
        journey_id=str(journey.id),
        content="我检查旧信封上的蜡印，并询问守门人昨夜是否听见钟声。",
        expected_selection_epoch=journey.selection_epoch,
        idempotency_key=f"real-kimi-turn-a-{uuid.uuid4()}",
    )
    assert first_kimi.attempt is not None
    first_kimi_result = await _run_story_task(
        db_session,
        task_id=first_kimi.attempt.task_id,
    )
    first_kimi_node = await _story_node(db_session, first_kimi_result)
    first_kimi_attempt = await _attempt(db_session, first_kimi.attempt.id)
    assert first_kimi_attempt.llm_execution_snapshot["profile"]["provider_id"] == ("kimi")

    journey = await db_session.get(InteractionJourney, journey.id)
    assert journey is not None
    full_events = await _persisted_sse_events(
        db_session,
        journey=journey,
        attempt=first_kimi_attempt,
        offset=0,
    )
    assert "event: chunk" in full_events[0]
    assert any("event: done" in event for event in full_events[1:])
    resume_offset = first_kimi_attempt.visible_offset // 2
    resumed_events = await _persisted_sse_events(
        db_session,
        journey=journey,
        attempt=first_kimi_attempt,
        offset=resume_offset,
    )
    assert "event: chunk" in resumed_events[0]
    resumed_payload = json.loads(
        next(
            line.removeprefix("data: ")
            for line in resumed_events[0].splitlines()
            if line.startswith("data: ")
        )
    )
    assert resumed_payload["offset"] == first_kimi_attempt.visible_offset
    assert len(resumed_payload["text"]) == (
        first_kimi_attempt.visible_offset - resume_offset
    )

    regenerated = await interaction.regenerate(
        db_session,
        journey_id=str(journey.id),
        assistant_node_id=str(first_kimi_node.id),
        expected_selection_epoch=journey.selection_epoch,
        idempotency_key=f"real-kimi-regenerate-{uuid.uuid4()}",
    )
    assert regenerated.attempt is not None
    regenerated_result = await _run_story_task(
        db_session,
        task_id=regenerated.attempt.task_id,
    )
    regenerated_node = await _story_node(db_session, regenerated_result)
    assert regenerated_node.id != first_kimi_node.id

    journey = await db_session.get(InteractionJourney, journey.id)
    assert journey is not None
    await interaction.select_branch(
        db_session,
        journey_id=str(journey.id),
        node_id=str(first_kimi_node.id),
        expected_selection_epoch=journey.selection_epoch,
    )
    journey = await db_session.get(InteractionJourney, journey.id)
    assert journey is not None
    long_user_text = (
        "我明确选择先前那条钟楼分支，并逐项核对信使日志。"
        "守门人只确认自己亲眼见到的事实，不把传闻当成真相。"
    ) * 480
    third_kimi = await interaction.send_message(
        db_session,
        journey_id=str(journey.id),
        content=long_user_text,
        expected_selection_epoch=journey.selection_epoch,
        idempotency_key=f"real-kimi-turn-c-{uuid.uuid4()}",
    )
    assert third_kimi.attempt is not None
    third_attempt = await _attempt(db_session, third_kimi.attempt.id)
    selected_path = await InteractionRepository().get_selected_path(
        db_session,
        journey=journey,
    )
    assert regenerated_node.id not in {node.id for node in selected_path}
    assert first_kimi_node.id in {node.id for node in selected_path}
    assert third_attempt.context_node_ids == [str(selected_path[-1].id)]
    assert third_attempt.context_path_hash == path_hash(selected_path)
    assert str(regenerated_node.id) not in third_attempt.reference_node_ids
    third_task = await db_session.get(AsyncTask, third_attempt.task_id)
    assert third_task is not None
    _assert_secret_free(
        {
            "attempt": third_attempt.llm_execution_snapshot,
            "task": third_task.meta,
        },
        deepseek_key,
        kimi_key,
    )

    third_result = await _run_story_task(
        db_session,
        task_id=third_kimi.attempt.task_id,
    )
    third_node = await _story_node(db_session, third_result)
    assert third_node.id != regenerated_node.id
    kimi_nodes = [first_kimi_node, regenerated_node, third_node]
    if not any(node.action_suggestions for node in kimi_nodes):
        pytest.fail("Kimi K3 did not produce a valid hidden metadata tail")

    kimi_summary_task_id = third_result.get("summary_task_id")
    assert kimi_summary_task_id
    kimi_summary = await _run_summary_task(
        db_session,
        task_id=str(kimi_summary_task_id),
    )
    assert kimi_summary["status"] == "completed"
    overview = await interaction.get_overview(
        db_session,
        journey_id=str(journey.id),
    )
    assert overview.status == "ready"
    assert overview.source == "automatic"
    assert overview.sections.has_content()
    assert overview.base_revision_id
    assert overview.base_selected_leaf_node_id
    assert overview.base_selected_path_hash

    journey = await db_session.get(InteractionJourney, journey.id)
    assert journey is not None
    manual_sections = overview.sections.model_copy(
        update={
            "current_situation": (
                overview.sections.current_situation
                + "\n用户确认：蜡印线索优先于未经证实的传闻。"
            ).strip()
        }
    )
    manual = await interaction.update_overview(
        db_session,
        journey_id=str(journey.id),
        sections=InteractionOverviewSections.model_validate(manual_sections),
        expected_overview_epoch=overview.overview_epoch,
        expected_selection_epoch=journey.selection_epoch,
        base_revision_id=overview.base_revision_id,
        base_selected_leaf_node_id=overview.base_selected_leaf_node_id,
        base_selected_path_hash=overview.base_selected_path_hash,
    )
    assert manual.source == "manual"
    assert "蜡印线索优先" in manual.sections.current_situation

    journey = await db_session.get(InteractionJourney, journey.id)
    assert journey is not None
    pending_after_clear = await interaction.send_message(
        db_session,
        journey_id=str(journey.id),
        content="我带着已经确认的线索返回港口档案室。",
        expected_selection_epoch=journey.selection_epoch,
        idempotency_key=f"real-kimi-clear-key-{uuid.uuid4()}",
    )
    assert pending_after_clear.attempt is not None
    pending_attempt = await _attempt(
        db_session,
        pending_after_clear.attempt.id,
    )
    assert pending_attempt.llm_execution_snapshot["profile"]["provider_id"] == "kimi"
    await settings.clear_account_llm_provider(db_session, "kimi")
    with pytest.raises(ProjectLLMConfigurationError):
        await _run_story_task(
            db_session,
            task_id=pending_after_clear.attempt.task_id,
        )
    failed_attempt = await _attempt(
        db_session,
        pending_after_clear.attempt.id,
    )
    assert failed_attempt.status == "failed"
    assert failed_attempt.result_node_id is None
    assert failed_attempt.llm_execution_snapshot["profile"]["provider_id"] == "kimi"

    final_connections = await settings.get_account_llm_connections(db_session)
    assert final_connections.active_provider_id == "kimi"
    assert (
        next(
            item for item in final_connections.providers if item.provider_id == "deepseek"
        ).connected
        is True
    )
    assert (
        next(
            item for item in final_connections.providers if item.provider_id == "kimi"
        ).connected
        is False
    )
    failed_task = await db_session.get(AsyncTask, failed_attempt.task_id)
    assert failed_task is not None
    _assert_secret_free(
        {
            "snapshot": failed_attempt.llm_execution_snapshot,
            "usage": failed_attempt.usage,
            "error": failed_attempt.error_message,
            "task": SimpleNamespace(meta=failed_task.meta),
            "deepseek_story_id": str(deepseek_node.id),
        },
        deepseek_key,
        kimi_key,
    )
