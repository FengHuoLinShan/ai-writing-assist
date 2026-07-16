"""Manual outline-analysis chapter-range loader."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import asdict
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.context.contracts import CompileOptions, StructureContextBundle
from modules.context.services.protocol import Loader

_GetOutlineAnalysisContextFn = Callable[..., Awaitable[Any]]


async def _default_get_outline_analysis_context(
    *args: Any,
    **kwargs: Any,
) -> Any:
    from modules.outline.facade import get_outline_analysis_context

    return await get_outline_analysis_context(*args, **kwargs)


class OutlineAnalysisLoader(Loader):
    """Load the full range package before related character/object Top-K."""

    def __init__(
        self,
        get_outline_analysis_context_fn: _GetOutlineAnalysisContextFn = (
            _default_get_outline_analysis_context
        ),
    ) -> None:
        self._get_outline_analysis_context = get_outline_analysis_context_fn

    @property
    def name(self) -> str:
        return "outline_analysis"

    async def load(
        self,
        db: AsyncSession,
        options: CompileOptions,
        bundle: StructureContextBundle,
    ) -> None:
        if options.consumer_action != "outline.analyze":
            bundle.budget_used["outline_analysis"] = 0
            return
        if options.reveal_mode not in {"author_safe", "author_full"}:
            bundle.warnings.append(
                "读者/角色视角不加载作者大纲分析范围资料"
            )
            bundle.budget_used["outline_analysis"] = 0
            return
        start_chapter = options.chapter_index
        end_chapter = options.visible_until_chapter or start_chapter
        if start_chapter is None or end_chapter is None:
            bundle.warnings.append("大纲分析缺少章节范围，未加载范围结构资料")
            bundle.budget_used["outline_analysis"] = 0
            return
        if end_chapter < start_chapter:
            bundle.warnings.append("大纲分析章节范围无效，未加载范围结构资料")
            bundle.budget_used["outline_analysis"] = 0
            return
        context = await self._get_outline_analysis_context(
            db,
            options.novel_id,
            start_chapter=start_chapter,
            end_chapter=end_chapter,
        )
        bundle.outline_analysis = (
            dict(context)
            if isinstance(context, dict)
            else asdict(context)
            if context is not None
            else None
        )
        if bundle.outline_analysis is None:
            bundle.budget_used["outline_analysis"] = 0
            return
        bundle.budget_used["outline_analysis"] = sum(
            len(bundle.outline_analysis.get(key) or [])
            for key in (
                "scenes",
                "arcs",
                "plot_threads",
                "foreshadowing_plans",
                "reveal_plans",
            )
        )
        bundle.warnings.extend(bundle.outline_analysis.get("warnings") or [])
