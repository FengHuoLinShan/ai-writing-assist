"""Worldbuilding creation suggestion queue service."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ConflictError, NotFoundError, ValidationError
from core.logging_context import (
    exception_summary_for_log,
    identifier_for_log,
    novel_id_for_log,
)
from modules.world.models import (
    CreationSuggestion,
    WorldBiblePage,
    WorldBiblePageDraft,
)
from modules.world.schemas import (
    AskWorldSaveRequest,
    AskWorldSaveResponse,
    CoreEntityCreate,
    CoreEntityDraftSuggestionPayload,
    CoreEntityResponse,
    CoreEntitySuggestionEditConfirmRequest,
    CoreEntityUpdate,
    CreationSuggestionCreate,
    CreationSuggestionResponse,
    CreationSuggestionRevisionLink,
    EntityAliasSuggestionPayload,
    EntityMergeRequest,
    EntityPromoteRequest,
    EntityRelationCreate,
    EntityRelationSuggestionPayload,
    EntityResolveAsAliasRequest,
    WorldAdoptionPackagePayload,
    WorldBiblePageDraftCreate,
    WorldBiblePageDraftSuggestionPayload,
    WorldBiblePageDraftUpdate,
    WorldBiblePageProposalContent,
    WorldBibleSourceRef,
    WorldCoreCheckpointPayload,
    WorldGenerationApplyPageDraftRequest,
    WorldGenerationApplyPageDraftResponse,
    WorldProfileUpsertRequest,
)
from shared.utils import parse_uuid

logger = logging.getLogger(__name__)


class SuggestionAlreadyProcessedError(Exception):
    def __init__(self, status: str) -> None:
        self.status = status
        super().__init__(f"suggestion already processed: {status}")


class SuggestionQueueService:
    def __init__(self, *, entity_service: Any | None = None) -> None:
        from modules.world.services.worldbuilding import worldbuilding_service

        self._profiles = worldbuilding_service.WorldProfileService()
        self._bible = worldbuilding_service.WorldBibleService()
        self._lifecycle = worldbuilding_service.WorldBibleLifecycleService()
        from modules.world.services.core.entity_alias_service import EntityAliasService
        from modules.world.services.core.entity_relation_service import (
            EntityRelationService,
        )
        from modules.world.services.core.entity_service import WorldEntityService

        self._entities = entity_service or WorldEntityService()
        self._relations = EntityRelationService()
        self._aliases = EntityAliasService()

    async def create_core_entity_suggestion(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        source_module: str,
        review_group: str,
        payload: CoreEntityDraftSuggestionPayload,
        evidence_refs_json: list[dict[str, Any]] | None = None,
        risk_level: str = "medium",
        compatibility_status: str | None = None,
        compatibility_created_by: str | None = None,
        action_schema: str = "v1",
    ) -> tuple[CreationSuggestionResponse, CoreEntityResponse | None]:
        """Create the authoritative suggestion and an optional legacy read shadow.

        New AI entry points call this method instead of writing ``CoreEntity``
        directly.  ``compatibility_status`` keeps old API/read contracts working
        while the queue remains the owner of adoption.  Confirmation promotes
        that same shadow, so no second entity is created.
        """
        from modules.world.services.core.entity_types import (
            normalize_system_entity_type,
        )

        payload = payload.model_copy(
            update={
                "entity_type": normalize_system_entity_type(payload.entity_type),
            }
        )
        if compatibility_status not in {None, "draft", "candidate"}:
            raise ValidationError(
                "compatibility_status must be draft or candidate for a pending "
                "core entity suggestion"
            )
        evidence_refs = list(evidence_refs_json or [])
        suggestion = await self.create(
            db,
            CreationSuggestionCreate(
                novel_id=novel_id,
                source_module=source_module,
                review_group=review_group,
                target_type="core_entity_draft",
                action_schema=action_schema,
                payload_json=payload.model_dump(mode="json"),
                evidence_refs_json=evidence_refs,
                risk_level=risk_level,
            ),
        )
        if compatibility_status is None:
            return suggestion, None

        content_json = dict(payload.content_json or {})
        meta = dict(content_json.get("_meta") or {})
        meta.setdefault("source", source_module)
        meta["suggestion_id"] = suggestion.id
        meta["review_group"] = review_group
        meta["source_refs"] = [item.model_dump() for item in payload.source_refs]
        meta["evidence_refs"] = evidence_refs
        meta["needs_review"] = True
        meta["compatibility_shadow"] = True
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
                importance=payload.importance,
                importance_level=payload.importance_level,
                reveal_level=payload.reveal_level,
                status=compatibility_status,
                created_by=compatibility_created_by or f"ai_{source_module}",
                force_create=True,
            ),
        )

        stored = await self._get_suggestion(db, novel_id, suggestion.id)
        stored.result_ref_json = {
            "type": "core_entity_compatibility",
            "id": entity.id,
            "status": "pending",
        }
        await db.flush()
        return CreationSuggestionResponse.model_validate(stored), entity

    async def create(
        self,
        db: AsyncSession,
        data: CreationSuggestionCreate,
    ) -> CreationSuggestionResponse:
        payload_json = self._validated_payload_json(
            data.target_type,
            data.payload_json,
        )
        if data.target_type in {"core_entity", "core_entity_draft"}:
            from modules.world.services.core.entity_types import (
                normalize_system_entity_type,
            )

            payload_json["entity_type"] = normalize_system_entity_type(
                payload_json["entity_type"]
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

    async def save_ask_world_answer(
        self,
        db: AsyncSession,
        data: AskWorldSaveRequest,
    ) -> AskWorldSaveResponse:
        """Save one author-requested answer as a reviewable new-page suggestion."""
        from modules.world.services.worldbuilding.ask_world_service import AskWorldService

        ask_world = AskWorldService()
        expected = ask_world.response_hash(
            data.question,
            data.answer,
            data.claims,
            data.uncertainty,
            data.citations,
        )
        if expected != data.response_hash:
            raise ConflictError("Ask World answer changed before it was saved")
        for citation in data.citations:
            opened = await ask_world.open_citation(db, data.novel_id, citation)
            if opened.status != "current":
                raise ConflictError("Ask World citation changed before it was saved")

        citations_by_key = {item.citation_key: item for item in data.citations}
        lines = [data.answer.strip()]
        for claim in data.claims:
            titles = [citations_by_key[key].title for key in claim.citation_keys]
            lines.append(f"- {claim.text}（来源：{'、'.join(titles)}）")
        if data.uncertainty.strip():
            lines.append(f"仍需核对：{data.uncertainty.strip()}")
        source_refs = [self._ask_world_source_ref(item) for item in data.citations]
        payload = WorldBiblePageDraftSuggestionPayload(
            operation="create_new",
            page=WorldBiblePageProposalContent(
                title=f"问世界：{data.question.strip()[:240]}",
                page_type="custom",
                free_text="\n\n".join(lines)[:30_000],
            ),
            design_rationale="作者主动把只读问答保存为待处理世界书建议。",
            review_notes=[
                "回答尚未写入正式世界书；请编辑并应用到工作稿后再决定是否发布。"
            ],
            source_refs=source_refs,
        )
        suggestion = await self.create(
            db,
            CreationSuggestionCreate(
                novel_id=data.novel_id,
                source_module="world",
                review_group="generation_center",
                target_type="world_bible_page_draft",
                action_schema="ask_world.page_draft.v1",
                payload_json=payload.model_dump(mode="json"),
                evidence_refs_json=[item.model_dump(mode="json") for item in source_refs],
                risk_level="low",
            ),
        )
        return AskWorldSaveResponse(suggestion=suggestion)

    @staticmethod
    def _ask_world_source_ref(citation) -> WorldBibleSourceRef:
        if citation.kind == "world_bible_page":
            return WorldBibleSourceRef(
                source_type="world_bible_page",
                source_id=citation.page_id,
                source_version=citation.source_version,
                source_hash=citation.source_hash,
                page_id=citation.page_id,
                title=citation.title,
            )
        if citation.kind == "manuscript":
            return WorldBibleSourceRef(
                source_type="writing_chapter",
                source_id=str((citation.source_ref or {}).get("draft_id") or "") or None,
                source_version=citation.source_version,
                source_hash=citation.source_hash,
                chapter_index=citation.chapter_index,
                title=citation.title,
            )
        return WorldBibleSourceRef(
            source_type="core_entity",
            source_id=str((citation.target_ref or {}).get("target_id") or "") or None,
            source_hash=citation.source_hash,
            title=citation.title,
        )

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

    async def require_generation_revision_parent(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        suggestion_id: str,
    ) -> CreationSuggestionResponse:
        try:
            suggestion = await self._get_pending(db, novel_id, suggestion_id)
        except SuggestionAlreadyProcessedError as exc:
            raise ConflictError(
                "The suggestion selected for revision is no longer pending"
            ) from exc
        if (
            suggestion.source_module != "world"
            or suggestion.review_group != "generation_center"
        ):
            raise ValidationError(
                "Only generation-center suggestions can be revised in this workflow"
            )
        response = CreationSuggestionResponse.model_validate(suggestion)
        if response.revision_link and response.revision_link.successor_suggestion_id:
            raise ConflictError("The suggestion already has a newer revision")
        return response

    async def supersede_generation_suggestion(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        predecessor_suggestion_id: str,
        successor_suggestion_id: str,
    ) -> CreationSuggestionResponse:
        try:
            predecessor = await self._claim_pending(
                db,
                novel_id,
                predecessor_suggestion_id,
            )
        except SuggestionAlreadyProcessedError as exc:
            raise ConflictError(
                "The suggestion selected for revision is no longer pending"
            ) from exc
        successor = await self._get_pending(db, novel_id, successor_suggestion_id)
        if (
            predecessor.source_module != "world"
            or predecessor.review_group != "generation_center"
            or successor.source_module != "world"
            or successor.review_group != "generation_center"
        ):
            raise ValidationError(
                "Only generation-center suggestions can participate in revisions"
            )
        predecessor_link = self._revision_link(predecessor.result_ref_json)
        successor_link = self._revision_link(successor.result_ref_json)
        if predecessor_link and predecessor_link.successor_suggestion_id:
            raise ConflictError("The suggestion already has a newer revision")
        if successor_link and successor_link.predecessor_suggestion_id:
            raise ConflictError("The new suggestion is already linked to a revision")

        compatibility_ref = await self._archive_compatibility_shadow(
            db,
            novel_id=novel_id,
            suggestion=predecessor,
        )
        predecessor.result_ref_json = self._with_revision_link(
            compatibility_ref or dict(predecessor.result_ref_json or {}),
            predecessor=predecessor_link.predecessor_suggestion_id
            if predecessor_link
            else None,
            successor=str(successor.id),
        )
        successor.result_ref_json = self._with_revision_link(
            dict(successor.result_ref_json or {}),
            predecessor=str(predecessor.id),
            successor=successor_link.successor_suggestion_id if successor_link else None,
        )
        predecessor.status = "rejected"
        await db.flush()
        return CreationSuggestionResponse.model_validate(successor)

    async def confirm(
        self,
        db: AsyncSession,
        novel_id: str,
        suggestion_id: str,
        *,
        core_entity_changes: CoreEntitySuggestionEditConfirmRequest | None = None,
    ) -> CreationSuggestionResponse:
        suggestion = await self._get_pending(db, novel_id, suggestion_id)
        payload_json = self._validated_payload_json(
            suggestion.target_type,
            suggestion.payload_json,
        )
        if core_entity_changes is not None:
            self._assert_core_entity_suggestion(suggestion)
            payload_json.update(
                core_entity_changes.model_dump(mode="json", exclude_unset=True)
            )
            payload_json = self._validated_payload_json(
                suggestion.target_type,
                payload_json,
            )
        if suggestion.target_type == "world_bible_page_draft":
            raise ValidationError(
                "World Bible page draft suggestions must be applied through "
                "the generation-center draft endpoint"
            )
        suggestion = await self._claim_pending(db, novel_id, suggestion_id)
        suggestion.payload_json = payload_json
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
        elif suggestion.target_type in {"core_entity", "core_entity_draft"}:
            payload = CoreEntityDraftSuggestionPayload.model_validate(
                suggestion.payload_json
            )
            content_json = self._core_entity_content_json(suggestion, payload)
            compatibility_ref = dict(suggestion.result_ref_json or {})
            legacy_entity_id = (
                str(compatibility_ref.get("id") or "")
                if compatibility_ref.get("type") == "core_entity_compatibility"
                else ""
            )
            if legacy_entity_id:
                entity = await self._entities.get(
                    db,
                    legacy_entity_id,
                    novel_id=novel_id,
                )
                if entity.status in {"draft", "candidate"}:
                    await self._sync_core_entity_shadow(
                        db,
                        novel_id=novel_id,
                        entity_id=legacy_entity_id,
                        suggestion=suggestion,
                        payload=payload,
                    )
                    promoted = await self._entities.promote(
                        db,
                        legacy_entity_id,
                        EntityPromoteRequest(approved_by="manual"),
                        novel_id=novel_id,
                        _from_suggestion_queue=True,
                    )
                    entity_id = promoted.entity_id
                elif entity.status == "canonical":
                    entity_id = entity.id
                else:
                    raise ValidationError(
                        "Suggestion compatibility entity cannot be adopted from "
                        f"status {entity.status}"
                    )
            else:
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
                        importance=payload.importance,
                        importance_level=payload.importance_level,
                        reveal_level=payload.reveal_level,
                        status="canonical",
                        created_by="ai_world_bible",
                        approved_by="manual",
                        force_create=True,
                    ),
                )
                entity_id = entity.id
            result_ref = {"type": "core_entity", "id": entity_id}
        elif suggestion.target_type == "entity_relation":
            payload = EntityRelationSuggestionPayload.model_validate(
                suggestion.payload_json
            )
            review_meta = {
                "source": suggestion.source_module,
                "review_group": suggestion.review_group,
                "suggestion_id": str(suggestion.id),
                "source_refs": [item.model_dump() for item in payload.source_refs],
                "evidence_refs": list(suggestion.evidence_refs_json or []),
                "reviewed_at": datetime.now(UTC).isoformat(),
                "reviewed_by": "manual",
                "reviewed_from": "creation_suggestion_queue",
                "review_action": "suggestion_accepted",
            }
            relation_result = await self._relations.create_or_merge(
                db,
                novel_id,
                EntityRelationCreate(
                    source_id=payload.source_id,
                    target_id=payload.target_id,
                    relation_type=payload.relation_type,
                    description=payload.description,
                    strength=payload.strength,
                    source_chapter_id=payload.source_chapter_id,
                    quote=payload.quote,
                    status="canonical",
                    review_meta=review_meta,
                ),
            )
            relation = relation_result["relation"]
            result_ref = {"type": "entity_relation", "id": relation.id}
        elif suggestion.target_type == "entity_alias":
            payload = EntityAliasSuggestionPayload.model_validate(suggestion.payload_json)
            alias = await self._aliases.create_alias(
                db,
                novel_id,
                payload.entity_id,
                payload.alias,
                payload.alias_type,
                status="canonical",
                source=suggestion.source_module,
                source_chapter_index=payload.source_chapter_index,
                confidence=payload.confidence,
                evidence_refs=[
                    *[item.model_dump() for item in payload.source_refs],
                    *(suggestion.evidence_refs_json or []),
                ],
                reviewed_by="manual",
            )
            result_ref = {
                "type": "entity_alias",
                "id": f"{payload.entity_id}:{alias['alias']}",
                "entity_id": payload.entity_id,
            }
        else:
            raise ValidationError(
                f"Unsupported suggestion target_type: {suggestion.target_type}"
            )
        return await self._mark_accepted(
            db,
            novel_id=novel_id,
            suggestion=suggestion,
            result_ref=result_ref,
        )

    async def edit_and_confirm_core_entity(
        self,
        db: AsyncSession,
        novel_id: str,
        suggestion_id: str,
        data: CoreEntitySuggestionEditConfirmRequest,
    ) -> CreationSuggestionResponse:
        """Atomically edit a CoreEntity suggestion and adopt the edited value."""
        return await self.confirm(
            db,
            novel_id,
            suggestion_id,
            core_entity_changes=data,
        )

    async def apply_world_generation_page_draft(
        self,
        db: AsyncSession,
        novel_id: str,
        suggestion_id: str,
        data: WorldGenerationApplyPageDraftRequest,
    ) -> WorldGenerationApplyPageDraftResponse:
        """Apply an edited complete-page proposal to a working draft only."""
        pending = await self._get_pending(db, novel_id, suggestion_id)
        if pending.target_type != "world_bible_page_draft":
            raise ValidationError(
                "This decision is only available for generation-center page drafts"
            )
        payload = WorldBiblePageDraftSuggestionPayload.model_validate(
            pending.payload_json
        )
        page_content = data.page or payload.page
        updated_by = data.updated_by or "manual"
        if payload.operation == "replace_existing":
            page_model, draft_model = await self._lock_and_validate_page_baseline(
                db,
                novel_id=novel_id,
                payload=payload,
            )
            suggestion = await self._claim_pending(db, novel_id, suggestion_id)
            if draft_model is None:
                draft = await self._lifecycle.create_draft(
                    db,
                    WorldBiblePageDraftCreate(
                        novel_id=novel_id,
                        page_id=str(page_model.id),
                        title=page_content.title,
                        page_type=page_content.page_type,
                        free_text=page_content.free_text,
                        sections_json=page_content.sections_json,
                        linked_asset_refs_json=page_content.linked_asset_refs_json,
                        template_key=page_model.template_key,
                        template_version=page_model.template_version,
                        created_by=updated_by,
                    ),
                )
            else:
                draft = await self._lifecycle.update_draft(
                    db,
                    novel_id,
                    str(draft_model.id),
                    WorldBiblePageDraftUpdate(
                        title=page_content.title,
                        page_type=page_content.page_type,
                        free_text=page_content.free_text,
                        sections_json=page_content.sections_json,
                        linked_asset_refs_json=page_content.linked_asset_refs_json,
                        updated_by=updated_by,
                    ),
                )
        else:
            suggestion = await self._claim_pending(db, novel_id, suggestion_id)
            draft = await self._lifecycle.create_draft(
                db,
                WorldBiblePageDraftCreate(
                    novel_id=novel_id,
                    title=page_content.title,
                    page_type=page_content.page_type,
                    free_text=page_content.free_text,
                    sections_json=page_content.sections_json,
                    linked_asset_refs_json=page_content.linked_asset_refs_json,
                    template_key=payload.template_key,
                    template_version=payload.template_version,
                    created_by=updated_by,
                ),
            )
        edited_payload = payload.model_copy(update={"page": page_content})
        suggestion.payload_json = edited_payload.model_dump(mode="json")
        accepted = await self._mark_accepted(
            db,
            novel_id=novel_id,
            suggestion=suggestion,
            result_ref={"type": "world_bible_page_draft", "id": draft.id},
        )
        return WorldGenerationApplyPageDraftResponse(
            suggestion=accepted,
            draft=draft,
        )

    async def _lock_and_validate_page_baseline(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        payload: WorldBiblePageDraftSuggestionPayload,
    ) -> tuple[WorldBiblePage, WorldBiblePageDraft | None]:
        baseline = payload.baseline
        if baseline is None or payload.target_page_id is None:
            raise ValidationError("Existing-page suggestion is missing its baseline")
        state = await self._lifecycle.load_page_source(
            db,
            novel_id,
            payload.target_page_id,
            for_update=True,
        )
        mismatch = self._lifecycle.baseline_mismatch(
            state,
            page_version=baseline.page_version,
            draft_id=baseline.draft_id,
            draft_updated_at=baseline.draft_updated_at,
            content_hash=baseline.content_hash,
        )
        if mismatch == "page_version":
            raise ConflictError("World Bible page changed after suggestion generation")
        if mismatch == "draft_created":
            raise ConflictError("World Bible working draft was created after generation")
        if mismatch == "draft_changed":
            raise ConflictError("World Bible working draft changed after generation")
        if mismatch == "content_hash":
            raise ConflictError("World Bible source content changed after generation")
        return state.page, state.draft

    async def merge_core_entity(
        self,
        db: AsyncSession,
        novel_id: str,
        suggestion_id: str,
        data: EntityMergeRequest,
    ) -> CreationSuggestionResponse:
        """Resolve a CoreEntity suggestion by merging it into an adopted entity."""
        suggestion, payload = await self._claim_core_entity_suggestion(
            db,
            novel_id,
            suggestion_id,
        )
        await self._require_canonical_target(db, novel_id, data.target_entity_id)
        candidate_id = await self._materialize_resolution_candidate(
            db,
            novel_id=novel_id,
            suggestion=suggestion,
            payload=payload,
            disposition="merged",
        )
        from modules.world.services.core.dedup_service import EntityDedupService

        merged = await EntityDedupService().merge_candidate_into_entity(
            db,
            novel_id,
            candidate_id,
            data.target_entity_id,
        )
        result_ref = {
            "type": "core_entity_merge",
            "id": data.target_entity_id,
            "candidate_entity_id": candidate_id,
            "affected_ids": [candidate_id, merged.target_entity_id],
            "merged_ids": [merged.candidate_entity_id],
        }
        return await self._mark_accepted(
            db,
            novel_id=novel_id,
            suggestion=suggestion,
            result_ref=result_ref,
        )

    async def resolve_core_entity_as_alias(
        self,
        db: AsyncSession,
        novel_id: str,
        suggestion_id: str,
        data: EntityResolveAsAliasRequest,
    ) -> CreationSuggestionResponse:
        """Resolve a CoreEntity suggestion as an alias of an adopted entity."""
        suggestion, payload = await self._claim_core_entity_suggestion(
            db,
            novel_id,
            suggestion_id,
        )
        await self._require_canonical_target(db, novel_id, data.target_entity_id)
        candidate_id = await self._materialize_resolution_candidate(
            db,
            novel_id=novel_id,
            suggestion=suggestion,
            payload=payload,
            disposition="alias",
        )
        alias_result = await self._aliases.resolve_candidate_as_alias(
            db,
            novel_id,
            candidate_id,
            target_entity_id=data.target_entity_id,
            alias=data.alias,
            alias_type=data.alias_type,
        )
        result_ref = {
            "type": "core_entity_alias",
            "id": data.target_entity_id,
            "candidate_entity_id": candidate_id,
            "affected_ids": list(alias_result.get("affected_ids") or []),
            "merged_ids": list(alias_result.get("merged_ids") or []),
            "alias": data.alias,
        }
        return await self._mark_accepted(
            db,
            novel_id=novel_id,
            suggestion=suggestion,
            result_ref=result_ref,
        )

    async def _claim_core_entity_suggestion(
        self,
        db: AsyncSession,
        novel_id: str,
        suggestion_id: str,
    ) -> tuple[CreationSuggestion, CoreEntityDraftSuggestionPayload]:
        pending = await self._get_pending(db, novel_id, suggestion_id)
        self._assert_core_entity_suggestion(pending)
        payload_json = self._validated_payload_json(
            pending.target_type,
            pending.payload_json,
        )
        suggestion = await self._claim_pending(db, novel_id, suggestion_id)
        suggestion.payload_json = payload_json
        return suggestion, CoreEntityDraftSuggestionPayload.model_validate(payload_json)

    @staticmethod
    def _assert_core_entity_suggestion(suggestion: CreationSuggestion) -> None:
        if suggestion.target_type not in {"core_entity", "core_entity_draft"}:
            raise ValidationError(
                "This decision is only available for core entity suggestions"
            )

    def _core_entity_content_json(
        self,
        suggestion: CreationSuggestion,
        payload: CoreEntityDraftSuggestionPayload,
        *,
        existing_content: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        content_json = dict(payload.content_json or {})
        existing_meta = dict((existing_content or {}).get("_meta") or {})
        payload_meta = dict(content_json.get("_meta") or {})
        meta = {**existing_meta, **payload_meta}
        meta.setdefault("source", suggestion.source_module)
        meta["suggestion_id"] = str(suggestion.id)
        meta["review_group"] = suggestion.review_group
        meta["source_refs"] = [item.model_dump() for item in payload.source_refs]
        meta["evidence_refs"] = list(suggestion.evidence_refs_json or [])
        content_json["_meta"] = meta
        return content_json

    async def _sync_core_entity_shadow(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        entity_id: str,
        suggestion: CreationSuggestion,
        payload: CoreEntityDraftSuggestionPayload,
        disposition: str | None = None,
    ) -> CoreEntityResponse:
        entity = await self._entities.get(db, entity_id, novel_id=novel_id)
        if entity.status not in {"draft", "candidate"}:
            raise ValidationError(
                "Suggestion compatibility entity cannot be resolved from "
                f"status {entity.status}"
            )
        content_json = self._core_entity_content_json(
            suggestion,
            payload,
            existing_content=entity.content_json,
        )
        meta = dict(content_json.get("_meta") or {})
        if disposition is not None:
            meta["compatibility_shadow"] = False
            meta["compatibility_shadow_decided"] = True
            meta["suggestion_disposition"] = disposition
            meta["needs_review"] = False
            meta["reviewed_at"] = datetime.now(UTC).isoformat()
            meta["reviewed_by"] = "manual"
            meta["reviewed_from"] = "creation_suggestion_queue"
        content_json["_meta"] = meta
        return await self._entities.update(
            db,
            entity_id,
            CoreEntityUpdate(
                entity_type=payload.entity_type,
                name=payload.name,
                summary=payload.summary,
                public_info=payload.public_info,
                hidden_truth=payload.hidden_truth,
                content_json=content_json,
                importance=payload.importance,
                importance_level=payload.importance_level,
                reveal_level=payload.reveal_level,
            ),
            novel_id=novel_id,
            _from_suggestion_queue=True,
        )

    async def _materialize_resolution_candidate(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        suggestion: CreationSuggestion,
        payload: CoreEntityDraftSuggestionPayload,
        disposition: str,
    ) -> str:
        compatibility_ref = dict(suggestion.result_ref_json or {})
        legacy_entity_id = (
            str(compatibility_ref.get("id") or "")
            if compatibility_ref.get("type") == "core_entity_compatibility"
            else ""
        )
        if legacy_entity_id:
            await self._sync_core_entity_shadow(
                db,
                novel_id=novel_id,
                entity_id=legacy_entity_id,
                suggestion=suggestion,
                payload=payload,
                disposition=disposition,
            )
            return legacy_entity_id

        content_json = self._core_entity_content_json(suggestion, payload)
        meta = dict(content_json.get("_meta") or {})
        meta.update(
            {
                "compatibility_shadow": False,
                "suggestion_resolution_record": True,
                "suggestion_disposition": disposition,
                "needs_review": False,
                "reviewed_at": datetime.now(UTC).isoformat(),
                "reviewed_by": "manual",
                "reviewed_from": "creation_suggestion_queue",
            }
        )
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
                importance=payload.importance,
                importance_level=payload.importance_level,
                reveal_level=payload.reveal_level,
                status="candidate",
                created_by=f"ai_{suggestion.source_module}",
                force_create=True,
            ),
        )
        return entity.id

    async def _require_canonical_target(
        self,
        db: AsyncSession,
        novel_id: str,
        target_entity_id: str,
    ) -> CoreEntityResponse:
        target = await self._entities.get(
            db,
            target_entity_id,
            novel_id=novel_id,
        )
        if target.status != "canonical":
            raise ValidationError("Suggestion decision target must be an adopted entity")
        return target

    async def _mark_accepted(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        suggestion: CreationSuggestion,
        result_ref: dict[str, Any],
    ) -> CreationSuggestionResponse:
        suggestion.status = "accepted"
        suggestion.result_ref_json = self._preserve_revision_link(
            result_ref,
            suggestion.result_ref_json,
        )
        try:
            from modules.evidence import facade as context_facade

            await context_facade.mark_asset_context_changed(
                db,
                novel_id=novel_id,
                asset_type="worldbuilding",
                asset_id=str(result_ref.get("id") or suggestion.id),
                reason="suggestion_confirmed",
            )
        except Exception as exc:
            logger.warning(
                "world_suggestion_context_invalidation_failed novel_id=%s "
                "suggestion_id=%s asset_id=%s; accepted_write_remains_valid; reason=%s",
                novel_id_for_log(novel_id),
                identifier_for_log(suggestion.id),
                identifier_for_log(result_ref.get("id") or suggestion.id),
                exception_summary_for_log(exc),
            )
        await db.flush()
        return CreationSuggestionResponse.model_validate(suggestion)

    def _validated_payload_json(
        self,
        target_type: str,
        payload_json: dict[str, Any] | None,
    ) -> dict[str, Any]:
        payload = payload_json or {}
        if target_type == "world_bible_page_draft":
            return WorldBiblePageDraftSuggestionPayload.model_validate(
                payload
            ).model_dump(mode="json")
        if target_type in {"core_entity", "core_entity_draft"}:
            return CoreEntityDraftSuggestionPayload.model_validate(payload).model_dump(
                mode="json"
            )
        if target_type == "entity_relation":
            return EntityRelationSuggestionPayload.model_validate(payload).model_dump(
                mode="json"
            )
        if target_type == "entity_alias":
            return EntityAliasSuggestionPayload.model_validate(payload).model_dump(
                mode="json"
            )
        if target_type == "profile_field":
            if not payload.get("entity_id") or not isinstance(
                payload.get("profile"), dict
            ):
                raise ValidationError(
                    "profile_field suggestion requires entity_id/profile"
                )
            return payload
        if target_type == "world_core_checkpoint":
            return WorldCoreCheckpointPayload.model_validate(payload).model_dump(
                mode="json"
            )
        if target_type == "world_adoption_package":
            return WorldAdoptionPackagePayload.model_validate(payload).model_dump(
                mode="json"
            )
        raise ValidationError(f"Unsupported suggestion target_type: {target_type}")

    @staticmethod
    def _world_bible_asset_refs(
        source_refs: list[WorldBibleSourceRef],
    ) -> list[dict[str, Any]]:
        """Keep provenance refs separate from page-to-canonical-asset links."""
        supported_types = {
            "core_entity",
            "entity",
            "profile",
            "event",
            "relation",
            "entity_relation",
        }
        return [
            item.model_dump(mode="json", exclude_none=True)
            for item in source_refs
            if item.source_type in supported_types and item.source_id
        ]

    async def reject(
        self,
        db: AsyncSession,
        novel_id: str,
        suggestion_id: str,
    ) -> CreationSuggestionResponse:
        # Reuse the same compare-and-set claim as confirm so confirm/reject and
        # repeated decisions have exactly one winner.
        suggestion = await self._claim_pending(db, novel_id, suggestion_id)
        compatibility_ref = await self._archive_compatibility_shadow(
            db,
            novel_id=novel_id,
            suggestion=suggestion,
        )
        if compatibility_ref is not None:
            suggestion.result_ref_json = self._preserve_revision_link(
                compatibility_ref,
                suggestion.result_ref_json,
            )
        suggestion.status = "rejected"
        await db.flush()
        return CreationSuggestionResponse.model_validate(suggestion)

    async def _archive_compatibility_shadow(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        suggestion: CreationSuggestion,
    ) -> dict[str, Any] | None:
        reference = dict(suggestion.result_ref_json or {})
        if reference.get("type") != "core_entity_compatibility":
            return None
        entity_id = str(reference.get("id") or "")
        if not entity_id:
            return None
        entity = await self._entities.get(db, entity_id, novel_id=novel_id)
        if entity.status not in {"ignored", "deprecated", "merged"}:
            content_json = dict(entity.content_json or {})
            meta = dict(content_json.get("_meta") or {})
            meta["needs_review"] = False
            meta["reviewed_at"] = datetime.now(UTC).isoformat()
            meta["reviewed_by"] = "manual"
            meta["reviewed_from"] = "creation_suggestion_reject"
            meta["suggestion_disposition"] = "rejected"
            content_json["_meta"] = meta
            await self._entities.update(
                db,
                entity_id,
                CoreEntityUpdate(status="ignored", content_json=content_json),
                novel_id=novel_id,
                _from_suggestion_queue=True,
            )
        return {
            "type": "core_entity_compatibility",
            "id": entity_id,
            "status": "archived",
        }

    @staticmethod
    def _revision_link(
        result_ref_json: dict[str, Any] | None,
    ) -> CreationSuggestionRevisionLink | None:
        raw = (result_ref_json or {}).get("revision_link")
        if raw is None:
            return None
        return CreationSuggestionRevisionLink.model_validate(raw)

    @staticmethod
    def _with_revision_link(
        result_ref_json: dict[str, Any],
        *,
        predecessor: str | None,
        successor: str | None,
    ) -> dict[str, Any]:
        result = dict(result_ref_json)
        result["revision_link"] = CreationSuggestionRevisionLink(
            predecessor_suggestion_id=predecessor,
            successor_suggestion_id=successor,
        ).model_dump(mode="json", exclude_none=True)
        return result

    @staticmethod
    def _preserve_revision_link(
        result_ref_json: dict[str, Any],
        previous_result_ref_json: dict[str, Any] | None,
    ) -> dict[str, Any]:
        result = dict(result_ref_json)
        revision_link = (previous_result_ref_json or {}).get("revision_link")
        if revision_link is not None:
            result["revision_link"] = revision_link
        return result

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


__all__ = ["SuggestionAlreadyProcessedError", "SuggestionQueueService"]
