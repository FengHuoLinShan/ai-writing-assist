"""Explicit, deterministic adoption of one pending world package."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ConflictError, ValidationError
from modules.project.facade import get_project_context, require_active_project
from modules.world.contracts import PostImportWorldAdoptionResultContract
from modules.world.models import CoreEntity, CreationSuggestion, EntityRelation
from modules.world.schemas import (
    CoreEntityCreate,
    CreationSuggestionCreate,
    CreationSuggestionResponse,
    EntityPromoteRequest,
    EntityRelationCreate,
    WorldAdoptionCoreEntityPayload,
    WorldAdoptionPackageApplyRequest,
    WorldAdoptionPackagePayload,
    WorldAdoptionPackagePreviewResponse,
    WorldAdoptionPackageSaveRequest,
    WorldAdoptionPagePayload,
    WorldAdoptionRelationPayload,
    WorldBiblePageDraftCreate,
    WorldCoreCheckpointPayload,
    WorldCoreCheckpointSaveRequest,
)
from modules.world.services.worldbuilding.suggestion_queue_service import (
    SuggestionQueueService,
)
from modules.world.services.worldbuilding.world_bible_lifecycle_service import (
    WorldBibleLifecycleService,
)


class WorldAdoptionPackageService:
    """Own typed checkpoints and package adoption; convergence itself stays read-only."""

    def __init__(
        self,
        suggestions: SuggestionQueueService | None = None,
        context_marker: (
            Callable[[AsyncSession, str, set[str]], Awaitable[None]] | None
        ) = None,
    ) -> None:
        self._suggestions = suggestions or SuggestionQueueService()
        self._context_marker = context_marker
        self._bible_lifecycle = WorldBibleLifecycleService()

    async def save_checkpoint(
        self, db: AsyncSession, request: WorldCoreCheckpointSaveRequest
    ) -> CreationSuggestionResponse:
        if request.checkpoint.parent_checkpoint_id:
            parent = await self._suggestions._get_suggestion(
                db, request.novel_id, request.checkpoint.parent_checkpoint_id
            )
            if parent.target_type != "world_core_checkpoint":
                raise ValidationError("Checkpoint parent lineage is invalid")
        return await self._suggestions.create(
            db,
            CreationSuggestionCreate(
                novel_id=request.novel_id,
                source_module="world",
                review_group="world_adoption",
                target_type="world_core_checkpoint",
                action_schema="world_core_checkpoint.v1",
                payload_json=request.checkpoint.model_dump(mode="json"),
                evidence_refs_json=[],
                risk_level="low",
            ),
        )

    async def save(
        self,
        db: AsyncSession,
        request: WorldAdoptionPackageSaveRequest,
        *,
        source_module: str = "world",
    ) -> CreationSuggestionResponse:
        return await self._suggestions.create(
            db,
            CreationSuggestionCreate(
                novel_id=request.novel_id,
                source_module=source_module,
                review_group="world_adoption",
                target_type="world_adoption_package",
                action_schema="world_adoption_package.v1",
                payload_json=request.package.model_dump(mode="json"),
                evidence_refs_json=[],
                risk_level="high",
            ),
        )

    async def assemble_post_import(
        self, db, request
    ) -> PostImportWorldAdoptionResultContract:
        """Materialize one review package without changing Phase 2 assets."""
        sources = {item.scene_id: item for item in request.scene_sources}
        manifest = hashlib.sha256(
            json.dumps(
                {
                    "workflow_id": request.workflow_id,
                    "authorization_ref": request.authorization_ref,
                    "scenes": [
                        {
                            "id": item.scene_id,
                            "hash": item.source_hash,
                            "entity_ids": sorted(item.entity_ids),
                            "relation_ids": sorted(item.relation_ids),
                        }
                        for item in sorted(
                            request.scene_sources, key=lambda value: value.scene_id
                        )
                    ],
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        existing = (
            (
                await db.execute(
                    select(CreationSuggestion).where(
                        CreationSuggestion.novel_id == uuid.UUID(request.novel_id),
                        CreationSuggestion.target_type == "world_adoption_package",
                        CreationSuggestion.source_module == "imports",
                    )
                )
            )
            .scalars()
            .all()
        )
        for suggestion in existing:
            payload = (
                suggestion.payload_json
                if isinstance(suggestion.payload_json, dict)
                else {}
            )
            if payload.get("source_manifest_hash") == manifest:
                return PostImportWorldAdoptionResultContract(
                    suggestion_id=str(suggestion.id), created=False
                )

        entity_refs: dict[str, list[dict[str, Any]]] = {}
        relation_refs: dict[str, list[dict[str, Any]]] = {}
        for source in request.scene_sources:
            ref = self._post_import_source_ref(
                source, request.workflow_id, request.authorization_ref
            )
            for entity_id in source.entity_ids:
                entity_refs.setdefault(entity_id, []).append(ref)
            for relation_id in source.relation_ids:
                relation_refs.setdefault(relation_id, []).append(ref)

        entity_ids = self._post_import_ids(entity_refs)
        relation_ids = self._post_import_ids(relation_refs)
        entities = (
            (
                await db.execute(
                    select(CoreEntity).where(
                        CoreEntity.novel_id == uuid.UUID(request.novel_id),
                        CoreEntity.id.in_(entity_ids),
                        CoreEntity.status.in_(("candidate", "canonical")),
                    )
                )
            )
            .scalars()
            .all()
            if entity_ids
            else []
        )
        relations = (
            (
                await db.execute(
                    select(EntityRelation).where(
                        EntityRelation.novel_id == uuid.UUID(request.novel_id),
                        EntityRelation.id.in_(relation_ids),
                        EntityRelation.status.in_(("candidate", "canonical")),
                    )
                )
            )
            .scalars()
            .all()
            if relation_ids
            else []
        )
        if entity_ids - {entity.id for entity in entities}:
            raise ValidationError("Post-import entity result changed before packaging")
        if relation_ids - {relation.id for relation in relations}:
            raise ValidationError("Post-import relation result changed before packaging")
        endpoint_ids = {
            endpoint
            for relation in relations
            for endpoint in (relation.source_id, relation.target_id)
        }
        known_ids = {entity.id for entity in entities}
        missing_endpoint_ids = endpoint_ids - known_ids
        if missing_endpoint_ids:
            endpoints = (
                (
                    await db.execute(
                        select(CoreEntity).where(
                            CoreEntity.novel_id == uuid.UUID(request.novel_id),
                            CoreEntity.id.in_(missing_endpoint_ids),
                            CoreEntity.status.in_(("candidate", "canonical")),
                        )
                    )
                )
                .scalars()
                .all()
            )
            entities.extend(endpoints)
            refs_by_relation = {
                relation.id: relation_refs.get(str(relation.id), [])
                for relation in relations
            }
            for relation in relations:
                for endpoint in (relation.source_id, relation.target_id):
                    key = str(endpoint)
                    if key not in entity_refs:
                        entity_refs[key] = list(refs_by_relation[relation.id])

        items: list[dict[str, Any]] = []
        entity_keys: dict[str, str] = {}
        entity_by_key: dict[str, CoreEntity] = {}
        for entity in sorted(entities, key=lambda value: str(value.id)):
            refs = self._unique_source_refs(entity_refs.get(str(entity.id), []))
            meta = (entity.content_json or {}).get("_meta") or {}
            if (
                meta.get("workflow_id") == request.workflow_id
                and str(meta.get("scene_id") or "") in sources
            ):
                refs = [
                    self._post_import_source_ref(
                        sources[str(meta["scene_id"])],
                        request.workflow_id,
                        request.authorization_ref,
                    )
                ]
            if not refs:
                continue
            key = f"entity-{str(entity.id).replace('-', '')[:24]}"
            entity_keys[str(entity.id)] = key
            entity_by_key[key] = entity
            operation = "existing_ref" if entity.status == "canonical" else "promote"
            item: dict[str, Any] = {
                "item_key": key,
                "kind": "core_entity",
                "disposition": "include",
                "authority_kind": "manuscript_observation",
                "source_refs": refs,
                "payload": {"operation": operation, "entity_id": str(entity.id)},
            }
            if operation == "promote":
                item["baseline"] = {
                    "expected_status": entity.status,
                    "expected_fingerprint": self._fingerprint_hash(
                        self._entity_fingerprint(entity)
                    ),
                }
            items.append(item)

        relation_by_key: dict[str, EntityRelation] = {}
        for relation in sorted(relations, key=lambda value: str(value.id)):
            source_key = entity_keys.get(str(relation.source_id))
            target_key = entity_keys.get(str(relation.target_id))
            if not source_key or not target_key:
                raise ValidationError("Post-import relation endpoint is unavailable")
            refs = self._unique_source_refs(relation_refs.get(str(relation.id), []))
            meta = relation.review_meta or {}
            if (
                meta.get("workflow_id") == request.workflow_id
                and str(meta.get("scene_id") or "") in sources
            ):
                refs = [
                    self._post_import_source_ref(
                        sources[str(meta["scene_id"])],
                        request.workflow_id,
                        request.authorization_ref,
                    )
                ]
            key = f"relation-{str(relation.id).replace('-', '')[:22]}"
            relation_by_key[key] = relation
            payload = {
                "operation": (
                    "promote" if relation.status == "candidate" else "existing_ref"
                ),
                "source_ref": f"local:{source_key}",
                "target_ref": f"local:{target_key}",
                "relation_type": relation.relation_type,
                "description": relation.description,
            }
            payload["relation_id"] = str(relation.id)
            items.append(
                {
                    "item_key": key,
                    "kind": "entity_relation",
                    "disposition": "include",
                    "authority_kind": "manuscript_observation",
                    "source_refs": refs,
                    "payload": payload,
                }
            )
        if len(items) > 31:
            raise ValidationError(
                "Post-import package exceeds 31 assets; batching is required"
            )
        if items:
            page_items = [item for item in items if item["kind"] != "world_bible_page"]
            sections = []
            mappings = []
            for index, item in enumerate(page_items):
                claim = self._post_import_claim(
                    item,
                    entity_by_key=entity_by_key,
                    relation_by_key=relation_by_key,
                )
                section_id = f"claim-{index + 1}"
                sections.append(
                    {
                        "section_id": section_id,
                        "title": "已纳入事实",
                        "body_markdown": claim,
                        "sort_order": index,
                    }
                )
                mappings.append(
                    {
                        "content_key": section_id,
                        "claim": claim,
                        "item_key": item["item_key"],
                        "source_ref": item["source_refs"][0],
                    }
                )
            items.append(
                {
                    "item_key": "world-bible",
                    "kind": "world_bible_page",
                    "disposition": "include",
                    "authority_kind": "generated_bridge",
                    "source_refs": self._unique_source_refs(
                        [item["source_refs"][0] for item in page_items]
                    ),
                    "payload": {
                        "operation": "create",
                        "title": "深度导入设定索引",
                        "page_type": "custom",
                        "sections_json": sections,
                        "linked_asset_refs_json": [
                            {
                                "target_type": "core_entity",
                                "target_id": f"local:{item['item_key']}",
                            }
                            for item in page_items
                            if item["kind"] == "core_entity"
                        ],
                        "claim_mappings": mappings,
                    },
                }
            )
        if not items:
            return PostImportWorldAdoptionResultContract(suggestion_id="", created=False)
        saved = await self.save(
            db,
            WorldAdoptionPackageSaveRequest(
                novel_id=request.novel_id,
                package=WorldAdoptionPackagePayload(
                    schema_version="world_adoption_package.v1",
                    source_manifest_hash=manifest,
                    items=items,
                ),
            ),
            source_module="imports",
        )
        return PostImportWorldAdoptionResultContract(suggestion_id=saved.id, created=True)

    @staticmethod
    def _post_import_source_ref(source, workflow_id, authorization_ref):
        return {
            "source_type": "manuscript",
            "source_id": source.scene_id,
            "source_version": workflow_id,
            "source_hash": source.source_hash,
            "range_start": source.range_start,
            "range_end": source.range_end,
            "scene_id": source.scene_id,
            "workflow_id": workflow_id,
            "authorization_ref": authorization_ref,
        }

    @staticmethod
    def _post_import_ids(refs: dict[str, Any]) -> set[uuid.UUID]:
        try:
            return {uuid.UUID(value) for value in refs}
        except (TypeError, ValueError) as exc:
            raise ValidationError("Post-import result reference is invalid") from exc

    @staticmethod
    def _unique_source_refs(refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        unique: dict[str, dict[str, Any]] = {}
        for ref in refs:
            key = json.dumps(ref, sort_keys=True, separators=(",", ":"))
            unique[key] = ref
        return [unique[key] for key in sorted(unique)]

    @staticmethod
    def _post_import_claim(
        item: dict[str, Any],
        *,
        entity_by_key: dict[str, CoreEntity],
        relation_by_key: dict[str, EntityRelation],
    ) -> str:
        if item["kind"] == "entity_relation":
            relation = relation_by_key[item["item_key"]]
            names = {str(entity.id): entity.name for entity in entity_by_key.values()}
            statement = (
                f"{names[str(relation.source_id)]} —{relation.relation_type}→ "
                f"{names[str(relation.target_id)]}"
            )
            return (
                f"{statement}：{relation.description}"
                if relation.description
                else statement
            )
        entity = entity_by_key[item["item_key"]]
        label = f"{entity.name}（{entity.entity_type}）"
        return f"{label}：{entity.summary}" if entity.summary else label

    async def preview(
        self, db: AsyncSession, novel_id: str, suggestion_id: str
    ) -> WorldAdoptionPackagePreviewResponse:
        suggestion = await self._suggestions._get_pending(db, novel_id, suggestion_id)
        package = self._package(suggestion)
        await self._validate_checkpoint_lineage(db, novel_id, package)
        omissions = self._omissions(package)
        baseline = await self._authoritative_baseline(db, novel_id, package)
        page_diffs = await self._page_diffs(db, novel_id, package)
        baseline["pages"] = page_diffs
        return WorldAdoptionPackagePreviewResponse(
            suggestion=CreationSuggestionResponse.model_validate(suggestion),
            expected_preview_hash=self._preview_hash(package, baseline),
            canon_diff=[*await self._canon_diff(db, novel_id, package), *page_diffs],
            omissions=omissions,
        )

    async def apply(
        self,
        db: AsyncSession,
        novel_id: str,
        suggestion_id: str,
        request: WorldAdoptionPackageApplyRequest,
    ) -> CreationSuggestionResponse:
        pending = await self._suggestions._get_suggestion(db, novel_id, suggestion_id)
        if pending.status == "accepted":
            if pending.target_type != "world_adoption_package":
                raise ValidationError("Suggestion is not a world adoption package")
            accepted_preview_hash = pending.result_ref_json.get("preview_hash")
            if request.expected_preview_hash != accepted_preview_hash:
                raise ConflictError("World adoption package changed; preview again")
            return CreationSuggestionResponse.model_validate(pending)
        if pending.status != "pending":
            raise ConflictError("World adoption package is no longer pending")
        package = self._package(pending)
        await self._validate_checkpoint_lineage(db, novel_id, package)
        authorization_actor = await self._active_owner_actor(db, novel_id)
        baseline = await self._authoritative_baseline(db, novel_id, package)
        baseline["pages"] = await self._page_diffs(
            db, novel_id, package, lock_universe=True, for_update=True
        )
        expected = self._preview_hash(package, baseline)
        if request.expected_preview_hash != expected:
            raise ConflictError("World adoption package changed; preview again")
        omissions = self._omissions(package)
        if omissions:
            raise ValidationError("World adoption package has incomplete source coverage")
        suggestion = await self._suggestions._claim_pending(db, novel_id, suggestion_id)
        locked_baseline = await self._authoritative_baseline(
            db, novel_id, package, for_update=True
        )
        locked_baseline["pages"] = await self._page_diffs(db, novel_id, package)
        if request.expected_preview_hash != self._preview_hash(package, locked_baseline):
            raise ConflictError("World adoption package changed; preview again")
        frozen_canon_diff = await self._canon_diff(db, novel_id, package)
        local_refs: dict[str, str] = {}
        results: list[dict[str, str]] = []
        for item in package.items:
            if item.disposition != "include":
                continue
            if item.kind != "core_entity":
                continue
            payload = WorldAdoptionCoreEntityPayload.model_validate(item.payload)
            if payload.operation == "existing_ref":
                entity = await self._canonical_endpoint(
                    db, novel_id, payload.entity_id or "", for_update=True
                )
                entity_id = str(entity.id)
                await self._attach_entity_provenance(
                    db,
                    novel_id,
                    entity_id,
                    suggestion.id,
                    item,
                    package.source_manifest_hash,
                )
                local_refs[item.item_key] = entity_id
                results.append(
                    {
                        "item_key": item.item_key,
                        "type": "core_entity",
                        "id": entity_id,
                        "action": "existing_ref",
                    }
                )
                continue
            if payload.operation == "promote":
                promoted = await self._suggestions._entities.promote(
                    db,
                    payload.entity_id or "",
                    EntityPromoteRequest(approved_by=authorization_actor),
                    novel_id=novel_id,
                    _from_suggestion_queue=True,
                )
                entity_id = promoted.entity_id
                await self._attach_entity_provenance(
                    db,
                    novel_id,
                    entity_id,
                    suggestion.id,
                    item,
                    package.source_manifest_hash,
                )
            else:
                draft = payload.entity
                assert draft is not None
                entity = await self._suggestions._entities.create(
                    db,
                    novel_id,
                    CoreEntityCreate(
                        entity_type=draft.entity_type,
                        name=draft.name,
                        summary=draft.summary,
                        public_info=draft.public_info,
                        hidden_truth=draft.hidden_truth,
                        content_json=self._entity_content_json(
                            draft.content_json,
                            suggestion.id,
                            item,
                            package.source_manifest_hash,
                        ),
                        status="canonical",
                        created_by="world_adoption_package",
                        approved_by=authorization_actor,
                        importance=draft.importance,
                        importance_level=draft.importance_level,
                        reveal_level=draft.reveal_level,
                        force_create=False,
                    ),
                )
                entity_id = entity.id
            await self._mark_context_changed(db, novel_id, {entity_id})
            local_refs[item.item_key] = entity_id
            results.append(
                {"item_key": item.item_key, "type": "core_entity", "id": entity_id}
            )
        for item in package.items:
            if item.disposition != "include" or item.kind != "entity_relation":
                continue
            payload = WorldAdoptionRelationPayload.model_validate(item.payload)
            source_id = self._resolve_ref(payload.source_ref, local_refs)
            target_id = self._resolve_ref(payload.target_ref, local_refs)
            if payload.operation == "existing_ref":
                relation = await self._canonical_relation(
                    db,
                    novel_id,
                    payload.relation_id or "",
                    source_id,
                    target_id,
                    payload.relation_type,
                    for_update=True,
                )
                relation.review_meta = self._merge_provenance(
                    relation.review_meta,
                    suggestion.id,
                    item,
                    package.source_manifest_hash,
                )
                local_refs[item.item_key] = str(relation.id)
                results.append(
                    {
                        "item_key": item.item_key,
                        "type": "entity_relation",
                        "id": str(relation.id),
                        "action": "existing_ref",
                    }
                )
                continue
            if payload.operation == "promote":
                relation = await self._promote_relation(
                    db,
                    novel_id,
                    payload,
                    source_id,
                    target_id,
                    suggestion.id,
                    item,
                    package.source_manifest_hash,
                )
                local_refs[item.item_key] = str(relation.id)
                results.append(
                    {
                        "item_key": item.item_key,
                        "type": "entity_relation",
                        "id": str(relation.id),
                        "action": "promote",
                    }
                )
                continue
            existing = await self._existing_relation(
                db, novel_id, source_id, target_id, payload.relation_type, for_update=True
            )
            if existing is not None:
                local_refs[item.item_key] = str(existing.id)
                results.append(
                    {
                        "item_key": item.item_key,
                        "type": "entity_relation",
                        "id": str(existing.id),
                        "action": "existing_ref",
                    }
                )
                continue
            relation = await self._suggestions._relations.create(
                db,
                novel_id,
                EntityRelationCreate(
                    source_id=source_id,
                    target_id=target_id,
                    relation_type=payload.relation_type,
                    description=payload.description,
                    status="canonical",
                    review_meta=self._provenance(
                        suggestion.id, item, package.source_manifest_hash
                    ),
                ),
            )
            await self._mark_context_changed(db, novel_id, {source_id, target_id})
            local_refs[item.item_key] = relation.id
            results.append(
                {
                    "item_key": item.item_key,
                    "type": "entity_relation",
                    "id": relation.id,
                }
            )
        page_canon_diff = locked_baseline.get("pages", [])
        for item in package.items:
            if item.disposition != "include" or item.kind != "world_bible_page":
                continue
            payload = WorldAdoptionPagePayload.model_validate(item.payload)
            self._validate_page_claims(package, payload)
            self._validate_page_local_refs(package, payload)
            draft_data = self._page_draft_data(
                novel_id, payload, local_refs, authorization_actor
            )
            await self._bible_lifecycle.preview_package_page(
                db, draft_data, expected_page_version=payload.expected_page_version
            )
            draft = await self._bible_lifecycle.create_draft(db, draft_data)
            actual_impact = await self._bible_lifecycle.preview_publish_impact(
                db, novel_id, draft.id
            )
            page = await self._bible_lifecycle.publish_draft(
                db,
                novel_id,
                draft.id,
                published_by=authorization_actor,
                expected_impact_scope_hash=actual_impact.impact_scope_hash,
            )
            results.append(
                {
                    "item_key": item.item_key,
                    "type": "world_bible_page",
                    "id": page.id,
                    "revision": str(page.version_number),
                }
            )
            for diff in page_canon_diff:
                if diff["item_key"] == item.item_key:
                    diff["published_page_id"] = page.id
                    diff["published_revision"] = page.version_number
        return await self._suggestions._mark_accepted(
            db,
            novel_id=novel_id,
            suggestion=suggestion,
            result_ref={
                "type": "world_adoption_package",
                "id": str(suggestion.id),
                "receipt": "accepted",
                "local_ref_map": local_refs,
                "result_refs": results,
                "canon_diff": [
                    *frozen_canon_diff,
                    *page_canon_diff,
                ],
                "source_manifest_hash": package.source_manifest_hash,
                "preview_hash": request.expected_preview_hash,
                "authorization_actor": authorization_actor,
                "item_provenance": [
                    item.model_dump(mode="json") for item in package.items
                ],
            },
        )

    @staticmethod
    def _package(suggestion) -> WorldAdoptionPackagePayload:
        if suggestion.target_type != "world_adoption_package":
            raise ValidationError("Suggestion is not a world adoption package")
        return WorldAdoptionPackagePayload.model_validate(suggestion.payload_json)

    async def get(
        self, db: AsyncSession, novel_id: str, suggestion_id: str
    ) -> CreationSuggestionResponse:
        suggestion = await self._suggestions._get_suggestion(db, novel_id, suggestion_id)
        if suggestion.target_type not in {
            "world_adoption_package",
            "world_core_checkpoint",
        }:
            raise ValidationError("Suggestion is not a world adoption artifact")
        return CreationSuggestionResponse.model_validate(suggestion)

    async def _validate_checkpoint_lineage(
        self, db: AsyncSession, novel_id: str, package: WorldAdoptionPackagePayload
    ) -> None:
        if not package.checkpoint_suggestion_id:
            return
        checkpoint = await self._suggestions._get_suggestion(
            db, novel_id, package.checkpoint_suggestion_id
        )
        if checkpoint.target_type != "world_core_checkpoint":
            raise ValidationError("Package checkpoint lineage is invalid")
        payload = WorldCoreCheckpointPayload.model_validate(checkpoint.payload_json)
        if payload.source_manifest_hash != package.checkpoint_manifest_hash:
            raise ConflictError("World core checkpoint changed; preview again")

    @staticmethod
    def _resolve_ref(value: Any, local_refs: dict[str, str]) -> str:
        value = str(value or "")
        if value.startswith("local:"):
            value = local_refs.get(value[6:], "")
        if not value:
            raise ValidationError("Package relation references an unavailable item")
        return value

    @staticmethod
    def _omissions(package: WorldAdoptionPackagePayload) -> list[str]:
        included = [item for item in package.items if item.disposition == "include"]
        if not included:
            return ["no_included_items"]
        return [item.item_key for item in included if not item.source_refs]

    async def _canon_diff(self, db, novel_id, package) -> list[dict[str, str]]:
        diff = []
        for item in package.items:
            if item.disposition != "include":
                continue
            if item.kind == "world_bible_page":
                continue
            action = "create"
            if item.kind == "core_entity":
                payload = WorldAdoptionCoreEntityPayload.model_validate(item.payload)
                if payload.operation == "existing_ref":
                    action = "existing_ref"
            if item.kind == "entity_relation":
                payload = WorldAdoptionRelationPayload.model_validate(item.payload)
                if payload.operation in {"promote", "existing_ref"}:
                    action = payload.operation
                if not payload.source_ref.startswith(
                    "local:"
                ) and not payload.target_ref.startswith("local:"):
                    if await self._existing_relation(
                        db,
                        novel_id,
                        payload.source_ref,
                        payload.target_ref,
                        payload.relation_type,
                    ):
                        action = "existing_ref"
            diff.append({"item_key": item.item_key, "kind": item.kind, "action": action})
        return diff

    async def _page_diffs(
        self, db, novel_id, package, *, lock_universe=False, for_update=False
    ):
        diffs = []
        for item in package.items:
            if item.disposition != "include" or item.kind != "world_bible_page":
                continue
            payload = WorldAdoptionPagePayload.model_validate(item.payload)
            self._validate_page_claims(package, payload)
            self._validate_page_local_refs(package, payload)
            impact = await self._bible_lifecycle.preview_package_page(
                db,
                self._page_draft_data(novel_id, payload, {}, None),
                expected_page_version=payload.expected_page_version,
                lock_universe=lock_universe,
                for_update=for_update,
                allow_local_refs=True,
            )
            before = None
            if payload.page_id:
                page = await self._bible_lifecycle._get_page_model(
                    db, novel_id, payload.page_id, for_update=for_update
                )
                before = {
                    "id": str(page.id),
                    "title": page.title,
                    "page_type": page.page_type,
                    "free_text": page.free_text,
                    "sections_json": page.sections_json,
                    "linked_asset_refs_json": page.linked_asset_refs_json,
                    "sort_order": page.sort_order,
                    "template_key": page.template_key,
                    "template_version": page.template_version,
                    "version_number": page.version_number,
                }
            diffs.append(
                {
                    "item_key": item.item_key,
                    "kind": item.kind,
                    "action": payload.operation,
                    "before": before,
                    "after": payload.model_dump(mode="json"),
                    "impact_scope_hash": impact.impact_scope_hash,
                    "omissions": [
                        omission.model_dump(mode="json") for omission in impact.omissions
                    ],
                }
            )
        return diffs

    @staticmethod
    def _page_draft_data(novel_id, payload, local_refs, actor):
        original_refs = payload.linked_asset_refs_json
        rewritten_refs = []
        for ref in original_refs:
            rewritten = dict(ref)
            for field in ("target_id", "id", "source_id"):
                value = rewritten.get(field)
                if isinstance(value, str) and value.startswith("local:"):
                    rewritten[field] = local_refs.get(value[6:], value)
            rewritten_refs.append(rewritten)
        hash_map = {
            WorldBibleLifecycleService._asset_ref_hash(
                old
            ): WorldBibleLifecycleService._asset_ref_hash(new)
            for old, new in zip(original_refs, rewritten_refs, strict=True)
        }
        sections = [section.model_dump(mode="json") for section in payload.sections_json]
        for section in sections:
            section["linked_asset_ref_hashes"] = [
                hash_map.get(
                    str(value).removeprefix("sha256:"),
                    str(value).removeprefix("sha256:"),
                )
                for value in section.get("linked_asset_ref_hashes") or []
            ]
        return WorldBiblePageDraftCreate(
            novel_id=novel_id,
            page_id=payload.page_id,
            title=payload.title,
            page_type=payload.page_type,
            free_text=payload.free_text,
            sections_json=sections,
            linked_asset_refs_json=rewritten_refs,
            sort_order=payload.sort_order,
            template_key=payload.template_key,
            template_version=payload.template_version,
            created_by=actor,
        )

    @staticmethod
    def _validate_page_claims(package, payload):
        blocks = {}
        if payload.free_text and payload.free_text.strip():
            blocks["free_text"] = payload.free_text.strip()
        for section in payload.sections_json:
            if section.projection_policy == "eligible" and section.body_markdown.strip():
                blocks[section.section_id] = section.body_markdown.strip()
            if section.projection_policy == "excluded" and (
                not section.section_id.startswith("author_decisions")
            ):
                raise ValidationError(
                    "Excluded package text must be an author_decisions section"
                )
        included = {
            item.item_key: item for item in package.items if item.disposition == "include"
        }
        seen = set()
        for mapping in payload.claim_mappings:
            if (
                mapping.content_key not in blocks
                or mapping.claim.strip() != blocks[mapping.content_key]
            ):
                raise ValidationError(
                    "World Bible claim mapping does not exactly cover its content block"
                )
            if mapping.content_key in seen:
                raise ValidationError(
                    "World Bible content block has duplicate claim mappings"
                )
            seen.add(mapping.content_key)
            item = included.get(mapping.item_key)
            if (
                item is None
                or item.kind not in {"core_entity", "entity_relation"}
                or mapping.source_ref not in item.source_refs
            ):
                raise ValidationError(
                    "World Bible claim mapping is not adopted package evidence"
                )
        if seen != set(blocks):
            raise ValidationError(
                "Every eligible World Bible content block requires one claim mapping"
            )

    @staticmethod
    def _validate_page_local_refs(package, payload):
        included = {
            item.item_key: item for item in package.items if item.disposition == "include"
        }
        for ref in payload.linked_asset_refs_json:
            local = str(ref.get("target_id") or ref.get("id") or "")
            if not local.startswith("local:"):
                continue
            item = included.get(local[6:])
            if item is None or item.kind not in {"core_entity", "entity_relation"}:
                raise ValidationError(
                    "World Bible local asset ref must name an included asset"
                )

    @staticmethod
    def _preview_hash(
        package: WorldAdoptionPackagePayload, baseline: dict[str, Any]
    ) -> str:
        return hashlib.sha256(
            json.dumps(
                {"package": package.model_dump(mode="json"), "baseline": baseline},
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()

    async def _authoritative_baseline(
        self,
        db: AsyncSession,
        novel_id: str,
        package: WorldAdoptionPackagePayload,
        *,
        for_update: bool = False,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for item in package.items:
            if item.disposition != "include" or item.kind != "core_entity":
                continue
            payload = WorldAdoptionCoreEntityPayload.model_validate(item.payload)
            if payload.operation == "promote":
                result[item.item_key] = await self._promote_baseline(
                    db,
                    novel_id,
                    item.item_key,
                    payload.entity_id or "",
                    item.baseline,
                    for_update,
                )
                continue
            if payload.operation == "existing_ref":
                result[item.item_key] = self._entity_fingerprint(
                    await self._canonical_endpoint(
                        db, novel_id, payload.entity_id or "", for_update
                    )
                )
        for item in package.items:
            if item.disposition != "include" or item.kind != "entity_relation":
                continue
            payload = WorldAdoptionRelationPayload.model_validate(item.payload)
            if payload.operation == "existing_ref":
                source_id = self._package_entity_id(package, payload.source_ref)
                target_id = self._package_entity_id(package, payload.target_ref)
                relation = await self._canonical_relation(
                    db,
                    novel_id,
                    payload.relation_id or "",
                    source_id,
                    target_id,
                    payload.relation_type,
                    for_update=for_update,
                )
                result[item.item_key] = self._relation_fingerprint(relation)
                continue
            if payload.source_ref.startswith("local:") or payload.target_ref.startswith(
                "local:"
            ):
                continue
            source = await self._canonical_endpoint(
                db, novel_id, payload.source_ref, for_update
            )
            target = await self._canonical_endpoint(
                db, novel_id, payload.target_ref, for_update
            )
            relation = await self._existing_relation(
                db,
                novel_id,
                payload.source_ref,
                payload.target_ref,
                payload.relation_type,
                for_update=for_update,
            )
            result[item.item_key] = {
                "source": self._entity_fingerprint(source),
                "target": self._entity_fingerprint(target),
                "existing_relation": self._relation_fingerprint(relation)
                if relation
                else None,
            }
        return result

    async def _promote_baseline(
        self, db, novel_id, item_key, entity_id, baseline, for_update
    ):
        assert baseline is not None
        entity = await self._canonical_or_candidate_entity(
            db, novel_id, entity_id, for_update
        )
        fingerprint = self._entity_fingerprint(entity)
        if entity.status != baseline.expected_status:
            raise ConflictError("Core entity changed; preview again")
        if (
            baseline.expected_fingerprint
            and baseline.expected_fingerprint != self._fingerprint_hash(fingerprint)
        ):
            raise ConflictError("Core entity changed; preview again")
        return fingerprint

    async def _canonical_or_candidate_entity(self, db, novel_id, entity_id, for_update):
        stmt = select(CoreEntity).where(
            CoreEntity.id == uuid.UUID(entity_id),
            CoreEntity.novel_id == uuid.UUID(novel_id),
        )
        if for_update:
            stmt = stmt.with_for_update()
        entity = (await db.execute(stmt)).scalar_one_or_none()
        if entity is None or entity.status not in {"draft", "candidate"}:
            raise ConflictError("Core entity changed; preview again")
        return entity

    async def _canonical_endpoint(self, db, novel_id, entity_id, for_update):
        stmt = select(CoreEntity).where(
            CoreEntity.id == uuid.UUID(entity_id),
            CoreEntity.novel_id == uuid.UUID(novel_id),
            CoreEntity.status == "canonical",
        )
        if for_update:
            stmt = stmt.with_for_update()
        entity = (await db.execute(stmt)).scalar_one_or_none()
        if entity is None:
            raise ConflictError("Relation endpoint changed; preview again")
        return entity

    @staticmethod
    def _entity_fingerprint(entity: CoreEntity) -> dict[str, Any]:
        payload = {
            key: getattr(entity, key)
            for key in (
                "id",
                "status",
                "name",
                "entity_type",
                "summary",
                "public_info",
                "hidden_truth",
                "content_json",
                "importance",
                "importance_level",
                "reveal_level",
                "updated_at",
            )
        }
        payload["id"] = str(payload["id"])
        payload["updated_at"] = (
            payload["updated_at"].isoformat() if payload["updated_at"] else None
        )
        return payload

    @staticmethod
    def _relation_fingerprint(relation: EntityRelation) -> dict[str, Any]:
        return {
            "id": str(relation.id),
            "status": relation.status,
            "description": relation.description,
            "review_meta": relation.review_meta,
            "updated_at": relation.updated_at.isoformat()
            if relation.updated_at
            else None,
        }

    @staticmethod
    def _fingerprint_hash(value: dict[str, Any]) -> str:
        return hashlib.sha256(
            json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    @staticmethod
    def _provenance(package_id, item, source_manifest_hash):
        return {
            "world_adoption": {
                "package_id": str(package_id),
                "item_key": item.item_key,
                "source_refs": [ref.model_dump(mode="json") for ref in item.source_refs],
                "authority_kind": item.authority_kind,
                "source_manifest_hash": source_manifest_hash,
            }
        }

    def _entity_content_json(self, content_json, package_id, item, source_manifest_hash):
        content = dict(content_json or {})
        content["_meta"] = self._merge_provenance(
            content.get("_meta"), package_id, item, source_manifest_hash
        )
        return content

    def _merge_provenance(self, meta, package_id, item, source_manifest_hash):
        result = dict(meta or {})
        adopted = self._provenance(package_id, item, source_manifest_hash)[
            "world_adoption"
        ]
        history = [
            value
            for value in result.get("world_adoptions") or []
            if isinstance(value, dict)
        ]
        identity = (adopted["package_id"], adopted["item_key"])
        if not any(
            (value.get("package_id"), value.get("item_key")) == identity
            for value in history
        ):
            history.append(adopted)
        result["world_adoptions"] = history
        result["world_adoption"] = adopted
        return result

    async def _attach_entity_provenance(
        self,
        db: AsyncSession,
        novel_id: str,
        entity_id: str,
        package_id: object,
        item: object,
        source_manifest_hash: str,
    ) -> None:
        stmt = (
            select(CoreEntity)
            .where(
                CoreEntity.id == uuid.UUID(entity_id),
                CoreEntity.novel_id == uuid.UUID(novel_id),
            )
            .with_for_update()
        )
        entity = (await db.execute(stmt)).scalar_one_or_none()
        if entity is None:
            raise ConflictError("Core entity changed; preview again")
        entity.content_json = self._entity_content_json(
            entity.content_json, package_id, item, source_manifest_hash
        )

    async def _active_owner_actor(self, db, novel_id):
        await require_active_project(db, novel_id)
        project = await get_project_context(db, novel_id)
        if project is None or not project.owner_id:
            raise ConflictError("Active project owner is unavailable")
        return project.owner_id

    async def _existing_relation(
        self,
        db: AsyncSession,
        novel_id: str,
        source_id: str,
        target_id: str,
        relation_type: str,
        *,
        for_update: bool = False,
    ) -> EntityRelation | None:
        stmt = select(EntityRelation).where(
            EntityRelation.novel_id == uuid.UUID(novel_id),
            EntityRelation.source_id == uuid.UUID(str(source_id)),
            EntityRelation.target_id == uuid.UUID(str(target_id)),
            EntityRelation.relation_type == relation_type,
            EntityRelation.status == "canonical",
        )
        if for_update:
            stmt = stmt.with_for_update()
        return (await db.execute(stmt)).scalar_one_or_none()

    async def _canonical_relation(
        self,
        db: AsyncSession,
        novel_id: str,
        relation_id: str,
        source_id: str,
        target_id: str,
        relation_type: str,
        *,
        for_update: bool = False,
    ) -> EntityRelation:
        stmt = select(EntityRelation).where(
            EntityRelation.id == uuid.UUID(relation_id),
            EntityRelation.novel_id == uuid.UUID(novel_id),
            EntityRelation.source_id == uuid.UUID(source_id),
            EntityRelation.target_id == uuid.UUID(target_id),
            EntityRelation.relation_type == relation_type,
            EntityRelation.status == "canonical",
        )
        if for_update:
            stmt = stmt.with_for_update()
        relation = (await db.execute(stmt)).scalar_one_or_none()
        if relation is None:
            raise ConflictError("Canonical relation changed; preview again")
        return relation

    @staticmethod
    def _package_entity_id(package, value: str) -> str:
        if not value.startswith("local:"):
            return value
        key = value[6:]
        for item in package.items:
            if item.item_key != key or item.kind != "core_entity":
                continue
            payload = WorldAdoptionCoreEntityPayload.model_validate(item.payload)
            if payload.entity_id:
                return payload.entity_id
        raise ValidationError("Existing relation endpoint is unavailable")

    async def _promote_relation(
        self, db, novel_id, payload, source_id, target_id, package_id, item, manifest
    ) -> EntityRelation:
        stmt = (
            select(EntityRelation)
            .where(
                EntityRelation.id == uuid.UUID(payload.relation_id or ""),
                EntityRelation.novel_id == uuid.UUID(novel_id),
                EntityRelation.status == "candidate",
                EntityRelation.source_id == uuid.UUID(source_id),
                EntityRelation.target_id == uuid.UUID(target_id),
                EntityRelation.relation_type == payload.relation_type,
            )
            .with_for_update()
        )
        relation = (await db.execute(stmt)).scalar_one_or_none()
        if relation is None:
            raise ConflictError("Candidate relation changed; preview again")
        relation.review_meta = self._merge_provenance(
            relation.review_meta, package_id, item, manifest
        )
        relation.status = "canonical"
        await self._mark_context_changed(db, novel_id, {source_id, target_id})
        return relation

    async def _mark_context_changed(
        self, db: AsyncSession, novel_id: str, entity_ids: set[str]
    ) -> None:
        if self._context_marker is not None:
            await self._context_marker(db, novel_id, entity_ids)
            return
        from modules.evidence.facade import mark_asset_context_changed

        for entity_id in sorted(entity_ids):
            await mark_asset_context_changed(
                db,
                novel_id=novel_id,
                asset_type="world_entity",
                asset_id=entity_id,
                reason="world_adoption_package",
            )
