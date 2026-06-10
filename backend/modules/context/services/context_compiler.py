"""Context Compiler 核心 — 按 scope 调度 Loader"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from modules.context.contracts import CONTEXT_BUDGET, StructureContextBundle
from modules.context.services.compiled_context import (
    CompiledContext,
    ContextSection,
    Tier,
)
from modules.context.services.constraint_engine import ConstraintEngine
from modules.context.services.loaders import (
    CharactersLoader,
    EventsLoader,
    MemoryRecordsLoader,
    OutlineArcLoader,
    PlotThreadsLoader,
    ProjectLoader,
    RagChunksLoader,
    WorldEntitiesLoader,
    is_loader_available,
)
from modules.context.services.protocol import Loader
from modules.context.services.types import CompileOptions

logger = logging.getLogger(__name__)

SCOPE_LOADERS: dict[str, list[str]] = {
    "project": ["project"],
    "world": ["project", "world_entities"],
    "world_character": ["project", "world_entities", "characters"],
    "arc": [
        "project", "world_entities", "characters",
        "memory_records", "events", "rag_chunks",
        "plot_threads", "outline_arc",
    ],
    "chapter": [
        "project", "world_entities", "characters",
        "memory_records", "events", "rag_chunks",
        "plot_threads", "outline_arc",
    ],
    "full": [
        "project", "world_entities", "characters",
        "memory_records", "events", "rag_chunks",
        "plot_threads", "outline_arc",
    ],
}

_PREREQUISITE_LOADERS = {"project", "world_entities"}


class ContextCompiler:
    """Context Compiler 核心

    根据 scope 从各模块按需加载数据，组装 StructureContextBundle。
    Loader 通过依赖注入传入，方便测试和扩展。
    """

    def __init__(self, loaders: list[Loader] | None = None) -> None:
        self._loaders: dict[str, Loader] = {}
        for loader in (loaders or self._default_loaders()):
            self._loaders[loader.name] = loader
        self._constraint_engine = ConstraintEngine()

    @staticmethod
    def _default_loaders() -> list[Loader]:
        return [
            ProjectLoader(),
            WorldEntitiesLoader(),
            CharactersLoader(),
            EventsLoader(),
            MemoryRecordsLoader(),
            RagChunksLoader(),
            PlotThreadsLoader(),
            OutlineArcLoader(),
        ]

    async def compile(
        self,
        db: AsyncSession,
        options: CompileOptions,
    ) -> StructureContextBundle:
        """主入口：编译结构化上下文

        分两阶段并发加载：
        1. 先加载前置 loader（project、world_entities）
        2. 再并发加载其余 loader（部分依赖 world_entities 的输出）
        """
        bundle = StructureContextBundle(
            novel_id=options.novel_id,
            task=options.task,
            scope=options.scope,
            chapter_index=options.chapter_index,
            arc_id=options.arc_id,
            reveal_mode=options.reveal_mode,
            viewpoint_character_id=options.viewpoint_character_id,
            budget_used={k: 0 for k in CONTEXT_BUDGET},
        )

        loader_names = SCOPE_LOADERS.get(options.scope, ["project"])
        warnings: list[str] = []

        prerequisite_names = [n for n in loader_names if n in _PREREQUISITE_LOADERS]
        dependent_names = [n for n in loader_names if n not in _PREREQUISITE_LOADERS]

        for name in prerequisite_names:
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

        if dependent_names:
            tasks = []
            task_names = []
            for name in dependent_names:
                loader = self._loaders.get(name)
                if loader is None:
                    msg = f"未知的加载器: {name}"
                    logger.warning(msg)
                    warnings.append(msg)
                    continue
                tasks.append(loader.load(db, options, bundle))
                task_names.append(name)

            results = await asyncio.gather(*tasks, return_exceptions=True)
            for task_name, result in zip(task_names, results):
                if isinstance(result, Exception):
                    msg = f"加载 {task_name} 时出错: {result}"
                    logger.warning(msg)
                    warnings.append(msg)

        bundle.warnings = warnings
        return bundle

    async def compile_with_tiers(
        self,
        db: AsyncSession,
        options: CompileOptions,
        budget_tokens: int = 4000,
    ) -> CompiledContext:
        """新入口：按 Tier 编译上下文，返回 CompiledContext IR"""
        bundle = await self.compile(db, options)
        sections = self._build_sections(bundle, options)
        constraint_sections = await self._constraint_engine.compile_constraints(
            db,
            options.novel_id,
            scene_id=None,
            chapter_index=options.chapter_index,
        )
        sections.extend(constraint_sections)
        total = sum(s.token_count for s in sections)
        ctx = CompiledContext(
            sections=sections,
            total_tokens=total,
            budget_tokens=budget_tokens,
            compiled_at=datetime.utcnow().isoformat(),
        )
        return ctx.enforce_budget()

    def _build_sections(
        self,
        bundle: StructureContextBundle,
        options: CompileOptions | None = None,
    ) -> list[ContextSection]:
        """将 StructureContextBundle 转为 Tier 标注的 ContextSection 列表"""
        sections: list[ContextSection] = []
        is_debug = options is not None and options.mode == "debug"
        mode_prefix = "[Snapshot 模式] " if is_debug else "[Delta 模式] "

        if bundle.task:
            sections.append(
                ContextSection(
                    key="writing_objective",
                    tier=Tier.P0,
                    content=bundle.task,
                    token_count=max(1, len(bundle.task) // 4),
                )
            )

        if bundle.chapter_card:
            content = json.dumps(
                bundle.chapter_card, ensure_ascii=False, indent=2
            )
            sections.append(
                ContextSection(
                    key="scene_blueprint",
                    tier=Tier.P0,
                    content=content,
                    token_count=max(1, len(content) // 4),
                )
            )

        if bundle.characters:
            content = "\n".join(str(c) for c in bundle.characters)
            prefixed = mode_prefix + content
            sections.append(
                ContextSection(
                    key="pov_knowledge",
                    tier=Tier.P1,
                    content=prefixed,
                    token_count=max(1, len(prefixed) // 4),
                )
            )

        if bundle.memory_records:
            content = "\n".join(str(m) for m in bundle.memory_records)
            prefixed = mode_prefix + content
            sections.append(
                ContextSection(
                    key="delta_timeline",
                    tier=Tier.P1,
                    content=prefixed,
                    token_count=max(1, len(prefixed) // 4),
                    truncatable_per_item=True,
                )
            )

        if bundle.plot_threads:
            content = "\n".join(str(t) for t in bundle.plot_threads)
            sections.append(
                ContextSection(
                    key="narrative_obligations",
                    tier=Tier.P2,
                    content=content,
                    token_count=max(1, len(content) // 4),
                    truncatable_per_item=True,
                )
            )

        if bundle.rag_chunks:
            content = "\n".join(str(c) for c in bundle.rag_chunks)
            sections.append(
                ContextSection(
                    key="retrieval_evidence",
                    tier=Tier.P2,
                    content=content,
                    token_count=max(1, len(content) // 4),
                    truncatable_per_item=True,
                )
            )

        if bundle.project:
            content = str(bundle.project)
            sections.append(
                ContextSection(
                    key="style_assets",
                    tier=Tier.P3,
                    content=content,
                    token_count=max(1, len(content) // 4),
                )
            )

        if bundle.warnings:
            content = "\n".join(f"- {w}" for w in bundle.warnings)
            sections.append(
                ContextSection(
                    key="compiler_warnings",
                    tier=Tier.P4,
                    content=content,
                    token_count=max(1, len(content) // 4),
                )
            )

        return sections
