"""Context Compiler 核心 — 按 scope 调度 Loader"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.llm.token_estimation import estimate_token_count
from modules.context.contracts import (
    CONTEXT_BUDGET,
    CompileOptions,
    StructureContextBundle,
)
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
    WorldBibleLoader,
    WorldEntitiesLoader,
)
from modules.context.services.protocol import Loader

logger = logging.getLogger(__name__)

SCOPE_LOADERS: dict[str, list[str]] = {
    "project": ["project", "world_bible"],
    "world": ["project", "world_entities", "world_bible"],
    "world_character": ["project", "world_entities", "characters", "world_bible"],
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
        "world_bible",
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
        "world_bible",
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
        "world_bible",
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
            WorldBibleLoader(),
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

        bundle.warnings = list(dict.fromkeys([*bundle.warnings, *warnings]))
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
            reveal_mode=options.reveal_mode,
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
                    token_count=estimate_token_count(bundle.task),
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

        if options is not None and options.reveal_mode == "character":
            sections.extend(self._build_character_reveal_sections(bundle, options))
            return sections

        if options is not None and options.reveal_mode == "reader":
            sections.extend(self._build_reader_reveal_sections(bundle, options))
            return sections

        if bundle.world_bible_synopsis:
            synopsis = bundle.world_bible_synopsis
            content = str(synopsis.get("content") or "").strip()
            if content:
                wrapped = (
                    "<WORLD_BIBLE_SYNOPSIS_DATA>\n"
                    f"{content}\n"
                    "</WORLD_BIBLE_SYNOPSIS_DATA>"
                )
                sections.append(
                    ContextSection(
                        key="world_bible_synopsis",
                        tier=Tier.P1,
                        content=wrapped,
                        token_count=estimate_token_count(wrapped),
                        title="世界观简介",
                        preview=content[:160],
                        status="canonical",
                        activation_reason="作者在本次生成中启用了世界观简介",
                        sources=[
                            {
                                "type": "world_bible_synopsis",
                                "id": str(synopsis.get("revision_id") or "fallback"),
                                "label": "世界观简介",
                                "status": str(synopsis.get("status") or "unknown"),
                            }
                        ],
                        can_exclude=True,
                        retrieval_metadata={
                            "revision_id": synopsis.get("revision_id"),
                            "source_hash": synopsis.get("source_hash"),
                            "block_hash": synopsis.get("block_hash"),
                            "stale": bool(synopsis.get("stale")),
                            "fallback": bool(synopsis.get("fallback")),
                            "coverage": dict(synopsis.get("coverage") or {}),
                            "omitted_reasons": list(
                                synopsis.get("omitted_reasons") or []
                            ),
                        },
                    )
                )

        if bundle.world_bible_working_pages:
            content = json.dumps(
                bundle.world_bible_working_pages,
                ensure_ascii=False,
                sort_keys=True,
            )
            wrapped = (
                "<WORLD_BIBLE_WORKING_PAGES_DATA>\n"
                f"{content}\n"
                "</WORLD_BIBLE_WORKING_PAGES_DATA>"
            )
            sections.append(
                ContextSection(
                    key="world_bible_working_pages",
                    tier=Tier.P1,
                    content=wrapped,
                    token_count=estimate_token_count(wrapped),
                    title="世界书工作稿",
                    preview=content[:160],
                    status="working",
                    activation_reason="作者显式选择了未发布工作稿",
                    sources=self._sources_from_items(
                        bundle.world_bible_working_pages,
                        default_type="world_bible_draft",
                        status="working",
                    ),
                    can_exclude=True,
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
                    token_count=estimate_token_count(content),
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
                    token_count=estimate_token_count(prefixed),
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
                    token_count=estimate_token_count(prefixed),
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
                    token_count=estimate_token_count(content),
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
                    token_count=estimate_token_count(content),
                    truncatable_per_item=True,
                    title="RAG 证据包",
                    preview=content[:160],
                    status=options.context_mode if options else "canonical",
                    activation_reason=self._retrieval_activation_reason(bundle),
                    sources=self._sources_from_items(
                        bundle.rag_chunks,
                        default_type="rag",
                        status=options.context_mode if options else "canonical",
                    ),
                    retrieval_metadata=dict(bundle.retrieval_trace or {}),
                )
            )

        if bundle.project:
            content = self._format_project_context(bundle.project)
            sections.append(
                ContextSection(
                    key="style_assets",
                    tier=Tier.P3,
                    content=content,
                    token_count=estimate_token_count(content),
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
                    token_count=estimate_token_count(content),
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

    def _build_reader_reveal_sections(
        self,
        bundle: StructureContextBundle,
        options: CompileOptions,
    ) -> list[ContextSection]:
        """Build a reader-view package from already visibility-checked evidence.

        Reader mode deliberately excludes author planning assets such as full Scene
        cards, plot threads, memories, outline arcs, and character profiles. Those
        assets can contain future facts even when an individual loader has applied
        field-level redaction.
        """
        sections: list[ContextSection] = []
        status = options.context_mode

        visible_world = self._format_reader_visible_world(bundle.world_entities)
        if visible_world:
            sections.append(
                self._make_section(
                    key="reader_visible_world",
                    tier=Tier.P1,
                    title="读者已知世界信息",
                    content=visible_world,
                    status=status,
                    activation_reason="ReaderRevealPolicy 与截止位置过滤后",
                    sources=self._safe_sources_from_items(
                        bundle.world_entities,
                        default_type="world_entity",
                        status=status,
                    ),
                )
            )

        visible_evidence = self._format_reader_visible_evidence(bundle.rag_chunks)
        if visible_evidence:
            sections.append(
                self._make_section(
                    key="reader_visible_manuscript",
                    tier=Tier.P1,
                    title="读者可见正文证据",
                    content=visible_evidence,
                    status=status,
                    activation_reason=self._retrieval_activation_reason(bundle),
                    sources=self._safe_sources_from_items(
                        bundle.rag_chunks,
                        default_type="writing_source",
                        status=status,
                    ),
                    truncatable_per_item=True,
                    retrieval_metadata=dict(bundle.retrieval_trace or {}),
                )
            )

        if bundle.project:
            content = self._format_project_style(bundle.project)
            if content:
                sections.append(
                    self._make_section(
                        key="style_assets",
                        tier=Tier.P3,
                        title="项目风格与基础设定",
                        content=content,
                        status="canonical",
                        activation_reason="不含剧情事实的项目风格资料",
                        sources=self._safe_sources_from_items(
                            [bundle.project],
                            default_type="project",
                            status="canonical",
                        ),
                    )
                )

        if bundle.warnings:
            content = "\n".join(f"- {warning}" for warning in bundle.warnings)
            sections.append(
                self._make_section(
                    key="compiler_warnings",
                    tier=Tier.P4,
                    title="编译警告",
                    content=content,
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

    def _build_character_reveal_sections(
        self,
        bundle: StructureContextBundle,
        options: CompileOptions,
    ) -> list[ContextSection]:
        """Build character-view sections without rendering legacy author context."""
        sections: list[ContextSection] = []
        status = options.context_mode

        if bundle.characters:
            content = self._format_role_profile(bundle.characters, options)
            sections.append(
                self._make_section(
                    key="role_profile",
                    tier=Tier.P0,
                    title="POV 角色档案",
                    content=content,
                    status=status,
                    activation_reason="character reveal 的视角人物资料",
                    sources=self._safe_sources_from_items(
                        bundle.characters,
                        default_type="character",
                        status=status,
                    ),
                    can_exclude=False,
                )
            )

        visible_knowledge = self._format_role_visible_knowledge(bundle.world_entities)
        if visible_knowledge:
            sections.append(
                self._make_section(
                    key="role_visible_knowledge",
                    tier=Tier.P1,
                    title="角色可见知识",
                    content=visible_knowledge,
                    status=status,
                    activation_reason="CharacterKnowledge 与默认可见性规则过滤后",
                    sources=self._safe_sources_from_items(
                        bundle.world_entities,
                        default_type="world_entity",
                        status=status,
                    ),
                )
            )

        relationship_content = (
            "未显式公开或未由 relation 级 CharacterKnowledge 授权的关系描述已排除。"
        )
        sections.append(
            self._make_section(
                key="role_relationship_context",
                tier=Tier.P1,
                title="角色可见关系",
                content=relationship_content,
                status=status,
                activation_reason="隐性关系描述默认不进入角色视角",
                sources=[],
            )
        )

        if bundle.scene:
            scene_perception = self._format_role_scene_perception(bundle.scene, options)
            sections.append(
                self._make_section(
                    key="role_scene_perception",
                    tier=Tier.P0,
                    title="当前 Scene 可感知信息",
                    content=scene_perception,
                    status=status,
                    activation_reason="当前 Scene 中角色可感知的场面锚点",
                    sources=self._safe_sources_from_items(
                        [bundle.scene],
                        default_type="scene",
                        status=status,
                    ),
                    can_exclude=False,
                )
            )

            director_constraints = self._format_scene_director_constraints(bundle.scene)
            sections.append(
                self._make_section(
                    key="scene_director_constraints",
                    tier=Tier.P0,
                    title="Scene 导演约束",
                    content=director_constraints,
                    status="director_only",
                    activation_reason="Scene goal/core_conflict/must/must_not 等作者约束",
                    sources=self._safe_sources_from_items(
                        [bundle.scene],
                        default_type="scene",
                        status="director_only",
                    ),
                    can_exclude=False,
                )
            )

        time_boundary = self._format_scene_time_boundary(bundle, options)
        sections.append(
            self._make_section(
                key="scene_time_boundary",
                tier=Tier.P0,
                title="Scene 时间边界",
                content=time_boundary,
                status="system",
                activation_reason="说明 scene_id 在本次 character reveal 中的边界语义",
                sources=[
                    {
                        "type": "scene_boundary",
                        "id": str(options.scene_id or "current_scene"),
                        "label": str(options.scene_id or "current_scene"),
                        "status": "system",
                    }
                ],
                can_exclude=False,
            )
        )

        evidence = self._format_current_scene_evidence(bundle.rag_chunks, options)
        if evidence:
            sections.append(
                self._make_section(
                    key="current_scene_evidence",
                    tier=Tier.P1,
                    title="当前 Scene RAG 证据",
                    content=evidence,
                    status=status,
                    activation_reason="RAG scene_id 严格过滤后的当前场景片段",
                    sources=self._safe_sources_from_items(
                        self._character_safe_rag_chunks(bundle.rag_chunks, options),
                        default_type="rag",
                        status=status,
                    ),
                    truncatable_per_item=True,
                    retrieval_metadata=dict(bundle.retrieval_trace or {}),
                )
            )

        if bundle.memory_records:
            content = (
                f"已加载 {len(bundle.memory_records)} 条记忆记录；"
                "character reveal 不渲染 memory_snapshots.full_state 或完整 JSON，"
                "仅允许后续拆解过滤后的摘要/事件单位进入角色视角。"
            )
            sections.append(
                self._make_section(
                    key="historical_role_context",
                    tier=Tier.P2,
                    title="历史角色上下文",
                    content=content,
                    status=status,
                    activation_reason="记忆记录已按角色视角阻断 raw full_state",
                    sources=self._safe_sources_from_items(
                        bundle.memory_records,
                        default_type="memory",
                        status=status,
                    ),
                    truncatable_per_item=True,
                )
            )

        if bundle.project:
            content = self._format_project_style(bundle.project)
            sections.append(
                self._make_section(
                    key="style_assets",
                    tier=Tier.P3,
                    title="项目风格与基础设定",
                    content=content,
                    status="canonical",
                    activation_reason="项目基础资料",
                    sources=self._safe_sources_from_items(
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
                self._make_section(
                    key="compiler_warnings",
                    tier=Tier.P4,
                    title="编译警告",
                    content=content,
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
    def _make_section(
        *,
        key: str,
        tier: Tier,
        title: str,
        content: str,
        status: str,
        activation_reason: str,
        sources: list[dict[str, Any]],
        can_exclude: bool = True,
        truncatable_per_item: bool = False,
        retrieval_metadata: dict[str, Any] | None = None,
    ) -> ContextSection:
        return ContextSection(
            key=key,
            tier=tier,
            content=content,
            token_count=estimate_token_count(content),
            truncatable_per_item=truncatable_per_item,
            title=title,
            preview=content[:160],
            status=status,
            activation_reason=activation_reason,
            sources=sources,
            can_exclude=can_exclude,
            retrieval_metadata=retrieval_metadata or {},
        )

    @staticmethod
    def _format_role_profile(
        characters: list,
        options: CompileOptions,
    ) -> str:
        profile_lines: list[str] = []
        for raw in characters or []:
            item = raw if isinstance(raw, dict) else getattr(raw, "__dict__", {})
            char_id = str(item.get("character_id") or item.get("entity_id") or "")
            if (
                options.viewpoint_character_id
                and char_id != options.viewpoint_character_id
            ):
                continue
            fields = [
                ("姓名", item.get("name")),
                ("角色", item.get("role")),
                ("当前目标", item.get("current_goal")),
                ("当前状态", item.get("current_state")),
                ("当前情绪", item.get("current_emotion")),
                ("立场", item.get("stance")),
                ("语气", item.get("voice_style")),
                ("行为规则", ", ".join(item.get("behavior_rules") or [])),
            ]
            profile_lines.extend(
                f"- {label}: {value}" for label, value in fields if value
            )
        return "\n".join(profile_lines) or "未找到 POV 角色档案。"

    @staticmethod
    def _format_reader_visible_world(world_entities: list) -> str:
        lines: list[str] = []
        for item in world_entities or []:
            if not isinstance(item, dict):
                continue
            text = item.get("reader_reveal_content") or item.get("public_info")
            if not text:
                continue
            name = item.get("name") or item.get("entity_id") or item.get("id")
            lines.append(f"- {name}: {text}" if name else f"- {text}")
        return "\n".join(lines)

    @staticmethod
    def _format_reader_visible_evidence(rag_chunks: list) -> str:
        lines: list[str] = []
        for item in rag_chunks or []:
            if not isinstance(item, dict):
                continue
            text = item.get("text")
            source_ref = item.get("source_ref")
            if text and isinstance(source_ref, dict):
                lines.append(f"- {text}")
        return "\n".join(lines)

    @staticmethod
    def _retrieval_activation_reason(bundle: StructureContextBundle) -> str:
        labels = {
            "current_scene": "当前 Scene",
            "structured_relation_focus": "相关人物/对象/剧情线",
            "task_intent": "任务意图",
        }
        reasons = [
            labels.get(str(item.get("reason_code")), str(item.get("reason_code")))
            for item in (bundle.retrieval_trace or {}).get("clause_summaries", [])
            if item.get("reason_code")
        ]
        reasons = list(dict.fromkeys(reason for reason in reasons if reason))
        return f"RAG 检索命中：{'、'.join(reasons)}" if reasons else "RAG 检索命中"

    @staticmethod
    def _format_role_visible_knowledge(world_entities: list) -> str:
        lines: list[str] = []
        for item in world_entities or []:
            if not isinstance(item, dict):
                continue
            name = item.get("name") or item.get("target_id") or item.get("id")
            entity_type = item.get("entity_type") or item.get("target_type")
            level = item.get("knowledge_level") or item.get("visibility_source")
            if level == "unknown":
                continue
            text = (
                item.get("misconception")
                or item.get("character_known_content")
                or item.get("content")
                or item.get("public_info")
            )
            label_parts = [str(name)]
            if entity_type:
                label_parts.append(f"类型={entity_type}")
            if level:
                label_parts.append(f"认知={level}")
            if text:
                lines.append(f"- {'; '.join(label_parts)}: {text}")
            elif name:
                lines.append(f"- {'; '.join(label_parts)}")
        return "\n".join(lines)

    @staticmethod
    def _format_role_scene_perception(
        scene: dict,
        options: CompileOptions,
    ) -> str:
        fields = [
            ("Scene", scene.get("title") or scene.get("name") or options.scene_id),
            ("章节", options.chapter_index),
            ("Scene 序号", scene.get("scene_index")),
            ("POV 角色", scene.get("pov_character_id") or options.viewpoint_character_id),
            ("地点", scene.get("location") or scene.get("location_id")),
            ("时间", scene.get("time_of_day") or scene.get("time")),
            (
                "在场对象",
                scene.get("present_character_ids") or scene.get("character_ids"),
            ),
            ("可感知氛围", scene.get("atmosphere") or scene.get("mood")),
        ]
        lines = [f"- {label}: {value}" for label, value in fields if value]
        lines.append(
            "- 角色内心、判断、台词只能使用 role_* sections 中可见的信息；"
            "Scene 导演约束不是角色已知事实。"
        )
        return "\n".join(lines)

    @staticmethod
    def _format_scene_director_constraints(scene: dict) -> str:
        lines = [
            "DIRECTOR_ONLY: 以下是作者创作约束，不是角色知识；"
            "不得把这些内容写成角色已经知道、已经判断或会主动说出的事实。"
        ]
        for label, key in (
            ("目标", "goal"),
            ("核心冲突", "core_conflict"),
            ("情绪节拍", "emotional_beat"),
            ("必须发生", "must_happen"),
            ("不得发生", "must_not_happen"),
        ):
            value = scene.get(key)
            if value:
                lines.append(f"- {label}: {value}")
        return "\n".join(lines)

    @staticmethod
    def _format_scene_time_boundary(
        bundle: StructureContextBundle,
        options: CompileOptions,
    ) -> str:
        scene_index = bundle.scene.get("scene_index") if bundle.scene else None
        return "\n".join(
            [
                f"- 当前 Scene 锚点: {options.scene_id or '未提供'}",
                f"- 当前章节: {options.chapter_index or '未提供'}",
                f"- 当前 Scene 序号: {scene_index or '未提供'}",
                "- character reveal 中 scene_id 同时表示当前 Scene、"
                "RAG 场景边界、POV 生成锚点。",
                "- 安全边界由 compiler 的 metadata/time filter 执行，不依赖提示词自律。",
            ]
        )

    @staticmethod
    def _character_safe_rag_chunks(
        rag_chunks: list,
        options: CompileOptions,
    ) -> list[dict]:
        safe_chunks: list[dict] = []
        for raw in rag_chunks or []:
            if not isinstance(raw, dict):
                continue
            if options.scene_id:
                chunk_scene_id = raw.get("scene_id")
                if chunk_scene_id != options.scene_id:
                    continue
            safe_chunks.append(raw)
        return safe_chunks

    def _format_current_scene_evidence(
        self,
        rag_chunks: list,
        options: CompileOptions,
    ) -> str:
        lines: list[str] = []
        for item in self._character_safe_rag_chunks(rag_chunks, options):
            text = item.get("text")
            if text:
                lines.append(f"- {text}")
        return "\n".join(lines)

    @staticmethod
    def _format_project_context(project: dict) -> str:
        fields = [
            ("标题", project.get("title") or project.get("name")),
            ("类型", project.get("genre")),
            ("语言", project.get("language")),
            ("风格", project.get("style") or project.get("tone")),
            ("创作阶段", project.get("current_stage")),
            ("目标规模", project.get("target_length")),
            ("默认揭示策略", project.get("default_reveal_policy")),
        ]
        return "\n".join(f"- {label}: {value}" for label, value in fields if value)

    @staticmethod
    def _format_project_style(project: dict) -> str:
        fields = [
            ("标题", project.get("title") or project.get("name")),
            ("类型", project.get("genre")),
            ("语言", project.get("language")),
            ("风格", project.get("style") or project.get("tone")),
        ]
        return "\n".join(f"- {label}: {value}" for label, value in fields if value)

    @staticmethod
    def _safe_sources_from_items(
        items,
        *,
        default_type: str,
        status: str,
    ) -> list[dict[str, Any]]:
        sources: list[dict[str, Any]] = []
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
                label = item.get("name") or item.get("title") or str(source_id)
                item_status = str(item.get("status") or status)
                source_type = str(item.get("source_type") or default_type)
                source = {
                    "type": source_type,
                    "id": str(source_id),
                    "label": str(label)[:80],
                    "status": item_status,
                }
                for field in ("chapter_index", "scene_id"):
                    if item.get(field) is not None:
                        source[field] = str(item.get(field))
                if isinstance(item.get("source_ref"), dict):
                    source["source_ref"] = dict(item["source_ref"])
                    source["source_hash"] = item["source_ref"].get("source_hash")
            else:
                source = {
                    "type": default_type,
                    "id": f"{default_type}-{index + 1}",
                    "label": f"{default_type}-{index + 1}",
                    "status": status,
                }
            sources.append(source)
        return sources

    @staticmethod
    def _sources_from_items(
        items,
        *,
        default_type: str,
        status: str,
    ) -> list[dict[str, Any]]:
        sources: list[dict[str, Any]] = []
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
            source = {
                "type": str(source_type),
                "id": str(source_id),
                "label": str(label)[:80],
                "status": item_status,
            }
            if isinstance(item, dict) and isinstance(item.get("source_ref"), dict):
                source["source_ref"] = dict(item["source_ref"])
                source["source_hash"] = item["source_ref"].get("source_hash")
            sources.append(source)
        return sources
