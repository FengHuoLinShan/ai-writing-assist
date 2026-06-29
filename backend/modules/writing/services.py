"""
Writing 业务逻辑层

调用 repository 完成业务操作。
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime

from fastapi import HTTPException
from fastapi import status as http_status
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.llm.client import LLMClient
from infrastructure.llm.schemas import LLMCallRequest, LLMMessage
from modules.context.markdown_renderer import render_compiled_context
from modules.outline.facade import split_scene_chunk_to_new_chapter
from modules.writing.conflict_ai import (
    ConflictCheckAiReviewService,
    ConflictSuggestionService,
)
from modules.writing.conflict_evidence import evidence_location
from modules.writing.contracts import WritingDraftContract
from modules.writing.repositories import (
    WritingConflictCheckRepository,
    WritingDraftRepository,
)
from modules.writing.schemas import (
    ChapterSplitResponse,
    DraftListItem,
    VersionHistoryResponse,
    WritingConflictAiReviewRequest,
    WritingConflictAiSuggestionRequest,
    WritingConflictCheckCreate,
    WritingConflictCheckListResponse,
    WritingConflictCheckResponse,
    WritingConflictItemResponse,
    WritingConflictItemUpdate,
    WritingDraftCreate,
    WritingDraftResponse,
    WritingDraftUpdate,
)
from shared.utils import parse_uuid

logger = logging.getLogger(__name__)


class WritingDraftService:
    """正文草稿业务服务"""

    def __init__(self, repo: WritingDraftRepository | None = None) -> None:
        self._repo = repo or WritingDraftRepository()

    async def create_draft(
        self,
        db: AsyncSession,
        data: WritingDraftCreate,
    ) -> WritingDraftResponse:
        """创建新草稿版本（发布）"""
        draft = await self._repo.create(db, data)
        return WritingDraftResponse.model_validate(draft)

    async def get_draft(
        self,
        db: AsyncSession,
        draft_id: str,
        novel_id: str,
    ) -> WritingDraftResponse:
        """获取草稿详情"""
        did = parse_uuid(draft_id, "draft")
        nid = parse_uuid(novel_id, "novel")
        draft = await self._repo.get(db, did)
        if draft is None or str(draft.novel_id) != str(nid):
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Draft {draft_id} not found",
            )
        return WritingDraftResponse.model_validate(draft)

    async def update_draft(
        self,
        db: AsyncSession,
        draft_id: str,
        data: WritingDraftUpdate,
        novel_id: str,
    ) -> WritingDraftResponse:
        """暂存草稿（原地更新最新版本，不创建新版本）"""
        did = parse_uuid(draft_id, "draft")
        nid = parse_uuid(novel_id, "novel")
        draft = await self._repo.get(db, did)
        if draft is None or str(draft.novel_id) != str(nid):
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Draft {draft_id} not found",
            )
        # 多 Tab 冲突检测：以章节最新版本为准
        latest = await self._repo.get_latest_by_chapter(
            db, draft.novel_id, draft.chapter_index
        )
        latest_version = latest.version_number if latest else draft.version_number
        latest_updated_at = latest.updated_at if latest else draft.updated_at

        if data.expected_updated_at is not None and latest_updated_at is not None:
            db_updated_at = _as_utc_aware(latest_updated_at)
            expected_updated_at = _as_utc_aware(data.expected_updated_at)
            if db_updated_at > expected_updated_at:
                raise HTTPException(
                    status_code=http_status.HTTP_409_CONFLICT,
                    detail=(
                        "该章节已被其他会话更新（当前修改时间晚于期望时间，"
                        "请刷新后重新编辑。"
                    ),
                )

        if data.expected_version is not None and latest_version != data.expected_version:
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail=(
                    f"该章节已被其他会话更新（当前版本 v{latest_version}，"
                    f"期望版本 v{data.expected_version}）。请刷新后重新编辑。"
                ),
            )
        updated = await self._repo.update(db, did, data)
        if updated is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Draft {draft_id} not found",
            )
        return WritingDraftResponse.model_validate(updated)

    async def delete_draft(
        self,
        db: AsyncSession,
        draft_id: str,
        novel_id: str,
    ) -> None:
        """删除单个版本（至少保留 1 个版本），并自动重排后续版本号"""
        did = parse_uuid(draft_id, "draft")
        nid = parse_uuid(novel_id, "novel")
        draft = await self._repo.get(db, did)
        if draft is None or str(draft.novel_id) != str(nid):
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Draft {draft_id} not found",
            )

        # 业务规则：至少保留 1 个版本
        version_count = await self._repo.count_versions(
            db,
            draft.novel_id,
            draft.chapter_index,
        )
        if version_count <= 1:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail="Cannot delete the last version of a chapter",
            )

        deleted = await self._repo.delete(db, did)
        if deleted is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Draft {draft_id} not found",
            )

        # 数据完整性：重排后续版本号
        await self._repo.renumber_versions_after_delete(
            db,
            draft.novel_id,
            draft.chapter_index,
            draft.version_number,
        )

    async def delete_chapter(
        self,
        db: AsyncSession,
        novel_id: str,
        chapter_index: int,
    ) -> int:
        """删除整章所有版本。返回删除的版本数。"""
        nid = parse_uuid(novel_id, "novel")
        return await self._repo.delete_all_versions(db, nid, chapter_index)

    async def get_latest_draft(
        self,
        db: AsyncSession,
        novel_id: str,
        chapter_index: int,
    ) -> WritingDraftResponse:
        """获取章节最新草稿"""
        nid = parse_uuid(novel_id, "novel")
        draft = await self._repo.get_latest_by_chapter(db, nid, chapter_index)
        if draft is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"No draft found for chapter {chapter_index} in novel {novel_id}",
            )
        return WritingDraftResponse.model_validate(draft)

    async def get_version_history(
        self,
        db: AsyncSession,
        novel_id: str,
        chapter_index: int,
    ) -> VersionHistoryResponse:
        """获取章节版本历史"""
        nid = parse_uuid(novel_id, "novel")
        versions = await self._repo.get_version_history(db, nid, chapter_index)
        items = []
        for v in versions:
            item = DraftListItem.model_validate(v)
            item.word_count = len(v.content) if v.content else 0
            items.append(item)
        return VersionHistoryResponse(
            novel_id=novel_id,
            chapter_index=chapter_index,
            versions=items,
            total=len(items),
        )

    async def set_conflict_check_snapshot(
        self,
        db: AsyncSession,
        draft_id: str,
        novel_id: str,
        snapshot: dict,
    ) -> WritingDraftResponse:
        did = parse_uuid(draft_id, "draft")
        nid = parse_uuid(novel_id, "novel")
        draft = await self._repo.get(db, did)
        if draft is None or draft.novel_id != nid:
            raise HTTPException(status_code=404, detail=f"Draft {draft_id} not found")
        updated = await self._repo.set_conflict_check_snapshot(db, did, snapshot)
        if updated is None:
            raise HTTPException(status_code=404, detail=f"Draft {draft_id} not found")
        return WritingDraftResponse.model_validate(updated)

    async def get_draft_contract(
        self,
        db: AsyncSession,
        draft_id: str,
    ) -> WritingDraftContract | None:
        """获取草稿契约（供其他模块使用，不存在返回 None）"""
        did = parse_uuid(draft_id, "draft")
        draft = await self._repo.get(db, did)
        if draft is None:
            return None
        return self._to_contract(draft)

    async def get_latest_draft_contract(
        self,
        db: AsyncSession,
        novel_id: str,
        chapter_index: int,
    ) -> WritingDraftContract | None:
        """获取章节最新草稿契约（供其他模块使用，不存在返回 None）"""
        nid = parse_uuid(novel_id, "novel")
        draft = await self._repo.get_latest_by_chapter(db, nid, chapter_index)
        if draft is None:
            return None
        return self._to_contract(draft)

    @staticmethod
    def _to_contract(draft: object) -> WritingDraftContract:
        """将 ORM draft 转为契约对象"""
        return WritingDraftContract(
            novel_id=str(draft.novel_id),  # type: ignore[union-attr]
            chapter_index=draft.chapter_index,  # type: ignore[union-attr]
            title=draft.title,  # type: ignore[union-attr]
            content=draft.content,  # type: ignore[union-attr]
            version_number=draft.version_number,  # type: ignore[union-attr]
            status=draft.status,  # type: ignore[union-attr]
        )

    async def list_chapter_indices(
        self,
        db: AsyncSession,
        novel_id: str,
    ) -> list[int]:
        """列出该小说所有有草稿的章节索引"""
        nid = parse_uuid(novel_id, "novel")
        return await self._repo.list_chapter_indices(db, nid)

    async def split_chapter_at_offset(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        chapter_index: int,
        split_pos: int,
        source_scene_id: str | None,
    ) -> ChapterSplitResponse:
        nid = parse_uuid(novel_id, "novel")
        latest = await self._repo.get_latest_by_chapter(db, nid, chapter_index)
        if latest is None:
            raise HTTPException(
                status_code=404,
                detail=f"No draft found for chapter {chapter_index}",
            )
        content = latest.content or ""
        if not (0 < split_pos < len(content)):
            raise HTTPException(
                status_code=422,
                detail="split_pos must be inside the chapter content",
            )

        head = content[:split_pos]
        tail = content[split_pos:]
        new_chapter_index = chapter_index + 1

        await self._repo.shift_chapter_indices_from(db, nid, new_chapter_index)
        source = await self._repo.update_latest_content(
            db,
            nid,
            chapter_index,
            title=latest.title,
            content=head,
        )
        new_draft = await self._repo.create(
            db,
            WritingDraftCreate(
                novel_id=novel_id,
                chapter_index=new_chapter_index,
                title=f"第{new_chapter_index}章",
                content=tail,
            ),
        )

        scenes: list[dict] = []
        if source_scene_id:
            scenes = await split_scene_chunk_to_new_chapter(
                db,
                novel_id,
                source_scene_id=source_scene_id,
                source_chapter_id=str(chapter_index),
                source_chapter_index=chapter_index,
                new_chapter_id=str(new_chapter_index),
                new_chapter_index=new_chapter_index,
                split_pos=split_pos,
                new_chapter_length=len(tail),
            )

        return ChapterSplitResponse(
            source_chapter_index=chapter_index,
            new_chapter_index=new_chapter_index,
            source_draft=WritingDraftResponse.model_validate(source),
            new_draft=WritingDraftResponse.model_validate(new_draft),
            scenes=scenes,
        )


class WritingConflictCheckService:
    """Rule-based Scene conflict checks for the writing workbench."""

    def __init__(
        self,
        repo: WritingConflictCheckRepository | None = None,
        draft_repo: WritingDraftRepository | None = None,
    ) -> None:
        self._repo = repo or WritingConflictCheckRepository()
        self._draft_repo = draft_repo or WritingDraftRepository()
        self._ai_review_service = ConflictCheckAiReviewService(self._repo)
        self._suggestion_service = ConflictSuggestionService(self._repo)

    async def create_check(
        self,
        db: AsyncSession,
        data: WritingConflictCheckCreate,
    ) -> WritingConflictCheckResponse:
        nid = parse_uuid(data.novel_id, "novel_id")
        scene_uuid = parse_uuid(data.scene_id, "scene_id") if data.scene_id else None
        draft_uuid = parse_uuid(data.draft_id, "draft_id") if data.draft_id else None
        if draft_uuid is not None:
            draft = await self._draft_repo.get(db, draft_uuid)
            if draft is None or draft.novel_id != nid:
                raise HTTPException(status_code=404, detail="Draft not found")

        items: list[dict] = []
        degraded_sources: list[str] = []
        if data.scene_id:
            scene = await self._load_scene(db, data.novel_id, data.scene_id)
            if scene is None:
                degraded_sources.append("outline")
            else:
                items.extend(self._scene_rule_items(scene, data.content or ""))

            map_items, map_degraded, map_summary = await self._map_rule_items(
                db,
                data.novel_id,
                data.scene_id,
                include_candidates=data.include_candidates,
            )
            items.extend(map_items)
            degraded_sources.extend(map_degraded)
        else:
            scene = None
            map_summary = None

        memory_items, memory_degraded = await self._memory_rule_items(
            db,
            data.novel_id,
            data.chapter_index,
            scene=scene,
            map_summary=map_summary,
        )
        items.extend(memory_items)
        degraded_sources.extend(memory_degraded)

        status = "degraded" if degraded_sources else "completed"
        summary_json = self._summary(items, degraded_sources)
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
                "content_excerpt": (data.content or "")[:4000],
                "content_char_count": len(data.content or ""),
                "sources": ["outline", "world.map", "memory"],
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
    ) -> WritingConflictCheckListResponse:
        nid = parse_uuid(novel_id, "novel_id")
        sid = parse_uuid(scene_id, "scene_id") if scene_id else None
        pairs, total = await self._repo.list_checks(
            db,
            novel_id=nid,
            chapter_index=chapter_index,
            scene_id=sid,
            limit=limit,
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
        nid = parse_uuid(novel_id, "novel_id")
        cid = parse_uuid(check_id, "check_id")
        result = await self._repo.get_check(db, cid, nid)
        if result is None:
            raise HTTPException(status_code=404, detail="Conflict check not found")
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
        nid = parse_uuid(novel_id, "novel_id")
        iid = parse_uuid(item_id, "item_id")
        item = await self._repo.update_item_status(
            db,
            item_id=iid,
            novel_id=nid,
            status=data.status,
        )
        if item is None:
            raise HTTPException(status_code=404, detail="Conflict item not found")
        return WritingConflictItemResponse.model_validate(item)

    async def run_ai_review(
        self,
        db: AsyncSession,
        *,
        check_id: str,
        data: WritingConflictAiReviewRequest,
    ) -> WritingConflictCheckResponse:
        check, items = await self._ai_review_service.run(
            db,
            novel_id=data.novel_id,
            check_id=check_id,
            context_confirmation_id=data.context_confirmation_id,
        )
        return self._to_check_response(check, items)

    async def generate_ai_suggestion(
        self,
        db: AsyncSession,
        *,
        item_id: str,
        data: WritingConflictAiSuggestionRequest,
    ) -> WritingConflictItemResponse:
        item = await self._suggestion_service.generate(
            db,
            novel_id=data.novel_id,
            item_id=item_id,
            context_confirmation_id=data.context_confirmation_id,
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
        nid = parse_uuid(novel_id, "novel_id")
        sid = parse_uuid(scene_id, "scene_id") if scene_id else None
        return await self._repo.build_latest_snapshot(
            db,
            novel_id=nid,
            chapter_index=chapter_index,
            scene_id=sid,
        )

    async def _load_scene(self, db: AsyncSession, novel_id: str, scene_id: str):
        try:
            from modules.outline.facade import get_scene_contract

            return await get_scene_contract(db, novel_id, scene_id)
        except Exception:
            logger.exception("Failed to load scene for conflict check")
            return None

    def _scene_rule_items(self, scene: object, content: str) -> list[dict]:
        items = []
        scene_id = getattr(scene, "id", None)
        title = getattr(scene, "title", None) or "未命名 Scene"
        scene_label = f"Scene：{title}"
        for phrase in _split_rule_phrases(getattr(scene, "must_not_happen", None)):
            text_range = _locate_phrase(content, phrase)
            if phrase in content:
                items.append(
                    {
                        "kind": "forbidden_present",
                        "severity": "high",
                        "source_module": "outline",
                        "source_type": "scene.must_not_happen",
                        "source_id": scene_id,
                        "evidence_summary": f"正文出现 Scene 禁止发生项：{phrase}",
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
                            text_range=text_range,
                        ),
                    }
                )
        for phrase in _split_rule_phrases(getattr(scene, "must_happen", None)):
            if phrase not in content:
                items.append(
                    {
                        "kind": "required_missing",
                        "severity": "medium",
                        "source_module": "outline",
                        "source_type": "scene.must_happen",
                        "source_id": scene_id,
                        "evidence_summary": f"正文尚未覆盖 Scene 必须发生项：{phrase}",
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
                        ),
                    }
                )
        return items

    async def _map_rule_items(
        self,
        db: AsyncSession,
        novel_id: str,
        scene_id: str,
        *,
        include_candidates: bool,
    ) -> tuple[list[dict], list[str], object | None]:
        try:
            from modules.world.map_facade import summarize_scene_map_for_writing

            summary = await summarize_scene_map_for_writing(
                db,
                novel_id,
                scene_id,
                include_candidates=include_candidates,
            )
        except Exception:
            logger.exception("Failed to load map summary for conflict check")
            return [], ["world.map"], None

        degraded = []
        if (
            include_candidates
            and _read_field(summary, "candidate_support") == "unsupported"
        ):
            degraded.append("world.map.candidates")

        items = []
        risks = _read_field(summary, "risks", []) or []
        warnings = _read_field(summary, "warnings", []) or []
        for warning in [*risks, *warnings]:
            message = (
                _read_field(warning, "message")
                or _read_field(warning, "code")
                or "地图状态需复核"
            )
            depends_on_candidate = bool(
                _read_field(warning, "depends_on_candidate")
            )
            evidence_excerpt = _read_field(warning, "evidence_excerpt") or message
            open_target = _read_field(warning, "open_target") or {
                "kind": "map_scene",
                "scene_id": scene_id,
            }
            needs_review_reason = (
                "依赖待确认地图观察" if depends_on_candidate else None
            )
            severity = "medium" if _read_field(warning, "level") == "warning" else "low"
            items.append(
                {
                    "kind": "map_risk",
                    "severity": severity,
                    "source_module": "world",
                    "source_type": "map.scene_summary",
                    "source_id": scene_id,
                    "evidence_summary": message,
                    "location_json": evidence_location(
                        source_module="world",
                        source_type="map.scene_summary",
                        source_id=scene_id,
                        source_label="地图摘要",
                        source_field="地图风险",
                        source_excerpt=str(evidence_excerpt),
                        open_target=open_target,
                        needs_review_reason=needs_review_reason,
                    ),
                    "needs_review": depends_on_candidate,
                }
            )
        return items, degraded, summary

    async def _memory_rule_items(
        self,
        db: AsyncSession,
        novel_id: str,
        chapter_index: int,
        *,
        scene: object | None,
        map_summary: object | None,
    ) -> tuple[list[dict], list[str]]:
        if scene is None or map_summary is None:
            return [], []

        pov_character_id = getattr(scene, "pov_character_id", None)
        primary_location = _read_field(map_summary, "primary_location")
        current_location_id = _read_field(primary_location, "entity_id")
        current_label = _read_field(primary_location, "name") or current_location_id

        try:
            from modules.memory.facade import get_continuity_evidence_for_writing

            evidence = await get_continuity_evidence_for_writing(
                db,
                novel_id,
                chapter_index,
                pov_character_id=pov_character_id,
                current_location_id=current_location_id,
                current_location_name=current_label,
            )
        except Exception:
            logger.exception("Failed to load memory evidence for conflict check")
            return [], ["memory"]

        if evidence is None:
            return [], []

        return [
            {
                "kind": "continuity_location_mismatch",
                "severity": "medium",
                "source_module": evidence.source_module,
                "source_type": evidence.source_type,
                "source_id": evidence.source_id,
                "evidence_summary": evidence.source_excerpt,
                "location_json": evidence_location(
                    source_module=evidence.source_module,
                    source_type=evidence.source_type,
                    source_id=evidence.source_id,
                    source_label=evidence.source_label,
                    source_field=evidence.source_field,
                    source_excerpt=evidence.source_excerpt,
                    open_target=evidence.open_target,
                ),
            }
        ], []

    def _summary(self, items: list[dict], degraded_sources: list[str]) -> dict:
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
                "summary_json": check.summary_json,
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


class WritingGenerationService:
    """AI 正文候选草稿生成服务。"""

    def __init__(
        self,
        repo: WritingDraftRepository | None = None,
        llm_client: LLMClient | None = None,
    ) -> None:
        self._repo = repo or WritingDraftRepository()
        self._llm = llm_client or LLMClient()

    async def generate_candidate(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        chapter_index: int,
        title: str | None,
        instruction: str | None,
        context_confirmation_id: str,
    ) -> WritingDraftResponse:
        from modules.context.facade import compile_from_confirmation

        compiled_context = await compile_from_confirmation(
            db,
            novel_id=novel_id,
            action="writing.generate",
            confirmation_id=context_confirmation_id,
        )
        context_markdown = render_compiled_context(compiled_context)
        prompt = _build_writing_generation_prompt(
            chapter_index=chapter_index,
            instruction=instruction,
            context_markdown=context_markdown,
        )
        response = await self._llm.generate(
            LLMCallRequest(
                model=getattr(self._llm, "model_name", "gpt-4o"),
                messages=[
                    LLMMessage(
                        role="system",
                        content=(
                            "你是小说正文生成助手。输出正文候选稿本身，"
                            "不要添加解释、标题栏或 Markdown 围栏。"
                        ),
                    ),
                    LLMMessage(role="user", content=prompt),
                ],
                temperature=0.7,
                max_tokens=4096,
            )
        )
        draft = await self._repo.create_with_status(
            db,
            WritingDraftCreate(
                novel_id=novel_id,
                chapter_index=chapter_index,
                title=title or f"第{chapter_index}章 AI 候选",
                content=response.content.strip(),
            ),
            status="candidate",
        )
        return WritingDraftResponse.model_validate(draft)


def _build_writing_generation_prompt(
    *,
    chapter_index: int,
    instruction: str | None,
    context_markdown: str,
) -> str:
    note = instruction.strip() if instruction else "无额外要求"
    return (
        f"请基于以下已确认的 AI 参考资料，生成第 {chapter_index} 章的正文候选稿。\n\n"
        f"本次额外要求：{note}\n\n"
        f"## AI 参考资料\n\n{context_markdown}"
    )


def _split_rule_phrases(value: str | None) -> list[str]:
    if not value:
        return []
    return [
        part.strip()
        for part in re.split(r"[；;，,\n。]+", value)
        if part.strip()
    ]


def _locate_phrase(content: str, phrase: str) -> dict:
    index = content.find(phrase)
    if index < 0:
        return {"target": "editor"}
    return {
        "target": "editor",
        "start": index,
        "end": index + len(phrase),
        "quote": phrase,
    }


def _read_field(value: object, field: str, default: object | None = None) -> object:
    if value is None:
        return default
    if isinstance(value, dict):
        return value.get(field, default)
    return getattr(value, field, default)


def _as_utc_aware(dt: datetime) -> datetime:
    """将可能为 naive 的 datetime 统一转为 UTC aware，便于比较。"""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)
