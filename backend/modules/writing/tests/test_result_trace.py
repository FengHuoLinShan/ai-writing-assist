from __future__ import annotations

import uuid

import pytest

from modules.evidence.compilation.facade import (
    attach_result_ref,
    confirm_context,
    require_confirmation,
)
from modules.evidence.compilation.repositories import ContextConfirmationRepository
from modules.writing.repositories import WritingDraftRepository
from modules.writing.schemas import WritingDraftCreate, WritingDraftUpdate
from modules.writing.services import WritingDraftService


async def _candidate(db_session, novel_id: str, confirmation_id: str):
    return await WritingDraftRepository().create_with_status(
        db_session,
        WritingDraftCreate(
            novel_id=novel_id,
            chapter_index=1,
            title="AI 建议",
            content="待处理正文",
            provenance_json={
                "source": "writing_generate",
                "context_confirmation_id": confirmation_id,
                "source_confirmation_id": confirmation_id,
                "knowledge_review": {"status": "passed"},
            },
        ),
        status="candidate",
    )


@pytest.mark.asyncio
async def test_candidate_adoption_updates_confirmation_result_trace(
    db_session,
    test_project_id,
    monkeypatch,
) -> None:
    confirmation = await confirm_context(
        db_session,
        novel_id=test_project_id,
        action="writing.generate",
        task="生成正文建议",
        scope="chapter",
        chapter_index=1,
    )
    candidate = await _candidate(db_session, test_project_id, confirmation.id)
    await attach_result_ref(
        db_session,
        novel_id=test_project_id,
        confirmation_id=confirmation.id,
        result_type="writing_draft",
        result_id=str(candidate.id),
        status="done",
    )

    async def accept_candidate(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr(
        "modules.writing.semantic_review.validate_candidate_upstream",
        accept_candidate,
    )
    adopted = await WritingDraftService().adopt_candidate_to_working(
        db_session,
        str(candidate.id),
        test_project_id,
    )

    stored = await require_confirmation(
        db_session,
        novel_id=test_project_id,
        action="writing.generate",
        confirmation_id=confirmation.id,
    )
    assert stored.result_status == "adopted"
    assert stored.result_refs == [
        {"type": "writing_draft", "id": str(candidate.id)},
        {"type": "writing_draft", "id": adopted.id},
    ]


@pytest.mark.asyncio
async def test_candidate_rejection_updates_confirmation_without_deleting_history(
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
    candidate = await _candidate(db_session, test_project_id, confirmation.id)
    await attach_result_ref(
        db_session,
        novel_id=test_project_id,
        confirmation_id=confirmation.id,
        result_type="writing_draft",
        result_id=str(candidate.id),
        status="done",
    )

    await WritingDraftService().delete_draft(
        db_session,
        str(candidate.id),
        test_project_id,
    )

    stored = await require_confirmation(
        db_session,
        novel_id=test_project_id,
        action="writing.generate",
        confirmation_id=confirmation.id,
    )
    archived = await WritingDraftRepository().get(db_session, candidate.id)
    assert stored.result_status == "rejected"
    assert stored.result_refs == [{"type": "writing_draft", "id": str(candidate.id)}]
    assert archived is not None and archived.status == "deprecated"


@pytest.mark.asyncio
async def test_working_draft_edit_marks_exact_confirmation_stale(
    db_session,
    test_project_id,
) -> None:
    draft_repo = WritingDraftRepository()
    draft = await draft_repo.create(
        db_session,
        WritingDraftCreate(
            novel_id=test_project_id,
            chapter_index=1,
            title="工作稿",
            content="旧内容",
        ),
    )
    confirmation = await confirm_context(
        db_session,
        novel_id=test_project_id,
        action="writing.generate",
        task="续写",
        scope="chapter",
        chapter_index=1,
    )
    confirmation_repo = ContextConfirmationRepository()
    record = await confirmation_repo.get(
        db_session,
        confirmation_id=uuid.UUID(confirmation.id),
        novel_id=uuid.UUID(test_project_id),
    )
    assert record is not None
    await confirmation_repo.replace_asset_refs(
        db_session,
        record,
        asset_role="selected",
        refs=[("writing_draft", str(draft.id))],
    )

    await draft_repo.update(
        db_session,
        draft,
        WritingDraftUpdate(content="新内容"),
    )

    stored = await require_confirmation(
        db_session,
        novel_id=test_project_id,
        action="writing.generate",
        confirmation_id=confirmation.id,
    )
    assert stored.result_status == "stale_context"
    assert stored.stale_reasons == ["source_changed"]
