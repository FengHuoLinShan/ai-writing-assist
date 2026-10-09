"""BR-6 回归：未采用的 P20 规划只存在于任务回执，不进入写作上下文与检索。

P20 预览在作者采用前只落在 outline_generate 任务结果里；结构资产表、
Evidence 编译与 RAG 检索都只读已采用的领域行。本测试把这条边界钉住：
采用（复制并重验后落库）是预览进入上下文的唯一门。
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from infrastructure.tasks.models import AsyncTask
from modules.account.facade import current_account_id
from modules.assistant.contracts import AssistantOperationContext, WorkContext
from modules.evidence.compilation.facade import compile_structure_context
from modules.evidence.contracts import ContextConfirmationRequest
from modules.evidence.facade import confirm_context
from modules.story.assistant_tools import _outline_apply, _outline_preview
from modules.story.outline_state.models import PlotThread
from modules.story.outline_state.p20_schemas import (
    OutlineLayerGenerateRequest,
    P20PlotThreadOutput,
)
from modules.story.outline_state.p20_window import apply_planning_window
from modules.story.outline_state.story_outline_schemas import StoryOutlineContent

pytestmark = pytest.mark.asyncio

_UNADOPTED_THREAD_NAME = "未采用候选：码头夜探"
_ADOPTED_THREAD_NAME = "已采用主线：来信调查"


def _preview_output() -> P20PlotThreadOutput:
    return P20PlotThreadOutput(
        result="proposed",
        threads=[
            {
                "proposal_ref": "P1",
                "name": _UNADOPTED_THREAD_NAME,
                "thread_type": "main",
                "start_chapter": 4,
                "basis": "尚待作者取舍的原创推进",
                "confidence": 0.7,
            }
        ],
    )


async def _completed_preview_task(db, nid: str) -> AsyncTask:
    """落一份已完成但从未采用的滚动规划回执（模拟真实任务结果形状）。"""
    confirmation = await confirm_context(
        db,
        ContextConfirmationRequest(
            novel_id=nid,
            action="outline.generate",
            task="滚动规划候选预览",
            scope="full",
            budget_tokens=0,
        ),
    )
    request = {
        "novel_id": nid,
        "context_confirmation_id": confirmation.id,
        "target": "plot_thread",
        "mode": "create",
        "instruction": "推进最近三章。",
        "start_chapter": 4,
        "end_chapter": 6,
        "rolling_window": True,
    }
    task = AsyncTask(
        novel_id=uuid.UUID(nid),
        task_type="outline_generate",
        status="done",
        meta={"action": "outline.generate", **request},
        result={
            "contract_version": "outline_layer_v2",
            "target": "plot_thread",
            "mode": "create",
            "draft_structure": _preview_output().model_dump(mode="json"),
            "requires_apply": True,
            "context_confirmation_id": confirmation.id,
            "context_fingerprint": "stale-preview-fingerprint",
            "_request": request,
            "_reference_map": {"threads": {"P1": str(uuid.uuid4())}},
        },
    )
    db.add(task)
    await db.flush()
    return task


async def _compile_thread_names(db, nid: str) -> list[str]:
    """按写作上下文真实消费路径编译（outline.analyze 的范围结构资料）。"""
    bundle = await compile_structure_context(
        db,
        nid,
        task="下一章创作上下文",
        scope="full",
        consumer_action="outline.analyze",
        chapter_index=1,
        visible_until_chapter=10,
        reveal_mode="author_full",
    )
    analysis = bundle.outline_analysis or {}
    return [
        item.get("name") if isinstance(item, dict) else getattr(item, "name", "")
        for item in analysis.get("plot_threads") or []
    ]


async def _active_thread_rows(db, nid: str) -> list[PlotThread]:
    return list(
        (
            await db.execute(
                select(PlotThread).where(
                    PlotThread.novel_id == uuid.UUID(nid),
                    PlotThread.status != "deprecated",
                )
            )
        )
        .scalars()
        .all()
    )


async def test_unadopted_preview_never_enters_context_until_adopted(
    db_session, test_project_id, account_llm_connection
) -> None:
    db, nid = db_session, test_project_id
    context = AssistantOperationContext(
        str(uuid.uuid4()), str(current_account_id()), WorkContext(scope="project")
    )
    # 保存总纲，保证结构上下文可完整物化。
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

    await _completed_preview_task(db, nid)

    # 预览只在任务回执里：没有对应结构资产行，也不进入编译上下文（检索同源）。
    assert await _active_thread_rows(db, nid) == []
    names = await _compile_thread_names(db, nid)
    assert _UNADOPTED_THREAD_NAME not in names

    # 采用（复制并重验）之后，资产行与上下文才出现规划；候选仍不可见。
    db.add(
        PlotThread(
            novel_id=uuid.UUID(nid),
            name=_ADOPTED_THREAD_NAME,
            thread_type="main",
            start_chapter=4,
            status="draft",
        )
    )
    await db.flush()
    names_after = await _compile_thread_names(db, nid)
    assert _ADOPTED_THREAD_NAME in names_after
    assert _UNADOPTED_THREAD_NAME not in names_after


async def test_window_drops_never_materialize_into_assets(
    db_session, test_project_id, account_llm_connection
) -> None:
    """窗口硬校验丢弃只改任务结果，不写资产：被丢弃条目同样进不了上下文。"""
    db, nid = db_session, test_project_id
    task = await _completed_preview_task(db, nid)
    request = OutlineLayerGenerateRequest.model_validate(task.result["_request"])
    # 预览线程起点第 4 章；把已写章节设为含第 4 章即触发“覆盖已写章节”丢弃。
    filtered, report = apply_planning_window(
        request,
        P20PlotThreadOutput.model_validate(task.result["draft_structure"]),
        written_chapters=frozenset({1, 2, 3, 4}),
    )
    assert filtered.threads == []
    assert report["dropped"][0]["reason"] == "chapter_points_to_written"

    assert await _active_thread_rows(db, nid) == []
    names = await _compile_thread_names(db, nid)
    assert _UNADOPTED_THREAD_NAME not in names
