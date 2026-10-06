"""Project-facing workspace stats and dedup ports owned by World (AO-4).

project 是 L1 隔离根，不得顶层 import world 聚合统计；组合根把这里的
adapter 注册为 ``project.workspace.world_stats`` / ``project.dedup.world``，
adapter 经本模块 facade 委托，属 world 内部合法调用。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.project.contracts import (
    WorkspaceAttentionItem,
    WorkspaceWorldAttentionSummary,
)
from modules.world import facade as world_facade


def _attention_item(item: Any) -> WorkspaceAttentionItem:
    return WorkspaceAttentionItem(
        key=item.key,
        title=item.title,
        summary=item.summary,
        author_action=item.author_action,
        severity=item.severity,
        source_kind=item.source_kind,
        target_kind=item.target_kind,
        item_id=item.item_id,
        chapter_index=item.chapter_index,
        scene_id=item.scene_id,
        page_id=item.page_id,
        suggestion_id=item.suggestion_id,
        updated_at=item.updated_at,
    )


class WorldWorkspaceStatsAdapter:
    """Adapt World's attention summary to the project workspace provider."""

    async def get_attention_summary(
        self,
        db: AsyncSession,
        novel_id: str,
    ) -> WorkspaceWorldAttentionSummary:
        summary = await world_facade.get_author_attention_summary(db, novel_id)
        return WorkspaceWorldAttentionSummary(
            novel_id=summary.novel_id,
            world_objects=summary.world_objects,
            world_aliases=summary.world_aliases,
            world_relations=summary.world_relations,
            items=tuple(_attention_item(item) for item in summary.items),
        )


class WorldDedupAdapter:
    """Delegate entity-fusion dedup suggestions and applies to World facades."""

    async def suggest_entity_fusion(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        limit: int,
        max_suggestions: int,
        group_before_budget: bool,
        progress_callback: Any | None,
        exclusions: list[dict[str, Any]] | None,
        llm_client: Any | None,
    ) -> dict[str, Any]:
        return await world_facade.suggest_entity_fusion(
            db,
            novel_id,
            limit=limit,
            max_suggestions=max_suggestions,
            progress_callback=progress_callback,
            exclusions=exclusions,
            llm_client=llm_client,
            group_before_budget=group_before_budget,
        )

    async def apply_entity_fusion_group(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        primary_entity_id: str,
        operations: list[dict[str, Any]],
        validate_only: bool,
        execution_fingerprints_prevalidated: bool,
    ) -> list[dict[str, Any]]:
        return await world_facade.apply_entity_fusion_group(
            db,
            novel_id,
            primary_entity_id=primary_entity_id,
            operations=operations,
            validate_only=validate_only,
            execution_fingerprints_prevalidated=execution_fingerprints_prevalidated,
        )

    async def apply_entity_fusion(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        confirmed: bool,
        suggestions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return await world_facade.apply_entity_fusion(
            db,
            novel_id,
            confirmed=confirmed,
            suggestions=suggestions,
        )
