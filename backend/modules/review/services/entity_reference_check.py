"""实体引用检查"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.review.schemas import ReviewWarning
from modules.review.services.helpers import is_valid_uuid
from modules.review.services.protocol import CheckStrategy


class EntityReferenceCheck(CheckStrategy):
    """检查 2: 实体引用检查 — 引用的实体/人物/剧情线是否存在于正史"""

    @property
    def name(self) -> str:
        return "entity_reference"

    async def check(
        self,
        db: AsyncSession,
        novel_id: str,
        candidate_payload: dict[str, Any],
    ) -> list[ReviewWarning]:
        warnings: list[ReviewWarning] = []

        referenced_ids: dict[str, list[str]] = {
            "entity": [], "character": [], "thread": [], "arc": [],
        }

        def _extract_refs(items: Any, field_map: list[tuple[str, str]]) -> None:
            if isinstance(items, dict):
                items = [items]
            for item in items if isinstance(items, list) else []:
                if not isinstance(item, dict):
                    continue
                for field, ref_type in field_map:
                    ids = item.get(field, [])
                    if isinstance(ids, list):
                        referenced_ids[ref_type].extend(
                            i for i in ids if isinstance(i, str) and i.strip()
                        )

        _extract_refs(
            candidate_payload.get("chapter_cards", []),
            [
                ("involved_character_ids", "character"),
                ("involved_entity_ids", "entity"),
                ("related_thread_ids", "thread"),
            ],
        )
        _extract_refs(
            candidate_payload.get("plot_threads", []),
            [
                ("related_character_ids", "character"),
                ("related_entity_ids", "entity"),
            ],
        )
        _extract_refs(
            candidate_payload.get("outline_arcs", []),
            [
                ("related_character_ids", "character"),
                ("related_entity_ids", "entity"),
                ("related_thread_ids", "thread"),
            ],
        )

        for ref_type in referenced_ids:
            referenced_ids[ref_type] = list(set(
                i for i in referenced_ids[ref_type] if is_valid_uuid(i)
            ))

        # 验证实体引用
        if referenced_ids["entity"]:
            try:
                from modules.world.facade import get_world_context
                ctx = await get_world_context(
                    db, novel_id,
                    entity_ids=referenced_ids["entity"],
                    limit=len(referenced_ids["entity"]),
                )
                found_ids = {e.entity_id for e in ctx.entities} if hasattr(ctx, "entities") else set()
                for mid in set(referenced_ids["entity"]) - found_ids:
                    warnings.append(
                        ReviewWarning(
                            type="entity_reference",
                            message=f"引用的世界对象不存在: {mid}",
                            severity="high",
                            location={"entity_id": mid},
                        )
                    )
            except Exception:
                pass

        # 验证人物引用
        if referenced_ids["character"]:
            try:
                from modules.world.facade import get_characters_context
                ctx = await get_characters_context(
                    db, novel_id,
                    character_ids=referenced_ids["character"],
                )
                found_ids = {c.character_id for c in ctx.characters} if hasattr(ctx, "characters") else set()
                for mid in set(referenced_ids["character"]) - found_ids:
                    warnings.append(
                        ReviewWarning(
                            type="entity_reference",
                            message=f"引用的人物不存在: {mid}",
                            severity="high",
                            location={"character_id": mid},
                        )
                    )
            except Exception:
                pass

        return warnings
