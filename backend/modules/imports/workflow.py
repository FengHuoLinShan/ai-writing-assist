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
<<<<<<< HEAD
        """为已确认的「人物」类型 CoreEntity 创建 Character 扩展表记录"""
        from modules.character.facade import create_character_extension, get_character
=======
        """将已确认的「人物」类型 world_entity 同步到人物档案"""
        from modules.world.facade import (
            create_character,
            get_character_id_by_world_entity,
        )
>>>>>>> origin/worktree-grill-v3
        from modules.world.facade import list_entities

        # 查询所有 character 类型实体
        character_entities = await list_entities(
            db, novel_id,
            entity_type="character",
        )

        total_synced = 0
        for entity in character_entities:
            entity_id = entity["id"]
            # 检查 Character 扩展表是否已有记录
            try:
                await get_character(db, entity_id, novel_id)
                continue  # already exists
            except Exception:
                pass

            try:
                await create_character_extension(
                    db=db, entity_id=entity_id, novel_id=novel_id,
                )
                total_synced += 1
            except Exception as exc:
                logger.warning(
                    "Failed to create Character extension for entity %s: %s",
                    entity_id, exc,
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
