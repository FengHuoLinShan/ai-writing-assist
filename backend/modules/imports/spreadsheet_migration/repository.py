"""表格迁移会话 repository（计划 §3.5）— imports 内部使用。

revision 作乐观 CAS：mapping、decisions 和 AI 结果写入时 +1，不匹配时抛
ConflictError。只 flush 不 commit；DB 异常向上传播。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ConflictError
from modules.imports.models import ImportMigrationSession

MIGRATION_SESSION_STATUSES = frozenset({
    "draft",
    "applied",
    "rolled_back",
    "partially_rolled_back",
})
AI_STATUSES = frozenset({"idle", "queued", "running", "done", "failed"})


def _utcnow() -> datetime:
    return datetime.now(UTC)


class ImportMigrationSessionRepository:
    """import_migration_sessions 数据访问。"""

    async def create(
        self,
        db: AsyncSession,
        *,
        novel_id: uuid.UUID,
        owner_id: uuid.UUID,
        file_manifest: list[dict[str, Any]],
        rows_json: dict[str, list[list[str]]],
        mapping_json: dict[str, Any],
    ) -> ImportMigrationSession:
        session = ImportMigrationSession(
            novel_id=novel_id,
            owner_id=owner_id,
            status="draft",
            revision=1,
            file_manifest=file_manifest,
            rows_json=rows_json,
            mapping_json=mapping_json,
        )
        db.add(session)
        await db.flush()
        await db.refresh(session)
        return session

    async def get(
        self,
        db: AsyncSession,
        session_id: uuid.UUID,
        *,
        novel_id: uuid.UUID,
        owner_id: uuid.UUID,
        for_update: bool = False,
    ) -> ImportMigrationSession | None:
        stmt = select(ImportMigrationSession).where(
            ImportMigrationSession.id == session_id,
            ImportMigrationSession.novel_id == novel_id,
            ImportMigrationSession.owner_id == owner_id,
        )
        if for_update:
            stmt = stmt.with_for_update()
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_recent(
        self,
        db: AsyncSession,
        *,
        novel_id: uuid.UUID,
        owner_id: uuid.UUID,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[ImportMigrationSession], int]:
        stmt = (
            select(ImportMigrationSession)
            .where(
                ImportMigrationSession.novel_id == novel_id,
                ImportMigrationSession.owner_id == owner_id,
            )
            .order_by(
                ImportMigrationSession.created_at.desc(),
                ImportMigrationSession.id.desc(),
            )
            .offset(offset)
            .limit(limit)
        )
        count_stmt = select(func.count()).select_from(ImportMigrationSession).where(
            ImportMigrationSession.novel_id == novel_id,
            ImportMigrationSession.owner_id == owner_id,
        )
        items = (await db.execute(stmt)).scalars().all()
        total = (await db.execute(count_stmt)).scalar() or 0
        return list(items), int(total)

    async def save_mapping(
        self,
        db: AsyncSession,
        session: ImportMigrationSession,
        *,
        mapping_json: dict[str, Any],
        expected_revision: int,
    ) -> ImportMigrationSession:
        if session.revision != expected_revision or session.status != "draft":
            raise ConflictError(
                "迁移会话已更新，请刷新后重试",
                code="migration_revision_stale",
            )
        session.mapping_json = mapping_json
        session.revision = expected_revision + 1
        await db.flush()
        await db.refresh(session)
        return session

    async def save_decisions(
        self,
        db: AsyncSession,
        session: ImportMigrationSession,
        *,
        decisions_json: dict[str, Any],
        expected_revision: int,
    ) -> ImportMigrationSession:
        if session.revision != expected_revision or session.status != "draft":
            raise ConflictError(
                "迁移会话已更新，请刷新后重试",
                code="migration_revision_stale",
            )
        session.decisions_json = decisions_json
        session.revision = expected_revision + 1
        await db.flush()
        await db.refresh(session)
        return session

    async def store_ai_result(
        self,
        db: AsyncSession,
        session_id: uuid.UUID,
        *,
        novel_id: uuid.UUID,
        task_id: uuid.UUID,
        scope_hash: str,
        result: dict[str, Any],
    ) -> bool:
        """写回 AI 结果；只有 scope_hash 一致才写，返回是否写入。"""
        stmt = select(ImportMigrationSession).where(
            ImportMigrationSession.id == session_id,
            ImportMigrationSession.novel_id == novel_id,
        ).with_for_update()
        session = (await db.execute(stmt)).scalar_one_or_none()
        if session is None:
            return False
        if session.ai_scope_hash != scope_hash:
            return False
        session.ai_result_json = result
        session.ai_task_id = task_id
        session.ai_status = "done"
        session.revision += 1
        await db.flush()
        return True

    async def store_ai_estimate(
        self,
        db: AsyncSession,
        session: ImportMigrationSession,
        *,
        estimate: dict[str, int],
        operation_id: str | None = None,
    ) -> ImportMigrationSession:
        """把 AI 成本预估（及提交时的 operation 授权信息）并入 ai_authorization。

        只 flush 不 commit；不提升 revision（预估是 mapping 的派生数据，
        随 mapping 保存/提交一起变化）。
        """
        authorization = dict(session.ai_authorization or {})
        authorization["estimate"] = {
            "rows": int(estimate["rows"]),
            "chars": int(estimate["chars"]),
            "requests": int(estimate["requests"]),
        }
        if operation_id:
            authorization["operation_id"] = operation_id
            authorization["authorized_at"] = _utcnow().isoformat()
        session.ai_authorization = authorization
        await db.flush()
        await db.refresh(session)
        return session

    async def mark_ai_status(
        self,
        db: AsyncSession,
        session: ImportMigrationSession,
        *,
        status: str,
        task_id: uuid.UUID | None = None,
        scope_hash: str | None = None,
    ) -> ImportMigrationSession:
        if status not in AI_STATUSES:
            raise ValueError(f"未知的 AI 状态: {status}")
        session.ai_status = status
        if task_id is not None:
            session.ai_task_id = task_id
        if scope_hash is not None:
            session.ai_scope_hash = scope_hash
        await db.flush()
        await db.refresh(session)
        return session

    async def mark_applied(
        self,
        db: AsyncSession,
        session: ImportMigrationSession,
        *,
        receipt: dict[str, Any],
        preview_hash: str,
    ) -> ImportMigrationSession:
        session.status = "applied"
        session.applied_at = _utcnow()
        session.receipt_json = receipt
        session.preview_hash = preview_hash
        session.rows_json = {}
        session.ai_status = session.ai_status if session.ai_status == "done" else "idle"
        await db.flush()
        await db.refresh(session)
        return session

    async def mark_rolled_back(
        self,
        db: AsyncSession,
        session: ImportMigrationSession,
        *,
        partially: bool,
    ) -> ImportMigrationSession:
        session.status = "partially_rolled_back" if partially else "rolled_back"
        session.rolled_back_at = _utcnow()
        await db.flush()
        await db.refresh(session)
        return session

    async def delete(
        self,
        db: AsyncSession,
        session: ImportMigrationSession,
    ) -> None:
        await db.delete(session)
        await db.flush()


__all__ = [
    "AI_STATUSES",
    "MIGRATION_SESSION_STATUSES",
    "ImportMigrationSessionRepository",
]
