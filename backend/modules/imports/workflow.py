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
            if result.get("degraded") and result.get("total_created", 0) == 0:
                errors = result.get("errors") or ["LLM 抽取未返回可用结构化结果"]
                raise ValueError(f"世界对象抽取失败：{'; '.join(errors[:3])}")

            progress.completed_steps.append(DeepImportStep.extract_world.value)
            progress.current_step = None
            progress.phase = "awaiting_review"
            if result.get("degraded"):
                progress.degraded = True
                progress.warnings.append("世界对象抽取部分批次失败，请审查候选质量。")
            progress.message = (
                f"世界对象抽取完成，共创建 {result['total_created']} 个候选。"
                "请在「候选清洗」视图中审查并确认候选，然后继续深度导入。"
            )
            if result.get("degraded"):
                progress.message += "部分批次抽取失败，建议检查日志或缩小章节范围重试。"

        elif progress.phase == "awaiting_review":
            pending_count = await count_pending_candidates(db, novel_id)
            if pending_count > 0:
                raise ValueError(
                    f"还有 {pending_count} 个候选对象未处理。"
                    "请在「世界对象 → 候选清洗」中确认或忽略所有候选后再继续。"
                )

            progress.phase = "running"

            progress.current_step = DeepImportStep.sync_characters
            progress.message = "正在同步人物档案..."
            char_result = await self._sync_characters(db, novel_id)
            progress.completed_steps.append(DeepImportStep.sync_characters.value)

            progress.current_step = DeepImportStep.generate_plot
            progress.message = "正在生成剧情线和篇章纲..."
            plot_result = await self._generate_plot(
                db,
                novel_id,
                start_chapter,
                end_chapter,
            )
            progress.completed_steps.append(DeepImportStep.generate_plot.value)

            progress.current_step = None
            progress.phase = "done"
            if plot_result["total_threads"] == 0 and plot_result["total_arcs"] == 0:
                progress.degraded = True
                progress.warnings.append(
                    "未生成剧情线或篇章纲，请检查正文内容或 LLM 输出。",
                )
                progress.message = (
                    f"深度导入完成，但未生成剧情线或篇章纲。"
                    f"同步 {char_result['total_synced']} 个人物。"
                )
            else:
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
            db,
            novel_id,
            entity_type="character_ref",
        )

        total_synced = 0
        for entity in character_entities:
            # 通过 character facade 检查是否已存在
            existing = await get_character_id_by_world_entity(
                db,
                novel_id,
                entity["id"],
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
                    entity["name"],
                    exc,
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
        """调用 outline facade 生成剧情线和篇章纲"""
        from modules.outline.facade import generate_plot_structure

        return await generate_plot_structure(db, novel_id, start_chapter, end_chapter)


async def count_pending_candidates(
    db: AsyncSession,
    novel_id: str,
) -> int:
    """统计待处理的候选对象数量（facade 封装）"""
    from modules.world.facade import count_pending_candidates as _count

    return await _count(db, novel_id)
