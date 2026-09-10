from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from core.errors import ConflictError, NotFoundError
from modules.account.facade import current_account_id
from modules.assistant.contracts import AssistantOperationContext, WorkContext
from modules.evidence.contracts import VisibilityContextContract
from modules.evidence.facade import inspect_novel_target
from modules.story.assistant_information_tools import OPERATIONS, EditInformationPlan
from modules.story.outline_state.foreshadowing_repository import (
    ForeshadowingPlanRepository,
)


@pytest.mark.asyncio
async def test_information_edit_keeps_identity_rechecks_baseline_and_is_author_only(
    db_session, test_project_id
):
    db, nid = db_session, test_project_id
    plan = await ForeshadowingPlanRepository().create(
        db, UUID(nid), {"name": "来信", "planned_seed_chapter": 1}
    )
    args = EditInformationPlan(
        kind="foreshadowing_plan",
        plan_id=plan.id,
        changes={"name": "迟来的信", "planned_seed_chapter": 2},
    )
    operation = OPERATIONS["story.edit_information_plan"]
    context = AssistantOperationContext(
        str(uuid4()), str(current_account_id()), WorkContext(scope="project")
    )
    before = await operation.prepare(db, nid, args, context=context)
    result = await operation.apply(db, nid, args, before, context=context)
    assert result["id"] == str(plan.id)
    with pytest.raises(ConflictError):
        await operation.apply(db, nid, args, before, context=context)
    with pytest.raises(NotFoundError):
        await operation.prepare(db, str(uuid4()), args, context=context)
    target = {"target_type": "foreshadowing_plan", "target_id": str(plan.id)}
    for mode, visible in (("author", True), ("reader", False)):
        read = await inspect_novel_target(
            db,
            novel_id=nid,
            target_ref=target,
            content_mode="canonical",
            visibility=VisibilityContextContract(
                mode=mode, cutoff_chapter=1 if mode == "reader" else None
            ),
        )
        assert read["visible"] is visible
    with pytest.raises(ValidationError):
        EditInformationPlan(
            kind="foreshadowing_plan", plan_id=plan.id, changes={"name": None}
        )
