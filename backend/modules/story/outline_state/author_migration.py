"""表格迁移 story 落库（ADR-0030，计划 §3.4/§4 L3）— outline_state 窄 seam。

映射：arc → OutlineArc、thread → PlotThread、foreshadowing → ForeshadowingPlan、
chapter_plan → planned/reference/link Scene；总纲经 create_revision 写入。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from modules.story.outline_state.contracts import (
        AuthorMigrationStoryRequest,
        StoryMigrationPlan,
        StoryMigrationReceipt,
    )
    from modules.world.contracts import MigrationRollbackResult


async def plan_author_migration_structures(
    db: AsyncSession,
    novel_id: str,
    request: AuthorMigrationStoryRequest,
    *,
    entity_refs: dict[str, str | None],
) -> StoryMigrationPlan:
    """只读计算故事结构迁移计划；entity_refs 值为 None 表示本次新建、尚无 id。"""
    raise NotImplementedError("L3 车道实现")


async def apply_author_migration_structures(
    db: AsyncSession,
    novel_id: str,
    request: AuthorMigrationStoryRequest,
    *,
    entity_ids: dict[str, str],
    expected_fingerprint: str,
    authorized_by: str,
) -> StoryMigrationReceipt:
    """按已确认的计划写入；只 flush，不 commit。"""
    raise NotImplementedError("L3 车道实现")


async def rollback_author_migration_structures(
    db: AsyncSession,
    novel_id: str,
    receipt: StoryMigrationReceipt,
    *,
    dry_run: bool,
) -> MigrationRollbackResult:
    """按回执逆序回滚；已改动项保留。"""
    raise NotImplementedError("L3 车道实现")
