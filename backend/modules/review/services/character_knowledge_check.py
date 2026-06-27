"""人物知识边界检查"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.review.schemas import ReviewWarning
from modules.review.services.helpers import is_valid_uuid
from modules.review.services.protocol import CheckStrategy


class CharacterKnowledgeCheck(CheckStrategy):
    """检查 4: 人物知识边界检查 — 角色是否知道不该知道的信息"""

    @property
    def name(self) -> str:
        return "character_knowledge"

    async def check(
        self,
        db: AsyncSession,
        novel_id: str,
        candidate_payload: dict[str, Any],
    ) -> list[ReviewWarning]:
        warnings: list[ReviewWarning] = []

        character_ids: set[str] = set()
        entity_ids: set[str] = set()

        # 收集角色和实体引用
        cards = candidate_payload.get("chapter_cards", [])
        if isinstance(cards, dict):
            cards = [cards]

        for card in cards if isinstance(cards, list) else []:
            if not isinstance(card, dict):
                continue
            for cid in card.get("involved_character_ids", []):
                if isinstance(cid, str) and cid.strip():
                    character_ids.add(cid)
            for eid in card.get("involved_entity_ids", []):
                if isinstance(eid, str) and eid.strip():
                    entity_ids.add(eid)

        threads = candidate_payload.get("plot_threads", [])
        if isinstance(threads, dict):
            threads = [threads]

        for thread in threads if isinstance(threads, list) else []:
            if not isinstance(thread, dict):
                continue
            for cid in thread.get("related_character_ids", []):
                if isinstance(cid, str) and cid.strip():
                    character_ids.add(cid)

        if not character_ids:
            return warnings

        # 对每个角色检查知识边界
        try:
            from modules.character.facade import get_character_knowledge_context

            for cid in list(character_ids):
                if not is_valid_uuid(cid):
                    continue

                knowledge_list = await get_character_knowledge_context(
                    db,
                    novel_id,
                    cid,
                    target_ids=list(entity_ids) if entity_ids else None,
                )

                for knowledge in knowledge_list:
                    if hasattr(knowledge, "knowledge_level"):
                        if knowledge.knowledge_level == "unknown":
                            target_name = getattr(knowledge, "target_id", "unknown")
                            warnings.append(
                                ReviewWarning(
                                    type="character_knowledge",
                                    message=(
                                        f"角色 {cid[:8]}... 不知道目标 {target_name}，"
                                        f"但候选结构暗示他们了解相关信息"
                                    ),
                                    severity="high",
                                    location={
                                        "character_id": cid,
                                        "target_id": target_name,
                                        "knowledge_level": "unknown",
                                    },
                                )
                            )
        except Exception:
            pass

        # 检查 visible_progress 和 hidden_progress 重叠
        for card in cards if isinstance(cards, list) else []:
            if not isinstance(card, dict):
                continue
            visible = card.get("visible_progress", [])
            hidden = card.get("hidden_progress", [])
            if isinstance(visible, list) and isinstance(hidden, list):
                overlap = set(str(v) for v in visible) & set(str(h) for h in hidden)
                if overlap:
                    warnings.append(
                        ReviewWarning(
                            type="character_knowledge",
                            message=(
                                f"章节 {card.get('chapter_index', '?')} 中 "
                                f"visible_progress 和 hidden_progress 存在重叠: "
                                f"{', '.join(str(o) for o in list(overlap)[:3])}"
                            ),
                            severity="medium",
                            location={
                                "chapter_index": card.get("chapter_index"),
                                "conflict_items": list(overlap),
                            },
                        )
                    )

        return warnings
