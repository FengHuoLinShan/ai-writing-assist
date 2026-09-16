from __future__ import annotations

import pytest

from modules.evidence.compilation.facade import (
    attach_result_ref,
    confirm_context,
    mark_asset_context_changed,
    require_confirmation,
    require_fresh_confirmation,
)


@pytest.mark.asyncio
async def test_stale_reasons_remain_authoritative_after_status_changes(
    db_session,
    test_project_id,
) -> None:
    confirmation = await confirm_context(
        db_session,
        novel_id=test_project_id,
        action="writing.generate",
        task="生成正文建议",
        scope="chapter",
        chapter_index=1,
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
        novel_id=test_project_id,
        action="outline.generate",
        task="修订场景",
        scope="scene",
    )
    second = await confirm_context(
        db_session,
        novel_id=test_project_id,
        action="outline.generate",
        task="检查场景",
        scope="scene",
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
