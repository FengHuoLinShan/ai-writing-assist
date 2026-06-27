"""剧情结构生成器的上下文构建模块。

负责从 context.facade 和 writing.facade 加载数据，组装为 LLM 可用的
Markdown 上下文，并输出名称→ID 映射表供后续解析使用。
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from modules.context import facade as context_facade
from modules.writing import facade as writing_facade


@dataclass
class PlotStructureContext:
    """生成剧情结构所需的上下文。"""

    markdown: str
    """注入 prompt 的 Markdown 文本。"""

    entity_name_to_id: dict[str, str]
    """世界对象名称 → entity_id (UUID hex)。"""

    character_name_to_id: dict[str, str]
    """人物名称 → character_id (UUID hex)。"""


class PlotStructureContextBuilder:
    """构建 PlotStructureGenerator 所需的上下文。"""

    async def build(
        self,
        db: AsyncSession,
        novel_id: str,
        start_chapter: int,
        end_chapter: int,
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

        chapter_texts = await self._load_chapter_texts(
            db, novel_id, start_chapter, end_chapter
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
        return context_md

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
        results: list[tuple[int, str]] = []
        for chapter_index in range(start_chapter, end_chapter + 1):
            draft = await writing_facade.get_latest_draft_for_chapter(
                db, novel_id, chapter_index
            )
            if draft is not None and draft.content:
                results.append((chapter_index, draft.content))
        return results
