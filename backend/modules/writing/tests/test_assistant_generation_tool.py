from dataclasses import replace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from core.errors import ConflictError
from infrastructure.tasks.models import AsyncTask
from modules.account.facade import current_account_id
from modules.assistant.contracts import AssistantOperationContext, WorkContext
from modules.evidence.facade import prepare_confirmed_ai_action
from modules.project.facade import build_project_llm_execution_snapshot
from modules.writing.assistant_generation_tool import OPERATIONS, GenerateCandidate
from modules.writing.facade import create_draft_only, get_latest_draft_for_chapter


@pytest.mark.asyncio
async def test_generation_freezes_original_context_and_reuses_parented_task(
    db_session, test_project_id, account_llm_connection
):
    db, nid = db_session, test_project_id
    draft = await create_draft_only(db, nid, 1, "开场", "他停在门前。")
    parent = AsyncTask(
        novel_id=UUID(nid), task_type="assistant_turn", status="running", meta={}
    )
    db.add(parent)
    await db.flush()
    context = AssistantOperationContext(
        str(parent.id),
        str(current_account_id()),
        WorkContext(
            page="writing",
            draft_id=draft.id,
            source_hash=draft.content_hash,
            chapter_index=1,
        ),
        operation_id=str(uuid4()),
        llm_snapshot=await build_project_llm_execution_snapshot(db, nid),
        internal_meta={
            "_parent_task_id": str(parent.id),
            "_execution_mode": "inline_only",
        },
    )
    args = GenerateCandidate(
        chapter_index=1, generation_mode="continue", instruction="续写他观察门锁的细节"
    )
    operation = OPERATIONS["writing.generate_candidate"]
    preview = await operation.prepare(db, nid, args, context=context)
    reference = await operation.apply(db, nid, args, preview, context=context)
    assert await operation.apply(db, nid, args, preview, context=context) == reference
    task = await db.get(AsyncTask, UUID(reference["task_id"]))
    assert task.meta["_parent_task_id"] == str(parent.id)
    assert task.meta["base_draft_id"] == draft.id
    confirmed = await prepare_confirmed_ai_action(
        db,
        novel_id=nid,
        action="writing.generate",
        confirmation_id=task.meta["context_confirmation_id"],
    )
    assert confirmed.compile_options["requested_chapter_index"] == 1
    assert confirmed.compile_options["visible_until_chapter"] == 1
    assert (
        await db.scalar(
            select(func.count())
            .select_from(AsyncTask)
            .where(AsyncTask.task_type == "writing_generate")
        )
        == 1
    )
    assert (await get_latest_draft_for_chapter(db, nid, 1)).id == draft.id
    assert (await operation.read_result(db, nid, reference))["status"] == "incomplete"
    with pytest.raises(ConflictError):
        await operation.prepare(
            db,
            nid,
            args,
            context=replace(context, work=WorkContext(excluded_targets=[str(uuid4())])),
        )
