"""Manual prose can check scoped world facts without gaining candidate authority."""

import uuid

import pytest

from core.errors import ConflictError
from modules.world.facade import create_entity
from modules.writing.facade import create_draft_only
from modules.writing.models import WritingDraft
from modules.writing.schemas import WritingWorldReviewScope
from modules.writing.semantic_review import (
    WritingSemanticWorkflowService,
    _review_set_fingerprint,
)


@pytest.mark.asyncio
async def test_manual_world_review_freezes_actual_world_sources_and_exclusions(
    db_session, test_project_id
):
    rule = await create_entity(
        db_session,
        test_project_id,
        {
            "name": "铜门规则",
            "entity_type": "rule",
            "summary": "铜门只能从内侧打开。",
            "status": "canonical",
            "importance": 1.0,
        },
    )
    hidden = await create_entity(
        db_session,
        test_project_id,
        {
            "name": "暂不使用的规则",
            "entity_type": "rule",
            "summary": "不应进入本次审查的材料。",
            "status": "canonical",
            "importance": 1.0,
        },
    )
    draft = await create_draft_only(
        db_session, test_project_id, 1, "铜门", "她站在外面，轻轻拉开了铜门。"
    )
    await create_draft_only(
        db_session, test_project_id, 2, "后文", "不应读取的后续正文。"
    )
    scope = WritingWorldReviewScope(
        cutoff_chapter=1, excluded_targets=[f"core_entity:{hidden['id']}"]
    )
    service = WritingSemanticWorkflowService()
    targets, adjacent = await service._freeze_review_set(
        db_session,
        novel_id=test_project_id,
        draft_ids=[draft.id],
        manual_world_scope=scope,
    )
    assert adjacent == []
    context = targets[0]["review_context"]
    assert context["review_mode"] == "world_constraints"
    assert context["knowledge_boundary_checked"] is False
    assert context["status"] != "checked"
    ids = {item["target_ref"]["target_id"] for item in context["world_evidence"]}
    assert str(rule["id"]) in ids and str(hidden["id"]) not in ids
    assert "不应读取的后续正文" not in str(targets)
    with pytest.raises(ConflictError, match="授权范围"):
        await service._freeze_review_set(
            db_session,
            novel_id=test_project_id,
            draft_ids=[draft.id],
            manual_world_scope=WritingWorldReviewScope(excluded_targets=[draft.id]),
        )
    row = await db_session.get(WritingDraft, uuid.UUID(draft.id))
    row.provenance_json = {"source": "writing_generate"}
    await db_session.flush()
    with pytest.raises(ConflictError, match="原生成参考资料"):
        await service._freeze_review_set(
            db_session,
            novel_id=test_project_id,
            draft_ids=[draft.id],
            manual_world_scope=scope,
        )


@pytest.mark.asyncio
async def test_manual_review_manifest_changes_when_world_changes(
    db_session, test_project_id
):
    from modules.world.facade import update_entity

    rule = await create_entity(
        db_session,
        test_project_id,
        {
            "name": "潮汐规则",
            "entity_type": "rule",
            "summary": "每天只有一次落潮。",
            "status": "canonical",
            "importance": 1.0,
        },
    )
    draft = await create_draft_only(
        db_session, test_project_id, 1, "潮汐", "第二次落潮开始了。"
    )
    service, scope = WritingSemanticWorkflowService(), WritingWorldReviewScope()
    before, _ = await service._freeze_review_set(
        db_session,
        novel_id=test_project_id,
        draft_ids=[draft.id],
        manual_world_scope=scope,
    )
    await update_entity(
        db_session, test_project_id, str(rule["id"]), {"summary": "每天有两次落潮。"}
    )
    after, _ = await service._freeze_review_set(
        db_session,
        novel_id=test_project_id,
        draft_ids=[draft.id],
        manual_world_scope=scope,
    )
    assert _review_set_fingerprint(before) != _review_set_fingerprint(after)
