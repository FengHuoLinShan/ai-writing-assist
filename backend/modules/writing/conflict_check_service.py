"""Deterministic continuity checks and confirmed conflict resolutions."""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ConflictError, NotFoundError, ValidationError
from infrastructure.llm.client import LLMClient
from infrastructure.llm.redaction import redact_diagnostic
from infrastructure.stable_hash import stable_hash as _generation_stable_fingerprint
from modules.evidence.facade import mark_asset_context_changed
from modules.writing.conflict_ai import (
    AI_REVIEW_ACTION,
    ConflictCheckAiReviewService,
    ConflictSuggestionService,
    validate_ai_review_confirmation_scope,
)
from modules.writing.conflict_evidence import evidence_location
from modules.writing.contracts import (
    WritingAuthorAttentionItemContract,
)
from modules.writing.repositories import (
    AI_REVIEW_TASK_OWNER_KEY,
    WritingConflictCheckRepository,
    WritingDraftRepository,
    public_conflict_summary,
)
from modules.writing.schemas import (
    WritingConflictAiReviewRequest,
    WritingConflictAiSuggestionRequest,
    WritingConflictCheckCreate,
    WritingConflictCheckListResponse,
    WritingConflictCheckResponse,
    WritingConflictItemResponse,
    WritingConflictItemUpdate,
    WritingContinuityConfirmationRequest,
    WritingContinuityConfirmationResponse,
)
from modules.writing.service_support import (
    _CONTINUITY_DIMENSION_BY_KIND,
    MapContinuityLoader,
    SceneCheckpointLoader,
    SceneContractLoader,
    _default_map_continuity_loader,
    _default_scene_checkpoint_loader,
    _default_scene_contract_loader,
    _parse_uuid,
    _split_rule_phrases,
    detect_repetition_overlap,
    logger,
)
from modules.writing.source_hashing import hash_text


class WritingConflictCheckService:
    """Rule-based Scene conflict checks for the writing workbench."""

    def __init__(
        self,
        repo: WritingConflictCheckRepository | None = None,
        draft_repo: WritingDraftRepository | None = None,
        scene_contract_loader: SceneContractLoader | None = None,
        scene_checkpoint_loader: SceneCheckpointLoader | None = None,
        map_continuity_loader: MapContinuityLoader | None = None,
        llm_client: LLMClient | None = None,
    ) -> None:
        self._repo = repo or WritingConflictCheckRepository()
        self._draft_repo = draft_repo or WritingDraftRepository()
        self._scene_contract_loader = (
            scene_contract_loader or _default_scene_contract_loader
        )
        self._scene_checkpoint_loader = (
            scene_checkpoint_loader
            if scene_checkpoint_loader is not None
            else _default_scene_checkpoint_loader
            if scene_contract_loader is None
            else None
        )
        self._map_continuity_loader = (
            map_continuity_loader or _default_map_continuity_loader
        )
        self._ai_review_service = ConflictCheckAiReviewService(
            self._repo,
            llm_client=llm_client,
        )
        self._suggestion_service = ConflictSuggestionService(
            self._repo,
            llm_client=llm_client,
        )

    async def _repetition_items(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        chapter_index: int,
        content: str | None,
        draft: object | None,
    ) -> tuple[list[dict], list[dict[str, str]]]:
        """跨章复读确定性检查：仅提示，不拒存。

        续写候选比较续写部分开头与冻结基稿结尾；其余比较候选开头与
        上一章（优先已采用版本）结尾。阈值未用真实长稿校准前保持保守。
        返回 (问题列表, 覆盖缺口说明)；续写分支承诺的比较无法执行时
        必须返回覆盖缺口，不得静默跳过。
        """
        candidate_text = (content or "").strip()
        if not candidate_text and draft is not None:
            candidate_text = (getattr(draft, "content", None) or "").strip()
        if not candidate_text:
            return [], []
        nid = _parse_uuid(novel_id, "novel_id")
        provenance = getattr(draft, "provenance_json", None) or {}
        if (
            provenance.get("source") == "writing_generate"
            and provenance.get("generation_mode") == "continue"
            and provenance.get("base_draft_id")
        ):
            try:
                base = await self._draft_repo.get(
                    db, _parse_uuid(str(provenance["base_draft_id"]), "base draft")
                )
            except ValidationError:
                base = None
            base_text = (getattr(base, "content", None) or "").strip() if base else ""
            candidate_lstripped = candidate_text.lstrip()
            if (
                base is None
                or str(getattr(base, "novel_id", "")) != novel_id
                or not base_text
            ):
                return [], [
                    {
                        "source": "writing.repetition_check",
                        "reason": "base_draft_unavailable",
                    }
                ]
            if not candidate_lstripped.startswith(base_text):
                # 基稿在续写后被改过（候选不再以基稿为前缀），比较失去
                # 基准：记录覆盖缺口而非静默跳过
                return [], [
                    {
                        "source": "writing.repetition_check",
                        "reason": "base_draft_modified",
                    }
                ]
            continuation = candidate_lstripped[len(base_text) :].lstrip()
            spans = detect_repetition_overlap(continuation, base_text)
            label = "续写基稿结尾"
        elif chapter_index >= 2:
            previous = await self._draft_repo.get_latest_published_by_chapter(
                db, nid, chapter_index - 1
            )
            if previous is None:
                previous = await self._draft_repo.get_latest_by_chapter(
                    db, nid, chapter_index - 1
                )
            previous_text = (getattr(previous, "content", None) or "").strip()
            if not previous_text:
                return [], []
            spans = detect_repetition_overlap(candidate_text, previous_text)
            label = f"上一章（第 {chapter_index - 1} 章）结尾"
        else:
            return [], []
        if not spans:
            return [], []
        longest = max(spans, key=lambda span: span["normalized_length"])
        return [
            {
                "kind": "cross_chapter_repetition",
                "severity": "low",
                "source_module": "writing",
                "source_type": "writing.repetition_check",
                "source_id": str(getattr(draft, "id", "") or "") or None,
                "evidence_summary": (
                    f"候选开头与{label}疑似复读"
                    f"（连续约 {longest['normalized_length']} 字，仅字面命中）："
                    f"{longest['sample']}"
                ),
                "needs_review": True,
                "location_json": evidence_location(
                    source_module="writing",
                    source_type="writing.repetition_check",
                    source_id=str(getattr(draft, "id", "") or "") or None,
                    source_label=label,
                    source_field="复读检测",
                    source_excerpt=longest["sample"],
                    open_target={},
                    needs_review_reason=(
                        "字面连续复读不代表语义问题；确认为有意复现或改写后可忽略"
                    ),
                ),
            }
        ], []

    async def create_check(
        self,
        db: AsyncSession,
        data: WritingConflictCheckCreate,
    ) -> WritingConflictCheckResponse:
        nid = _parse_uuid(data.novel_id, "novel_id")
        scene_uuid = _parse_uuid(data.scene_id, "scene_id") if data.scene_id else None
        draft_uuid = _parse_uuid(data.draft_id, "draft_id") if data.draft_id else None
        draft = None
        if draft_uuid is not None:
            draft = await self._draft_repo.get(db, draft_uuid)
            if draft is None or draft.novel_id != nid:
                raise NotFoundError("Draft not found")

        items: list[dict] = []
        degraded_sources: list[str] = []
        omissions: list[dict[str, str]] = []
        continuity_coverage: dict[str, str] = {}
        if data.scene_id:
            scene = await self._load_scene(db, data.novel_id, data.scene_id)
            if scene is None:
                degraded_sources.append("outline")
                omissions.append({"source": "outline", "reason": "scene_unavailable"})
            else:
                scene_items, omission_reason = self._scene_rule_items(
                    scene,
                    data.chapter_index,
                    data.content or "",
                )
                items.extend(scene_items)
                if omission_reason:
                    degraded_sources.append("outline.scene_chunks")
                    omissions.append(
                        {
                            "source": "outline.scene_chunks",
                            "reason": omission_reason,
                        }
                    )
                checkpoint_set = await self._load_scene_checkpoints(
                    db,
                    data.novel_id,
                    data.scene_id,
                )
                if checkpoint_set is not None:
                    map_facts, map_coverage = await self._load_map_facts(
                        db,
                        data.novel_id,
                        checkpoint_set,
                    )
                    continuity_items, continuity_coverage, continuity_omissions = (
                        self._continuity_rule_items(
                            scene,
                            checkpoint_set,
                            map_facts=map_facts,
                            map_coverage=map_coverage,
                        )
                    )
                    items.extend(continuity_items)
                    for dimension, coverage in continuity_coverage.items():
                        if coverage == "not_checked":
                            source = f"continuity.{dimension}"
                            degraded_sources.append(source)
                    omissions.extend(continuity_omissions)
                elif self._scene_checkpoint_loader is not None:
                    continuity_coverage = {
                        "space": "not_checked",
                        "time": "not_checked",
                        "logic": "not_checked",
                    }
                    degraded_sources.append("continuity")
                    omissions.append(
                        {
                            "source": "continuity",
                            "reason": "scene_state_unavailable",
                        }
                    )
        else:
            scene = None

        repetition_items, repetition_omissions = await self._repetition_items(
            db,
            novel_id=data.novel_id,
            chapter_index=data.chapter_index,
            content=data.content,
            draft=draft if draft_uuid is not None else None,
        )
        items.extend(repetition_items)
        if repetition_omissions:
            degraded_sources.append("writing.repetition_check")
            omissions.extend(repetition_omissions)

        status = "degraded" if degraded_sources else "completed"
        summary_json = self._summary(items, degraded_sources, omissions)
        if continuity_coverage:
            summary_json["continuity_coverage"] = continuity_coverage
        content = data.content or ""
        check, created_items = await self._repo.create_check(
            db,
            novel_id=nid,
            chapter_index=data.chapter_index,
            scene_id=scene_uuid,
            draft_id=draft_uuid,
            version_number=data.version_number,
            scope={
                "chapter_index": data.chapter_index,
                "scene_id": data.scene_id,
                "draft_id": data.draft_id,
                "version_number": data.version_number,
                "content_excerpt": content[:4000],
                "content_char_count": len(content),
                "content_hash": hash_text(content),
                "sources": [
                    "outline",
                    *(["story.continuity"] if continuity_coverage else []),
                ],
            },
            include_candidates=data.include_candidates,
            status=status,
            summary_json=summary_json,
            items=items,
        )
        return self._to_check_response(check, created_items)

    async def list_checks(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        chapter_index: int,
        scene_id: str | None,
        limit: int,
        draft_id: str | None = None,
        version_number: int | None = None,
        content_hash: str | None = None,
        include_candidates: bool | None = None,
        ai_review_only: bool = False,
    ) -> WritingConflictCheckListResponse:
        nid = _parse_uuid(novel_id, "novel_id")
        sid = _parse_uuid(scene_id, "scene_id") if scene_id else None
        pairs, total = await self._repo.list_checks(
            db,
            novel_id=nid,
            chapter_index=chapter_index,
            scene_id=sid,
            limit=limit,
            draft_id=_parse_uuid(draft_id, "draft_id") if draft_id else None,
            version_number=version_number,
            content_hash=content_hash,
            include_candidates=include_candidates,
            ai_review_only=ai_review_only,
            exact_scene_scope=ai_review_only,
        )
        return WritingConflictCheckListResponse(
            items=[self._to_check_response(check, items) for check, items in pairs],
            total=total,
        )

    async def get_check(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        check_id: str,
    ) -> WritingConflictCheckResponse:
        nid = _parse_uuid(novel_id, "novel_id")
        cid = _parse_uuid(check_id, "check_id")
        result = await self._repo.get_check(db, cid, nid)
        if result is None:
            raise NotFoundError("Conflict check not found")
        check, items = result
        return self._to_check_response(check, items)

    async def update_item(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        item_id: str,
        data: WritingConflictItemUpdate,
    ) -> WritingConflictItemResponse:
        nid = _parse_uuid(novel_id, "novel_id")
        iid = _parse_uuid(item_id, "item_id")
        item = await self._repo.update_item_status(
            db,
            item_id=iid,
            novel_id=nid,
            status=data.status,
        )
        if item is None:
            raise NotFoundError("Conflict item not found")
        return WritingConflictItemResponse.model_validate(item)

    async def confirm_continuity_item(
        self,
        db: AsyncSession,
        *,
        item_id: str,
        data: WritingContinuityConfirmationRequest,
    ) -> WritingContinuityConfirmationResponse:
        nid = _parse_uuid(data.novel_id, "novel_id")
        iid = _parse_uuid(item_id, "item_id")
        initial = await self._repo.get_item(db, iid, nid)
        if initial is None:
            raise NotFoundError("Conflict item not found")
        locked = await self._repo.get_check_for_ai_review_update(
            db,
            initial.check_id,
            nid,
        )
        if locked is None:
            raise NotFoundError("Conflict check not found")
        check, items = locked
        item = next((candidate for candidate in items if candidate.id == iid), None)
        if item is None:
            raise NotFoundError("Conflict item not found")
        dimension = _CONTINUITY_DIMENSION_BY_KIND.get(item.kind)
        if dimension is None:
            raise ValidationError("该问题不是可确认的连续性事实")
        if not check.scene_id:
            raise ValidationError("连续性确认必须绑定 Scene")
        content_hash = hash_text(data.content)
        request_hash = _generation_stable_fingerprint(
            {
                "item_id": item_id,
                "content_hash": content_hash,
                "dimension": dimension,
                "category": data.category,
                "field_path": data.field_path,
                "old_value": data.old_value,
                "new_value": data.new_value,
                "evidence_summary": data.evidence_summary,
            }
        )
        location = dict(item.location_json or {})
        receipt = location.get("continuity_receipt") or {}
        if receipt.get("request_hash") == request_hash and receipt.get("event_id"):
            scene_state = await self._load_scene_checkpoints(
                db,
                data.novel_id,
                str(check.scene_id),
            )
            return WritingContinuityConfirmationResponse(
                event_id=str(receipt["event_id"]),
                created=False,
                item=WritingConflictItemResponse.model_validate(item),
                scene_state=self._checkpoint_payload(scene_state),
                message="该连续性事实已经确认",
            )
        if self._timestamp_key(item.updated_at) != self._timestamp_key(
            data.expected_item_updated_at
        ):
            raise ConflictError("问题已变化，请刷新后重新确认")
        if content_hash != str(check.scope.get("content_hash") or ""):
            raise ConflictError("正文已变化，请重新检查后再确认连续性事实")
        if check.draft_id:
            draft = await self._draft_repo.get(db, check.draft_id)
            if (
                draft is None
                or draft.novel_id != nid
                or draft.content_hash != content_hash
                or draft.version_number != check.version_number
            ):
                raise ConflictError("正文版本已变化，请重新检查后再确认")

        scene = await self._load_scene(db, data.novel_id, str(check.scene_id))
        if scene is None:
            raise NotFoundError("Scene not found")
        confirmed_context = None
        if item.is_ai_judgment:
            if not item.source_confirmation_id:
                raise ConflictError("AI 连续性问题缺少原确认资料")
            from modules.evidence.facade import prepare_confirmed_ai_action

            confirmed_context = await prepare_confirmed_ai_action(
                db,
                novel_id=data.novel_id,
                action=AI_REVIEW_ACTION,
                confirmation_id=str(item.source_confirmation_id),
            )

        checkpoint_set = await self._load_scene_checkpoints(
            db,
            data.novel_id,
            str(check.scene_id),
        )
        checkpoint_payload = self._checkpoint_payload(checkpoint_set)
        current_checkpoint = next(
            (
                candidate
                for candidate in checkpoint_payload.get("items") or []
                if candidate.get("dimension") == dimension
            ),
            None,
        )
        expected_checkpoint_id = self._expected_checkpoint_id(
            item,
            confirmed_context,
            dimension,
        )
        if (
            current_checkpoint is None
            or not expected_checkpoint_id
            or str(current_checkpoint.get("id") or "") != expected_checkpoint_id
        ):
            raise ConflictError("Scene 时点状态已变化，请重新检查后再确认")

        from modules.story.contracts import ConfirmedContinuityEventIngest
        from modules.story.facade import (
            confirm_scene_continuity_event,
            ensure_scene_checkpoints,
        )

        event, created = await confirm_scene_continuity_event(
            db,
            data.novel_id,
            scene_id=str(check.scene_id),
            scene_index=int(getattr(scene, "scene_index")),
            chapter_index=check.chapter_index,
            event=ConfirmedContinuityEventIngest(
                dimension=dimension,
                category=data.category,
                field_path=data.field_path,
                old_value=data.old_value,
                new_value=data.new_value,
                idempotency_key=f"writing_conflict_item:{item.id}",
                evidence_summary=data.evidence_summary,
                source_confirmation_id=(
                    str(item.source_confirmation_id)
                    if item.source_confirmation_id
                    else None
                ),
            ),
        )
        rebuilt = await ensure_scene_checkpoints(
            db,
            data.novel_id,
            str(check.scene_id),
        )
        await mark_asset_context_changed(
            db,
            novel_id=data.novel_id,
            asset_type="memory_scene_checkpoint",
            asset_id=expected_checkpoint_id,
            reason="continuity_changed",
        )
        location["continuity_receipt"] = {
            "request_hash": request_hash,
            "event_id": event.id,
            "dimension": dimension,
            "confirmed_at": datetime.now(UTC).isoformat(),
        }
        item.location_json = location
        item.status = "resolved"
        summary = dict(check.summary_json or {})
        summary["continuity_state_changed"] = {
            "item_id": str(item.id),
            "event_id": event.id,
            "dimension": dimension,
        }
        check.summary_json = summary
        check.status = "degraded"
        db.add_all([check, item])
        await db.flush()
        return WritingContinuityConfirmationResponse(
            event_id=event.id,
            created=created,
            item=WritingConflictItemResponse.model_validate(item),
            scene_state=self._checkpoint_payload(rebuilt),
        )

    async def run_ai_review_for_task(
        self,
        db: AsyncSession,
        *,
        check_id: str,
        data: WritingConflictAiReviewRequest,
        task_id: str,
        llm_execution_snapshot: dict[str, Any],
        allow_unowned_legacy: bool = False,
        finalize_transient_failure: bool = True,
    ) -> WritingConflictCheckResponse:
        """Run the commit-owning task seam; never exposed through the facade."""
        check, items = await self._ai_review_service.run_for_task(
            db,
            novel_id=data.novel_id,
            check_id=check_id,
            context_confirmation_id=data.context_confirmation_id,
            task_id=task_id,
            llm_execution_snapshot=llm_execution_snapshot,
            allow_unowned_legacy=allow_unowned_legacy,
            finalize_transient_failure=finalize_transient_failure,
        )
        return self._to_check_response(check, items)

    async def start_ai_review_task(
        self,
        db: AsyncSession,
        *,
        check_id: str,
        data: WritingConflictAiReviewRequest,
        activate: bool = True,
    ) -> WritingConflictCheckResponse:
        from modules.evidence.facade import prepare_confirmed_ai_action

        nid = _parse_uuid(data.novel_id, "novel_id")
        cid = _parse_uuid(check_id, "check_id")
        confirmation_uuid = _parse_uuid(
            data.context_confirmation_id,
            "context_confirmation_id",
        )
        # Serialize sync review and competing async enqueues on the same check.
        # The API project guard is acquired before this row lock.
        existing = await self._repo.get_check_for_ai_review_update(db, cid, nid)
        if existing is None:
            raise NotFoundError("Conflict check not found")
        check, items = existing

        try:
            confirmed_context = await prepare_confirmed_ai_action(
                db,
                novel_id=data.novel_id,
                action=AI_REVIEW_ACTION,
                confirmation_id=data.context_confirmation_id,
            )
            validate_ai_review_confirmation_scope(
                confirmed_context.confirmation,
                check,
            )
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc

        if not activate:
            return self._to_check_response(check, items)
        updated = await self._repo.update_ai_review(
            db,
            check_id=cid,
            novel_id=nid,
            status="running",
            confirmation_id=confirmation_uuid,
            model=None,
            error=None,
        )
        return self._to_check_response(updated or check, items)

    async def bind_ai_review_task_owner(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        check_id: str,
        task_id: str,
        confirmation_id: str | None = None,
    ) -> None:
        """Fence a queued review to the task created in the same transaction."""
        nid = _parse_uuid(novel_id, "novel_id")
        cid = _parse_uuid(check_id, "check_id")
        existing = await self._repo.get_check_for_ai_review_update(db, cid, nid)
        if existing is None:
            raise NotFoundError("Conflict check not found")
        check, _items = existing
        summary = dict(check.summary_json or {})
        summary[AI_REVIEW_TASK_OWNER_KEY] = str(task_id)
        await self._repo.update_loaded_ai_review(
            db,
            check,
            status="running",
            summary_json=summary,
            confirmation_id=(
                _parse_uuid(confirmation_id, "context_confirmation_id")
                if confirmation_id
                else check.ai_review_confirmation_id
            ),
            model=None,
            error=None,
        )

    async def validate_ai_suggestion_request(
        self,
        db: AsyncSession,
        *,
        item_id: str,
        data: WritingConflictAiSuggestionRequest,
    ) -> None:
        await self._suggestion_service.validate(
            db,
            novel_id=data.novel_id,
            item_id=item_id,
            context_confirmation_id=data.context_confirmation_id,
        )

    async def run_ai_suggestion_for_task(
        self,
        db: AsyncSession,
        *,
        item_id: str,
        data: WritingConflictAiSuggestionRequest,
        llm_execution_snapshot: dict[str, Any],
        finalize_transient_failure: bool,
    ) -> WritingConflictItemResponse:
        item = await self._suggestion_service.run_for_task(
            db,
            novel_id=data.novel_id,
            item_id=item_id,
            context_confirmation_id=data.context_confirmation_id,
            llm_execution_snapshot=llm_execution_snapshot,
            finalize_transient_failure=finalize_transient_failure,
        )
        return WritingConflictItemResponse.model_validate(item)

    async def latest_snapshot(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        chapter_index: int,
        scene_id: str | None,
    ) -> dict | None:
        nid = _parse_uuid(novel_id, "novel_id")
        sid = _parse_uuid(scene_id, "scene_id") if scene_id else None
        return await self._repo.build_latest_snapshot(
            db,
            novel_id=nid,
            chapter_index=chapter_index,
            scene_id=sid,
        )

    async def get_author_attention_items(
        self,
        db: AsyncSession,
        novel_id: str,
    ) -> list[WritingAuthorAttentionItemContract]:
        nid = _parse_uuid(novel_id, "novel_id")
        rows = await self._repo.list_latest_open_items_for_project(db, nid)
        if not rows:
            return []
        chapter_indices = sorted({check.chapter_index for check, _item in rows})
        latest_drafts = await self._draft_repo.list_latest_by_chapters(
            db,
            nid,
            chapter_indices,
        )
        drafts_by_chapter = {draft.chapter_index: draft for draft in latest_drafts}
        items: list[WritingAuthorAttentionItemContract] = []
        stale_checks: set[uuid.UUID] = set()
        for check, item in rows:
            latest_draft = drafts_by_chapter.get(check.chapter_index)
            is_stale = latest_draft is not None and (
                check.draft_id != latest_draft.id
                or check.version_number != latest_draft.version_number
                or check.scope.get("content_hash") != latest_draft.content_hash
            )
            if is_stale:
                if check.id in stale_checks:
                    continue
                stale_checks.add(check.id)
                items.append(
                    WritingAuthorAttentionItemContract(
                        key=f"writing:recheck:{check.id}",
                        title=f"重新检查第 {check.chapter_index} 章",
                        summary="正文版本已更新，旧的字面预警不再作为当前结果。",
                        author_action="can_improve",
                        severity="low",
                        chapter_index=check.chapter_index,
                        scene_id=str(check.scene_id) if check.scene_id else None,
                        item_id=None,
                        updated_at=check.updated_at,
                    )
                )
                continue
            author_action = (
                "needs_decision"
                if item.is_ai_judgment and item.needs_review
                else "can_improve"
            )
            title = {
                "forbidden_present": "疑似出现 Scene 禁止项",
                "required_missing": "Scene 必须发生项未逐字出现",
                "space_continuity_risk": "检查空间连续性",
                "time_continuity_risk": "检查时间连续性",
                "logic_continuity_risk": "检查前提与结果",
            }.get(item.kind, "检查写作语义问题")
            items.append(
                WritingAuthorAttentionItemContract(
                    key=f"writing:conflict:{item.id}",
                    title=title,
                    summary=item.evidence_summary,
                    author_action=author_action,
                    severity=item.severity,
                    chapter_index=check.chapter_index,
                    scene_id=str(check.scene_id) if check.scene_id else None,
                    item_id=str(item.id),
                    updated_at=item.updated_at or check.updated_at,
                )
            )
        return items

    async def _load_scene(self, db: AsyncSession, novel_id: str, scene_id: str):
        try:
            return await self._scene_contract_loader(db, novel_id, scene_id)
        except Exception as exc:
            logger.warning(
                "Failed to load scene for conflict check: %s",
                redact_diagnostic(exc, limit=500),
            )
            return None

    async def _load_scene_checkpoints(
        self,
        db: AsyncSession,
        novel_id: str,
        scene_id: str,
    ) -> object | None:
        if self._scene_checkpoint_loader is None:
            return None
        try:
            return await self._scene_checkpoint_loader(db, novel_id, scene_id)
        except Exception as exc:
            logger.warning(
                "Failed to load Scene continuity state for conflict check: %s",
                redact_diagnostic(exc, limit=500),
            )
            return None

    async def _load_map_facts(
        self,
        db: AsyncSession,
        novel_id: str,
        checkpoint_set: object,
    ) -> tuple[list[dict[str, Any]], str]:
        location_ids = self._continuity_location_ids(checkpoint_set)
        if len(location_ids) < 2:
            return [], "not_applicable"
        try:
            facts = await self._map_continuity_loader(
                db,
                novel_id,
                sorted(location_ids),
            )
        except Exception as exc:
            logger.warning(
                "Failed to load adopted map continuity evidence: %s",
                redact_diagnostic(exc, limit=500),
            )
            return [], "not_checked"
        projected = [item if isinstance(item, dict) else asdict(item) for item in facts]
        return projected, "checked" if projected else "not_checked"

    def _continuity_rule_items(
        self,
        scene: object,
        checkpoint_set: object,
        *,
        map_facts: list[dict[str, Any]] | None = None,
        map_coverage: str = "not_applicable",
    ) -> tuple[list[dict], dict[str, str], list[dict[str, str]]]:
        payload = (
            checkpoint_set.model_dump()
            if hasattr(checkpoint_set, "model_dump")
            else dict(checkpoint_set)
        )
        checkpoints = {
            str(item.get("dimension")): item
            for item in payload.get("items") or []
            if isinstance(item, dict) and item.get("dimension")
        }
        mapping = {
            "space": "locations",
            "time": "timeline",
            "logic": "causality",
        }
        coverage: dict[str, str] = {}
        omissions: list[dict[str, str]] = []
        trusted: dict[str, dict[str, Any]] = {}
        for label, dimension in mapping.items():
            checkpoint = checkpoints.get(dimension) or {}
            is_trusted = checkpoint.get("status") == "ready" and (
                checkpoint.get("source") == "system_generated"
                or checkpoint.get("confirmed") is True
            )
            coverage[label] = "checked" if is_trusted else "not_checked"
            if is_trusted:
                trusted[dimension] = checkpoint
            else:
                omissions.append(
                    {
                        "source": f"continuity.{label}",
                        "reason": str(checkpoint.get("status") or "missing"),
                    }
                )
        coverage["map"] = map_coverage
        if map_coverage == "not_checked":
            omissions.append(
                {"source": "continuity.map", "reason": "adopted_map_unavailable"}
            )

        items: list[dict] = []
        if checkpoint := trusted.get("locations"):
            items.extend(
                self._space_rule_items(
                    scene,
                    checkpoint,
                    map_facts=map_facts or [],
                )
            )
        if checkpoint := trusted.get("timeline"):
            items.extend(self._time_rule_items(scene, checkpoint))
        if checkpoint := trusted.get("causality"):
            items.extend(self._logic_rule_items(scene, checkpoint))
        return items, coverage, omissions

    def _space_rule_items(
        self,
        scene: object,
        checkpoint: dict,
        *,
        map_facts: list[dict[str, Any]],
    ) -> list[dict]:
        state = checkpoint.get("state_json") or {}
        issues: list[tuple[str, str]] = []
        structure_meta = getattr(scene, "structure_meta", None) or {}
        exit_state = structure_meta.get("exit_state") or {}
        pov_id = str(getattr(scene, "pov_character_id", None) or "")
        if isinstance(exit_state, dict) and pov_id:
            expected = exit_state.get("location_id") or exit_state.get("location")
            actual_state = (state.get("character_locations") or {}).get(pov_id) or {}
            actual = (
                actual_state.get("location_id")
                or actual_state.get("location")
                or actual_state.get("new_value")
                if isinstance(actual_state, dict)
                else None
            )
            if (
                expected
                and actual
                and self._stable_value(expected) != self._stable_value(actual)
            ):
                issues.append(
                    (
                        "space_exit_state_mismatch",
                        "Scene 结束位置与可追溯位置状态不一致",
                    )
                )

        grouped: dict[tuple[str, str], set[str]] = {}
        for change in state.get("changes") or []:
            if not isinstance(change, dict):
                continue
            meta = change.get("meta") or {}
            subject = str(meta.get("subject_name") or change.get("subject_id") or "")
            effective_at = str(
                change.get("effective_at")
                or change.get("scene_index")
                or meta.get("effective_at")
                or ""
            )
            location = change.get("new_value")
            if subject and effective_at and location not in (None, ""):
                grouped.setdefault((subject, effective_at), set()).add(
                    self._stable_value(location)
                )
        if any(len(values) > 1 for values in grouped.values()):
            issues.append(
                (
                    "space_simultaneous_presence",
                    "同一对象在同一时点存在互斥的位置记录",
                )
            )
        transition_pairs = self._location_transition_pairs_from_state(state)
        if transition_pairs and map_facts:
            route_edges = {
                frozenset(
                    (
                        str(fact.get("subject_entity_id") or ""),
                        str(fact.get("target_entity_id") or ""),
                    )
                )
                for fact in map_facts
                if fact.get("relation")
                in {"adjacent", "connects", "passes_through", "entrance_to"}
            }
            known_locations = {
                str(fact.get(key) or "")
                for fact in map_facts
                for key in ("subject_entity_id", "target_entity_id")
                if fact.get(key)
            }
            if any(
                {start, end}.issubset(known_locations)
                and frozenset((start, end)) not in route_edges
                for start, end in transition_pairs
            ):
                issues.append(
                    (
                        "space_route_not_declared",
                        "已采用地图覆盖起止地点，但未声明两地之间的通行关系",
                    )
                )
        return [
            self._continuity_item(
                scene,
                checkpoint,
                kind="space_continuity_risk",
                rule_code=rule_code,
                summary=summary,
            )
            for rule_code, summary in issues
        ]

    def _time_rule_items(self, scene: object, checkpoint: dict) -> list[dict]:
        facts = [
            item
            for item in (checkpoint.get("state_json") or {}).get("facts") or []
            if isinstance(item, dict)
        ]
        edges: set[tuple[str, str]] = set()
        same_time: set[frozenset[str]] = set()
        anchors: dict[tuple[str, str], set[str]] = {}
        for fact in facts:
            category = str(fact.get("category") or "").lower()
            meta = fact.get("meta") or {}
            subject = str(meta.get("subject_name") or fact.get("subject") or "").strip()
            target = fact.get("new_value") or fact.get("target")
            if subject and isinstance(target, str) and target.strip():
                target = target.strip()
                if "before" in category:
                    edges.add((subject, target))
                elif "after" in category:
                    edges.add((target, subject))
                elif "same_time" in category or "simultaneous" in category:
                    same_time.add(frozenset((subject, target)))
            field = str(fact.get("field_path") or "").strip()
            effective_at = str(fact.get("scene_index") or meta.get("effective_at") or "")
            value = fact.get("new_value")
            if field and effective_at and value not in (None, ""):
                anchors.setdefault((field, effective_at), set()).add(
                    self._stable_value(value)
                )

        issues: list[tuple[str, str]] = []
        if self._has_directed_cycle(edges):
            issues.append(("time_order_cycle", "已确认的时间先后关系形成循环"))
        if any(frozenset(edge) in same_time for edge in edges):
            issues.append(
                ("time_simultaneous_order_conflict", "同一事件既被标为同时又有先后顺序")
            )
        if any(len(values) > 1 for values in anchors.values()):
            issues.append(("time_anchor_conflict", "同一时点存在互斥的时间锚记录"))
        return [
            self._continuity_item(
                scene,
                checkpoint,
                kind="time_continuity_risk",
                rule_code=rule_code,
                summary=summary,
            )
            for rule_code, summary in issues
        ]

    def _logic_rule_items(self, scene: object, checkpoint: dict) -> list[dict]:
        claims = [
            item
            for item in (checkpoint.get("state_json") or {}).get("claims") or []
            if isinstance(item, dict)
        ]
        current_scene_index = int(getattr(scene, "scene_index", 0) or 0)
        grouped: dict[tuple[str, str], set[str]] = {}
        true_claims: set[str] = set()
        required: set[str] = set()
        overdue: list[str] = []
        for claim in claims:
            meta = claim.get("meta") or {}
            key = str(meta.get("claim_key") or claim.get("field_path") or "").strip()
            effective_at = str(claim.get("scene_index") or meta.get("effective_at") or "")
            value = claim.get("new_value")
            if key and effective_at and value not in (None, ""):
                grouped.setdefault((key, effective_at), set()).add(
                    self._stable_value(value)
                )
            if key and self._is_true_value(value):
                true_claims.add(key)
            for item in meta.get("required_preconditions") or []:
                if str(item).strip():
                    required.add(str(item).strip())
            due = meta.get("due_scene_index")
            if (
                key
                and isinstance(due, int)
                and due <= current_scene_index
                and str(value).strip().lower() in {"open", "pending", "unmet"}
            ):
                overdue.append(key)

        issues: list[tuple[str, str]] = []
        if any(len(values) > 1 for values in grouped.values()):
            issues.append(("logic_claim_conflict", "同一时点存在互斥的事实或前提"))
        missing = sorted(required - true_claims)
        if missing:
            issues.append(
                (
                    "logic_precondition_missing",
                    f"明确要求的前提尚未满足：{'、'.join(missing[:3])}",
                )
            )
        if overdue:
            issues.append(
                (
                    "logic_commitment_unmet",
                    f"已到约定边界但仍未兑现：{'、'.join(sorted(overdue)[:3])}",
                )
            )
        return [
            self._continuity_item(
                scene,
                checkpoint,
                kind="logic_continuity_risk",
                rule_code=rule_code,
                summary=summary,
            )
            for rule_code, summary in issues
        ]

    @staticmethod
    def _continuity_item(
        scene: object,
        checkpoint: dict,
        *,
        kind: str,
        rule_code: str,
        summary: str,
    ) -> dict:
        scene_id = str(getattr(scene, "id", "") or "")
        location = evidence_location(
            source_module="memory",
            source_type=f"scene_checkpoint.{checkpoint.get('dimension')}",
            source_id=str(checkpoint.get("id") or ""),
            source_label=(
                f"Scene 时点状态：{getattr(scene, 'title', None) or '未命名场景'}"
            ),
            source_field={
                "space_continuity_risk": "空间与位置",
                "time_continuity_risk": "时间顺序",
                "logic_continuity_risk": "因果与前提",
            }[kind],
            source_excerpt=str(checkpoint.get("display_summary") or summary)[:500],
            open_target={"kind": "outline_scene", "scene_id": scene_id},
            needs_review_reason="依据结构化 Scene 时点证据确定性发现，请核对来源后处理",
        )
        location.update(
            rule_code=rule_code,
            coverage="checked",
            evidence_refs=list(checkpoint.get("evidence_refs") or [])[:20],
            continuity_confirmation={
                "dimension": checkpoint.get("dimension"),
                "editable": True,
            },
        )
        return {
            "kind": kind,
            "severity": "medium",
            "source_module": "memory",
            "source_type": f"scene_checkpoint.{checkpoint.get('dimension')}",
            "source_id": str(checkpoint.get("id") or ""),
            "evidence_summary": summary,
            "needs_review": True,
            "location_json": location,
        }

    @staticmethod
    def _stable_value(value: Any) -> str:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )

    @staticmethod
    def _checkpoint_payload(value: object | None) -> dict[str, Any]:
        if value is None:
            return {}
        if hasattr(value, "model_dump"):
            payload = value.model_dump()
            return payload if isinstance(payload, dict) else {}
        return dict(value) if isinstance(value, Mapping) else {}

    @staticmethod
    def _timestamp_key(value: object) -> str:
        if isinstance(value, str):
            try:
                value = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return value
        if not isinstance(value, datetime):
            return str(value)
        normalized = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return normalized.astimezone(UTC).isoformat()

    @staticmethod
    def _expected_checkpoint_id(
        item: object,
        confirmed_context: object | None,
        dimension: str,
    ) -> str:
        if confirmed_context is None:
            location = getattr(item, "location_json", None) or {}
            source = location.get("source") or {}
            return str(source.get("id") or "")
        compiled = getattr(confirmed_context, "compiled", None)
        section = next(
            (
                candidate
                for candidate in getattr(compiled, "sections", [])
                if candidate.key == "scene_world_state"
            ),
            None,
        )
        versions = (
            (section.retrieval_metadata or {}).get("checkpoint_versions") or []
            if section is not None
            else []
        )
        return next(
            (
                str(candidate.get("id") or "")
                for candidate in versions
                if isinstance(candidate, dict) and candidate.get("dimension") == dimension
            ),
            "",
        )

    @classmethod
    def _continuity_location_ids(cls, checkpoint_set: object) -> set[str]:
        payload = (
            checkpoint_set.model_dump()
            if hasattr(checkpoint_set, "model_dump")
            else dict(checkpoint_set)
        )
        checkpoint = next(
            (
                item
                for item in payload.get("items") or []
                if isinstance(item, dict) and item.get("dimension") == "locations"
            ),
            {},
        )
        pairs = cls._location_transition_pairs_from_state(
            checkpoint.get("state_json") or {}
        )
        return {location_id for pair in pairs for location_id in pair}

    @classmethod
    def _location_transition_pairs_from_state(
        cls,
        state: dict[str, Any],
    ) -> set[tuple[str, str]]:
        pairs: set[tuple[str, str]] = set()
        for change in state.get("changes") or []:
            if not isinstance(change, dict):
                continue
            before = cls._location_id(change.get("old_value"))
            after = cls._location_id(change.get("new_value"))
            if before and after and before != after:
                pairs.add((before, after))
        return pairs

    @staticmethod
    def _location_id(value: Any) -> str | None:
        candidate = (
            value.get("location_id") or value.get("id")
            if isinstance(value, dict)
            else value
        )
        try:
            return str(uuid.UUID(str(candidate)))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _is_true_value(value: Any) -> bool:
        if value is True or value == 1:
            return True
        return str(value).strip().lower() in {"true", "met", "satisfied", "done"}

    @staticmethod
    def _has_directed_cycle(edges: set[tuple[str, str]]) -> bool:
        graph: dict[str, set[str]] = {}
        for source, target in edges:
            graph.setdefault(source, set()).add(target)
            graph.setdefault(target, set())
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node: str) -> bool:
            if node in visiting:
                return True
            if node in visited:
                return False
            visiting.add(node)
            if any(visit(target) for target in graph.get(node, ())):
                return True
            visiting.remove(node)
            visited.add(node)
            return False

        return any(visit(node) for node in graph)

    def _scene_rule_items(
        self,
        scene: object,
        chapter_index: int,
        content: str,
    ) -> tuple[list[dict], str | None]:
        from modules.story.contracts import scene_semantic_field_status

        chapter_chunks: list[dict] = []
        for chunk in getattr(scene, "scene_chunks", None) or []:
            if not isinstance(chunk, dict):
                continue
            raw_chapter = chunk.get("chapter_index", chunk.get("chapter_id"))
            try:
                if int(raw_chapter) == chapter_index:
                    chapter_chunks.append(chunk)
            except (TypeError, ValueError):
                continue
        if not chapter_chunks:
            return [], "missing_for_chapter"

        current_content_hash = hash_text(content)
        if any(
            chunk.get("source_content_hash")
            and str(chunk["source_content_hash"]) != current_content_hash
            for chunk in chapter_chunks
        ):
            return [], "source_hash_mismatch"

        ranges: list[tuple[int, int]] = []
        for chunk in chapter_chunks:
            raw_start = chunk.get("start_offset", chunk.get("start_pos"))
            raw_end = chunk.get("end_offset", chunk.get("end_pos"))
            try:
                start = int(raw_start)
                end = int(raw_end)
            except (TypeError, ValueError):
                continue
            if 0 <= start < end <= len(content):
                ranges.append((start, end))
        if not ranges:
            return [], "invalid_for_content"

        ranges = sorted(set(ranges))
        if len(ranges) < len(chapter_chunks):
            return [], "partially_invalid_for_content"
        items = []
        scene_id = getattr(scene, "id", None)
        title = getattr(scene, "title", None) or "未命名 Scene"
        scene_label = f"Scene：{title}"
        must_not_status = scene_semantic_field_status(scene, "must_not_happen")
        must_status = scene_semantic_field_status(scene, "must_happen")
        must_not_phrases = (
            []
            if must_not_status is not None
            else _split_rule_phrases(getattr(scene, "must_not_happen", None))
        )
        must_phrases = (
            []
            if must_status is not None
            else _split_rule_phrases(getattr(scene, "must_happen", None))
        )
        for phrase in must_not_phrases:
            absolute_start = next(
                (
                    start + local_start
                    for start, end in ranges
                    if (local_start := content[start:end].find(phrase)) >= 0
                ),
                None,
            )
            if absolute_start is not None:
                items.append(
                    {
                        "kind": "forbidden_present",
                        "severity": "medium",
                        "source_module": "outline",
                        "source_type": "scene.must_not_happen",
                        "source_id": scene_id,
                        "evidence_summary": (
                            f"当前场景疑似涉及禁止发生项（仅字面命中）：{phrase}"
                        ),
                        "needs_review": True,
                        "location_json": evidence_location(
                            source_module="outline",
                            source_type="scene.must_not_happen",
                            source_id=scene_id,
                            source_label=scene_label,
                            source_field="禁止发生",
                            source_excerpt=phrase,
                            open_target={
                                "kind": "outline_scene",
                                "scene_id": scene_id,
                            },
                            text_range={
                                "target": "editor",
                                "start": absolute_start,
                                "end": absolute_start + len(phrase),
                                "quote": phrase,
                            },
                            needs_review_reason="字面命中不代表语义冲突，请结合上下文确认",
                        ),
                    }
                )
        for phrase in must_phrases:
            if not any(phrase in content[start:end] for start, end in ranges):
                items.append(
                    {
                        "kind": "required_missing",
                        "severity": "low",
                        "source_module": "outline",
                        "source_type": "scene.must_happen",
                        "source_id": scene_id,
                        "evidence_summary": (
                            f"当前场景未逐字出现必须发生项，需结合语义确认：{phrase}"
                        ),
                        "needs_review": True,
                        "location_json": evidence_location(
                            source_module="outline",
                            source_type="scene.must_happen",
                            source_id=scene_id,
                            source_label=scene_label,
                            source_field="必须发生",
                            source_excerpt=phrase,
                            open_target={
                                "kind": "outline_scene",
                                "scene_id": scene_id,
                            },
                            needs_review_reason="未逐字出现不代表剧情语义缺失，请人工确认",
                        ),
                    }
                )
        return items, None

    def _summary(
        self,
        items: list[dict],
        degraded_sources: list[str],
        omissions: list[dict[str, str]] | None = None,
    ) -> dict:
        by_severity: dict[str, int] = {}
        open_high = 0
        for item in items:
            severity = item["severity"]
            by_severity[severity] = by_severity.get(severity, 0) + 1
            if severity == "high" and item.get("status", "open") == "open":
                open_high += 1
        return {
            "total": len(items),
            "open_high_count": open_high,
            "by_severity": by_severity,
            "degraded_sources": sorted(set(degraded_sources)),
            "omissions": omissions or [],
        }

    def _to_check_response(
        self,
        check: object,
        items: list[object],
    ) -> WritingConflictCheckResponse:
        return WritingConflictCheckResponse.model_validate(
            {
                "id": check.id,
                "novel_id": check.novel_id,
                "chapter_index": check.chapter_index,
                "scene_id": check.scene_id,
                "draft_id": check.draft_id,
                "version_number": check.version_number,
                "scope": check.scope,
                "include_candidates": check.include_candidates,
                "status": check.status,
                "summary_json": public_conflict_summary(check.summary_json),
                "ai_review_enabled": check.ai_review_enabled,
                "ai_review_status": check.ai_review_status,
                "ai_review_confirmation_id": check.ai_review_confirmation_id,
                "ai_review_model": check.ai_review_model,
                "ai_review_error": check.ai_review_error,
                "items": [
                    WritingConflictItemResponse.model_validate(item) for item in items
                ],
                "created_at": check.created_at,
                "updated_at": check.updated_at,
            }
        )
