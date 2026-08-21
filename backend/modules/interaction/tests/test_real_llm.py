"""Explicit DeepSeek acceptance for the account-to-RP generation path."""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.tasks.models import AsyncTask
from modules.account.settings_service import SettingsService
from modules.interaction.framing import META_END, META_START
from modules.interaction.models import (
    InteractionGenerationAttempt,
    InteractionMessageNode,
)
from modules.interaction.schemas import JourneyCreateRequest
from modules.interaction.services import InteractionService
from modules.interaction.tasks import handle_interaction_story_generate

pytestmark = [
    pytest.mark.real_llm,
    pytest.mark.skipif(
        os.getenv("RUN_INTERACTION_REAL_LLM") != "1"
        or not os.getenv("DEEPSEEK_API_KEY"),
        reason=(
            "requires RUN_INTERACTION_REAL_LLM=1 and a temporary "
            "DEEPSEEK_API_KEY process variable"
        ),
    ),
]


async def test_deepseek_account_connection_generates_persisted_rp_opening(
    db_session: AsyncSession,
) -> None:
    """Validate the real first-release provider through the complete RP seam."""
    await SettingsService().connect_account_llm_provider(
        db_session,
        "deepseek",
        os.environ["DEEPSEEK_API_KEY"],
    )
    created = await InteractionService().create_journey(
        db_session,
        JourneyCreateRequest(
            opening_text=(
                "进入一个原创的雾港幻想世界。我是一名刚抵达港口的年轻修表师，"
                "随身只有一封没有署名的委托信。请用约四百字直接开始故事。"
            ),
            action_options_enabled=False,
            see_sea_enabled=False,
            idempotency_key=f"real-deepseek-rp-{uuid.uuid4()}",
        ),
    )
    task = await db_session.get(AsyncTask, uuid.UUID(created.attempt.task_id))
    assert task is not None
    task.mark_running()
    await db_session.flush()

    # Production passes a detached claimed task into a fenced handler session.
    # Match that lifecycle so handler commits cannot expire the task envelope.
    db_session.expunge(task)
    db_session.task_checkpoint_enabled = True  # type: ignore[attr-defined]
    result = await handle_interaction_story_generate(db_session, task)

    attempt = (
        await db_session.execute(
            select(InteractionGenerationAttempt).where(
                InteractionGenerationAttempt.id
                == uuid.UUID(created.attempt.id)
            )
        )
    ).scalar_one()
    assert result["status"] == "completed"
    assert attempt.status == "completed"
    assert attempt.result_node_id is not None
    node = await db_session.get(InteractionMessageNode, attempt.result_node_id)
    assert node is not None
    assert node.role == "assistant"
    assert node.message_kind == "story"
    assert node.completion_state == "complete"
    assert len(node.content.strip()) >= 80
    assert META_START not in node.content
    assert META_END not in node.content
