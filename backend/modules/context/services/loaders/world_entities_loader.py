"""世界对象加载器"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.context.contracts import (
    AUTHOR_ONLY_WARNING,
    CONTEXT_BUDGET,
    CompileOptions,
    StructureContextBundle,
)
from modules.context.services.protocol import Loader

logger = logging.getLogger(__name__)

_GetWorldContextFn = Callable[..., Awaitable[Any]]


async def _default_get_world_context(*args: Any, **kwargs: Any) -> Any:
    from modules.world.facade import get_world_context

    return await get_world_context(*args, **kwargs)


class WorldEntitiesLoader(Loader):
    """加载世界对象，按重要性排序并受 budget 限制"""

    def __init__(
        self,
        get_world_context_fn: _GetWorldContextFn = _default_get_world_context,
    ) -> None:
        self._get_world_context = get_world_context_fn

    @property
    def name(self) -> str:
        return "world_entities"

    async def load(
        self,
        db: AsyncSession,
        options: CompileOptions,
        bundle: StructureContextBundle,
    ) -> None:
        core_limit = CONTEXT_BUDGET.get("core_entities", 8)
        normal_limit = CONTEXT_BUDGET.get("normal_entities", 8)

        if options.entity_ids:
            all_limit = core_limit + normal_limit
            limited_ids = options.entity_ids[:all_limit]
            ctx = await self._get_world_context(
                db,
                options.novel_id,
                entity_ids=limited_ids,
                reveal_mode=options.reveal_mode,
                limit=all_limit,
                current_chapter=options.visible_until_chapter or options.chapter_index,
            )
            entities = [e.model_dump() for e in ctx.entities] if ctx else []
            bundle.world_entities = entities
            bundle.budget_used["core_entities"] = min(len(entities), core_limit)
            bundle.budget_used["normal_entities"] = max(0, len(entities) - core_limit)
        else:
            ctx = await self._get_world_context(
                db,
                options.novel_id,
                reveal_mode=options.reveal_mode,
                limit=core_limit + normal_limit,
                current_chapter=options.visible_until_chapter or options.chapter_index,
            )
            entities = [e.model_dump() for e in ctx.entities] if ctx else []
            entities.sort(key=lambda e: e.get("importance", 0.0), reverse=True)

            core_entities = [
                e
                for e in entities
                if e.get("importance_level") == "core" or e.get("importance", 0.0) >= 0.75
            ][:core_limit]
            normal_entities = [e for e in entities if e not in core_entities][
                :normal_limit
            ]

            bundle.world_entities = core_entities + normal_entities
            bundle.budget_used["core_entities"] = len(core_entities)
            bundle.budget_used["normal_entities"] = len(normal_entities)

        # Reveal 过滤
        if options.reveal_mode == "author_safe":
            for ent in bundle.world_entities:
                if ent.get("hidden_truth"):
                    ent["hidden_truth"] = f"{AUTHOR_ONLY_WARNING} {ent['hidden_truth']}"
        if options.reveal_mode in {"reader", "character"}:
            await self._apply_reader_visibility(db, options, bundle)

    async def _apply_reader_visibility(
        self,
        db: AsyncSession,
        options: CompileOptions,
        bundle: StructureContextBundle,
    ) -> None:
        from modules.outline.facade import get_reader_reveal_decision

        cutoff = options.visible_until_chapter or options.chapter_index
        if cutoff is None:
            bundle.world_entities = []
            bundle.warnings.append("读者/角色视角缺少截止章，已保守排除世界对象")
            return
        visible: list[dict] = []
        for item in bundle.world_entities:
            if item.get("status") != "canonical":
                continue
            decision = await get_reader_reveal_decision(
                db,
                novel_id=options.novel_id,
                target_type=(
                    "character" if item.get("entity_type") == "character" else "entity"
                ),
                target_id=str(item.get("entity_id") or item.get("id") or ""),
                cutoff_chapter=cutoff,
            )
            redacted = dict(item)
            redacted["hidden_truth"] = None
            if decision.has_policy:
                redacted["reader_reveal_content"] = decision.reveal_content
                if not decision.revealed:
                    redacted["summary"] = None
            else:
                # `summary` is an author-facing synopsis. Without an explicit
                # reveal policy only the public baseline is safe for readers.
                redacted["summary"] = redacted.get("public_info")
            visible.append(redacted)
        bundle.world_entities = visible
