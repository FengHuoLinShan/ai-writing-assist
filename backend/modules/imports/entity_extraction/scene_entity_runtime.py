"""Typed runtime interfaces for Phase 2 entity extraction strategies."""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Any, Protocol


class SceneEntityExtractionRuntime(Protocol):
    """Methods consumed by Phase 2 extraction strategy helpers."""

    def _entity_key(self, entity_type: str, name: str) -> tuple[str, str]: ...

    def _scene_id(self, scene: dict[str, Any]) -> str | None: ...

    def _scene_provenance_key(
        self,
        workflow_id: str | None,
        scene: dict[str, Any],
    ) -> str | None: ...

    def _scene_source_chapter_index(self, scene: dict[str, Any]) -> int | None: ...

    def _build_memory_context(self, accumulated_memory: list[dict]) -> str: ...

    def _parallel_scene_memory_context(
        self,
        scene: dict[str, Any],
        scene_idx: int,
    ) -> str: ...

    def _bulk_entity_memory_context(self, scenes: list[dict[str, Any]]) -> str: ...

    def _fallback_entity_label(self, entity_type: str) -> str: ...

    def _error_kind(self, exc: Exception) -> str: ...

    def _phase2_scene_llm_timeout_seconds(self) -> float: ...

    def _small_sample_chapter_indices(
        self,
        scenes: list[dict[str, Any]],
    ) -> list[int]: ...

    def _result_ref_ids(
        self,
        result_refs: list[dict[str, str]],
        result_type: str,
    ) -> list[str]: ...

    def _append_extracted_entities_to_context(
        self,
        existing_context: str,
        extraction: Any,
    ) -> str: ...

    def _merge_alias_relation_result(
        self,
        base: dict[str, Any],
        alias_result: dict[str, Any],
    ) -> dict[str, Any]: ...

    def _phase2_audit_summary(
        self,
        db: Any,
        novel_id: str,
        workflow_id: str | None,
    ) -> Awaitable[dict[str, Any]]: ...

    def _phase2_snapshot_health_summary(
        self,
        db: Any,
        novel_id: str,
        workflow_id: str | None,
    ) -> Awaitable[dict[str, Any]]: ...

    def _load_scene_chapters(self, db: Any, scene: dict[str, Any]) -> Awaitable[str]: ...

    def _load_small_sample_chapters_text(
        self,
        db: Any,
        scenes: list[dict[str, Any]],
    ) -> Awaitable[str]: ...

    def _create_phase2_snapshot(self, *args: Any, **kwargs: Any) -> Awaitable[Any]: ...

    def _prepare_import_context_activation(
        self,
        *args: Any,
        **kwargs: Any,
    ) -> Awaitable[Any]: ...

    def _create_phase2b_snapshot(self, *args: Any, **kwargs: Any) -> Awaitable[Any]: ...

    def _call_llm_extraction(self, *args: Any, **kwargs: Any) -> Awaitable[Any]: ...

    def _call_bulk_llm_extractions(
        self,
        *args: Any,
        **kwargs: Any,
    ) -> Awaitable[Any]: ...

    def _call_alias_relation_extraction(
        self,
        *args: Any,
        **kwargs: Any,
    ) -> Awaitable[Any]: ...

    def _persist_entities(self, *args: Any, **kwargs: Any) -> Awaitable[Any]: ...

    def _persist_relations(self, *args: Any, **kwargs: Any) -> Awaitable[Any]: ...

    def _record_deltas(self, *args: Any, **kwargs: Any) -> Awaitable[Any]: ...

    def _record_map_observation_proposals(
        self, *args: Any, **kwargs: Any
    ) -> Awaitable[Any]: ...

    def _persist_alias_relation_output(
        self,
        *args: Any,
        **kwargs: Any,
    ) -> Awaitable[Any]: ...

    def _build_alias_relation_entity_index(
        self,
        *args: Any,
        **kwargs: Any,
    ) -> Awaitable[str]: ...

    def _run_alias_relation_phase(
        self,
        *args: Any,
        **kwargs: Any,
    ) -> Awaitable[dict[str, Any]]: ...

    def _build_scene_checkpoint(self, *args: Any, **kwargs: Any) -> dict[str, Any]: ...

    def _scene_input_fingerprint(
        self,
        scene: dict[str, Any],
        scene_text: str,
    ) -> str: ...

    def _phase2_flush_with_timeout(
        self,
        *args: Any,
        **kwargs: Any,
    ) -> Awaitable[dict[str, Any]]: ...

    def _supplement_small_sample_entities(
        self,
        *args: Any,
        **kwargs: Any,
    ) -> Awaitable[dict[str, Any]]: ...

    def _supplement_small_sample_entities_with_llm(
        self,
        *args: Any,
        **kwargs: Any,
    ) -> Awaitable[Any]: ...
