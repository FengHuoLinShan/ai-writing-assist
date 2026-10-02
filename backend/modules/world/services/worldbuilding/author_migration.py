"""表格迁移 world 落库（ADR-0030，计划 §3.3/§4 L2）— 窄 seam，不复用 adoption package。

plan：只读预览（名称/别名解析、动作判定、关系处理、fingerprint）。
apply：行锁下重算计划并比对指纹，门禁一次性检查，写入 canonical 资产并产出回执。
rollback：逆序处理回执，已改动项保留。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from modules.world.contracts import (
        AuthorMigrationWorldRequest,
        MigrationRollbackResult,
        WorldMigrationPlan,
        WorldMigrationReceipt,
    )


async def plan_author_migration_world(
    db: AsyncSession,
    novel_id: str,
    request: AuthorMigrationWorldRequest,
) -> WorldMigrationPlan:
    """只读计算迁移计划。"""
    raise NotImplementedError("L2 车道实现")


async def apply_author_migration_world(
    db: AsyncSession,
    novel_id: str,
    request: AuthorMigrationWorldRequest,
    *,
    expected_fingerprint: str,
    authorized_by: str,
) -> WorldMigrationReceipt:
    """按已确认的计划写入；只 flush，不 commit。"""
    raise NotImplementedError("L2 车道实现")


async def rollback_author_migration_world(
    db: AsyncSession,
    novel_id: str,
    receipt: WorldMigrationReceipt,
    *,
    dry_run: bool,
) -> MigrationRollbackResult:
    """按回执逆序回滚；已改动项保留。"""
    raise NotImplementedError("L2 车道实现")
