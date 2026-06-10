"""Deep Import 工作流编排器

将世界对象抽取、人物同步、剧情结构生成三步串成流水线，
全自动执行，无需用户中途确认。
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from core.container import get as _container_get
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
        return await _container_get("world.run_entity_extraction")(
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
        _list_entities = _container_get("world.list_entities")
        _get_char_id = _container_get("world.get_character_id_by_world_entity")
        _create_char = _container_get("world.create_character")

        character_entities = await _list_entities(
            db, novel_id,
            entity_type="character_ref",
        )

        total_synced = 0
        for entity in character_entities:
            existing = await _get_char_id(db, novel_id, entity["id"])
            if existing is not None:
                continue

            try:
                await _create_char(
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
        _generate = _container_get("outline.generate_structure")
        try:
            result = await _generate(
                db, novel_id,
                start_chapter=start_chapter,
                end_chapter=end_chapter,
            )
            logger.info(
                "剧情结构生成完成: %d 条剧情线, %d 个篇章纲",
                result["total_threads"],
                result["total_arcs"],
            )
            return result
        except Exception as exc:
            logger.warning("剧情结构生成失败: %s", exc)
            return {"total_threads": 0, "total_arcs": 0, "threads": [], "arcs": []}
