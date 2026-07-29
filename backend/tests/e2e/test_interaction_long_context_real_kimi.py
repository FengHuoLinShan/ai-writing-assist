"""Paid Kimi tokenizer calibration and real PostgreSQL long-journey gate."""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.llm.schemas import LLMCallRequest, LLMMessage
from infrastructure.tasks.models import AsyncTask
from modules.account.facade import current_account_id
from modules.interaction.framing import META_END, META_START
from modules.interaction.models import (
    InteractionGenerationAttempt,
    InteractionJourney,
    InteractionMessageNode,
    InteractionSummarySegment,
)
from modules.interaction.prompts import (
    STORY_OUTPUT_TOKENS,
    estimate_input_tokens,
)
from modules.interaction.repositories import InteractionRepository
from modules.interaction.services import (
    InteractionService,
    estimate_story_tokens,
    path_hash,
)
from modules.interaction.tasks import handle_interaction_story_generate
from modules.project.facade import (
    build_project_llm_execution_snapshot,
    create_interaction_project,
    open_project_llm_client,
)
from modules.settings.services import SettingsService

_CALIBRATION_TARGETS = (
    16_000,
    128_000,
    240_000,
    270_000,
    500_000,
    530_000,
    730_000,
)
_MIXED_PROSE = (
    "雾港的钟声越过石桥，记录员写下第17号线索；"
    "Mara问：“你亲眼看见了吗？”守门人只确认事实，不补全传闻。"
    "潮汐表显示03:40，旧齿轮上刻着A-19。🌫️ "
)
_UNSELECTED_SENTINEL = "UNSELECTED_SIBLING_MUST_NEVER_ENTER_KIMI_CONTEXT"
_REQUIRED_ENV = (
    os.getenv("RUN_INTERACTION_LONG_CONTEXT_CALIBRATION") == "1"
    and os.getenv("KIMI_LONG_CONTEXT_COST_APPROVED") == "1"
    and os.getenv("ENABLE_ACCOUNT_KIMI_K3") == "1"
    and bool(os.getenv("KIMI_API_KEY"))
    and bool(os.getenv("KIMI_CONTEXT_LIMIT_TOKENS"))
)

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.real_llm,
    pytest.mark.skipif(
        not _REQUIRED_ENV,
        reason=(
            "requires the explicit long-context run flag, cost approval, "
            "Kimi K3 enable flag, KIMI_API_KEY, and "
            "KIMI_CONTEXT_LIMIT_TOKENS"
        ),
    ),
]


def _context_limit() -> int:
    try:
        value = int(os.environ["KIMI_CONTEXT_LIMIT_TOKENS"])
    except (KeyError, TypeError, ValueError):
        pytest.fail("KIMI_CONTEXT_LIMIT_TOKENS must be an integer")
    if value < 900_000:
        pytest.fail("the declared Kimi context limit cannot exercise the 730K gate")
    return value


def _mixed_content(length: int) -> str:
    repeats, remainder = divmod(max(0, length), len(_MIXED_PROSE))
    return (_MIXED_PROSE * repeats) + _MIXED_PROSE[:remainder]


def _messages_for_estimate(target: int) -> list[LLMMessage]:
    system = LLMMessage(role="system", content="只回复“好”。不要解释。")
    empty = [system, LLMMessage(role="user", content="")]
    fixed = estimate_input_tokens(empty)
    content = _mixed_content(max(1, target - fixed))
    messages = [system, LLMMessage(role="user", content=content)]
    assert estimate_input_tokens(messages) == target
    return messages


def _write_calibration_report(payload: dict) -> None:
    artifact_dir = Path(".test-artifacts")
    artifact_dir.mkdir(parents=True, exist_ok=True)
    target = artifact_dir / "kimi-context-calibration.json"
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


async def _run_story_task(
    db: AsyncSession,
    *,
    task_id: uuid.UUID,
) -> dict:
    task = await db.get(AsyncTask, task_id)
    assert task is not None
    task.mark_running()
    await db.flush()
    db.expunge(task)
    db.task_checkpoint_enabled = True  # type: ignore[attr-defined]
    return await handle_interaction_story_generate(db, task)


async def test_kimi_reported_prompt_tokens_fit_the_budget_envelope(
    db_session: AsyncSession,
) -> None:
    """Use provider usage, never tiktoken, as the Kimi calibration truth."""

    context_limit = _context_limit()
    await SettingsService().connect_account_llm_provider(
        db_session,
        "kimi",
        os.environ["KIMI_API_KEY"],
    )
    project = await create_interaction_project(
        db_session,
        title="Kimi 长上下文 tokenizer 校准",
    )
    samples = []
    async with open_project_llm_client(
        db_session,
        project.novel_id,
    ) as client:
        for target in _CALIBRATION_TARGETS:
            messages = _messages_for_estimate(target)
            request = LLMCallRequest(
                model="kimi-k3",
                messages=messages,
                temperature=0,
                max_tokens=8,
            )
            # This paid calibration must not inherit LLMClient retries. The
            # account/project facade still owns provider, model and secret
            # resolution; only the test invokes the resolved provider once.
            response = await client._provider.generate(request)  # noqa: SLF001
            actual = int(response.usage.prompt_tokens or 0)
            if actual <= 0:
                pytest.fail("Kimi did not return exact prompt token usage")
            estimated = estimate_input_tokens(messages)
            safety_ceiling = int(context_limit * 0.90)
            assert actual + STORY_OUTPUT_TOKENS <= safety_ceiling
            assert estimated <= int(actual * 1.50)
            samples.append(
                {
                    "target_estimate": target,
                    "estimated_input_tokens": estimated,
                    "provider_prompt_tokens": actual,
                    "provider_completion_tokens": int(
                        response.usage.completion_tokens or 0
                    ),
                    "provider_total_tokens": int(response.usage.total_tokens or 0),
                    "latency_ms": response.latency_ms,
                    "model": response.model or "kimi-k3",
                }
            )

    assert samples[-1]["target_estimate"] == 730_000
    assert samples[-1]["provider_prompt_tokens"] + STORY_OUTPUT_TOKENS <= 900_000
    _write_calibration_report(
        {
            "provider": "kimi",
            "model": "kimi-k3",
            "official_context_limit_tokens": context_limit,
            "content_recorded": False,
            "samples": samples,
        }
    )


async def test_kimi_emergency_summary_resumes_seeded_530k_postgresql_journey(
    db_session: AsyncSession,
) -> None:
    """Prove the real 530K summary→story path without sending an unselected sibling."""

    await SettingsService().connect_account_llm_provider(
        db_session,
        "kimi",
        os.environ["KIMI_API_KEY"],
    )
    project = await create_interaction_project(
        db_session,
        title="Kimi 530K 紧急整理",
    )
    owner_id = current_account_id()
    journey = InteractionJourney(
        novel_id=uuid.UUID(project.novel_id),
        owner_id=owner_id,
        title="Kimi 530K 紧急整理",
        title_source="manual",
        opening_text="长旅程校准",
        status="active",
        see_sea_enabled=False,
        action_options_enabled=False,
        selection_epoch=0,
        overview_epoch=0,
        latest_activity_at=datetime.now(UTC),
    )
    db_session.add(journey)
    await db_session.flush()

    path_nodes: list[InteractionMessageNode] = []
    parent_id = None
    total_chars = 530_000
    node_count = 6
    base_chars, remainder = divmod(total_chars, node_count)
    repository = InteractionRepository()
    for index in range(node_count):
        content_length = base_chars + (1 if index < remainder else 0)
        content = _mixed_content(content_length)
        node = InteractionMessageNode(
            novel_id=journey.novel_id,
            journey_id=journey.id,
            parent_node_id=parent_id,
            role="user" if index % 2 == 0 else "assistant",
            message_kind="setup" if index == 0 else "story",
            content=content,
            completion_state="complete",
            end_reason="stop" if index % 2 else None,
            token_estimate=estimate_story_tokens(content),
        )
        db_session.add(node)
        await db_session.flush()
        await repository.set_selected_child(
            db_session,
            journey=journey,
            parent_node_id=parent_id,
            child_node_id=node.id,
        )
        path_nodes.append(node)
        parent_id = node.id

    branch_parent = path_nodes[2]
    unselected = InteractionMessageNode(
        novel_id=journey.novel_id,
        journey_id=journey.id,
        parent_node_id=branch_parent.id,
        role="assistant",
        message_kind="story",
        content=_UNSELECTED_SENTINEL,
        completion_state="complete",
        end_reason="stop",
        token_estimate=estimate_story_tokens(_UNSELECTED_SENTINEL),
    )
    db_session.add(unselected)
    journey.selected_leaf_node_id = path_nodes[-1].id
    await db_session.flush()

    selected_path = await repository.get_selected_path(
        db_session,
        journey=journey,
    )
    assert [node.id for node in selected_path] == [node.id for node in path_nodes]
    assert _UNSELECTED_SENTINEL not in "\n".join(node.content for node in selected_path)

    snapshot = await build_project_llm_execution_snapshot(
        db_session,
        str(journey.novel_id),
    )
    service = InteractionService(repository)
    attempt = await service._create_attempt(  # noqa: SLF001
        db_session,
        journey=journey,
        response_to=path_nodes[-1],
        context_nodes=path_nodes,
        idempotency_key=f"real-kimi-530k-{uuid.uuid4()}",
        request_kind="message",
        llm_execution_snapshot=snapshot,
    )
    task = await db_session.get(AsyncTask, attempt.task_id)
    assert task is not None
    serialized_task = json.dumps(task.meta, ensure_ascii=False, default=str)
    assert os.environ["KIMI_API_KEY"] not in serialized_task
    assert attempt.context_path_hash == path_hash(path_nodes)
    assert attempt.context_node_ids == [str(path_nodes[-1].id)]

    result = await _run_story_task(
        db_session,
        task_id=attempt.task_id,
    )
    assert result["status"] in {"completed", "stopped"}
    refreshed = await db_session.get(InteractionGenerationAttempt, attempt.id)
    assert refreshed is not None
    assert refreshed.status in {"completed", "stopped"}
    assert refreshed.usage["context_tier"] == "emergency_summary"
    assert int(refreshed.usage["estimated_input_tokens"]) > 512_000
    assert refreshed.result_node_id is not None
    story = await db_session.get(
        InteractionMessageNode,
        refreshed.result_node_id,
    )
    assert story is not None
    assert story.content.strip()
    assert _UNSELECTED_SENTINEL not in story.content
    assert META_START not in story.content
    assert META_END not in story.content

    segment = (
        await db_session.execute(
            select(InteractionSummarySegment).where(
                InteractionSummarySegment.journey_id == journey.id
            )
        )
    ).scalar_one()
    assert segment.ordinal == 1
    assert segment.producer["provider_id"] == "kimi"
    assert segment.producer["model"] == "kimi-k3"
    assert segment.producer["call_attempts"] == 1
    assert _UNSELECTED_SENTINEL not in segment.content
