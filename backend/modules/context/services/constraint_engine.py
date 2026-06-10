"""ConstraintEngine — dynamic hard constraint compilation (Tier=P0).

Generates ContextSection objects from 4 constraint sources:
- StaticConstraints: language-specific writing rules
- SceneConstraints: must_not_happen from scene cards (TODO)
- KnowledgeConstraints: POV character knowledge boundaries (TODO)
- ForeshadowingConstraints: seeded foreshadowing payoffs (TODO)
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
        chapter_index: int | None = None,
    ) -> list[ContextSection]:
        sections: list[ContextSection] = []
        sections.extend(await self._static_constraints("zh"))
        sections.extend(await self._scene_constraints(scene_id, chapter_index))
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

    async def _scene_constraints(
        self, scene_id: str | None, chapter_index: int | None
    ) -> list[ContextSection]:
        # TODO: When scenes table exists, load must_not_happen from scene card
        return []

    async def _knowledge_constraints(
        self,
        db: AsyncSession,
        novel_id: str,
        chapter_index: int | None = None,
    ) -> list[ContextSection]:
        # TODO: When scenes/character_knowledge integrated, load POV knowledge
        return []

    async def _foreshadowing_constraints(
        self,
        db: AsyncSession,
        novel_id: str,
        chapter_index: int | None = None,
    ) -> list[ContextSection]:
        # TODO: When foreshadowing_plans table exists, load seeded foreshadowing
        return []
