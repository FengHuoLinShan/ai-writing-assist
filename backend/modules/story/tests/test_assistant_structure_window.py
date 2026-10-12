"""BR-6 滚动规划：窗口参数、覆盖窗口改修订与 operation_id 确定性。"""

from __future__ import annotations

import uuid
from dataclasses import replace

import pytest
from sqlalchemy import select

from app.assistant_operation_registry import story_structure_operations
from infrastructure.tasks.models import AsyncTask
from modules.account.facade import current_account_id
from modules.assistant.contracts import AssistantOperationContext, WorkContext
from modules.project.facade import build_project_llm_execution_snapshot
from modules.story.assistant_structure_workflow import PlanStructure
from modules.story.assistant_tools import _outline_apply, _outline_preview
from modules.story.outline_state.models import OutlineArc
from modules.story.outline_state.p20_schemas import OutlineLayerGenerateRequest
from modules.story.outline_state.story_outline_schemas import StoryOutlineContent


def _context(run_id: str) -> AssistantOperationContext:
    return AssistantOperationContext(
        run_id, str(current_account_id()), WorkContext(scope="project")
    )


async def _prepared_context(db, nid) -> tuple[AssistantOperationContext, str]:
    parent = AsyncTask(
        novel_id=uuid.UUID(nid), task_type="assistant_turn", status="running", meta={}
    )
    db.add(parent)
    await db.flush()
    context = _context(str(parent.id))
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
    snapshot = await build_project_llm_execution_snapshot(db, nid)
    return (
        replace(
            context,
            operation_id=str(uuid.uuid4()),
            llm_snapshot=snapshot,
            internal_meta={
                "_execution_mode": "inline_only",
                "_parent_task_id": str(parent.id),
            },
        ),
        snapshot,
    )


async def _submit(db, nid, args, context):
    operation = story_structure_operations["story.plan_structure"]
    preview = await operation.prepare(db, nid, args, context=context)
    return await operation.apply(db, nid, args, preview, context=context)


async def _task_request(db, task_id: str) -> OutlineLayerGenerateRequest:
    task = await db.get(AsyncTask, uuid.UUID(task_id))
    return OutlineLayerGenerateRequest.model_validate(
        {
            key: task.meta[key]
            for key in OutlineLayerGenerateRequest.model_fields
            if key in task.meta
        }
    )


@pytest.mark.asyncio
async def test_window_enters_confirmation_parameters_and_fingerprint(
    db_session, test_project_id, account_llm_connection
):
    db, nid = db_session, test_project_id
    context, _snapshot = await _prepared_context(db, nid)

    args = PlanStructure(
        target="outline_arc", instruction="推进第 4 章之后", start_chapter=4
    )
    preview = await story_structure_operations["story.plan_structure"].prepare(
        db, nid, args, context=context
    )

    # 篇章层默认窗口 3 章：只传起始章时结束章自动补足。
    assert preview["after"]["start_chapter"] == 4
    assert preview["after"]["end_chapter"] == 6
    assert preview["context_parameters"]["chapter_index"] == 4
    assert preview["context_parameters"]["planning_window_end"] == 6
    assert "第 4 至 6 章" not in preview["effect"]

    reference = await _submit(db, nid, args, context)
    request = await _task_request(db, reference["task_id"])
    assert request.rolling_window is True
    assert (request.start_chapter, request.end_chapter) == (4, 6)

    task = await db.get(AsyncTask, uuid.UUID(reference["task_id"]))
    window_fingerprint = task.meta["submission_fingerprint"]

    args_other = PlanStructure(
        target="outline_arc", instruction="推进第 4 章之后", start_chapter=8
    )
    reference_other = await _submit(db, nid, args_other, context)
    assert reference_other["task_id"] != reference["task_id"]
    task_other = await db.get(AsyncTask, uuid.UUID(reference_other["task_id"]))
    # 窗口参与规划指纹：不同窗口不会共享同一份来源快照。
    assert task_other.meta["submission_fingerprint"] != window_fingerprint


@pytest.mark.asyncio
async def test_covered_window_becomes_revision_suggestion(
    db_session, test_project_id, account_llm_connection
):
    db, nid = db_session, test_project_id
    context, _snapshot = await _prepared_context(db, nid)
    arc = OutlineArc(
        novel_id=uuid.UUID(nid),
        title="第一卷",
        start_chapter=4,
        end_chapter=6,
        arc_index=1,
        status="draft",
    )
    db.add(arc)
    await db.flush()

    args = PlanStructure(
        target="outline_arc", instruction="接着写第一卷", start_chapter=4
    )
    operation = story_structure_operations["story.plan_structure"]
    preview = await operation.prepare(db, nid, args, context=context)

    assert preview["after"]["mode"] == "revise"
    assert preview["after"]["selected_arc_ids"] == [str(arc.id)]
    assert preview["revision_of"] == {
        "arc_id": str(arc.id),
        "title": "第一卷",
        "start_chapter": 4,
        "end_chapter": 6,
    }
    assert "修订建议" in preview["effect"]

    reference = await _submit(db, nid, args, context)
    request = await _task_request(db, reference["task_id"])
    assert request.mode == "revise"
    assert request.selected_arc_ids == [str(arc.id)]


@pytest.mark.asyncio
async def test_window_operation_id_is_deterministic_per_window_layer(
    db_session, test_project_id, account_llm_connection
):
    db, nid = db_session, test_project_id
    context, snapshot = await _prepared_context(db, nid)

    args = PlanStructure(
        target="outline_arc", instruction="规划第一卷之后", start_chapter=4
    )
    first = await _submit(db, nid, args, context)

    same = await _submit(db, nid, args, context)
    assert same["task_id"] == first["task_id"]
    # 新运行或指令是新意图，不复用旧结果。
    other_run = replace(
        context,
        operation_id=str(uuid.uuid4()),
        llm_snapshot=await build_project_llm_execution_snapshot(db, nid),
    )
    replay_args = PlanStructure(
        target="outline_arc", instruction="换个说法再推一次", start_chapter=4
    )
    replay = await _submit(db, nid, replay_args, other_run)
    assert replay["task_id"] != first["task_id"]

    tasks = (
        (
            await db.execute(
                select(AsyncTask.id).where(
                    AsyncTask.task_type == "outline_generate",
                    AsyncTask.novel_id == uuid.UUID(nid),
                )
            )
        )
        .scalars()
        .all()
    )
    assert set(str(value) for value in tasks) == {first["task_id"], replay["task_id"]}

    # 其他层不受同窗口键影响：Scene 层窗口默认 1 章，各自独立回执。
    scene_args = PlanStructure(
        target="planned_scene", instruction="下一章的场景目标", start_chapter=4
    )
    scene_reference = await _submit(db, nid, scene_args, other_run)
    assert scene_reference["task_id"] != first["task_id"]
    scene_request = await _task_request(db, scene_reference["task_id"])
    assert (scene_request.start_chapter, scene_request.end_chapter) == (4, 4)
    assert snapshot  # 快照冻结来自提交时运行上下文


@pytest.mark.asyncio
async def test_window_size_caps_are_enforced_per_layer():
    with pytest.raises(ValueError, match="上限"):
        PlanStructure(
            target="outline_arc", instruction="一卷六章", start_chapter=1, end_chapter=7
        )
    with pytest.raises(ValueError, match="上限"):
        PlanStructure(
            target="planned_scene",
            instruction="三章场景",
            start_chapter=4,
            end_chapter=7,
        )
    with pytest.raises(ValueError, match="起始章"):
        PlanStructure(target="outline_arc", instruction="缺起始章", end_chapter=9)


@pytest.mark.asyncio
async def test_full_book_requests_keep_run_scoped_receipts(
    db_session, test_project_id, account_llm_connection
):
    """窗口外的手动/全书范围照旧：回执跟随运行，不受窗口键影响。"""
    db, nid = db_session, test_project_id
    context, _snapshot = await _prepared_context(db, nid)

    args = PlanStructure(target="plot_thread", instruction="全书剧情线梳理")
    first = await _submit(db, nid, args, context)
    request = await _task_request(db, first["task_id"])
    assert request.rolling_window is False
    assert request.start_chapter is None


@pytest.mark.asyncio
async def test_rolling_layers_adopt_with_fresh_confirmations_and_actual_domain_writes(
    db_session, test_project_id, account_llm_connection
):
    """生成与审查使用合成结果，其余确认、来源冻结和三层采用走真实领域。"""
    from types import SimpleNamespace

    from core.container import container_scope
    from modules.assistant.guided_flow.flows import _run_rolling_plan
    from modules.assistant.guided_flow.registry import FLOWS
    from modules.evidence.contracts import ContextConfirmationRequest
    from modules.evidence.facade import confirm_context
    from modules.story.assistant_structure_workflow import AdoptStructure
    from modules.story.outline_state.models import PlotThread, Scene
    from modules.story.outline_state.p20_schemas import P20_OUTPUT_SCHEMAS
    from modules.story.outline_state.p20_service import P20GenerationService

    db, nid = db_session, test_project_id
    context, _ = await _prepared_context(db, nid)
    artifacts = {"rolling_decision": {"accepted": True, "at_chapter": 1, "window": 3}}
    run = SimpleNamespace(id=uuid.uuid4())
    plan_operation = story_structure_operations["story.plan_structure"]
    adopt_operation = story_structure_operations["story.adopt_structure"]
    contexts = []
    with container_scope({"assistant.operations": story_structure_operations}):
        for layer, target, field, entry in (
            (
                "threads",
                "plot_thread",
                "threads",
                {
                    "name": "来信主线",
                    "thread_type": "main",
                    "start_chapter": 2,
                    "planned_payoff_chapter": 4,
                },
            ),
            (
                "arcs",
                "outline_arc",
                "arcs",
                {"title": "港口追查", "start_chapter": 2, "end_chapter": 4},
            ),
            (
                "scenes",
                "planned_scene",
                "scenes",
                {
                    "title": "打开来信",
                    "planned_start_chapter": 2,
                    "planned_end_chapter": 2,
                    "core_conflict_status": "not_applicable",
                },
            ),
        ):
            end = 3 if layer == "scenes" else 4
            args = PlanStructure(
                target=target,
                instruction="作者确认窗口内的原创规划",
                start_chapter=2,
                end_chapter=end,
            )
            preview = await plan_operation.prepare(db, nid, args, context=context)
            confirmation = await confirm_context(
                db,
                ContextConfirmationRequest(
                    novel_id=nid,
                    action="outline.generate",
                    **preview["context_parameters"],
                    expected_context_fingerprint=preview["context_fingerprint"],
                ),
            )
            artifacts[f"rolling_{layer}_confirmation"] = {
                "confirmation_id": str(confirmation.id)
            }
            receipt = await _run_rolling_plan(
                db,
                nid,
                context.owner_id,
                run,
                FLOWS["continue_writing"],
                artifacts,
                f"rolling_{layer}",
                input_fingerprint="synthetic-flow",
            )
            task = await db.get(AsyncTask, uuid.UUID(receipt["task_id"]))
            request = await _task_request(db, str(task.id))
            plan = await P20GenerationService().prepare(db, request)
            contexts.append(plan.source_fingerprint)
            output = P20_OUTPUT_SCHEMAS[target].model_validate(
                {
                    "result": "proposed",
                    field: [
                        {
                            "proposal_ref": "P1",
                            "basis": "作者确认窗口内的原创规划",
                            "confidence": 0.8,
                            **entry,
                        }
                    ],
                }
            )
            task.status = "done"
            task.result = P20GenerationService.task_result(
                plan,
                output,
                task_id=str(task.id),
                knowledge_review={
                    "policy_version": 1,
                    "capability": "story.outline.p20",
                    "status": "passed",
                },
            )
            await db.flush()
            adoption = AdoptStructure(task_id=task.id, proposal_refs=["P1"])
            prepared = await adopt_operation.prepare(db, nid, adoption, context=context)
            await adopt_operation.apply(db, nid, adoption, prepared, context=context)
            assert task.result["apply_status"] == "applied"
    assert len(set(contexts)) == 3
    assert (await db.scalar(select(PlotThread))).name == "来信主线"
    assert (await db.scalar(select(OutlineArc))).start_chapter == 2
    scene = await db.scalar(select(Scene))
    assert scene.title == "打开来信"
    assert scene.structure_meta["planned_chapter_range"] == {"start": 2, "end": 2}
