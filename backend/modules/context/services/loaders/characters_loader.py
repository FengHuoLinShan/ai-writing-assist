"""人物信息加载器（含知识边界过滤）"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from modules.context.contracts import CONTEXT_BUDGET, StructureContextBundle
from modules.context.services.protocol import Loader
from modules.context.services.types import CompileOptions

logger = logging.getLogger(__name__)


class CharactersLoader(Loader):
    """加载人物信息，对首个人物执行知识边界过滤"""

    @property
    def name(self) -> str:
        return "characters"

    async def load(
        self,
        db: AsyncSession,
        options: CompileOptions,
        bundle: StructureContextBundle,
    ) -> None:
        char_limit = CONTEXT_BUDGET.get("characters", 6)

        if options.character_ids:
            limited_ids = options.character_ids[:char_limit]
        else:
            limited_ids = await self._infer_character_ids(db, options, char_limit)

        if limited_ids:
            from modules.world.facade import get_characters_context

            ctx = await get_characters_context(
                db,
                options.novel_id,
                character_ids=limited_ids,
                reveal_mode=options.reveal_mode,
            )
            if ctx:
                bundle.characters = [c.model_dump() for c in ctx.characters]

        # 知识边界过滤：仅在 character reveal 模式下执行，使用视角人物作为过滤主体。
        if (
            options.reveal_mode == "character"
            and limited_ids
            and bundle.world_entities
            and options.scope != "project"
        ):
            from modules.world.facade import filter_context_by_character_knowledge

            filter_character_id = options.viewpoint_character_id or limited_ids[0]
            if not options.viewpoint_character_id:
                logger.warning(
                    "character reveal 模式未提供 viewpoint_character_id，"
                    "使用 limited_ids[0] 作为过滤角色: %s",
                    filter_character_id,
                )

            try:
                # 世界对象字段 (entity_type/entity_id) 需要映射为知识过滤器的
                # target_type/target_id 才能正确匹配 character_knowledge 记录。
                # character_knowledge 的 target_type 使用粗粒度分类：
                # character/location/event 保持原样，其它世界对象统一归为 entity。
                filter_input: list[dict] = []
                for ent in bundle.world_entities:
                    mapped = dict(ent)
                    etype = ent.get("entity_type", "")
                    if etype == "character":
                        mapped["target_type"] = "character"
                    elif etype in ("location", "event"):
                        mapped["target_type"] = etype
                    else:
                        mapped["target_type"] = "entity"
                    mapped["target_id"] = ent.get("entity_id", "") or ent.get("id", "")
                    filter_input.append(mapped)

                filtered = await filter_context_by_character_knowledge(
                    db,
                    options.novel_id,
                    filter_character_id,
                    filter_input,
                )

                # 将过滤结果映射回世界对象字段，并整合知识边界信息。
                # false_belief 时用 misconception 替换 summary，且不暴露 hidden_truth。
                restored: list[dict] = []
                for ent in filtered or []:
                    mapped = dict(ent)
                    mapped.pop("target_type", None)
                    mapped.pop("target_id", None)
                    mapped.pop("original_content", None)
                    if ent.get("knowledge_level") == "false_belief":
                        misconception = ent.get("content", "")
                        if misconception:
                            mapped["summary"] = misconception
                            mapped["misconception"] = misconception
                        mapped.pop("hidden_truth", None)
                    restored.append(mapped)

                if filtered is not None:
                    bundle.world_entities = restored
            except Exception:
                logger.warning("知识边界过滤失败", exc_info=True)

        bundle.budget_used["characters"] = len(bundle.characters)

    async def _infer_character_ids(
        self,
        db: AsyncSession,
        options: CompileOptions,
        limit: int,
    ) -> list[str]:
        """推断相关人物 ID — outline 模块已移除，暂时返回空"""
        return []
