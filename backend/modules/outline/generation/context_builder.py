"""剧情结构生成器的上下文构建模块。

负责从 context.facade 和 writing.facade 加载数据，组装为 LLM 可用的
Markdown 上下文，并输出名称→ID 映射表供后续解析使用。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from modules.context import facade as context_facade
from modules.outline.generation.context_renderer import (
    _CHAPTER_TEXT_LIMIT,
    _PromptTextGuard,
    render_bundle_to_markdown,
    render_chapter_text_sections,
    render_scene_summary_card,
    render_scene_summary_line,
    render_warnings_to_markdown,
)
from modules.writing import facade as writing_facade


@dataclass
class PlotStructureContext:
    """生成剧情结构所需的上下文。"""

    markdown: str
    """注入 prompt 的 Markdown 文本。"""

    warnings: list[str] = field(default_factory=list)
    """构建上下文时产生的警告。"""

    entity_name_to_id: dict[str, str] = field(default_factory=dict)
    """世界对象名称 → entity_id (UUID hex)。"""

    character_name_to_id: dict[str, str] = field(default_factory=dict)
    """人物名称 → character_id (UUID hex)。"""

    scenes: list[dict] = field(default_factory=list)
    """已生成 Scene 卡片，供 deep-import fast path 使用。"""


class SceneSummaryText(str):
    """Backward-compatible scene summary text that can also unpack cards."""

    cards: list[dict]

    def __new__(cls, markdown: str, cards: list[dict]):
        value = str.__new__(cls, markdown)
        value.cards = cards
        return value

    def __iter__(self):
        yield str(self)
        yield self.cards


class PlotStructureContextBuilder:
    """构建 PlotStructureGenerator 所需的上下文。"""

    async def build(
        self,
        db: AsyncSession,
        novel_id: str,
        start_chapter: int,
        end_chapter: int,
        *,
        context_mode: str = "canonical",
        include_pending_objects: bool = False,
        include_chapter_texts: bool = True,
        include_existing_scenes: bool = False,
    ) -> PlotStructureContext:
        """加载并组装上下文。

        Args:
            db: 数据库 session
            novel_id: 项目 ID（UUID hex 字符串）
            start_chapter: 起始章节索引
            end_chapter: 结束章节索引

        Returns:
            PlotStructureContext: 包含 markdown 与名称映射的上下文对象
        """
        bundle = await context_facade.compile_structure_context(
            db=db,
            novel_id=novel_id,
            task="生成剧情结构",
            scope="full",
            chapter_index=start_chapter,
            visible_until_chapter=end_chapter,
            reveal_mode="author_only",
            context_mode=context_mode,
            include_pending_objects=include_pending_objects,
        )

        warnings = list(bundle.warnings or [])
        guard = _PromptTextGuard(warnings=warnings)
        context_md = self._render_bundle_to_markdown(bundle, guard=guard)
        world_background_md = await self._load_world_background(
            db,
            novel_id,
            context_mode=context_mode,
            budget_tokens=1800,
        )
        if world_background_md:
            context_md += "\n" + world_background_md

        entity_name_to_id = {
            e["name"]: e["entity_id"]
            for e in (bundle.world_entities or [])
            if e.get("entity_id") and e.get("name")
        }
        character_name_to_id = {
            ch["name"]: ch["character_id"]
            for ch in (bundle.characters or [])
            if ch.get("character_id") and ch.get("name")
        }

        scene_cards: list[dict] = []
        if include_existing_scenes:
            scenes_md, scene_cards = await self._load_scene_summaries(
                db,
                novel_id,
                start_chapter,
                end_chapter,
                guard=guard,
            )
            if scenes_md:
                context_md += "\n## 已生成 Scene 摘要\n" + scenes_md

        chapter_texts = (
            await self._load_chapter_texts(db, novel_id, start_chapter, end_chapter)
            if include_chapter_texts
            else []
        )
        if chapter_texts:
            context_md += render_chapter_text_sections(chapter_texts, guard=guard)

        generated_warnings = [
            warning for warning in warnings if warning not in (bundle.warnings or [])
        ]
        if generated_warnings:
            context_md += self._render_warnings_to_markdown(
                "动态文本安全警告",
                generated_warnings,
                guard,
            )

        return PlotStructureContext(
            markdown=context_md,
            warnings=warnings,
            entity_name_to_id=entity_name_to_id,
            character_name_to_id=character_name_to_id,
            scenes=scene_cards,
        )

    async def _load_world_background(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        context_mode: str,
        budget_tokens: int,
    ) -> str:
        """Append derived world background without reading novel body text."""
        from infrastructure.llm.token_estimation import estimate_token_count
        from modules.world.facade import get_world_background

        background = await get_world_background(
            db,
            novel_id,
            context_mode=context_mode,
        )
        lines: list[str] = []
        used = 0
        seen_groups: set[str] = set()
        for entry in background.entries:
            if entry.group in seen_groups:
                continue
            line = f"- {entry.title}: {entry.summary}"
            tokens = estimate_token_count(line)
            if used + tokens > budget_tokens:
                continue
            lines.append(line)
            seen_groups.add(entry.group)
            used += tokens
        return "## 世界背景聚合\n" + "\n".join(lines) if lines else ""

    def _render_bundle_to_markdown(
        self,
        bundle: object,
        *,
        guard: _PromptTextGuard | None = None,
    ) -> str:
        """将 StructureContextBundle 渲染为 Markdown 片段。"""
        return render_bundle_to_markdown(bundle, guard=guard)

    def _render_warnings_to_markdown(
        self,
        title: str,
        warnings: list[str],
        guard: _PromptTextGuard,
    ) -> str:
        return render_warnings_to_markdown(title, warnings, guard)

    async def _load_scene_summaries(
        self,
        db: AsyncSession,
        novel_id: str,
        start_chapter: int,
        end_chapter: int,
        *,
        guard: _PromptTextGuard | None = None,
    ) -> SceneSummaryText:
        """加载指定章节范围内已有 Scene 的紧凑摘要。"""
        from modules.outline.services import SceneService

        guard = guard or _PromptTextGuard(warnings=[])
        scenes = await SceneService().get_by_chapter_range_models(
            db,
            novel_id,
            start_chapter,
            end_chapter,
        )
        lines: list[str] = []
        cards: list[dict] = []
        for scene in scenes:
            if scene.status == "deprecated":
                continue
            chapter_indices = self._scene_chapter_indices(scene)
            lines.append(render_scene_summary_line(scene, chapter_indices, guard=guard))
            cards.append(render_scene_summary_card(scene, chapter_indices))
        return SceneSummaryText("\n".join(lines) + ("\n" if lines else ""), cards)

    @staticmethod
    def _scene_chapter_indices(scene: object) -> list[int]:
        indices: set[int] = set()
        for chapter_id in getattr(scene, "chapter_ids", []) or []:
            try:
                indices.add(int(chapter_id))
            except (TypeError, ValueError):
                continue
        for chunk in getattr(scene, "scene_chunks", []) or []:
            if not isinstance(chunk, dict):
                continue
            try:
                indices.add(int(chunk.get("chapter_index")))
            except (TypeError, ValueError):
                continue
        return sorted(indices)

    async def _load_chapter_texts(
        self,
        db: AsyncSession,
        novel_id: str,
        start_chapter: int,
        end_chapter: int,
    ) -> list[tuple[int, str]]:
        """加载指定章节范围的最新正文草稿内容。

        通过 writing.facade 读取，不直接访问 writing 模块的 model/repository。
        """
        chapter_indices = list(range(start_chapter, end_chapter + 1))
        drafts = await writing_facade.list_latest_drafts_for_chapters(
            db,
            novel_id,
            chapter_indices,
            content_limit=_CHAPTER_TEXT_LIMIT + 1,
        )
        draft_by_chapter = {draft.chapter_index: draft for draft in drafts}
        results: list[tuple[int, str]] = []
        for chapter_index in chapter_indices:
            draft = draft_by_chapter.get(chapter_index)
            if draft is not None and draft.content:
                results.append((chapter_index, draft.content))
        return results
