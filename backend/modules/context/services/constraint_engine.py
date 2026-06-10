"""ConstraintEngine — dynamic hard constraint compilation (Tier=P0).

Generates ContextSection objects from 4 constraint sources:
- StaticConstraints: language-specific writing rules
- SceneConstraints: must_not_happen from scene cards
- KnowledgeConstraints: POV character knowledge boundaries
- ForeshadowingConstraints: seeded foreshadowing that must not be prematurely revealed
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.context.services.compiled_context import ContextSection, Tier

logger = logging.getLogger(__name__)

_STATIC_CONSTRAINTS_ZH = [
    "不得让角色知道其知识边界之外的信息",
    "不得在读者层提前揭示作者视角的秘密",
    "伏笔未到收束阶段不得提前揭示",
]

_STATIC_CONSTRAINTS_EN = [
    "Characters must not know information beyond their knowledge boundary",
    "Author-only secrets must not be revealed to readers prematurely",
    "Foreshadowing must not be revealed before their planned payoff",
]


class ConstraintEngine:
    async def compile_constraints(
        self,
        db: AsyncSession,
        novel_id: str,
        scene_id: str | None = None,
        chapter_index: int | None = None,
    ) -> list[ContextSection]:
        sections: list[ContextSection] = []
        sections.extend(await self._static_constraints("zh"))
        sections.extend(await self._scene_constraints(db, novel_id, scene_id))
        sections.extend(
            await self._knowledge_constraints(db, novel_id, chapter_index)
        )
        sections.extend(
            await self._foreshadowing_constraints(db, novel_id, chapter_index)
        )
        return sections

    async def _static_constraints(
        self, language: str = "zh"
    ) -> list[ContextSection]:
        constraints = (
            _STATIC_CONSTRAINTS_ZH if language == "zh" else _STATIC_CONSTRAINTS_EN
        )
        content = "\n".join(f"- {c}" for c in constraints)
        return [
            ContextSection(
                key="hard_constraints",
                tier=Tier.P0,
                content=content,
                token_count=max(1, len(content) // 4),
            )
        ]

    # ------------------------------------------------------------------
    # Scene constraints: must_not_happen from current Scene card
    # ------------------------------------------------------------------

    async def _scene_constraints(
        self,
        db: AsyncSession,
        novel_id: str,
        scene_id: str | None = None,
    ) -> list[ContextSection]:
        """加载当前 Scene 的 must_not_happen 作为硬约束"""
        if not scene_id:
            return []

        from shared.utils import parse_uuid

        sid = parse_uuid(scene_id, "scene_id")
        from modules.outline.models import Scene

        stmt = select(Scene).where(Scene.id == sid)
        result = await db.execute(stmt)
        scene = result.scalar_one_or_none()

        if not scene or not scene.must_not_happen:
            return []

        content = (
            f"## 当前 Scene 禁止事件\n\n"
            f"- {scene.must_not_happen}"
        )
        return [
            ContextSection(
                key="scene_constraints",
                tier=Tier.P0,
                content=content,
                token_count=max(1, len(content) // 4),
            )
        ]

    # ------------------------------------------------------------------
    # Knowledge constraints: POV character knowledge boundaries
    # ------------------------------------------------------------------

    async def _knowledge_constraints(
        self,
        db: AsyncSession,
        novel_id: str,
        chapter_index: int | None = None,
    ) -> list[ContextSection]:
        """加载人物知识边界约束

        对于 knowledge_level = "unknown" 的目标实体 → 角色不能使用该信息
        对于 knowledge_level = "false_belief" → 角色应按误判表现
        """
        from shared.utils import parse_uuid

        nid = parse_uuid(novel_id, "novel_id")
        from modules.world.models import CharacterKnowledge

        stmt = select(CharacterKnowledge).where(
            CharacterKnowledge.novel_id == nid,
        )
        result = await db.execute(stmt)
        entries = result.scalars().all()

        if not entries:
            return []

        lines: list[str] = []
        unknown_count = 0
        false_beliefs: list[str] = []

        for entry in entries:
            level = entry.knowledge_level
            target_ref = f"{entry.target_type}:{entry.target_id}"
            if level == "unknown":
                unknown_count += 1
            elif level == "false_belief":
                if entry.misconception:
                    false_beliefs.append(f"- {target_ref}: {entry.misconception}")

        if unknown_count > 0:
            lines.append(
                f"角色对 {unknown_count} 个目标实体/人物的知识级别为 unknown，"
                f"写作时不得让角色知晓这些实体的隐藏信息"
            )
        if false_beliefs:
            lines.append(
                "角色对以下实体存在错误认知，应按错误认知表现:\n"
                + "\n".join(false_beliefs)
            )

        if not lines:
            return []

        content = "\n\n".join(lines)
        return [
            ContextSection(
                key="knowledge_constraints",
                tier=Tier.P0,
                content=content,
                token_count=max(1, len(content) // 4),
            )
        ]

    # ------------------------------------------------------------------
    # Foreshadowing constraints: seeded foreshadowing must not be
    # prematurely revealed
    # ------------------------------------------------------------------

    async def _foreshadowing_constraints(
        self,
        db: AsyncSession,
        novel_id: str,
        chapter_index: int | None = None,
    ) -> list[ContextSection]:
        """加载伏笔约束

        状态为 "seeded" 且 planned_payoff_chapter > 当前章节的伏笔
        → LLM 不得在当前章节提前揭示
        """
        from shared.utils import parse_uuid

        nid = parse_uuid(novel_id, "novel_id")
        from modules.outline.models import ForeshadowingPlan

        stmt = select(ForeshadowingPlan).where(
            ForeshadowingPlan.novel_id == nid,
            ForeshadowingPlan.status == "seeded",
        )
        result = await db.execute(stmt)
        plans = result.scalars().all()

        if not plans:
            return []

        # Filter: only warn about foreshadowing whose payoff is after current chapter
        active = []
        for plan in plans:
            if (
                chapter_index is not None
                and plan.planned_payoff_chapter is not None
                and plan.planned_payoff_chapter <= chapter_index
            ):
                continue  # already due for payoff, no constraint
            active.append(plan)

        if not active:
            return []

        lines = ["## 伏笔约束\n\n以下伏笔已埋下但尚未到兑现章节，禁止提前揭示："]
        for plan in active:
            payoff = (
                f"第{plan.planned_payoff_chapter}章"
                if plan.planned_payoff_chapter
                else "待定"
            )
            lines.append(
                f"- **{plan.name}**: {plan.surface_meaning or plan.summary or ''} "
                f"(计划兑现: {payoff})"
            )

        content = "\n".join(lines)
        return [
            ContextSection(
                key="foreshadowing_constraints",
                tier=Tier.P0,
                content=content,
                token_count=max(1, len(content) // 4),
            )
        ]
