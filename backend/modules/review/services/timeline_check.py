"""时间线冲突检查"""

from __future__ import annotations

from collections import Counter
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.review.schemas import ReviewWarning
from modules.review.services.protocol import CheckStrategy


class TimelineCheck(CheckStrategy):
    """检查 5: 时间线冲突检查 — 顺序矛盾、事件重复、角色位置冲突"""

    @property
    def name(self) -> str:
        return "timeline"

    async def check(
        self,
        db: AsyncSession,
        novel_id: str,
        candidate_payload: dict[str, Any],
    ) -> list[ReviewWarning]:
        warnings: list[ReviewWarning] = []

        try:
            from modules.world.facade import check_timeline_conflicts
            conflict_result = await check_timeline_conflicts(db, novel_id, candidate_payload)
            for conflict in conflict_result:
                warnings.append(
                    ReviewWarning(
                        type="timeline_conflict",
                        message=getattr(conflict, "description", str(conflict)),
                        severity=getattr(conflict, "severity", "medium"),
                        location={
                            "source_event_ids": getattr(conflict, "source_event_ids", []),
                        },
                    )
                )
        except Exception:
            pass

        # 本地回退：检查章节顺序
        self._check_chapter_order(candidate_payload, warnings)
        # 本地回退：检查伏笔顺序
        self._check_foreshadowing_order(candidate_payload, warnings)

        return warnings

    def _check_chapter_order(
        self,
        candidate_payload: dict[str, Any],
        warnings: list[ReviewWarning],
    ) -> None:
        """检查章节顺序"""
        cards = candidate_payload.get("chapter_cards", [])
        if isinstance(cards, dict):
            cards = [cards]

        if not isinstance(cards, list):
            return

        indices = []
        for card in cards:
            if isinstance(card, dict):
                ci = card.get("chapter_index")
                if isinstance(ci, int):
                    indices.append(ci)

        # 检查重复
        if len(indices) != len(set(indices)):
            dupes = [idx for idx, count in Counter(indices).items() if count > 1]
            for d in dupes:
                warnings.append(
                    ReviewWarning(
                        type="timeline_conflict",
                        message=f"存在重复的章节索引: {d}",
                        severity="high",
                        location={"chapter_index": d},
                    )
                )

        # 检查连续跳转
        if indices:
            sorted_indices = sorted(indices)
            gaps = []
            for j in range(1, len(sorted_indices)):
                gap = sorted_indices[j] - sorted_indices[j - 1]
                if gap > 1:
                    gaps.append(
                        f"{sorted_indices[j - 1]} → {sorted_indices[j]}（跳过 {gap - 1} 章）"
                    )
            if len(gaps) > 3:
                warnings.append(
                    ReviewWarning(
                        type="timeline_conflict",
                        message=f"章节序列存在多处不连续跳转:\n" + "\n".join(gaps[:5]),
                        severity="low",
                        location={"gaps": gaps},
                    )
                )

    def _check_foreshadowing_order(
        self,
        candidate_payload: dict[str, Any],
        warnings: list[ReviewWarning],
    ) -> None:
        """检查伏笔 seed / payoff 顺序"""
        foreshadowings = candidate_payload.get("foreshadowing_plans", [])
        if isinstance(foreshadowings, dict):
            foreshadowings = [foreshadowings]

        for i, fs in enumerate(foreshadowings if isinstance(foreshadowings, list) else []):
            if not isinstance(fs, dict):
                continue
            seed = fs.get("planned_seed_chapter")
            payoff = fs.get("planned_payoff_chapter")
            if isinstance(seed, int) and isinstance(payoff, int) and seed >= payoff:
                warnings.append(
                    ReviewWarning(
                        type="timeline_conflict",
                        message=(
                            f"伏笔 '{fs.get('name', 'unnamed')}' "
                            f"的埋设章节({seed}) >= 收束章节({payoff})"
                        ),
                        severity="high",
                        location={
                            "foreshadowing_index": i,
                            "seed_chapter": seed,
                            "payoff_chapter": payoff,
                        },
                    )
                )
