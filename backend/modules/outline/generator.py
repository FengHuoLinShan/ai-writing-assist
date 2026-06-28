"""AI 剧情结构生成器入口。

`PlotStructureGenerator` 是薄协调层，负责把上下文构建、LLM 解析、持久化
三个深度模块串起来。实际逻辑分别位于 `modules.outline.generation.*`。
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from core.config import get_settings
from infrastructure.llm.client import LLMClient
from modules.outline.generation.context_builder import PlotStructureContextBuilder
from modules.outline.generation.parser import PlotStructureParser
from modules.outline.generation.persister import PlotStructurePersister
from modules.outline.services import (
    ForeshadowingPlanService,
    OutlineArcService,
    PlotThreadService,
    RevealPlanService,
    SceneService,
)
from shared.utils import parse_uuid

logger = logging.getLogger(__name__)


class PlotStructureGenerator:
    """AI 剧情结构生成器 — 薄协调层。"""

    def __init__(
        self,
        context_builder: PlotStructureContextBuilder | None = None,
        llm_client: LLMClient | None = None,
        persister: PlotStructurePersister | None = None,
    ) -> None:
        self._context_builder = context_builder or PlotStructureContextBuilder()
        self._llm_client = llm_client or LLMClient()
        self._persister = persister or PlotStructurePersister(
            thread_service=PlotThreadService(),
            arc_service=OutlineArcService(),
            scene_service=SceneService(),
            foreshadowing_service=ForeshadowingPlanService(),
            reveal_service=RevealPlanService(),
        )

    async def generate(
        self,
        db: AsyncSession,
        novel_id: str,
        start_chapter: int,
        end_chapter: int,
        *,
        context_mode: str = "canonical",
        include_pending_objects: bool = False,
    ) -> dict[str, Any]:
        """为指定章节范围生成剧情结构并持久化。

        接口与重构前保持一致：返回包含 total_threads / total_arcs /
        total_scenes / threads / arcs / scenes / extra_sections / warnings 的字典。
        """
        nid = parse_uuid(novel_id, "novel_id")

        context = await self._context_builder.build(
            db,
            novel_id,
            start_chapter,
            end_chapter,
            context_mode=context_mode,
            include_pending_objects=include_pending_objects,
        )

        parser = PlotStructureParser(context)
        settings = get_settings()
        parsed = await parser.parse(
            self._llm_client,
            settings.llm_model,
            start_chapter,
            end_chapter,
        )

        if parsed is None:
            logger.error(
                "All generation attempts returned empty or failed for novel %s",
                novel_id,
            )
            return {
                "total_threads": 0,
                "total_arcs": 0,
                "total_scenes": 0,
                "existing_threads_count": 0,
                "existing_arcs_count": 0,
                "threads": [],
                "arcs": [],
                "scenes": [],
                "extra_sections": {},
                "warnings": ["LLM 多次返回空结果，请重试"],
            }

        result = await self._persister.persist(
            db,
            nid,
            start_chapter,
            end_chapter,
            parsed,
            entity_name_to_id=context.entity_name_to_id,
            character_name_to_id=context.character_name_to_id,
        )
        return result.to_dict()
