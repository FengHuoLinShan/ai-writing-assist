from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from core.errors import ConflictError, NotFoundError
from infrastructure.tasks.models import AsyncTask
from modules.account.facade import current_account_id
from modules.assistant.contracts import AssistantOperationContext, WorkContext
from modules.assistant.models import AssistantMessage, AssistantRun, AssistantSession
from modules.assistant.schemas import SessionCreate
from modules.assistant.service import AssistantService
from modules.world.assistant_cocreation_tools import OPERATIONS, SaveCheckpoint
from modules.world.models import CreationSuggestion


@pytest.mark.asyncio
async def test_stage_save_keeps_session_lineage_decisions_and_rejects_late_pointer(
    db_session, test_project_id
):
    db, nid = db_session, test_project_id
    session = await AssistantService().create_session(db, SessionCreate(novel_id=nid))
    task = AsyncTask(
        novel_id=UUID(nid), task_type="assistant_turn", status="done", meta={}
    )
    db.add(task)
    await db.flush()
    run = AssistantRun(
        id=task.id,
        novel_id=UUID(nid),
        session_id=UUID(session.id),
        task_id=task.id,
        owner_id=current_account_id(),
        status="waiting_approval",
        request_hash="a" * 64,
        request_json={"message": "保存本轮世界讨论结果"},
    )
    db.add(run)
    await db.flush()
    context = AssistantOperationContext(
        str(run.id), str(current_account_id()), WorkContext(scope="project")
    )
    operation = OPERATIONS["world.save_checkpoint"]
    first = SaveCheckpoint(
        decisions=[
            {"item_key": "door", "text": "铜门只从内侧开启", "disposition": "locked"}
        ]
    )
    preview = await operation.prepare(db, nid, first, context=context)
    run.result_json = {"answer": "已准备阶段成果", "actions": [preview]}
    await db.flush()
    result = await operation.apply(db, nid, first, preview, context=context)
    row = await db.get(AssistantSession, UUID(session.id))
    assert str(row.current_checkpoint_id) == result["id"] and row.checkpoint_round == 1
    with pytest.raises(ConflictError):
        await operation.apply(db, nid, first, preview, context=context)
    assert await db.scalar(select(func.count()).select_from(CreationSuggestion)) == 1
    second = SaveCheckpoint(
        decisions=[
            {"item_key": "keeper", "text": "守门人身份待定", "disposition": "open"}
        ]
    )
    result2 = await operation.apply(
        db,
        nid,
        second,
        await operation.prepare(db, nid, second, context=context),
        context=context,
    )
    checkpoint = await db.get(CreationSuggestion, UUID(result2["id"]))
    assert checkpoint.payload_json["parent_checkpoint_id"] == result["id"]
    assert {item["item_key"] for item in checkpoint.payload_json["decisions"]} == {
        "door",
        "keeper",
    }
    assert checkpoint.status == "pending"
    messages = (await db.scalars(select(AssistantMessage))).all()
    decisions = [message for message in messages if message.kind == "decision"]
    receipts = [message for message in messages if message.kind == "message"]
    assert len(decisions) == len(receipts) == 2
    assert {str(message.outcome_suggestion_id) for message in decisions} == {
        result["id"],
        result2["id"],
    }
    assert all(message.outcome_kind == "world_core_checkpoint" for message in decisions)
    assert all(
        message.outcome_kind == "checkpoint" and message.task_id == task.id
        for message in receipts
    )
    from modules.world.assistant_outcome_tools import (
        OPERATIONS as OUTCOMES,
    )
    from modules.world.assistant_outcome_tools import (
        PreparePackage,
    )

    package_args = PreparePackage(
        items=[
            {
                "item_key": "harbor",
                "kind": "core_entity",
                "disposition": "include",
                "payload": {
                    "operation": "create",
                    "entity": {"entity_type": "location", "name": "候选港口"},
                },
            }
        ]
    )
    package_op = OUTCOMES["world.prepare_package"]
    package_preview = await package_op.prepare(db, nid, package_args, context=context)
    package_result = await package_op.apply(
        db, nid, package_args, package_preview, context=context
    )
    package = await db.get(CreationSuggestion, UUID(package_result["id"]))
    assert package.status == "pending"
    source = package.payload_json["items"][0]["source_refs"][0]
    assert source["source_id"] == session.id and source["source_version"] == str(run.id)
    assert package.payload_json["items"][0]["authority_kind"] == "generated_bridge"
    other = AssistantOperationContext(str(uuid4()), context.owner_id, context.work)
    with pytest.raises(NotFoundError):
        await operation.prepare(db, nid, second, context=other)
