from hashlib import sha256
from types import SimpleNamespace
from uuid import UUID

import pytest

from core.errors import ConflictError
from infrastructure.llm.agent_runtime import AgentRunBudget
from modules.account.facade import current_account_id
from modules.assistant.evidence_tools import AssistantToolContext, inspect_current
from modules.assistant.schemas import WorkContext
from modules.evidence.contracts import VisibilityContextContract
from modules.evidence.facade import inspect_novel_target
from modules.writing.facade import create_draft_only
from modules.writing.models import WritingDraft
from modules.writing.semantic_review import WritingSemanticWorkflowService


@pytest.mark.asyncio
async def test_selected_candidate_is_author_read_only_and_does_not_gain_review_approval(
    db_session, test_project_id
):
    db, nid = db_session, test_project_id
    await create_draft_only(db, nid, 1, title="当前稿", content="作者自己的正文")
    candidate = await create_draft_only(
        db,
        nid,
        1,
        title="候选",
        content="候选文字" * 2100,
    )
    candidate_row = await db.get(WritingDraft, UUID(candidate.id))
    candidate_row.status = "candidate"
    candidate_row.provenance_json = {"source": "writing_generate"}
    await db.flush()
    context = AssistantToolContext(
        db,
        nid,
        str(current_account_id()),
        WorkContext(
            page="writing",
            chapter_index=1,
            draft_id=candidate.id,
            source_hash=candidate.content_hash,
        ),
        None,
        AgentRunBudget(),
        None,
    )
    first = await inspect_current(SimpleNamespace(deps=context))
    assert len(first["inspection"]["item"]["text"]) == 8000
    assert first["inspection"]["item"]["next_offset"] == 8000
    second = await inspect_current(SimpleNamespace(deps=context), 8000)
    assert second["inspection"]["item"]["next_offset"] is None
    denied = await inspect_novel_target(
        db,
        novel_id=nid,
        target_ref=first["target_ref"],
        content_mode="working",
        visibility=VisibilityContextContract(mode="reader", cutoff_chapter=1),
    )
    assert not denied["visible"]
    with pytest.raises(ConflictError):
        await WritingSemanticWorkflowService()._freeze_draft(
            db, novel_id=nid, draft_id=str(candidate.id), role="target"
        )
    row = await db.get(WritingDraft, UUID(candidate.id))
    row.content = "已经修改"
    row.content_hash = sha256(row.content.encode()).hexdigest()
    await db.flush()
    with pytest.raises(ConflictError):
        await context.revalidate(list(context.evidence_refs))
