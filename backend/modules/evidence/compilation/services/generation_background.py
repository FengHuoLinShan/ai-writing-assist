"""Author-only generation-background compilation and provenance.

This module owns the complete operation: normalize the caller's focus, compile
the tiered context, project the public usage summary, and durably open the
matching context snapshot.  The facade only adapts the stable keyword
interface into :class:`GenerationBackgroundRequest`.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass, field, replace
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from modules.evidence.compilation.contracts import (
    CompileOptions,
    ContextSnapshotContract,
    ContextSnapshotRequest,
)
from modules.evidence.compilation.markdown_renderer import render_compiled_context
from modules.evidence.compilation.services.compiled_context import (
    LINE_ITEM_SOURCE_KEYS,
    CompiledContext,
)
from modules.evidence.compilation.services.context_compiler import ContextCompiler
from modules.evidence.compilation.services.snapshot_service import (
    DurableContextSnapshotService,
)

_WORLD_GENERATION_OPERATIONS = frozenset(
    {
        "world.generation.chat",
        "world.generation.convergence",
        "world.generation.core_entity",
        "world.generation.exploration",
        "world.generation.semantic_inspection",
        "world.generation.world_bible_page",
        "world.map_atlas.generate",
    }
)
_MAX_FOCUS_CHARS = 4000
_DEFAULT_BUDGET_TOKENS = 4000


class _Compiler(Protocol):
    async def compile_with_tiers(
        self,
        db: AsyncSession,
        options: CompileOptions,
        budget_tokens: int = _DEFAULT_BUDGET_TOKENS,
    ) -> CompiledContext: ...


class _SnapshotWriter(Protocol):
    async def open_context_snapshot(
        self,
        caller_db: AsyncSession,
        request: ContextSnapshotRequest,
    ) -> ContextSnapshotContract: ...


@dataclass(frozen=True)
class GenerationBackgroundRequest:
    """One immutable request consumed by the deep generation-background module."""

    novel_id: str
    task: str
    include_world_synopsis: bool = False
    selected_world_bible_draft_ids: tuple[str, ...] = ()
    activation_profile_id: str | None = None
    activation_profile_version: int | None = None
    operation: str = "world.generation.core_entity"
    prompt_name: str = "world.generation.core_entity.structured"
    model: str = "project-default"
    focus_text: str = ""
    reference_chapter_index: int | None = None
    scene_id: str | None = None
    thread_ids: tuple[str, ...] | None = None
    character_ids: tuple[str, ...] | None = None
    entity_ids: tuple[str, ...] | None = None
    source_snapshot: Mapping[str, Any] = field(default_factory=dict)
    budget_tokens: int = _DEFAULT_BUDGET_TOKENS
    capture_snapshot: bool = True


class GenerationBackgroundService:
    """Compile generation context and open its durable provenance snapshot."""

    def __init__(
        self,
        *,
        compiler: _Compiler | None = None,
        renderer: Callable[[CompiledContext], str] | None = None,
        snapshot_writer: _SnapshotWriter | None = None,
    ) -> None:
        self._compiler = compiler or ContextCompiler()
        self._renderer = renderer or render_compiled_context
        self._snapshot_writer = snapshot_writer or DurableContextSnapshotService()

    async def compile(
        self,
        db: AsyncSession,
        request: GenerationBackgroundRequest,
    ) -> dict[str, Any]:
        """Return the stable generation-background dict consumed by world."""
        request = replace(
            request,
            source_snapshot=deepcopy(dict(request.source_snapshot)),
        )
        normalized_focus = self._normalize_focus(request.focus_text)
        is_world_generation = request.operation in _WORLD_GENERATION_OPERATIONS
        options = self._compile_options(
            request,
            normalized_focus=normalized_focus,
            is_world_generation=is_world_generation,
        )
        compiled = await self._compiler.compile_with_tiers(
            db,
            options,
            budget_tokens=options.budget_tokens,
        )
        rendered = self._renderer(compiled)
        usage = self._context_usage(
            request,
            options,
            compiled,
            is_world_generation=is_world_generation,
        )
        included_asset_ids = self._included_asset_ids(compiled, options)
        included_asset_manifest = self._included_asset_manifest(
            compiled,
            operation=request.operation,
        )
        if request.capture_snapshot:
            snapshot_request = self._snapshot_request(
                request,
                options,
                compiled,
                rendered=rendered,
                usage=usage,
                included_asset_ids=included_asset_ids,
                normalized_focus=normalized_focus,
            )
            snapshot = await self._snapshot_writer.open_context_snapshot(
                db,
                snapshot_request,
            )
            usage["context_snapshot_id"] = snapshot.id
        return {
            "rendered_context": rendered,
            "context_usage": {
                **usage,
                "included_asset_ids": included_asset_ids,
                "included_asset_manifest": included_asset_manifest,
            },
        }

    @staticmethod
    def _normalize_focus(focus_text: str) -> str:
        return " ".join((focus_text or "").split())[:_MAX_FOCUS_CHARS]

    @staticmethod
    def _compile_options(
        request: GenerationBackgroundRequest,
        *,
        normalized_focus: str,
        is_world_generation: bool,
    ) -> CompileOptions:
        compile_task = (
            f"{request.task}：{normalized_focus}" if normalized_focus else request.task
        )
        return CompileOptions(
            novel_id=request.novel_id,
            task=compile_task,
            scope="generation_center" if is_world_generation else "world",
            reveal_mode=(
                "author_full"
                if request.operation == "world.map_atlas.generate"
                else "author_safe"
            ),
            retrieval_purpose=(
                "map_atlas"
                if request.operation == "world.map_atlas.generate"
                else "world_generation"
                if is_world_generation
                else "world_fusion"
            ),
            consumer_action=request.operation,
            chapter_index=request.reference_chapter_index,
            scene_id=request.scene_id,
            thread_ids=(
                list(request.thread_ids) if request.thread_ids is not None else None
            ),
            character_ids=(
                list(request.character_ids) if request.character_ids is not None else None
            ),
            entity_ids=(
                list(request.entity_ids) if request.entity_ids is not None else None
            ),
            include_world_synopsis=request.include_world_synopsis,
            selected_world_bible_draft_ids=list(request.selected_world_bible_draft_ids),
            activation_profile_id=request.activation_profile_id,
            activation_profile_version=request.activation_profile_version,
            budget_tokens=request.budget_tokens,
        )

    @staticmethod
    def _context_usage(
        request: GenerationBackgroundRequest,
        options: CompileOptions,
        compiled: CompiledContext,
        *,
        is_world_generation: bool,
    ) -> dict[str, Any]:
        synopsis = next(
            (
                section
                for section in compiled.sections
                if section.key == "world_bible_synopsis"
            ),
            None,
        )
        metadata = dict(synopsis.retrieval_metadata or {}) if synopsis else {}
        total_tokens = sum(section.token_count for section in compiled.sections)
        return {
            "included": bool(compiled.sections),
            "section_key": (
                "generation_background" if is_world_generation else "world_bible_synopsis"
            ),
            "revision_id": metadata.get("revision_id"),
            "source_hash": metadata.get("source_hash"),
            "block_hash": metadata.get("block_hash"),
            "token_count": (
                total_tokens
                if is_world_generation
                else (synopsis.token_count if synopsis else 0)
            ),
            "stale": bool(metadata.get("stale")),
            "fallback": bool(metadata.get("fallback")),
            "status": (
                "included"
                if compiled.sections
                else "not_requested"
                if not request.include_world_synopsis
                else "unavailable"
            ),
            "warnings": list(compiled.warnings),
            "activation_profile_id": options.activation_profile_id,
            "activation_profile_version": options.activation_profile_version,
            "activation_rule_hash": options.activation_profile_rule_hash,
            "activation_source_hashes": list(options.activation_source_hashes),
        }

    @staticmethod
    def _included_asset_ids(
        compiled: CompiledContext,
        options: CompileOptions,
    ) -> dict[str, list[str]]:
        """Project only assets that influenced or survived the final context.

        Requested working drafts and synopsis revisions are content inputs, so
        they count as included only when their section survived budget
        enforcement.  The resolved activation profile is retained as control
        provenance; target hashes count only when its data section survived.
        """
        retained_sections = {section.key: section for section in compiled.sections}

        def retained_content(section_key: str) -> bool:
            section = retained_sections.get(section_key)
            return bool(
                section
                and section.content.strip()
                and section_key not in compiled.truncated_keys
                and section.truncated_reason is None
            )

        content_owned_section_keys = {
            "world_bible_working_pages",
            "world_bible_synopsis",
            "world_bible_activation",
        }
        included: dict[str, list[str]] = {
            "world_bible_draft": [],
            "world_bible_synopsis_revision": (
                [str(options.world_synopsis_revision_id)]
                if options.world_synopsis_revision_id
                and retained_content("world_bible_synopsis")
                else []
            ),
            "activation_profile": (
                [options.activation_profile_id]
                if options.activation_profile_id
                and options.activation_profile_version is not None
                and options.activation_profile_rule_hash
                else []
            ),
            "activation_target_hash": (
                list(options.activation_included_target_hashes)
                if retained_content("world_bible_activation")
                else []
            ),
        }
        for section in compiled.sections:
            if section.key in content_owned_section_keys and not retained_content(
                section.key
            ):
                continue
            for source in section.sources:
                source_type = str(source.get("type") or "context_source")
                source_id = str(source.get("id") or "").strip()
                if source_id:
                    included.setdefault(source_type, []).append(source_id)
        return {key: list(dict.fromkeys(values)) for key, values in included.items()}

    @staticmethod
    def _included_asset_manifest(
        compiled: CompiledContext,
        *,
        operation: str = "",
    ) -> dict[str, list[dict[str, Any]]]:
        """Project retained source identities with content-sensitive hashes.

        A loader-provided hash is authoritative. Legacy sources fall back to the
        retained section hash, which may refresh extra atlas pages but cannot
        hide a changed source from the update workflow.
        """

        manifest: dict[str, list[dict[str, Any]]] = {}
        seen: set[tuple[str, str]] = set()
        for section in compiled.sections:
            if (
                operation == "world.map_atlas.generate"
                and section.key
                not in {
                    "scene_blueprint",
                    "world_entities",
                    "retrieval_evidence_packs",
                    "world_bible_working_pages",
                }
            ):
                continue
            if not section.content.strip():
                continue
            if section.truncated_reason and section.key not in LINE_ITEM_SOURCE_KEYS:
                # Only one-line-per-item sections retain exact provenance after
                # budget truncation. Wrapped JSON/summary sections fail closed.
                continue
            section_hash = hashlib.sha256(section.content.encode("utf-8")).hexdigest()
            for source in section.sources:
                source_type = str(source.get("type") or "context_source").strip()
                source_id = str(source.get("id") or "").strip()
                source_status = str(source.get("status") or section.status)
                identity = (source_type, source_id)
                if (
                    not source_type
                    or not source_id
                    or source_status == "system"
                    or identity in seen
                ):
                    continue
                source_hash = str(source.get("source_hash") or "").strip()
                if len(source_hash) != 64:
                    source_hash = hashlib.sha256(
                        json.dumps(
                            {"section_hash": section_hash, "source": source},
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                            default=str,
                        ).encode("utf-8")
                    ).hexdigest()
                entry: dict[str, Any] = {
                    "source_id": source_id,
                    "source_hash": source_hash,
                    "status": source_status,
                    "label": str(source.get("label") or source_id)[:80],
                }
                if source.get("summary"):
                    entry["summary"] = str(source["summary"])[:1000]
                for source_field in ("chapter_index", "scene_id"):
                    if source.get(source_field) is not None:
                        entry[source_field] = str(source[source_field])
                manifest.setdefault(source_type, []).append(entry)
                seen.add(identity)
        return manifest

    @staticmethod
    def _snapshot_request(
        request: GenerationBackgroundRequest,
        options: CompileOptions,
        compiled: CompiledContext,
        *,
        rendered: str,
        usage: dict[str, Any],
        included_asset_ids: dict[str, list[str]],
        normalized_focus: str,
    ) -> ContextSnapshotRequest:
        section_metadata = {
            section.key: {
                "tier": int(section.tier),
                "status": section.status,
                "token_count": section.token_count,
                "source_count": len(section.sources),
                "retrieval_metadata": dict(section.retrieval_metadata or {}),
                "truncated_reason": section.truncated_reason,
            }
            for section in compiled.sections
        }
        actual_included = {
            key: list(values) for key, values in included_asset_ids.items()
        }
        return ContextSnapshotRequest(
            novel_id=request.novel_id,
            phase="generation_background",
            operation=request.operation,
            context_mode="canonical",
            include_pending_objects=False,
            prompt_name=request.prompt_name,
            model=request.model,
            compile_options={
                "novel_id": options.novel_id,
                "task": request.task,
                "focus_hash": (
                    hashlib.sha256(normalized_focus.encode("utf-8")).hexdigest()
                    if normalized_focus
                    else None
                ),
                "scope": options.scope,
                "reveal_mode": options.reveal_mode,
                "retrieval_purpose": options.retrieval_purpose,
                "consumer_action": options.consumer_action,
                "reference_chapter_index": request.reference_chapter_index,
                "effective_chapter_index": options.chapter_index,
                "scene_id": options.scene_id,
                "requested_thread_ids": list(options.thread_ids or []),
                "requested_character_ids": list(options.character_ids or []),
                "requested_entity_ids": list(options.entity_ids or []),
                "source_snapshot": dict(request.source_snapshot),
                "budget_tokens": options.budget_tokens,
                "include_world_synopsis": options.include_world_synopsis,
                "selected_world_bible_draft_ids": list(
                    options.selected_world_bible_draft_ids
                ),
                "world_synopsis_revision_id": options.world_synopsis_revision_id,
                "world_synopsis_source_hash": options.world_synopsis_source_hash,
                "world_synopsis_block_hash": options.world_synopsis_block_hash,
                "activation_profile_id": options.activation_profile_id,
                "activation_profile_version": options.activation_profile_version,
                "activation_profile_rule_hash": options.activation_profile_rule_hash,
                "activation_source_hashes": list(options.activation_source_hashes),
                "activation_included_target_hashes": list(
                    options.activation_included_target_hashes
                ),
            },
            included_asset_ids=included_asset_ids,
            context_summary={
                "section_keys": [section.key for section in compiled.sections],
                "warning_count": len(compiled.warnings),
                "warnings": list(compiled.warnings),
                "evicted_keys": list(compiled.evicted_keys),
                "truncated_keys": list(compiled.truncated_keys),
                "budget_events": [
                    item.model_dump(mode="json") for item in compiled.budget_events
                ],
                "actual_included_asset_ids": actual_included,
                "generation_selection": dict(compiled.selection_trace),
                "synopsis": deepcopy(usage),
                "activation": dict(compiled.activation_trace),
            },
            section_metadata=section_metadata,
            token_metadata={
                "budget_tokens": options.budget_tokens,
                "used_tokens": sum(section.token_count for section in compiled.sections),
            },
            rendered_context=rendered,
        )


__all__ = [
    "GenerationBackgroundRequest",
    "GenerationBackgroundService",
]
