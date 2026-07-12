"""Reader safety checks for worldbuilding targets."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.models import (
    ReaderRevealPolicy,
)
from modules.world.schemas import (
    ReaderSafetyItem,
    ReaderSafetyResponse,
    TargetRefSchema,
)
from shared.target_ref import TargetRef, normalize_target_ref
from shared.utils import parse_uuid


class ReaderSafetyService:
    async def check(
        self,
        db: AsyncSession,
        novel_id: str,
        targets: list[TargetRef | TargetRefSchema],
        *,
        effective_chapter_index: int | None = None,
        scene_id: str | None = None,
    ) -> ReaderSafetyResponse:
        nid = parse_uuid(novel_id, "novel_id")
        items: list[ReaderSafetyItem] = []
        for raw_target in targets:
            raw_value = (
                raw_target.model_dump()
                if hasattr(raw_target, "model_dump")
                else raw_target
            )
            target = normalize_target_ref(raw_value)
            result = await db.execute(
                select(ReaderRevealPolicy).where(
                    ReaderRevealPolicy.novel_id == nid,
                    ReaderRevealPolicy.target_hash == target.target_hash(),
                )
            )
            policy = result.scalar_one_or_none()
            diagnostics: list[str] = []
            reader_safe = False
            reveal_status = "unrevealed"
            public_baseline = False
            if policy is None:
                diagnostics.append("missing_reveal_policy")
            else:
                reveal_status = policy.status
                public_baseline = policy.public_baseline
                if policy.public_baseline:
                    reader_safe = True
                elif policy.reveal_chapter_index is None:
                    diagnostics.append("unrevealed_null_chapter")
                elif (
                    effective_chapter_index is not None
                    and policy.reveal_chapter_index <= effective_chapter_index
                ):
                    reader_safe = True
                if (
                    scene_id
                    and policy.reveal_scene_id
                    and str(policy.reveal_scene_id) == scene_id
                ):
                    reader_safe = True
            items.append(
                ReaderSafetyItem(
                    target=TargetRefSchema(**target.canonical_dict()),
                    target_hash=target.target_hash(),
                    reader_safe=reader_safe,
                    reveal_status=reveal_status,
                    public_baseline=public_baseline,
                    diagnostics=diagnostics,
                )
            )
        return ReaderSafetyResponse(items=items)


__all__ = ["ReaderSafetyService"]
