"""Confirmed AI action context materialization."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.evidence.compilation.contracts import (
    CompileOptions,
    ConfirmedAIActionContext,
    ContextConfirmationContract,
)
from modules.evidence.compilation.markdown_renderer import render_compiled_context
from modules.evidence.compilation.services.confirmation_service import (
    ContextConfirmationService,
    _pop_exploration_frozen_options,
    execution_compile_options,
)


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
        consumer_action: str | None = None,
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
            **({"consumer_action": consumer_action} if consumer_action else {}),
        )
        return ConfirmedAIActionContext(
            confirmation=confirmation,
            compiled=compiled,
            rendered_markdown=render_compiled_context(compiled),
            compile_options=execution_compile_options(confirmation.compile_options),
            result_refs=list(confirmation.result_refs),
        )

    async def bind_result(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        confirmation_id: str,
        result_type: str,
        result_id: str,
        status: str = "running",
    ) -> ContextConfirmationContract:
        return await self._confirmation.attach_result_ref(
            db,
            novel_id=novel_id,
            confirmation_id=confirmation_id,
            result_type=result_type,
            result_id=result_id,
            status=status,
        )

    async def character_projection(self, db, *, confirmed, character_id: str):
        """Narrow the same confirmation to a character; never expand its read set."""
        from core.errors import ConflictError

        projection_options = dict(confirmed.compile_options)
        _pop_exploration_frozen_options(projection_options)
        options = CompileOptions(**projection_options)
        options.reveal_mode = "character"
        if options.scope == "project":
            options.scope = "world_character"
        options.viewpoint_character_id = character_id
        options.character_ids = [character_id]
        options.visible_until_scene_id = (
            options.visible_until_scene_id or options.scene_id
        )
        options.user_note = ""
        options.task = ""
        options.compiled_context_fingerprint = None
        projected = await self._confirmation._compiler.compile_with_tiers(
            db, options, budget_tokens=options.budget_tokens
        )
        allowed = {
            str(source.get("id"))
            for section in confirmed.compiled.sections
            for source in section.sources
            if source.get("id")
        }
        sections = []
        for section in projected.sections:
            if section.key not in {
                "role_profile",
                "role_visible_knowledge",
                "role_observed_characters",
                "role_relationship_context",
                "scene_world_state",
            }:
                continue
            if section.items:
                items = [
                    item
                    for item in section.items
                    if (item.sources or [item.source])
                    and all(
                        str(source.get("id") or "") in allowed
                        for source in (item.sources or [item.source])
                    )
                ]
                if items:
                    sections.append(
                        section.model_copy(
                            update={
                                "items": items,
                                "content": "\n".join(item.content for item in items),
                                "sources": [
                                    source
                                    for item in items
                                    for source in (item.sources or [item.source])
                                ],
                            }
                        )
                    )
            elif section.sources and all(
                str(source.get("id") or "") in allowed for source in section.sources
            ):
                sections.append(section)
        if not any(section.key == "role_profile" for section in sections):
            raise ConflictError("角色资料不在原确认范围内，请将该角色纳入资料后重新确认")
        projected.sections = sections
        return ConfirmedAIActionContext(
            confirmation=confirmed.confirmation,
            compiled=projected,
            rendered_markdown=render_compiled_context(projected),
            compile_options={
                **confirmed.compile_options,
                "reveal_mode": "character",
                "viewpoint_character_id": character_id,
                "visible_until_scene_id": options.scene_id,
            },
            result_refs=list(confirmed.result_refs),
        )
