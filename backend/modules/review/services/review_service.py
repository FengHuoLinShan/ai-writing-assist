"""Review 业务逻辑层 — 结构复查核心

通过策略模式组织 7 个独立检查维度。
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.review.models import ReviewReport
from modules.review.repositories import ReviewReportRepository
from modules.review.schemas import ReviewReportContext, ReviewWarning
from modules.review.services.character_knowledge_check import CharacterKnowledgeCheck
from modules.review.services.duplicate_check import DuplicateCheck
from modules.review.services.early_reveal_check import EarlyRevealCheck
from modules.review.services.entity_reference_check import EntityReferenceCheck
from modules.review.services.geo_check import GeoCheck
from modules.review.services.helpers import is_valid_uuid, parse_uuid
from modules.review.services.protocol import CheckStrategy
from modules.review.services.schema_check import SchemaCheck
from modules.review.services.timeline_check import TimelineCheck
from shared.enums import ReviewDecision


class ReviewService:
    """结构复查服务

    编排 7 个检查策略，汇总结果，生成决策和修改建议。
    """

    VALID_TARGET_TYPES = frozenset({
        "world_structure",
        "plot_structure",
        "chapter_cards",
        "memory_update",
        "entity_candidates",
        "geo_structure",
    })

    def __init__(self, strategies: list[CheckStrategy] | None = None) -> None:
        self._repo = ReviewReportRepository()
        self._strategies = strategies or [
            SchemaCheck(),
            EntityReferenceCheck(),
            EarlyRevealCheck(),
            CharacterKnowledgeCheck(),
            TimelineCheck(),
            GeoCheck(),
            DuplicateCheck(),
        ]

    # ============================================================
    # 主入口
    # ============================================================

    async def run_all_checks(
        self,
        db: AsyncSession,
        novel_id: str,
        target_type: str,
        candidate_payload: dict[str, Any],
    ) -> ReviewReportContext:
        """运行所有检查维度，生成复查报告

        并行执行所有检查策略，汇总结果并生成决策。
        """
        import asyncio

        results = await asyncio.gather(
            *[s.check(db, novel_id, candidate_payload) for s in self._strategies],
        )

        (
            schema_warnings,
            entity_warnings,
            reveal_warnings,
            knowledge_warnings,
            timeline_warnings,
            geo_warnings,
            duplicate_warnings,
        ) = results

        all_warnings = (
            schema_warnings
            + entity_warnings
            + reveal_warnings
            + knowledge_warnings
            + timeline_warnings
            + geo_warnings
            + duplicate_warnings
        )

        decision = self._decide(all_warnings)
        revision_instructions = self._generate_revision_instructions(
            decision,
            schema_warnings,
            entity_warnings,
            reveal_warnings,
            knowledge_warnings,
            timeline_warnings,
            geo_warnings,
            duplicate_warnings,
        )
        score = self._calculate_score(decision, all_warnings)

        def _w_to_dict(w: ReviewWarning) -> dict:
            return w.model_dump()

        nid = parse_uuid(novel_id, "novel_id")
        entity = await self._repo.create(
            db,
            novel_id=nid,
            target_type=target_type,
            decision=decision,
            score=score,
            problems=[_w_to_dict(w) for w in all_warnings],
            conflict_warnings=[_w_to_dict(w) for w in timeline_warnings],
            early_reveal_warnings=[_w_to_dict(w) for w in reveal_warnings],
            character_knowledge_warnings=[_w_to_dict(w) for w in knowledge_warnings],
            duplicate_entity_warnings=[_w_to_dict(w) for w in duplicate_warnings],
            geo_warnings=[_w_to_dict(w) for w in geo_warnings],
            revision_instructions=revision_instructions,
        )

        return self._to_context(entity)

    async def get_report(
        self,
        db: AsyncSession,
        report_id: str,
        novel_id: str,
    ) -> ReviewReportContext:
        """获取已存在的复查报告"""
        rid = parse_uuid(report_id, "report_id")
        nid = parse_uuid(novel_id, "novel_id")
        entity = await self._repo.get(db, rid)
        from fastapi import HTTPException
        from fastapi import status as http_status

        if entity is None or str(entity.novel_id) != str(nid):
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"ReviewReport {report_id} not found",
            )
        return self._to_context(entity)

    async def list_reports(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        target_type: str | None = None,
        decision: str | None = None,
        skip: int = 0,
        limit: int = 20,
    ) -> tuple[list[ReviewReportContext], int]:
        """获取复查报告列表"""
        nid = parse_uuid(novel_id, "novel_id")
        reports, total = await self._repo.get_by_novel(
            db, nid, target_type=target_type, decision=decision,
            skip=skip, limit=limit,
        )
        return [self._to_context(r) for r in reports], total

    # ============================================================
    # 向后兼容的检查方法（委托给策略）
    # ============================================================

    async def _check_schema(
        self,
        target_type: str,
        candidate_payload: dict[str, Any],
    ) -> list[ReviewWarning]:
        """委托给 SchemaCheck（向后兼容）"""
        # 注入 target_type 到 payload 中供策略使用
        payload = dict(candidate_payload)
        if target_type:
            payload["target_type"] = target_type
        from sqlalchemy.ext.asyncio import AsyncSession
        return await self._strategies[0].check(None, "", payload)  # type: ignore[arg-type]

    async def _check_entity_references(
        self,
        db: AsyncSession,
        novel_id: str,
        candidate_payload: dict[str, Any],
    ) -> list[ReviewWarning]:
        return await self._strategies[1].check(db, novel_id, candidate_payload)

    async def _check_early_reveal(
        self,
        db: AsyncSession,
        novel_id: str,
        candidate_payload: dict[str, Any],
    ) -> list[ReviewWarning]:
        return await self._strategies[2].check(db, novel_id, candidate_payload)

    async def _check_character_knowledge(
        self,
        db: AsyncSession,
        novel_id: str,
        candidate_payload: dict[str, Any],
    ) -> list[ReviewWarning]:
        return await self._strategies[3].check(db, novel_id, candidate_payload)

    async def _check_timeline(
        self,
        db: AsyncSession,
        novel_id: str,
        candidate_payload: dict[str, Any],
    ) -> list[ReviewWarning]:
        return await self._strategies[4].check(db, novel_id, candidate_payload)

    async def _check_geo(
        self,
        db: AsyncSession,
        novel_id: str,
        candidate_payload: dict[str, Any],
    ) -> list[ReviewWarning]:
        return await self._strategies[5].check(db, novel_id, candidate_payload)

    async def _check_duplicates(
        self,
        db: AsyncSession,
        novel_id: str,
        candidate_payload: dict[str, Any],
    ) -> list[ReviewWarning]:
        return await self._strategies[6].check(db, novel_id, candidate_payload)

    # ============================================================
    # 辅助方法
    # ============================================================

    def _decide(self, warnings: list[ReviewWarning]) -> str:
        """根据警告列表生成决策"""
        critical = [w for w in warnings if w.severity == "high"]
        major = [w for w in warnings if w.severity == "medium"]

        if len(critical) > 0:
            return ReviewDecision.reject
        if len(major) > 3:
            return ReviewDecision.major_revision
        if len(major) > 0:
            return ReviewDecision.minor_revision
        return ReviewDecision.pass_

    def _calculate_score(self, decision: str, warnings: list[ReviewWarning]) -> float:
        """计算综合评分 (0.0 - 1.0)"""
        score = 1.0
        for w in warnings:
            if w.severity == "high":
                score -= 0.3
            elif w.severity == "medium":
                score -= 0.1
            elif w.severity == "low":
                score -= 0.05
        return max(0.0, round(score, 2))

    def _generate_revision_instructions(
        self,
        decision: str,
        schema_warnings: list[ReviewWarning],
        entity_warnings: list[ReviewWarning],
        reveal_warnings: list[ReviewWarning],
        knowledge_warnings: list[ReviewWarning],
        timeline_warnings: list[ReviewWarning],
        geo_warnings: list[ReviewWarning],
        duplicate_warnings: list[ReviewWarning],
    ) -> list[str]:
        """根据决策和警告生成修改建议"""
        instructions: list[str] = []

        if decision == ReviewDecision.reject:
            instructions.append("结构存在严重问题，建议重新生成候选。")

        checks = [
            (schema_warnings, "Schema"),
            (entity_warnings, "实体引用"),
            (reveal_warnings, "提前揭示"),
            (knowledge_warnings, "人物知识边界"),
            (timeline_warnings, "时间线"),
            (geo_warnings, "地理"),
            (duplicate_warnings, "重复"),
        ]
        for warns, label in checks:
            if warns:
                instructions.append(
                    f"修复 {len(warns)} 个{label}问题: "
                    + "; ".join(w.message for w in warns[:3])
                )

        return instructions

    def _to_context(self, entity: ReviewReport) -> ReviewReportContext:
        """将 ORM 模型转为上下文对象"""
        return ReviewReportContext(
            report_id=str(entity.id),
            novel_id=str(entity.novel_id),
            target_type=entity.target_type,
            target_id=str(entity.target_id) if entity.target_id else None,
            decision=entity.decision,
            score=entity.score,
            problems=entity.problems or [],
            conflict_warnings=entity.conflict_warnings or [],
            early_reveal_warnings=entity.early_reveal_warnings or [],
            character_knowledge_warnings=entity.character_knowledge_warnings or [],
            duplicate_entity_warnings=entity.duplicate_entity_warnings or [],
            geo_warnings=entity.geo_warnings or [],
            revision_instructions=entity.revision_instructions or [],
        )

    _parse_uuid = staticmethod(parse_uuid)
    _is_valid_uuid = staticmethod(is_valid_uuid)
