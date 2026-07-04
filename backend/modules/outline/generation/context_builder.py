"""剧情结构生成器的上下文构建模块。

负责从 context.facade 和 writing.facade 加载数据，组装为 LLM 可用的
Markdown 上下文，并输出名称→ID 映射表供后续解析使用。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from modules.context import facade as context_facade
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
            reveal_mode="author_only",
            context_mode=context_mode,
            include_pending_objects=include_pending_objects,
        )

        context_md = self._render_bundle_to_markdown(bundle)

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

        if include_existing_scenes:
            scenes_md = await self._load_scene_summaries(
                db,
                novel_id,
                start_chapter,
                end_chapter,
            )
            if scenes_md:
                context_md += "\n## 已生成 Scene 摘要\n" + scenes_md

        chapter_texts = (
            await self._load_chapter_texts(db, novel_id, start_chapter, end_chapter)
            if include_chapter_texts
            else []
        )
        if chapter_texts:
            context_md += "\n## 章节原文\n"
            for chapter_index, text in chapter_texts:
                truncated = text[:12000]
                context_md += f"\n### 第{chapter_index}章\n{truncated}\n"
                if len(text) > 12000:
                    context_md += "\n（本章内容已截断）\n"

        return PlotStructureContext(
            markdown=context_md,
            warnings=list(bundle.warnings or []),
            entity_name_to_id=entity_name_to_id,
            character_name_to_id=character_name_to_id,
        )

    def _render_bundle_to_markdown(self, bundle: object) -> str:
        """将 StructureContextBundle 渲染为 Markdown 片段。"""
        context_md = ""
        if bundle.project:
            context_md += f"## 项目\n{bundle.project}\n\n"
        if bundle.world_entities:
            context_md += "## 世界对象\n"
            for e in bundle.world_entities:
                context_md += (
                    f"- {e.get('name', '?')} ({e.get('entity_type', '?')}): "
                    f"{e.get('summary', '')}\n"
                )
        if bundle.characters:
            context_md += "\n## 人物\n"
            for c in bundle.characters:
                context_md += (
                    f"- {c.get('name', '?')} ({c.get('role', '?')}): "
                    f"{c.get('desire', '')}\n"
                )
        if bundle.rag_chunks:
            context_md += "\n## RAG 检索证据\n"
            for chunk in bundle.rag_chunks:
                if isinstance(chunk, dict):
                    source = chunk.get("source_type", "?")
                    chapter = chunk.get("chapter_index")
                    prefix = f"- [{source}"
                    if chapter is not None:
                        prefix += f" / 第{chapter}章"
                    text = str(chunk.get("text", "")).strip()
                    context_md += f"{prefix}] {text}\n"
                else:
                    context_md += f"- {chunk}\n"
        if bundle.warnings:
            context_md += "\n## 上下文警告\n"
            for warning in bundle.warnings:
                context_md += f"- {warning}\n"
        return context_md

    async def _load_scene_summaries(
        self,
        db: AsyncSession,
        novel_id: str,
        start_chapter: int,
        end_chapter: int,
    ) -> str:
        """加载指定章节范围内已有 Scene 的紧凑摘要。"""
        from modules.outline.services import SceneService

        scenes = await SceneService().get_by_chapter_range_models(
            db,
            novel_id,
            start_chapter,
            end_chapter,
        )
        lines: list[str] = []
        for scene in scenes:
            if scene.status == "deprecated":
                continue
            chapter_indices = self._scene_chapter_indices(scene)
            chapter_label = (
                f"第{min(chapter_indices)}-{max(chapter_indices)}章"
                if chapter_indices
                else "章节未知"
            )
            summary_parts = [
                scene.goal,
                scene.core_conflict,
                scene.emotional_beat,
            ]
            summary = "；".join(str(part).strip() for part in summary_parts if part)
            lines.append(
                f"- S{scene.scene_index} {chapter_label}《{scene.title or '未命名'}》"
                f"：{summary[:240]}"
            )
        return "\n".join(lines) + ("\n" if lines else "")

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
        )
        draft_by_chapter = {draft.chapter_index: draft for draft in drafts}
        results: list[tuple[int, str]] = []
        for chapter_index in chapter_indices:
            draft = draft_by_chapter.get(chapter_index)
            if draft is not None and draft.content:
                results.append((chapter_index, draft.content))
        return results
