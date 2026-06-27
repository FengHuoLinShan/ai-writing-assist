"""重复检查"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.review.schemas import ReviewWarning
from modules.review.services.protocol import CheckStrategy


class DuplicateCheck(CheckStrategy):
    """检查 7: 重复检查 — 对象/剧情线/章节是否与已有正史重复"""

    @property
    def name(self) -> str:
        return "duplicate"

    async def check(
        self,
        db: AsyncSession,
        novel_id: str,
        candidate_payload: dict[str, Any],
    ) -> list[ReviewWarning]:
        warnings: list[ReviewWarning] = []

        # 检查 chapter_cards 是否与已有章节卡重复
        cards = candidate_payload.get("chapter_cards", [])
        if isinstance(cards, dict):
            cards = [cards]

        if isinstance(cards, list):
            for card in cards:
                if not isinstance(card, dict):
                    continue
                ci = card.get("chapter_index")
                if isinstance(ci, int):
                    try:
                        from modules.outline.facade import get_chapter_card

                        existing = await get_chapter_card(db, novel_id, ci)
                        if existing is not None:
                            warnings.append(
                                ReviewWarning(
                                    type="duplicate",
                                    message=(
                                        f"第 {ci} 章已有章节卡 "
                                        f"'{existing.title or 'unnamed'}'，"
                                        f"候选将创建重复条目"
                                    ),
                                    severity="medium",
                                    location={
                                        "chapter_index": ci,
                                        "existing_card_id": existing.card_id,
                                    },
                                )
                            )
                    except Exception:
                        pass

        # 检查 world_entities 名称重复
        entities = candidate_payload.get("world_entities", [])
        if isinstance(entities, dict):
            entities = [entities]

        for i, entity in enumerate(entities if isinstance(entities, list) else []):
            if not isinstance(entity, dict):
                continue
            name = entity.get("name", "")
            if name:
                try:
                    from modules.world.facade import get_world_context

                    ctx = await get_world_context(db, novel_id, limit=50)
                    existing_names = (
                        [
                            e.name
                            for e in ctx.entities
                            if hasattr(e, "name") and e.name == name
                        ]
                        if hasattr(ctx, "entities")
                        else []
                    )
                    if existing_names:
                        warnings.append(
                            ReviewWarning(
                                type="duplicate",
                                message=f"世界对象名称 '{name}' 已存在",
                                severity="low",
                                location={
                                    "entity_index": i,
                                    "entity_name": name,
                                },
                            )
                        )
                except Exception:
                    pass

        # 检查 entity_candidates 内部名称重复
        candidates_list = candidate_payload.get("entity_candidates", [])
        if isinstance(candidates_list, dict):
            candidates_list = [candidates_list]

        candidate_names = [
            (i, cand.get("name", ""))
            for i, cand in enumerate(
                candidates_list if isinstance(candidates_list, list) else []
            )
            if isinstance(cand, dict) and cand.get("name", "")
        ]

        seen_names: dict[str, int] = {}
        for i, name in candidate_names:
            if name in seen_names:
                warnings.append(
                    ReviewWarning(
                        type="duplicate",
                        message=(
                            f"候选列表内部存在重复名称: '{name}' "
                            f"（索引 {seen_names[name]} 和 {i}）"
                        ),
                        severity="medium",
                        location={
                            "first_index": seen_names[name],
                            "second_index": i,
                            "name": name,
                        },
                    )
                )
            else:
                seen_names[name] = i

        return warnings
