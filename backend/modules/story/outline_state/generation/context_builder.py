"""剧情结构生成器的上下文构建模块。

负责从 context.facade 和 writing.facade 加载数据，组装为 LLM 可用的
Markdown 上下文，并输出名称→ID 映射表供后续解析使用。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from modules.evidence import facade as context_facade
from modules.story.outline_state.generation.context_renderer import (
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
            retrieval_purpose="outline_generation",
            consumer_action="outline.generate",
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
                context_mode=context_mode,
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
        context_mode: str = "canonical",
        guard: _PromptTextGuard | None = None,
    ) -> SceneSummaryText:
        """加载指定章节范围内已有 Scene 的紧凑摘要。"""
        from modules.story.outline_state.services import SceneService

        guard = guard or _PromptTextGuard(warnings=[])
        scenes = await SceneService().get_by_chapter_range_models(
            db,
            novel_id,
            start_chapter,
            end_chapter,
        )
        chapter_indices = sorted(
            {
                int(chunk["chapter_index"])
                for scene in scenes
                for chunk in (getattr(scene, "scene_chunks", None) or [])
                if isinstance(chunk, dict)
                and str(chunk.get("chapter_index", "")).isdigit()
                and start_chapter <= int(chunk["chapter_index"]) <= end_chapter
            }
        )
        drafts = (
            await writing_facade.list_manuscript_sources(
                db,
                novel_id,
                chapter_indices,
                content_mode=context_mode,
            )
            if chapter_indices
            else []
        )
        draft_by_chapter = {draft.chapter_index: draft for draft in drafts}
        lines: list[str] = []
        cards: list[dict] = []
        for scene in scenes:
            if scene.status == "deprecated":
                continue
            scene_chapters = self._scene_chapter_indices(scene)
            lines.append(render_scene_summary_line(scene, scene_chapters, guard=guard))
            card = render_scene_summary_card(scene, scene_chapters)
            card["_evidence"] = self._scene_evidence(
                scene,
                draft_by_chapter,
                start_chapter=start_chapter,
                end_chapter=end_chapter,
            )
            cards.append(card)
        return SceneSummaryText("\n".join(lines) + ("\n" if lines else ""), cards)

    @staticmethod
    def _scene_evidence(
        scene: object,
        draft_by_chapter: dict[int, object],
        *,
        start_chapter: int,
        end_chapter: int,
    ) -> dict:
        sources: list[dict] = []
        issues: list[str] = []
        for chunk in getattr(scene, "scene_chunks", []) or []:
            if not isinstance(chunk, dict):
                issues.append("invalid_scene_chunk")
                continue
            try:
                chapter_index = int(chunk.get("chapter_index"))
                start = int(chunk.get("start_offset"))
                end = int(chunk.get("end_offset"))
            except (TypeError, ValueError):
                issues.append("missing_exact_offsets")
                continue
            draft = draft_by_chapter.get(chapter_index)
            content = str(getattr(draft, "content", "") or "")
            content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
            if not (start_chapter <= chapter_index <= end_chapter):
                issues.append("scene_chunk_outside_visible_range")
            if draft is None or not getattr(draft, "id", None):
                issues.append("source_draft_missing")
            elif not chunk.get("source_draft_id"):
                issues.append("missing_source_draft_id")
            elif str(chunk["source_draft_id"]) != str(getattr(draft, "id")):
                issues.append("source_draft_mismatch")
            if not content or content_hash != str(getattr(draft, "content_hash", "")):
                issues.append("source_hash_mismatch")
            if not chunk.get("source_content_hash"):
                issues.append("missing_scene_chunk_hash")
            elif str(chunk["source_content_hash"]) != content_hash:
                issues.append("scene_chunk_hash_mismatch")
            if start < 0 or end <= start or end > len(content):
                issues.append("invalid_scene_offsets")
                continue
            sources.append(
                {
                    "chapter_index": chapter_index,
                    "start_offset": start,
                    "end_offset": end,
                    "source_draft_id": str(getattr(draft, "id", "")),
                    "source_content_hash": content_hash,
                    "text": content[start:end],
                }
            )
        meta = dict(getattr(scene, "structure_meta", None) or {})
        if getattr(scene, "status", None) == "candidate" or meta.get("needs_review"):
            issues.append("scene_needs_review")
        if not sources:
            issues.append("scene_source_missing")
        issues = list(dict.fromkeys(issues))
        return {
            "status": "exact" if not issues else "invalid",
            "issues": issues,
            "sources": sources,
        }

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
