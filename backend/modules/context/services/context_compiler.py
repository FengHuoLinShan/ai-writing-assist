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
    SceneLoader,
    WorldEntitiesLoader,
)
from modules.context.services.protocol import Loader
from modules.context.services.types import CompileOptions

logger = logging.getLogger(__name__)

SCOPE_LOADERS: dict[str, list[str]] = {
    "project": ["project"],
    "world": ["project", "world_entities"],
    "world_character": ["project", "world_entities", "characters"],
    "arc": [
        "scene",
        "project",
        "world_entities",
        "characters",
        "memory_records",
        "events",
        "rag_chunks",
        "plot_threads",
        "outline_arc",
    ],
    "chapter": [
        "scene",
        "project",
        "world_entities",
        "characters",
        "memory_records",
        "events",
        "rag_chunks",
        "plot_threads",
        "outline_arc",
    ],
    "full": [
        "scene",
        "project",
        "world_entities",
        "characters",
        "memory_records",
        "events",
        "rag_chunks",
        "plot_threads",
        "outline_arc",
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
        for loader in loaders or self._default_loaders():
            self._loaders[loader.name] = loader
        self._constraint_engine = ConstraintEngine()

    @staticmethod
    def _default_loaders() -> list[Loader]:
        # _default_loaders() only registers the available loaders.
        # Actual execution order is determined by SCOPE_LOADERS and the
        # prerequisite/dependent phase split inside compile().
        return [
            ProjectLoader(),
            WorldEntitiesLoader(),
            CharactersLoader(),
            EventsLoader(),
            MemoryRecordsLoader(),
            RagChunksLoader(),
            PlotThreadsLoader(),
            OutlineArcLoader(),
            SceneLoader(),
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
        scene_index = bundle.scene.get("scene_index") if bundle.scene else None
        constraint_sections = await self._constraint_engine.compile_constraints(
            db,
            options.novel_id,
            scene_id=options.scene_id,
            scene_index=scene_index,
            chapter_index=options.chapter_index,
        )
        sections.extend(constraint_sections)
        sections, exclusion_warnings = self._apply_section_exclusions(
            sections,
            options.excluded_asset_ids.get("context_sections", []),
        )
        warnings = [*bundle.warnings, *exclusion_warnings]
        total = sum(s.token_count for s in sections)
        ctx = CompiledContext(
            sections=sections,
            total_tokens=total,
            budget_tokens=budget_tokens,
            compiled_at=datetime.utcnow().isoformat(),
            warnings=warnings,
        )
        return ctx.enforce_budget()

    @staticmethod
    def _apply_section_exclusions(
        sections: list[ContextSection],
        excluded_section_keys: list[str],
    ) -> tuple[list[ContextSection], list[str]]:
        excluded = set(excluded_section_keys or [])
        if not excluded:
            return sections, []

        warnings: list[str] = []
        kept: list[ContextSection] = []
        for section in sections:
            if section.key not in excluded:
                kept.append(section)
                continue
            if section.tier == Tier.P0 or not section.can_exclude:
                warnings.append(f"核心参考资料不可排除：{section.key}")
                kept.append(section)
        return kept, warnings

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
                    title="本次任务",
                    preview=bundle.task,
                    status="system",
                    activation_reason="用户当前发起的 AI 操作",
                    sources=[
                        {
                            "type": "task",
                            "id": "writing_objective",
                            "label": bundle.task,
                            "status": "system",
                        }
                    ],
                    can_exclude=False,
                )
            )

        if bundle.scene:
            content = json.dumps(bundle.scene, ensure_ascii=False, indent=2)
            scene_id = options.scene_id if options else None
            scene_label = str(
                bundle.scene.get("title")
                or bundle.scene.get("name")
                or bundle.scene.get("scene_id")
                or scene_id
                or "当前 Scene"
            )
            sections.append(
                ContextSection(
                    key="scene_blueprint",
                    tier=Tier.P0,
                    content=content,
                    token_count=max(1, len(content) // 4),
                    title="当前 Scene",
                    preview=content[:160],
                    status=options.context_mode if options else "canonical",
                    activation_reason="当前 scene_id/章节范围",
                    sources=[
                        {
                            "type": "scene",
                            "id": str(scene_id or scene_label),
                            "label": scene_label,
                            "status": options.context_mode if options else "canonical",
                        }
                    ],
                    can_exclude=False,
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
                    title="人物与视角知识",
                    preview=prefixed[:160],
                    status=options.context_mode if options else "canonical",
                    activation_reason="scope 包含人物资料",
                    sources=self._sources_from_items(
                        bundle.characters,
                        default_type="character",
                        status=options.context_mode if options else "canonical",
                    ),
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
                    title="记忆与时间线变化",
                    preview=prefixed[:160],
                    status=options.context_mode if options else "canonical",
                    activation_reason="章节/Scene 相邻上下文",
                    sources=self._sources_from_items(
                        (
                            bundle.memory_records
                            if isinstance(bundle.memory_records, list)
                            else [bundle.memory_records]
                        ),
                        default_type="memory",
                        status=options.context_mode if options else "canonical",
                    ),
                )
            )

        if bundle.plot_threads:
            content = "\n".join(str(t) for t in bundle.plot_threads)
            sections.append(
                ContextSection(
                    key="open_narrative_obligations",
                    tier=Tier.P2,
                    content=content,
                    token_count=max(1, len(content) // 4),
                    truncatable_per_item=True,
                    title="剧情线与未完成义务",
                    preview=content[:160],
                    status=options.context_mode if options else "canonical",
                    activation_reason="scope 包含剧情结构资料",
                    sources=self._sources_from_items(
                        bundle.plot_threads,
                        default_type="plot_thread",
                        status=options.context_mode if options else "canonical",
                    ),
                )
            )

        if bundle.rag_chunks:
            content = "\n".join(str(c) for c in bundle.rag_chunks)
            sections.append(
                ContextSection(
                    key="retrieval_evidence_packs",
                    tier=Tier.P2,
                    content=content,
                    token_count=max(1, len(content) // 4),
                    truncatable_per_item=True,
                    title="RAG 证据包",
                    preview=content[:160],
                    status=options.context_mode if options else "canonical",
                    activation_reason="RAG 检索命中",
                    sources=self._sources_from_items(
                        bundle.rag_chunks,
                        default_type="rag",
                        status=options.context_mode if options else "canonical",
                    ),
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
                    title="项目风格与基础设定",
                    preview=content[:160],
                    status="canonical",
                    activation_reason="项目基础资料",
                    sources=self._sources_from_items(
                        [bundle.project],
                        default_type="project",
                        status="canonical",
                    ),
                )
            )

        warnings = list(bundle.warnings)
        if warnings:
            content = "\n".join(f"- {w}" for w in warnings)
            sections.append(
                ContextSection(
                    key="compiler_warnings",
                    tier=Tier.P4,
                    content=content,
                    token_count=max(1, len(content) // 4),
                    title="编译警告",
                    preview=content[:160],
                    status="system",
                    activation_reason="编译过程产生的提示",
                    sources=[
                        {
                            "type": "compiler",
                            "id": "compiler_warnings",
                            "label": "编译警告",
                            "status": "system",
                        }
                    ],
                    can_exclude=False,
                )
            )

        return sections

    @staticmethod
    def _sources_from_items(
        items,
        *,
        default_type: str,
        status: str,
    ) -> list[dict[str, str]]:
        sources: list[dict[str, str]] = []
        for index, item in enumerate(items or []):
            if isinstance(item, dict):
                source_id = (
                    item.get("id")
                    or item.get("entity_id")
                    or item.get("character_id")
                    or item.get("chunk_id")
                    or item.get("scene_id")
                    or item.get("novel_id")
                    or f"{default_type}-{index + 1}"
                )
                label = (
                    item.get("name")
                    or item.get("title")
                    or item.get("summary")
                    or item.get("text")
                    or str(source_id)
                )
                item_status = str(item.get("status") or status)
                source_type = str(item.get("source_type") or default_type)
            else:
                source_id = f"{default_type}-{index + 1}"
                label = str(item)
                item_status = status
                source_type = default_type
            sources.append(
                {
                    "type": str(source_type),
                    "id": str(source_id),
                    "label": str(label)[:80],
                    "status": item_status,
                }
            )
        return sources
