"""ConstraintEngine — dynamic hard constraint compilation (Tier=P0).

Generates ContextSection objects from 4 constraint sources:
- StaticConstraints: language-specific writing rules
- SceneConstraints: must_not_happen from scene cards
- KnowledgeConstraints: POV character knowledge boundaries
- ForeshadowingConstraints: seeded foreshadowing that must not be prematurely revealed
"""

from __future__ import annotations

import logging

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
        scene_index: int | None = None,
        chapter_index: int | None = None,
    ) -> list[ContextSection]:
        sections: list[ContextSection] = []
        sections.extend(await self._static_constraints("zh"))
        sections.extend(
            await self._scene_constraints(db, novel_id, scene_id=scene_id)
        )
        sections.extend(
            await self._knowledge_constraints(db, novel_id, chapter_index=chapter_index)
        )
        sections.extend(
            await self._foreshadowing_constraints(
                db, novel_id, scene_index=scene_index, chapter_index=chapter_index
            )
        )
        return sections

    async def _static_constraints(self, language: str = "zh") -> list[ContextSection]:
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

        from modules.outline.facade import get_scene

        scene = await get_scene(db, scene_id)

        if not scene or not scene.get("must_not_happen"):
            return []

        content = f"## 当前 Scene 禁止事件\n\n- {scene['must_not_happen']}"
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
        对于 knowledge_level = "restricted"/"partial"/"rumor" → 只能使用已知内容
        对于 knowledge_level = "false_belief"/"misunderstood" → 角色应按错误认知表现
        """
        from modules.world.facade import get_character_knowledge_entries

        entries = await get_character_knowledge_entries(db, novel_id)

        if not entries:
            return []

        lines: list[str] = []
        unknown_count = 0
        restricted_count = 0
        misunderstood: list[str] = []

        for entry in entries:
            level = entry.get("knowledge_level")
            target_ref = (
                f"{entry.get('target_type', '')}:{entry.get('target_id', '')}"
            )
            if level == "unknown":
                unknown_count += 1
            elif level in ("restricted", "partial", "rumor"):
                restricted_count += 1
            elif level in ("false_belief", "misunderstood"):
                misconception = entry.get("misconception")
                if misconception:
                    misunderstood.append(f"- {target_ref}: {misconception}")

        if unknown_count > 0:
            lines.append(
                f"角色对 {unknown_count} 个目标实体/人物的知识级别为 unknown，"
                f"写作时不得让角色知晓这些实体的隐藏信息"
            )
        if restricted_count > 0:
            lines.append(
                f"角色对 {restricted_count} 个目标实体/人物的知识受限，"
                f"只能使用已知内容(known_content)描述，不得暴露 hidden_truth"
            )
        if misunderstood:
            lines.append(
                "角色对以下实体存在错误认知，应按错误认知表现:\n"
                + "\n".join(misunderstood)
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
        scene_index: int | None = None,
        chapter_index: int | None = None,
    ) -> list[ContextSection]:
        """加载伏笔约束

        状态为 "seeded" 且 planned_payoff_scene > 当前场景索引（或
        planned_payoff_chapter > 当前章节）的伏笔 → LLM 不得在当前上下文提前揭示
        """
        from modules.outline.facade import get_active_foreshadowing

        plans = await get_active_foreshadowing(db, novel_id, status="seeded")

        if not plans:
            return []

        active = []
        for plan in plans:
            payoff_scene = plan.get("planned_payoff_scene")
            payoff_ch = plan.get("planned_payoff_chapter")

            if scene_index is not None and payoff_scene is not None:
                if payoff_scene <= scene_index:
                    continue
            elif chapter_index is not None and payoff_ch is not None:
                if payoff_ch <= chapter_index:
                    continue
            # else: cannot determine ordering, include conservatively

            active.append(plan)

        if not active:
            return []

        lines = ["## 伏笔约束\n\n以下伏笔已埋下但尚未到兑现章节，禁止提前揭示："]
        for plan in active:
            payoff_scene = plan.get("planned_payoff_scene")
            payoff_ch = plan.get("planned_payoff_chapter")
            if payoff_scene is not None:
                payoff = f"场景{payoff_scene}"
            elif payoff_ch is not None:
                payoff = f"第{payoff_ch}章"
            else:
                payoff = "待定"
            surface = plan.get("surface_meaning") or plan.get("summary") or ""
            name = plan.get("name", "")
            lines.append(
                f"- **{name}**: {surface} "
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
