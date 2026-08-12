"""Context confirmation service."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ConflictError
from modules.context.contracts import (
    CompileOptions,
    ContextConfirmationContract,
)
from modules.context.repositories import ContextConfirmationRepository
from modules.context.services.compiled_context import CompiledContext
from modules.context.services.context_compiler import ContextCompiler
from shared.utils import parse_uuid

_ASSET_TYPE_ALIASES = {
    "scenes": "scene",
    "outline_arcs": "outline_arc",
    "world_entities": "world_entity",
    "characters": "character",
    "locations": "location",
    "plot_threads": "plot_thread",
    "foreshadowing_plans": "foreshadowing_plan",
    "reveal_plans": "reveal_plan",
    "context_sections": "context_section",
}


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
        activation_profile_id: str | None = None,
        activation_profile_version: int | None = None,
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
            requested_chapter_index=chapter_index,
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
            activation_profile_id=activation_profile_id,
            activation_profile_version=activation_profile_version,
        )
        compiled = await self._compiler.compile_with_tiers(
            db,
            options,
            budget_tokens=budget_tokens,
        )
        if self._requires_character_profile(options):
            self._require_character_profile(compiled)
        if action == "outline.analyze":
            self._require_outline_analysis_range(compiled, options)
            options.outline_analysis_fingerprint = self._outline_analysis_fingerprint(
                compiled
            )
        if self._requires_scene_state_fingerprint(options):
            options.scene_state_fingerprint = self._scene_state_fingerprint(compiled)
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
        await self._repo.replace_asset_refs(
            db,
            record,
            asset_role="selected",
            refs=self._selected_refs(selected_asset_ids),
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
            novel_id=parse_uuid(novel_id, "novel_id"),
            for_update=for_update,
        )
        if record is None:
            raise ValueError("context_confirmation_id not found")
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
        compiled = await self._compiler.compile_with_tiers(
            db,
            options,
            budget_tokens=options.budget_tokens,
        )
        if self._requires_character_profile(options):
            self._require_character_profile(compiled)
        if action == "outline.analyze":
            self._require_outline_analysis_range(compiled, options)
        if options.outline_analysis_fingerprint:
            current_fingerprint = self._outline_analysis_fingerprint(compiled)
            if current_fingerprint != options.outline_analysis_fingerprint:
                raise ValueError(
                    "outline analysis context changed; "
                    "review and confirm the latest context"
                )
        if options.scene_state_fingerprint:
            current_fingerprint = self._scene_state_fingerprint(compiled)
            if current_fingerprint != options.scene_state_fingerprint:
                raise ConflictError(
                    "Scene time state changed; review and confirm the latest context",
                    code="scene_state_changed",
                )
        return compiled

    async def attach_result_ref(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        confirmation_id: str | uuid.UUID,
        result_type: str,
        result_id: str,
        status: str = "running",
    ) -> ContextConfirmationContract:
        normalized_ref = self._validated_result_ref(result_type, result_id)
        record = await self._repo.get(
            db,
            self._as_uuid(confirmation_id),
            novel_id=parse_uuid(novel_id, "novel_id"),
            for_update=True,
        )
        if record is None:
            raise ValueError("context_confirmation_id not found")
        refs = [
            ref
            for ref in (record.result_refs or [])
            if not (
                ref.get("type") == normalized_ref["type"]
                and ref.get("id") == normalized_ref["id"]
            )
        ]
        refs.append(normalized_ref)
        updated = await self._repo.update_tracking(
            db,
            record,
            result_refs=refs,
            result_status=status,
        )
        await self._repo.replace_asset_refs(
            db,
            updated,
            asset_role="result",
            refs=self._result_refs(refs),
        )
        return self._to_contract(updated)

    async def attach_result_refs(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        confirmation_id: str | uuid.UUID,
        result_refs: list[dict[str, str]],
        status: str = "running",
    ) -> ContextConfirmationContract:
        normalized_result_refs = [
            self._validated_result_ref(ref.get("type"), ref.get("id"))
            for ref in result_refs
        ]
        record = await self._repo.get(
            db,
            self._as_uuid(confirmation_id),
            novel_id=parse_uuid(novel_id, "novel_id"),
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
        for result_ref in normalized_result_refs:
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
        await self._repo.replace_asset_refs(
            db,
            updated,
            asset_role="result",
            refs=self._result_refs(list(refs_by_key.values())),
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
            asset_type=self._normalized_asset_type(asset_type),
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
            selected["world_bible_draft"] = list(options.selected_world_bible_draft_ids)
        if options.activation_profile_id:
            selected["activation_profile"] = [options.activation_profile_id]
        if options.activation_included_target_hashes:
            selected["activation_target_hash"] = list(
                options.activation_included_target_hashes
            )
        for item in compiled.activation_trace.get("items") or []:
            target = item.get("target") or {}
            target_type = str(target.get("target_type") or "")
            target_id = str(target.get("target_id") or "")
            if target_type and target_id:
                selected.setdefault(target_type, []).append(target_id)
        range_source_keys = {
            "scene": "scenes",
            "outline_arc": "outline_arcs",
            "plot_thread": "plot_threads",
            "foreshadowing_plan": "foreshadowing_plans",
            "reveal_plan": "reveal_plans",
        }
        for section in compiled.sections:
            if not section.key.startswith("outline_analysis_"):
                continue
            for source in section.sources:
                asset_key = range_source_keys.get(str(source.get("type") or ""))
                asset_id = str(source.get("id") or "")
                if asset_key and asset_id:
                    selected.setdefault(asset_key, []).append(asset_id)
        selected = {key: list(dict.fromkeys(values)) for key, values in selected.items()}
        selected["context_sections"] = [section.key for section in compiled.sections]
        return selected

    @staticmethod
    def _selected_refs(
        selected_asset_ids: dict[str, list[str]],
    ) -> list[tuple[str, str]]:
        refs: list[tuple[str, str]] = []
        for asset_type, asset_ids in selected_asset_ids.items():
            normalized_type = ContextConfirmationService._normalized_asset_type(
                asset_type
            )
            if not normalized_type:
                continue
            refs.extend(
                (normalized_type, normalized_id)
                for asset_id in asset_ids
                if (normalized_id := str(asset_id).strip())
            )
        return refs

    @staticmethod
    def _result_refs(result_refs: list[dict[str, str]]) -> list[tuple[str, str]]:
        refs: list[tuple[str, str]] = []
        for result_ref in result_refs:
            result_type = str(result_ref.get("type") or "").strip()
            result_id = str(result_ref.get("id") or "").strip()
            if not result_type or not result_id:
                raise ValueError("result refs require non-empty type and id")
            refs.append(
                (
                    ContextConfirmationService._normalized_asset_type(result_type),
                    result_id,
                )
            )
        return refs

    @staticmethod
    def _normalized_asset_type(asset_type: Any) -> str:
        normalized_type = str(asset_type or "").strip()
        return _ASSET_TYPE_ALIASES.get(normalized_type, normalized_type)

    @staticmethod
    def _validated_result_ref(result_type: Any, result_id: Any) -> dict[str, str]:
        normalized_type = str(result_type or "").strip()
        normalized_id = str(result_id or "").strip()
        if not normalized_type or not normalized_id:
            raise ValueError("result refs require non-empty type and id")
        return {"type": normalized_type, "id": normalized_id}

    @staticmethod
    def _compile_options_json(options: CompileOptions) -> dict[str, Any]:
        return {
            "novel_id": options.novel_id,
            "task": options.task,
            "scope": options.scope,
            "consumer_action": options.consumer_action,
            "retrieval_purpose": options.retrieval_purpose,
            "chapter_index": options.chapter_index,
            "requested_chapter_index": options.requested_chapter_index,
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
            "activation_profile_id": options.activation_profile_id,
            "activation_profile_version": options.activation_profile_version,
            "activation_profile_rule_hash": options.activation_profile_rule_hash,
            "activation_source_hashes": options.activation_source_hashes,
            "activation_included_target_hashes": (
                options.activation_included_target_hashes
            ),
            "outline_analysis_fingerprint": options.outline_analysis_fingerprint,
            "scene_state_fingerprint": options.scene_state_fingerprint,
        }

    @staticmethod
    def _outline_analysis_fingerprint(compiled: CompiledContext) -> str:
        payload = [
            {
                "key": section.key,
                "content": section.content,
                "sources": list(section.sources or []),
                "excluded": section.excluded,
                "truncated_reason": section.truncated_reason,
            }
            for section in compiled.sections
        ]
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _requires_scene_state_fingerprint(options: CompileOptions) -> bool:
        return bool(
            options.consumer_action == "writing.generate"
            and options.scene_id
            and options.reveal_mode == "character"
        )

    @staticmethod
    def _requires_character_profile(options: CompileOptions) -> bool:
        return bool(
            options.consumer_action == "writing.generate"
            and options.reveal_mode == "character"
        )

    @staticmethod
    def _require_character_profile(compiled: CompiledContext) -> None:
        if not any(section.key == "role_profile" for section in compiled.sections):
            raise ValueError(
                "POV character is unavailable; select an active character and recompile"
            )

    @staticmethod
    def _scene_state_fingerprint(compiled: CompiledContext) -> str:
        section = next(
            (item for item in compiled.sections if item.key == "scene_world_state"),
            None,
        )
        if section is None:
            raise ValueError(
                "Scene time state unavailable; review and confirm the latest context"
            )
        versions = section.retrieval_metadata.get("checkpoint_versions") or []
        by_dimension = {
            str(item.get("dimension")): item
            for item in versions
            if isinstance(item, dict) and item.get("dimension")
        }
        payload = [
            {
                "dimension": dimension,
                "id": str((by_dimension.get(dimension) or {}).get("id") or ""),
                "status": str(
                    (by_dimension.get(dimension) or {}).get("status") or "missing"
                ),
            }
            for dimension in ("entities", "relations", "locations", "knowledge", "map")
        ]
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _require_outline_analysis_range(
        compiled: CompiledContext,
        options: CompileOptions,
    ) -> None:
        """Fail closed when a requested range could not be materialized.

        Confirmations created before range-aware P07 remain compatible when
        they have no chapter range. A partially specified or failed new range
        in an author view must not silently degrade into a project-only
        analysis. Reader/character views intentionally use their separate
        spoiler-safe compiler path and never materialize author planning cards.
        """
        if options.reveal_mode not in {"author_safe", "author_full"}:
            return
        start = options.chapter_index
        end = options.visible_until_chapter
        if start is None and end is None:
            return
        if start is None:
            raise ValueError("outline analysis chapter range is invalid")
        resolved_end = end if end is not None else start
        expected_id = f"{start}-{resolved_end}"
        range_section = next(
            (
                section
                for section in compiled.sections
                if section.key == "outline_analysis_range"
            ),
            None,
        )
        source_ids = {
            str(source.get("id") or "")
            for source in (range_section.sources if range_section else [])
        }
        if range_section is None or expected_id not in source_ids:
            raise ValueError(
                "outline analysis range context could not be loaded; "
                "review and confirm the reference context again"
            )

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
