"""
Writing 业务逻辑层

调用 repository 完成业务操作。
"""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ConflictError, NotFoundError, ValidationError
from infrastructure.llm.agent_step_harness import run_managed_generate
from infrastructure.llm.client import LLMClient
from infrastructure.llm.schemas import LLMCallRequest, LLMMessage
from modules.writing.conflict_ai import (
    AI_REVIEW_ACTION,
    ConflictCheckAiReviewService,
    ConflictSuggestionService,
    validate_ai_review_confirmation_scope,
)
from modules.writing.conflict_evidence import evidence_location
from modules.writing.contracts import WritingDraftContract, WritingProjectStatsContract
from modules.writing.pov_generation import (
    POV_PROMPT_NAME,
    CharacterRevealGuard,
    GenerationProfile,
    GenerationProfileResolver,
    PovGenerationParser,
    build_pov_generation_prompt,
    prompt_hash,
)
from modules.writing.repositories import (
    WritingConflictCheckRepository,
    WritingDraftRepository,
)
from modules.writing.schemas import (
    ChapterSplitResponse,
    ChapterSummaryItem,
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
from modules.writing.text_sanitizer import sanitize_writing_text
from shared.utils import parse_uuid as _shared_parse_uuid

logger = logging.getLogger(__name__)

SceneChunkSplitProvider = Callable[..., Awaitable[list[dict[str, Any]]]]
SceneContractLoader = Callable[[AsyncSession, str, str], Awaitable[object | None]]


async def _default_split_scene_chunk_to_new_chapter(
    db: AsyncSession,
    novel_id: str,
    *,
    source_scene_id: str,
    source_chapter_id: str,
    source_chapter_index: int,
    new_chapter_id: str,
    new_chapter_index: int,
    split_pos: int,
    new_chapter_length: int,
) -> list[dict[str, Any]]:
    from modules.outline.facade import split_scene_chunk_to_new_chapter

    return await split_scene_chunk_to_new_chapter(
        db,
        novel_id,
        source_scene_id=source_scene_id,
        source_chapter_id=source_chapter_id,
        source_chapter_index=source_chapter_index,
        new_chapter_id=new_chapter_id,
        new_chapter_index=new_chapter_index,
        split_pos=split_pos,
        new_chapter_length=new_chapter_length,
    )


async def _default_scene_contract_loader(
    db: AsyncSession,
    novel_id: str,
    scene_id: str,
) -> object | None:
    from modules.outline.facade import get_scene_contract

    return await get_scene_contract(db, novel_id, scene_id)


def _sanitize_draft_create(
    data: WritingDraftCreate,
) -> tuple[WritingDraftCreate, dict[str, bool]]:
    title = sanitize_writing_text(data.title)
    content = sanitize_writing_text(data.content)
    return data.model_copy(update={"title": title.text, "content": content.text}), {
        "title_html_removed": title.html_removed,
        "content_html_removed": content.html_removed,
    }


def _sanitize_draft_update(data: WritingDraftUpdate) -> WritingDraftUpdate:
    updates: dict[str, str | None] = {}
    if data.title is not None:
        updates["title"] = sanitize_writing_text(data.title).text
    if data.content is not None:
        updates["content"] = sanitize_writing_text(data.content).text
    return data.model_copy(update=updates) if updates else data


def _parse_uuid(value: str, field_name: str = "id") -> uuid.UUID:
    return _shared_parse_uuid(value, field_name)


class WritingDraftService:
    """正文草稿业务服务"""

    def __init__(
        self,
        repo: WritingDraftRepository | None = None,
        split_scene_chunk_to_new_chapter: SceneChunkSplitProvider | None = None,
    ) -> None:
        self._repo = repo or WritingDraftRepository()
        self._split_scene_chunk_to_new_chapter = (
            split_scene_chunk_to_new_chapter
            or _default_split_scene_chunk_to_new_chapter
        )

    async def create_draft(
        self,
        db: AsyncSession,
        data: WritingDraftCreate,
    ) -> WritingDraftResponse:
        """创建新草稿版本（发布）"""
        sanitized_data, _summary = _sanitize_draft_create(data)
        draft = await self._repo.create(db, sanitized_data)
        return WritingDraftResponse.model_validate(draft)

    async def create_published_draft(
        self,
        db: AsyncSession,
        data: WritingDraftCreate,
    ) -> WritingDraftResponse:
        """创建已发布的正文版本。"""
        sanitized_data, _summary = _sanitize_draft_create(data)
        draft = await self._repo.create_with_status(
            db,
            sanitized_data,
            status="published",
        )
        return WritingDraftResponse.model_validate(draft)

    async def create_draft_contract(
        self,
        db: AsyncSession,
        data: WritingDraftCreate,
    ) -> WritingDraftContract:
        """创建草稿并返回跨模块契约。"""
        draft = await self.create_draft(db, data)
        return self._to_contract(draft)

    async def create_published_draft_contract(
        self,
        db: AsyncSession,
        data: WritingDraftCreate,
    ) -> WritingDraftContract:
        """创建已发布正文版本并返回跨模块契约。"""
        draft = await self.create_published_draft(db, data)
        return self._to_contract(draft)

    async def publish_draft(
        self,
        db: AsyncSession,
        data: WritingDraftCreate,
    ) -> WritingDraftResponse:
        """发布章节正文；最新已发布内容相同时复用版本，避免重复版本膨胀。"""
        sanitized_data, _summary = _sanitize_draft_create(data)
        nid = _parse_uuid(sanitized_data.novel_id, "novel")
        latest = await self._repo.get_latest_by_chapter(
            db,
            nid,
            sanitized_data.chapter_index,
        )
        if (
            latest is not None
            and latest.status == "published"
            and (latest.title or "") == (sanitized_data.title or "")
            and (latest.content or "") == (sanitized_data.content or "")
        ):
            return WritingDraftResponse.model_validate(latest)

        return await self.create_published_draft(db, sanitized_data)

    async def get_draft(
        self,
        db: AsyncSession,
        draft_id: str,
        novel_id: str,
    ) -> WritingDraftResponse:
        """获取草稿详情"""
        did = _parse_uuid(draft_id, "draft")
        nid = _parse_uuid(novel_id, "novel")
        draft = await self._repo.get(db, did)
        if draft is None or str(draft.novel_id) != str(nid):
            raise NotFoundError(f"Draft {draft_id} not found")
        return WritingDraftResponse.model_validate(draft)

    async def update_draft(
        self,
        db: AsyncSession,
        draft_id: str,
        data: WritingDraftUpdate,
        novel_id: str,
    ) -> WritingDraftResponse:
        """暂存草稿（原地更新最新版本，不创建新版本）"""
        did = _parse_uuid(draft_id, "draft")
        nid = _parse_uuid(novel_id, "novel")
        draft = await self._repo.get(db, did)
        if draft is None or str(draft.novel_id) != str(nid):
            raise NotFoundError(f"Draft {draft_id} not found")
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
                raise ConflictError(
                    "该章节已被其他会话更新（当前修改时间晚于期望时间，"
                    "请刷新后重新编辑。"
                )

        if data.expected_version is not None and latest_version != data.expected_version:
            raise ConflictError(
                f"该章节已被其他会话更新（当前版本 v{latest_version}，"
                f"期望版本 v{data.expected_version}）。请刷新后重新编辑。"
            )
        sanitized_data = _sanitize_draft_update(data)
        updated = await self._repo.update(db, draft, sanitized_data)
        if updated is None:
            raise NotFoundError(f"Draft {draft_id} not found")
        return WritingDraftResponse.model_validate(updated)

    async def delete_draft(
        self,
        db: AsyncSession,
        draft_id: str,
        novel_id: str,
    ) -> None:
        """删除单个版本（至少保留 1 个版本），并自动重排后续版本号"""
        did = _parse_uuid(draft_id, "draft")
        nid = _parse_uuid(novel_id, "novel")
        draft = await self._repo.get(db, did)
        if draft is None or str(draft.novel_id) != str(nid):
            raise NotFoundError(f"Draft {draft_id} not found")

        # 业务规则：至少保留 1 个版本
        version_count = await self._repo.count_versions(
            db,
            draft.novel_id,
            draft.chapter_index,
        )
        if version_count <= 1:
            raise ValidationError("Cannot delete the last version of a chapter")

        deleted = await self._repo.delete(db, did)
        if deleted is None:
            raise NotFoundError(f"Draft {draft_id} not found")

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
        nid = _parse_uuid(novel_id, "novel")
        return await self._repo.delete_all_versions(db, nid, chapter_index)

    async def get_latest_draft(
        self,
        db: AsyncSession,
        novel_id: str,
        chapter_index: int,
    ) -> WritingDraftResponse:
        """获取章节最新草稿"""
        nid = _parse_uuid(novel_id, "novel")
        draft = await self._repo.get_latest_by_chapter(db, nid, chapter_index)
        if draft is None:
            raise NotFoundError(
                f"No draft found for chapter {chapter_index} in novel {novel_id}"
            )
        return WritingDraftResponse.model_validate(draft)

    async def get_version_history(
        self,
        db: AsyncSession,
        novel_id: str,
        chapter_index: int,
    ) -> VersionHistoryResponse:
        """获取章节版本历史"""
        nid = _parse_uuid(novel_id, "novel")
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
        did = _parse_uuid(draft_id, "draft")
        nid = _parse_uuid(novel_id, "novel")
        draft = await self._repo.get(db, did)
        if draft is None or draft.novel_id != nid:
            raise NotFoundError(f"Draft {draft_id} not found")
        updated = await self._repo.set_conflict_check_snapshot(db, did, snapshot)
        if updated is None:
            raise NotFoundError(f"Draft {draft_id} not found")
        return WritingDraftResponse.model_validate(updated)

    async def get_draft_contract(
        self,
        db: AsyncSession,
        novel_id: str,
        draft_id: str,
    ) -> WritingDraftContract | None:
        """获取草稿契约（供其他模块使用，不存在返回 None）"""
        nid = _parse_uuid(novel_id, "novel")
        did = _parse_uuid(draft_id, "draft")
        draft = await self._repo.get(db, did)
        if draft is None or draft.novel_id != nid:
            return None
        return self._to_contract(draft)

    async def get_latest_draft_contract(
        self,
        db: AsyncSession,
        novel_id: str,
        chapter_index: int,
    ) -> WritingDraftContract | None:
        """获取章节最新草稿契约（供其他模块使用，不存在返回 None）"""
        nid = _parse_uuid(novel_id, "novel")
        draft = await self._repo.get_latest_by_chapter(db, nid, chapter_index)
        if draft is None:
            return None
        return self._to_contract(draft)

    async def list_latest_draft_contracts(
        self,
        db: AsyncSession,
        novel_id: str,
        chapter_indices: list[int],
        *,
        content_limit: int | None = None,
    ) -> list[WritingDraftContract]:
        """批量获取章节最新草稿契约（供跨模块范围加载使用）。"""
        if content_limit is not None and content_limit <= 0:
            raise ValueError("content_limit must be a positive integer")
        nid = _parse_uuid(novel_id, "novel")
        requested = sorted({idx for idx in chapter_indices if idx >= 1})
        if not requested:
            return []
        drafts = await self._repo.list_latest_by_chapters(
            db,
            nid,
            requested,
            content_limit=content_limit,
        )
        if content_limit is None:
            return [self._to_contract(draft) for draft in drafts]
        return [self._projection_to_contract(draft) for draft in drafts]

    @staticmethod
    def _to_contract(draft: object) -> WritingDraftContract:
        """将 ORM draft 转为契约对象"""
        return WritingDraftContract(
            id=str(draft.id) if getattr(draft, "id", None) is not None else None,
            novel_id=str(draft.novel_id),  # type: ignore[union-attr]
            chapter_index=draft.chapter_index,  # type: ignore[union-attr]
            title=draft.title,  # type: ignore[union-attr]
            content=draft.content,  # type: ignore[union-attr]
            version_number=draft.version_number,  # type: ignore[union-attr]
            status=draft.status,  # type: ignore[union-attr]
            conflict_check_snapshot_json=draft.conflict_check_snapshot_json,  # type: ignore[union-attr]
            provenance_json=draft.provenance_json,  # type: ignore[union-attr]
            created_at=draft.created_at,  # type: ignore[union-attr]
            updated_at=draft.updated_at,  # type: ignore[union-attr]
        )

    @staticmethod
    def _projection_to_contract(row: object) -> WritingDraftContract:
        """将最新草稿投影结果转为契约对象。"""
        mapping = row._mapping if hasattr(row, "_mapping") else row  # noqa: SLF001
        return WritingDraftContract(
            id=str(mapping["id"]) if mapping["id"] is not None else None,  # type: ignore[index]
            novel_id=str(mapping["novel_id"]),  # type: ignore[index]
            chapter_index=mapping["chapter_index"],  # type: ignore[index]
            title=mapping["title"],  # type: ignore[index]
            content=mapping["content"],  # type: ignore[index]
            version_number=mapping["version_number"],  # type: ignore[index]
            status=mapping["status"],  # type: ignore[index]
            conflict_check_snapshot_json=mapping["conflict_check_snapshot_json"],  # type: ignore[index]
            provenance_json=mapping["provenance_json"],  # type: ignore[index]
            created_at=mapping["created_at"],  # type: ignore[index]
            updated_at=mapping["updated_at"],  # type: ignore[index]
        )

    async def list_chapter_indices(
        self,
        db: AsyncSession,
        novel_id: str,
    ) -> list[int]:
        """列出该小说所有有草稿的章节索引"""
        nid = _parse_uuid(novel_id, "novel")
        return await self._repo.list_chapter_indices(db, nid)

    async def list_chapter_summaries(
        self,
        db: AsyncSession,
        novel_id: str,
    ) -> list[ChapterSummaryItem]:
        """列出每章最新版本摘要。"""
        nid = _parse_uuid(novel_id, "novel")
        drafts = await self._repo.list_chapter_summaries(db, nid)
        return [
            ChapterSummaryItem(
                id=str(draft.id),
                chapter_index=draft.chapter_index,
                title=draft.title,
                word_count=len(draft.content or ""),
                version_number=draft.version_number,
                status=draft.status,
                updated_at=draft.updated_at,
            )
            for draft in drafts
        ]

    async def get_project_stats(
        self,
        db: AsyncSession,
        novel_id: str,
    ) -> WritingProjectStatsContract:
        """统计该小说正文草稿概览（每章只取最新版本）。"""
        nid = _parse_uuid(novel_id, "novel")
        chapter_count, word_count = await self._repo.project_stats(db, nid)
        return WritingProjectStatsContract(
            novel_id=str(nid),
            chapter_count=chapter_count,
            word_count=word_count,
        )

    async def list_project_stats(
        self,
        db: AsyncSession,
        novel_ids: list[str],
    ) -> dict[str, WritingProjectStatsContract]:
        """批量统计多个项目正文概览（每章只取最新版本）。"""
        parsed_ids = [_parse_uuid(novel_id, "novel") for novel_id in novel_ids]
        raw_stats = await self._repo.project_stats_many(db, parsed_ids)
        return {
            str(novel_id): WritingProjectStatsContract(
                novel_id=str(novel_id),
                chapter_count=raw_stats.get(novel_id, (0, 0))[0],
                word_count=raw_stats.get(novel_id, (0, 0))[1],
            )
            for novel_id in parsed_ids
        }

    async def split_chapter_at_offset(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        chapter_index: int,
        split_pos: int,
        source_scene_id: str | None,
    ) -> ChapterSplitResponse:
        nid = _parse_uuid(novel_id, "novel")
        latest = await self._repo.get_latest_by_chapter(db, nid, chapter_index)
        if latest is None:
            raise NotFoundError(f"No draft found for chapter {chapter_index}")
        content = latest.content or ""
        if not (0 < split_pos < len(content)):
            raise ValidationError(
                "split_pos must be inside the chapter content",
                status_code=422,
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
            scenes = await self._split_scene_chunk_to_new_chapter(
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
        scene_contract_loader: SceneContractLoader | None = None,
    ) -> None:
        self._repo = repo or WritingConflictCheckRepository()
        self._draft_repo = draft_repo or WritingDraftRepository()
        self._scene_contract_loader = (
            scene_contract_loader or _default_scene_contract_loader
        )
        self._ai_review_service = ConflictCheckAiReviewService(self._repo)
        self._suggestion_service = ConflictSuggestionService(self._repo)

    async def create_check(
        self,
        db: AsyncSession,
        data: WritingConflictCheckCreate,
    ) -> WritingConflictCheckResponse:
        nid = _parse_uuid(data.novel_id, "novel_id")
        scene_uuid = _parse_uuid(data.scene_id, "scene_id") if data.scene_id else None
        draft_uuid = _parse_uuid(data.draft_id, "draft_id") if data.draft_id else None
        if draft_uuid is not None:
            draft = await self._draft_repo.get(db, draft_uuid)
            if draft is None or draft.novel_id != nid:
                raise NotFoundError("Draft not found")

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
        nid = _parse_uuid(novel_id, "novel_id")
        sid = _parse_uuid(scene_id, "scene_id") if scene_id else None
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

    async def start_ai_review_task(
        self,
        db: AsyncSession,
        *,
        check_id: str,
        data: WritingConflictAiReviewRequest,
    ) -> WritingConflictCheckResponse:
        from modules.context.facade import prepare_confirmed_ai_action

        nid = _parse_uuid(data.novel_id, "novel_id")
        cid = _parse_uuid(check_id, "check_id")
        confirmation_uuid = _parse_uuid(
            data.context_confirmation_id,
            "context_confirmation_id",
        )
        existing = await self._repo.get_check(db, cid, nid)
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
        nid = _parse_uuid(novel_id, "novel_id")
        sid = _parse_uuid(scene_id, "scene_id") if scene_id else None
        return await self._repo.build_latest_snapshot(
            db,
            novel_id=nid,
            chapter_index=chapter_index,
            scene_id=sid,
        )

    async def _load_scene(self, db: AsyncSession, novel_id: str, scene_id: str):
        try:
            return await self._scene_contract_loader(db, novel_id, scene_id)
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
        self._profile_resolver = GenerationProfileResolver()
        self._pov_parser = PovGenerationParser()
        self._pov_guard = CharacterRevealGuard()

    async def generate_candidate(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        chapter_index: int,
        title: str | None,
        instruction: str | None,
        context_confirmation_id: str,
        source_task_id: str | None = None,
    ) -> WritingDraftResponse:
        from modules.context.facade import (
            build_hidden_guard_context,
            prepare_confirmed_ai_action,
        )

        confirmed_context = await prepare_confirmed_ai_action(
            db,
            novel_id=novel_id,
            action="writing.generate",
            confirmation_id=context_confirmation_id,
        )
        profile = self._profile_resolver.resolve(confirmed_context)
        is_pov = profile.profile == GenerationProfile.POV_CHARACTER
        if is_pov:
            prompt = build_pov_generation_prompt(
                chapter_index=chapter_index,
                instruction=instruction,
                context_markdown=confirmed_context.rendered_markdown,
            )
            system_prompt = (
                "你是小说角色视角生成助手。必须输出合法 JSON object，"
                "不要添加解释、标题栏或 Markdown 围栏。"
            )
            response_format = {"type": "json_object"}
        else:
            prompt = _build_writing_generation_prompt(
                chapter_index=chapter_index,
                instruction=instruction,
                context_markdown=confirmed_context.rendered_markdown,
            )
            system_prompt = (
                "你是小说正文生成助手。输出正文候选稿本身，"
                "不要添加解释、标题栏或 Markdown 围栏。"
            )
            response_format = None

        response = await run_managed_generate(
            self._llm,
            LLMCallRequest(
                model=getattr(self._llm, "model_name", "gpt-4o"),
                messages=[
                    LLMMessage(
                        role="system",
                        content=system_prompt,
                    ),
                    LLMMessage(role="user", content=prompt),
                ],
                temperature=0.7,
                max_tokens=4096,
                response_format=response_format,
            ),
            step_name="writing.generation.candidate.generate",
        )
        model_name = response.model or getattr(
            self._llm,
            "model_name",
            "gpt-4o",
        )

        pov_view = None
        pov_validation = {"status": "not_applicable", "findings": [], "warnings": []}
        content = response.content.strip()
        generation_profile = "default"
        prompt_name = "writing_default"
        parse_warnings: list[str] = []

        if is_pov:
            generation_profile = "pov_character"
            prompt_name = POV_PROMPT_NAME
            parsed = self._pov_parser.parse(response.content)
            content = parsed.content
            pov_view = parsed.pov_view
            parse_warnings = parsed.warnings
            content_sanitized = sanitize_writing_text(content)
            content = content_sanitized.text or ""
            guard_terms = await build_hidden_guard_context(
                db,
                confirmed_context=confirmed_context,
            )
            pov_validation = self._pov_guard.validate(
                pov_view=pov_view,
                draft_prose=content,
                guard_terms=guard_terms,
                warnings=parse_warnings,
            )
        else:
            content_sanitized = sanitize_writing_text(content)
            content = content_sanitized.text or ""

        candidate_title = title or f"第{chapter_index}章 AI 候选"
        title_sanitized = sanitize_writing_text(candidate_title)

        provenance = {
            "source": "writing_generate",
            "source_confirmation_id": context_confirmation_id,
            "source_task_id": source_task_id,
            "context_action": "writing.generate",
            "context_result_refs": confirmed_context.result_refs,
            "generation_profile": generation_profile,
            "context_confirmation_id": context_confirmation_id,
            "scene_id": profile.scene_id,
            "viewpoint_character_id": profile.viewpoint_character_id,
            "prompt_name": prompt_name,
            "prompt_hash": prompt_hash(prompt),
            "model": model_name,
            "pov_view": pov_view,
            "pov_validation": pov_validation,
            "content_sanitization": {
                "content_html_removed": content_sanitized.html_removed,
                "title_html_removed": title_sanitized.html_removed,
            },
        }
        draft = await self._repo.create_with_status(
            db,
            WritingDraftCreate(
                novel_id=novel_id,
                chapter_index=chapter_index,
                title=title_sanitized.text,
                content=content,
                provenance_json=provenance,
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
