"""Deep Import 工作流编排器

将世界对象抽取、人物同步、剧情结构生成三步串成流水线，
全自动执行，无需用户中途确认。
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

            # Step 1: 世界对象抽取
            progress.current_step = DeepImportStep.extract_world
            progress.message = "正在从章节正文中抽取世界对象..."
            result = await self._extract_world(db, novel_id, start_chapter, end_chapter)
            progress.completed_steps.append(DeepImportStep.extract_world.value)
            progress.message = (
                f"世界对象抽取完成，共创建 {result['total_created']} 个对象。"
            )

            # Step 2: 人物同步
            progress.current_step = DeepImportStep.sync_characters
            progress.message = "正在同步人物档案..."
            char_result = await self._sync_characters(db, novel_id)
            progress.completed_steps.append(DeepImportStep.sync_characters.value)
            progress.message = f"人物同步完成，共同步 {char_result['total_synced']} 个人物。"

            # Step 3: 剧情生成
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
        """调用 world facade 从章节正文抽取世界对象"""
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
        from modules.world.facade import (
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
        """outline 模块已移除（minimal-core），跳过剧情结构生成"""
        logger.warning("outline 模块已移除，跳过剧情结构生成")
        return {"total_threads": 0, "total_arcs": 0, "threads": [], "arcs": []}
