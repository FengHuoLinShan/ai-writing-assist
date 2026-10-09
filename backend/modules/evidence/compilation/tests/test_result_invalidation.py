from __future__ import annotations

import uuid

import pytest

from modules.evidence.compilation.facade import (
    attach_result_ref,
    confirm_context,
    mark_asset_context_changed,
    require_confirmation,
    require_fresh_confirmation,
)
from modules.evidence.contracts import ContextConfirmationRequest


@pytest.mark.asyncio
async def test_stale_reasons_remain_authoritative_after_status_changes(
    db_session,
    test_project_id,
) -> None:
    confirmation = await confirm_context(
        db_session,
        ContextConfirmationRequest(
            novel_id=test_project_id,
            action="writing.generate",
            task="生成正文建议",
            scope="chapter",
            chapter_index=1,
        ),
    )
    await attach_result_ref(
        db_session,
        novel_id=test_project_id,
        confirmation_id=confirmation.id,
        result_type="task",
        result_id="task-1",
        status="running",
    )
    await mark_asset_context_changed(
        db_session,
        novel_id=test_project_id,
        asset_type="task",
        asset_id="task-1",
        reason="source_changed",
    )
    await attach_result_ref(
        db_session,
        novel_id=test_project_id,
        confirmation_id=confirmation.id,
        result_type="writing_draft",
        result_id="draft-1",
        status="adopted",
    )

    stored = await require_confirmation(
        db_session,
        novel_id=test_project_id,
        action="writing.generate",
        confirmation_id=confirmation.id,
    )
    assert stored.result_status == "adopted"
    assert stored.stale_reasons == ["source_changed"]
    with pytest.raises(ValueError, match="参考资料已更新"):
        await require_fresh_confirmation(
            db_session,
            novel_id=test_project_id,
            action="writing.generate",
            confirmation_id=confirmation.id,
        )


@pytest.mark.asyncio
async def test_invalidation_alias_excludes_current_confirmation_and_is_idempotent(
    db_session,
    test_project_id,
) -> None:
    first = await confirm_context(
        db_session,
        ContextConfirmationRequest(
            novel_id=test_project_id,
            action="outline.generate",
            task="修订场景",
            scope="scene",
        ),
    )
    second = await confirm_context(
        db_session,
        ContextConfirmationRequest(
            novel_id=test_project_id,
            action="outline.generate",
            task="检查场景",
            scope="scene",
        ),
    )
    for confirmation in (first, second):
        await attach_result_ref(
            db_session,
            novel_id=test_project_id,
            confirmation_id=confirmation.id,
            result_type="scene",
            result_id="scene-1",
            status="done",
        )

    changed = await mark_asset_context_changed(
        db_session,
        novel_id=test_project_id,
        asset_type="outline_scene",
        asset_id="scene-1",
        reason="source_changed",
        exclude_confirmation_id=first.id,
    )
    repeated = await mark_asset_context_changed(
        db_session,
        novel_id=test_project_id,
        asset_type="scene_story_assets",
        asset_id="scene-1",
        reason="source_changed",
        exclude_confirmation_id=first.id,
    )

    assert changed == repeated == 1
    first_stored = await require_confirmation(
        db_session,
        novel_id=test_project_id,
        action="outline.generate",
        confirmation_id=first.id,
    )
    second_stored = await require_confirmation(
        db_session,
        novel_id=test_project_id,
        action="outline.generate",
        confirmation_id=second.id,
    )
    assert first_stored.stale_reasons == []
    assert second_stored.stale_reasons == ["source_changed"]


@pytest.mark.asyncio
async def test_describe_confirmed_task_outcomes_maps_owner_and_superseded(
    db_session,
    test_project_id,
) -> None:
    """用量归因只读缝：归属任务带走确认结果，被取代任务标记非归属。"""
    from modules.evidence.compilation.facade import describe_confirmed_task_outcomes

    confirmation = await confirm_context(
        db_session,
        ContextConfirmationRequest(
            novel_id=test_project_id,
            action="writing.generate",
            task="生成正文建议",
            scope="chapter",
            chapter_index=1,
        ),
    )
    # 先绑定 task-1，再在同一确认上重新生成绑定 task-2：task-1 被取代
    for task_id in ("task-1", "task-2"):
        await attach_result_ref(
            db_session,
            novel_id=test_project_id,
            confirmation_id=confirmation.id,
            result_type="task",
            result_id=task_id,
            status="running",
        )
    await attach_result_ref(
        db_session,
        novel_id=test_project_id,
        confirmation_id=confirmation.id,
        result_type="writing_draft",
        result_id="draft-1",
        status="adopted",
    )

    outcomes = await describe_confirmed_task_outcomes(
        db_session,
        novel_id=test_project_id,
        task_ids=["task-1", "task-2", "task-missing"],
    )

    assert set(outcomes) == {"task-1", "task-2"}
    assert outcomes["task-2"] == {
        "confirmation_id": confirmation.id,
        "result_status": "adopted",
        "owner_task": True,
    }
    assert outcomes["task-1"]["owner_task"] is False
    assert outcomes["task-1"]["result_status"] == "adopted"
    assert outcomes["task-1"]["confirmation_id"] == confirmation.id


@pytest.mark.asyncio
async def test_describe_confirmed_task_outcomes_prefers_owner_and_isolates_novel(
    db_session,
    test_project_id,
    project_factory,
) -> None:
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import select

    from modules.evidence.compilation.facade import describe_confirmed_task_outcomes
    from modules.evidence.compilation.models import ContextConfirmation

    other_novel = str(await project_factory.create_project(title="其他作品"))
    earlier = await confirm_context(
        db_session,
        ContextConfirmationRequest(
            novel_id=test_project_id,
            action="writing.generate",
            task="较早的确认，任务是其归属",
            scope="chapter",
        ),
    )
    await attach_result_ref(
        db_session,
        novel_id=test_project_id,
        confirmation_id=earlier.id,
        result_type="task",
        result_id="task-shared",
        status="rejected",
    )
    later = await confirm_context(
        db_session,
        ContextConfirmationRequest(
            novel_id=test_project_id,
            action="writing.generate",
            task="较新的确认，任务被重新生成取代",
            scope="chapter",
        ),
    )
    for task_id in ("task-shared", "task-latest"):
        await attach_result_ref(
            db_session,
            novel_id=test_project_id,
            confirmation_id=later.id,
            result_type="task",
            result_id=task_id,
            status="running",
        )
    other_confirmation = await confirm_context(
        db_session,
        ContextConfirmationRequest(
            novel_id=other_novel,
            action="writing.generate",
            task="别的作品的确认",
            scope="chapter",
        ),
    )
    await attach_result_ref(
        db_session,
        novel_id=other_novel,
        confirmation_id=other_confirmation.id,
        result_type="task",
        result_id="task-shared",
        status="running",
    )
    # 固定创建时间，避免同秒创建时排序不稳定
    base = datetime.now(UTC) - timedelta(minutes=5)
    stamps = (
        (earlier.id, base),
        (later.id, base + timedelta(minutes=1)),
    )
    for record_id, created_at in stamps:
        record = (
            await db_session.execute(
                select(ContextConfirmation).where(
                    ContextConfirmation.id == uuid.UUID(record_id)
                )
            )
        ).scalar_one()
        record.created_at = created_at
        await db_session.flush()

    outcomes = await describe_confirmed_task_outcomes(
        db_session,
        novel_id=test_project_id,
        task_ids=["task-shared", "task-latest"],
    )

    # 同作品内归属优先于时间：task-shared 在较早确认里是归属任务
    assert outcomes["task-shared"]["confirmation_id"] == earlier.id
    assert outcomes["task-shared"]["result_status"] == "rejected"
    assert outcomes["task-shared"]["owner_task"] is True
    assert outcomes["task-latest"]["confirmation_id"] == later.id
    assert outcomes["task-latest"]["owner_task"] is True
