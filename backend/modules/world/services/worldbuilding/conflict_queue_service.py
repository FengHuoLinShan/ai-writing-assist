"""Worldbuilding conflict queue service."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import NotFoundError
from modules.world.models import (
    ConflictCheckQueueItem,
)
from modules.world.schemas import (
    ConflictQueueResponse,
    WorldbookImportItem,
    WorldGenerationSemanticInspectionFinding,
    WorldGenerationSemanticInspectionReceipt,
)
from shared.utils import parse_uuid


class ConflictQueueService:
    async def replace_worldbook_import_conflicts(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        suggestion_id: str,
        manifest_hash: str,
        items: list[WorldbookImportItem],
    ) -> list[ConflictQueueResponse]:
        nid = parse_uuid(novel_id, "novel_id")
        pending = (
            (
                await db.execute(
                    select(ConflictCheckQueueItem).where(
                        ConflictCheckQueueItem.novel_id == nid,
                        ConflictCheckQueueItem.conflict_type
                        == "worldbook_import_conflict",
                        ConflictCheckQueueItem.status == "pending",
                    )
                )
            )
            .scalars()
            .all()
        )
        source_keys = {item.source_key for item in items}
        for existing in pending:
            if str((existing.target or {}).get("source_key") or "") in source_keys:
                existing.status = "stale"
        created: list[ConflictCheckQueueItem] = []
        for finding in items:
            conflict = ConflictCheckQueueItem(
                novel_id=nid,
                conflict_type="worldbook_import_conflict",
                severity="high" if finding.action == "conflict" else "medium",
                source_module="world.worldbook_import",
                target={
                    "source_key": finding.source_key,
                    "source_path": finding.path,
                    "target_id": finding.target_id,
                    "target_kind": finding.target_kind,
                    "suggestion_id": suggestion_id,
                },
                target_hash=finding.current_content_hash,
                summary=finding.reason,
                evidence_refs_json=[],
                resolution_json={
                    "author_action": "needs_decision",
                    "manifest_hash": manifest_hash,
                    "source_hash": finding.source_hash,
                    "current_content_hash": finding.current_content_hash,
                    "next_step": "手动核对导入版本与项目版本；系统不会自动覆盖或删除。",
                },
                status="pending",
            )
            db.add(conflict)
            created.append(conflict)
        await db.flush()
        return [ConflictQueueResponse.model_validate(item) for item in created]

    async def replace_semantic_inspection(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        target: dict[str, Any],
        target_hash: str,
        findings: list[WorldGenerationSemanticInspectionFinding],
        receipt: WorldGenerationSemanticInspectionReceipt,
    ) -> list[ConflictQueueResponse]:
        """Replace the pending inspection for one page while retaining history."""
        nid = parse_uuid(novel_id, "novel_id")
        result = await db.execute(
            select(ConflictCheckQueueItem).where(
                ConflictCheckQueueItem.novel_id == nid,
                ConflictCheckQueueItem.conflict_type == "semantic_inspection",
                ConflictCheckQueueItem.status == "pending",
            )
        )
        page_id = str(target.get("page_id") or "")
        for item in result.scalars().all():
            if str((item.target or {}).get("page_id") or "") == page_id:
                item.status = "stale"

        created: list[ConflictCheckQueueItem] = []
        for finding in findings:
            item = ConflictCheckQueueItem(
                novel_id=nid,
                conflict_type="semantic_inspection",
                severity=(
                    "medium" if finding.author_action == "needs_decision" else "low"
                ),
                source_module="world.semantic_inspection",
                target=target,
                target_hash=target_hash,
                summary=finding.summary,
                evidence_refs_json=[
                    evidence.source_ref.model_dump(mode="json")
                    for evidence in finding.evidence_refs
                ],
                resolution_json={
                    "author_action": finding.author_action,
                    "finding_type": finding.finding_type,
                    "evidence": finding.evidence,
                    "location": finding.location,
                    "next_step": finding.next_step,
                    "source_keys": finding.source_keys,
                    "receipt": receipt.model_dump(mode="json"),
                },
                status="pending",
            )
            db.add(item)
            created.append(item)
        await db.flush()
        return [ConflictQueueResponse.model_validate(item) for item in created]

    async def list(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        status: str | None = None,
        conflict_type: str | None = None,
    ) -> tuple[list[ConflictQueueResponse], int]:
        nid = parse_uuid(novel_id, "novel_id")
        stmt = select(ConflictCheckQueueItem).where(
            ConflictCheckQueueItem.novel_id == nid
        )
        if status:
            stmt = stmt.where(ConflictCheckQueueItem.status == status)
        if conflict_type:
            stmt = stmt.where(ConflictCheckQueueItem.conflict_type == conflict_type)
        result = await db.execute(stmt.order_by(ConflictCheckQueueItem.created_at.desc()))
        items = [
            ConflictQueueResponse.model_validate(item) for item in result.scalars().all()
        ]
        return items, len(items)

    async def resolve(
        self,
        db: AsyncSession,
        novel_id: str,
        item_id: str,
        *,
        status: str,
        resolution_json: dict[str, Any],
    ) -> ConflictQueueResponse:
        nid = parse_uuid(novel_id, "novel_id")
        iid = parse_uuid(item_id, "conflict_id")
        result = await db.execute(
            select(ConflictCheckQueueItem).where(
                ConflictCheckQueueItem.id == iid,
                ConflictCheckQueueItem.novel_id == nid,
            )
        )
        item = result.scalar_one_or_none()
        if item is None:
            raise NotFoundError("Conflict item not found")
        item.status = status
        item.resolution_json = resolution_json
        await db.flush()
        return ConflictQueueResponse.model_validate(item)


__all__ = ["ConflictQueueService"]
