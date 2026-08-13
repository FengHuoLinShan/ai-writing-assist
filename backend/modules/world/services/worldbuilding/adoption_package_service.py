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
from modules.world.models import CoreEntity, EntityRelation
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
    WorldAdoptionRelationPayload,
    WorldCoreCheckpointPayload,
    WorldCoreCheckpointSaveRequest,
)
from modules.world.services.worldbuilding.suggestion_queue_service import (
    SuggestionQueueService,
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
        self, db: AsyncSession, request: WorldAdoptionPackageSaveRequest
    ) -> CreationSuggestionResponse:
        return await self._suggestions.create(
            db,
            CreationSuggestionCreate(
                novel_id=request.novel_id,
                source_module="world",
                review_group="world_adoption",
                target_type="world_adoption_package",
                action_schema="world_adoption_package.v1",
                payload_json=request.package.model_dump(mode="json"),
                evidence_refs_json=[],
                risk_level="high",
            ),
        )

    async def preview(
        self, db: AsyncSession, novel_id: str, suggestion_id: str
    ) -> WorldAdoptionPackagePreviewResponse:
        suggestion = await self._suggestions._get_pending(db, novel_id, suggestion_id)
        package = self._package(suggestion)
        await self._validate_checkpoint_lineage(db, novel_id, package)
        omissions = self._omissions(package)
        baseline = await self._authoritative_baseline(db, novel_id, package)
        return WorldAdoptionPackagePreviewResponse(
            suggestion=CreationSuggestionResponse.model_validate(suggestion),
            expected_preview_hash=self._preview_hash(package, baseline),
            canon_diff=await self._canon_diff(db, novel_id, package),
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
        expected = self._preview_hash(
            package, await self._authoritative_baseline(db, novel_id, package)
        )
        if request.expected_preview_hash != expected:
            raise ConflictError("World adoption package changed; preview again")
        omissions = self._omissions(package)
        if omissions:
            raise ValidationError("World adoption package has incomplete source coverage")
        suggestion = await self._suggestions._claim_pending(db, novel_id, suggestion_id)
        locked_baseline = await self._authoritative_baseline(
            db, novel_id, package, for_update=True
        )
        if request.expected_preview_hash != self._preview_hash(package, locked_baseline):
            raise ConflictError("World adoption package changed; preview again")
        local_refs: dict[str, str] = {}
        results: list[dict[str, str]] = []
        for item in package.items:
            if item.disposition != "include":
                continue
            if item.kind != "core_entity":
                continue
            payload = WorldAdoptionCoreEntityPayload.model_validate(item.payload)
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
            existing = await self._existing_relation(
                db, novel_id, source_id, target_id, payload.relation_type, for_update=True
            )
            if existing is not None:
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
            results.append(
                {
                    "item_key": item.item_key,
                    "type": "entity_relation",
                    "id": relation.id,
                }
            )
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
                "canon_diff": await self._canon_diff(db, novel_id, package),
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
            action = "create"
            if item.kind == "entity_relation":
                payload = WorldAdoptionRelationPayload.model_validate(item.payload)
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
        for item in package.items:
            if item.disposition != "include" or item.kind != "entity_relation":
                continue
            payload = WorldAdoptionRelationPayload.model_validate(item.payload)
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
        meta = dict(content.get("_meta") or {})
        meta.update(self._provenance(package_id, item, source_manifest_hash))
        content["_meta"] = meta
        return content

    async def _attach_entity_provenance(
        self,
        db: AsyncSession,
        novel_id: str,
        entity_id: str,
        package_id: object,
        item: object,
        source_manifest_hash: str,
    ) -> None:
        stmt = select(CoreEntity).where(
            CoreEntity.id == uuid.UUID(entity_id),
            CoreEntity.novel_id == uuid.UUID(novel_id),
        ).with_for_update()
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

    async def _mark_context_changed(
        self, db: AsyncSession, novel_id: str, entity_ids: set[str]
    ) -> None:
        if self._context_marker is not None:
            await self._context_marker(db, novel_id, entity_ids)
            return
        from modules.context.facade import mark_asset_context_changed

        for entity_id in sorted(entity_ids):
            await mark_asset_context_changed(
                db,
                novel_id=novel_id,
                asset_type="world_entity",
                asset_id=entity_id,
                reason="world_adoption_package",
            )
