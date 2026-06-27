"""提前揭示检查"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.review.schemas import ReviewWarning
from modules.review.services.protocol import CheckStrategy


class EarlyRevealCheck(CheckStrategy):
    """检查 3: 提前揭示检查 — hidden_truth 是否泄露到公开字段"""

    @property
    def name(self) -> str:
        return "early_reveal"

    async def check(
        self,
        db: AsyncSession,
        novel_id: str,
        candidate_payload: dict[str, Any],
    ) -> list[ReviewWarning]:
        warnings: list[ReviewWarning] = []

        # 检查 world_entities
        entities = candidate_payload.get("world_entities", [])
        if isinstance(entities, dict):
            entities = [entities]

        for i, entity in enumerate(entities if isinstance(entities, list) else []):
            if not isinstance(entity, dict):
                continue
            self._check_entity_reveal(entity, i, warnings)

        # 检查 plot_threads
        threads = candidate_payload.get("plot_threads", [])
        if isinstance(threads, dict):
            threads = [threads]
        chapter_index = candidate_payload.get("chapter_index")

        for i, thread in enumerate(threads if isinstance(threads, list) else []):
            if not isinstance(thread, dict):
                continue
            self._check_thread_reveal(thread, i, chapter_index, warnings)

        # 检查 reveal_plans
        reveals = candidate_payload.get("reveal_plans", [])
        if isinstance(reveals, dict):
            reveals = [reveals]

        for i, reveal in enumerate(reveals if isinstance(reveals, list) else []):
            if not isinstance(reveal, dict):
                continue
            self._check_reveal_plan_gaps(reveal, i, warnings)

        return warnings

    def _check_entity_reveal(
        self,
        entity: dict[str, Any],
        index: int,
        warnings: list[ReviewWarning],
    ) -> None:
        """检查单个实体的提前揭示"""
        hidden_truth = entity.get("hidden_truth")
        reveal_level = entity.get("reveal_level", "author_only")

        if not hidden_truth or reveal_level != "author_only":
            return

        leaked_fields = []
        hidden_subs = set()
        for ci in range(len(hidden_truth) - 2):
            sub = hidden_truth[ci : ci + 3]
            if sub.strip():
                hidden_subs.add(sub)

        if not hidden_subs:
            hidden_subs = {hidden_truth} if hidden_truth.strip() else set()

        for field_name in ("public_info", "summary", "description"):
            field_val = entity.get(field_name, "")
            if field_val and isinstance(field_val, str):
                match_count = sum(1 for sub in hidden_subs if field_val.find(sub) >= 0)
                if match_count >= 2:
                    leaked_fields.append(field_name)

        if leaked_fields:
            warnings.append(
                ReviewWarning(
                    type="early_reveal",
                    message=(
                        f"世界对象 '{entity.get('name', 'unnamed')}' "
                        "的 hidden_truth 泄露至 "
                        f"{'/'.join(leaked_fields)}，揭示层级为 {reveal_level}"
                    ),
                    severity="high",
                    location={
                        "entity_index": index,
                        "entity_name": entity.get("name", ""),
                        "leaked_fields": leaked_fields,
                    },
                )
            )

    def _check_thread_reveal(
        self,
        thread: dict[str, Any],
        index: int,
        chapter_index: Any,
        warnings: list[ReviewWarning],
    ) -> None:
        """检查剧情线的提前揭示"""
        hidden_truth = thread.get("hidden_truth")
        if not hidden_truth or not chapter_index:
            return

        visible_goal = thread.get("visible_goal", "")
        if visible_goal and len(hidden_truth) > 2:
            revealed = any(
                visible_goal.find(sub) >= 0
                for sub in [hidden_truth[i : i + 3] for i in range(len(hidden_truth) - 2)]
                if sub.strip()
            )
            if revealed:
                warnings.append(
                    ReviewWarning(
                        type="early_reveal",
                        message=(
                            f"剧情线 '{thread.get('name', 'unnamed')}' "
                            f"的 hidden_truth 在 visible_goal 中被暗示"
                        ),
                        severity="medium",
                        location={
                            "thread_index": index,
                            "thread_name": thread.get("name", ""),
                        },
                    )
                )

    def _check_reveal_plan_gaps(
        self,
        reveal: dict[str, Any],
        index: int,
        warnings: list[ReviewWarning],
    ) -> None:
        """检查揭示计划阶段间隔"""
        stages = reveal.get("reveal_stages", [])
        if not isinstance(stages, list) or len(stages) < 2:
            return

        chapters = [
            s.get("chapter_index", 0)
            for s in stages
            if isinstance(s, dict) and s.get("chapter_index")
        ]
        for j in range(1, len(chapters)):
            gap = chapters[j] - chapters[j - 1]
            if gap > 20:
                warnings.append(
                    ReviewWarning(
                        type="early_reveal",
                        message=(
                            f"揭示计划 '{reveal.get('secret_summary', 'unnamed')[:50]}' "
                            f"两个揭示阶段间隔 {gap} 章"
                            f"（{chapters[j - 1]} → {chapters[j]}），"
                            f"可能造成读者遗忘前文伏笔"
                        ),
                        severity="low",
                        location={
                            "reveal_index": index,
                            "from_chapter": chapters[j - 1],
                            "to_chapter": chapters[j],
                            "gap": gap,
                        },
                    )
                )
