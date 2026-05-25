"""Deep Import 工作流编排器

将世界对象抽取、人物同步、剧情结构生成三步串成流水线，
每步完成后退回到 checkpoint，用户确认后继续。
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.imports.workflow_schemas import DeepImportProgress, DeepImportStep

logger = logging.getLogger(__name__)


class DeepImportWorkflow:
    """深度导入流水线编排器"""

    async def run_step(
        self,
        db: AsyncSession,
        novel_id: str,
        start_chapter: int,
        end_chapter: int,
        progress: DeepImportProgress,
    ) -> DeepImportProgress:
        if progress.phase == "pending":
            progress.phase = "running"
            progress.current_step = DeepImportStep.extract_world
            progress.message = "正在从章节正文中抽取世界对象..."

            result = await self._extract_world(db, novel_id, start_chapter, end_chapter)
            progress.completed_steps.append(DeepImportStep.extract_world.value)
            progress.current_step = None
            progress.phase = "awaiting_review"
            progress.message = (
                f"世界对象抽取完成，共创建 {result['total_created']} 个候选。"
                "请在「对象库」视图中审查并确认候选，然后继续深度导入。"
            )

        elif progress.phase == "awaiting_review":
            pending_count = await count_pending_candidates(db, novel_id)
            if pending_count > 0:
                raise ValueError(
                    f"还有 {pending_count} 个候选对象未处理。"
                    "请在「世界对象 → 对象库」中确认或忽略所有候选后再继续。"
                )

            progress.phase = "running"

            progress.current_step = DeepImportStep.sync_characters
            progress.message = "正在同步人物档案..."
            char_result = await self._sync_characters(db, novel_id)
            progress.completed_steps.append(DeepImportStep.sync_characters.value)

            progress.current_step = DeepImportStep.generate_plot
            progress.message = "正在生成剧情线和篇章纲..."
            plot_result = await self._generate_plot(db, novel_id, start_chapter, end_chapter)
            progress.completed_steps.append(DeepImportStep.generate_plot.value)

            progress.current_step = None
            progress.phase = "done"
            progress.message = (
                f"深度导入完成！"
                f"同步 {char_result['total_synced']} 个人物，"
                f"创建 {plot_result['total_threads']} 条剧情线、"
                f"{plot_result['total_arcs']} 个篇章纲。"
            )

        else:
            raise ValueError(f"无法处理当前进度状态: {progress.phase}")

        return progress

    # ------------------------------------------------------------------
    # Step 1: 世界对象抽取
    # ------------------------------------------------------------------

    async def _extract_world(
        self,
        db: AsyncSession,
        novel_id: str,
        start_chapter: int,
        end_chapter: int,
    ) -> dict[str, Any]:
        """调用 world facade 从章节正文抽取世界对象候选"""
        from modules.world.facade import run_entity_extraction

        return await run_entity_extraction(
            db,
            novel_id=novel_id,
            start_chapter=start_chapter,
            end_chapter=end_chapter,
        )

    # ------------------------------------------------------------------
    # Step 2: 人物同步
    # ------------------------------------------------------------------

    async def _sync_characters(
        self,
        db: AsyncSession,
        novel_id: str,
    ) -> dict[str, Any]:
        """将已确认的「人物」类型 world_entity 同步到人物档案"""
        from modules.character.facade import (
            create_character,
            get_character_id_by_world_entity,
        )
        from modules.world.facade import list_entities

        # 通过 world facade 查询所有 character_ref 实体
        character_entities = await list_entities(
            db, novel_id,
            entity_type="character_ref",
        )

        total_synced = 0
        for entity in character_entities:
            # 通过 character facade 检查是否已存在
            existing = await get_character_id_by_world_entity(
                db, novel_id, entity["id"],
            )
            if existing is not None:
                continue

            try:
                await create_character(
                    db=db,
                    novel_id=novel_id,
                    name=entity["name"],
                    world_entity_id=entity["id"],
                )
                total_synced += 1
            except Exception as exc:
                logger.warning(
                    "Failed to create Character for entity %s: %s",
                    entity["name"], exc,
                )

        await db.flush()
        return {"total_synced": total_synced, "total_entities": len(character_entities)}

    # ------------------------------------------------------------------
    # Step 3: 剧情结构生成
    # ------------------------------------------------------------------

    async def _generate_plot(
        self,
        db: AsyncSession,
        novel_id: str,
        start_chapter: int,
        end_chapter: int,
    ) -> dict[str, Any]:
        """调用 LLM 生成剧情线和篇章纲"""
        from pydantic import BaseModel

        from core.config import get_settings
        from infrastructure.llm.client import LLMClient
        from infrastructure.llm.schemas import LLMCallRequest
        from modules.outline.facade import (
            create_arc,
            create_thread,
            list_arc_summaries,
            list_thread_summaries,
            update_arc,
            update_thread,
        )
        from modules.outline.schemas import (
            OutlineArcCreate,
            OutlineArcUpdate,
            PlotThreadCreate,
            PlotThreadUpdate,
        )
        from modules.world.facade import list_entities
        from modules.writing.facade import get_latest_draft_for_chapter

        # 1. 加载章节正文
        chapters = []
        for idx in range(start_chapter, end_chapter + 1):
            draft = await get_latest_draft_for_chapter(db, novel_id, idx)
            if draft and draft.content:
                chapters.append(f"--- 第{idx}章 ---\n{draft.content}")

        if not chapters:
            raise ValueError(f"未找到章节 {start_chapter}-{end_chapter} 的正文")

        batch_text = "\n\n".join(chapters)

        # 2. 通过 facade 加载已有上下文
        existing_entities = await list_entities(db, novel_id)
        existing_threads = await list_thread_summaries(db, novel_id)
        existing_arcs = await list_arc_summaries(db, novel_id)

        # 3. LLM 输出 Schema
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

        # 4. 构建 Prompt
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
            "- plot_threads: 剧情线数组...\n"
            "- outline_arcs: 篇章纲数组...\n\n"
            f"{context_note}"
            "规则：只基于已有章节正文分析，不凭空创造未发生的内容。\n"
            "增量规则：\n"
            "- 已有记录通过 existing_id 标记，此时更新其字段\n"
            "- 新记录 existing_id 设为 null\n"
            "- 不修改不可变字段（name, thread_type, arc_index 等）\n"
            "start_chapter 和 planned_payoff_chapter 必须为正整数（≥1），不确定时写 null。"
        )

        settings = get_settings()
        request = LLMCallRequest(
            model=settings.llm_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": batch_text},
            ],
            temperature=0.3,
            response_format={"type": "json_object"},
        )

        llm = LLMClient()
        parsed = await llm.generate_structured(request, _PlotOutput)

        # 5. 通过 facade 写入数据库
        created_threads = []
        created_arcs = []

        for pt in parsed.plot_threads:
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
                        await update_thread(
                            db, pt.existing_id,
                            PlotThreadUpdate(**updates),
                            novel_id,
                        )
                    except Exception as exc:
                        logger.warning("Failed to update thread %s: %s", pt.existing_id, exc)
            else:
                data = PlotThreadCreate(
                    name=pt.name, thread_type=pt.thread_type,
                    summary=pt.summary, visible_goal=pt.visible_goal,
                    start_chapter=sc, planned_payoff_chapter=ppc,
                )
                try:
                    created = await create_thread(db, novel_id, data)
                    created_threads.append({"id": str(created.id), "name": created.name})
                except Exception as exc:
                    logger.warning("Failed to create thread %s: %s", pt.name, exc)

        for arc in parsed.outline_arcs:
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
                        await update_arc(
                            db, arc.existing_id,
                            OutlineArcUpdate(**updates),
                            novel_id,
                        )
                    except Exception as exc:
                        logger.warning("Failed to update arc %s: %s", arc.existing_id, exc)
            else:
                data = OutlineArcCreate(
                    title=arc.title, arc_index=arc.arc_index,
                    start_chapter=arc.start_chapter, end_chapter=arc.end_chapter,
                    arc_goal=arc.arc_goal, core_conflict=arc.core_conflict,
                    climax=arc.climax, result=arc.result,
                )
                try:
                    created = await create_arc(db, novel_id, data)
                    created_arcs.append({"id": str(created.id), "title": created.title})
                except Exception as exc:
                    logger.warning("Failed to create arc %s: %s", arc.title, exc)

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


async def count_pending_candidates(
    db: AsyncSession,
    novel_id: str,
) -> int:
    """统计待处理的候选对象数量（facade 封装）"""
    from modules.world.facade import count_pending_candidates as _count
    return await _count(db, novel_id)
