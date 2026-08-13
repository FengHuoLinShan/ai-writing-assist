from __future__ import annotations

import copy
import hashlib
import json
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.outline.models import StoryOutlineHead, StoryOutlineRevision
from modules.outline.story_outline_repository import StoryOutlineRepository
from modules.outline.story_outline_schemas import (
    StoryExecutionProfile,
    StoryOutlineContent,
    StoryOutlineCurrentResponse,
    StoryOutlineGeneratedPreviewApply,
    StoryOutlineProvenance,
    StoryOutlineRevisionApply,
    StoryOutlineRevisionCreate,
    StoryOutlineRevisionListResponse,
    StoryOutlineRevisionResponse,
)


class StoryOutlineConflictError(RuntimeError):
    pass


class StoryOutlineNotFoundError(LookupError):
    pass


class StoryOutlineService:
    def __init__(self, repository: StoryOutlineRepository | None = None) -> None:
        self.repository = repository or StoryOutlineRepository()

    async def get_current(
        self,
        db: AsyncSession,
        novel_id: str,
    ) -> StoryOutlineCurrentResponse:
        nid = uuid.UUID(novel_id)
        head = await self.repository.get_head(db, nid)
        if head is None or head.current_revision_id is None:
            return StoryOutlineCurrentResponse(
                current_revision_id=None,
                revision=None,
            )
        revision = await self.repository.get_revision(
            db,
            nid,
            head.current_revision_id,
        )
        if revision is None:
            raise StoryOutlineConflictError(
                "StoryOutline head points to a missing project revision"
            )
        return StoryOutlineCurrentResponse(
            current_revision_id=revision.id,
            revision=self._response(revision, current_revision_id=revision.id),
        )

    async def get_revision(
        self,
        db: AsyncSession,
        novel_id: str,
        revision_id: uuid.UUID,
    ) -> StoryOutlineRevisionResponse:
        nid = uuid.UUID(novel_id)
        revision = await self.repository.get_revision(db, nid, revision_id)
        if revision is None:
            raise StoryOutlineNotFoundError("StoryOutline revision not found")
        head = await self.repository.get_head(db, nid)
        return self._response(
            revision,
            current_revision_id=head.current_revision_id if head else None,
        )

    async def list_revisions(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        skip: int,
        limit: int,
    ) -> StoryOutlineRevisionListResponse:
        nid = uuid.UUID(novel_id)
        head = await self.repository.get_head(db, nid)
        revisions, total = await self.repository.list_revisions(
            db,
            nid,
            skip=skip,
            limit=limit,
        )
        current_id = head.current_revision_id if head else None
        return StoryOutlineRevisionListResponse(
            items=[
                self._response(item, current_revision_id=current_id) for item in revisions
            ],
            total=total,
            skip=skip,
            limit=limit,
        )

    async def create_revision(
        self,
        db: AsyncSession,
        novel_id: str,
        data: StoryOutlineRevisionCreate,
    ) -> StoryOutlineRevisionResponse:
        nid = uuid.UUID(novel_id)
        head = await self.repository.lock_or_create_head(db, nid)
        request_payload = data.model_dump(mode="json")
        request_hash = self._hash(request_payload)
        existing = await self.repository.get_revision_by_idempotency_key(
            db,
            nid,
            data.idempotency_key,
        )
        if existing is not None:
            return self._idempotent_response(existing, request_hash, head)

        self._assert_base_revision(head, data.base_revision_id)
        content = self._content_payload(data)
        provenance = self._with_execution_profile(data.provenance, content)
        revision = StoryOutlineRevision(
            novel_id=nid,
            version_number=await self.repository.next_version_number(db, nid),
            title=content["title"],
            creative_core_json=content["creative_core"],
            outline_markdown=content["outline_markdown"],
            major_storylines_json=content["major_storylines"],
            macro_movements_json=content["macro_movements"],
            open_decisions_json=content["open_decisions"],
            source=data.source,
            provenance_json=provenance.model_dump(
                mode="json",
                exclude_none=True,
            ),
            base_revision_id=data.base_revision_id,
            restored_from_revision_id=None,
            idempotency_key=data.idempotency_key,
            request_hash=request_hash,
            content_hash=self._hash(content),
        )
        await self.repository.create_revision(db, revision)
        head.current_revision_id = revision.id
        await db.flush()
        return self._response(revision, current_revision_id=revision.id)

    async def apply_revision(
        self,
        db: AsyncSession,
        novel_id: str,
        revision_id: uuid.UUID,
        data: StoryOutlineRevisionApply,
    ) -> StoryOutlineRevisionResponse:
        nid = uuid.UUID(novel_id)
        head = await self.repository.lock_or_create_head(db, nid)
        request_hash = self._hash(
            {
                "operation": "apply",
                "revision_id": str(revision_id),
                **data.model_dump(mode="json"),
            }
        )
        existing = await self.repository.get_revision_by_idempotency_key(
            db,
            nid,
            data.idempotency_key,
        )
        if existing is not None:
            return self._idempotent_response(existing, request_hash, head)

        target = await self.repository.get_revision(db, nid, revision_id)
        if target is None:
            raise StoryOutlineNotFoundError("StoryOutline revision not found")
        self._assert_base_revision(head, data.base_revision_id)

        provenance = self._with_execution_profile(
            data.provenance,
            self._content_from_revision(target),
            inherited=target.provenance_json,
        )
        revision = StoryOutlineRevision(
            novel_id=nid,
            version_number=await self.repository.next_version_number(db, nid),
            title=target.title,
            creative_core_json=copy.deepcopy(target.creative_core_json),
            outline_markdown=target.outline_markdown,
            major_storylines_json=copy.deepcopy(target.major_storylines_json),
            macro_movements_json=copy.deepcopy(target.macro_movements_json),
            open_decisions_json=copy.deepcopy(target.open_decisions_json),
            source="restored",
            provenance_json=provenance.model_dump(
                mode="json",
                exclude_none=True,
            ),
            base_revision_id=data.base_revision_id,
            restored_from_revision_id=target.id,
            idempotency_key=data.idempotency_key,
            request_hash=request_hash,
            content_hash=target.content_hash,
        )
        await self.repository.create_revision(db, revision)
        head.current_revision_id = revision.id
        await db.flush()
        return self._response(revision, current_revision_id=revision.id)

    async def apply_generated_preview(
        self,
        db: AsyncSession,
        data: StoryOutlineGeneratedPreviewApply,
    ) -> StoryOutlineRevisionResponse:
        """Adopt an edited preview after validating its completed task source."""
        from infrastructure.tasks.facade import (
            get_completed_task_payload,
            replace_completed_task_result,
        )
        from modules.outline.story_outline_generation import (
            STORY_OUTLINE_CONTEXT_VERSION,
            STORY_OUTLINE_GENERATE_ACTION,
        )

        novel_id = data.novel_id
        nid = uuid.UUID(novel_id)
        task_id = str(data.source_task_id)
        task = await get_completed_task_payload(
            db,
            task_id=task_id,
            task_type="story_outline_generate",
            novel_id=novel_id,
            for_update=True,
        )
        if task is None:
            raise StoryOutlineNotFoundError(
                "source_task_id must reference a completed StoryOutline preview task"
            )
        if task.action != STORY_OUTLINE_GENERATE_ACTION:
            raise StoryOutlineConflictError("StoryOutline preview task action mismatch")
        context_hash = self._validate_task_context_provenance(
            task.context_provenance,
            novel_id=novel_id,
            expected_version=STORY_OUTLINE_CONTEXT_VERSION,
        )
        allowed_result_fields = {
            *StoryOutlineContent.model_fields,
            "managed_llm_steps",
            "apply_status",
            "applied_revision_id",
        }
        unexpected_result_fields = set(task.result) - allowed_result_fields
        if unexpected_result_fields:
            raise StoryOutlineConflictError(
                "source task StoryOutline preview contains forbidden fields"
            )
        preview_payload = {
            field_name: task.result[field_name]
            for field_name in StoryOutlineContent.model_fields
            if field_name in task.result
        }
        try:
            StoryOutlineContent.model_validate(preview_payload)
        except Exception as exc:
            raise StoryOutlineConflictError(
                "source task has no valid StoryOutline preview"
            ) from exc

        head = await self.repository.lock_or_create_head(db, nid)
        request_hash = self._hash(
            {
                "operation": "apply_generated_preview",
                "source_task_id": task_id,
                "context_hash": context_hash,
                **data.model_dump(mode="json"),
            }
        )
        existing = await self.repository.get_revision_by_idempotency_key(
            db,
            nid,
            data.idempotency_key,
        )
        if existing is not None:
            return self._idempotent_response(existing, request_hash, head)
        if task.result.get("apply_status") == "applied":
            raise StoryOutlineConflictError(
                "StoryOutline preview task was already adopted"
            )

        self._assert_base_revision(head, data.base_revision_id)
        content = self._content_payload(data)
        provenance = self._task_provenance(
            task_id=task_id,
            context_hash=context_hash,
            context_provenance=task.context_provenance,
        )
        provenance = self._with_execution_profile(provenance, content)
        revision = StoryOutlineRevision(
            novel_id=nid,
            version_number=await self.repository.next_version_number(db, nid),
            title=content["title"],
            creative_core_json=content["creative_core"],
            outline_markdown=content["outline_markdown"],
            major_storylines_json=content["major_storylines"],
            macro_movements_json=content["macro_movements"],
            open_decisions_json=content["open_decisions"],
            source="ai_generated",
            provenance_json=provenance.model_dump(mode="json", exclude_none=True),
            base_revision_id=data.base_revision_id,
            restored_from_revision_id=None,
            idempotency_key=data.idempotency_key,
            request_hash=request_hash,
            content_hash=self._hash(content),
        )
        await self.repository.create_revision(db, revision)
        head.current_revision_id = revision.id
        replaced = await replace_completed_task_result(
            db,
            task_id=task_id,
            task_type="story_outline_generate",
            novel_id=novel_id,
            expected_revision_token=task.revision_token,
            result={
                **task.result,
                "apply_status": "applied",
                "applied_revision_id": str(revision.id),
            },
        )
        if not replaced:
            raise StoryOutlineConflictError(
                "StoryOutline preview task is no longer applicable"
            )
        await db.flush()
        return self._response(revision, current_revision_id=revision.id)

    def _idempotent_response(
        self,
        revision: StoryOutlineRevision,
        request_hash: str,
        head: StoryOutlineHead,
    ) -> StoryOutlineRevisionResponse:
        if revision.request_hash != request_hash:
            raise StoryOutlineConflictError(
                "idempotency_key was already used for a different request"
            )
        return self._response(
            revision,
            current_revision_id=head.current_revision_id,
        )

    @staticmethod
    def _assert_base_revision(
        head: StoryOutlineHead,
        base_revision_id: uuid.UUID | None,
    ) -> None:
        if head.current_revision_id != base_revision_id:
            current = str(head.current_revision_id) if head.current_revision_id else None
            raise StoryOutlineConflictError(
                f"StoryOutline base revision conflict; current_revision_id={current}"
            )

    @staticmethod
    def _content_payload(data: StoryOutlineContent) -> dict[str, Any]:
        return data.model_dump(
            mode="json",
            include={
                "title",
                "creative_core",
                "outline_markdown",
                "major_storylines",
                "macro_movements",
                "open_decisions",
            },
        )

    @staticmethod
    def _content_from_revision(revision: StoryOutlineRevision) -> dict[str, Any]:
        return {
            "title": revision.title,
            "creative_core": copy.deepcopy(revision.creative_core_json),
            "outline_markdown": revision.outline_markdown,
            "major_storylines": copy.deepcopy(revision.major_storylines_json),
            "macro_movements": copy.deepcopy(revision.macro_movements_json),
            "open_decisions": copy.deepcopy(revision.open_decisions_json),
        }

    @classmethod
    def _with_execution_profile(
        cls,
        provenance: StoryOutlineProvenance,
        content: dict[str, Any],
        *,
        inherited: dict[str, Any] | None = None,
    ) -> StoryOutlineProvenance:
        profile = provenance.story_execution_profile
        if profile is None and inherited:
            profile = StoryOutlineProvenance.model_validate(
                inherited
            ).story_execution_profile
        if profile is None:
            profile = cls._derive_execution_profile(content)
        return provenance.model_copy(
            update={
                "story_execution_profile": profile,
                "story_execution_profile_hash": cls._hash(
                    profile.model_dump(mode="json")
                ),
            }
        )

    @staticmethod
    def _derive_execution_profile(content: dict[str, Any]) -> StoryExecutionProfile:
        creative_core = content["creative_core"]
        return StoryExecutionProfile(
            premise=creative_core["premise"],
            tone_and_reader_promise=creative_core["tone_and_reader_promise"],
            story_engine=creative_core["story_engine"],
            ending_direction=creative_core.get("ending_direction"),
            major_storyline_directions=[
                item["resolution_direction"] for item in content["major_storylines"]
            ],
            macro_state_changes=[
                item["story_state_change"] for item in content["macro_movements"]
            ],
        )

    @staticmethod
    def _validate_task_context_provenance(
        provenance: dict[str, Any],
        *,
        novel_id: str,
        expected_version: str,
    ) -> str:
        if provenance.get("action") != "outline.story_outline.generate":
            raise StoryOutlineConflictError(
                "StoryOutline task context provenance action mismatch"
            )
        if provenance.get("version") != expected_version:
            raise StoryOutlineConflictError(
                "StoryOutline task context provenance version mismatch"
            )
        context_hash = str(provenance.get("context_hash") or "")
        if len(context_hash) != 64 or any(
            character not in "0123456789abcdef" for character in context_hash
        ):
            raise StoryOutlineConflictError(
                "StoryOutline task context provenance is invalid"
            )
        source_refs = provenance.get("source_refs")
        if not isinstance(source_refs, list) or not source_refs:
            raise StoryOutlineConflictError(
                "StoryOutline task context source refs are invalid"
            )
        allowed_source_types = {
            "project",
            "world_bible_synopsis",
            "world_bible_page",
            "character",
            "entity",
            "story_outline_revision",
        }
        project_refs = 0
        for source_ref in source_refs:
            if not isinstance(source_ref, dict):
                raise StoryOutlineConflictError(
                    "StoryOutline task context source refs are invalid"
                )
            source_type = str(source_ref.get("type") or "")
            source_id = str(source_ref.get("id") or "")
            source_hash = str(source_ref.get("hash") or "")
            if (
                source_type not in allowed_source_types
                or not source_id
                or len(source_hash) != 64
                or any(character not in "0123456789abcdef" for character in source_hash)
            ):
                raise StoryOutlineConflictError(
                    "StoryOutline task context source refs are invalid"
                )
            if source_type == "project":
                project_refs += 1
                if source_id != novel_id:
                    raise StoryOutlineConflictError(
                        "StoryOutline task project provenance mismatch"
                    )
        if project_refs != 1:
            raise StoryOutlineConflictError(
                "StoryOutline task context must contain one project source ref"
            )
        return context_hash

    @staticmethod
    def _task_provenance(
        *,
        task_id: str,
        context_hash: str,
        context_provenance: dict[str, Any],
    ) -> StoryOutlineProvenance:
        source_refs = [f"task:{task_id}", f"context:{context_hash}"]
        for source in context_provenance.get("source_refs") or []:
            if not isinstance(source, dict):
                continue
            source_type = str(source.get("type") or "source")[:64]
            source_id = str(source.get("id") or "unknown")[:160]
            source_hash = str(source.get("hash") or "")[:64]
            ref = f"{source_type}:{source_id}"
            if source_hash:
                ref += f"@{source_hash}"
            if ref not in source_refs:
                source_refs.append(ref[:512])
            if len(source_refs) >= 100:
                break
        return StoryOutlineProvenance(
            actor="author",
            note="Adopted an author-edited StoryOutline AI preview.",
            client_ref="story-outline-generate/apply",
            source_refs=source_refs,
        )

    @staticmethod
    def _hash(payload: Any) -> str:
        raw = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return hashlib.sha256(raw).hexdigest()

    @staticmethod
    def _response(
        revision: StoryOutlineRevision,
        *,
        current_revision_id: uuid.UUID | None,
    ) -> StoryOutlineRevisionResponse:
        return StoryOutlineRevisionResponse(
            id=revision.id,
            novel_id=revision.novel_id,
            version_number=revision.version_number,
            title=revision.title,
            creative_core=revision.creative_core_json,
            outline_markdown=revision.outline_markdown,
            major_storylines=revision.major_storylines_json,
            macro_movements=revision.macro_movements_json,
            open_decisions=revision.open_decisions_json,
            source=revision.source,
            provenance=revision.provenance_json,
            base_revision_id=revision.base_revision_id,
            restored_from_revision_id=revision.restored_from_revision_id,
            content_hash=revision.content_hash,
            created_at=revision.created_at,
            is_current=revision.id == current_revision_id,
        )
