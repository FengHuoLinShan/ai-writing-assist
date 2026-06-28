"""Persistence helpers for context confirmations."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.context.models import ContextConfirmation


class ContextConfirmationRepository:
    """Data access for AI reference confirmations."""

    async def create(
        self,
        db: AsyncSession,
        *,
        novel_id: uuid.UUID,
        action: str,
        task: str,
        scope: str,
        context_mode: str,
        include_pending_objects: bool,
        excluded_asset_ids: dict[str, list[str]],
        selected_asset_ids: dict[str, list[str]],
        user_note: str | None,
        compile_options: dict,
        warnings: list[str],
    ) -> ContextConfirmation:
        record = ContextConfirmation(
            novel_id=novel_id,
            action=action,
            task=task,
            scope=scope,
            context_mode=context_mode,
            include_pending_objects=include_pending_objects,
            excluded_asset_ids=excluded_asset_ids,
            selected_asset_ids=selected_asset_ids,
            user_note=user_note,
            compile_options=compile_options,
            warnings=warnings,
            result_refs=[],
            result_status="confirmed",
            stale_reasons=[],
        )
        db.add(record)
        await db.flush()
        return record

    async def get(
        self,
        db: AsyncSession,
        confirmation_id: uuid.UUID,
    ) -> ContextConfirmation | None:
        return await db.get(ContextConfirmation, confirmation_id)

    async def update_tracking(
        self,
        db: AsyncSession,
        record: ContextConfirmation,
        *,
        result_refs: list[dict[str, str]] | None = None,
        result_status: str | None = None,
        stale_reasons: list[str] | None = None,
    ) -> ContextConfirmation:
        if result_refs is not None:
            record.result_refs = result_refs
        if result_status is not None:
            record.result_status = result_status
        if stale_reasons is not None:
            record.stale_reasons = stale_reasons
        await db.flush()
        return record

    async def list_by_asset_ref(
        self,
        db: AsyncSession,
        *,
        novel_id: uuid.UUID,
        asset_type: str,
        asset_id: str,
    ) -> list[ContextConfirmation]:
        stmt = select(ContextConfirmation).where(
            ContextConfirmation.novel_id == novel_id,
        )
        result = await db.execute(stmt)
        records = list(result.scalars().all())
        matched: list[ContextConfirmation] = []
        for record in records:
            selected = record.selected_asset_ids or {}
            result_refs = record.result_refs or []
            if asset_id in [str(v) for v in selected.get(asset_type, [])]:
                matched.append(record)
                continue
            if any(str(ref.get("id")) == asset_id for ref in result_refs):
                matched.append(record)
        return matched
