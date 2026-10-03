"""作者写作示例（好例/反例）加载器。

作者开启「示例用于 AI 写作」后，示例作为 few-shot 在编译期进入
Context（默认关闭）。首版只覆盖正文生成（writing.generate）的作者
视角；示例只表达语感偏好，不新增事实或事件，作者事实与前文因果
优先。角色/读者视角不加载。
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.evidence.compilation.contracts import CompileOptions, StructureContextBundle
from modules.evidence.compilation.services.protocol import Loader

logger = logging.getLogger(__name__)

_GetExamplesFn = Callable[[AsyncSession, str], Awaitable[Any]]


async def _default_get_examples(db: AsyncSession, novel_id: str) -> Any:
    from modules.project.facade import read_author_examples_for_writing

    return await read_author_examples_for_writing(db, novel_id)


class AuthorExamplesLoader(Loader):
    """加载作者写作示例；仅 AI 写作（writing.generate）的作者视角注入。

    开关关闭或没有实质示例时不注入任何内容；读者/角色视角与其他
    消费动作（角色卡、大纲、导入整理等）不加载。
    """

    def __init__(
        self,
        get_examples_fn: _GetExamplesFn = _default_get_examples,
    ) -> None:
        self._get_examples = get_examples_fn

    @property
    def name(self) -> str:
        return "author_examples"

    async def load(
        self,
        db: AsyncSession,
        options: CompileOptions,
        bundle: StructureContextBundle,
    ) -> None:
        bundle.budget_used["author_examples"] = 0
        if options.consumer_action != "writing.generate":
            return
        payload = await self._get_examples(db, options.novel_id)
        if not (isinstance(payload, dict) and payload.get("examples")):
            return
        examples = [
            item
            for item in payload["examples"]
            if isinstance(item, dict) and item.get("capability_id") == "writing.generate"
        ]
        if not examples:
            return
        if options.reveal_mode not in {"author_safe", "author_full"}:
            # 只在示例本会生效时提示，未开启开关的作者不受打扰
            bundle.warnings.append(
                "角色视角写作不使用作者示例：示例语感不能当作角色已知资料"
            )
            return
        bundle.author_examples = {
            "version": int(payload.get("version") or 0),
            "examples": examples,
        }
        bundle.budget_used["author_examples"] = 1
