"""Context Compiler 核心 — 按 scope 调度 Loader"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.llm.redaction import redact_diagnostic
from infrastructure.llm.token_estimation import estimate_token_count
from modules.evidence.compilation.contracts import (
    CONTEXT_BUDGET,
    CompileOptions,
    StructureContextBundle,
)
from modules.evidence.compilation.services.compiled_context import (
    CompiledContext,
    ContextSection,
    Tier,
)
from modules.evidence.compilation.services.constraint_engine import ConstraintEngine
from modules.evidence.compilation.services.loaders import (
    CharactersLoader,
    EventsLoader,
    MemoryRecordsLoader,
    OutlineAnalysisLoader,
    OutlineArcLoader,
    PlotThreadsLoader,
    ProjectLoader,
    RagChunksLoader,
    SceneLoader,
    WorldBibleLoader,
    WorldEntitiesLoader,
)
from modules.evidence.compilation.services.protocol import Loader
from modules.memory.contracts import SCENE_MEMORY_DIMENSIONS

logger = logging.getLogger(__name__)

SCOPE_LOADERS: dict[str, list[str]] = {
    "project": ["project", "world_bible"],
    "world": ["project", "world_entities", "world_bible"],
    "world_character": ["project", "world_entities", "characters", "world_bible"],
    "generation_center": [
        "scene",
        "project",
        "world_entities",
        "characters",
        "rag_chunks",
        "plot_threads",
        "outline_arc",
        "world_bible",
    ],
    "arc": [
        "scene",
        "outline_analysis",
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
        "outline_analysis",
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
        "outline_analysis",
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
_SCENE_STATE_LABELS = {
    "entities": "人物与对象",
    "relations": "关系",
    "locations": "人物位置",
    "knowledge": "知识边界",
}


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
            OutlineAnalysisLoader(),
        ]

    async def compile(
        self,
        db: AsyncSession,
        options: CompileOptions,
    ) -> StructureContextBundle:
        """主入口：编译结构化上下文

        分两阶段加载：
        1. 先加载前置 loader（project、world_entities）
        2. 再顺序加载其余 loader（部分依赖 world_entities 的输出）

        所有 loader 共用同一 AsyncSession；SQLAlchemy 不允许并发使用
        同一 session，因此这里必须顺序执行。
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

        loader_names = list(SCOPE_LOADERS.get(options.scope, ["project"]))
        if self._uses_scene_world_state(options):
            loader_names = list(dict.fromkeys(["scene", *loader_names, "memory_records"]))
        warnings: list[str] = []

        relevance_generation = options.consumer_action in {
            "writing.generate",
            "outline.analyze",
            "world.generation.chat",
            "world.generation.convergence",
            "world.generation.core_entity",
            "world.generation.world_bible_page",
            "world.map_atlas.generate",
        }
        if relevance_generation:
            # Generation relevance is assembled before entity Top-K: Scene,
            # active threads and RAG chunks contribute stable IDs.
            prerequisite_names = [
                n
                for n in loader_names
                if n == "project" or (n == "scene" and options.scene_id is not None)
            ]
            if (
                options.consumer_action == "outline.analyze"
                and "outline_analysis" in loader_names
            ):
                # Range assets are the prerequisite for P07 relevance selection.
                # Keep this query out of the shared-session gather and make every
                # dependent loader observe the completed, author-confirmed range.
                prerequisite_names.append("outline_analysis")
            dependent_names = [
                n
                for n in loader_names
                if n
                not in {
                    *prerequisite_names,
                    "plot_threads",
                    "world_entities",
                    "characters",
                }
            ]
        else:
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
                if name == "scene" and bundle.scene:
                    scene_chapter = self._scene_chapter_index(bundle.scene)
                    if scene_chapter is not None:
                        if (
                            options.chapter_index is not None
                            and options.chapter_index != scene_chapter
                        ):
                            bundle.warnings.append(
                                "当前 Scene 章节锚点优先于请求中的参考章节"
                            )
                        options.chapter_index = scene_chapter
                        bundle.chapter_index = scene_chapter
            except Exception as exc:
                msg = f"加载 {name} 时出错: {redact_diagnostic(exc, limit=500)}"
                logger.warning(msg)
                warnings.append(msg)

        if dependent_names:
            for name in dependent_names:
                loader = self._loaders.get(name)
                if loader is None:
                    msg = f"未知的加载器: {name}"
                    logger.warning(msg)
                    warnings.append(msg)
                    continue
                try:
                    await loader.load(db, options, bundle)
                except Exception as exc:
                    msg = f"加载 {name} 时出错: {redact_diagnostic(exc, limit=500)}"
                    logger.warning(msg)
                    warnings.append(msg)

        if relevance_generation:
            if "plot_threads" in loader_names:
                loader = self._loaders.get("plot_threads")
                if loader is None:
                    msg = "未知的加载器: plot_threads"
                    logger.warning(msg)
                    warnings.append(msg)
                else:
                    try:
                        await loader.load(db, options, bundle)
                    except Exception as exc:
                        msg = (
                            "加载 plot_threads 时出错: "
                            f"{redact_diagnostic(exc, limit=500)}"
                        )
                        logger.warning(msg)
                        warnings.append(msg)
            for name in ("world_entities", "characters"):
                if name not in loader_names:
                    continue
                loader = self._loaders.get(name)
                if loader is None:
                    msg = f"未知的加载器: {name}"
                    logger.warning(msg)
                    warnings.append(msg)
                    continue
                try:
                    await loader.load(db, options, bundle)
                except Exception as exc:
                    msg = f"加载 {name} 时出错: {redact_diagnostic(exc, limit=500)}"
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
        (
            activation_section,
            activation_trace,
            activation_warnings,
        ) = await self._build_activation_section(db, bundle, options)
        if activation_section is not None:
            sections.append(activation_section)
        sections, exclusion_warnings = self._apply_section_exclusions(
            sections,
            options.excluded_asset_ids.get("context_sections", []),
        )
        warnings = [
            *bundle.warnings,
            *activation_warnings,
            *exclusion_warnings,
        ]
        total = sum(s.token_count for s in sections)
        ctx = CompiledContext(
            sections=sections,
            total_tokens=total,
            budget_tokens=budget_tokens,
            compiled_at=datetime.now(UTC).replace(tzinfo=None).isoformat(),
            warnings=warnings,
            activation_trace=activation_trace,
            selection_trace=dict(bundle.selection_trace),
        )
        compiled = ctx.enforce_budget()
        if activation_trace:
            self._apply_global_activation_budget_trace(compiled)
        return compiled

    @staticmethod
    def _scene_chapter_index(scene: object) -> int | None:
        """Resolve the latest real chapter covered by the current Scene."""
        if not isinstance(scene, dict):
            return None
        direct = scene.get("chapter_index")
        if str(direct or "").isdigit():
            return int(direct)
        indices: list[int] = []
        for chunk in scene.get("scene_chunks") or []:
            if not isinstance(chunk, dict):
                continue
            value = chunk.get("chapter_index")
            if str(value or "").isdigit():
                indices.append(int(value))
        if not indices:
            for value in scene.get("chapter_ids") or []:
                if str(value or "").isdigit():
                    indices.append(int(value))
        return max(indices) if indices else None

    async def _build_activation_section(
        self,
        db: AsyncSession,
        bundle: StructureContextBundle,
        options: CompileOptions,
    ) -> tuple[ContextSection | None, dict[str, Any], list[str]]:
        if not options.activation_profile_id:
            return None, {}, []
        if not options.consumer_action:
            return None, {}, ["activation_profile_requires_consumer_action"]

        from modules.evidence.compilation.schemas import ContextActivationPreviewRequest
        from modules.evidence.compilation.services.activation_profile_service import (
            ActivationProfileService,
        )

        scene = bundle.scene or {}
        current_scene_text = "\n".join(
            str(scene.get(key) or "")
            for key in ("title", "summary", "content", "scene_text")
        )
        request = ContextActivationPreviewRequest(
            novel_id=options.novel_id,
            action=options.consumer_action,
            profile_id=options.activation_profile_id,
            profile_version=options.activation_profile_version,
            reveal_mode=options.reveal_mode,
            task_text=options.task,
            current_scene_text=current_scene_text[:50000],
            explicit_focus=" ".join(
                value
                for value in (
                    options.focus_entity_id,
                    " ".join(options.entity_ids or []),
                )
                if value
            ),
            scene_id=options.scene_id,
            entity_ids=options.entity_ids or [],
            focus_entity_id=options.focus_entity_id,
            top_k=min(max(options.top_k, 1), 256),
            depth=2,
        )
        trace = await ActivationProfileService().preview_published(db, request)
        profile = trace.get("profile")
        warnings = list(trace.get("warnings") or [])
        if not profile:
            return None, trace, warnings
        options.activation_profile_version = int(profile["version"])
        options.activation_profile_rule_hash = str(profile["rule_hash"])
        options.activation_source_hashes = list(
            dict.fromkeys(
                str(item.get("source_hash") or "")
                for item in trace.get("items") or []
                if item.get("source_hash")
            )
        )
        options.activation_included_target_hashes = [
            str(item["target_hash"])
            for item in trace.get("items") or []
            if item.get("target_hash")
        ]
        if not trace.get("items"):
            return None, trace, warnings
        data_items = [
            {
                "label": item.get("label"),
                "target": item.get("target"),
                "source_hash": item.get("source_hash"),
                "content": item.get("content"),
            }
            for item in trace["items"]
        ]
        serialized_items = (
            json.dumps(
                data_items,
                ensure_ascii=False,
                separators=(",", ":"),
            )
            .replace("<", "\\u003c")
            .replace(">", "\\u003e")
        )
        content = (
            "<WORLD_BIBLE_ACTIVATION_DATA>\n"
            + serialized_items
            + "\n</WORLD_BIBLE_ACTIVATION_DATA>"
        )
        section = ContextSection(
            key="world_bible_activation",
            tier=Tier.P1,
            content=content,
            token_count=estimate_token_count(content),
            title="AI 参考规则命中的世界资料",
            preview="；".join(str(item.get("label") or "") for item in trace["items"])[
                :160
            ],
            status="canonical",
            activation_reason=(
                f"Activation Profile {profile['profile_key']} v{profile['version']}"
            ),
            sources=[
                {
                    "type": str(item["target"].get("target_type") or "world"),
                    "id": str(item["target"].get("target_id") or ""),
                    "label": str(item.get("label") or ""),
                    "status": str(item.get("status") or "canonical"),
                    "source_hash": str(item.get("source_hash") or ""),
                }
                for item in trace["items"]
            ],
            can_exclude=True,
            retrieval_metadata={
                "profile": profile,
                "rule_evaluations": trace.get("rule_evaluations") or [],
                "activation_budget_events": trace.get("budget_events") or [],
                "included_target_hashes": options.activation_included_target_hashes,
                "source_hashes": options.activation_source_hashes,
            },
        )
        return section, trace, warnings

    @staticmethod
    def _apply_global_activation_budget_trace(compiled: CompiledContext) -> None:
        trace = compiled.activation_trace
        if not trace:
            return
        if "world_bible_activation" in compiled.evicted_keys:
            for item in trace.get("items") or []:
                item["decision"] = "excluded"
                item["excluded_reason"] = "global_budget_evicted"
                item["token_after"] = 0
            trace.setdefault("budget_events", []).append(
                {
                    "section_key": "world_bible_activation",
                    "event_type": "evicted",
                    "reason": "global_budget_evicted",
                }
            )
        elif "world_bible_activation" in compiled.truncated_keys:
            for item in trace.get("items") or []:
                item["excluded_reason"] = "global_budget_truncated"
            trace.setdefault("budget_events", []).append(
                {
                    "section_key": "world_bible_activation",
                    "event_type": "truncated",
                    "reason": "global_budget_truncated",
                }
            )

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

        if bundle.outline_analysis and (
            options is None or options.reveal_mode in {"author_safe", "author_full"}
        ):
            sections.extend(self._build_outline_analysis_sections(bundle, options))

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

        if bundle.world_entities:
            content = "\n".join(str(item) for item in bundle.world_entities)
            sections.append(
                ContextSection(
                    key="world_entities",
                    tier=Tier.P2,
                    content=content,
                    token_count=estimate_token_count(content),
                    truncatable_per_item=True,
                    max_items=(
                        160
                        if options
                        and options.consumer_action == "world.map_atlas.generate"
                        else 16
                    ),
                    title="相关世界对象",
                    preview=content[:160],
                    status=options.context_mode if options else "canonical",
                    activation_reason="作者显式选择及 Scene、剧情线、检索证据关联",
                    sources=self._sources_from_items(
                        bundle.world_entities,
                        default_type="world_entity",
                        status=options.context_mode if options else "canonical",
                    ),
                )
            )

        if bundle.memory_records:
            content = self._format_memory_records(bundle.memory_records)
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

        if bundle.plot_threads and not bundle.outline_analysis:
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
            rag_sources = self._sources_from_items(
                bundle.rag_chunks,
                default_type="rag",
                status=options.context_mode if options else "canonical",
            )
            if options and options.consumer_action == "world.map_atlas.generate":
                for source in rag_sources:
                    source["type"] = "rag"
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
                    sources=rag_sources,
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

        if options is not None and options.consumer_action in {
            "world.generation.chat",
            "world.generation.convergence",
            "world.generation.core_entity",
            "world.generation.world_bible_page",
            "world.map_atlas.generate",
        }:
            generation_order = {
                "writing_objective": 0,
                "world_bible_working_pages": 1,
                "scene_blueprint": 2,
                "open_narrative_obligations": 3,
                "retrieval_evidence_packs": 4,
                "pov_knowledge": 5,
                "world_entities": 6,
                "style_assets": 7,
                "world_bible_synopsis": 8,
                "compiler_warnings": 9,
            }
            sections.sort(key=lambda item: generation_order.get(item.key, 7))
        return sections

    @staticmethod
    def _build_outline_analysis_sections(
        bundle: StructureContextBundle,
        options: CompileOptions | None,
    ) -> list[ContextSection]:
        analysis = bundle.outline_analysis or {}
        start_chapter = analysis.get("start_chapter")
        end_chapter = analysis.get("end_chapter")
        status = options.context_mode if options else "canonical"
        sections = []
        counts = {
            "scenes": len(analysis.get("scenes") or []),
            "arcs": len(analysis.get("arcs") or []),
            "plot_threads": len(analysis.get("plot_threads") or []),
            "foreshadowing_plans": len(analysis.get("foreshadowing_plans") or []),
            "reveal_plans": len(analysis.get("reveal_plans") or []),
        }
        overview = json.dumps(
            {
                "start_chapter": start_chapter,
                "end_chapter": end_chapter,
                "asset_counts": counts,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        sections.append(
            ContextSection(
                key="outline_analysis_range",
                tier=Tier.P0,
                content=overview,
                token_count=estimate_token_count(overview),
                title="大纲分析范围",
                preview=(
                    f"章节 {start_chapter}-{end_chapter} · {counts['scenes']} 个 Scene"
                ),
                status="system",
                activation_reason="作者本次确认的分析章节范围",
                sources=[
                    {
                        "type": "chapter_range",
                        "id": f"{start_chapter}-{end_chapter}",
                        "label": f"章节 {start_chapter}-{end_chapter}",
                        "status": "system",
                    }
                ],
                can_exclude=False,
            )
        )
        specs = (
            (
                "outline_analysis_scenes",
                "scenes",
                "范围内 Scene（按叙事顺序）",
                "scene",
                Tier.P1,
                False,
            ),
            (
                "outline_analysis_threads",
                "plot_threads",
                "相关剧情线",
                "plot_thread",
                Tier.P2,
                True,
            ),
            (
                "outline_analysis_arcs",
                "arcs",
                "相关篇章纲",
                "outline_arc",
                Tier.P2,
                True,
            ),
            (
                "outline_analysis_foreshadowing",
                "foreshadowing_plans",
                "相关伏笔计划",
                "foreshadowing_plan",
                Tier.P2,
                True,
            ),
            (
                "outline_analysis_reveals",
                "reveal_plans",
                "相关揭示计划",
                "reveal_plan",
                Tier.P2,
                True,
            ),
        )
        for key, data_key, title, source_type, tier, can_exclude in specs:
            items = [
                item for item in analysis.get(data_key) or [] if isinstance(item, dict)
            ]
            if not items:
                continue
            content = "\n".join(
                json.dumps(item, ensure_ascii=False, sort_keys=True) for item in items
            )
            sections.append(
                ContextSection(
                    key=key,
                    tier=tier,
                    content=content,
                    token_count=estimate_token_count(content),
                    truncatable_per_item=True,
                    title=title,
                    preview=content[:160],
                    status=status,
                    activation_reason=(
                        f"与章节 {start_chapter}-{end_chapter} 的结构范围重叠"
                    ),
                    sources=[
                        {
                            "type": source_type,
                            "id": str(item.get("id") or ""),
                            "label": str(
                                item.get("title")
                                or item.get("name")
                                or item.get("secret_summary")
                                or item.get("id")
                                or title
                            ),
                            "status": str(item.get("status") or status),
                        }
                        for item in items
                    ],
                    can_exclude=can_exclude,
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

            observed_characters = self._other_characters(
                bundle.characters,
                options,
            )
            if observed_characters:
                sections.append(
                    self._make_section(
                        key="role_observed_characters",
                        tier=Tier.P1,
                        title="POV 可观察的相关人物",
                        content=self._format_role_observed_characters(
                            observed_characters
                        ),
                        status=status,
                        activation_reason=("当前 Scene、篇章、剧情线或证据关联的人物"),
                        sources=self._safe_sources_from_items(
                            observed_characters,
                            default_type="character",
                            status=status,
                        ),
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

        if bundle.scene_checkpoint_set is not None:
            sections.append(self._build_scene_world_state_section(bundle, options))

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

        safe_plotlines = self._format_safe_plotline_context(
            bundle.plot_threads,
            bundle.scene,
        )
        if safe_plotlines:
            sections.append(
                self._make_section(
                    key="safe_plotline_context",
                    tier=Tier.P1,
                    title="当前剧情线导演摘要",
                    content=safe_plotlines,
                    status="director_only",
                    activation_reason="当前章活跃剧情线的公开进展与 Scene 作用",
                    sources=self._safe_sources_from_items(
                        bundle.plot_threads,
                        default_type="plot_thread",
                        status="director_only",
                    ),
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
    def _uses_scene_world_state(options: CompileOptions) -> bool:
        return bool(
            options.consumer_action == "writing.generate"
            and options.scene_id
            and options.reveal_mode == "character"
        )

    @classmethod
    def _build_scene_world_state_section(
        cls,
        bundle: StructureContextBundle,
        options: CompileOptions,
    ) -> ContextSection:
        checkpoint_set = bundle.scene_checkpoint_set or {}
        items = {
            str(item.get("dimension")): item
            for item in checkpoint_set.get("items") or []
            if isinstance(item, dict) and item.get("dimension")
        }
        related_labels = cls._scene_state_related_labels(bundle, options)
        trusted: dict[str, dict[str, Any]] = {}
        dimensions: list[dict[str, Any]] = []
        checkpoint_versions: list[dict[str, str]] = []
        sources: list[dict[str, Any]] = []
        missing_status = (
            "unavailable"
            if checkpoint_set.get("coverage_status") == "unavailable"
            else "missing"
        )

        for dimension in SCENE_MEMORY_DIMENSIONS:
            item = items.get(dimension) or {}
            status = str(item.get("status") or missing_status)
            is_trusted = status == "ready" and (
                item.get("source") == "system_generated" or item.get("confirmed") is True
            )
            if is_trusted:
                trusted[dimension] = item
                sources.append(
                    {
                        "type": "memory_scene_checkpoint",
                        "id": str(item.get("id") or f"{options.scene_id}:{dimension}"),
                        "label": _SCENE_STATE_LABELS[dimension],
                        "status": "director_only",
                    }
                )
            checkpoint_versions.append(
                {
                    "dimension": dimension,
                    "id": str(item.get("id") or ""),
                    "status": status,
                }
            )
            dimensions.append(
                {
                    "label": _SCENE_STATE_LABELS[dimension],
                    "state_label": cls._scene_state_status_label(status, is_trusted),
                    "summary": str(
                        item.get("display_summary")
                        or item.get("gap_reason")
                        or "尚无可用记录"
                    ),
                    "evidence_count": len(item.get("evidence_refs") or []),
                }
            )

        entity_state = (
            trusted.get("entities", {}).get("state_json", {}).get("entities") or {}
        )
        entity_state_ids = {cls._id_key(entity_id) for entity_id in entity_state}
        historical_labels = {
            cls._id_key(entity_id): str(payload.get("name"))
            for entity_id, payload in entity_state.items()
            if isinstance(payload, dict) and payload.get("name")
        }
        lines = [
            "DIRECTOR_ONLY: 以下只是当前 Scene 时点可追溯的环境事实，"
            "不代表 POV 人物知道或相信它们。",
            "人物的判断、内心与台词只能使用角色可见知识；"
            "未覆盖项不表示当时不存在，不得用当前世界资料回填。",
        ]
        fact_lines = cls._scene_state_fact_lines(
            trusted,
            related_labels,
            historical_labels,
        )
        lines.extend(fact_lines or ["- 本次没有可交给模型的相关 Scene 时点事实。"])

        manual_entities = trusted.get("entities") or {}
        entity_absence_confirmed = bool(
            manual_entities.get("source") == "manual"
            and manual_entities.get("confirmed") is True
            and manual_entities.get("display_summary") == "已人工确认此阶段没有该维度事实"
        )
        omissions = []
        if not entity_absence_confirmed:
            omissions = [
                {"label": label, "reason": "尚无时间锚"}
                for entity_id, label in related_labels.items()
                if entity_id not in entity_state_ids
            ]

        coverage_status = str(checkpoint_set.get("coverage_status") or "missing")
        if omissions:
            coverage_label = "有些相关对象尚无时间锚"
        elif coverage_status == "ready":
            coverage_label = "当时状态已有可追溯证据"
        elif coverage_status == "retry_pending":
            coverage_label = "部分状态正在重建"
        elif coverage_status == "manual_required":
            coverage_label = "部分状态需要作者判断"
        else:
            coverage_label = "Scene 时点证据不完整"

        content = "\n".join(lines)
        return cls._make_section(
            key="scene_world_state",
            tier=Tier.P0,
            title="Scene 时点可证状态",
            content=content,
            status="director_only",
            activation_reason="当前 Scene 四维 checkpoint 与相关对象对照",
            sources=sources,
            can_exclude=False,
            retrieval_metadata={
                "coverage_label": coverage_label,
                "dimensions": dimensions,
                "omissions": omissions,
                "checkpoint_versions": checkpoint_versions,
                "current_canon_note": (
                    "当前正典只作为作者修复参考，不会回填这个 Scene 的过去状态。"
                ),
            },
        )

    @staticmethod
    def _scene_state_status_label(status: str, trusted: bool) -> str:
        if trusted:
            return "当时可证"
        return {
            "retry_pending": "正在重建",
            "manual_required": "需要判断",
            "gap": "证据不完整",
            "unavailable": "证据不完整",
        }.get(status, "尚无时间锚")

    @classmethod
    def _scene_state_related_labels(
        cls,
        bundle: StructureContextBundle,
        options: CompileOptions,
    ) -> dict[str, str]:
        labels: dict[str, str] = {}

        def add(value: Any, label: Any = None) -> None:
            normalized = cls._id_key(value)
            if not normalized:
                return
            current = str(label or "").strip()
            labels.setdefault(normalized, current)
            if current:
                labels[normalized] = current

        for item in [*bundle.characters, *bundle.world_entities]:
            if not isinstance(item, dict):
                continue
            add(
                item.get("character_id") or item.get("entity_id") or item.get("id"),
                item.get("name") or item.get("title"),
            )
        for value in [
            options.viewpoint_character_id,
            *(options.character_ids or []),
            *(options.entity_ids or []),
            *(options.location_ids or []),
        ]:
            add(value)
        scene = bundle.scene or {}
        add(scene.get("pov_character_id"))
        structure_meta = scene.get("structure_meta") or {}
        for key in (
            "related_character_ids",
            "present_character_ids",
            "character_ids",
            "related_entity_ids",
            "world_entity_ids",
            "item_ids",
            "related_location_ids",
        ):
            for value in structure_meta.get(key) or []:
                add(value)
        for key in ("location_id", "location_entity_id"):
            add(structure_meta.get(key) or scene.get(key))

        unnamed = 0
        for entity_id, label in list(labels.items()):
            if label:
                continue
            unnamed += 1
            labels[entity_id] = f"已选对象 {unnamed}"
        return labels

    @classmethod
    def _scene_state_fact_lines(
        cls,
        trusted: dict[str, dict[str, Any]],
        related_labels: dict[str, str],
        historical_labels: dict[str, str],
    ) -> list[str]:
        lines: list[str] = []
        related_ids = set(related_labels)
        entity_state = trusted.get("entities", {}).get("state_json", {})
        for entity_id, payload in sorted((entity_state.get("entities") or {}).items()):
            if cls._id_key(entity_id) not in related_ids or not isinstance(payload, dict):
                continue
            label = str(payload.get("name") or "相关人物或对象")
            details = cls._scene_state_details(
                payload,
                (
                    "summary",
                    "public_info",
                    "current_state",
                    "state",
                    "condition",
                    "description",
                ),
            )
            lines.append(f"- 人物与对象｜{label}: {details or '该时点已有明确事件锚'}")

        relation_state = trusted.get("relations", {}).get("state_json", {})
        for payload in relation_state.get("relations") or []:
            if not isinstance(payload, dict):
                continue
            source_id = cls._id_key(payload.get("source_id"))
            target_id = cls._id_key(payload.get("target_id"))
            if not ({source_id, target_id} & related_ids):
                continue
            endpoints = [
                payload.get("source_name") or historical_labels.get(source_id),
                payload.get("target_name") or historical_labels.get(target_id),
            ]
            label = " → ".join(str(value) for value in endpoints if value) or "相关关系"
            details = cls._scene_state_details(
                payload,
                ("relation_type", "description", "current_state", "state"),
            )
            lines.append(f"- 关系｜{label}: {details or '该时点已有明确关系锚'}")

        location_state = trusted.get("locations", {}).get("state_json", {})
        for character_id, payload in sorted(
            (location_state.get("character_locations") or {}).items()
        ):
            if cls._id_key(character_id) not in related_ids or not isinstance(
                payload, dict
            ):
                continue
            label = historical_labels.get(cls._id_key(character_id)) or "相关人物"
            location_id = cls._id_key(payload.get("location_id"))
            details = cls._scene_state_details(
                payload,
                ("text_state", "location_name", "state", "description"),
            ) or historical_labels.get(location_id)
            if details:
                lines.append(f"- 人物位置｜{label}: {details}")

        for dimension in ("entities", "relations", "locations"):
            item = trusted.get(dimension) or {}
            state = item.get("state_json") or {}
            if item.get("source") == "manual" and item.get("confirmed") is True:
                summary = (
                    cls._scene_state_details(state, ("manual_summary",))
                    or str(item.get("display_summary") or "")[:1200]
                )
                if summary:
                    lines.append(
                        f"- {_SCENE_STATE_LABELS[dimension]}｜作者确认: {summary}"
                    )
        return list(dict.fromkeys(lines))[:16]

    @staticmethod
    def _scene_state_details(payload: Any, fields: tuple[str, ...]) -> str:
        if not isinstance(payload, dict):
            return ""
        values: list[str] = []
        for field in fields:
            value = payload.get(field)
            if not isinstance(value, str | int | float | bool) or value in (None, ""):
                continue
            text = str(value).strip()
            if text and text not in values:
                values.append(text)
        return "；".join(values)[:1200]

    @staticmethod
    def _id_key(value: object) -> str:
        text = str(value or "").strip()
        try:
            return uuid.UUID(text).hex
        except ValueError:
            return text

    @staticmethod
    def _format_memory_records(records: list) -> str:
        lines: list[str] = []
        for item in records:
            if not isinstance(item, dict):
                continue
            kind = str(item.get("memory_type") or "记忆")
            title = str(item.get("title") or item.get("name") or "").strip()
            summary = str(item.get("summary") or item.get("event") or "").strip()
            chapter = item.get("chapter_index")
            prefix = f"- [{kind}]"
            if chapter is not None:
                prefix += f" 第 {chapter} 章"
            detail = " — ".join(value for value in (title, summary) if value)
            lines.append(f"{prefix}: {detail}" if detail else prefix)
        return "\n".join(lines)

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
            char_id = ContextCompiler._id_key(
                item.get("character_id") or item.get("entity_id") or ""
            )
            if options.viewpoint_character_id and char_id != ContextCompiler._id_key(
                options.viewpoint_character_id
            ):
                continue
            fields = [
                ("姓名", item.get("name")),
                ("角色", item.get("role")),
                ("外观", item.get("appearance")),
                ("性格", item.get("personality")),
                ("渴望", item.get("desire")),
                ("恐惧", item.get("fear")),
                ("弱点", item.get("weakness")),
                ("当前目标", item.get("current_goal")),
                ("当前状态", item.get("current_state")),
                ("当前情绪", item.get("current_emotion")),
                ("立场", item.get("stance")),
                ("语气", item.get("voice_style")),
                (
                    "行为规则",
                    ContextCompiler._format_character_behavior_rules(
                        item.get("behavior_rules")
                    ),
                ),
            ]
            profile_lines.extend(
                f"- {label}: {value}" for label, value in fields if value
            )
        return "\n".join(profile_lines) or "未找到 POV 角色档案。"

    @staticmethod
    def _other_characters(
        characters: list,
        options: CompileOptions,
    ) -> list[dict]:
        result: list[dict] = []
        for raw in characters or []:
            item = raw if isinstance(raw, dict) else getattr(raw, "__dict__", {})
            char_id = ContextCompiler._id_key(
                item.get("character_id") or item.get("entity_id") or ""
            )
            if options.viewpoint_character_id and char_id == ContextCompiler._id_key(
                options.viewpoint_character_id
            ):
                continue
            result.append(item)
        return result

    @staticmethod
    def _format_role_observed_characters(characters: list[dict]) -> str:
        lines = [
            "以下姓名仅供模型指代人物，不代表 POV 角色知道其姓名；"
            "其余仅是可观察的外在表现，不代表 POV 知道对方的身份、"
            "真实动机或内心。"
        ]
        for item in characters:
            name = item.get("name") or "未命名人物"
            observable_fields = [
                ("外观", item.get("appearance")),
                ("语言风格", item.get("voice_style")),
            ]
            details = "；".join(
                f"{label}={value}" for label, value in observable_fields if value
            )
            lines.append(f"- {name}: {details}" if details else f"- {name}")
        return "\n".join(lines)

    @staticmethod
    def _format_character_behavior_rules(value: Any) -> str:
        if not value:
            return ""
        if not isinstance(value, list):
            return str(value)
        rendered: list[str] = []
        for item in value:
            if isinstance(item, dict):
                text = item.get("rule") or item.get("description") or item.get("content")
                if text:
                    rendered.append(str(text))
            elif item:
                rendered.append(str(item))
        return "、".join(rendered)

    @staticmethod
    def _format_safe_plotline_context(
        plot_threads: list,
        scene: dict | None,
    ) -> str:
        if not plot_threads:
            return ""
        lines = [
            "DIRECTOR_ONLY: 以下只用于理解当前 Scene 在剧情线中的作用，"
            "不是 POV 角色已知事实。"
        ]
        narrative_tag = scene.get("narrative_tag") if scene else None
        if narrative_tag:
            lines.append(f"- 当前 Scene 叙事标签: {narrative_tag}")
        for raw in plot_threads:
            item = raw if isinstance(raw, dict) else getattr(raw, "__dict__", {})
            name = item.get("name") or item.get("id") or "未命名剧情线"
            public_fields = [
                ("公开目标", item.get("visible_goal")),
                ("当前进展", item.get("current_stage")),
            ]
            details = "；".join(
                f"{label}={value}" for label, value in public_fields if value
            )
            lines.append(f"- {name}: {details}" if details else f"- {name}")
        return "\n".join(lines)

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
        level_labels = {
            "rumor": "听说过",
            "partial": "知道一部分",
            "full": "清楚知道",
            "false_belief": "相信错误版本",
            "restricted": "只知道这段",
            "misunderstood": "理解偏了",
            "public_info": "公开信息",
        }
        type_labels = {
            "entity": "世界对象",
            "character": "人物",
            "event": "事件",
            "location": "地点",
            "item": "物品",
            "faction": "势力",
        }
        lines: list[str] = []
        for item in world_entities or []:
            if not isinstance(item, dict):
                continue
            name = item.get("name") or "未命名对象"
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
                label_parts.append(
                    f"类型={type_labels.get(str(entity_type), '世界对象')}"
                )
            if level:
                label_parts.append(f"认知={level_labels.get(str(level), str(level))}")
            learned = item.get("knowledge_source_chapter_index")
            if learned is not None:
                label_parts.append(f"第{learned}章后生效")
            elif item.get("knowledge_is_public_baseline"):
                label_parts.append("开场已知")
            elif item.get("visibility_source") == "public_info":
                label_parts.append("公开基线")
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
        present = scene.get("present_character_ids") or scene.get("character_ids")
        present_summary = (
            f"{len(present)} 位在场人物"
            if isinstance(present, list | tuple | set) and present
            else None
        )
        fields = [
            ("Scene", scene.get("title") or scene.get("name") or "当前 Scene"),
            ("章节", options.chapter_index),
            ("Scene 序号", scene.get("scene_index")),
            (
                "POV 角色",
                "见 POV 角色档案"
                if scene.get("pov_character_id") or options.viewpoint_character_id
                else None,
            ),
            (
                "地点",
                scene.get("location")
                or ("已选择地点" if scene.get("location_id") else None),
            ),
            ("时间", scene.get("time_of_day") or scene.get("time")),
            ("在场对象", present_summary),
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
        from modules.outline.contracts import scene_semantic_field_status

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
            status = scene_semantic_field_status(scene, key)
            if status == "not_applicable":
                continue
            if status == "uncertain":
                if value:
                    lines.append(f"- 待复核{label}: {value}（不得作为硬约束）")
                continue
            if value:
                lines.append(f"- {label}: {value}")
        return "\n".join(lines)

    @staticmethod
    def _format_scene_time_boundary(
        bundle: StructureContextBundle,
        options: CompileOptions,
    ) -> str:
        scene_index = bundle.scene.get("scene_index") if bundle.scene else None
        chapter_label = (
            options.chapter_index if options.chapter_index is not None else "未提供"
        )
        scene_index_label = scene_index if scene_index is not None else "未提供"
        return "\n".join(
            [
                f"- 当前 Scene 锚点: {'已固定' if options.scene_id else '未提供'}",
                f"- 当前章节: {chapter_label}",
                f"- 当前 Scene 序号: {scene_index_label}",
                "- 角色视角、正文证据与生成位置都以这个 Scene 为边界。",
                "- 可见边界由系统确定性校验，不依赖提示词自律。",
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
            if isinstance(item, dict):
                summary = item.get("summary") or item.get("text") or item.get("free_text")
                if summary:
                    source["summary"] = str(summary)[:1000]
                for field in ("chapter_index", "scene_id"):
                    if item.get(field) is not None:
                        source[field] = str(item[field])
            if isinstance(item, dict) and isinstance(item.get("source_ref"), dict):
                source["source_ref"] = dict(item["source_ref"])
                source["source_hash"] = item["source_ref"].get("source_hash")
            sources.append(source)
        return sources
