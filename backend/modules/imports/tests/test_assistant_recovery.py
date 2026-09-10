from uuid import UUID, uuid4

import pytest

from modules.account.facade import current_account_id
from modules.assistant.contracts import AssistantOperationContext, WorkContext
from modules.imports.assistant_tools import (
    OPERATIONS,
    ResumeOrganization,
    read_organization_status,
)
from modules.imports.tests.test_workflow_runs import _create_pending_run


@pytest.mark.asyncio
async def test_assistant_recovers_same_import_scope_without_recreating_task(
    db_session, test_project_id, project_factory
):
    db, nid = db_session, test_project_id
    task, run = await _create_pending_run(db, nid)
    task.novel_id = UUID(nid)
    task.meta = {**task.meta, "recovery_required": True}
    task.status = "failed"
    task.result = {"interrupted": True, "recovery_required": True}
    run.status, run.recovery_required = "failed", True
    await db.flush()
    context = AssistantOperationContext(
        str(uuid4()), str(current_account_id()), WorkContext(scope="project")
    )
    operation, args = OPERATIONS["imports.resume"], ResumeOrganization(task_id=task.id)
    preview = await operation.prepare(db, nid, args, context=context)
    assert "1～3" in preview["after"]
    result = await operation.apply(db, nid, args, preview, context=context)
    assert result["task_id"] == str(task.id)
    assert run.start_chapter == 1 and run.end_chapter == 3
    assert run.llm_execution_snapshot == {"provider": "test", "model": "frozen"}
    assert task.status == "pending" and not run.recovery_required
    other_id = str(await project_factory.create_project("另一本书"))
    assert not (await read_organization_status(db, other_id, task.id))["items"]
