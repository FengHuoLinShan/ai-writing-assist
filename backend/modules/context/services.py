"""
Context Compiler 核心业务逻辑

Context Compiler 是系统最核心的智能模块之一。
RAG 负责找资料，Context Compiler 决定哪些资料真正交给模型。

核心原则：
1. 按需加载 — 不预加载所有数据，根据 scope 按需加载
2. Budget 控制 — 有限上下文预算，防止过载
3. Reveal 过滤 — author_safe 模式下隐藏 hidden_truth
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from modules.context.contracts import (
    CONTEXT_BUDGET,
    AUTHOR_ONLY_WARNING,
    StructureContextBundle,
)
from modules.context.schemas import BudgetUsedItem

logger = logging.getLogger(__name__)


# ============================================================
# Scope 定义
# ============================================================

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


@dataclass
class CompileOptions:
    """编译选项"""

    novel_id: str
    task: str
    scope: str
    chapter_index: int | None = None
    arc_id: str | None = None
    entity_ids: list[str] | None = None
    character_ids: list[str] | None = None
    location_ids: list[str] | None = None
    reveal_mode: str = "author_safe"


class ContextCompiler:
    """Context Compiler 核心

    根据 scope 从各模块按需加载数据，组装 StructureContextBundle。
    """

    async def compile(
        self,
        db: AsyncSession,
        options: CompileOptions,
    ) -> StructureContextBundle:
        """主入口：编译结构化上下文

        根据 scope 选择加载哪些模块的数据，组合为 StructureContextBundle。

        Args:
            db: 数据库 session
            options: 编译选项

        Returns:
            StructureContextBundle — 结构化创作上下文包
        """
        bundle = StructureContextBundle(
            novel_id=options.novel_id,
            task=options.task,
            scope=options.scope,
            chapter_index=options.chapter_index,
            arc_id=options.arc_id,
            reveal_mode=options.reveal_mode,
            budget_used={k: 0 for k in CONTEXT_BUDGET},
        )

        loaders = SCOPE_LOADERS.get(options.scope, ["project"])
        warnings: list[str] = []

        for loader_name in loaders:
            loader = getattr(self, f"_load_{loader_name}", None)
            if loader is not None:
                try:
                    await loader(db, options, bundle)
                except Exception as exc:
                    msg = f"加载 {loader_name} 时出错: {exc}"
                    logger.warning(msg)
                    warnings.append(msg)

        bundle.warnings = warnings

        return bundle

    # ---------------------------------------------------------------
    # 各模块数据加载器（按 scope 选择性调用）
    # ---------------------------------------------------------------

    async def _load_project(
        self,
        db: AsyncSession,
        options: CompileOptions,
        bundle: StructureContextBundle,
    ) -> None:
        """加载项目元信息"""
        from modules.project.facade import get_project_context

        ctx = await get_project_context(db, options.novel_id)
        if ctx is not None:
            bundle.project = ctx.model_dump()
        else:
            bundle.warnings.append(f"项目 {options.novel_id} 不存在")

    async def _load_world_entities(
        self,
        db: AsyncSession,
        options: CompileOptions,
        bundle: StructureContextBundle,
    ) -> None:
        """加载世界对象"""

        # 核心对象（高重要性）
        core_limit = CONTEXT_BUDGET.get("core_entities", 8)
        normal_limit = CONTEXT_BUDGET.get("normal_entities", 8)

        # 如果指定了 entity_ids，优先加载这些
        if options.entity_ids:
            from modules.world.facade import get_world_context

            all_limit = core_limit + normal_limit
            limited_ids = options.entity_ids[:all_limit]

            ctx = await get_world_context(
                db, options.novel_id,
                entity_ids=limited_ids,
                reveal_mode=options.reveal_mode,
                limit=all_limit,
            )
            entities = []
            if ctx:
                entities = [e.model_dump() for e in ctx.entities]
            bundle.world_entities = entities
            bundle.budget_used["core_entities"] = min(len(entities), core_limit)
            bundle.budget_used["normal_entities"] = max(
                0, len(entities) - core_limit,
            )
        else:
            # 无指定 ID 时，加载所有 canonical 的正史对象（受 limit 限制）
            from modules.world.facade import get_world_context

            ctx = await get_world_context(
                db, options.novel_id,
                reveal_mode=options.reveal_mode,
                limit=core_limit + normal_limit,
            )
            entities = []
            if ctx:
                entities = [e.model_dump() for e in ctx.entities]

            # 按重要性排序
            entities.sort(key=lambda e: e.get("importance", 0.0), reverse=True)

            core_entities = [
                e for e in entities
                if e.get("importance_level") == "core"
                or e.get("importance", 0.0) >= 0.75
            ][:core_limit]
            normal_entities = [
                e for e in entities
                if e not in core_entities
            ][:normal_limit]

            bundle.world_entities = core_entities + normal_entities
            bundle.budget_used["core_entities"] = len(core_entities)
            bundle.budget_used["normal_entities"] = len(normal_entities)

        # Reveal 过滤：author_safe 模式下标记 hidden_truth
        if options.reveal_mode == "author_safe":
            for ent in bundle.world_entities:
                if ent.get("hidden_truth"):
                    ent["hidden_truth"] = (
                        f"{AUTHOR_ONLY_WARNING} {ent['hidden_truth']}"
                    )

    async def _load_characters(
        self,
        db: AsyncSession,
        options: CompileOptions,
        bundle: StructureContextBundle,
    ) -> None:
        """加载人物信息

        加载后对第一个角色的视角执行知识边界过滤，
        剔除角色不该知道的 world_entities 信息。
        """
        char_limit = CONTEXT_BUDGET.get("characters", 6)

        if options.character_ids:
            limited_ids = options.character_ids[:char_limit]
        else:
            # 无指定 ID 时，从 outline / world context 推断相关人物
            limited_ids = await self._infer_character_ids(
                db, options, char_limit,
            )

        if limited_ids:
            from modules.character.facade import get_characters_context

            ctx = await get_characters_context(
                db, options.novel_id,
                character_ids=limited_ids,
                reveal_mode=options.reveal_mode,
            )
            if ctx:
                bundle.characters = [c.model_dump() for c in ctx.characters]

        # 知识边界过滤：以第一个角色的视角过滤 bundle 中的 world_entities
        if limited_ids and bundle.world_entities and options.scope != "project":
            from modules.character.facade import filter_context_by_character_knowledge

            try:
                filtered = await filter_context_by_character_knowledge(
                    db, options.novel_id,
                    limited_ids[0],
                    bundle.world_entities,
                )
                if filtered is not None:
                    bundle.world_entities = filtered
            except Exception:
                pass

        bundle.budget_used["characters"] = len(bundle.characters)

    async def _infer_character_ids(
        self,
        db: AsyncSession,
        options: CompileOptions,
        limit: int,
    ) -> list[str]:
        """推断相关人物 ID（从当前章节/篇章信息）"""
        char_ids: list[str] = []

        if options.chapter_index is not None:
            from modules.outline.facade import get_chapter_card

            card = await get_chapter_card(db, options.novel_id, options.chapter_index)
            if card and card.involved_character_ids:
                char_ids.extend(card.involved_character_ids)

        if not char_ids and options.arc_id is not None:
            from modules.outline.facade import get_arc_context

            try:
                arc = await get_arc_context(db, options.novel_id, options.arc_id)
                if arc and arc.related_character_ids:
                    char_ids.extend(arc.related_character_ids)
            except Exception:
                pass

        return char_ids[:limit]

    async def _load_geo_locations(
        self,
        db: AsyncSession,
        options: CompileOptions,
        bundle: StructureContextBundle,
    ) -> None:
        """加载地理地点"""
        # geo 模块需要 location_id，如未指定则跳过
        if not options.location_ids and not bundle.world_entities:
            return

        geo_limit = CONTEXT_BUDGET.get("geo_relations", 10)

        if options.location_ids:
            location_ids = options.location_ids[:geo_limit]
        else:
            # 从 world_entities 中推断 location 类型实体
            location_ids = [
                e.get("entity_id", e.get("id", ""))
                for e in bundle.world_entities
                if e.get("entity_type") == "location"
            ][:geo_limit]

        if not location_ids:
            bundle.geo_locations = []
            bundle.budget_used["geo_relations"] = 0
            return

        # TODO: 后续可添加 geo facade 批量查询接口，减少 N+1 查询
        locations = []
        for loc_id in location_ids:
            try:
                from modules.geo.facade import get_location_context

                ctx = await get_location_context(
                    db, options.novel_id, loc_id, depth=1,
                )
                if ctx and ctx.location:
                    loc_data = {
                        "location": ctx.location,
                        "parent_locations": [
                            p.model_dump() if hasattr(p, "model_dump") else p
                            for p in ctx.parent_locations
                        ],
                        "child_locations": [
                            c.model_dump() if hasattr(c, "model_dump") else c
                            for c in ctx.child_locations
                        ],
                        "edges": [
                            e.model_dump() if hasattr(e, "model_dump") else e
                            for e in ctx.edges
                        ],
                        "current_era": ctx.current_era,
                    }
                    locations.append(loc_data)
            except Exception:
                continue

        bundle.geo_locations = locations
        bundle.budget_used["geo_relations"] = min(len(locations), geo_limit)

    async def _load_memory_records(
        self,
        db: AsyncSession,
        options: CompileOptions,
        bundle: StructureContextBundle,
    ) -> None:
        """加载长期记忆"""
        mem_limit = CONTEXT_BUDGET.get("memory", 10)

        from modules.memory.facade import get_recent_story_memory

        records = await get_recent_story_memory(
            db, options.novel_id,
            before_chapter_index=options.chapter_index,
            limit=mem_limit,
        )
        if records:
            bundle.memory_records = [
                r.model_dump() if hasattr(r, "model_dump") else r
                for r in records
            ]

        bundle.budget_used["memory"] = len(bundle.memory_records)

    async def _load_timeline_events(
        self,
        db: AsyncSession,
        options: CompileOptions,
        bundle: StructureContextBundle,
    ) -> None:
        """加载时间线事件"""
        tl_limit = CONTEXT_BUDGET.get("timeline", 8)

        from modules.timeline.facade import get_relevant_timeline_context

        entity_ids_for_tl = (
            options.entity_ids
            or [
                e.get("entity_id", e.get("id", ""))
                for e in bundle.world_entities
            ]
            or None
        )

        events = await get_relevant_timeline_context(
            db, options.novel_id,
            chapter_index=options.chapter_index,
            related_entity_ids=entity_ids_for_tl,
            limit=tl_limit,
        )
        if events:
            bundle.timeline_events = [
                e.model_dump() if hasattr(e, "model_dump") else e
                for e in events
            ]

        bundle.budget_used["timeline"] = len(bundle.timeline_events)

    async def _load_plot_threads(
        self,
        db: AsyncSession,
        options: CompileOptions,
        bundle: StructureContextBundle,
    ) -> None:
        """加载剧情线"""
        from modules.outline.facade import get_active_threads

        threads = await get_active_threads(
            db, options.novel_id,
            chapter_index=options.chapter_index,
            limit=10,
        )
        if threads:
            bundle.plot_threads = [
                t.model_dump() if hasattr(t, "model_dump") else t
                for t in threads
            ]

    async def _load_outline_arc(
        self,
        db: AsyncSession,
        options: CompileOptions,
        bundle: StructureContextBundle,
    ) -> None:
        """加载篇章纲"""
        arc_id = options.arc_id
        if not arc_id and options.chapter_index is not None:
            # 从章节卡推断所属篇章
            from modules.outline.facade import get_chapter_card

            card = await get_chapter_card(db, options.novel_id, options.chapter_index)
            if card and card.arc_id:
                arc_id = card.arc_id

        if arc_id:
            from modules.outline.facade import get_arc_context

            try:
                arc = await get_arc_context(db, options.novel_id, arc_id)
                bundle.outline_arc = (
                    arc.model_dump() if hasattr(arc, "model_dump") else arc
                )
            except Exception:
                pass

    async def _load_chapter_card(
        self,
        db: AsyncSession,
        options: CompileOptions,
        bundle: StructureContextBundle,
    ) -> None:
        """加载章节卡"""
        if options.chapter_index is not None:
            from modules.outline.facade import get_chapter_card

            card = await get_chapter_card(
                db, options.novel_id, options.chapter_index,
            )
            if card:
                bundle.chapter_card = (
                    card.model_dump() if hasattr(card, "model_dump") else card
                )

    async def _load_rag_chunks(
        self,
        db: AsyncSession,
        options: CompileOptions,
        bundle: StructureContextBundle,
    ) -> None:
        """加载 RAG 检索片段

        根据 reveal_mode 决定 visibility 过滤：
        - author_safe: 不限制（保留全量，后续可细化）
        - reader: 只返回读者已知的信息
        """
        rag_limit = CONTEXT_BUDGET.get("rag_chunks", 8)

        # 根据 reveal_mode 推导 visibility 过滤
        rag_visibility: str | None = None
        if options.reveal_mode == "reader":
            rag_visibility = "reader_known"
        # author_safe 模式下不传 visibility（保留全量，让下游决定）

        from modules.rag.facade import retrieve

        result = await retrieve(
            db, options.novel_id,
            query=options.task,
            entity_ids=options.entity_ids,
            character_ids=options.character_ids,
            chapter_index=options.chapter_index,
            visibility=rag_visibility,
            top_k=rag_limit,
        )
        if result and result.chunks:
            bundle.rag_chunks = [
                c.model_dump() if hasattr(c, "model_dump") else c
                for c in result.chunks
            ]

        bundle.budget_used["rag_chunks"] = len(bundle.rag_chunks)
