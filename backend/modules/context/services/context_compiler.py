"""Context Compiler 核心 — 按 scope 调度 Loader"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from modules.context.contracts import CONTEXT_BUDGET, StructureContextBundle
from modules.context.services.loaders import (
    ChapterCardLoader,
    CharactersLoader,
    GeoLocationsLoader,
    MemoryRecordsLoader,
    OutlineArcLoader,
    PlotThreadsLoader,
    ProjectLoader,
    RagChunksLoader,
    TimelineEventsLoader,
    WorldEntitiesLoader,
)
from modules.context.services.protocol import Loader
from modules.context.services.types import CompileOptions

logger = logging.getLogger(__name__)

# Scope → 所需 Loader 名称列表
SCOPE_LOADERS: dict[str, list[str]] = {
    "project": ["project"],
    "world": ["project", "world_entities"],
    "world_character": ["project", "world_entities", "characters"],
    "arc": [
        "project", "world_entities", "characters", "geo_locations",
        "memory_records", "timeline_events", "plot_threads", "outline_arc",
        "rag_chunks",
    ],
    "chapter": [
        "project", "world_entities", "characters", "geo_locations",
        "memory_records", "timeline_events", "plot_threads", "chapter_card",
        "rag_chunks",
    ],
    "full": [
        "project", "world_entities", "characters", "geo_locations",
        "memory_records", "timeline_events", "plot_threads", "outline_arc",
        "chapter_card", "rag_chunks",
    ],
}


class ContextCompiler:
    """Context Compiler 核心

    根据 scope 从各模块按需加载数据，组装 StructureContextBundle。
    Loader 通过依赖注入传入，方便测试和扩展。
    """

    def __init__(self, loaders: list[Loader] | None = None) -> None:
        self._loaders: dict[str, Loader] = {}
        for loader in (loaders or self._default_loaders()):
            self._loaders[loader.name] = loader

    @staticmethod
    def _default_loaders() -> list[Loader]:
        return [
            ProjectLoader(),
            WorldEntitiesLoader(),
            CharactersLoader(),
            GeoLocationsLoader(),
            MemoryRecordsLoader(),
            TimelineEventsLoader(),
            PlotThreadsLoader(),
            OutlineArcLoader(),
            ChapterCardLoader(),
            RagChunksLoader(),
        ]

    async def compile(
        self,
        db: AsyncSession,
        options: CompileOptions,
    ) -> StructureContextBundle:
        """主入口：编译结构化上下文"""
        bundle = StructureContextBundle(
            novel_id=options.novel_id,
            task=options.task,
            scope=options.scope,
            chapter_index=options.chapter_index,
            arc_id=options.arc_id,
            reveal_mode=options.reveal_mode,
            budget_used={k: 0 for k in CONTEXT_BUDGET},
        )

        loader_names = SCOPE_LOADERS.get(options.scope, ["project"])
        warnings: list[str] = []

        for name in loader_names:
            loader = self._loaders.get(name)
            if loader is None:
                msg = f"未知的加载器: {name}"
                logger.warning(msg)
                warnings.append(msg)
                continue
            try:
                await loader.load(db, options, bundle)
            except Exception as exc:
                msg = f"加载 {name} 时出错: {exc}"
                logger.warning(msg)
                warnings.append(msg)

        bundle.warnings = warnings
        return bundle
