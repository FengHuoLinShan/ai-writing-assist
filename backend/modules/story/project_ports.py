"""Project-facing workspace stats and dedup ports owned by Story (AO-4).

project 是 L1 隔离根，不得顶层 import story 聚合统计；组合根把这里的
adapter 注册为 ``project.workspace.story_stats`` / ``project.dedup.story``，
adapter 经本模块 facade 委托，属 story 内部合法调用。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.project.contracts import (
    WorkspaceAttentionItem,
    WorkspaceSceneFocus,
)
from modules.story import facade as story_facade


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
        scene_ids=tuple(item.scene_ids or ()),
        suggestion_id=item.suggestion_id,
        updated_at=item.updated_at,
    )


class StoryWorkspaceStatsAdapter:
    """Adapt Scene progress and attention items to the project provider."""

    async def count_scenes(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        status_filter: list[str] | None = None,
    ) -> int:
        return await story_facade.count_scenes_by_novel(
            db,
            novel_id,
            status_filter=status_filter,
        )

    async def get_attention_items(
        self,
        db: AsyncSession,
        novel_id: str,
    ) -> tuple[WorkspaceAttentionItem, ...]:
        items = await story_facade.get_author_attention_items(db, novel_id)
        return tuple(_attention_item(item) for item in items)

    async def get_scene_focus(
        self,
        db: AsyncSession,
        novel_id: str,
        scene_id: str,
    ) -> WorkspaceSceneFocus | None:
        scene = await story_facade.get_scene_contract(db, novel_id, scene_id)
        if scene is None:
            return None
        # Keep the exact chapter-membership semantics of the former project-side
        # helper: chapter_ids plus dict scene_chunks' chapter_index/chapter_id,
        # filtered to digit strings before the int cast.
        values = list(scene.chapter_ids or [])
        values.extend(
            chunk.get("chapter_index", chunk.get("chapter_id"))
            for chunk in (scene.scene_chunks or [])
            if isinstance(chunk, dict)
        )
        return WorkspaceSceneFocus(
            id=scene.id,
            chapter_indices=tuple(
                int(value) for value in values if str(value).isdigit()
            ),
        )


class StoryDedupAdapter:
    """Delegate structure dedup suggestions and applies to Story facades."""

    async def suggest_structure_dedup(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        asset_types: list[str],
        limit: int,
        max_suggestions: int,
        progress_callback: Any | None,
        exclusions: list[dict[str, Any]] | None,
        llm_client: Any | None,
    ) -> dict[str, Any]:
        return await story_facade.suggest_structure_dedup(
            db,
            novel_id,
            asset_types=asset_types,
            limit=limit,
            max_suggestions=max_suggestions,
            progress_callback=progress_callback,
            exclusions=exclusions,
            llm_client=llm_client,
        )

    async def apply_structure_dedup_group(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        asset_type: str,
        primary_asset_id: str,
        operations: list[dict[str, Any]],
        validate_only: bool,
        execution_fingerprints_prevalidated: bool,
    ) -> list[dict[str, Any]]:
        return await story_facade.apply_structure_dedup_group(
            db,
            novel_id,
            asset_type=asset_type,
            primary_asset_id=primary_asset_id,
            operations=operations,
            validate_only=validate_only,
            execution_fingerprints_prevalidated=execution_fingerprints_prevalidated,
        )

    async def apply_structure_dedup(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        confirmed: bool,
        suggestions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return await story_facade.apply_structure_dedup(
            db,
            novel_id,
            confirmed=confirmed,
            suggestions=suggestions,
        )
