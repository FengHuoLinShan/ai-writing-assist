"""Task-only transaction boundary for manual alias/relation extraction.

The normal Phase 2/Deep Import path deliberately remains in
``scene_entity_alias_relation.py``.  This workflow exists only for the resumable
``world_alias_relation_extraction`` task: database preparation is checkpointed
before provider I/O, and the validated provider receipt is revalidated before
one atomic persistence transaction.
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.llm.errors import LLMInvalidResponseError
from infrastructure.llm.profiles import resolve_llm_profile
from infrastructure.llm.redaction import redact_diagnostic
from modules.imports.entity_extraction import scene_entity_config as _phase2_config
from modules.imports.entity_extraction.scene_entity_alias_relation import (
    _accepts_keyword,
    _effective_alias_relation_total_timeout_seconds,
    _run_alias_relation_llm_calls,
)
from modules.imports.entity_extraction.scene_entity_phase2b_context import (
    build_phase2b_context_bundle,
    phase2b_scene_input_fingerprint,
)
from modules.imports.llm_schemas import AliasRelationExtractionOutput
from shared.utils import parse_uuid

_VERSION = 2
_ACTION = "world.alias_relations.extract"
_MAX_CONFIRMATION_PAYLOAD_CHARS = 16_000
_MAX_RECEIPT_BYTES = 8 * 1024 * 1024
_MAX_OUTPUT_BYTES = 2 * 1024 * 1024
_MAX_OUTPUT_ITEMS = 10_000
_MAX_OUTPUT_STRING_CHARS = 4_000


class _AliasRelationReceiptScene(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scene_id: str = Field(min_length=1, max_length=128)
    scene_index: int = Field(ge=1)
    input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    context_snapshot_id: str | None = Field(default=None, max_length=128)
    status: Literal["succeeded", "fallback", "failed", "skipped"]
    output: AliasRelationExtractionOutput | None = None
    error_kind: str | None = Field(default=None, max_length=80)
    error: str | None = Field(default=None, max_length=300)

    @field_validator("error", mode="before")
    @classmethod
    def _redact_error(cls, value: Any) -> str | None:
        if value is None or not str(value):
            return None
        return redact_diagnostic(value, limit=300)

    @model_validator(mode="after")
    def _validate_status_payload(self) -> _AliasRelationReceiptScene:
        if self.status in {"succeeded", "fallback"} and self.output is None:
            raise ValueError("successful receipt scene requires output")
        if self.status in {"failed", "skipped"} and self.output is not None:
            raise ValueError("non-success receipt scene cannot contain output")
        if self.status == "succeeded" and (self.error_kind or self.error):
            raise ValueError("successful receipt scene cannot contain an error")
        if self.status in {"fallback", "failed", "skipped"} and not self.error_kind:
            raise ValueError("non-success receipt scene requires error_kind")
        if self.status == "skipped" and self.context_snapshot_id is not None:
            raise ValueError("skipped receipt scene cannot own a context snapshot")
        return self


class _AliasRelationProviderReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[2]
    plan_fingerprint: str = Field(min_length=1, max_length=128)
    elapsed_s: float = Field(ge=0, le=604_800)
    total_timeout_s: float = Field(gt=0, le=604_800)
    concurrency: int = Field(ge=1, le=1_000)
    llm_timeout_s: int = Field(ge=1, le=604_800)
    scenes: list[_AliasRelationReceiptScene] = Field(max_length=10_000)
    receipt_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _require_unique_scenes(self) -> _AliasRelationProviderReceipt:
        scene_ids = [item.scene_id for item in self.scenes]
        if len(scene_ids) != len(set(scene_ids)):
            raise ValueError("provider receipt contains duplicate scene ids")
        return self


def _stable_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _stable_hash(value: Any) -> str:
    payload = value if isinstance(value, str) else _stable_json(value)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _normalized_asset_ids(value: Any) -> dict[str, list[str]]:
    if not isinstance(value, dict):
        raise ValueError("context confirmation asset selection is invalid")
    normalized: dict[str, list[str]] = {}
    for raw_key, raw_items in value.items():
        if not isinstance(raw_items, list):
            raise ValueError("context confirmation asset selection is invalid")
        key = str(raw_key or "").strip()
        if not key:
            raise ValueError("context confirmation asset selection is invalid")
        normalized[key] = sorted(
            dict.fromkeys(str(item).strip() for item in raw_items if str(item).strip())
        )
    return normalized


def _confirmation_payload(
    confirmation: dict[str, Any],
    *,
    novel_id: str,
    confirmation_id: str,
) -> dict[str, Any]:
    """Return the stable authorization/content portion of one confirmation."""
    if not isinstance(confirmation, dict):
        raise ValueError("context confirmation is required")
    if str(confirmation.get("id") or "") != str(confirmation_id):
        raise ValueError("context confirmation id mismatch")
    if str(confirmation.get("novel_id") or "") != str(novel_id):
        raise ValueError("context confirmation novel_id mismatch")
    if str(confirmation.get("action") or "") != _ACTION:
        raise ValueError("context confirmation action mismatch")

    task = str(confirmation.get("task") or "").strip()
    scope = str(confirmation.get("scope") or "").strip()
    context_mode = str(confirmation.get("context_mode") or "").strip()
    compile_options = confirmation.get("compile_options")
    if not task or not scope or not context_mode or not isinstance(compile_options, dict):
        raise ValueError("context confirmation content is incomplete")

    payload = {
        "id": str(confirmation_id),
        "novel_id": str(novel_id),
        "action": _ACTION,
        "task": task,
        "scope": scope,
        "context_mode": context_mode,
        "include_pending_objects": bool(
            confirmation.get("include_pending_objects", False)
        ),
        "selected_asset_ids": _normalized_asset_ids(
            confirmation.get("selected_asset_ids") or {}
        ),
        "excluded_asset_ids": _normalized_asset_ids(
            confirmation.get("excluded_asset_ids") or {}
        ),
        "user_note": str(confirmation.get("user_note") or "").strip() or None,
        "compile_options": compile_options,
        "warnings": [str(item)[:500] for item in (confirmation.get("warnings") or [])],
        "compiled_at": str(confirmation.get("compiled_at") or ""),
    }
    encoded = _stable_json(payload)
    if len(encoded) > _MAX_CONFIRMATION_PAYLOAD_CHARS:
        raise ValueError("context confirmation content exceeds the task limit")
    return payload


def _manifest_without_volatile_ids(manifest: dict[str, Any]) -> dict[str, Any]:
    value = {
        key: item for key, item in manifest.items() if key not in {"plan_fingerprint"}
    }
    value["scenes"] = [
        {key: field for key, field in scene.items() if key != "context_snapshot_id"}
        for scene in manifest.get("scenes") or []
    ]
    return value


def _validate_output_payload(output: Any) -> dict[str, Any]:
    validated = AliasRelationExtractionOutput.model_validate(output)
    if (
        len(validated.aliases) > _MAX_OUTPUT_ITEMS
        or len(validated.relations) > _MAX_OUTPUT_ITEMS
        or len(validated.uncertain_items) > _MAX_OUTPUT_ITEMS
    ):
        raise ValueError("alias/relation output contains too many items")
    payload = validated.model_dump(mode="json")

    def _check_strings(value: Any) -> None:
        if isinstance(value, str) and len(value) > _MAX_OUTPUT_STRING_CHARS:
            raise ValueError("alias/relation output field exceeds the task limit")
        if isinstance(value, dict):
            for item in value.values():
                _check_strings(item)
        elif isinstance(value, list):
            for item in value:
                _check_strings(item)

    _check_strings(payload)
    if len(_stable_json(payload).encode("utf-8")) > _MAX_OUTPUT_BYTES:
        raise ValueError("alias/relation output exceeds the task receipt limit")
    return payload


def _validated_receipt_payload(
    receipt: Any,
    *,
    require_hash: bool,
) -> dict[str, Any]:
    validated = _AliasRelationProviderReceipt.model_validate(receipt)
    payload = validated.model_dump(mode="json", exclude_none=True)
    for scene in payload["scenes"]:
        if "output" in scene:
            scene["output"] = _validate_output_payload(scene["output"])
    supplied_hash = payload.pop("receipt_hash", None)
    expected_hash = _stable_hash(payload)
    if require_hash and supplied_hash != expected_hash:
        raise ValueError("alias/relation provider receipt hash is invalid")
    payload["receipt_hash"] = expected_hash
    if len(_stable_json(payload).encode("utf-8")) > _MAX_RECEIPT_BYTES:
        raise ValueError("alias/relation provider receipt exceeds the task limit")
    return payload


class AliasRelationTaskMixin:
    """Internal three-stage task implementation for the existing world DI seam."""

    async def prepare(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        task_id: str,
        confirmation_id: str,
        confirmation: dict[str, Any],
        start_chapter: int,
        end_chapter: int,
        scene_ids: list[str] | None,
        llm_execution_snapshot: dict[str, Any],
        project_settings: dict[str, Any],
        existing_manifest: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not isinstance(llm_execution_snapshot, dict) or not str(
            llm_execution_snapshot.get("profile_hash") or ""
        ):
            raise ValueError("valid LLM execution snapshot is required")
        profile = resolve_llm_profile(project_settings)
        if not profile.model:
            raise ValueError("valid LLM execution profile is required")

        with _phase2_config.phase2_project_settings_context(
            project_settings,
            novel_id=str(novel_id),
            request_model=profile.model,
        ):
            return await self._prepare_in_context(
                db,
                novel_id=novel_id,
                task_id=task_id,
                confirmation_id=confirmation_id,
                confirmation=confirmation,
                start_chapter=start_chapter,
                end_chapter=end_chapter,
                scene_ids=scene_ids,
                llm_execution_snapshot=llm_execution_snapshot,
                existing_manifest=existing_manifest,
            )

    async def _prepare_in_context(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        task_id: str,
        confirmation_id: str,
        confirmation: dict[str, Any],
        start_chapter: int,
        end_chapter: int,
        scene_ids: list[str] | None,
        llm_execution_snapshot: dict[str, Any],
        existing_manifest: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if existing_manifest is not None and existing_manifest.get("version") != _VERSION:
            raise ValueError(
                "unfinished alias/relation v1 task cannot run with the v2 prompt; "
                "submit the task again"
            )
        if start_chapter < 1 or end_chapter < start_chapter:
            raise ValueError("invalid alias/relation chapter range")
        requested_scene_ids = list(dict.fromkeys(scene_ids or []))
        if any(not str(item).strip() for item in requested_scene_ids):
            raise ValueError("scene_ids must contain non-empty ids")

        nid = parse_uuid(novel_id, "novel_id")
        confirmation_payload = _confirmation_payload(
            confirmation,
            novel_id=novel_id,
            confirmation_id=confirmation_id,
        )
        confirmation_hash = _stable_hash(confirmation_payload)

        all_scenes = await self._get_scenes(db, nid)
        selected: list[dict[str, Any]] = []
        requested = set(requested_scene_ids)
        seen_ids: set[str] = set()
        for scene in all_scenes:
            if str(scene.get("novel_id") or "") != str(novel_id):
                raise ValueError("scene novel_id mismatch")
            scene_id = str(self._scene_id(scene) or "")
            if not scene_id or scene_id in seen_ids:
                raise ValueError("scene identity is missing or duplicated")
            seen_ids.add(scene_id)
            if requested and scene_id not in requested:
                continue
            chapter_index = int(self._scene_source_chapter_index(scene) or 0)
            if chapter_index < start_chapter or chapter_index > end_chapter:
                continue
            selected.append(scene)
        selected_ids = {str(self._scene_id(scene)) for scene in selected}
        if requested and selected_ids != requested:
            missing = sorted(requested - selected_ids)
            raise ValueError(
                f"requested scenes are unavailable: {','.join(missing)[:300]}"
            )

        runtime_scenes: list[dict[str, Any]] = []
        scene_manifest: list[dict[str, Any]] = []
        existing_by_scene = {
            str(item.get("scene_id") or ""): item
            for item in ((existing_manifest or {}).get("scenes") or [])
            if isinstance(item, dict)
        }
        for position, scene in enumerate(selected):
            scene_id = str(self._scene_id(scene))
            activation = await self._prepare_import_context_activation(
                db,
                novel_id=str(novel_id),
                scene_id=scene_id,
            )
            context_bundle = build_phase2b_context_bundle(
                activation,
                novel_id=str(novel_id),
                scene_id=scene_id,
                authorization_scope=confirmation_payload,
            )
            full_text = str(context_bundle["_current_scene_text"])
            scene_index = int(scene.get("scene_index") or position + 1)
            input_fingerprint = phase2b_scene_input_fingerprint(
                scene,
                full_text,
                str(context_bundle["context_fingerprint"]),
            )
            source_refs = list(context_bundle.get("_current_scene_sources") or [])
            included_sources = list(context_bundle.get("_included_sources") or [])
            omitted_sources = list(context_bundle.get("_omitted_sources") or [])
            item = {
                "scene_id": scene_id,
                "scene_index": scene_index,
                "position": position,
                "semantic_fingerprint": _stable_hash(scene),
                "source_text_hash": _stable_hash(full_text),
                "consumed_text_hash": _stable_hash(full_text),
                "input_fingerprint": input_fingerprint,
                "context_fingerprint": context_bundle["context_fingerprint"],
                "activation_context_fingerprint": context_bundle.get(
                    "_activation_context_fingerprint"
                ),
                "prompt_contract_version": (
                    _phase2_config.PHASE2B_PROMPT_CONTRACT_VERSION
                ),
                "source_refs_hash": _stable_hash(source_refs),
                "included_sources_hash": _stable_hash(included_sources),
                "omitted_sources_hash": _stable_hash(omitted_sources),
                "included_entity_refs": sorted(
                    (context_bundle.get("_entity_ref_map") or {}).keys()
                ),
                "included_relation_refs": sorted(
                    (context_bundle.get("_relation_ref_map") or {}).keys()
                ),
                "omitted_source_refs": sorted(
                    str(source.get("prompt_ref"))
                    for source in omitted_sources
                    if isinstance(source, dict) and source.get("prompt_ref")
                ),
                "empty_text": False,
                "context_snapshot_id": None,
            }
            existing_scene = existing_by_scene.get(scene_id)
            if existing_manifest is not None:
                snapshot_id = (
                    str(existing_scene.get("context_snapshot_id") or "")
                    if existing_scene
                    else ""
                )
                if not snapshot_id:
                    raise ValueError("prepared context snapshot is missing")
                item["context_snapshot_id"] = snapshot_id or None
            else:
                snapshot_kwargs: dict[str, Any] = {"workflow_id": task_id}
                if _accepts_keyword(self._create_phase2b_snapshot, "context_bundle"):
                    snapshot_kwargs["context_bundle"] = context_bundle
                snapshot = await self._create_phase2b_snapshot(
                    db,
                    nid,
                    scene,
                    full_text,
                    "",
                    **snapshot_kwargs,
                )
                snapshot_id = str(getattr(snapshot, "id", "") or "")
                if not snapshot_id:
                    raise ValueError("context snapshot persistence failed")
                item["context_snapshot_id"] = snapshot_id

            scene_manifest.append(item)
            runtime_scenes.append(
                {
                    "position": position,
                    "scene": scene,
                    "scene_id": scene_id,
                    "scene_index": scene_index,
                    "chapters_text": full_text,
                    "entity_index": "",
                    "context_bundle": context_bundle,
                    "snapshot_id": item["context_snapshot_id"],
                    "input_fingerprint": item["input_fingerprint"],
                    "retry_count": 0,
                }
            )

        manifest = {
            "version": _VERSION,
            "novel_id": str(novel_id),
            "task_id": str(task_id),
            "confirmation_id": str(confirmation_id),
            "confirmation_fingerprint": confirmation_hash,
            "llm_profile_hash": str(llm_execution_snapshot["profile_hash"]),
            "start_chapter": start_chapter,
            "end_chapter": end_chapter,
            "requested_scene_ids": requested_scene_ids,
            "prompt_contract_version": _phase2_config.PHASE2B_PROMPT_CONTRACT_VERSION,
            "scene_count": len(scene_manifest),
            "scenes": scene_manifest,
        }
        if existing_manifest is not None:
            if _manifest_without_volatile_ids(manifest) != _manifest_without_volatile_ids(
                existing_manifest
            ):
                raise ValueError(
                    "alias/relation inputs changed; discarded stale provider result"
                )
        manifest["plan_fingerprint"] = _stable_hash(manifest)
        if existing_manifest is not None and manifest["plan_fingerprint"] != str(
            existing_manifest.get("plan_fingerprint") or ""
        ):
            raise ValueError("alias/relation prepared snapshot fingerprint mismatch")
        return {
            "manifest": manifest,
            "runtime_plan": {
                "version": _VERSION,
                "plan_fingerprint": manifest["plan_fingerprint"],
                "scenes": runtime_scenes,
            },
        }

    async def execute(
        self,
        *,
        runtime_plan: dict[str, Any],
        project_settings: dict[str, Any],
        novel_id: str,
    ) -> dict[str, Any]:
        """Call providers without accepting a database session."""
        if runtime_plan.get("version") != _VERSION:
            raise ValueError("alias/relation runtime plan version mismatch")
        profile = resolve_llm_profile(project_settings)
        started_at = time.monotonic()
        prepared = [
            item
            for item in (runtime_plan.get("scenes") or [])
            if item.get("chapters_text")
        ]
        with _phase2_config.phase2_project_settings_context(
            project_settings,
            novel_id=str(novel_id),
            request_model=profile.model,
        ):
            concurrency = _phase2_config.phase2_alias_relation_concurrency()
            llm_timeout_s = _phase2_config.phase2_alias_relation_llm_timeout_seconds()
            total_timeout_s = _effective_alias_relation_total_timeout_seconds(
                scene_count=len(runtime_plan.get("scenes") or []),
                concurrency=concurrency,
                configured_timeout_seconds=(
                    _phase2_config.phase2_alias_relation_total_timeout_seconds()
                ),
            )
            results = await _run_alias_relation_llm_calls(
                self,
                prepared,
                started_at=started_at,
                total_timeout_seconds=total_timeout_s,
                concurrency=concurrency,
                llm_timeout_seconds=llm_timeout_s,
            )

        receipt_by_scene: dict[str, dict[str, Any]] = {}
        for item, output, exc in results:
            receipt_item: dict[str, Any] = {
                "scene_id": str(item["scene_id"]),
                "scene_index": int(item["scene_index"]),
                "input_fingerprint": str(item["input_fingerprint"]),
                "context_snapshot_id": item.get("snapshot_id"),
            }
            if exc is None:
                try:
                    receipt_item.update(
                        {
                            "status": "succeeded",
                            "output": _validate_output_payload(output),
                        }
                    )
                except Exception as validation_exc:
                    receipt_item.update(
                        {
                            "status": "failed",
                            "error_kind": "invalid_response",
                            "error": redact_diagnostic(validation_exc, limit=300),
                        }
                    )
            elif isinstance(exc, LLMInvalidResponseError):
                receipt_item.update(
                    {
                        "status": "fallback",
                        "output": {
                            "aliases": [],
                            "relations": [],
                            "uncertain_items": [],
                        },
                        "error_kind": "invalid_response",
                        "error": redact_diagnostic(exc, limit=300),
                    }
                )
            else:
                receipt_item.update(
                    {
                        "status": "failed",
                        "error_kind": self._error_kind(exc),
                        "error": redact_diagnostic(exc, limit=300),
                    }
                )
            receipt_by_scene[receipt_item["scene_id"]] = receipt_item

        receipt_scenes: list[dict[str, Any]] = []
        for item in runtime_plan.get("scenes") or []:
            scene_id = str(item["scene_id"])
            if not item.get("chapters_text"):
                receipt_scenes.append(
                    {
                        "scene_id": scene_id,
                        "scene_index": int(item["scene_index"]),
                        "input_fingerprint": str(item["input_fingerprint"]),
                        "context_snapshot_id": None,
                        "status": "skipped",
                        "error_kind": "empty_scene_text",
                    }
                )
                continue
            if scene_id not in receipt_by_scene:
                raise ValueError("provider receipt is incomplete")
            receipt_scenes.append(receipt_by_scene[scene_id])

        receipt = _validated_receipt_payload(
            {
                "version": _VERSION,
                "plan_fingerprint": str(runtime_plan.get("plan_fingerprint") or ""),
                "elapsed_s": round(time.monotonic() - started_at, 3),
                "total_timeout_s": total_timeout_s,
                "concurrency": concurrency,
                "llm_timeout_s": llm_timeout_s,
                "scenes": receipt_scenes,
            },
            require_hash=False,
        )
        return receipt

    async def finalize(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        task_id: str,
        confirmation_id: str,
        confirmation: dict[str, Any],
        start_chapter: int,
        end_chapter: int,
        scene_ids: list[str] | None,
        llm_execution_snapshot: dict[str, Any],
        project_settings: dict[str, Any],
        manifest: dict[str, Any],
        receipt: dict[str, Any],
    ) -> dict[str, Any]:
        """Revalidate all sources, then stage every domain/result write atomically."""
        recompiled = await self.prepare(
            db,
            novel_id=novel_id,
            task_id=task_id,
            confirmation_id=confirmation_id,
            confirmation=confirmation,
            start_chapter=start_chapter,
            end_chapter=end_chapter,
            scene_ids=scene_ids,
            llm_execution_snapshot=llm_execution_snapshot,
            project_settings=project_settings,
            existing_manifest=manifest,
        )
        runtime_by_scene = {
            str(item["scene_id"]): item
            for item in recompiled["runtime_plan"].get("scenes") or []
        }
        receipt = _validated_receipt_payload(receipt, require_hash=True)
        if str(receipt.get("plan_fingerprint") or "") != str(
            manifest.get("plan_fingerprint") or ""
        ):
            raise ValueError("alias/relation provider receipt is invalid")

        manifest_by_scene = {
            str(item["scene_id"]): item for item in manifest.get("scenes") or []
        }
        receipt_scenes = receipt.get("scenes")
        if not isinstance(receipt_scenes, list) or {
            str(item.get("scene_id") or "")
            for item in receipt_scenes
            if isinstance(item, dict)
        } != set(manifest_by_scene):
            raise ValueError("alias/relation provider receipt scene set mismatch")

        from modules.context.facade import (
            fail_context_snapshot,
            succeed_context_snapshot,
        )

        total_aliases = 0
        total_relations = 0
        total_uncertain = 0
        uncertain_diagnostics: list[dict[str, Any]] = []
        completed = 0
        skipped = 0
        failed: list[int] = []
        fallback: list[int] = []
        checkpoints: list[dict[str, Any]] = []
        result_refs: list[dict[str, str]] = []
        for receipt_item in receipt_scenes:
            scene_id = str(receipt_item.get("scene_id") or "")
            source = manifest_by_scene[scene_id]
            runtime_source = runtime_by_scene.get(scene_id)
            if runtime_source is None:
                raise ValueError("alias/relation recompiled runtime source is missing")
            if str(receipt_item.get("input_fingerprint") or "") != str(
                source.get("input_fingerprint") or ""
            ) or receipt_item.get("context_snapshot_id") != source.get(
                "context_snapshot_id"
            ):
                raise ValueError("alias/relation provider receipt source mismatch")
            scene_index = int(source["scene_index"])
            status = str(receipt_item.get("status") or "")
            checkpoint = {
                "scene_id": scene_id,
                "scene_index": scene_index,
                "position": int(source["position"]),
                "retry_count": 0,
                "source": "manual_alias_relation_task",
                "auto_ingested": True,
                "input_fingerprint": source["input_fingerprint"],
                "aliases": 0,
                "relations": 0,
                "uncertain_items": 0,
                "fallback": status == "fallback",
            }
            snapshot_id = source.get("context_snapshot_id")
            if status == "skipped":
                skipped += 1
                checkpoint.update({"status": "skipped", "error_kind": "empty_scene_text"})
            elif status in {"succeeded", "fallback"}:
                output = AliasRelationExtractionOutput.model_validate(
                    receipt_item.get("output")
                )
                if status == "succeeded":
                    scene_result_refs: list[dict[str, str]] = []
                    persist_kwargs: dict[str, Any] = {
                        "scene_index": scene_index,
                        "workflow_id": task_id,
                        "scene_id": scene_id,
                        "result_refs": scene_result_refs,
                        "strict": True,
                        "context_bundle": runtime_source.get("context_bundle"),
                        "current_scene_text": runtime_source.get("chapters_text"),
                    }
                    if _accepts_keyword(
                        self._persist_alias_relation_output,
                        "context_snapshot_id",
                    ):
                        persist_kwargs["context_snapshot_id"] = snapshot_id
                    persisted = await self._persist_alias_relation_output(
                        db,
                        novel_id,
                        output,
                        **persist_kwargs,
                    )
                    result_refs.extend(scene_result_refs)
                    total_aliases += int(persisted["aliases"])
                    total_relations += int(persisted["relations"])
                    total_uncertain += int(persisted.get("uncertain_count", 0) or 0)
                    uncertain_diagnostics.extend(persisted.get("diagnostics") or [])
                    completed += 1
                    checkpoint.update(
                        {
                            "status": "done",
                            "aliases": int(persisted["aliases"]),
                            "relations": int(persisted["relations"]),
                            "uncertain_items": int(
                                persisted.get("uncertain_count", 0) or 0
                            ),
                        }
                    )
                    if snapshot_id:
                        await succeed_context_snapshot(
                            db,
                            snapshot_id=str(snapshot_id),
                            result_refs=scene_result_refs,
                        )
                else:
                    completed += 1
                    fallback.append(scene_index)
                    checkpoint.update(
                        {
                            "status": "done",
                            "error_kind": "invalid_response",
                            "error": str(receipt_item.get("error") or "")[:300],
                        }
                    )
                    if snapshot_id:
                        await fail_context_snapshot(
                            db,
                            snapshot_id=str(snapshot_id),
                            error_kind="invalid_response",
                            error_message=str(receipt_item.get("error") or "")[:300],
                        )
            elif status == "failed":
                failed.append(scene_index)
                error_kind = str(receipt_item.get("error_kind") or "provider_error")
                error = str(receipt_item.get("error") or "")[:300]
                checkpoint.update(
                    {"status": "failed", "error_kind": error_kind, "error": error}
                )
                if snapshot_id:
                    await fail_context_snapshot(
                        db,
                        snapshot_id=str(snapshot_id),
                        error_kind=error_kind,
                        error_message=error,
                    )
            else:
                raise ValueError("alias/relation provider receipt status is invalid")
            checkpoints.append(checkpoint)

        return {
            "summary": {
                "total_aliases": total_aliases,
                "total_relations": total_relations,
                "total_uncertain_items": total_uncertain,
                "total_scenes": len(manifest_by_scene),
                "alias_relation_scenes": completed,
                "alias_relation_failed_scenes": failed,
                "alias_relation_skipped_scenes": skipped,
                "alias_relation_rerun_scenes": 0,
                "alias_relation_fallback_scenes": fallback,
                "degraded": bool(failed),
                "error_kind": "provider_error" if failed else None,
                "error_message": None,
                "alias_relation_elapsed_s": float(receipt.get("elapsed_s") or 0),
                "alias_relation_total_timeout_s": float(receipt["total_timeout_s"]),
                "alias_relation_concurrency": int(receipt["concurrency"]),
                "alias_relation_llm_timeout_s": int(receipt["llm_timeout_s"]),
                "alias_relation_format_diagnostics": [],
                "alias_relation_uncertain_diagnostics": uncertain_diagnostics,
                "alias_relation_checkpoints": {"phase2b": {"scenes": checkpoints}},
            },
            "result_refs": result_refs,
        }


class AliasRelationTaskWorkflow(AliasRelationTaskMixin):
    """Compatibility adapter for the former owner-bound workflow."""

    def __init__(self, service: Any) -> None:
        self.service = service

    def __getattr__(self, name):
        return getattr(self.service, name)
