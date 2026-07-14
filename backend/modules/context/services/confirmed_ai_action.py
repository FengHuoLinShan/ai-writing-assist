"""Confirmed AI action context materialization."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.context.contracts import (
    ConfirmedAIActionContext,
    ContextConfirmationContract,
)
from modules.context.markdown_renderer import render_compiled_context
from modules.context.services.confirmation_service import ContextConfirmationService


class ConfirmedAIActionService:
    """Owns the context lifecycle required before an AI action runs."""

    def __init__(
        self,
        confirmation_service: ContextConfirmationService | Any | None = None,
    ) -> None:
        self._confirmation = confirmation_service or ContextConfirmationService()

    async def prepare(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        action: str,
        confirmation_id: str,
        for_update: bool = False,
    ) -> ConfirmedAIActionContext:
        confirmation_kwargs = {
            "novel_id": novel_id,
            "action": action,
            "confirmation_id": confirmation_id,
        }
        if for_update:
            confirmation_kwargs["for_update"] = True
        confirmation = await self._confirmation.require_fresh_confirmation(
            db,
            **confirmation_kwargs,
        )
        compiled = await self._confirmation.compile_from_confirmation(
            db,
            novel_id=novel_id,
            action=action,
            confirmation_id=confirmation_id,
        )
        return ConfirmedAIActionContext(
            confirmation=confirmation,
            compiled=compiled,
            rendered_markdown=render_compiled_context(compiled),
            compile_options=dict(confirmation.compile_options),
            result_refs=list(confirmation.result_refs),
        )

    async def bind_result(
        self,
        db: AsyncSession,
        *,
        confirmation_id: str,
        result_type: str,
        result_id: str,
        status: str = "running",
    ) -> ContextConfirmationContract:
        return await self._confirmation.attach_result_ref(
            db,
            confirmation_id=confirmation_id,
            result_type=result_type,
            result_id=result_id,
            status=status,
        )
