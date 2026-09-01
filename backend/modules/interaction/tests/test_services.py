from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import func, select

from core.errors import ConflictError, NotFoundError
from infrastructure.llm.capabilities import (
    LLM_CAPABILITY_SNAPSHOT_KEY,
    resolve_llm_capability_profile,
)
from infrastructure.llm.errors import LLMContentFilterError
from infrastructure.llm.schemas import LLMMessage
from infrastructure.tasks.models import AsyncTask
from modules.interaction.generation import (
    InteractionContextBudgetError,
    InteractionGenerationWorkflow,
    PreparedStoryGeneration,
    PreparedSummaryGeneration,
    _source_retrieval_query,
    story_request,
    summary_request,
)
from modules.interaction.models import (
    InteractionGenerationAttempt,
    InteractionJourney,
    InteractionMessageNode,
    InteractionOverviewRevision,
    InteractionSummarySegment,
)
from modules.interaction.prompts import compile_story_messages, render_overview_sections
from modules.interaction.schemas import (
    InteractionActionSuggestion,
    InteractionOverviewSections,
    InteractionResponseMetadata,
    InteractionSummaryOutput,
    JourneyCreateRequest,
)
from modules.interaction.services import InteractionService, path_hash
from modules.project.services import ProjectService

pytestmark = pytest.mark.asyncio

_SNAPSHOT = {
    "version": "1",
    "novel_id": "filled-by-test",
    "profile": {"provider_id": "deepseek", "model": "deepseek-v4-flash"},
    LLM_CAPABILITY_SNAPSHOT_KEY: resolve_llm_capability_profile(
        "deepseek",
        "deepseek-v4-flash",
    ).to_snapshot(),
}


def _snapshot_for(novel_id: uuid.UUID) -> dict:
    return {**_SNAPSHOT, "novel_id": str(novel_id)}


def _task_for(journey: InteractionJourney, attempt: InteractionGenerationAttempt):
    task = SimpleNamespace(
        id=attempt.task_id,
        meta={
            "novel_id": str(journey.novel_id),
            "journey_id": str(journey.id),
            "attempt_id": str(attempt.id),
            "llm_execution_snapshot": dict(attempt.llm_execution_snapshot or {}),
        },
        progress=0.0,
    )
    task.update_progress = lambda value: setattr(task, "progress", value)
    return task


async def _create_journey(db_session, *, key: str = "create-journey-0001"):
    service = InteractionService()

    async def snapshot(_db, novel_id: str) -> dict:
        return _snapshot_for(uuid.UUID(novel_id))

    with patch(
        "modules.interaction.services.build_project_llm_execution_snapshot",
        autospec=True,
        side_effect=snapshot,
    ):
        response = await service.create_journey(
            db_session,
            JourneyCreateRequest(
                opening_text="我进入《诡秘之主》的廷根，身份是一名刚入职的记者。",
                idempotency_key=key,
            ),
        )
    journey = (
        await db_session.execute(
            select(InteractionJourney).where(
                InteractionJourney.id == uuid.UUID(response.journey.id)
            )
        )
    ).scalar_one()
    attempt = (
        await db_session.execute(
            select(InteractionGenerationAttempt).where(
                InteractionGenerationAttempt.id == uuid.UUID(response.attempt.id)
            )
        )
    ).scalar_one()
    return service, journey, attempt, response


async def _append_selected_node(
    db_session,
    service: InteractionService,
    journey: InteractionJourney,
    *,
    parent: InteractionMessageNode,
    role: str,
    content: str,
    completion_state: str = "complete",
) -> InteractionMessageNode:
    node = InteractionMessageNode(
        novel_id=journey.novel_id,
        journey_id=journey.id,
        parent_node_id=parent.id,
        role=role,
        message_kind="story",
        content=content,
        completion_state=completion_state,
        token_estimate=max(1, len(content) // 2),
    )
    db_session.add(node)
    await db_session.flush()
    await service._repo.set_selected_child(  # noqa: SLF001 - aggregate test helper
        db_session,
        journey=journey,
        parent_node_id=parent.id,
        child_node_id=node.id,
    )
    journey.selected_leaf_node_id = node.id
    return node


async def test_source_query_seeds_low_information_input_from_journey_state() -> None:
    query = _source_retrieval_query(
        latest_input="继续",
        overview_sections=InteractionOverviewSections(
            current_situation="洛恩正在北塔外寻找入口。",
            important_people_and_factions="奈拉保管银钥匙。",
            open_threads="尚未兑现向南门送药的承诺。",
        ),
        path=[
            SimpleNamespace(content="洛恩把银钥匙交给奈拉。"),
            SimpleNamespace(content="两人在北塔外墙发现刻痕。"),
            SimpleNamespace(content="继续"),
        ],
    )

    assert query.startswith("当前输入：继续")
    assert "北塔" in query
    assert "奈拉保管银钥匙" in query
    assert "南门送药" in query
    assert len(query) <= 4_000


async def test_create_journey_hidden_project_does_not_enter_author_list(
    db_session,
) -> None:
    _service, journey, _attempt, response = await _create_journey(db_session)

    author_projects = await ProjectService().list_projects(db_session)

    assert response.journey.title == "诡秘之主 · 新旅程"
    assert author_projects.total == 0
    with pytest.raises(NotFoundError):
        await ProjectService().get_project(db_session, str(journey.novel_id))


async def test_create_journey_repeated_idempotency_reuses_attempt_and_project(
    db_session,
) -> None:
    service, _journey, _attempt, first = await _create_journey(db_session)
    with patch(
        "modules.interaction.services.build_project_llm_execution_snapshot",
        autospec=True,
    ) as snapshot:
        second = await service.create_journey(
            db_session,
            JourneyCreateRequest(
                opening_text="这段重复请求不应新建旅程。",
                idempotency_key="create-journey-0001",
            ),
        )

    project_count = (
        await db_session.execute(select(func.count(InteractionJourney.id)))
    ).scalar_one()
    assert second.journey.id == first.journey.id
    assert second.attempt.id == first.attempt.id
    assert project_count == 1
    snapshot.assert_not_awaited()


async def test_opening_created_in_see_sea_is_adopted_and_hides_actions(
    db_session,
) -> None:
    service = InteractionService()
    with patch(
        "modules.interaction.services.build_project_llm_execution_snapshot",
        autospec=True,
        return_value=_snapshot_for(uuid.uuid4()),
    ):
        created = await service.create_journey(
            db_session,
            JourneyCreateRequest(
                opening_text="我进入一座陌生的港城。",
                idempotency_key="opening-direct-see-sea",
                see_sea_enabled=True,
                action_options_enabled=True,
            ),
        )
    journey = await db_session.get(
        InteractionJourney,
        uuid.UUID(created.journey.id),
    )
    attempt = await db_session.get(
        InteractionGenerationAttempt,
        uuid.UUID(created.attempt.id),
    )
    assert journey is not None
    assert attempt is not None
    assert attempt.usage["see_sea_adopted"] is True
    attempt.status = "running"
    attempt.visible_text = "港城的雾里传来第一声汽笛。"
    attempt.visible_offset = len(attempt.visible_text)
    db_session.task_checkpoint_enabled = True

    result = await InteractionGenerationWorkflow().finalize_story_task(
        db_session,
        task=_task_for(journey, attempt),
        finish_reason="stop",
        metadata=InteractionResponseMetadata(
            action_suggestions=[
                InteractionActionSuggestion(
                    label="追过去",
                    text="我追向汽笛传来的方向。",
                )
            ],
        ),
    )
    node = await db_session.get(
        InteractionMessageNode,
        uuid.UUID(result["node_id"]),
    )

    assert node is not None
    assert node.action_suggestions == []
    assert journey.see_sea_enabled is True
    with patch(
        "modules.interaction.services.build_project_llm_execution_snapshot",
        autospec=True,
    ) as snapshot:
        boundary = await service.heartbeat(
            db_session,
            journey_id=str(journey.id),
        )
    assert boundary.attempt is None
    snapshot.assert_not_awaited()


async def test_see_sea_waits_for_answer_after_opening_clarification(
    db_session,
) -> None:
    service = InteractionService()
    with patch(
        "modules.interaction.services.build_project_llm_execution_snapshot",
        autospec=True,
        return_value=_snapshot_for(uuid.uuid4()),
    ):
        created = await service.create_journey(
            db_session,
            JourneyCreateRequest(
                opening_text="我进入那个有两部同名作品的世界。",
                idempotency_key="opening-see-sea-clarification",
                see_sea_enabled=True,
            ),
        )
    journey = await db_session.get(
        InteractionJourney,
        uuid.UUID(created.journey.id),
    )
    attempt = await db_session.get(
        InteractionGenerationAttempt,
        uuid.UUID(created.attempt.id),
    )
    assert journey is not None
    assert attempt is not None
    attempt.status = "running"
    attempt.visible_text = "你指的是哪一部同名作品？补充一个人物或时代即可。"
    attempt.visible_offset = len(attempt.visible_text)
    db_session.task_checkpoint_enabled = True

    finalized = await InteractionGenerationWorkflow().finalize_story_task(
        db_session,
        task=_task_for(journey, attempt),
        finish_reason="stop",
        metadata=InteractionResponseMetadata(response_kind="clarification"),
    )
    clarification = await db_session.get(
        InteractionMessageNode,
        uuid.UUID(finalized["node_id"]),
    )
    assert clarification is not None
    assert clarification.message_kind == "setup"

    with patch(
        "modules.interaction.services.build_project_llm_execution_snapshot",
        autospec=True,
    ) as snapshot:
        heartbeat = await service.heartbeat(
            db_session,
            journey_id=str(journey.id),
        )

    assert heartbeat.accepted is True
    assert heartbeat.see_sea_enabled is True
    assert heartbeat.attempt is None
    snapshot.assert_not_awaited()
    attempts = (
        await db_session.execute(
            select(InteractionGenerationAttempt).where(
                InteractionGenerationAttempt.journey_id == journey.id
            )
        )
    ).scalars()
    assert len(list(attempts)) == 1

    with patch(
        "modules.interaction.services.build_project_llm_execution_snapshot",
        autospec=True,
        return_value=_snapshot_for(journey.novel_id),
    ):
        continued = await service.send_message(
            db_session,
            journey_id=str(journey.id),
            content="我指的是蒸汽时代的那一部，现在开始吧。",
            expected_selection_epoch=journey.selection_epoch,
            idempotency_key="answer-see-sea-clarification",
        )
    continued_attempt = await db_session.get(
        InteractionGenerationAttempt,
        uuid.UUID(continued.attempt.id),
    )
    assert continued_attempt is not None
    assert continued_attempt.request_kind == "setup_continue"
    assert continued_attempt.usage["see_sea_adopted"] is True


async def test_create_journey_rechecks_idempotency_after_owner_lock(
    db_session,
) -> None:
    _service, journey, attempt, first = await _create_journey(
        db_session,
        key="create-after-lock",
    )
    service = InteractionService()

    with (
        patch.object(
            service._repo,
            "get_attempt_by_idempotency",
            autospec=True,
            side_effect=[None, attempt],
        ),
        patch.object(
            service._repo,
            "lock_owner_generation_slots",
            autospec=True,
        ) as lock,
        patch(
            "modules.interaction.services.create_interaction_project",
            autospec=True,
        ) as create_project,
    ):
        repeated = await service.create_journey(
            db_session,
            JourneyCreateRequest(
                opening_text="并发重试不应再创建一条旅程。",
                idempotency_key="create-after-lock",
            ),
        )

    assert repeated.journey.id == str(journey.id) == first.journey.id
    assert repeated.attempt.id == str(attempt.id)
    lock.assert_awaited_once()
    create_project.assert_not_awaited()


async def test_path_index_covers_unloaded_assistant_story_and_around_window(
    db_session,
) -> None:
    service, journey, attempt, _response = await _create_journey(
        db_session,
        key="create-path-index",
    )
    attempt.status = "completed"
    opening = (
        await db_session.execute(
            select(InteractionMessageNode).where(
                InteractionMessageNode.id == journey.selected_leaf_node_id
            )
        )
    ).scalar_one()
    parent = opening
    assistants: list[InteractionMessageNode] = []
    for index in range(1, 5):
        parent = await _append_selected_node(
            db_session,
            service,
            journey,
            parent=parent,
            role="user",
            content=f"我的第 {index} 个行动",
        )
        parent = await _append_selected_node(
            db_session,
            service,
            journey,
            parent=parent,
            role="assistant",
            content=f"\n  第 {index} 段故事从这里开始，随后继续发展。",
            completion_state="partial" if index == 2 else "complete",
        )
        assistants.append(parent)
    journey.selection_epoch = 4
    await db_session.flush()

    index = await service.get_path_index(db_session, journey_id=str(journey.id))
    page = await service.get_message_page(
        db_session,
        journey_id=str(journey.id),
        before_node_id=None,
        around_node_id=str(assistants[1].id),
        limit=3,
    )

    assert index.selection_epoch == 4
    assert [item.id for item in index.items] == [str(node.id) for node in assistants]
    assert index.items[1].excerpt.startswith("未完整 · 第 2 段故事")
    assert index.items[-1].ordinal == index.items[-1].total == 4
    assert str(assistants[1].id) in {item.id for item in page.items}
    assert page.has_newer is True
    assert page.selection_epoch == 4


async def test_overview_from_previous_branch_is_not_exposed_after_switch(
    db_session,
) -> None:
    service, journey, attempt, _response = await _create_journey(
        db_session,
        key="create-overview-branch",
    )
    attempt.status = "completed"
    opening = (
        await db_session.execute(
            select(InteractionMessageNode).where(
                InteractionMessageNode.id == journey.selected_leaf_node_id
            )
        )
    ).scalar_one()
    first_branch = await _append_selected_node(
        db_session,
        service,
        journey,
        parent=opening,
        role="assistant",
        content="第一条发展已经发生。",
    )
    await db_session.flush()
    saved = await service.update_overview(
        db_session,
        journey_id=str(journey.id),
        sections=InteractionOverviewSections(
            current_situation="第一条发展中的当前局面。"
        ),
        expected_overview_epoch=0,
        expected_selection_epoch=0,
    )
    second_branch = InteractionMessageNode(
        novel_id=journey.novel_id,
        journey_id=journey.id,
        parent_node_id=opening.id,
        role="assistant",
        message_kind="story",
        content="第二条发展取代了第一条。",
        completion_state="complete",
        token_estimate=20,
    )
    db_session.add(second_branch)
    await db_session.flush()
    switched = await service.select_branch(
        db_session,
        journey_id=str(journey.id),
        node_id=str(second_branch.id),
        expected_selection_epoch=0,
    )

    overview = await service.get_overview(
        db_session,
        journey_id=str(journey.id),
    )

    assert saved.anchor_node_id == str(first_branch.id)
    assert switched.selected_leaf_node_id == str(second_branch.id)
    assert overview.sections.current_situation == ""
    assert overview.anchor_node_id is None
    assert overview.status == "forming"

    current_path = await service._repo.get_selected_path(
        db_session,
        journey=journey,
    )
    with patch(
        "modules.interaction.generation.restore_project_llm_execution_settings",
        autospec=True,
        return_value={"llm": {"model": "deepseek-v4-flash"}},
    ):
        prepared = await InteractionGenerationWorkflow()._prepare_summary_generation(
            db_session,
            journey=journey,
            current_path=current_path,
            expected_path_hash=path_hash(current_path),
            started_epoch=journey.overview_epoch,
            snapshot=_snapshot_for(journey.novel_id),
        )
    assert prepared is None

    _filename, _media_type, exported = await service.export_journey(
        db_session,
        journey_id=str(journey.id),
        format_name="md",
        story_only=False,
        include_overview=True,
    )
    assert "第一条发展中的当前局面" not in exported
    assert "第二条发展取代了第一条" in exported


async def test_failed_visible_record_stays_off_current_branch_until_adopted(
    db_session,
) -> None:
    service, journey, attempt, _response = await _create_journey(
        db_session,
        key="create-failed-record",
    )
    attempt.status = "failed"
    attempt.visible_text = "雾中那扇门只推开了一半。"
    attempt.visible_offset = len(attempt.visible_text)
    attempt.error_kind = "connection"
    opening = (await service._repo.get_selected_path(db_session, journey=journey))[-1]
    selected_story = InteractionMessageNode(
        novel_id=journey.novel_id,
        journey_id=journey.id,
        parent_node_id=opening.id,
        role="assistant",
        message_kind="story",
        content="另一条完整的发展被选中。",
        completion_state="complete",
        token_estimate=12,
    )
    db_session.add(selected_story)
    await db_session.flush()

    switched = await service.select_branch(
        db_session,
        journey_id=str(journey.id),
        node_id=str(selected_story.id),
        expected_selection_epoch=0,
    )
    listed = await service.list_journeys(
        db_session,
        status="active",
        search=None,
        offset=0,
        limit=20,
    )
    records = await service.list_generation_records(
        db_session,
        journey_id=str(journey.id),
    )
    before_export = await service.export_journey(
        db_session,
        journey_id=str(journey.id),
        format_name="txt",
        story_only=True,
        include_overview=True,
    )

    assert switched.active_attempt is None
    assert listed.items[0].attempt_status is None
    assert [item.id for item in records.items] == [str(attempt.id)]
    assert attempt.visible_text not in before_export[2]
    assert selected_story.content in before_export[2]

    original_keep_epoch = switched.selection_epoch
    kept = await service.keep_partial(
        db_session,
        journey_id=str(journey.id),
        attempt_id=str(attempt.id),
        expected_selection_epoch=original_keep_epoch,
    )
    await db_session.refresh(journey)
    repeated = await service.keep_partial(
        db_session,
        journey_id=str(journey.id),
        attempt_id=str(attempt.id),
        expected_selection_epoch=original_keep_epoch,
    )
    after_records = await service.list_generation_records(
        db_session,
        journey_id=str(journey.id),
    )
    after_export = await service.export_journey(
        db_session,
        journey_id=str(journey.id),
        format_name="txt",
        story_only=True,
        include_overview=True,
    )

    assert kept.partial_node is not None
    assert repeated.partial_node is not None
    assert repeated.partial_node.id == kept.partial_node.id
    assert journey.selected_leaf_node_id == uuid.UUID(kept.partial_node.id)
    assert after_records.items == []
    assert attempt.visible_text in after_export[2]
    assert "我来到" not in after_export[2]


async def test_unadopted_failed_fragment_does_not_trigger_overview(
    db_session,
) -> None:
    service, journey, attempt, _response = await _create_journey(
        db_session,
        key="create-unadopted-no-overview",
    )
    attempt.status = "failed"
    attempt.visible_text = "雨幕中的谈话只留下了半句。"
    attempt.visible_offset = len(attempt.visible_text)
    await db_session.flush()

    before = list(
        (
            await db_session.execute(
                select(AsyncTask).where(
                    AsyncTask.task_type == "interaction_summary_refresh"
                )
            )
        )
        .scalars()
        .all()
    )
    kept = await service.keep_partial(
        db_session,
        journey_id=str(journey.id),
        attempt_id=str(attempt.id),
        expected_selection_epoch=journey.selection_epoch,
    )
    after = list(
        (
            await db_session.execute(
                select(AsyncTask).where(
                    AsyncTask.task_type == "interaction_summary_refresh"
                )
            )
        )
        .scalars()
        .all()
    )

    assert before == []
    assert kept.partial_node is not None
    assert len(after) == 0


async def test_manual_overview_save_keeps_frozen_coverage_and_recent_tail_raw(
    db_session,
) -> None:
    service, journey, attempt, _response = await _create_journey(
        db_session,
        key="create-overview-fast-forward",
    )
    attempt.status = "completed"
    opening = (await service._repo.get_selected_path(db_session, journey=journey))[-1]
    first_story = await _append_selected_node(
        db_session,
        service,
        journey,
        parent=opening,
        role="assistant",
        content="旧回顾已经覆盖这一段。",
    )
    first_path = await service._repo.get_selected_path(db_session, journey=journey)
    base = InteractionOverviewRevision(
        novel_id=journey.novel_id,
        journey_id=journey.id,
        anchor_node_id=first_story.id,
        path_hash=path_hash(first_path),
        coverage_anchor_node_id=first_story.id,
        coverage_path_hash=path_hash(first_path),
        sections={"current_situation": "旧局面。"},
        source="automatic",
        started_overview_epoch=0,
        promoted=True,
        producer={"kind": "model"},
    )
    db_session.add(base)
    await db_session.flush()
    journey.overview_head_revision_id = base.id
    journey.overview_epoch = 1
    journey.selection_epoch = 1
    frozen = await service.get_overview(
        db_session,
        journey_id=str(journey.id),
    )

    new_story = await _append_selected_node(
        db_session,
        service,
        journey,
        parent=first_story,
        role="assistant",
        content="编辑回顾期间，新的事实已经发生。",
    )
    current_path = await service._repo.get_selected_path(
        db_session,
        journey=journey,
    )
    base.promoted = False
    automatic = InteractionOverviewRevision(
        novel_id=journey.novel_id,
        journey_id=journey.id,
        anchor_node_id=new_story.id,
        path_hash=path_hash(current_path),
        coverage_anchor_node_id=new_story.id,
        coverage_path_hash=path_hash(current_path),
        sections={"current_situation": "自动版本包含新事实。"},
        source="automatic",
        based_on_revision_id=base.id,
        started_overview_epoch=1,
        promoted=True,
        producer={"kind": "model"},
    )
    db_session.add(automatic)
    await db_session.flush()
    journey.overview_head_revision_id = automatic.id
    journey.overview_epoch = 2
    journey.selection_epoch = 2

    async def snapshot(_db, novel_id: str) -> dict:
        return _snapshot_for(uuid.UUID(novel_id))

    with patch(
        "modules.interaction.services.build_project_llm_execution_snapshot",
        autospec=True,
        side_effect=snapshot,
    ):
        saved = await service.update_overview(
            db_session,
            journey_id=str(journey.id),
            sections=InteractionOverviewSections(
                current_situation="用户纠正后的旧局面。"
            ),
            expected_overview_epoch=frozen.overview_epoch,
            expected_selection_epoch=1,
            base_revision_id=frozen.base_revision_id,
            base_selected_leaf_node_id=frozen.base_selected_leaf_node_id,
            base_selected_path_hash=frozen.base_selected_path_hash,
        )

    head = await service._repo.get_overview_head(db_session, journey=journey)
    assert head is not None
    head_id = head.id
    base_id = base.id
    first_story_id = first_story.id
    new_story_id = new_story.id
    task = (
        await db_session.execute(
            select(AsyncTask)
            .where(AsyncTask.task_type == "interaction_summary_refresh")
            .order_by(AsyncTask.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    head = await db_session.get(InteractionOverviewRevision, head_id)

    assert head is not None
    assert head.source == "manual"
    assert head.anchor_node_id == first_story_id
    assert head.coverage_anchor_node_id == first_story_id
    assert head.based_on_revision_id == base_id
    assert saved.base_selected_leaf_node_id == str(new_story_id)
    assert saved.is_refreshing is False
    assert saved.status == "ready"
    assert task is None


async def test_manual_overview_is_scoped_to_branch_and_restored_on_return(
    db_session,
) -> None:
    service, journey, attempt, _response = await _create_journey(
        db_session,
        key="create-overview-branch-roundtrip",
    )
    attempt.status = "completed"
    opening = (await service._repo.get_selected_path(db_session, journey=journey))[-1]
    common_path = [opening]
    common = InteractionOverviewRevision(
        novel_id=journey.novel_id,
        journey_id=journey.id,
        anchor_node_id=opening.id,
        path_hash=path_hash(common_path),
        coverage_anchor_node_id=opening.id,
        coverage_path_hash=path_hash(common_path),
        sections={"current_situation": "公共起点。"},
        source="automatic",
        started_overview_epoch=0,
        promoted=False,
        producer={"kind": "model"},
    )
    branch_a = await _append_selected_node(
        db_session,
        service,
        journey,
        parent=opening,
        role="assistant",
        content="A 分支。",
    )
    path_a = await service._repo.get_selected_path(db_session, journey=journey)
    overview_a = InteractionOverviewRevision(
        novel_id=journey.novel_id,
        journey_id=journey.id,
        anchor_node_id=branch_a.id,
        path_hash=path_hash(path_a),
        coverage_anchor_node_id=opening.id,
        coverage_path_hash=path_hash(common_path),
        sections={"current_situation": "A 分支的人工回顾。"},
        source="manual",
        based_on_revision_id=common.id,
        started_overview_epoch=0,
        promoted=True,
        producer={"kind": "user"},
    )
    db_session.add_all([common, overview_a])
    await db_session.flush()
    journey.overview_head_revision_id = overview_a.id
    journey.overview_epoch = 1
    branch_b = InteractionMessageNode(
        novel_id=journey.novel_id,
        journey_id=journey.id,
        parent_node_id=opening.id,
        role="assistant",
        message_kind="story",
        content="B 分支。",
        completion_state="complete",
        token_estimate=6,
    )
    db_session.add(branch_b)
    await db_session.flush()

    await service.select_branch(
        db_session,
        journey_id=str(journey.id),
        node_id=str(branch_b.id),
        expected_selection_epoch=0,
    )
    on_b = await service.get_overview(db_session, journey_id=str(journey.id))
    await db_session.refresh(journey)
    await service.select_branch(
        db_session,
        journey_id=str(journey.id),
        node_id=str(branch_a.id),
        expected_selection_epoch=journey.selection_epoch,
    )
    back_on_a = await service.get_overview(
        db_session,
        journey_id=str(journey.id),
    )

    assert on_b.sections.current_situation == "公共起点。"
    assert back_on_a.sections.current_situation == "A 分支的人工回顾。"
    assert back_on_a.base_revision_id == str(overview_a.id)


async def test_tree_projection_only_returns_real_branch_points(
    db_session,
) -> None:
    service, journey, attempt, _response = await _create_journey(
        db_session,
        key="create-compressed-tree",
    )
    attempt.status = "completed"
    opening = (
        await db_session.execute(
            select(InteractionMessageNode).where(
                InteractionMessageNode.id == journey.selected_leaf_node_id
            )
        )
    ).scalar_one()
    selected = await _append_selected_node(
        db_session,
        service,
        journey,
        parent=opening,
        role="assistant",
        content="老板表面配合，暗中留下假线索。",
    )
    await _append_selected_node(
        db_session,
        service,
        journey,
        parent=selected,
        role="user",
        content="我收起线索继续追问。",
    )
    alternative = InteractionMessageNode(
        novel_id=journey.novel_id,
        journey_id=journey.id,
        parent_node_id=opening.id,
        role="assistant",
        message_kind="story",
        content="守卫闯入，谈判转为追逐。",
        completion_state="complete",
        token_estimate=20,
    )
    db_session.add(alternative)
    await db_session.flush()

    tree = await service.get_tree(db_session, journey_id=str(journey.id))

    assert len(tree.branch_points) == 1
    assert tree.branch_points[0].label
    assert {item.node_id for item in tree.branch_points[0].variants} == {
        str(selected.id),
        str(alternative.id),
    }
    assert sum(item.selected for item in tree.branch_points[0].variants) == 1


async def test_stop_attempt_formalizes_visible_text_once_as_partial(
    db_session,
) -> None:
    service, journey, attempt, _response = await _create_journey(db_session)
    attempt.status = "running"
    attempt.visible_text = "我刚推开门，走廊尽头传来脚步声。"
    attempt.visible_offset = len(attempt.visible_text)
    await db_session.flush()

    first = await service.stop_attempt(
        db_session,
        journey_id=str(journey.id),
        attempt_id=str(attempt.id),
        expected_selection_epoch=0,
    )
    second = await service.stop_attempt(
        db_session,
        journey_id=str(journey.id),
        attempt_id=str(attempt.id),
        expected_selection_epoch=0,
    )

    assistants = list(
        (
            await db_session.execute(
                select(InteractionMessageNode).where(
                    InteractionMessageNode.journey_id == journey.id,
                    InteractionMessageNode.role == "assistant",
                )
            )
        )
        .scalars()
        .all()
    )
    assert first.partial_node is not None
    assert first.partial_node.completion_state == "partial"
    assert first.partial_node.end_reason == "user_stopped"
    assert second.partial_node is not None
    assert second.partial_node.id == first.partial_node.id
    assert len(assistants) == 1
    summary_tasks = list(
        (
            await db_session.execute(
                select(AsyncTask).where(
                    AsyncTask.task_type == "interaction_summary_refresh"
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(summary_tasks) == 0


async def test_late_stream_checkpoint_cannot_change_stopped_partial(
    db_session,
) -> None:
    service, journey, attempt, _response = await _create_journey(
        db_session,
        key="create-late-checkpoint-fence",
    )
    attempt.status = "running"
    attempt.visible_text = "停止前已经持久化的正文。"
    attempt.visible_offset = len(attempt.visible_text)
    await db_session.flush()
    task = _task_for(journey, attempt)

    stopped = await service.stop_attempt(
        db_session,
        journey_id=str(journey.id),
        attempt_id=str(attempt.id),
        expected_selection_epoch=journey.selection_epoch,
    )
    db_session.task_checkpoint_enabled = True
    with pytest.raises(RuntimeError, match="no longer accepts"):
        await InteractionGenerationWorkflow().checkpoint_story_task(
            db_session,
            task=task,
            visible_delta="这段晚到内容不得写入。",
        )
    await db_session.refresh(attempt)

    assert stopped.partial_node is not None
    assert stopped.partial_node.content == "停止前已经持久化的正文。"
    assert attempt.visible_text == "停止前已经持久化的正文。"


async def test_archive_awaiting_continue_formalizes_visible_text_as_partial(
    db_session,
) -> None:
    service, journey, attempt, _response = await _create_journey(
        db_session,
        key="create-archive-awaiting",
    )
    attempt.status = "awaiting_continue"
    attempt.visible_text = "钟楼的门已经打开，但这段故事被长度限制截断。"
    attempt.visible_offset = len(attempt.visible_text)
    await db_session.flush()

    archived = await service.archive_journey(
        db_session,
        journey_id=str(journey.id),
        confirmed=True,
    )

    await db_session.refresh(attempt)
    partial = await db_session.get(
        InteractionMessageNode,
        attempt.result_node_id,
    )
    assert archived.status == "archived"
    assert attempt.status == "stopped"
    assert attempt.finish_reason == "archived"
    assert partial is not None
    assert partial.content == attempt.visible_text
    assert partial.completion_state == "partial"
    assert partial.end_reason == "archived"


async def test_archive_latest_failed_visible_text_as_partial(
    db_session,
) -> None:
    service, journey, attempt, _response = await _create_journey(
        db_session,
        key="create-archive-failed-visible",
    )
    attempt.status = "failed"
    attempt.visible_text = "网络断开前，这段钟楼故事已经显示给用户。"
    attempt.visible_offset = len(attempt.visible_text)
    attempt.error_kind = "connection"
    await db_session.flush()

    archived = await service.archive_journey(
        db_session,
        journey_id=str(journey.id),
        confirmed=True,
    )

    await db_session.refresh(attempt)
    partial = await db_session.get(
        InteractionMessageNode,
        attempt.result_node_id,
    )
    assert archived.status == "archived"
    assert attempt.status == "stopped"
    assert attempt.finish_reason == "archived"
    assert partial is not None
    assert partial.content == attempt.visible_text
    assert partial.completion_state == "partial"


async def test_old_failed_attempt_cannot_interrupt_or_replace_newer_attempt(
    db_session,
) -> None:
    service, journey, failed_attempt, _response = await _create_journey(
        db_session,
        key="create-old-failed-resolution-guard",
    )
    failed_attempt.status = "failed"
    failed_attempt.visible_text = "旧失败片段不应再抢回当前发展。"
    await db_session.flush()

    with patch(
        "modules.interaction.services.build_project_llm_execution_snapshot",
        autospec=True,
        return_value=_snapshot_for(journey.novel_id),
    ):
        retried = await service.retry_attempt(
            db_session,
            journey_id=str(journey.id),
            attempt_id=str(failed_attempt.id),
            expected_selection_epoch=journey.selection_epoch,
            idempotency_key="newer-active-after-failure",
        )
    newer_attempt = await db_session.get(
        InteractionGenerationAttempt,
        uuid.UUID(retried.attempt.id),
    )
    assert newer_attempt is not None
    selected_before = journey.selected_leaf_node_id
    epoch_before = journey.selection_epoch

    with pytest.raises(ConflictError, match="当前未完成"):
        await service.keep_partial(
            db_session,
            journey_id=str(journey.id),
            attempt_id=str(failed_attempt.id),
            expected_selection_epoch=journey.selection_epoch,
        )
    with pytest.raises(ConflictError, match="保留这段"):
        await service.stop_attempt(
            db_session,
            journey_id=str(journey.id),
            attempt_id=str(failed_attempt.id),
            expected_selection_epoch=journey.selection_epoch,
        )

    assert newer_attempt.status == "pending"
    assert journey.selected_leaf_node_id == selected_before
    assert journey.selection_epoch == epoch_before
    assert failed_attempt.result_node_id is None


async def test_task_owner_reconciler_keeps_worker_checkpoint_unselected(
    db_session,
) -> None:
    service, journey, attempt, _response = await _create_journey(
        db_session,
        key="create-worker-reconcile",
    )
    attempt.status = "running"
    attempt.visible_text = "雾中传来半截钟声，故事在这里被意外打断。"
    attempt.visible_offset = len(attempt.visible_text)
    journey.see_sea_enabled = True
    journey.see_sea_last_heartbeat_at = datetime.now(UTC)
    task = await db_session.get(AsyncTask, attempt.task_id)
    assert task is not None
    task.mark_failed("Task interrupted: heartbeat timeout")
    await db_session.flush()

    assert await service.reconcile_task_owners(db_session) == 1

    await db_session.refresh(attempt)
    await db_session.refresh(journey)
    assert attempt.status == "failed"
    assert attempt.finish_reason == "worker_interrupted"
    assert attempt.error_kind == "worker_interrupted"
    assert attempt.result_node_id is None
    assert journey.selected_leaf_node_id == attempt.response_to_node_id
    assert journey.see_sea_enabled is False


async def test_awaiting_continue_blocks_new_history_and_branch_switch(
    db_session,
) -> None:
    service, journey, attempt, _response = await _create_journey(
        db_session,
        key="create-awaiting-block",
    )
    attempt.status = "awaiting_continue"
    attempt.visible_text = "这段故事尚未写完。"
    await db_session.flush()

    with pytest.raises(ConflictError, match="继续写完"):
        await service.send_message(
            db_session,
            journey_id=str(journey.id),
            content="绕过未完成片段的新输入",
            expected_selection_epoch=journey.selection_epoch,
            idempotency_key="blocked-new-message",
        )
    with pytest.raises(ConflictError, match="继续写完"):
        await service.select_branch(
            db_session,
            journey_id=str(journey.id),
            node_id=str(journey.selected_leaf_node_id),
            expected_selection_epoch=journey.selection_epoch,
        )


async def test_retry_old_failure_cannot_bypass_newer_awaiting_continue(
    db_session,
) -> None:
    service, journey, failed_attempt, _response = await _create_journey(
        db_session,
        key="create-retry-awaiting-guard",
    )
    failed_attempt.status = "failed"
    await db_session.flush()

    with patch(
        "modules.interaction.services.build_project_llm_execution_snapshot",
        autospec=True,
        return_value=_snapshot_for(journey.novel_id),
    ):
        first_retry = await service.retry_attempt(
            db_session,
            journey_id=str(journey.id),
            attempt_id=str(failed_attempt.id),
            expected_selection_epoch=journey.selection_epoch,
            idempotency_key="retry-awaiting-current",
        )
    awaiting_attempt = await db_session.get(
        InteractionGenerationAttempt,
        uuid.UUID(first_retry.attempt.id),
    )
    assert awaiting_attempt is not None
    awaiting_attempt.status = "awaiting_continue"
    awaiting_attempt.visible_text = "当前这段故事还需要继续写完。"
    await db_session.flush()

    with pytest.raises(ConflictError, match="当前未完成"):
        await service.retry_attempt(
            db_session,
            journey_id=str(journey.id),
            attempt_id=str(failed_attempt.id),
            expected_selection_epoch=journey.selection_epoch,
            idempotency_key="retry-old-failure-again",
        )


async def test_retry_current_awaiting_continue_replaces_that_attempt(
    db_session,
) -> None:
    service, journey, attempt, _response = await _create_journey(
        db_session,
        key="create-retry-current-awaiting",
    )
    attempt.status = "awaiting_continue"
    attempt.visible_text = "当前片段被长度限制截断。"
    await db_session.flush()

    with patch(
        "modules.interaction.services.build_project_llm_execution_snapshot",
        autospec=True,
        return_value=_snapshot_for(journey.novel_id),
    ):
        retried = await service.retry_attempt(
            db_session,
            journey_id=str(journey.id),
            attempt_id=str(attempt.id),
            expected_selection_epoch=journey.selection_epoch,
            idempotency_key="retry-current-awaiting",
        )

    assert retried.attempt.id != str(attempt.id)
    assert attempt.status == "cancelled"
    assert attempt.finish_reason == "regenerated"
    records = await service.list_generation_records(
        db_session,
        journey_id=str(journey.id),
    )
    assert records.items == []


async def test_retry_reconstructs_multi_node_context_from_leaf(
    db_session,
) -> None:
    service, journey, opening_attempt, _response = await _create_journey(
        db_session,
        key="create-retry-multi-node",
    )
    opening_attempt.status = "completed"
    opening = (await service._repo.get_selected_path(db_session, journey=journey))[-1]
    story = await _append_selected_node(
        db_session,
        service,
        journey,
        parent=opening,
        role="assistant",
        content="钟楼下的人群突然安静下来。",
    )
    user = await _append_selected_node(
        db_session,
        service,
        journey,
        parent=story,
        role="user",
        content="我停下脚步观察钟楼。",
    )
    current_path = await service._repo.get_selected_path(
        db_session,
        journey=journey,
    )
    failed = InteractionGenerationAttempt(
        novel_id=journey.novel_id,
        journey_id=journey.id,
        owner_id=journey.owner_id,
        response_to_node_id=user.id,
        idempotency_key="failed-multi-node-source",
        request_kind="message",
        status="failed",
        started_selection_epoch=journey.selection_epoch,
        visible_text="",
        visible_offset=0,
        metadata_text="",
        llm_execution_snapshot=_snapshot_for(journey.novel_id),
        context_path_hash=path_hash(current_path),
        context_node_ids=[str(user.id)],
        reference_node_ids=[],
        usage={},
    )
    db_session.add(failed)
    await db_session.flush()
    expected_contents = [node.content for node in current_path]

    with patch(
        "modules.interaction.services.build_project_llm_execution_snapshot",
        autospec=True,
        return_value=_snapshot_for(journey.novel_id),
    ):
        retried = await service.retry_attempt(
            db_session,
            journey_id=str(journey.id),
            attempt_id=str(failed.id),
            expected_selection_epoch=journey.selection_epoch,
            idempotency_key="retry-multi-node-attempt",
        )
    retry_attempt = await db_session.get(
        InteractionGenerationAttempt,
        uuid.UUID(retried.attempt.id),
    )
    assert retry_attempt is not None
    assert retry_attempt.context_node_ids == [str(user.id)]
    assert retry_attempt.context_path_hash == path_hash(current_path)
    db_session.task_checkpoint_enabled = True
    with patch(
        "modules.interaction.generation.restore_project_llm_execution_settings",
        autospec=True,
        return_value={"llm": {"model": "deepseek-v4-flash"}},
    ):
        prepared = await InteractionGenerationWorkflow().prepare_story_task(
            db_session,
            task=_task_for(journey, retry_attempt),
        )

    assert isinstance(prepared, PreparedStoryGeneration)
    compiled = "\n".join(message.content for message in prepared.messages)
    assert all(content in compiled for content in expected_contents)


async def test_regenerate_uses_rejected_full_text_and_two_earlier_hints(
    db_session,
) -> None:
    service, journey, opening_attempt, _response = await _create_journey(
        db_session,
        key="create-regenerate-reference-window",
    )
    opening_attempt.status = "completed"
    opening = (await service._repo.get_selected_path(db_session, journey=journey))[-1]
    now = datetime.now(UTC)
    variants = [
        InteractionMessageNode(
            id=uuid.uuid4(),
            novel_id=journey.novel_id,
            journey_id=journey.id,
            parent_node_id=opening.id,
            role="assistant",
            message_kind="story",
            content=f"不会进入提示词的完整旧正文 {index}",
            completion_state="complete",
            branch_hint=f"旧分支提示 {index}",
            token_estimate=10,
            created_at=now + timedelta(seconds=index),
        )
        for index in range(3)
    ]
    rejected = InteractionMessageNode(
        id=uuid.uuid4(),
        novel_id=journey.novel_id,
        journey_id=journey.id,
        parent_node_id=opening.id,
        role="assistant",
        message_kind="story",
        content=(
            "被拒绝正文的明确开头。"
            + "这是一段需要完整保留的较长故事。" * 400
            + "被拒绝正文的明确结尾。"
        ),
        completion_state="complete",
        branch_hint="当前被拒绝的发展",
        token_estimate=12,
        created_at=now + timedelta(seconds=4),
    )
    db_session.add_all([*variants, rejected])
    await db_session.flush()
    await service._repo.set_selected_child(
        db_session,
        journey=journey,
        parent_node_id=opening.id,
        child_node_id=rejected.id,
    )
    journey.selected_leaf_node_id = rejected.id

    with patch(
        "modules.interaction.services.build_project_llm_execution_snapshot",
        autospec=True,
        return_value=_snapshot_for(journey.novel_id),
    ):
        response = await service.regenerate(
            db_session,
            journey_id=str(journey.id),
            assistant_node_id=str(rejected.id),
            expected_selection_epoch=journey.selection_epoch,
            idempotency_key="regenerate-reference-window",
        )
    regenerated = await db_session.get(
        InteractionGenerationAttempt,
        uuid.UUID(response.attempt.id),
    )
    assert regenerated is not None
    assert regenerated.reference_node_ids == [
        str(rejected.id),
        str(variants[1].id),
        str(variants[2].id),
    ]
    rejected_content = rejected.content
    earlier_hints = [variants[1].branch_hint, variants[2].branch_hint]
    earlier_contents = [variant.content for variant in variants]
    db_session.task_checkpoint_enabled = True
    with patch(
        "modules.interaction.generation.restore_project_llm_execution_settings",
        autospec=True,
        return_value={"llm": {"model": "deepseek-v4-flash"}},
    ):
        prepared = await InteractionGenerationWorkflow().prepare_story_task(
            db_session,
            task=_task_for(journey, regenerated),
        )

    assert isinstance(prepared, PreparedStoryGeneration)
    prompt = "\n".join(message.content for message in prepared.messages)
    assert rejected_content in prompt
    assert all(hint in prompt for hint in earlier_hints if hint)
    assert all(content not in prompt for content in earlier_contents)
    assert "不得把传闻、误解、怀疑、猜测或未知原因升级成确定真相" in prompt
    assert "被拒绝正文的明确开头" in prompt
    assert "被拒绝正文的明确结尾" in prompt
    assert "至少改变 NPC 反应、冲突方式、可见线索、代价或本轮结果之一" in prompt
    assert "同时保持用户已经采取的行动、人物性格、世界规则和既有承诺" in prompt


async def test_continue_idempotency_precedes_stale_selection_epoch(
    db_session,
) -> None:
    service, journey, attempt, _response = await _create_journey(
        db_session,
        key="create-continue-idempotency",
    )
    attempt.status = "awaiting_continue"
    attempt.visible_text = "等待继续写完。"
    await db_session.flush()

    first = await service.continue_attempt(
        db_session,
        journey_id=str(journey.id),
        attempt_id=str(attempt.id),
        expected_selection_epoch=0,
        idempotency_key="continue-same-request",
    )
    attempt.status = "completed"
    journey.selection_epoch = 1
    await db_session.flush()

    repeated = await service.continue_attempt(
        db_session,
        journey_id=str(journey.id),
        attempt_id=str(attempt.id),
        expected_selection_epoch=0,
        idempotency_key="continue-same-request",
    )

    assert repeated.attempt.id == first.attempt.id
    assert repeated.attempt.status == "completed"


async def test_continue_rejects_an_already_continued_attempt(
    db_session,
) -> None:
    service, journey, attempt, _response = await _create_journey(
        db_session,
        key="create-continue-limit",
    )
    attempt.status = "awaiting_continue"
    attempt.continuation_count = 1
    attempt.visible_text = "已经续写过一次的残段。"
    await db_session.flush()

    with pytest.raises(ConflictError, match="已经继续写过一次"):
        await service.continue_attempt(
            db_session,
            journey_id=str(journey.id),
            attempt_id=str(attempt.id),
            expected_selection_epoch=journey.selection_epoch,
            idempotency_key="continue-over-limit",
        )


async def test_normal_length_allows_one_continue_then_formalizes_second_cutoff(
    db_session,
) -> None:
    service, journey, attempt, _response = await _create_journey(
        db_session,
        key="create-normal-length-limit",
    )
    attempt.status = "running"
    attempt.visible_text = "第一段正文在长度边界处暂停。"
    attempt.visible_offset = len(attempt.visible_text)
    await db_session.flush()
    db_session.task_checkpoint_enabled = True
    workflow = InteractionGenerationWorkflow()

    first = await workflow.finalize_story_task(
        db_session,
        task=_task_for(journey, attempt),
        finish_reason="length",
        metadata=None,
    )

    assert first["status"] == "awaiting_continue"
    assert attempt.continuation_count == 0
    continued = await service.continue_attempt(
        db_session,
        journey_id=str(journey.id),
        attempt_id=str(attempt.id),
        expected_selection_epoch=journey.selection_epoch,
        idempotency_key="continue-normal-length-once",
    )
    assert continued.attempt.status == "pending"
    assert attempt.continuation_count == 1

    attempt.status = "running"
    attempt.visible_text += "续写正文再次碰到长度边界。"
    attempt.visible_offset = len(attempt.visible_text)
    await db_session.flush()
    with patch.object(
        InteractionGenerationWorkflow,
        "_summary_is_due",
        autospec=True,
        return_value=False,
    ):
        second = await workflow.finalize_story_task(
            db_session,
            task=_task_for(journey, attempt),
            finish_reason="length",
            metadata=None,
        )

    node = await db_session.get(
        InteractionMessageNode,
        uuid.UUID(second["node_id"]),
    )
    assert second["status"] == "stopped"
    assert second["selected"] is True
    assert attempt.status == "stopped"
    assert node is not None
    assert node.completion_state == "partial"
    assert node.content == attempt.visible_text


async def test_finalize_late_story_keeps_variant_but_does_not_move_selection(
    db_session,
) -> None:
    _service, journey, attempt, _response = await _create_journey(db_session)
    original_leaf = journey.selected_leaf_node_id
    attempt.status = "running"
    attempt.visible_text = "这是晚到的另一个发展。"
    attempt.visible_offset = len(attempt.visible_text)
    journey.selection_epoch = 1
    await db_session.flush()
    db_session.task_checkpoint_enabled = True
    task = SimpleNamespace(
        id=attempt.task_id,
        meta={
            "novel_id": str(journey.novel_id),
            "journey_id": str(journey.id),
            "attempt_id": str(attempt.id),
        },
        progress=0.0,
        update_progress=lambda value: setattr(task, "progress", value),
    )

    result = await InteractionGenerationWorkflow().finalize_story_task(
        db_session,
        task=task,
        finish_reason="stop",
        metadata=None,
    )
    await db_session.refresh(journey)

    assert result["selected"] is False
    assert result["node_id"]
    assert journey.selected_leaf_node_id == original_leaf


async def test_first_completed_sibling_wins_and_late_sibling_cannot_steal_path(
    db_session,
) -> None:
    _service, journey, first_attempt, _response = await _create_journey(
        db_session,
        key="create-concurrent-siblings",
    )
    first_attempt.status = "running"
    first_attempt.visible_text = "第一条发展先完成。"
    first_attempt.visible_offset = len(first_attempt.visible_text)
    second_attempt = InteractionGenerationAttempt(
        novel_id=journey.novel_id,
        journey_id=journey.id,
        owner_id=journey.owner_id,
        response_to_node_id=first_attempt.response_to_node_id,
        task_id=uuid.uuid4(),
        idempotency_key="concurrent-sibling-second",
        request_kind="opening",
        status="running",
        started_selection_epoch=journey.selection_epoch,
        visible_text="第二条发展稍后才完成。",
        visible_offset=len("第二条发展稍后才完成。"),
        llm_execution_snapshot=dict(first_attempt.llm_execution_snapshot),
        context_path_hash=first_attempt.context_path_hash,
        context_node_ids=list(first_attempt.context_node_ids),
        reference_node_ids=[],
    )
    db_session.add(second_attempt)
    await db_session.flush()
    db_session.task_checkpoint_enabled = True
    first_task = _task_for(journey, first_attempt)
    second_task = _task_for(journey, second_attempt)
    workflow = InteractionGenerationWorkflow()

    with patch.object(
        InteractionGenerationWorkflow,
        "_summary_is_due",
        autospec=True,
        return_value=False,
    ):
        first = await workflow.finalize_story_task(
            db_session,
            task=first_task,
            finish_reason="stop",
            metadata=InteractionResponseMetadata(suggested_title="先完成的旅程"),
        )
        second = await workflow.finalize_story_task(
            db_session,
            task=second_task,
            finish_reason="stop",
            metadata=InteractionResponseMetadata(suggested_title="迟到的标题"),
        )

    await db_session.refresh(journey)
    assert first["selected"] is True
    assert second["selected"] is False
    assert journey.selection_epoch == 1
    assert journey.selected_leaf_node_id == uuid.UUID(first["node_id"])
    assert journey.title == "先完成的旅程"


async def test_late_sibling_length_becomes_unselected_partial_without_blocking(
    db_session,
) -> None:
    service, journey, first_attempt, _response = await _create_journey(
        db_session,
        key="late-sibling-length",
    )
    first_attempt.status = "running"
    first_attempt.visible_text = "先完成的发展成为当前故事。"
    first_attempt.visible_offset = len(first_attempt.visible_text)
    late_attempt = InteractionGenerationAttempt(
        novel_id=journey.novel_id,
        journey_id=journey.id,
        owner_id=journey.owner_id,
        response_to_node_id=first_attempt.response_to_node_id,
        task_id=uuid.uuid4(),
        idempotency_key="late-sibling-length-candidate",
        request_kind="opening",
        status="running",
        started_selection_epoch=journey.selection_epoch,
        visible_text="迟到的发展在长度边界处结束。",
        visible_offset=len("迟到的发展在长度边界处结束。"),
        llm_execution_snapshot=dict(first_attempt.llm_execution_snapshot),
        context_path_hash=first_attempt.context_path_hash,
        context_node_ids=list(first_attempt.context_node_ids),
        reference_node_ids=[],
        usage={},
    )
    db_session.add(late_attempt)
    await db_session.flush()
    db_session.task_checkpoint_enabled = True
    workflow = InteractionGenerationWorkflow()

    with patch.object(
        InteractionGenerationWorkflow,
        "_summary_is_due",
        autospec=True,
        return_value=False,
    ):
        first = await workflow.finalize_story_task(
            db_session,
            task=_task_for(journey, first_attempt),
            finish_reason="stop",
            metadata=None,
        )
        late = await workflow.finalize_story_task(
            db_session,
            task=_task_for(journey, late_attempt),
            finish_reason="length",
            metadata=None,
        )

    late_node = await db_session.get(
        InteractionMessageNode,
        uuid.UUID(late["node_id"]),
    )
    assert first["selected"] is True
    assert late["selected"] is False
    assert late["status"] == "stopped"
    assert late_node is not None
    assert late_node.completion_state == "partial"
    assert journey.selected_leaf_node_id == uuid.UUID(first["node_id"])
    assert (
        await service._repo.get_unresolved_attempt(  # noqa: SLF001
            db_session,
            journey=journey,
        )
        is None
    )

    with patch(
        "modules.interaction.services.build_project_llm_execution_snapshot",
        autospec=True,
        return_value=_snapshot_for(journey.novel_id),
    ):
        sent = await service.send_message(
            db_session,
            journey_id=str(journey.id),
            content="我沿着当前发展继续调查。",
            expected_selection_epoch=journey.selection_epoch,
            idempotency_key="send-after-late-length",
        )
    assert sent.attempt.status == "pending"


async def test_story_usage_checkpoint_preserves_context_budget_diagnostics(
    db_session,
) -> None:
    _service, journey, attempt, _response = await _create_journey(
        db_session,
        key="create-checkpoint-usage",
    )
    attempt.status = "running"
    attempt.usage = {
        "context_tier": "extended",
        "estimated_input_tokens": 300_000,
    }
    attempt_id = attempt.id
    await db_session.flush()
    db_session.task_checkpoint_enabled = True
    task = _task_for(journey, attempt)

    await InteractionGenerationWorkflow().checkpoint_story_task(
        db_session,
        task=task,
        visible_delta="新的故事内容。",
        usage={
            "prompt_tokens": 123,
            "completion_tokens": 45,
            "total_tokens": 168,
        },
    )

    refreshed = await db_session.get(InteractionGenerationAttempt, attempt_id)
    assert refreshed.usage == {
        "context_tier": "extended",
        "estimated_input_tokens": 300_000,
        "prompt_tokens": 123,
        "completion_tokens": 45,
        "total_tokens": 168,
    }


async def test_finalize_story_adopts_valid_title_and_action_metadata(
    db_session,
) -> None:
    _service, journey, attempt, _response = await _create_journey(
        db_session,
        key="create-journey-title",
    )
    attempt.status = "running"
    attempt.visible_text = "雨幕中，一辆马车停在报社门口。"
    attempt.visible_offset = len(attempt.visible_text)
    await db_session.flush()
    db_session.task_checkpoint_enabled = True
    task = SimpleNamespace(
        id=attempt.task_id,
        meta={
            "novel_id": str(journey.novel_id),
            "journey_id": str(journey.id),
            "attempt_id": str(attempt.id),
        },
        progress=0.0,
        update_progress=lambda value: setattr(task, "progress", value),
    )
    metadata = InteractionResponseMetadata(
        suggested_title="廷根雨夜",
        action_suggestions=[
            InteractionActionSuggestion(label="上前查看", text="我走向那辆马车。")
        ],
    )

    result = await InteractionGenerationWorkflow().finalize_story_task(
        db_session,
        task=task,
        finish_reason="stop",
        metadata=metadata,
    )
    node = (
        await db_session.execute(
            select(InteractionMessageNode).where(
                InteractionMessageNode.id == uuid.UUID(result["node_id"])
            )
        )
    ).scalar_one()
    await db_session.refresh(journey)

    assert journey.title == "廷根雨夜"
    assert journey.title_source == "model"
    assert node.action_suggestions == [{"label": "上前查看", "text": "我走向那辆马车。"}]


async def test_opening_can_clarify_once_without_becoming_story(
    db_session,
) -> None:
    service, journey, attempt, _response = await _create_journey(
        db_session,
        key="create-journey-clarification",
    )
    attempt.status = "running"
    attempt.visible_text = "你说的是哪一个同名世界？可以补充时代，或让我按当前理解开始。"
    attempt.visible_offset = len(attempt.visible_text)
    await db_session.flush()
    db_session.task_checkpoint_enabled = True
    task = _task_for(journey, attempt)
    metadata = InteractionResponseMetadata(
        response_kind="clarification",
        story_ended=True,
        action_suggestions=[
            InteractionActionSuggestion(label="不应出现", text="不应出现")
        ],
    )

    with patch.object(
        InteractionGenerationWorkflow,
        "_summary_is_due",
        autospec=True,
    ) as summary_due:
        result = await InteractionGenerationWorkflow().finalize_story_task(
            db_session,
            task=task,
            finish_reason="stop",
            metadata=metadata,
        )

    clarification = await db_session.get(
        InteractionMessageNode,
        uuid.UUID(result["node_id"]),
    )
    assert clarification is not None
    assert clarification.message_kind == "setup"
    assert clarification.story_ended is False
    assert clarification.action_suggestions == []
    assert journey.setup_clarification_used is True
    assert result["summary_task_id"] is None
    assert result["next_attempt_id"] is None
    summary_due.assert_not_awaited()

    with patch(
        "modules.interaction.services.build_project_llm_execution_snapshot",
        autospec=True,
        return_value=_snapshot_for(journey.novel_id),
    ):
        continued = await service.send_message(
            db_session,
            journey_id=str(journey.id),
            content="按你当前理解开始，但我是普通人。",
            expected_selection_epoch=1,
            idempotency_key="clarification-continue",
        )
    next_attempt = await db_session.get(
        InteractionGenerationAttempt,
        uuid.UUID(continued.attempt.id),
    )
    setup_reply = await db_session.get(
        InteractionMessageNode,
        next_attempt.response_to_node_id,
    )
    assert next_attempt.request_kind == "setup_continue"
    assert setup_reply.message_kind == "setup"

    next_attempt.status = "running"
    next_attempt.visible_text = "港口的晨雾里，你第一次听见远处的钟声。"
    next_attempt.visible_offset = len(next_attempt.visible_text)
    await db_session.flush()
    next_task = _task_for(journey, next_attempt)
    with patch.object(
        InteractionGenerationWorkflow,
        "_summary_is_due",
        autospec=True,
        return_value=False,
    ):
        second = await InteractionGenerationWorkflow().finalize_story_task(
            db_session,
            task=next_task,
            finish_reason="stop",
            metadata=InteractionResponseMetadata(
                response_kind="clarification",
            ),
        )
    story = await db_session.get(
        InteractionMessageNode,
        uuid.UUID(second["node_id"]),
    )
    assert story.message_kind == "story"


async def test_manual_overview_epoch_rejects_late_automatic_summary(
    db_session,
) -> None:
    service, journey, attempt, _response = await _create_journey(
        db_session,
        key="create-journey-overview",
    )
    manual = await service.update_overview(
        db_session,
        journey_id=str(journey.id),
        sections=InteractionOverviewSections(world_and_start="我在廷根担任记者。"),
        expected_overview_epoch=0,
        expected_selection_epoch=0,
    )
    path = await service._repo.get_selected_path(db_session, journey=journey)
    db_session.task_checkpoint_enabled = True
    task = SimpleNamespace(
        id=attempt.task_id,
        meta={"novel_id": str(journey.novel_id)},
        progress=0.0,
        update_progress=lambda value: setattr(task, "progress", value),
    )
    prepared = PreparedSummaryGeneration(
        novel_id=str(journey.novel_id),
        journey_id=str(journey.id),
        path_hash="stale-path",
        node_ids=[str(node.id) for node in path],
        segment_node_ids=[str(node.id) for node in path],
        started_overview_epoch=0,
        messages=[],
        executable_settings={},
    )

    result = await InteractionGenerationWorkflow().finalize_summary_task(
        db_session,
        task=task,
        prepared=prepared,
        output=InteractionSummaryOutput(
            segment_summary="旧的自动回顾",
            overview=InteractionOverviewSections(world_and_start="旧的自动回顾"),
        ),
    )
    head = (
        await db_session.execute(
            select(InteractionOverviewRevision).where(
                InteractionOverviewRevision.id == journey.overview_head_revision_id
            )
        )
    ).scalar_one()

    assert manual.overview_epoch == 1
    assert result == {"status": "stale"}
    assert head.source == "manual"
    assert head.sections == {
        "world_and_start": "我在廷根担任记者。",
        "player_character": "",
        "current_situation": "",
        "important_people_and_factions": "",
        "key_turning_points": "",
        "open_threads": "",
        "must_remember": "",
    }


async def test_manual_rebase_reuses_wider_existing_episode_segment(
    db_session,
) -> None:
    service, journey, attempt, _response = await _create_journey(
        db_session,
        key="manual-rebase-reuses-segment",
    )
    root = (await service._repo.get_selected_path(db_session, journey=journey))[-1]
    story = await _append_selected_node(
        db_session,
        service,
        journey,
        parent=root,
        role="assistant",
        content="记者先收到了没有署名的邀请。",
    )
    await _append_selected_node(
        db_session,
        service,
        journey,
        parent=story,
        role="user",
        content="我检查邀请上的蜡印。",
    )
    path = await service._repo.get_selected_path(db_session, journey=journey)
    selected_hash = path_hash(path)
    existing = InteractionSummarySegment(
        novel_id=journey.novel_id,
        journey_id=journey.id,
        start_node_id=path[0].id,
        end_node_id=path[-1].id,
        path_hash=selected_hash,
        token_count=sum(node.token_estimate for node in path),
        content="已有的同段往事概要。",
        ordinal=1,
        producer={"kind": "model"},
    )
    db_session.add(existing)
    await db_session.flush()
    existing_id = existing.id

    await service.update_overview(
        db_session,
        journey_id=str(journey.id),
        sections=InteractionOverviewSections(
            current_situation="用户修正后的当前局面。",
        ),
        expected_overview_epoch=0,
        expected_selection_epoch=0,
    )
    await db_session.flush()
    await db_session.refresh(journey)
    manual_id = journey.overview_head_revision_id
    manual = await db_session.get(InteractionOverviewRevision, manual_id)
    assert manual is not None
    manual.coverage_anchor_node_id = path[0].id
    manual.coverage_path_hash = path_hash(path[:1])
    prepared = PreparedSummaryGeneration(
        novel_id=str(journey.novel_id),
        journey_id=str(journey.id),
        path_hash=selected_hash,
        node_ids=[str(node.id) for node in path],
        segment_node_ids=[str(node.id) for node in path[1:]],
        started_overview_epoch=journey.overview_epoch,
        messages=[],
        executable_settings={},
    )
    task = _task_for(journey, attempt)
    db_session.task_checkpoint_enabled = True

    invalid_prepared = replace(
        prepared,
        segment_node_ids=[str(path[-1].id)],
    )
    with pytest.raises(RuntimeError, match="start after current overview coverage"):
        await InteractionGenerationWorkflow().finalize_summary_task(
            db_session,
            task=task,
            prepared=invalid_prepared,
            output=InteractionSummaryOutput(
                segment_summary="不能跳过中间节点。",
                overview=InteractionOverviewSections(
                    current_situation="这个结果不能安装。",
                ),
            ),
        )
    result = await InteractionGenerationWorkflow().finalize_summary_task(
        db_session,
        task=task,
        prepared=prepared,
        output=InteractionSummaryOutput(
            segment_summary="这次重放不应再插入 episode row。",
            overview=InteractionOverviewSections(
                current_situation="用户修正后的局面已吸收当前尾部。",
            ),
        ),
    )

    segment_count = (
        await db_session.execute(
            select(func.count(InteractionSummarySegment.id)).where(
                InteractionSummarySegment.journey_id == journey.id
            )
        )
    ).scalar_one()
    head = await db_session.get(
        InteractionOverviewRevision,
        uuid.UUID(result["overview_revision_id"]),
    )
    assert segment_count == 1
    assert result["segment_id"] == str(existing_id)
    assert "checkpoint" not in result
    assert head is not None
    assert head.based_on_revision_id == manual_id
    reuse = head.producer["summary_segment_reuse"]
    assert reuse["exact_range"] is False
    assert reuse["folded_range"] == {
        "start_node_id": str(path[1].id),
        "end_node_id": str(path[-1].id),
        "path_hash": selected_hash,
    }


async def test_best_overview_rejects_farther_stale_automatic_lineage(
    db_session,
) -> None:
    service, journey, attempt, _response = await _create_journey(
        db_session,
        key="overview-authority-lineage",
    )
    root = (await service._repo.get_selected_path(db_session, journey=journey))[-1]
    story = await _append_selected_node(
        db_session,
        service,
        journey,
        parent=root,
        role="assistant",
        content="当前分支继续向前。",
    )
    user = await _append_selected_node(
        db_session,
        service,
        journey,
        parent=story,
        role="user",
        content="我继续追问当前线索。",
    )
    path = await service._repo.get_selected_path(db_session, journey=journey)
    stale_farther = InteractionOverviewRevision(
        novel_id=journey.novel_id,
        journey_id=journey.id,
        anchor_node_id=story.id,
        path_hash=path_hash(path),
        coverage_anchor_node_id=story.id,
        coverage_path_hash=path_hash(path),
        sections={"current_situation": "旧权威链的更远回顾。"},
        source="automatic",
        based_on_revision_id=None,
        started_overview_epoch=0,
        promoted=False,
        producer={"kind": "model"},
    )
    manual = InteractionOverviewRevision(
        novel_id=journey.novel_id,
        journey_id=journey.id,
        anchor_node_id=root.id,
        path_hash=path_hash(path[:1]),
        coverage_anchor_node_id=root.id,
        coverage_path_hash=path_hash(path[:1]),
        sections={"current_situation": "用户修正后的权威。"},
        source="manual",
        based_on_revision_id=None,
        started_overview_epoch=1,
        promoted=False,
        producer={"kind": "user"},
    )
    db_session.add_all([stale_farther, manual])
    await db_session.flush()
    compatible = InteractionOverviewRevision(
        novel_id=journey.novel_id,
        journey_id=journey.id,
        anchor_node_id=root.id,
        path_hash=path_hash(path[:1]),
        coverage_anchor_node_id=root.id,
        coverage_path_hash=path_hash(path[:1]),
        sections={"current_situation": "从用户修正继续形成的回顾。"},
        source="automatic",
        based_on_revision_id=manual.id,
        started_overview_epoch=2,
        promoted=False,
        producer={"kind": "model"},
    )
    db_session.add(compatible)
    await db_session.flush()

    best = await service._best_overview_for_path(  # noqa: SLF001
        db_session,
        journey=journey,
        path=path,
    )

    assert best is not None
    assert best.id == compatible.id
    assert best.id != stale_farther.id

    stale_farther.promoted = True
    journey.overview_head_revision_id = stale_farther.id
    journey.overview_epoch = 3
    attempt.response_to_node_id = user.id
    attempt.context_path_hash = path_hash(path)
    attempt.context_node_ids = [str(user.id)]
    await db_session.flush()
    db_session.task_checkpoint_enabled = True
    with patch(
        "modules.interaction.generation.restore_project_llm_execution_settings",
        autospec=True,
        return_value={"llm": {"model": "deepseek-v4-flash"}},
    ):
        prepared = await InteractionGenerationWorkflow().prepare_story_task(
            db_session,
            task=_task_for(journey, attempt),
        )

    prompt = "\n".join(message.content for message in prepared.messages)
    assert "从用户修正继续形成的回顾" in prompt
    assert "旧权威链的更远回顾" not in prompt


async def test_empty_model_overview_is_rejected_without_replacing_head(
    db_session,
) -> None:
    service, journey, _attempt, _response = await _create_journey(
        db_session,
        key="empty-model-overview",
    )
    await service.update_overview(
        db_session,
        journey_id=str(journey.id),
        sections=InteractionOverviewSections(
            current_situation="这份有效回顾必须继续保留。",
        ),
        expected_overview_epoch=0,
        expected_selection_epoch=0,
    )
    await db_session.flush()
    head_id = journey.overview_head_revision_id

    with pytest.raises(PydanticValidationError, match="模型回顾不能全部为空"):
        InteractionSummaryOutput(
            segment_summary="模型只生成了分段文本。",
            overview=InteractionOverviewSections(),
        )

    await db_session.refresh(journey)
    assert journey.overview_head_revision_id == head_id
    head = await db_session.get(InteractionOverviewRevision, head_id)
    assert head is not None
    assert head.sections["current_situation"] == "这份有效回顾必须继续保留。"


async def test_automatic_summary_keeps_segment_and_total_overview_distinct(
    db_session,
) -> None:
    service, journey, attempt, _response = await _create_journey(
        db_session,
        key="create-journey-summary-distinct",
    )
    opening = (await service._repo.get_selected_path(db_session, journey=journey))[-1]
    story = InteractionMessageNode(
        novel_id=journey.novel_id,
        journey_id=journey.id,
        parent_node_id=opening.id,
        role="assistant",
        content="报社门外的马车送来一封没有署名的邀请。",
        token_estimate=24,
    )
    db_session.add(story)
    await db_session.flush()
    await service._repo.set_selected_child(
        db_session,
        journey=journey,
        parent_node_id=opening.id,
        child_node_id=story.id,
    )
    journey.selected_leaf_node_id = story.id
    path = await service._repo.get_selected_path(db_session, journey=journey)
    db_session.task_checkpoint_enabled = True
    task = SimpleNamespace(
        id=attempt.task_id,
        meta={"llm_execution_snapshot": dict(attempt.llm_execution_snapshot)},
        progress=0.0,
        update_progress=lambda value: setattr(task, "progress", value),
    )
    prepared = PreparedSummaryGeneration(
        novel_id=str(journey.novel_id),
        journey_id=str(journey.id),
        path_hash=path_hash(path),
        node_ids=[str(node.id) for node in path],
        segment_node_ids=[str(node.id) for node in path],
        started_overview_epoch=0,
        messages=[],
        executable_settings={
            "llm": {
                "provider_id": "deepseek",
                "model": "deepseek-v4-flash",
                "api_key": "must-not-be-persisted",
            }
        },
        estimated_input_tokens=321,
    )

    workflow = InteractionGenerationWorkflow()
    with patch.object(
        workflow._repo,  # noqa: SLF001 - checkpoint cadence seam
        "list_summary_segments",
        autospec=True,
        return_value=[
            SimpleNamespace(
                end_node_id=story.id,
                path_hash=path_hash(path),
            )
            for _ in range(7)
        ],
    ):
        result = await workflow.finalize_summary_task(
            db_session,
            task=task,
            prepared=prepared,
            output=InteractionSummaryOutput(
                segment_summary="记者收到一封匿名邀请。",
                overview=InteractionOverviewSections(
                    world_and_start="我以记者身份来到廷根。",
                    current_situation="一辆马车送来匿名邀请。",
                    open_threads="邀请者的身份与目的仍不明确。",
                ),
            ),
            diagnostics=[
                {
                    "kind": "structured_usage",
                    "status": "succeeded",
                    "completion_tokens": 77,
                }
            ],
        )
    segment = (
        await db_session.execute(
            select(InteractionSummarySegment).where(
                InteractionSummarySegment.id == uuid.UUID(result["segment_id"])
            )
        )
    ).scalar_one()
    head = await service._repo.get_overview_head(db_session, journey=journey)

    assert segment.content == "记者收到一封匿名邀请。"
    assert segment.start_node_id == opening.id
    assert segment.end_node_id == story.id
    assert segment.token_count == sum(node.token_estimate for node in path)
    expected_producer = {
        "kind": "model",
        "provider_id": "deepseek",
        "model": "deepseek-v4-flash",
        "prompt_version": "interaction-summary-v1",
        "schema_version": "interaction-summary-output-v1",
        "estimated_input_tokens": 321,
        "completion_tokens": 77,
        "call_attempts": 1,
    }
    assert "checkpoint" not in result
    assert segment.ordinal == 8
    assert segment.producer == expected_producer
    assert segment.based_on_overview_revision_id is None
    assert segment.based_on_checkpoint_revision_id is None
    assert "api_key" not in str(segment.producer)
    assert head is not None
    assert head.producer == expected_producer
    assert head.sections["current_situation"] == "一辆马车送来匿名邀请。"
    assert head.sections["open_threads"] == "邀请者的身份与目的仍不明确。"
    assert head.sections.get("segment_summary") is None

    tail = await _append_selected_node(
        db_session,
        service,
        journey,
        parent=story,
        role="user",
        content="我先检查信封上的蜡印。",
    )
    tail_id = tail.id
    current_path = await service._repo.get_selected_path(
        db_session,
        journey=journey,
    )
    next_task = SimpleNamespace(
        id=uuid.uuid4(),
        meta={},
        progress=0.0,
    )
    next_task.update_progress = lambda value: setattr(next_task, "progress", value)
    next_prepared = PreparedSummaryGeneration(
        novel_id=str(journey.novel_id),
        journey_id=str(journey.id),
        path_hash=path_hash(current_path),
        node_ids=[str(node.id) for node in current_path],
        segment_node_ids=[str(tail_id)],
        segment_path_hash=path_hash(current_path),
        started_overview_epoch=journey.overview_epoch,
        messages=[],
        executable_settings={},
    )

    next_result = await workflow.finalize_summary_task(
        db_session,
        task=next_task,
        prepared=next_prepared,
        output=InteractionSummaryOutput(
            segment_summary="记者检查了匿名信的蜡印。",
            overview=InteractionOverviewSections(
                world_and_start="我以记者身份来到廷根。",
                current_situation="我正在检查匿名邀请的蜡印。",
                open_threads="邀请者的身份与目的仍不明确。",
            ),
        ),
    )
    next_segment = await db_session.get(
        InteractionSummarySegment,
        uuid.UUID(next_result["segment_id"]),
    )
    assert next_segment is not None
    assert next_segment.based_on_overview_revision_id == uuid.UUID(
        result["overview_revision_id"]
    )
    assert next_segment.based_on_checkpoint_revision_id is None
    assert "memory_checkpoint_base_revision_id" not in next_segment.producer


async def test_prepare_summary_reads_manual_baseline_and_only_new_tail(
    db_session,
) -> None:
    service, journey, attempt, _response = await _create_journey(
        db_session,
        key="create-journey-summary-tail",
    )
    await service.update_overview(
        db_session,
        journey_id=str(journey.id),
        sections=InteractionOverviewSections(
            world_and_start="用户确认的起点。",
            must_remember="A 的立场仍然可疑。",
        ),
        expected_overview_epoch=0,
        expected_selection_epoch=0,
    )
    opening = (await service._repo.get_selected_path(db_session, journey=journey))[-1]
    story = InteractionMessageNode(
        novel_id=journey.novel_id,
        journey_id=journey.id,
        parent_node_id=opening.id,
        role="assistant",
        content="A 提供了一条线索，但拒绝解释来源。",
        token_estimate=20_000,
    )
    db_session.add(story)
    await db_session.flush()
    await service._repo.set_selected_child(
        db_session,
        journey=journey,
        parent_node_id=opening.id,
        child_node_id=story.id,
    )
    journey.selected_leaf_node_id = story.id
    recent_user = await _append_selected_node(
        db_session,
        service,
        journey,
        parent=story,
        role="user",
        content="我先观察 A 是否还在隐瞒。",
    )
    recent_user.token_estimate = 100
    recent_story = await _append_selected_node(
        db_session,
        service,
        journey,
        parent=recent_user,
        role="assistant",
        content="A 沉默着看向门外，没有立刻回答。",
    )
    recent_story.token_estimate = 16_000
    await db_session.flush()
    story_id = str(story.id)
    recent_user_id = str(recent_user.id)
    recent_story_id = str(recent_story.id)
    opening_content = opening.content
    path = await service._repo.get_selected_path(db_session, journey=journey)
    story_prefix_hash = path_hash(path[: path.index(story) + 1])
    db_session.task_checkpoint_enabled = True
    task = SimpleNamespace(
        id=uuid.uuid4(),
        meta={
            "novel_id": str(journey.novel_id),
            "journey_id": str(journey.id),
            "path_hash": path_hash(path),
            "node_ids": [str(node.id) for node in path],
            "started_overview_epoch": 1,
            "llm_execution_snapshot": dict(attempt.llm_execution_snapshot),
        },
        progress=0.0,
        update_progress=lambda value: setattr(task, "progress", value),
    )
    with patch(
        "modules.interaction.generation.restore_project_llm_execution_settings",
        autospec=True,
        return_value={"llm": {"model": "deepseek-v4-flash"}},
    ):
        prepared = await InteractionGenerationWorkflow().prepare_summary_task(
            db_session,
            task=task,
        )

    assert prepared is not None
    assert prepared.segment_node_ids == [story_id]
    assert prepared.segment_path_hash == story_prefix_hash
    assert prepared.protected_node_ids == [
        recent_user_id,
        recent_story_id,
    ]
    prompt = prepared.messages[-1].content
    assert "用户确认的起点。" in prompt
    assert "A 的立场仍然可疑。" in prompt
    assert "A 提供了一条线索" in prompt
    assert "A 沉默着看向门外" not in prompt
    assert "不得恢复该修正删除或改写的旧当前值" in prompt
    assert opening_content not in prompt

    result = await InteractionGenerationWorkflow().finalize_summary_task(
        db_session,
        task=task,
        prepared=prepared,
        output=InteractionSummaryOutput(
            segment_summary="A 提供线索但仍有所隐瞒。",
            overview=InteractionOverviewSections(
                world_and_start="用户确认的起点。",
                current_situation="A 刚提供一条来源不明的线索。",
                must_remember="A 的立场仍然可疑。",
            ),
        ),
    )
    segment = await db_session.get(
        InteractionSummarySegment,
        uuid.UUID(result["segment_id"]),
    )
    revision = await db_session.get(
        InteractionOverviewRevision,
        uuid.UUID(result["overview_revision_id"]),
    )
    assert segment is not None
    assert segment.path_hash == story_prefix_hash
    assert segment.end_node_id == uuid.UUID(story_id)
    assert revision is not None
    assert revision.coverage_anchor_node_id == uuid.UUID(story_id)
    assert revision.coverage_path_hash == story_prefix_hash
    refreshed_path = await service._repo.get_selected_path(
        db_session,
        journey=await db_session.get(InteractionJourney, uuid.UUID(prepared.journey_id)),
    )
    story_messages = compile_story_messages(
        path=refreshed_path,
        overview=render_overview_sections(revision.sections),
        overview_anchor_node_id=str(revision.coverage_anchor_node_id),
        see_sea_enabled=False,
        action_options_enabled=False,
        request_kind="message",
    )
    assert [(item.role, item.content) for item in story_messages[-2:]] == [
        ("user", "我先观察 A 是否还在隐瞒。"),
        ("assistant", "A 沉默着看向门外，没有立刻回答。"),
    ]


async def test_non_reducing_summary_does_not_advance_coverage(db_session) -> None:
    service, journey, attempt, _response = await _create_journey(
        db_session,
        key="summary-must-reduce",
    )
    path = await service._repo.get_selected_path(db_session, journey=journey)
    prepared = PreparedSummaryGeneration(
        novel_id=str(journey.novel_id),
        journey_id=str(journey.id),
        path_hash=path_hash(path),
        node_ids=[str(node.id) for node in path],
        segment_node_ids=[str(node.id) for node in path],
        segment_path_hash=path_hash(path),
        started_overview_epoch=journey.overview_epoch,
        messages=[],
        executable_settings={},
        compaction_source_tokens=200,
    )
    db_session.task_checkpoint_enabled = True

    with pytest.raises(InteractionContextBudgetError, match="did not reduce"):
        await InteractionGenerationWorkflow().finalize_summary_task(
            db_session,
            task=_task_for(journey, attempt),
            prepared=prepared,
            output=InteractionSummaryOutput(
                segment_summary="没有缩短。",
                overview=InteractionOverviewSections(
                    current_situation="长" * 200,
                ),
            ),
        )

    assert (
        await service._repo.count_summary_segments(
            db_session,
            journey=journey,
        )
        == 0
    )
    assert journey.overview_head_revision_id is None


async def test_two_prefix_summary_passes_are_contiguous_and_keep_suffix_raw(
    db_session,
) -> None:
    service, journey, _attempt, _response = await _create_journey(
        db_session,
        key="two-prefix-summary-passes",
    )
    await service.update_overview(
        db_session,
        journey_id=str(journey.id),
        sections=InteractionOverviewSections(current_situation="安全起点。"),
        expected_overview_epoch=0,
        expected_selection_epoch=0,
    )
    opening = (await service._repo.get_selected_path(db_session, journey=journey))[-1]
    old_one = await _append_selected_node(
        db_session,
        service,
        journey,
        parent=opening,
        role="assistant",
        content="第一段旧发展。",
    )
    old_one.token_estimate = 140_000
    old_two = await _append_selected_node(
        db_session,
        service,
        journey,
        parent=old_one,
        role="assistant",
        content="第二段旧发展。",
    )
    old_two.token_estimate = 140_000
    recent_user = await _append_selected_node(
        db_session,
        service,
        journey,
        parent=old_two,
        role="user",
        content="保留这条当前请求。",
    )
    recent_user.token_estimate = 100
    recent_story = await _append_selected_node(
        db_session,
        service,
        journey,
        parent=recent_user,
        role="assistant",
        content="保留这段最近回应。",
    )
    recent_story.token_estimate = 16_000
    await db_session.flush()
    path = await service._repo.get_selected_path(db_session, journey=journey)
    full_hash = path_hash(path)
    task = SimpleNamespace(
        id=uuid.uuid4(),
        meta={},
        progress=0.0,
        update_progress=lambda value: setattr(task, "progress", value),
    )
    db_session.task_checkpoint_enabled = True
    workflow = InteractionGenerationWorkflow()

    with patch(
        "modules.interaction.generation.restore_project_llm_execution_settings",
        autospec=True,
        return_value={"llm": {"model": "deepseek-v4-flash"}},
    ):
        first = await workflow._prepare_summary_generation(  # noqa: SLF001
            db_session,
            journey=journey,
            current_path=path,
            expected_path_hash=full_hash,
            started_epoch=journey.overview_epoch,
            snapshot=_snapshot_for(journey.novel_id),
        )
        assert first is not None
        first_result = await workflow.finalize_summary_task(
            db_session,
            task=task,
            prepared=first,
            output=InteractionSummaryOutput(
                segment_summary="第一段旧发展。",
                overview=InteractionOverviewSections(
                    current_situation="已整理第一段旧发展。"
                ),
            ),
        )
        second = await workflow._prepare_summary_generation(  # noqa: SLF001
            db_session,
            journey=journey,
            current_path=path,
            expected_path_hash=full_hash,
            started_epoch=journey.overview_epoch,
            snapshot=_snapshot_for(journey.novel_id),
        )
        assert second is not None
        second_result = await workflow.finalize_summary_task(
            db_session,
            task=task,
            prepared=second,
            output=InteractionSummaryOutput(
                segment_summary="第二段旧发展。",
                overview=InteractionOverviewSections(
                    current_situation="两段旧发展均已整理。"
                ),
            ),
        )

    assert first.segment_node_ids == [str(old_one.id)]
    assert second.segment_node_ids == [str(old_two.id)]
    assert "不得恢复该修正删除或改写的旧当前值" in second.messages[-1].content
    assert (
        first.protected_node_ids
        == second.protected_node_ids
        == [
            str(recent_user.id),
            str(recent_story.id),
        ]
    )
    first_revision = await db_session.get(
        InteractionOverviewRevision,
        uuid.UUID(first_result["overview_revision_id"]),
    )
    second_revision = await db_session.get(
        InteractionOverviewRevision,
        uuid.UUID(second_result["overview_revision_id"]),
    )
    assert first_revision is not None
    assert second_revision is not None
    assert first_revision.coverage_anchor_node_id == old_one.id
    assert second_revision.coverage_anchor_node_id == old_two.id
    assert second_revision.based_on_revision_id == first_revision.id
    assert (
        await service._repo.count_summary_segments(
            db_session,
            journey=journey,
        )
        == 2
    )


async def test_single_old_node_over_summary_ceiling_fails_closed(db_session) -> None:
    service, journey, attempt, _response = await _create_journey(
        db_session,
        key="single-node-summary-ceiling",
    )
    await service.update_overview(
        db_session,
        journey_id=str(journey.id),
        sections=InteractionOverviewSections(current_situation="安全基线。"),
        expected_overview_epoch=0,
        expected_selection_epoch=0,
    )
    opening = (await service._repo.get_selected_path(db_session, journey=journey))[-1]
    huge = await _append_selected_node(
        db_session,
        service,
        journey,
        parent=opening,
        role="assistant",
        content="一个不能拆开的超长旧节点。",
    )
    huge.token_estimate = 300_000
    recent_user = await _append_selected_node(
        db_session,
        service,
        journey,
        parent=huge,
        role="user",
        content="继续。",
    )
    recent_user.token_estimate = 100
    recent_story = await _append_selected_node(
        db_session,
        service,
        journey,
        parent=recent_user,
        role="assistant",
        content="最近发展保持原文。",
    )
    recent_story.token_estimate = 16_000
    await db_session.flush()
    path = await service._repo.get_selected_path(db_session, journey=journey)
    task = SimpleNamespace(
        id=uuid.uuid4(),
        meta={
            "novel_id": str(journey.novel_id),
            "journey_id": str(journey.id),
            "path_hash": path_hash(path),
            "selected_leaf_node_id": str(path[-1].id),
            "started_overview_epoch": journey.overview_epoch,
            "llm_execution_snapshot": dict(attempt.llm_execution_snapshot),
        },
        progress=0.0,
        update_progress=lambda value: setattr(task, "progress", value),
    )
    db_session.task_checkpoint_enabled = True

    with pytest.raises(InteractionContextBudgetError, match="one interaction node"):
        await InteractionGenerationWorkflow().prepare_summary_task(
            db_session,
            task=task,
        )


async def test_failed_overview_latches_branch_until_explicit_retry(
    db_session,
) -> None:
    service, journey, attempt, _response = await _create_journey(
        db_session,
        key="create-overview-failure-latch",
    )
    opening = (await service._repo.get_selected_path(db_session, journey=journey))[-1]
    story = await _append_selected_node(
        db_session,
        service,
        journey,
        parent=opening,
        role="assistant",
        content="码头的追踪暂时失去了方向。",
    )
    path = await service._repo.get_selected_path(db_session, journey=journey)
    task = SimpleNamespace(
        id=uuid.uuid4(),
        meta={},
        progress=0.0,
    )
    task.update_progress = lambda value: setattr(task, "progress", value)
    prepared = PreparedSummaryGeneration(
        novel_id=str(journey.novel_id),
        journey_id=str(journey.id),
        path_hash=path_hash(path),
        node_ids=[str(node.id) for node in path],
        segment_node_ids=[str(node.id) for node in path],
        started_overview_epoch=journey.overview_epoch,
        messages=[],
        executable_settings={},
    )
    journey_id = str(journey.id)
    db_session.task_checkpoint_enabled = True
    workflow = InteractionGenerationWorkflow()

    await workflow.mark_summary_failed(
        db_session,
        task=task,
        prepared=prepared,
    )
    failed = await service.get_overview(
        db_session,
        journey_id=journey_id,
    )
    tail = await _append_selected_node(
        db_session,
        service,
        journey,
        parent=story,
        role="user",
        content="我决定先回报社整理已有线索。",
    )
    extended_path = await service._repo.get_selected_path(
        db_session,
        journey=journey,
    )

    assert failed.status == "failed"
    assert (
        await workflow._summary_is_due(  # noqa: SLF001 - retry latch contract
            db_session,
            journey,
            extended_path,
        )
        is False
    )

    with patch(
        "modules.interaction.services.build_project_llm_execution_snapshot",
        autospec=True,
        return_value=_snapshot_for(journey.novel_id),
    ):
        retried = await service.retry_overview(
            db_session,
            journey_id=journey_id,
        )

    assert tail.id == extended_path[-1].id
    assert retried.status == "refreshing"
    assert journey.overview_failure == {}
    summary_task = (
        await db_session.execute(
            select(AsyncTask)
            .where(AsyncTask.task_type == "interaction_summary_refresh")
            .order_by(AsyncTask.created_at.desc())
            .limit(1)
        )
    ).scalar_one()
    assert summary_task.meta["selected_leaf_node_id"] == str(extended_path[-1].id)
    assert "node_ids" not in summary_task.meta


async def test_summary_preparation_failure_can_retry_after_reconnect(
    db_session,
) -> None:
    service, journey, _attempt, _response = await _create_journey(
        db_session,
        key="create-summary-preparation-failure",
    )
    opening = (await service._repo.get_selected_path(db_session, journey=journey))[-1]
    await _append_selected_node(
        db_session,
        service,
        journey,
        parent=opening,
        role="assistant",
        content="第一幕故事已经发生，但后台整理时连接失效。",
    )
    path = await service._repo.get_selected_path(db_session, journey=journey)
    task = SimpleNamespace(
        id=uuid.uuid4(),
        meta={
            "novel_id": str(journey.novel_id),
            "journey_id": str(journey.id),
            "path_hash": path_hash(path),
            "selected_leaf_node_id": str(path[-1].id),
            "started_overview_epoch": journey.overview_epoch,
        },
        progress=0.0,
    )
    task.update_progress = lambda value: setattr(task, "progress", value)
    db_session.task_checkpoint_enabled = True

    await InteractionGenerationWorkflow().mark_summary_task_failed(
        db_session,
        task=task,
    )
    failed = await service.get_overview(
        db_session,
        journey_id=str(task.meta["journey_id"]),
    )
    assert failed.status == "failed"

    with patch(
        "modules.interaction.services.build_project_llm_execution_snapshot",
        autospec=True,
        return_value=_snapshot_for(uuid.UUID(task.meta["novel_id"])),
    ):
        retried = await service.retry_overview(
            db_session,
            journey_id=str(task.meta["journey_id"]),
        )

    assert retried.status == "refreshing"


async def test_selection_epoch_conflict_preserves_existing_branch(
    db_session,
) -> None:
    service, journey, _attempt, _response = await _create_journey(
        db_session,
        key="create-journey-conflict",
    )

    with pytest.raises(ConflictError) as exc:
        await service.select_branch(
            db_session,
            journey_id=str(journey.id),
            node_id=str(journey.selected_leaf_node_id),
            expected_selection_epoch=99,
        )

    assert exc.value.code == "interaction_selection_conflict"
    assert exc.value.context == {"current_selection_epoch": 0}


async def test_ancestry_supports_more_than_one_thousand_nodes(
    db_session,
) -> None:
    service, journey, attempt, _response = await _create_journey(
        db_session,
        key="create-long-ancestry",
    )
    attempt.status = "completed"
    root = (await service._repo.get_selected_path(db_session, journey=journey))[-1]
    nodes: list[InteractionMessageNode] = []
    parent = root
    for index in range(1005):
        node = InteractionMessageNode(
            id=uuid.uuid4(),
            novel_id=journey.novel_id,
            journey_id=journey.id,
            parent_node_id=parent.id,
            role="assistant" if index % 2 == 0 else "user",
            message_kind="story",
            content=f"长期旅程节点 {index}",
            completion_state="complete",
            token_estimate=4,
        )
        nodes.append(node)
        parent = node
    db_session.add_all(nodes)
    await db_session.flush()

    ancestry = await service._repo.get_ancestry(
        db_session,
        journey=journey,
        node=nodes[-1],
    )

    assert len(ancestry) == 1006
    assert ancestry[0].id == root.id
    assert ancestry[-1].id == nodes[-1].id


async def test_expired_see_sea_heartbeat_closes_loop_without_new_attempt(
    db_session,
) -> None:
    service, journey, attempt, _response = await _create_journey(
        db_session,
        key="create-journey-expired-heartbeat",
    )
    attempt.status = "completed"
    journey.see_sea_enabled = True
    journey.see_sea_last_heartbeat_at = datetime.now(UTC) - timedelta(seconds=61)
    await db_session.flush()

    with patch(
        "modules.interaction.services.build_project_llm_execution_snapshot",
        autospec=True,
    ) as snapshot:
        response = await service.heartbeat(
            db_session,
            journey_id=str(journey.id),
        )

    assert response.accepted is False
    assert response.see_sea_enabled is False
    assert journey.see_sea_enabled is False
    assert journey.see_sea_last_heartbeat_at is None
    snapshot.assert_not_awaited()
    attempts = (
        await db_session.execute(
            select(InteractionGenerationAttempt).where(
                InteractionGenerationAttempt.journey_id == journey.id
            )
        )
    ).scalars()
    assert len(list(attempts)) == 1


async def test_heartbeat_starts_waiting_see_sea_and_failed_step_can_retry(
    db_session,
) -> None:
    service, journey, opening_attempt, _response = await _create_journey(
        db_session,
        key="create-journey-heartbeat-start",
    )
    opening_attempt.status = "completed"
    root = (await service._repo.get_selected_path(db_session, journey=journey))[-1]
    story = await _append_selected_node(
        db_session,
        service,
        journey,
        parent=root,
        role="assistant",
        content="港口的第一声汽笛已经拉开故事。",
    )
    story.created_at = datetime.now(UTC) - timedelta(seconds=2)
    opening_attempt.result_node_id = story.id
    journey.see_sea_enabled = True
    journey.see_sea_last_heartbeat_at = datetime.now(UTC)
    await db_session.flush()

    with patch(
        "modules.interaction.services.build_project_llm_execution_snapshot",
        autospec=True,
        return_value=_snapshot_for(journey.novel_id),
    ):
        first = await service.heartbeat(
            db_session,
            journey_id=str(journey.id),
        )

    assert first.accepted is True
    assert first.attempt is not None
    first_attempt = (
        await db_session.execute(
            select(InteractionGenerationAttempt).where(
                InteractionGenerationAttempt.id == uuid.UUID(first.attempt.id)
            )
        )
    ).scalar_one()
    assert first_attempt.request_kind == "see_sea"
    first_attempt.status = "failed"
    journey.see_sea_enabled = False
    journey.see_sea_last_heartbeat_at = None
    await db_session.flush()

    with patch(
        "modules.interaction.services.build_project_llm_execution_snapshot",
        autospec=True,
        return_value=_snapshot_for(journey.novel_id),
    ):
        retried = await service.update_modes(
            db_session,
            journey_id=str(journey.id),
            see_sea_enabled=True,
            action_options_enabled=None,
            expected_selection_epoch=journey.selection_epoch,
        )

    assert retried.attempt is not None
    assert retried.attempt.id != str(first_attempt.id)


async def test_see_sea_adopts_running_attempt_and_auto_finishes_length(
    db_session,
) -> None:
    service, journey, attempt, _response = await _create_journey(
        db_session,
        key="create-see-sea-adopt-running",
    )
    attempt.status = "running"
    attempt.visible_text = "这段普通生成在开启看海后到达长度边界。"
    attempt.visible_offset = len(attempt.visible_text)
    await db_session.flush()

    adopted = await service.update_modes(
        db_session,
        journey_id=str(journey.id),
        see_sea_enabled=True,
        action_options_enabled=None,
        expected_selection_epoch=journey.selection_epoch,
    )
    assert adopted.attempt is not None
    assert adopted.attempt.id == str(attempt.id)
    assert attempt.usage["see_sea_adopted"] is True

    db_session.task_checkpoint_enabled = True
    result = await InteractionGenerationWorkflow().finalize_story_task(
        db_session,
        task=_task_for(journey, attempt),
        finish_reason="length",
        metadata=None,
    )

    assert result["status"] == "pending"
    assert attempt.request_kind == "see_sea_continue"
    assert journey.see_sea_enabled is True


async def test_see_sea_adopts_awaiting_length_on_the_same_attempt(
    db_session,
) -> None:
    service, journey, attempt, _response = await _create_journey(
        db_session,
        key="adopt-awaiting-length",
    )
    attempt.status = "awaiting_continue"
    attempt.visible_text = "普通生成在这里碰到长度边界。"
    attempt.visible_offset = len(attempt.visible_text)
    await db_session.flush()

    adopted = await service.update_modes(
        db_session,
        journey_id=str(journey.id),
        see_sea_enabled=True,
        action_options_enabled=None,
        expected_selection_epoch=journey.selection_epoch,
    )

    assert adopted.attempt is not None
    assert adopted.attempt.id == str(attempt.id)
    assert attempt.status == "pending"
    assert attempt.request_kind == "see_sea_continue"
    assert attempt.continuation_count == 1
    assert attempt.usage["see_sea_adopted"] is True

    attempt.status = "running"
    attempt.visible_text += "它在同一节拍内自然写完。"
    attempt.visible_offset = len(attempt.visible_text)
    db_session.task_checkpoint_enabled = True
    with patch.object(
        InteractionGenerationWorkflow,
        "_summary_is_due",
        autospec=True,
        return_value=False,
    ):
        finalized = await InteractionGenerationWorkflow().finalize_story_task(
            db_session,
            task=_task_for(journey, attempt),
            finish_reason="stop",
            metadata=None,
        )
    story = await db_session.get(
        InteractionMessageNode,
        uuid.UUID(finalized["node_id"]),
    )
    assert story is not None
    story.created_at = datetime.now(UTC) - timedelta(seconds=2)
    await db_session.flush()

    with patch(
        "modules.interaction.services.build_project_llm_execution_snapshot",
        autospec=True,
        return_value=_snapshot_for(journey.novel_id),
    ):
        heartbeat = await service.heartbeat(
            db_session,
            journey_id=str(journey.id),
        )
    assert heartbeat.attempt is not None
    next_attempt = await db_session.get(
        InteractionGenerationAttempt,
        uuid.UUID(heartbeat.attempt.id),
    )
    assert next_attempt is not None
    assert next_attempt.id != attempt.id
    assert next_attempt.request_kind == "see_sea"


async def test_see_sea_awaiting_length_waits_for_account_capacity(
    db_session,
) -> None:
    service, journey, attempt, _response = await _create_journey(
        db_session,
        key="awaiting-length-capacity",
    )
    attempt.status = "awaiting_continue"
    attempt.visible_text = "已有正文等待续完。"
    attempt.visible_offset = len(attempt.visible_text)
    await db_session.flush()

    with patch.object(
        service,
        "_require_generation_slot",
        autospec=True,
        side_effect=ConflictError(
            "账户已有 8 段故事正在生成，请稍后再试",
            code="interaction_concurrency_limit",
        ),
    ):
        waiting = await service.update_modes(
            db_session,
            journey_id=str(journey.id),
            see_sea_enabled=True,
            action_options_enabled=None,
            expected_selection_epoch=journey.selection_epoch,
        )

    assert waiting.attempt is not None
    assert waiting.attempt.status == "awaiting_continue"
    assert journey.see_sea_enabled is True

    heartbeat = await service.heartbeat(
        db_session,
        journey_id=str(journey.id),
    )
    assert heartbeat.attempt is not None
    assert heartbeat.attempt.status == "pending"
    assert attempt.request_kind == "see_sea_continue"


async def test_disabling_see_sea_finishes_adopted_beat_without_actions(
    db_session,
) -> None:
    service, journey, attempt, _response = await _create_journey(
        db_session,
        key="disable-see-sea-after-current-beat",
    )
    attempt.status = "running"
    attempt.visible_text = "这段普通生成在开启看海后到达长度边界。"
    attempt.visible_offset = len(attempt.visible_text)
    await db_session.flush()
    await service.update_modes(
        db_session,
        journey_id=str(journey.id),
        see_sea_enabled=True,
        action_options_enabled=True,
        expected_selection_epoch=journey.selection_epoch,
    )
    await service.update_modes(
        db_session,
        journey_id=str(journey.id),
        see_sea_enabled=False,
        action_options_enabled=None,
        expected_selection_epoch=journey.selection_epoch,
    )

    assert attempt.usage["see_sea_adopted"] is True
    assert journey.see_sea_enabled is False
    db_session.task_checkpoint_enabled = True
    first = await InteractionGenerationWorkflow().finalize_story_task(
        db_session,
        task=_task_for(journey, attempt),
        finish_reason="length",
        metadata=None,
    )
    assert first["status"] == "pending"
    assert attempt.request_kind == "see_sea_continue"

    attempt.status = "running"
    attempt.visible_text += "随后它在当前节拍内自然收束。"
    attempt.visible_offset = len(attempt.visible_text)
    db_session.task_checkpoint_enabled = True
    with patch.object(
        InteractionGenerationWorkflow,
        "_summary_is_due",
        autospec=True,
        return_value=False,
    ):
        finalized = await InteractionGenerationWorkflow().finalize_story_task(
            db_session,
            task=_task_for(journey, attempt),
            finish_reason="stop",
            metadata=InteractionResponseMetadata(
                action_suggestions=[
                    InteractionActionSuggestion(
                        label="不应出现",
                        text="不应出现",
                    )
                ],
            ),
        )
    node = await db_session.get(
        InteractionMessageNode,
        uuid.UUID(finalized["node_id"]),
    )

    assert node is not None
    assert node.action_suggestions == []
    assert journey.see_sea_enabled is False
    assert journey.see_sea_last_heartbeat_at is None


async def test_see_sea_adopted_attempt_failure_stops_loop(
    db_session,
) -> None:
    service, journey, attempt, _response = await _create_journey(
        db_session,
        key="create-see-sea-adopt-failure",
    )
    attempt.status = "running"
    await db_session.flush()
    await service.update_modes(
        db_session,
        journey_id=str(journey.id),
        see_sea_enabled=True,
        action_options_enabled=None,
        expected_selection_epoch=journey.selection_epoch,
    )
    journey_id = journey.id
    attempt_id = attempt.id
    db_session.task_checkpoint_enabled = True

    await InteractionGenerationWorkflow().fail_story_task(
        db_session,
        task=_task_for(journey, attempt),
        error=LLMContentFilterError("blocked"),
    )
    persisted_journey = await db_session.get(InteractionJourney, journey_id)
    persisted_attempt = await db_session.get(
        InteractionGenerationAttempt,
        attempt_id,
    )

    assert persisted_journey is not None
    assert persisted_journey.see_sea_enabled is False
    assert persisted_journey.see_sea_last_heartbeat_at is None
    assert persisted_attempt is not None
    assert persisted_attempt.status == "failed"


async def test_first_see_sea_length_cutoff_continues_same_attempt(
    db_session,
) -> None:
    _service, journey, attempt, _response = await _create_journey(
        db_session,
        key="create-journey-see-sea-length",
    )
    old_task_id = attempt.task_id
    attempt.status = "running"
    attempt.request_kind = "see_sea"
    attempt.visible_text = "雨幕中的追逐尚未结束。"
    attempt.visible_offset = len(attempt.visible_text)
    journey.see_sea_enabled = True
    journey.see_sea_last_heartbeat_at = datetime.now(UTC)
    await db_session.flush()
    db_session.task_checkpoint_enabled = True
    task = _task_for(journey, attempt)

    result = await InteractionGenerationWorkflow().finalize_story_task(
        db_session,
        task=task,
        finish_reason="length",
        metadata=None,
    )

    assert result["status"] == "pending"
    assert result["attempt_id"] == str(attempt.id)
    assert attempt.status == "pending"
    assert attempt.request_kind == "see_sea_continue"
    assert attempt.continuation_count == 1
    assert attempt.task_id != old_task_id
    assistant_count = (
        await db_session.execute(
            select(func.count(InteractionMessageNode.id)).where(
                InteractionMessageNode.journey_id == journey.id,
                InteractionMessageNode.role == "assistant",
            )
        )
    ).scalar_one()
    assert assistant_count == 0


@pytest.mark.parametrize(
    ("request_kind", "see_sea_enabled"),
    [
        ("message", False),
        ("see_sea", True),
    ],
)
async def test_empty_length_response_fails_without_continuation(
    db_session,
    request_kind: str,
    see_sea_enabled: bool,
) -> None:
    _service, journey, attempt, _response = await _create_journey(
        db_session,
        key=f"empty-length-{request_kind}",
    )
    attempt.status = "running"
    attempt.request_kind = request_kind
    attempt.visible_text = ""
    attempt.visible_offset = 0
    original_task_id = attempt.task_id
    journey.see_sea_enabled = see_sea_enabled
    journey.see_sea_last_heartbeat_at = datetime.now(UTC) if see_sea_enabled else None
    await db_session.flush()
    db_session.task_checkpoint_enabled = True

    result = await InteractionGenerationWorkflow().finalize_story_task(
        db_session,
        task=_task_for(journey, attempt),
        finish_reason="length",
        metadata=None,
    )

    assert result["status"] == "failed"
    assert attempt.status == "failed"
    assert attempt.error_kind == "empty_response"
    assert attempt.continuation_count == 0
    assert attempt.task_id == original_task_id
    assert attempt.result_node_id is None
    if see_sea_enabled:
        assert journey.see_sea_enabled is False
        assert journey.see_sea_last_heartbeat_at is None


async def test_see_sea_continuation_prompt_contains_persisted_partial(
    db_session,
) -> None:
    _service, journey, attempt, _response = await _create_journey(
        db_session,
        key="create-journey-see-sea-context",
    )
    attempt.status = "pending"
    attempt.request_kind = "see_sea_continue"
    attempt.visible_text = "她推开门，正准备说出那个名字。"
    attempt.visible_offset = len(attempt.visible_text)
    expected_visible_text = attempt.visible_text
    journey.see_sea_enabled = True
    journey.see_sea_last_heartbeat_at = datetime.now(UTC)
    await db_session.flush()
    db_session.task_checkpoint_enabled = True
    task = _task_for(journey, attempt)

    with patch(
        "modules.interaction.generation.restore_project_llm_execution_settings",
        autospec=True,
        return_value={"llm": {"model": "deepseek-v4-flash"}},
    ):
        prepared = await InteractionGenerationWorkflow().prepare_story_task(
            db_session,
            task=task,
        )

    assert any(
        message.role == "assistant" and message.content == expected_visible_text
        for message in prepared.messages
    )
    assert prepared.messages[-1] == LLMMessage(
        role="user",
        content="自然承接并继续推进当前故事。",
    )


async def test_pending_adopted_beat_keeps_sea_prompt_after_loop_is_disabled(
    db_session,
) -> None:
    service, journey, attempt, _response = await _create_journey(
        db_session,
        key="pending-adopted-sea-prompt",
    )
    await service.update_modes(
        db_session,
        journey_id=str(journey.id),
        see_sea_enabled=True,
        action_options_enabled=True,
        expected_selection_epoch=journey.selection_epoch,
    )
    await service.update_modes(
        db_session,
        journey_id=str(journey.id),
        see_sea_enabled=False,
        action_options_enabled=None,
        expected_selection_epoch=journey.selection_epoch,
    )
    db_session.task_checkpoint_enabled = True

    with patch(
        "modules.interaction.generation.restore_project_llm_execution_settings",
        autospec=True,
        return_value={
            "llm": {
                "provider_id": "deepseek",
                "model": "deepseek-v4-flash",
                "max_tokens": 8192,
            }
        },
    ):
        prepared = await InteractionGenerationWorkflow().prepare_story_task(
            db_session,
            task=_task_for(journey, attempt),
        )

    assert isinstance(prepared, PreparedStoryGeneration)
    assert prepared.see_sea_step is True
    system_prompt = prepared.messages[0].content
    assert "看海模式已开启" in system_prompt
    assert "不要给出行动建议" in system_prompt
    assert story_request(prepared).max_tokens == 4096


async def test_extended_context_uses_full_selected_path_without_forced_summary(
    db_session,
) -> None:
    _service, journey, attempt, _response = await _create_journey(
        db_session,
        key="create-journey-extended-context",
    )
    attempt_id = attempt.id
    opening_content = (
        await db_session.get(
            InteractionMessageNode,
            attempt.response_to_node_id,
        )
    ).content
    db_session.task_checkpoint_enabled = True
    task = _task_for(journey, attempt)

    with (
        patch(
            "modules.interaction.generation.estimate_input_tokens",
            autospec=True,
            return_value=300_000,
        ),
        patch(
            "modules.interaction.generation.restore_project_llm_execution_settings",
            autospec=True,
            return_value={"llm": {"model": "deepseek-v4-flash"}},
        ),
    ):
        prepared = await InteractionGenerationWorkflow().prepare_story_task(
            db_session,
            task=task,
        )

    refreshed_attempt = await db_session.get(
        InteractionGenerationAttempt,
        attempt_id,
    )
    assert isinstance(prepared, PreparedStoryGeneration)
    assert any(message.content == opening_content for message in prepared.messages)
    assert refreshed_attempt.status == "running"
    assert refreshed_attempt.usage["context_tier"] == "extended"
    assert refreshed_attempt.usage["estimated_input_tokens"] == 300_000
    assert refreshed_attempt.usage["prompt_version"] == "interaction-story-v3"


async def test_emergency_summary_resumes_same_story_attempt_without_losing_path(
    db_session,
) -> None:
    service, journey, attempt, _response = await _create_journey(
        db_session,
        key="create-journey-emergency-summary",
    )
    attempt_id = attempt.id
    task_id = attempt.task_id
    journey_id = journey.id
    initial_path = await service._repo.get_selected_path(
        db_session,
        journey=journey,
    )
    initial_path[0].token_estimate = 1_000
    await db_session.flush()
    initial_node_ids = [node.id for node in initial_path]
    initial_contents = [node.content for node in initial_path]
    db_session.task_checkpoint_enabled = True
    task = _task_for(journey, attempt)
    workflow = InteractionGenerationWorkflow()

    with (
        patch(
            "modules.interaction.generation.estimate_input_tokens",
            autospec=True,
            side_effect=[600_000, 200_000, 200_000],
        ),
        patch(
            "modules.interaction.generation.restore_project_llm_execution_settings",
            autospec=True,
            return_value={"llm": {"model": "deepseek-v4-flash"}},
        ),
        patch(
            "modules.interaction.generation._summary_compressible_prefix_end",
            autospec=True,
            side_effect=lambda nodes: len(nodes),
        ),
    ):
        summary = await workflow.prepare_story_task(db_session, task=task)
        assert isinstance(summary, PreparedSummaryGeneration)
        preparing_attempt = await db_session.get(
            InteractionGenerationAttempt,
            attempt_id,
        )
        assert preparing_attempt.status == "preparing_context"
        assert summary.origin_attempt_id == str(attempt_id)
        assert summary.origin_task_id == str(task_id)
        assert all(
            content in summary.messages[-1].content for content in initial_contents
        )

        result = await workflow.finalize_summary_task(
            db_session,
            task=task,
            prepared=summary,
            output=InteractionSummaryOutput(
                segment_summary="用户以记者身份进入廷根。",
                overview=InteractionOverviewSections(
                    world_and_start="故事发生在廷根。",
                    player_character="用户是一名刚入职的记者。",
                    current_situation="旅程即将开始。",
                ),
            ),
        )
        resumed = await workflow.prepare_story_task(db_session, task=task)

    current_path = await service._repo.get_selected_path(
        db_session,
        journey=await db_session.get(InteractionJourney, journey_id),
    )
    resumed_attempt = await db_session.get(
        InteractionGenerationAttempt,
        attempt_id,
    )
    assert result["story_resume"] is True
    assert isinstance(resumed, PreparedStoryGeneration)
    assert resumed.attempt_id == str(attempt_id)
    assert [node.id for node in current_path] == initial_node_ids
    assert resumed_attempt.task_id == task_id
    assert resumed_attempt.status == "running"
    assert any("故事发生在廷根" in message.content for message in resumed.messages)


async def test_hard_context_budget_fails_closed_and_preserves_selected_path(
    db_session,
) -> None:
    service, journey, attempt, _response = await _create_journey(
        db_session,
        key="create-journey-hard-context",
    )
    attempt_id = attempt.id
    journey_id = journey.id
    initial_path = await service._repo.get_selected_path(
        db_session,
        journey=journey,
    )
    initial_node_ids = [node.id for node in initial_path]
    db_session.task_checkpoint_enabled = True
    task = _task_for(journey, attempt)
    workflow = InteractionGenerationWorkflow()

    with patch(
        "modules.interaction.generation.estimate_input_tokens",
        autospec=True,
        return_value=800_000,
    ):
        with pytest.raises(InteractionContextBudgetError) as exc:
            await workflow.prepare_story_task(db_session, task=task)
    await workflow.fail_story_task(db_session, task=task, error=exc.value)

    failed_attempt = await db_session.get(
        InteractionGenerationAttempt,
        attempt_id,
    )
    current_path = await service._repo.get_selected_path(
        db_session,
        journey=await db_session.get(InteractionJourney, journey_id),
    )
    assert failed_attempt.status == "failed"
    assert failed_attempt.error_kind == "context_budget"
    assert "精简回顾" in failed_attempt.error_message
    assert [node.id for node in current_path] == initial_node_ids


async def test_content_filter_error_is_mapped_to_safe_user_message() -> None:
    kind, message = InteractionGenerationWorkflow._safe_story_error(
        LLMContentFilterError("provider detail must not escape")
    )

    assert kind == "content_filter"
    assert message == "这次内容未能生成，请换一种说法后重试"
    assert "provider detail" not in message


async def test_source_context_blocker_keeps_user_reason() -> None:
    error = InteractionContextBudgetError(
        "已固定的作品资料超出可用篇幅，请减少固定项",
        kind="source_context_blocked",
        user_message="已固定的作品资料超出可用篇幅，请减少固定项",
    )

    kind, message = InteractionGenerationWorkflow._safe_story_error(error)

    assert kind == "source_context_blocked"
    assert message == "已固定的作品资料超出可用篇幅，请减少固定项"


async def test_context_budget_error_keeps_default_copy_and_kind() -> None:
    kind, message = InteractionGenerationWorkflow._safe_story_error(
        InteractionContextBudgetError("internal diagnostic must not escape")
    )

    assert kind == "context_budget"
    assert "精简回顾" in message
    assert "internal diagnostic" not in message


async def test_second_see_sea_length_cutoff_formalizes_partial_and_stops_loop(
    db_session,
) -> None:
    _service, journey, attempt, _response = await _create_journey(
        db_session,
        key="create-journey-see-sea-second-length",
    )
    attempt.status = "running"
    attempt.request_kind = "see_sea_continue"
    attempt.continuation_count = 1
    attempt.visible_text = "这一节仍然在长度边界处结束。"
    attempt.visible_offset = len(attempt.visible_text)
    journey.see_sea_enabled = True
    journey.see_sea_last_heartbeat_at = datetime.now(UTC)
    await db_session.flush()
    db_session.task_checkpoint_enabled = True
    task = _task_for(journey, attempt)
    workflow = InteractionGenerationWorkflow()

    with patch.object(
        InteractionGenerationWorkflow,
        "_summary_is_due",
        autospec=True,
        return_value=False,
    ):
        result = await workflow.finalize_story_task(
            db_session,
            task=task,
            finish_reason="length",
            metadata=None,
        )

    node = (
        await db_session.execute(
            select(InteractionMessageNode).where(
                InteractionMessageNode.id == uuid.UUID(result["node_id"])
            )
        )
    ).scalar_one()
    assert result["status"] == "stopped"
    assert node.completion_state == "partial"
    assert node.end_reason == "length"
    assert journey.see_sea_enabled is False
    assert journey.see_sea_last_heartbeat_at is None


async def test_story_terminal_signal_stops_see_sea_without_actions(
    db_session,
) -> None:
    _service, journey, attempt, _response = await _create_journey(
        db_session,
        key="create-journey-story-terminal",
    )
    attempt.status = "running"
    attempt.request_kind = "see_sea"
    attempt.visible_text = "最后一盏灯熄灭后，这个漫长故事终于抵达终点。"
    attempt.visible_offset = len(attempt.visible_text)
    journey.see_sea_enabled = True
    journey.see_sea_last_heartbeat_at = datetime.now(UTC)
    await db_session.flush()
    db_session.task_checkpoint_enabled = True
    task = _task_for(journey, attempt)
    metadata = InteractionResponseMetadata(
        branch_hint="最后一盏灯熄灭",
        story_ended=True,
        action_suggestions=[
            InteractionActionSuggestion(label="继续", text="我继续前进。")
        ],
    )

    with patch.object(
        InteractionGenerationWorkflow,
        "_summary_is_due",
        autospec=True,
        return_value=False,
    ):
        result = await InteractionGenerationWorkflow().finalize_story_task(
            db_session,
            task=task,
            finish_reason="stop",
            metadata=metadata,
        )

    node = (
        await db_session.execute(
            select(InteractionMessageNode).where(
                InteractionMessageNode.id == uuid.UUID(result["node_id"])
            )
        )
    ).scalar_one()
    assert node.story_ended is True
    assert node.branch_hint == "最后一盏灯熄灭"
    assert node.action_suggestions == []
    assert journey.see_sea_enabled is False


async def test_leaving_story_page_revokes_sea_without_cancelling_current_step(
    db_session,
) -> None:
    service, journey, attempt, _response = await _create_journey(
        db_session,
        key="create-leave-story",
    )
    attempt.status = "running"
    await db_session.flush()
    await service.update_modes(
        db_session,
        journey_id=str(journey.id),
        see_sea_enabled=True,
        action_options_enabled=None,
        expected_selection_epoch=journey.selection_epoch,
    )

    result = await service.leave_story_page(
        db_session,
        journey_id=str(journey.id),
    )

    assert result.accepted is False
    assert result.see_sea_enabled is True
    assert result.attempt is not None
    assert result.attempt.id == str(attempt.id)
    assert attempt.status == "running"
    assert journey.see_sea_last_heartbeat_at is None

    attempt.visible_text = "离页前已经开始生成的当前节拍仍然正常结束。"
    attempt.visible_offset = len(attempt.visible_text)
    db_session.task_checkpoint_enabled = True
    with patch.object(
        InteractionGenerationWorkflow,
        "_summary_is_due",
        autospec=True,
        return_value=False,
    ):
        await InteractionGenerationWorkflow().finalize_story_task(
            db_session,
            task=_task_for(journey, attempt),
            finish_reason="stop",
            metadata=None,
        )

    assert journey.see_sea_enabled is False
    assert journey.see_sea_last_heartbeat_at is None
    heartbeat = await service.heartbeat(
        db_session,
        journey_id=str(journey.id),
    )
    assert heartbeat.accepted is False
    assert heartbeat.see_sea_enabled is False
    assert heartbeat.attempt is None


async def test_see_sea_story_request_uses_narrow_output_budget() -> None:
    common = {
        "novel_id": str(uuid.uuid4()),
        "journey_id": str(uuid.uuid4()),
        "attempt_id": str(uuid.uuid4()),
        "messages": [LLMMessage(role="user", content="继续")],
        "executable_settings": {
            "llm": {
                "provider_id": "deepseek",
                "model": "deepseek-v4-flash",
                "max_tokens": 8192,
                "temperature": 0.3,
            }
        },
        "existing_visible_text": "",
    }

    see_sea = story_request(PreparedStoryGeneration(request_kind="see_sea", **common))
    manual = story_request(PreparedStoryGeneration(request_kind="message", **common))

    assert see_sea.max_tokens == 4096
    assert manual.max_tokens == 8192


async def test_summary_request_uses_json_contract_and_twelve_k_budget() -> None:
    prepared = PreparedSummaryGeneration(
        novel_id=str(uuid.uuid4()),
        journey_id=str(uuid.uuid4()),
        path_hash="path",
        node_ids=[str(uuid.uuid4())],
        segment_node_ids=[str(uuid.uuid4())],
        started_overview_epoch=0,
        messages=[LLMMessage(role="user", content="整理")],
        executable_settings={
            "llm": {
                "provider_id": "deepseek",
                "model": "deepseek-v4-flash",
                "max_tokens": 20_000,
            }
        },
    )

    request = summary_request(prepared)

    assert request.response_format == {"type": "json_object"}
    assert request.max_tokens == 12_000


async def test_unknown_model_request_uses_long_context_fallback_output_budget() -> None:
    prepared = PreparedStoryGeneration(
        novel_id=str(uuid.uuid4()),
        journey_id=str(uuid.uuid4()),
        attempt_id=str(uuid.uuid4()),
        request_kind="message",
        messages=[LLMMessage(role="user", content="继续")],
        executable_settings={
            "llm": {
                "provider_id": "custom",
                "model": "unknown-model",
                "max_tokens": 20_000,
            }
        },
        existing_visible_text="",
    )

    # 未校验模型假定不弱于已校准档(MEM-DEC-078),输出预算同 DeepSeek 档。
    assert story_request(prepared).max_tokens == 8_192
