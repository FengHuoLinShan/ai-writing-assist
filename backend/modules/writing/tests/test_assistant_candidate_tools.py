from uuid import UUID, uuid4

import pytest

from core.errors import ConflictError
from modules.account.facade import current_account_id
from modules.assistant.contracts import AssistantOperationContext, WorkContext
from modules.writing.assistant_candidate_tools import OPERATIONS, SelectDraft
from modules.writing.facade import create_draft_only, get_draft
from modules.writing.repositories import WritingDraftRepository
from modules.writing.schemas import WritingDraftCreate
from modules.writing.services import WritingDraftService


@pytest.mark.asyncio
async def test_adoption_rechecks_working_head_and_restore_creates_a_working_copy(
    db_session, test_project_id
):
    db, nid = db_session, test_project_id
    original = await create_draft_only(db, nid, 1, "旧工作稿", "原有正文")
    candidate = await WritingDraftRepository().create_with_status(
        db,
        WritingDraftCreate(
            novel_id=nid, chapter_index=1, title="候选", content="供作者选择的正文"
        ),
        status="candidate",
    )
    context = AssistantOperationContext(
        str(uuid4()), str(current_account_id()), WorkContext(scope="project")
    )
    operation = OPERATIONS["writing.adopt_candidate"]
    args = SelectDraft(draft_id=candidate.id)
    preview = await operation.prepare(db, nid, args, context=context)
    newer = await create_draft_only(db, nid, 1, "后来的工作稿", "稍后输入的正文")
    with pytest.raises(ConflictError):
        await operation.apply(db, nid, args, preview, context=context)
    preview = await operation.prepare(db, nid, args, context=context)
    assert preview["working_base"]["draft_id"] == newer.id
    result = await operation.apply(db, nid, args, preview, context=context)
    adopted = await get_draft(db, nid, result["id"])
    assert adopted.status == "draft" and adopted.content == "供作者选择的正文"
    assert UUID(adopted.id) != candidate.id
    assert (await get_draft(db, nid, str(candidate.id))).status == "deprecated"
    restore = OPERATIONS["writing.restore_version"]
    args = SelectDraft(draft_id=original.id)
    preview = await restore.prepare(db, nid, args, context=context)
    result = await restore.apply(db, nid, args, preview, context=context)
    restored = await get_draft(db, nid, result["id"])
    assert restored.status == "draft" and restored.content == "原有正文"
    assert restored.id != original.id
    assert restored.provenance_json["restored_from_draft_id"] == original.id
    assert (await get_draft(db, nid, adopted.id)).content == "供作者选择的正文"


@pytest.mark.asyncio
async def test_ai_candidate_without_original_confirmation_cannot_be_adopted(
    db_session, test_project_id
):
    candidate = await WritingDraftRepository().create_with_status(
        db_session,
        WritingDraftCreate(
            novel_id=test_project_id,
            chapter_index=1,
            content="候选",
            provenance_json={"source": "writing_generate", "review_required": True},
        ),
        status="candidate",
    )
    context = AssistantOperationContext(
        str(uuid4()), str(current_account_id()), WorkContext(scope="project")
    )
    with pytest.raises(ConflictError, match="参考资料"):
        await OPERATIONS["writing.adopt_candidate"].prepare(
            db_session,
            test_project_id,
            SelectDraft(draft_id=candidate.id),
            context=context,
        )


@pytest.mark.asyncio
async def test_regeneration_preserves_stale_selection_without_freshening_old_candidate(
    db_session, test_project_id
):
    from core.errors import NotFoundError
    from modules.evidence.compilation.models import ContextConfirmation

    db, nid = db_session, test_project_id
    original = ContextConfirmation(
        novel_id=UUID(nid),
        action="writing.generate",
        task="旧确认",
        scope="chapter",
        compile_options={"chapter_index": 1, "visible_until_chapter": 1},
        excluded_asset_ids={"core_entities": [str(uuid4())]},
        result_status="stale",
        stale_reasons=["原资料已变化"],
    )
    db.add(original)
    await db.flush()
    candidate = await WritingDraftRepository().create_with_status(
        db,
        WritingDraftCreate(
            novel_id=nid,
            chapter_index=1,
            content="旧候选",
            provenance_json={
                "source": "writing_generate",
                "review_required": True,
                "context_confirmation_id": str(original.id),
            },
        ),
        status="candidate",
    )
    service = WritingDraftService()
    result = await service.regeneration_context(db, str(candidate.id), nid)
    assert result.original_scope_available
    assert result.reference_options["excluded_asset_ids"] == original.excluded_asset_ids
    assert result.reference_options["visible_until_chapter"] == 1
    assert original.result_status == "stale" and candidate.content == "旧候选"
    with pytest.raises(ConflictError):
        await service.adopt_candidate_to_working(db, str(candidate.id), nid)
    with pytest.raises(NotFoundError):
        await service.regeneration_context(db, str(candidate.id), str(uuid4()))
    candidate.provenance_json = {"source": "writing_generate", "review_required": True}
    await db.flush()
    fallback = await service.regeneration_context(db, str(candidate.id), nid)
    assert not fallback.original_scope_available
    assert fallback.reference_options["scope"] == "chapter"
    assert fallback.reference_options["chapter_index"] == 1
    with pytest.raises(ConflictError):
        await service.adopt_candidate_to_working(db, str(candidate.id), nid)
