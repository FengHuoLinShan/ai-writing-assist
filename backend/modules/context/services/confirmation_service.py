"""Context confirmation service."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.context.contracts import (
    CompileOptions,
    ContextConfirmationContract,
)
from modules.context.repositories import ContextConfirmationRepository
from modules.context.services.compiled_context import CompiledContext
from modules.context.services.context_compiler import ContextCompiler
from shared.utils import parse_uuid


class ContextConfirmationService:
    """Owns AI reference confirmation semantics."""

    def __init__(
        self,
        repository: ContextConfirmationRepository | None = None,
        compiler: ContextCompiler | None = None,
    ) -> None:
        self._repo = repository or ContextConfirmationRepository()
        self._compiler = compiler or ContextCompiler()

    async def confirm_context(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        action: str,
        task: str,
        scope: str,
        retrieval_purpose: str = "generic_context",
        chapter_index: int | None = None,
        visible_until_chapter: int | None = None,
        visible_until_scene_id: str | None = None,
        visible_until_offset: int | None = None,
        scene_id: str | None = None,
        arc_id: str | None = None,
        entity_ids: list[str] | None = None,
        character_ids: list[str] | None = None,
        thread_ids: list[str] | None = None,
        location_ids: list[str] | None = None,
        reveal_mode: str = "author_safe",
        enable_geo_filter: bool = False,
        viewpoint_character_id: str | None = None,
        budget_tokens: int = 4000,
        context_mode: str = "canonical",
        content_mode: str = "canonical",
        include_pending_objects: bool = False,
        excluded_asset_ids: dict[str, list[str]] | None = None,
        user_note: str | None = None,
        include_world_synopsis: bool = False,
        selected_world_bible_draft_ids: list[str] | None = None,
    ) -> ContextConfirmationContract:
        retrieval_purpose = _resolve_retrieval_purpose(
            action,
            retrieval_purpose,
            reveal_mode=reveal_mode,
        )
        options = CompileOptions(
            novel_id=novel_id,
            task=task,
            scope=scope,
            consumer_action=action,
            retrieval_purpose=retrieval_purpose,
            chapter_index=chapter_index,
            visible_until_chapter=visible_until_chapter,
            visible_until_scene_id=visible_until_scene_id,
            visible_until_offset=visible_until_offset,
            scene_id=scene_id,
            arc_id=arc_id,
            entity_ids=entity_ids,
            character_ids=character_ids,
            thread_ids=thread_ids,
            location_ids=location_ids,
            reveal_mode=reveal_mode,
            enable_geo_filter=enable_geo_filter,
            viewpoint_character_id=viewpoint_character_id,
            budget_tokens=budget_tokens,
            context_mode=context_mode,
            content_mode=content_mode,
            include_pending_objects=include_pending_objects,
            excluded_asset_ids=excluded_asset_ids or {},
            user_note=user_note,
            include_world_synopsis=include_world_synopsis,
            selected_world_bible_draft_ids=selected_world_bible_draft_ids or [],
        )
        compiled = await self._compiler.compile_with_tiers(
            db,
            options,
            budget_tokens=budget_tokens,
        )
        selected_asset_ids = self._selected_asset_ids(compiled, options)
        warnings = list(compiled.warnings)
        record = await self._repo.create(
            db,
            novel_id=parse_uuid(novel_id, "novel_id"),
            action=action,
            task=task,
            scope=scope,
            context_mode=context_mode,
            include_pending_objects=include_pending_objects,
            excluded_asset_ids=excluded_asset_ids or {},
            selected_asset_ids=selected_asset_ids,
            user_note=user_note,
            compile_options=self._compile_options_json(options),
            warnings=warnings,
        )
        return self._to_contract(record, compiled=compiled)

    async def require_confirmation(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        action: str,
        confirmation_id: str | uuid.UUID,
        for_update: bool = False,
    ) -> ContextConfirmationContract:
        record = await self._repo.get(
            db,
            self._as_uuid(confirmation_id),
            for_update=for_update,
        )
        if record is None:
            raise ValueError("context_confirmation_id not found")
        if str(record.novel_id) != str(parse_uuid(novel_id, "novel_id")):
            raise ValueError("context confirmation novel_id mismatch")
        if record.action != action:
            raise ValueError("context confirmation action mismatch")
        return self._to_contract(record)

    async def require_fresh_confirmation(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        action: str,
        confirmation_id: str | uuid.UUID,
        for_update: bool = False,
    ) -> ContextConfirmationContract:
        confirmation = await self.require_confirmation(
            db,
            novel_id=novel_id,
            action=action,
            confirmation_id=confirmation_id,
            for_update=for_update,
        )
        if confirmation.result_status in {"stale_context", "needs_review"}:
            raise ValueError(
                f"context confirmation is {confirmation.result_status}; "
                "please review and confirm the latest context",
            )
        return confirmation

    async def compile_from_confirmation(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        action: str,
        confirmation_id: str | uuid.UUID,
    ) -> CompiledContext:
        confirmation = await self.require_confirmation(
            db,
            novel_id=novel_id,
            action=action,
            confirmation_id=confirmation_id,
        )
        options = CompileOptions(**confirmation.compile_options)
        return await self._compiler.compile_with_tiers(
            db,
            options,
            budget_tokens=options.budget_tokens,
        )

    async def attach_result_ref(
        self,
        db: AsyncSession,
        *,
        confirmation_id: str | uuid.UUID,
        result_type: str,
        result_id: str,
        status: str = "running",
    ) -> ContextConfirmationContract:
        record = await self._repo.get(
            db,
            self._as_uuid(confirmation_id),
            for_update=True,
        )
        if record is None:
            raise ValueError("context_confirmation_id not found")
        refs = [
            ref
            for ref in (record.result_refs or [])
            if not (ref.get("type") == result_type and ref.get("id") == result_id)
        ]
        refs.append({"type": result_type, "id": result_id})
        updated = await self._repo.update_tracking(
            db,
            record,
            result_refs=refs,
            result_status=status,
        )
        return self._to_contract(updated)

    async def attach_result_refs(
        self,
        db: AsyncSession,
        *,
        confirmation_id: str | uuid.UUID,
        result_refs: list[dict[str, str]],
        status: str = "running",
    ) -> ContextConfirmationContract:
        record = await self._repo.get(
            db,
            self._as_uuid(confirmation_id),
            for_update=True,
        )
        if record is None:
            raise ValueError("context_confirmation_id not found")

        refs_by_key = {
            (ref.get("type"), ref.get("id")): {
                "type": ref.get("type"),
                "id": ref.get("id"),
            }
            for ref in (record.result_refs or [])
        }
        for result_ref in result_refs:
            result_type = result_ref.get("type")
            result_id = result_ref.get("id")
            key = (result_type, result_id)
            refs_by_key.pop(key, None)
            refs_by_key[key] = {"type": result_type, "id": result_id}

        updated = await self._repo.update_tracking(
            db,
            record,
            result_refs=list(refs_by_key.values()),
            result_status=status,
        )
        return self._to_contract(updated)

    async def mark_asset_context_changed(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        asset_type: str,
        asset_id: str,
        reason: str,
    ) -> int:
        records = await self._repo.list_by_asset_ref(
            db,
            novel_id=parse_uuid(novel_id, "novel_id"),
            asset_type=asset_type,
            asset_id=asset_id,
        )
        status = "needs_review" if reason == "candidate_promoted" else "stale_context"
        updates = []
        for record in records:
            reasons = list(record.stale_reasons or [])
            if reason not in reasons:
                reasons.append(reason)
            updates.append((record, reasons))
        return await self._repo.update_tracking_many(
            db,
            updates,
            result_status=status,
        )

    @staticmethod
    def _selected_asset_ids(
        compiled: CompiledContext,
        options: CompileOptions,
    ) -> dict[str, list[str]]:
        selected: dict[str, list[str]] = {"project": [options.novel_id]}
        if options.scene_id:
            selected["scenes"] = [options.scene_id]
        if options.arc_id:
            selected["outline_arcs"] = [options.arc_id]
        if options.entity_ids:
            selected["world_entities"] = list(options.entity_ids)
        if options.character_ids:
            selected["characters"] = list(options.character_ids)
        if options.location_ids:
            selected["locations"] = list(options.location_ids)
        if options.selected_world_bible_draft_ids:
            selected["world_bible_draft"] = list(
                options.selected_world_bible_draft_ids
            )
        selected["context_sections"] = [section.key for section in compiled.sections]
        return selected

    @staticmethod
    def _compile_options_json(options: CompileOptions) -> dict[str, Any]:
        return {
            "novel_id": options.novel_id,
            "task": options.task,
            "scope": options.scope,
            "consumer_action": options.consumer_action,
            "retrieval_purpose": options.retrieval_purpose,
            "chapter_index": options.chapter_index,
            "visible_until_chapter": options.visible_until_chapter,
            "visible_until_scene_id": options.visible_until_scene_id,
            "visible_until_offset": options.visible_until_offset,
            "scene_id": options.scene_id,
            "arc_id": options.arc_id,
            "entity_ids": options.entity_ids,
            "character_ids": options.character_ids,
            "thread_ids": options.thread_ids,
            "location_ids": options.location_ids,
            "reveal_mode": options.reveal_mode,
            "viewpoint_character_id": options.viewpoint_character_id,
            "enable_geo_filter": options.enable_geo_filter,
            "budget_tokens": options.budget_tokens,
            "top_k": options.top_k,
            "context_mode": options.context_mode,
            "content_mode": options.content_mode,
            "include_pending_objects": options.include_pending_objects,
            "excluded_asset_ids": options.excluded_asset_ids,
            "user_note": options.user_note,
            "include_world_synopsis": options.include_world_synopsis,
            "selected_world_bible_draft_ids": options.selected_world_bible_draft_ids,
            "world_synopsis_revision_id": options.world_synopsis_revision_id,
            "world_synopsis_source_hash": options.world_synopsis_source_hash,
            "world_synopsis_block_hash": options.world_synopsis_block_hash,
        }

    @staticmethod
    def _to_contract(
        record,
        compiled: CompiledContext | None = None,
    ) -> ContextConfirmationContract:
        compiled_at = record.compiled_at or datetime.now(UTC)
        created_at = record.created_at or compiled_at
        sections = []
        budget_events = []
        if compiled is not None:
            sections = [
                {
                    "key": section.key,
                    "tier": int(section.tier),
                    "content": section.content,
                    "token_count": section.token_count,
                    "truncated": section.key in compiled.truncated_keys,
                    "title": section.title,
                    "preview": section.preview or section.content[:160],
                    "status": section.status,
                    "activation_reason": section.activation_reason,
                    "sources": section.sources,
                    "can_exclude": section.can_exclude and int(section.tier) != 0,
                    "excluded": section.excluded,
                    "truncated_reason": section.truncated_reason,
                    "retrieval_metadata": section.retrieval_metadata,
                }
                for section in compiled.sections
            ]
            budget_events = [event.model_dump() for event in compiled.budget_events]
        return ContextConfirmationContract(
            id=str(record.id),
            novel_id=str(record.novel_id),
            action=record.action,
            task=record.task,
            scope=record.scope,
            context_mode=record.context_mode,
            include_pending_objects=record.include_pending_objects,
            excluded_asset_ids=record.excluded_asset_ids or {},
            selected_asset_ids=record.selected_asset_ids or {},
            user_note=record.user_note,
            compile_options=record.compile_options or {},
            warnings=record.warnings or [],
            sections=sections,
            budget_events=budget_events,
            result_refs=record.result_refs or [],
            result_status=record.result_status,
            stale_reasons=record.stale_reasons or [],
            compiled_at=compiled_at.isoformat(),
            created_at=created_at.isoformat(),
        )

    @staticmethod
    def _as_uuid(value: str | uuid.UUID) -> uuid.UUID:
        if isinstance(value, uuid.UUID):
            return value
        return parse_uuid(str(value), "context_confirmation_id")


def _resolve_retrieval_purpose(
    action: str,
    requested: str,
    *,
    reveal_mode: str,
) -> str:
    if requested != "generic_context":
        return requested
    if reveal_mode == "character":
        return "character_context"
    if reveal_mode == "reader":
        return "reader_context"
    if action == "writing.generate":
        return "writing_generation"
    if action.startswith("writing.conflict_check"):
        return "conflict_review"
    if action.startswith("outline."):
        return "outline_generation"
    return "generic_context"
