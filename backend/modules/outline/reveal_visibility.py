"""Deterministic reader reveal policy evaluation."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from modules.outline.contracts import ReaderRevealDecisionContract
from modules.outline.reveal_repository import RevealPlanRepository
from shared.utils import parse_uuid


class ReaderRevealPolicyService:
    """Resolve only chapter-level reveal information, conservatively."""

    def __init__(self, repo: RevealPlanRepository | None = None) -> None:
        self._repo = repo or RevealPlanRepository()

    async def evaluate(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        target_type: str,
        target_id: str,
        cutoff_chapter: int,
    ) -> ReaderRevealDecisionContract:
        plans = await self._repo.get_for_target(
            db,
            parse_uuid(novel_id, "novel_id"),
            target_type=target_type,
            target_id=parse_uuid(target_id, "target_id"),
        )
        if not plans:
            return ReaderRevealDecisionContract(
                target_type=target_type,
                target_id=target_id,
            )

        reached: list[tuple[int, int, str]] = []
        for plan in plans:
            for stage in plan.reveal_stages or []:
                try:
                    chapter = int(stage.get("chapter_index"))
                    stage_index = int(stage.get("stage_index") or 0)
                except (AttributeError, TypeError, ValueError):
                    continue
                # Reveal stages have no in-chapter offset. The cutoff chapter itself
                # therefore remains hidden instead of guessing ordering.
                if chapter < cutoff_chapter:
                    reached.append(
                        (chapter, stage_index, str(stage.get("reveal_content") or ""))
                    )
        if not reached:
            return ReaderRevealDecisionContract(
                target_type=target_type,
                target_id=target_id,
                has_policy=True,
                revealed=False,
            )
        chapter, _, content = max(reached, key=lambda item: (item[0], item[1]))
        return ReaderRevealDecisionContract(
            target_type=target_type,
            target_id=target_id,
            has_policy=True,
            revealed=True,
            reveal_chapter=chapter,
            reveal_content=content or None,
        )
