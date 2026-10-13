"""scene workbench fusion operations for SceneWorkbenchService."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from itertools import combinations
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.stable_hash import stable_hash
from infrastructure.tasks.enqueuer import enqueue_task
from modules.story.outline_state.contracts import (
    SCENE_SEMANTIC_FIELDS,
)
from modules.story.outline_state.models import Scene, SceneFusionSuggestion
from modules.story.outline_state.repositories import (
    SceneRepository,
    SceneSuggestionSourceProjection,
)
from modules.story.outline_state.schemas import (
    SceneCreate,
    SceneFusionDraft,
    SceneFusionPreviewRequest,
    SceneFusionPreviewResponse,
    SceneFusionSaveRequest,
    SceneFusionSaveResponse,
    SceneFusionSuggestionDismissRequest,
    SceneFusionSuggestionDismissResponse,
    SceneFusionSuggestionListResponse,
    SceneFusionSuggestionResponse,
    SceneReplacementApplyRequest,
    SceneReplacementApplyResponse,
    SceneResponse,
    SceneUpdate,
)
from modules.writing.facade import (
    get_draft,
    list_chapter_indices,
)
from shared.utils import parse_uuid

if TYPE_CHECKING:
    from modules.evidence.contracts import ConfirmedAIActionContext


from modules.story.outline_state.scene_workbench_support import (
    _ANCHOR_SUMMARY_LIMIT as _ANCHOR_SUMMARY_LIMIT,
)
from modules.story.outline_state.scene_workbench_support import (
    _FUSION_DECISION_STATUSES as _FUSION_DECISION_STATUSES,
)
from modules.story.outline_state.scene_workbench_support import (
    CONFIDENCE_BANDS as CONFIDENCE_BANDS,
)
from modules.story.outline_state.scene_workbench_support import (
    HEALTH_DEFS as HEALTH_DEFS,
)
from modules.story.outline_state.scene_workbench_support import (
    HEALTH_REASON_GROUPS as HEALTH_REASON_GROUPS,
)
from modules.story.outline_state.scene_workbench_support import (
    HEALTH_REASON_LABELS as HEALTH_REASON_LABELS,
)
from modules.story.outline_state.scene_workbench_support import (
    MAPPING_STATUS_LABELS as MAPPING_STATUS_LABELS,
)
from modules.story.outline_state.scene_workbench_support import (
    SceneSuggestionConflictError as SceneSuggestionConflictError,
)


class SceneWorkbenchFusionMixin:
    async def persist_fusion_suggestions(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        source_workflow_id: str,
        suggestions: list[dict[str, Any]],
    ) -> list[str]:
        nid = parse_uuid(novel_id, "novel_id")
        stored_ids: list[str] = []
        for suggestion in suggestions:
            suggestion_payload = dict(suggestion)
            source_ids = [
                str(value) for value in suggestion_payload.get("source_scene_ids") or []
            ]
            if len(source_ids) < 2 or len(set(source_ids)) != len(source_ids):
                continue
            scenes = await self._get_scenes_in_novel(db, novel_id, source_ids)
            source_fingerprint = self._suggestion_source_fingerprint(scenes)
            suggestion_kind = str(
                suggestion_payload.get("suggestion_kind") or "cross_chapter"
            )
            decision_origin = suggestion_payload.get("decision_origin")
            if decision_origin:
                scan_trace = list(suggestion_payload.get("scan_trace") or [])
                scan_trace.append(
                    {
                        "decision_origin": str(decision_origin),
                        "contract_version": "phase1c-v2",
                    }
                )
                suggestion_payload["scan_trace"] = scan_trace
            suggestion_key = hashlib.sha256(
                (
                    f"{suggestion_kind}:{','.join(source_ids)}:{source_fingerprint}"
                ).encode()
            ).hexdigest()
            stored = await self._suggestion_repo.upsert_pending(
                db,
                novel_id=nid,
                source_workflow_id=source_workflow_id,
                suggestion_key=suggestion_key,
                source_fingerprint=source_fingerprint,
                payload=suggestion_payload,
            )
            stored_ids.append(str(stored.id))
        return stored_ids

    async def get_current_fusion_decision_pairs(
        self,
        db: AsyncSession,
        novel_id: str,
    ) -> set[frozenset[str]]:
        """Return current Scene pairs already decided through Phase 1c review.

        This is an outline-internal read model for global structure dedup. A
        current pending or dismissed decision owns its source pair. An adopted
        decision also owns every source-to-result pair so keep-originals does
        not reappear as a global duplicate suggestion.
        """
        decisions = await self._current_fusion_suggestions(
            db,
            parse_uuid(novel_id, "novel_id"),
            statuses=_FUSION_DECISION_STATUSES,
        )
        protected_pairs: set[frozenset[str]] = set()
        for item in decisions:
            source_ids = [str(value) for value in item.source_scene_ids or []]
            protected_pairs.update(
                frozenset(pair) for pair in combinations(source_ids, 2)
            )
            if item.status == "adopted" and item.result_scene_id is not None:
                result_id = str(item.result_scene_id)
                protected_pairs.update(
                    frozenset((source_id, result_id)) for source_id in source_ids
                )
        return protected_pairs

    async def list_fusion_suggestions(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        skip: int = 0,
        limit: int = 50,
    ) -> SceneFusionSuggestionListResponse:
        pending = await self._active_pending_suggestions(
            db,
            parse_uuid(novel_id, "novel_id"),
        )
        visible = pending[skip : skip + limit]
        return SceneFusionSuggestionListResponse(
            items=[
                SceneFusionSuggestionResponse.model_validate(item) for item in visible
            ],
            total=len(pending),
        )

    async def dismiss_fusion_suggestions(
        self,
        db: AsyncSession,
        novel_id: str,
        data: SceneFusionSuggestionDismissRequest,
    ) -> SceneFusionSuggestionDismissResponse:
        if not data.confirmed:
            raise PermissionError("dismiss suggestions requires confirmed=true")
        if len(set(data.suggestion_ids)) != len(data.suggestion_ids):
            raise ValueError("suggestion_ids cannot contain duplicates")
        nid = parse_uuid(novel_id, "novel_id")
        items: list[SceneFusionSuggestion] = []
        for raw_id in data.suggestion_ids:
            item = await self._suggestion_repo.get_for_novel_for_update(
                db,
                nid,
                parse_uuid(raw_id, "suggestion_id"),
            )
            if item is None:
                raise LookupError("Scene fusion suggestion not found")
            if item.status != "pending":
                raise ValueError("Scene fusion suggestion is already processed")
            if not await self._suggestion_is_current(db, item):
                raise ValueError("Scene fusion suggestion is stale")
            items.append(item)
        for item in items:
            await self._suggestion_repo.mark_status(db, item, status="dismissed")
        return SceneFusionSuggestionDismissResponse(dismissed=len(items))

    async def apply_replacement_suggestion(
        self,
        db: AsyncSession,
        novel_id: str,
        data: SceneReplacementApplyRequest,
    ) -> SceneReplacementApplyResponse:
        if not data.confirmed:
            raise PermissionError("replacement apply requires confirmed=true")
        nid = parse_uuid(novel_id, "novel_id")
        item = await self._suggestion_repo.get_for_novel_for_update(
            db,
            nid,
            parse_uuid(data.suggestion_id, "suggestion_id"),
        )
        if item is None:
            raise LookupError("Scene replacement suggestion not found")
        if item.suggestion_kind != "replacement":
            raise ValueError("suggestion is not a Scene replacement")
        if item.status != "pending":
            raise SceneSuggestionConflictError("Scene replacement is already processed")

        source_ids = self._parse_suggestion_source_ids(item)
        if source_ids is None:
            raise SceneSuggestionConflictError("Scene replacement sources are invalid")
        source_scenes = await self._lock_replacement_sources(db, nid, source_ids)
        if not self._replacement_suggestion_is_current(item, source_scenes):
            await self._suggestion_repo.mark_status(db, item, status="stale")
            raise SceneSuggestionConflictError(
                "Scene replacement suggestion is stale",
                persist_stale=True,
            )

        proposed = dict(item.proposed_scene or {})
        stored_drafts = list(proposed.get("draft_scenes") or [])
        drafts = self._replacement_drafts(data, stored_drafts)
        try:
            await self._validate_replacement_source_hashes(db, novel_id, drafts)
        except SceneSuggestionConflictError as exc:
            await self._suggestion_repo.mark_status(db, item, status="stale")
            raise SceneSuggestionConflictError(
                str(exc),
                persist_stale=True,
            ) from exc

        # 替换 Scene 的索引分配与其它创建路径共享 scene_order advisory lock
        await self.repo.lock_scene_order(db, nid)
        active = list(
            (
                await db.execute(
                    select(Scene)
                    .where(
                        Scene.novel_id == nid,
                        Scene.status.in_(("candidate", "draft", "canonical")),
                    )
                    .order_by(Scene.scene_index, Scene.id)
                    .with_for_update()
                )
            )
            .scalars()
            .all()
        )
        next_index = max((scene.scene_index for scene in active), default=-1) + 1
        now = datetime.now(UTC).isoformat()
        created: list[Scene] = []
        for replacement_order, draft in enumerate(drafts):
            meta = {
                **dict(draft.get("structure_meta") or {}),
                "needs_review": False,
                "needs_organize": False,
                "reviewed_at": now,
                "reviewed_by": "manual",
                "reviewed_from": "scene_replacement",
                "adopted_at": now,
                "replaces_scene_ids": [str(scene.id) for scene in source_scenes],
                "source_workflow_id": item.source_workflow_id,
                "replacement_suggestion_id": str(item.id),
                "replacement_order": replacement_order,
            }
            payload = SceneCreate(
                scene_index=next_index,
                title=draft.get("title"),
                goal=draft.get("goal"),
                core_conflict=draft.get("core_conflict"),
                emotional_beat=draft.get("emotional_beat"),
                must_happen=draft.get("must_happen"),
                must_not_happen=draft.get("must_not_happen"),
                narrative_tag=draft.get("narrative_tag") or "imported",
                source="deep_import",
                scene_chunks=list(draft.get("scene_chunks") or []),
                chapter_ids=list(draft.get("chapter_ids") or []),
                structure_meta=meta,
                status="canonical",
            )
            created.append(await self.repo.create(db, nid, payload))
            next_index += 1

        created_ids = [scene.id for scene in created]
        for scene in source_scenes:
            meta = {
                **dict(scene.structure_meta or {}),
                "previous_status": scene.status,
                "deprecated_reason": "scene_replacement",
                "deprecated_at": now,
                "replaced_by_scene_ids": [str(scene_id) for scene_id in created_ids],
            }
            await self.repo.update(
                db,
                scene.id,
                SceneUpdate(status="deprecated", structure_meta=meta),
            )

        remaining = [scene for scene in active if scene.id not in set(source_ids)]
        ordered = sorted([*remaining, *created], key=self._replacement_sort_key)
        await self.repo.reorder(db, nid, [scene.id for scene in ordered])
        await self._suggestion_repo.mark_status(
            db,
            item,
            status="adopted",
            result_scene_id=created_ids[0] if created_ids else None,
            result_scene_ids=created_ids,
        )
        chapter_indices = sorted(
            {
                int(chapter)
                for draft in drafts
                for chapter in draft.get("chapter_ids") or []
            }
        )
        rag_task_id = enqueue_task(
            db,
            "rag_reindex_novel",
            meta={
                "novel_id": novel_id,
                "start_chapter": chapter_indices[0] if chapter_indices else None,
                "end_chapter": chapter_indices[-1] if chapter_indices else None,
                "source": "scene_replacement_apply",
            },
            novel_id=novel_id,
        )
        return SceneReplacementApplyResponse(
            deprecated_scene_ids=[str(scene.id) for scene in source_scenes],
            result_scene_ids=[str(scene_id) for scene_id in created_ids],
            rag_reindex_task_id=str(rag_task_id),
        )

    async def _lock_replacement_sources(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        source_ids: list[uuid.UUID],
    ) -> list[Scene]:
        result = await db.execute(
            select(Scene)
            .where(Scene.novel_id == novel_id, Scene.id.in_(source_ids))
            .with_for_update()
        )
        by_id = {scene.id: scene for scene in result.scalars().all()}
        if any(scene_id not in by_id for scene_id in source_ids):
            raise SceneSuggestionConflictError("Scene replacement source is missing")
        return [by_id[scene_id] for scene_id in source_ids]

    def _replacement_drafts(
        self,
        data: SceneReplacementApplyRequest,
        stored: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not stored:
            raise SceneSuggestionConflictError("Scene replacement has no candidates")
        if data.decision == "replace":
            if data.draft_scenes is not None:
                raise ValueError("draft_scenes is only valid for edit_then_replace")
            return [dict(item) for item in stored]
        if data.draft_scenes is None or len(data.draft_scenes) != len(stored):
            raise ValueError("edited draft_scenes must preserve candidate count")
        allowed = {
            "title",
            "goal",
            "core_conflict",
            "emotional_beat",
            "must_happen",
            "must_not_happen",
            "narrative_tag",
        }
        merged: list[dict[str, Any]] = []
        for original, edited in zip(stored, data.draft_scenes, strict=True):
            unexpected = set(edited) - allowed
            if unexpected:
                raise ValueError(
                    f"edited replacement contains protected fields: {sorted(unexpected)}"
                )
            merged.append({**dict(original), **{key: edited[key] for key in edited}})
        return merged

    async def _validate_replacement_source_hashes(
        self,
        db: AsyncSession,
        novel_id: str,
        drafts: list[dict[str, Any]],
    ) -> None:
        for draft in drafts:
            for chunk in draft.get("scene_chunks") or []:
                draft_id = chunk.get("source_draft_id")
                expected_hash = chunk.get("source_content_hash")
                if not draft_id or not expected_hash:
                    continue
                current = await get_draft(db, novel_id, str(draft_id))
                if current is None or current.content_hash != expected_hash:
                    raise SceneSuggestionConflictError(
                        "Scene replacement source content has changed"
                    )

    @staticmethod
    def _replacement_sort_key(scene: Scene) -> tuple[Any, ...]:
        chapters = SceneRepository().chapter_indices_for_scene(scene)
        offsets = [
            int(chunk["start_offset"])
            for chunk in scene.scene_chunks or []
            if isinstance(chunk, dict) and chunk.get("start_offset") is not None
        ]
        meta = dict(scene.structure_meta or {})
        return (
            chapters[0] if chapters else 10**12,
            min(offsets) if offsets else 10**12,
            scene.scene_index,
            int(meta.get("replacement_order", 10**12)),
            str(scene.id),
        )

    async def preview_llm_fusion(
        self,
        db: AsyncSession,
        novel_id: str,
        data: SceneFusionPreviewRequest,
        *,
        llm_execution_snapshot: dict[str, Any] | None = None,
        task_mode: bool = False,
        confirmed_context: ConfirmedAIActionContext | None = None,
    ) -> SceneFusionPreviewResponse:
        if not data.primary_scene_id:
            raise ValueError("primary_scene_id is required for AI Scene fusion preview")
        if confirmed_context is not None:
            self._require_confirmed_fusion_sources(confirmed_context, data)
        sources = await self._load_fusion_scenes(db, novel_id, data.source_scene_ids)
        source_fingerprint = self._suggestion_source_fingerprint(sources)
        review_sources = [
            SimpleNamespace(
                **{
                    field: getattr(scene, field)
                    for field in (
                        "id",
                        "title",
                        "goal",
                        "core_conflict",
                        "emotional_beat",
                        "must_happen",
                        "must_not_happen",
                        "narrative_tag",
                        "pov_character_id",
                        "chapter_ids",
                        "scene_chunks",
                        "source",
                        "status",
                        "structure_meta",
                    )
                }
            )
            for scene in sources
        ]
        deterministic_draft = await self._fusion_scene_payload(
            db,
            novel_id,
            sources,
            primary_scene_id=data.primary_scene_id,
        )
        generated = await self._fusion_draft_generator.generate(
            db,
            novel_id=novel_id,
            sources=sources,
            primary_scene_id=data.primary_scene_id,
            deterministic_draft=deterministic_draft,
            llm_execution_snapshot=llm_execution_snapshot,
            allow_degraded=not task_mode,
            confirmed_context=confirmed_context,
        )
        if task_mode:
            from modules.project.facade import require_active_project
            from modules.writing.facade import lock_chapter_versions_for_revalidation

            await require_active_project(db, novel_id)
            await lock_chapter_versions_for_revalidation(
                db,
                novel_id,
                list(generated.evidence_chapter_indices),
            )
            current_sources = await self._load_fusion_scenes(
                db, novel_id, data.source_scene_ids, for_update=True
            )
            if self._suggestion_source_fingerprint(current_sources) != source_fingerprint:
                raise ValueError("Scene fusion sources changed while task ran")
            if (
                await self._fusion_draft_generator.evidence_fingerprint(
                    db,
                    novel_id=novel_id,
                    sources=current_sources,
                )
                != generated.evidence_fingerprint
            ):
                raise ValueError("Scene fusion evidence changed while task ran")
        fused_scene = {
            **deterministic_draft,
            **generated.semantic_fields,
        }
        fused_scene["narrative_function"] = generated.semantic_meta.get(
            "narrative_function"
        )
        fused_scene["structure_meta"] = {
            **dict(deterministic_draft.get("structure_meta") or {}),
            **generated.semantic_meta,
            "fusion_strategy": (
                "local_deterministic_fallback"
                if generated.degraded
                else "project_llm_structured"
            ),
            "semantic_preview_values": {
                **{
                    field: fused_scene.get(field)
                    for field in SCENE_SEMANTIC_FIELDS
                    if field != "narrative_function"
                },
                "narrative_function": generated.semantic_meta.get("narrative_function"),
            },
        }
        review = self._draft_review_service.build_fusion_review(
            sources=review_sources,  # type: ignore[arg-type]
            primary_scene_id=data.primary_scene_id,
            draft_scene=fused_scene,
            mode="fusion",
            confidence=generated.confidence,
            reason=generated.reason,
            warnings=generated.warnings,
        )
        draft = (
            review.draft_scene.model_dump(mode="json", exclude_none=True)
            if review.draft_scene
            else fused_scene
        )
        return SceneFusionPreviewResponse(
            mode=review.mode,
            source_scene_ids=[str(scene.id) for scene in sources],
            primary_scene_id=review.primary_scene_id,
            draft_scene=review.draft_scene,
            draft_scenes=review.draft_scenes,
            field_references=review.field_references,
            field_sources=review.field_sources,
            source_scene_summaries=review.source_scene_summaries,
            conflicts=review.conflicts,
            warnings=review.warnings,
            confidence=review.confidence,
            reason=review.reason,
            fused_scene=draft,
            preview_scene=draft,
        )

    @staticmethod
    def _require_confirmed_fusion_sources(
        confirmed_context: ConfirmedAIActionContext,
        data: SceneFusionPreviewRequest,
    ) -> None:
        pinned_scene_ids = {
            str(target.get("target_id") or "")
            for ref in confirmed_context.compile_options.get("pinned_refs") or []
            if isinstance(ref, dict)
            for target in [ref.get("target_ref") or {}]
            if ref.get("kind") == "target"
            and target.get("target_type") in {"scene", "outline_scene"}
            and target.get("target_id")
        }
        if pinned_scene_ids != set(data.source_scene_ids):
            raise ValueError("confirmed Scene fusion source selection changed")

    async def save_llm_fusion(
        self,
        db: AsyncSession,
        novel_id: str,
        data: SceneFusionSaveRequest,
    ) -> SceneFusionSaveResponse:
        if len(set(data.source_scene_ids)) != len(data.source_scene_ids):
            raise ValueError("source_scene_ids cannot contain duplicates")
        normalized_source_ids = [
            str(parse_uuid(scene_id, "scene_id")) for scene_id in data.source_scene_ids
        ]
        # 先锁建议行、再锁 Scene 行：与 apply_replacement_suggestion 保持同一加锁顺序，
        # 防止 dismiss/save 并发时决策状态与结构数据互相覆盖
        suggestion = await self._load_current_suggestion(
            db,
            novel_id,
            data.suggestion_id,
            normalized_source_ids,
        )
        sources = await self._load_fusion_scenes(
            db,
            novel_id,
            data.source_scene_ids,
            for_update=True,
        )
        source_ids = [str(scene.id) for scene in sources]
        if data.mode == "discard":
            if suggestion is not None:
                await self._suggestion_repo.mark_status(
                    db,
                    suggestion,
                    status="dismissed",
                )
            return SceneFusionSaveResponse(
                status="discarded",
                source_scene_ids=source_ids,
                fused_scene=None,
                warnings=["融合结果已放弃，原 Scene 未修改。"],
            )

        overrides = data.fused_scene if data.mode != "discard" else None
        payload = await self._fusion_scene_payload(
            db,
            novel_id,
            sources,
            overrides,
            primary_scene_id=data.primary_scene_id,
        )
        payload["structure_meta"] = self._adopted_structure_meta(
            payload.get("structure_meta"),
            source=str(payload.get("source") or "manual_fusion"),
        )
        payload["structure_meta"] = self._author_reviewed_fusion_semantic_meta(
            payload,
            payload["structure_meta"],
        )
        await self._validate_fusion_override_chapters(db, novel_id, overrides)
        created = await self.repo.create(
            db,
            parse_uuid(novel_id, "novel_id"),
            SceneCreate(**payload),
        )

        if data.mode == "deprecate_originals":
            await self.repo.deprecate_with_reference(
                db,
                sources,
                reference_field="fused_into_scene_id",
                reference_scene_id=created.id,
            )

        if suggestion is not None:
            await self._suggestion_repo.mark_status(
                db,
                suggestion,
                status="adopted",
                result_scene_id=created.id,
            )

        return SceneFusionSaveResponse(
            status="saved",
            source_scene_ids=source_ids,
            fused_scene=SceneResponse.model_validate(created),
        )

    async def _load_current_suggestion(
        self,
        db: AsyncSession,
        novel_id: str,
        suggestion_id: str | None,
        source_scene_ids: list[str],
    ) -> SceneFusionSuggestion | None:
        if suggestion_id is None:
            return None
        item = await self._suggestion_repo.get_for_novel_for_update(
            db,
            parse_uuid(novel_id, "novel_id"),
            parse_uuid(suggestion_id, "suggestion_id"),
        )
        if item is None:
            raise LookupError("Scene fusion suggestion not found")
        if item.status != "pending":
            raise ValueError("Scene fusion suggestion is already processed")
        if list(item.source_scene_ids or []) != source_scene_ids:
            raise ValueError("Scene fusion suggestion sources do not match")
        if not await self._suggestion_is_current(db, item):
            raise ValueError("Scene fusion suggestion is stale")
        return item

    async def _load_fusion_scenes(
        self,
        db: AsyncSession,
        novel_id: str,
        source_scene_ids: list[str],
        *,
        for_update: bool = False,
    ) -> list[Scene]:
        if len(set(source_scene_ids)) != len(source_scene_ids):
            raise ValueError("source_scene_ids cannot contain duplicates")
        return await self._get_scenes_in_novel(
            db, novel_id, source_scene_ids, for_update=for_update
        )

    async def _fusion_scene_payload(
        self,
        db: AsyncSession,
        novel_id: str,
        sources: list[Scene],
        overrides: SceneFusionDraft | None = None,
        primary_scene_id: str | None = None,
    ) -> dict[str, Any]:
        if not sources:
            raise ValueError("source_scene_ids cannot be empty")
        source_ids = [str(scene.id) for scene in sources]
        ordered_sources = self._primary_first_sources(sources, primary_scene_id)
        payload: dict[str, Any] = {
            "scene_index": await self._next_scene_index(db, novel_id),
            "title": self._fusion_title(ordered_sources),
            "goal": self._join_unique_scene_text(ordered_sources, "goal"),
            "core_conflict": self._join_unique_scene_text(
                ordered_sources,
                "core_conflict",
            ),
            "emotional_beat": self._join_unique_scene_text(
                ordered_sources,
                "emotional_beat",
            ),
            "must_happen": self._join_unique_scene_text(ordered_sources, "must_happen"),
            "must_not_happen": self._join_unique_scene_text(
                ordered_sources,
                "must_not_happen",
            ),
            "narrative_tag": ordered_sources[0].narrative_tag or "draft",
            "source": "manual_fusion",
            "scene_chunks": self._merge_chunks(
                *[source.scene_chunks or [] for source in ordered_sources]
            ),
            "chapter_ids": self._merge_chapter_ids(
                *[source.chapter_ids or [] for source in ordered_sources]
            ),
            "pov_character_id": self._first_non_empty(
                ordered_sources,
                "pov_character_id",
            ),
            "structure_meta": {
                "fused_from_scene_ids": source_ids,
                "fusion_kind": "llm_scene_workbench",
                "fusion_strategy": "author_reviewed_preview",
                "needs_review": True,
            },
            "status": "draft",
        }
        if overrides is not None:
            override_values = overrides.model_dump(exclude_unset=True)
            override_meta = override_values.pop("structure_meta", None)
            has_narrative_function = "narrative_function" in override_values
            narrative_function = override_values.pop("narrative_function", None)
            if has_narrative_function:
                override_meta = {
                    **dict(override_meta or {}),
                    "narrative_function": narrative_function,
                }
            for field, value in override_values.items():
                if (
                    field
                    in {
                        "title",
                        "goal",
                        "core_conflict",
                        "emotional_beat",
                        "must_happen",
                        "must_not_happen",
                        "narrative_tag",
                    }
                    or value is not None
                ):
                    payload[field] = value
            if override_meta is not None:
                meta = dict(payload["structure_meta"])
                meta.update(override_meta)
                payload["structure_meta"] = meta
        payload["status"] = "draft"
        payload["source"] = payload.get("source") or "manual_fusion"
        payload["structure_meta"] = {
            **dict(payload.get("structure_meta") or {}),
            "fused_from_scene_ids": source_ids,
            **({"primary_scene_id": primary_scene_id} if primary_scene_id else {}),
        }
        return payload

    def _primary_first_sources(
        self,
        sources: list[Scene],
        primary_scene_id: str | None,
    ) -> list[Scene]:
        if primary_scene_id is None:
            return sources
        for scene in sources:
            if str(scene.id) == primary_scene_id:
                return [scene, *[source for source in sources if source.id != scene.id]]
        raise ValueError("primary_scene_id must be one of source_scene_ids")

    async def _validate_fusion_override_chapters(
        self,
        db: AsyncSession,
        novel_id: str,
        overrides: SceneFusionDraft | None,
    ) -> None:
        if overrides is None:
            return
        override_values = overrides.model_dump(exclude_unset=True)
        if "chapter_ids" not in override_values and "scene_chunks" not in override_values:
            return
        if not await list_chapter_indices(db, novel_id):
            return
        await self._validate_mapping_chapters(
            db,
            novel_id,
            override_values.get("chapter_ids"),
            override_values.get("scene_chunks"),
        )

    def _fusion_title(self, sources: list[Scene]) -> str:
        titles = [scene.title for scene in sources if scene.title]
        if not titles:
            return "融合 Scene"
        joined = " / ".join(titles)
        return f"融合：{joined}"[:255]

    def _join_unique_scene_text(self, scenes: list[Scene], field: str) -> str | None:
        values: list[str] = []
        seen: set[str] = set()
        for scene in scenes:
            value = getattr(scene, field)
            if value and value not in seen:
                seen.add(value)
                values.append(value)
        if not values:
            return None
        return "\n\n".join(values)

    async def _active_pending_suggestions(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        use_source_projections: bool = False,
    ) -> list[SceneFusionSuggestion]:
        return await self._current_fusion_suggestions(
            db,
            novel_id,
            statuses=("pending",),
            use_source_projections=use_source_projections,
        )

    async def _current_fusion_suggestions(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        statuses: tuple[str, ...],
        use_source_projections: bool = False,
    ) -> list[SceneFusionSuggestion]:
        candidates = await self._suggestion_repo.list_by_statuses(
            db,
            novel_id,
            statuses=statuses,
            skip=0,
            limit=None,
        )
        parsed_candidates: list[tuple[SceneFusionSuggestion, list[uuid.UUID]]] = []
        source_ids: set[uuid.UUID] = set()
        for item in candidates:
            parsed_ids = self._parse_suggestion_source_ids(item)
            if parsed_ids is None:
                continue
            parsed_candidates.append((item, parsed_ids))
            source_ids.update(parsed_ids)
        if not parsed_candidates:
            return []

        if use_source_projections:
            scenes = await self.repo.get_suggestion_source_projections(
                db,
                novel_id,
                list(source_ids),
            )
        else:
            scenes = await self.repo.get_many_for_novel(
                db,
                novel_id,
                list(source_ids),
            )
        scene_by_id = {scene.id: scene for scene in scenes}
        return [
            item
            for item, parsed_ids in parsed_candidates
            if self._suggestion_sources_are_current(item, parsed_ids, scene_by_id)
        ]

    async def _suggestion_is_current(
        self,
        db: AsyncSession,
        item: SceneFusionSuggestion,
    ) -> bool:
        parsed_ids = self._parse_suggestion_source_ids(item)
        if parsed_ids is None:
            return False
        scenes = await self.repo.get_many_for_novel(db, item.novel_id, parsed_ids)
        scene_by_id = {scene.id: scene for scene in scenes}
        return self._suggestion_sources_are_current(item, parsed_ids, scene_by_id)

    @staticmethod
    def _parse_suggestion_source_ids(
        item: SceneFusionSuggestion,
    ) -> list[uuid.UUID] | None:
        try:
            parsed_ids = [uuid.UUID(str(value)) for value in item.source_scene_ids or []]
        except (TypeError, ValueError):
            return None
        minimum = 1 if item.suggestion_kind == "replacement" else 2
        if len(parsed_ids) < minimum or len(set(parsed_ids)) != len(parsed_ids):
            return None
        return parsed_ids

    def _suggestion_sources_are_current(
        self,
        item: SceneFusionSuggestion,
        source_ids: list[uuid.UUID],
        scene_by_id: dict[uuid.UUID, Scene | SceneSuggestionSourceProjection],
    ) -> bool:
        if any(scene_id not in scene_by_id for scene_id in source_ids):
            return False
        ordered = [scene_by_id[scene_id] for scene_id in source_ids]
        if any(scene.status == "deprecated" for scene in ordered):
            return False
        if item.suggestion_kind == "replacement":
            return self._replacement_suggestion_is_current(item, ordered)
        return self._suggestion_source_fingerprint(ordered) == item.source_fingerprint

    @staticmethod
    def _replacement_suggestion_is_current(
        item: SceneFusionSuggestion,
        scenes: list[Scene | SceneSuggestionSourceProjection],
    ) -> bool:
        from modules.story.outline_state.scene_replacement import (
            replacement_source_fingerprint,
            replacement_source_scene_fingerprint,
        )

        if any(scene.status == "deprecated" for scene in scenes):
            return False
        proposed = dict(item.proposed_scene or {})
        expected_scene_fingerprint = proposed.get("source_scene_fingerprint")
        if expected_scene_fingerprint != replacement_source_scene_fingerprint(scenes):
            return False
        return item.source_fingerprint == replacement_source_fingerprint(
            scenes,
            proposed,
        )

    def _suggestion_source_fingerprint(
        self,
        scenes: list[Scene | SceneSuggestionSourceProjection],
    ) -> str:
        payload = [
            {
                "id": str(scene.id),
                "title": scene.title,
                "goal": scene.goal,
                "core_conflict": scene.core_conflict,
                "emotional_beat": scene.emotional_beat,
                "must_happen": scene.must_happen,
                "must_not_happen": scene.must_not_happen,
                "narrative_tag": scene.narrative_tag,
                "pov_character_id": scene.pov_character_id,
                "chapter_ids": scene.chapter_ids or [],
                "scene_chunks": scene.scene_chunks or [],
                "semantic_meta": {
                    key: value
                    for key, value in (scene.structure_meta or {}).items()
                    if key
                    in {
                        "semantic_contract_version",
                        "semantic_origin",
                        "semantic_field_statuses",
                        "semantic_uncertain_fields",
                        "narrative_function",
                        "core_conflict_status",
                    }
                },
            }
            for scene in scenes
        ]
        return stable_hash(payload)
