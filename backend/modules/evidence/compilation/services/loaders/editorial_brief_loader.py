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
    """加载作者编辑约定；仅 AI 写作（writing.generate）的作者视角注入。

    开关关闭或约定为空时不注入任何内容；读者/角色视角与其他消费
    动作（角色卡、大纲、导入整理等）不加载，约定里的刻意留白与
    误导安排不得进入角色已知资料。
    """

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
        bundle.budget_used["editorial_brief"] = 0
        if options.consumer_action != "writing.generate":
            return
        brief = await self._get_brief(db, options.novel_id)
        if not (isinstance(brief, dict) and brief.get("brief")):
            return
        if options.reveal_mode not in {"author_safe", "author_full"}:
            # 只在约定本会生效时提示，未开启开关的作者不受打扰
            bundle.warnings.append(
                "角色视角写作不使用编辑约定：其中的刻意留白与误导安排不能当作角色已知"
            )
            return
        bundle.editorial_brief = {
            "version": int(brief.get("version") or 0),
            "brief": brief["brief"],
        }
        bundle.budget_used["editorial_brief"] = 1
