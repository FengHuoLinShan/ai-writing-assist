"""Outline 任务处理器"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException

from infrastructure.tasks.registry import task_handler
from modules.outline.services import OutlineArcService, PlotThreadService
from modules.outline.schemas import (
    ChapterCardCreate,
    OutlineArcCreate,
    OutlineArcUpdate,
    PlotThreadCreate,
    PlotThreadUpdate,
)

logger = logging.getLogger(__name__)


@task_handler("plot_structure_generate")
async def handle_plot_structure_generate(db, task):
    """处理剧情结构生成任务

    从指定章节范围读取正文，调用 LLM 生成剧情线和篇章纲。
    支持增量更新（当已有剧情线/篇章纲时通过 existing_id 匹配）。

    Task meta 参数：
    - novel_id: 项目 ID
    - start_chapter: 起始章节
    - end_chapter: 结束章节
    """
    meta = task.meta or {}
    novel_id = meta.get("novel_id", "")
    start_chapter = int(meta.get("start_chapter", 1))
    end_chapter = int(meta.get("end_chapter", 5))

    if not novel_id:
        raise ValueError("novel_id is required for plot_structure_generate")

    # 1. 读取章节正文
    from modules.writing.facade import get_latest_draft_for_chapter

    chapters = []
    for idx in range(start_chapter, end_chapter + 1):
        draft = await get_latest_draft_for_chapter(db, novel_id, idx)
        if draft and draft.content:
            chapters.append(f"--- 第{idx}章 ---\n{draft.content}")

    if not chapters:
        raise HTTPException(400, detail=f"未找到章节 {start_chapter}-{end_chapter} 的正文")

    batch_text = "\n\n".join(chapters)

    # 2. 加载已有上下文（用于增量更新）
    existing_threads = await _load_existing_threads(db, novel_id)
    existing_arcs = await _load_existing_arcs(db, novel_id)
    existing_entities = await _load_existing_entities(db, novel_id)

    # 3. 调用 LLM 生成剧情结构
    from infrastructure.llm.client import LLMClient
    from infrastructure.llm.schemas import LLMCallRequest
    from pydantic import BaseModel
    from core.config import get_settings

    class _GeneratedThread(BaseModel):
        name: str
        thread_type: str
        summary: str
        visible_goal: str
        start_chapter: int | None = None
        planned_payoff_chapter: int | None = None
        existing_id: str | None = None

    class _GeneratedArc(BaseModel):
        title: str
        arc_index: int
        start_chapter: int
        end_chapter: int
        arc_goal: str
        core_conflict: str
        climax: str = ""
        result: str = ""
        existing_id: str | None = None

    class _PlotOutput(BaseModel):
        plot_threads: list[_GeneratedThread]
        outline_arcs: list[_GeneratedArc]

    context_note = ""
    if existing_threads or existing_arcs:
        context_note = (
            f"\n已有实体：{', '.join(e['name'] for e in existing_entities[:30])}\n"
            f"已有剧情线：\n" + "\n".join(
                f"  - id={t['id']} name={t['name']} type={t['thread_type']} "
                f"summary={t['summary'][:50]}"
                for t in existing_threads
            ) + "\n"
            f"已有篇章纲：\n" + "\n".join(
                f"  - id={a['id']} title={a['title']} chapters={a['start_chapter']}-{a['end_chapter']}"
                for a in existing_arcs
            ) + "\n"
        )

    system_prompt = (
        "你是一个小说剧情结构分析助手。"
        "从章节正文中分析识别剧情线和篇章结构。"
        f"当前章节范围：第{start_chapter}章到第{end_chapter}章\n\n"
        "输出 JSON 对象，包含：\n"
        "- plot_threads: 剧情线数组，每项包含 name, thread_type (main/secondary/hidden), "
        "summary, visible_goal, start_chapter, planned_payoff_chapter, existing_id\n"
        "- outline_arcs: 篇章纲数组，每项包含 title, arc_index, start_chapter, end_chapter, "
        "arc_goal, core_conflict, climax, result, existing_id\n\n"
        f"{context_note}"
        "规则：只基于已有章节正文分析，不凭空创造未发生的内容。\n"
        "增量规则：\n"
        "- 已有记录通过 existing_id 标记（值为已有的 id），此时更新其字段\n"
        "- 新记录 existing_id 设为 null（不提供该字段）\n"
        "- 不修改不可变字段（name, thread_type, arc_index 等，即使提供了也忽略）\n"
        "- 对已有线程，如在新章节中有明确进展则更新 summary / planned_payoff_chapter\n"
        "- 对已有篇章，如边界扩展则更新 end_chapter\n"
        "start_chapter 和 planned_payoff_chapter 必须为正整数（≥1），不确定时写 null。"
        "climax 和 result 是 OutlineArc 必填字段，必须根据正文内容填写。"
    )

    _settings = get_settings()
    request = LLMCallRequest(
        model=_settings.llm_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": batch_text},
        ],
        temperature=0.3,
        response_format={"type": "json_object"},
    )

    llm = LLMClient()
    result = await llm.generate_structured(request, _PlotOutput)

    # 4. 创建/更新剧情线和篇章纲
    thread_service = PlotThreadService()
    arc_service = OutlineArcService()
    created_threads = []
    created_arcs = []

    for pt in result.plot_threads:
        sc = pt.start_chapter if (pt.start_chapter is not None and pt.start_chapter >= 1) else None
        ppc = pt.planned_payoff_chapter if (pt.planned_payoff_chapter is not None and pt.planned_payoff_chapter >= 1) else None

        if pt.existing_id:
            updates: dict[str, Any] = {}
            if pt.summary:
                updates["summary"] = pt.summary
            if pt.visible_goal:
                updates["visible_goal"] = pt.visible_goal
            if ppc is not None:
                updates["planned_payoff_chapter"] = ppc
            if updates:
                try:
                    await thread_service.update(
                        db, pt.existing_id,
                        PlotThreadUpdate(**updates),
                        novel_id,
                    )
                except Exception as exc:
                    logger.warning("Failed to update thread %s: %s", pt.existing_id, exc)
        else:
            data = PlotThreadCreate(
                name=pt.name,
                thread_type=pt.thread_type,
                summary=pt.summary,
                visible_goal=pt.visible_goal,
                start_chapter=sc,
                planned_payoff_chapter=ppc,
            )
            created = await thread_service.create(db, novel_id, data)
            created_threads.append({"id": str(created.id), "name": created.name})

    for arc in result.outline_arcs:
        if arc.existing_id:
            updates: dict[str, Any] = {}
            if arc.arc_goal:
                updates["arc_goal"] = arc.arc_goal
            if arc.core_conflict:
                updates["core_conflict"] = arc.core_conflict
            if arc.climax:
                updates["climax"] = arc.climax
            if arc.result:
                updates["result"] = arc.result
            if arc.end_chapter:
                updates["end_chapter"] = arc.end_chapter
            if updates:
                try:
                    await arc_service.update(
                        db, arc.existing_id,
                        OutlineArcUpdate(**updates),
                        novel_id,
                    )
                except Exception as exc:
                    logger.warning("Failed to update arc %s: %s", arc.existing_id, exc)
        else:
            data = OutlineArcCreate(
                title=arc.title,
                arc_index=arc.arc_index,
                start_chapter=arc.start_chapter,
                end_chapter=arc.end_chapter,
                arc_goal=arc.arc_goal,
                core_conflict=arc.core_conflict,
                climax=arc.climax,
                result=arc.result,
            )
            created = await arc_service.create(db, novel_id, data)
            created_arcs.append({"id": str(created.id), "title": created.title})

    await db.flush()

    logger.info(
        "Plot structure generated: %d threads, %d arcs",
        len(created_threads), len(created_arcs),
    )

    return {
        "total_threads": len(created_threads),
        "total_arcs": len(created_arcs),
        "threads": created_threads,
        "arcs": created_arcs,
    }


async def _load_existing_threads(
    db,
    novel_id: str,
) -> list[dict[str, Any]]:
    """加载已有剧情线"""
    from modules.outline.facade import list_thread_summaries
    return await list_thread_summaries(db, novel_id)


async def _load_existing_arcs(
    db,
    novel_id: str,
) -> list[dict[str, Any]]:
    """加载已有篇章纲"""
    from modules.outline.facade import list_arc_summaries
    return await list_arc_summaries(db, novel_id)


async def _load_existing_entities(
    db,
    novel_id: str,
) -> list[dict[str, Any]]:
    """加载已有世界对象"""
    from modules.world.facade import list_entities
    return await list_entities(db, novel_id)


# ============================================================
# 章节卡提取
# ============================================================


@task_handler("chapter_card_extraction")
async def handle_chapter_card_extraction(db, task):
    """处理章节卡提取任务

    从指定章节范围逐章读取正文，调用 LLM 提取章节卡字段。
    已有章节卡（任意 status）的章节跳过。
    产出 status="candidate" 的章节卡，等待用户审核确认。

    Task meta 参数：
    - novel_id: 项目 ID
    - start_chapter: 起始章节
    - end_chapter: 结束章节
    """
    meta = task.meta or {}
    novel_id = meta.get("novel_id", "")
    start_chapter = int(meta.get("start_chapter", 1))
    end_chapter = int(meta.get("end_chapter", 5))

    if not novel_id:
        raise ValueError("novel_id is required for chapter_card_extraction")

    from modules.outline.services import ChapterCardService
    from modules.writing.facade import get_latest_draft_for_chapter

    card_service = ChapterCardService()

    total = end_chapter - start_chapter + 1
    skipped_no_draft = 0
    skipped_has_card = 0
    created = 0
    errors: list[str] = []
    items: list[dict[str, Any]] = []

    for idx in range(start_chapter, end_chapter + 1):
        # 更新进度
        progress = (idx - start_chapter) / max(total, 1)
        task.update_progress(progress)
        await db.flush()

        # 1. 检查是否有正文
        draft = await get_latest_draft_for_chapter(db, novel_id, idx)
        if not draft or not draft.content:
            skipped_no_draft += 1
            items.append({"chapter_index": idx, "status": "skipped", "reason": "no_draft"})
            continue

        # 2. 检查是否已有章节卡
        existing = await card_service.get_by_chapter_index(db, novel_id, idx)
        if existing is not None:
            skipped_has_card += 1
            items.append({"chapter_index": idx, "status": "skipped", "reason": "has_card"})
            continue

        # 3. 调用 LLM 单章提取
        try:
            card_data = await _extract_single_chapter_card(
                db, novel_id, idx, draft.content,
            )

            create_data = ChapterCardCreate(
                chapter_index=idx,
                title=f"第{idx}章",
                chapter_goal=card_data.chapter_goal,
                main_conflict=card_data.main_conflict,
                emotional_point=card_data.emotional_point,
                ending_hook=card_data.ending_hook,
                scene_cards=[s.model_dump() for s in card_data.scene_cards],
                must_happen=card_data.must_happen,
                must_not_happen=card_data.must_not_happen,
                visible_progress=card_data.visible_progress,
                hidden_progress=card_data.hidden_progress,
                status="candidate",
            )
            result = await card_service.create(db, novel_id, create_data)
            created += 1
            items.append({"chapter_index": idx, "card_id": str(result.id), "status": "created"})
        except Exception as exc:
            logger.warning("Failed to extract chapter card for ch %d: %s", idx, exc)
            errors.append(f"第{idx}章: {exc}")

        await db.flush()

    task.update_progress(1.0)
    await db.flush()

    return {
        "total": total,
        "skipped_no_draft": skipped_no_draft,
        "skipped_has_card": skipped_has_card,
        "created": created,
        "errors": errors,
        "items": items,
    }


async def _extract_single_chapter_card(
    db,
    novel_id: str,
    chapter_index: int,
    content: str,
) -> Any:
    """对单章正文调用 LLM 提取章节卡信息"""
    from core.config import get_settings
    from infrastructure.llm.client import LLMClient
    from infrastructure.llm.schemas import LLMCallRequest
    from pydantic import BaseModel

    class _ExtractedSceneCard(BaseModel):
        scene_index: int
        summary: str
        location: str | None = None
        conflict: str | None = None

    class _ExtractedChapterCard(BaseModel):
        chapter_goal: str
        main_conflict: str
        emotional_point: str | None = None
        ending_hook: str | None = None
        scene_cards: list[_ExtractedSceneCard] = []
        must_happen: list[str] = []
        must_not_happen: list[str] = []
        visible_progress: list[str] = []
        hidden_progress: list[str] = []

    # 加载已有世界对象名称作为上下文
    from modules.world.facade import list_entities

    entities = await list_entities(db, novel_id)
    entity_names = ", ".join(e["name"] for e in entities[:30])

    system_prompt = (
        "你是一个小说章节分析助手。"
        "从章节正文中分析并提取章节卡信息。\n\n"
        f"当前章节：第{chapter_index}章\n\n"
        "输出 JSON 对象，包含以下字段：\n"
        "- chapter_goal: 本章核心目标（字符串）\n"
        "- main_conflict: 本章主要冲突（字符串）\n"
        "- emotional_point: 情绪基调（字符串，可选）\n"
        "- ending_hook: 章尾钩子（字符串，可选）\n"
        "- scene_cards: 场景细纲数组，每项包含 scene_index（序号）、"
        "summary（场景摘要）、location（地点，可选）、conflict（场景冲突，可选）\n"
        "- must_happen: 本章必须发生的事件列表\n"
        "- must_not_happen: 本章绝对不能发生的事件列表\n"
        "- visible_progress: 读者可见的剧情进展列表\n"
        "- hidden_progress: 隐藏的剧情进展列表（仅作者知）\n"
        "\n"
        f"已有世界对象：{entity_names}\n"
        "规则：只基于本章正文分析，不凭空创造未发生的内容。"
    )

    settings = get_settings()
    request = LLMCallRequest(
        model=settings.llm_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": content},
        ],
        temperature=0.3,
        response_format={"type": "json_object"},
    )

    llm = LLMClient()
    result = await llm.generate_structured(request, _ExtractedChapterCard)
    return result


