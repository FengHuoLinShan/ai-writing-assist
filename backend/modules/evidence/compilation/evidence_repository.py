"""Persistence for target-to-original-text evidence links."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.evidence.compilation.models import EvidenceLink


class EvidenceLinkRepository:
    async def create(
        self,
        db: AsyncSession,
        *,
        novel_id: uuid.UUID,
        target_ref: dict,
        target_hash: str,
        claim_path: str,
        evidence_type: str,
        source_ref: dict,
        precision: str,
        status: str,
        provenance: dict,
    ) -> EvidenceLink:
        item = EvidenceLink(
            novel_id=novel_id,
            target_ref=target_ref,
            target_hash=target_hash,
            claim_path=claim_path,
            evidence_type=evidence_type,
            source_ref=source_ref,
            precision=precision,
            status=status,
            provenance=provenance,
        )
        db.add(item)
        await db.flush()
        return item

    async def list_for_target(
        self,
        db: AsyncSession,
        *,
        novel_id: uuid.UUID,
        target_hash: str,
        claim_path: str = "",
        statuses: tuple[str, ...] = ("active",),
    ) -> list[EvidenceLink]:
        conditions = [
            EvidenceLink.novel_id == novel_id,
            EvidenceLink.target_hash == target_hash,
            EvidenceLink.status.in_(statuses),
        ]
        if claim_path:
            conditions.append(EvidenceLink.claim_path == claim_path)
        stmt = (
            select(EvidenceLink)
            .where(*conditions)
            .order_by(EvidenceLink.created_at, EvidenceLink.id)
        )
        return list((await db.execute(stmt)).scalars().all())

    async def list_for_source_chapter(
        self,
        db: AsyncSession,
        *,
        novel_id: uuid.UUID,
        chapter_index: int,
    ) -> list[EvidenceLink]:
        stmt = select(EvidenceLink).where(
            EvidenceLink.novel_id == novel_id,
            EvidenceLink.status == "active",
        )
        items = list((await db.execute(stmt)).scalars().all())
        return [
            item
            for item in items
            if int((item.source_ref or {}).get("chapter_index") or 0) == chapter_index
        ]
