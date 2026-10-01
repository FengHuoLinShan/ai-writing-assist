"""作者编辑约定（也用于 AI 写作）加载器。

作者在编辑约定页显式开启「也用于 AI 写作」后，brief 在编译期进入
Context（默认关闭）。文风只决定表达方式，不新增事实或事件；
作者事实、前文与本章因果优先。
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.evidence.compilation.contracts import CompileOptions, StructureContextBundle
from modules.evidence.compilation.services.protocol import Loader

logger = logging.getLogger(__name__)

_GetBriefFn = Callable[[AsyncSession, str], Awaitable[Any]]


async def _default_get_brief(db: AsyncSession, novel_id: str) -> Any:
    from modules.project.facade import read_editorial_brief_for_writing

    return await read_editorial_brief_for_writing(db, novel_id)


class EditorialBriefLoader(Loader):
    """加载作者编辑约定；开关关闭或约定为空时不注入任何内容。"""

    def __init__(
        self,
        get_brief_fn: _GetBriefFn = _default_get_brief,
    ) -> None:
        self._get_brief = get_brief_fn

    @property
    def name(self) -> str:
        return "editorial_brief"

    async def load(
        self,
        db: AsyncSession,
        options: CompileOptions,
        bundle: StructureContextBundle,
    ) -> None:
        brief = await self._get_brief(db, options.novel_id)
        if isinstance(brief, dict) and brief.get("brief"):
            bundle.editorial_brief = {
                "version": int(brief.get("version") or 0),
                "brief": brief["brief"],
            }
            bundle.budget_used["editorial_brief"] = 1
        else:
            bundle.budget_used["editorial_brief"] = 0
