"""Outline 任务处理器"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException

from infrastructure.tasks.registry import task_handler
from modules.outline.schemas import ChapterCardCreate

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

    from modules.outline.services import PlotGenerationService

    svc = PlotGenerationService()
    result = await svc.generate(db, novel_id, start_chapter, end_chapter)

    if result["total_threads"] == 0 and result["total_arcs"] == 0:
        raise HTTPException(400, detail=f"未找到章节 {start_chapter}-{end_chapter} 的正文")

    logger.info(
        "Plot structure generated: %d threads, %d arcs",
        result["total_threads"], result["total_arcs"],
    )

    return result


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

    from infrastructure.llm.prompt_loader import load_prompt

    system_prompt = load_prompt("extract_chapter_scene",
        chapter_index=str(chapter_index),
        entity_names=entity_names,
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


