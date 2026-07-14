"""项目元信息加载器"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.context.contracts import CompileOptions, StructureContextBundle
from modules.context.services.protocol import Loader

logger = logging.getLogger(__name__)

_GetProjectContextFn = Callable[[AsyncSession, str], Awaitable[Any]]

_PROMPT_SAFE_PROJECT_FIELDS = (
    "novel_id",
    "title",
    "genre",
    "tone",
    "language",
    "target_length",
    "current_stage",
    "default_reveal_policy",
)


async def _default_get_project_context(db: AsyncSession, novel_id: str) -> Any:
    from modules.project.facade import get_project_context

    return await get_project_context(db, novel_id)


class ProjectLoader(Loader):
    """加载项目元信息"""

    def __init__(
        self,
        get_project_context_fn: _GetProjectContextFn = _default_get_project_context,
    ) -> None:
        self._get_project_context = get_project_context_fn

    @property
    def name(self) -> str:
        return "project"

    async def load(
        self,
        db: AsyncSession,
        options: CompileOptions,
        bundle: StructureContextBundle,
    ) -> None:
        ctx = await self._get_project_context(db, options.novel_id)
        if ctx is not None:
            raw = ctx.model_dump()
            bundle.project = {
                field: raw[field] for field in _PROMPT_SAFE_PROJECT_FIELDS if field in raw
            }
            bundle.budget_used["project"] = 1
        else:
            bundle.budget_used["project"] = 0
            bundle.warnings.append(f"项目 {options.novel_id} 不存在")
