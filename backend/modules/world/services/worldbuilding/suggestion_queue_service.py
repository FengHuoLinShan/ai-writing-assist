"""Worldbuilding creation suggestion queue service."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import NotFoundError
from modules.world.models import (
    CreationSuggestion,
)
from modules.world.schemas import (
    CoreEntityCreate,
    CoreEntityDraftSuggestionPayload,
    CreationSuggestionCreate,
    CreationSuggestionResponse,
    WorldBibleNewPageSuggestionPayload,
    WorldBiblePageCreate,
    WorldBiblePagePatchSuggestionPayload,
    WorldProfileUpsertRequest,
)
from shared.utils import parse_uuid


class SuggestionAlreadyProcessedError(Exception):
    def __init__(self, status: str) -> None:
        self.status = status
        super().__init__(f"suggestion already processed: {status}")


class SuggestionQueueService:
    def __init__(self) -> None:
        from modules.world.services.worldbuilding import worldbuilding_service

        self._profiles = worldbuilding_service.WorldProfileService()
        self._bible = worldbuilding_service.WorldBibleService()
        from modules.world.services.core.entity_service import WorldEntityService

        self._entities = WorldEntityService()

    async def create(
        self,
        db: AsyncSession,
        data: CreationSuggestionCreate,
    ) -> CreationSuggestionResponse:
        payload_json = self._validated_payload_json(
            data.target_type,
            data.payload_json,
        )
        suggestion = CreationSuggestion(
            novel_id=parse_uuid(data.novel_id, "novel_id"),
            source_module=data.source_module,
            review_group=data.review_group,
            target_type=data.target_type,
            action_schema=data.action_schema,
            payload_json=payload_json,
            evidence_refs_json=data.evidence_refs_json,
            risk_level=data.risk_level,
            status=data.status,
        )
        db.add(suggestion)
        await db.flush()
        return CreationSuggestionResponse.model_validate(suggestion)

    async def list(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        source_module: str | None = None,
        review_group: str | None = None,
        risk_level: str | None = None,
        status: str | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list[CreationSuggestionResponse], int]:
        nid = parse_uuid(novel_id, "novel_id")
        stmt = select(CreationSuggestion).where(CreationSuggestion.novel_id == nid)
        if source_module:
            stmt = stmt.where(CreationSuggestion.source_module == source_module)
        if review_group:
            stmt = stmt.where(CreationSuggestion.review_group == review_group)
        if risk_level:
            stmt = stmt.where(CreationSuggestion.risk_level == risk_level)
        if status:
            stmt = stmt.where(CreationSuggestion.status == status)
        total_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await db.execute(total_stmt)).scalar_one()
        result = await db.execute(
            stmt.order_by(CreationSuggestion.created_at.desc()).offset(skip).limit(limit)
        )
        return [
            CreationSuggestionResponse.model_validate(item)
            for item in result.scalars().all()
        ], total

    async def confirm(
        self,
        db: AsyncSession,
        novel_id: str,
        suggestion_id: str,
    ) -> CreationSuggestionResponse:
        suggestion = await self._get_pending(db, novel_id, suggestion_id)
        suggestion.payload_json = self._validated_payload_json(
            suggestion.target_type,
            suggestion.payload_json,
        )
        suggestion = await self._claim_pending(db, novel_id, suggestion_id)
        result_ref: dict[str, Any] = {}
        if suggestion.target_type == "profile_field":
            entity_id = str(suggestion.payload_json.get("entity_id") or "")
            profile_payload = suggestion.payload_json.get("profile") or {}
            profile_payload.setdefault(
                "evidence_refs_json",
                suggestion.evidence_refs_json,
            )
            profile = await self._profiles.upsert_profile(
                db,
                novel_id,
                entity_id,
                WorldProfileUpsertRequest.model_validate(profile_payload),
            )
            result_ref = {"type": "profile", "id": profile.entity_id}
        elif suggestion.target_type == "world_bible_page_patch":
            payload = WorldBiblePagePatchSuggestionPayload.model_validate(
                suggestion.payload_json
            )
            page = await self._bible.apply_page_patch(
                db,
                novel_id,
                payload.page_id,
                payload.append_text,
                revision_reason="ai_suggestion",
            )
            result_ref = {"type": "world_bible_page", "id": page.id}
        elif suggestion.target_type == "world_bible_page":
            payload = WorldBibleNewPageSuggestionPayload.model_validate(
                suggestion.payload_json
            )
            page = await self._bible.create_page(
                db,
                WorldBiblePageCreate(
                    novel_id=novel_id,
                    title=payload.title,
                    page_type=payload.page_type,
                    status="confirmed",
                    free_text=payload.free_text,
                    linked_asset_refs_json=[
                        item.model_dump() for item in payload.source_refs
                    ],
                    created_by="ai_world_bible",
                ),
            )
            result_ref = {"type": "world_bible_page", "id": page.id}
        elif suggestion.target_type == "core_entity_draft":
            payload = CoreEntityDraftSuggestionPayload.model_validate(
                suggestion.payload_json
            )
            content_json = dict(payload.content_json or {})
            meta = dict(content_json.get("_meta") or {})
            meta.setdefault("source", "world_bible_ai_generation")
            meta["source_refs"] = [item.model_dump() for item in payload.source_refs]
            content_json["_meta"] = meta
            entity = await self._entities.create(
                db,
                novel_id,
                CoreEntityCreate(
                    entity_type=payload.entity_type,
                    name=payload.name,
                    summary=payload.summary,
                    public_info=payload.public_info,
                    hidden_truth=payload.hidden_truth,
                    content_json=content_json,
                    importance_level=payload.importance_level,
                    reveal_level=payload.reveal_level,
                    status="draft",
                    created_by="ai_world_bible",
                    force_create=True,
                ),
            )
            result_ref = {"type": "core_entity", "id": entity.id}
        else:
            result_ref = {"type": suggestion.target_type, "accepted_payload": True}
        suggestion.status = "accepted"
        suggestion.result_ref_json = result_ref
        try:
            from modules.context import facade as context_facade

            await context_facade.mark_asset_context_changed(
                db,
                novel_id=novel_id,
                asset_type="worldbuilding",
                asset_id=str(result_ref.get("id") or suggestion.id),
                reason="suggestion_confirmed",
            )
        except Exception:
            # Context invalidation is advisory for v1; the accepted write remains valid.
            pass
        await db.flush()
        return CreationSuggestionResponse.model_validate(suggestion)

    def _validated_payload_json(
        self,
        target_type: str,
        payload_json: dict[str, Any] | None,
    ) -> dict[str, Any]:
        payload = payload_json or {}
        if target_type == "world_bible_page_patch":
            return WorldBiblePagePatchSuggestionPayload.model_validate(
                payload
            ).model_dump(mode="json")
        if target_type == "world_bible_page":
            return WorldBibleNewPageSuggestionPayload.model_validate(
                payload
            ).model_dump(mode="json")
        if target_type == "core_entity_draft":
            return CoreEntityDraftSuggestionPayload.model_validate(payload).model_dump(
                mode="json"
            )
        return payload

    async def reject(
        self,
        db: AsyncSession,
        novel_id: str,
        suggestion_id: str,
    ) -> CreationSuggestionResponse:
        suggestion = await self._get_pending(db, novel_id, suggestion_id)
        suggestion.status = "rejected"
        await db.flush()
        return CreationSuggestionResponse.model_validate(suggestion)

    async def _get_pending(
        self,
        db: AsyncSession,
        novel_id: str,
        suggestion_id: str,
    ) -> CreationSuggestion:
        nid = parse_uuid(novel_id, "novel_id")
        sid = parse_uuid(suggestion_id, "suggestion_id")
        result = await db.execute(
            select(CreationSuggestion).where(
                CreationSuggestion.id == sid,
                CreationSuggestion.novel_id == nid,
            )
        )
        suggestion = result.scalar_one_or_none()
        if suggestion is None:
            raise NotFoundError("Suggestion not found")
        if suggestion.status != "pending":
            raise SuggestionAlreadyProcessedError(suggestion.status)
        return suggestion

    async def _claim_pending(
        self,
        db: AsyncSession,
        novel_id: str,
        suggestion_id: str,
    ) -> CreationSuggestion:
        nid = parse_uuid(novel_id, "novel_id")
        sid = parse_uuid(suggestion_id, "suggestion_id")
        result = await db.execute(
            update(CreationSuggestion)
            .where(
                CreationSuggestion.id == sid,
                CreationSuggestion.novel_id == nid,
                CreationSuggestion.status == "pending",
            )
            .values(status="processing")
        )
        if result.rowcount != 1:
            suggestion = await self._get_suggestion(db, novel_id, suggestion_id)
            raise SuggestionAlreadyProcessedError(suggestion.status)
        suggestion = await self._get_suggestion(db, novel_id, suggestion_id)
        return suggestion

    async def _get_suggestion(
        self,
        db: AsyncSession,
        novel_id: str,
        suggestion_id: str,
    ) -> CreationSuggestion:
        nid = parse_uuid(novel_id, "novel_id")
        sid = parse_uuid(suggestion_id, "suggestion_id")
        result = await db.execute(
            select(CreationSuggestion).where(
                CreationSuggestion.id == sid,
                CreationSuggestion.novel_id == nid,
            )
        )
        suggestion = result.scalar_one_or_none()
        if suggestion is None:
            raise NotFoundError("Suggestion not found")
        return suggestion

__all__ = ['SuggestionAlreadyProcessedError', 'SuggestionQueueService']
