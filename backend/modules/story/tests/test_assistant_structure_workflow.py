import uuid
from dataclasses import replace

import pytest
from sqlalchemy import func, select

from core.config import get_settings
from core.errors import ConflictError
from infrastructure.tasks.models import AsyncTask
from modules.account.facade import current_account_id
from modules.assistant.contracts import AssistantOperationContext, WorkContext
from modules.assistant.models import AssistantWatch
from modules.assistant.proactive import save_policy
from modules.assistant.schemas import ProactivePolicy
from modules.project.facade import build_project_llm_execution_snapshot
from modules.story.assistant_structure_workflow import (
    OPERATIONS,
    AdoptStructure,
    PlanStructure,
)
from modules.story.assistant_tools import _outline_apply, _outline_preview
from modules.story.outline_state.models import ForeshadowingPlan, PlotThread
from modules.story.outline_state.p20_schemas import (
    OutlineLayerGenerateRequest,
    P20PlotThreadOutput,
)
from modules.story.outline_state.p20_service import P20GenerationService
from modules.story.outline_state.story_outline_schemas import StoryOutlineContent


@pytest.mark.asyncio
async def test_structure_task_keeps_parent_and_adopts_original_information_package(
    db_session, test_project_id, account_llm_connection, monkeypatch
):
    db, nid = db_session, test_project_id
    settings = replace(get_settings(), assistant_enabled=True)
    monkeypatch.setattr("modules.assistant.proactive.get_settings", lambda: settings)
    await save_policy(db, nid, ProactivePolicy(enabled=True))
    parent = AsyncTask(
        novel_id=uuid.UUID(nid), task_type="assistant_turn", status="running", meta={}
    )
    db.add(parent)
    await db.flush()
    context = AssistantOperationContext(
        str(parent.id), str(current_account_id()), WorkContext(scope="project")
    )
    outline = StoryOutlineContent(
        title="港口调查",
        creative_core={
            "premise": "调查者收到失踪者来信",
            "tone_and_reader_promise": "可信的悬疑",
            "story_engine": "线索引发选择",
        },
        outline_markdown="追查信件，决定是否公开真相。",
        major_storylines=[],
        macro_movements=[],
        open_decisions=[],
    )
    await _outline_apply(
        db,
        nid,
        outline,
        await _outline_preview(db, nid, outline, context=context),
        context=context,
    )
    args = PlanStructure(target="plot_thread", instruction="规划来信主线及其铺垫与回收")
    operation = OPERATIONS["story.plan_structure"]
    preview = await operation.prepare(db, nid, args, context=context)
    context = replace(
        context,
        operation_id=str(uuid.uuid4()),
        llm_snapshot=await build_project_llm_execution_snapshot(db, nid),
        internal_meta={
            "_execution_mode": "inline_only",
            "_parent_task_id": str(parent.id),
        },
    )
    reference = await operation.apply(db, nid, args, preview, context=context)
    assert await operation.apply(db, nid, args, preview, context=context) == reference
    task = await db.get(AsyncTask, uuid.UUID(reference["task_id"]))
    assert task.meta["_parent_task_id"] == str(parent.id)
    assert task.meta["_execution_mode"] == "inline_only"
    assert (await operation.read_result(db, nid, reference))["status"] == "incomplete"
    request = OutlineLayerGenerateRequest.model_validate(
        {
            key: task.meta[key]
            for key in OutlineLayerGenerateRequest.model_fields
            if key in task.meta
        }
    )
    plan = await P20GenerationService().prepare(db, request)
    output = P20PlotThreadOutput(
        result="proposed",
        threads=[
            {
                "proposal_ref": "P1",
                "name": "港口来信",
                "thread_type": "main",
                "start_chapter": 1,
                "planned_payoff_chapter": 5,
                "basis": "遵循总纲的调查方向",
                "confidence": 0.8,
                "information_movements": [
                    {
                        "movement_ref": "M1",
                        "information_subject": "信上的污痕",
                        "hidden_content": "污痕留下求救地点",
                        "basis": "原创待采用铺垫",
                        "confidence": 0.8,
                        "nodes": [
                            {"kind": "seed", "content": "发现污痕", "chapter_hint": 1},
                            {"kind": "payoff", "content": "识别地点", "chapter_hint": 5},
                        ],
                    }
                ],
            }
        ],
    )
    task.status = "done"
    task.result = P20GenerationService.task_result(plan, output, task_id=str(task.id))
    await db.flush()
    assert await db.scalar(select(func.count()).select_from(PlotThread)) == 0
    assert (await operation.read_result(db, nid, reference))["draft_structure"][
        "threads"
    ][0]["name"] == "港口来信"
    adopt = OPERATIONS["story.adopt_structure"]
    adoption = AdoptStructure(task_id=task.id)
    preview = await adopt.prepare(db, nid, adoption, context=context)
    result = await adopt.apply(db, nid, adoption, preview, context=context)
    assert result["result"]["total_threads"] == 1
    assert await db.scalar(select(func.count()).select_from(ForeshadowingPlan)) == 1
    thread = await db.scalar(select(PlotThread))
    assert thread.provenance_meta["adopted_from_preview_task_id"] == str(task.id)
    watch = await db.scalar(select(AssistantWatch))
    assert f"plot_thread:{thread.id}" in watch.dirty_json
    with pytest.raises(ConflictError):
        await adopt.prepare(
            db,
            nid,
            adoption,
            context=replace(context, work=WorkContext(excluded_targets=[str(thread.id)])),
        )
