"""Draft saving, versions, publishing and author adoption."""

from __future__ import annotations

import hashlib
import json
import uuid
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.container import get
from core.errors import ConflictError, NotFoundError, ValidationError
from core.service_keys import (
    ASSISTANT_EDITORIAL_POST_ADOPTION_RECHECKS,
    ASSISTANT_MARK_EDITORIAL_READY,
    EVIDENCE_CONFIRMATION_READS,
)
from infrastructure.llm.redaction import redact_diagnostic
from modules.project.contracts import WorkspaceCreationProgressItem
from modules.writing.contracts import (
    StoryChapterOrderPort,
    WritingDraftContract,
    WritingProjectStatsContract,
)
from modules.writing.models import (
    WritingChapterOrderOperation,
    WritingComment,
    WritingDraft,
)
from modules.writing.repositories import (
    INVALIDATION_VIEW_ATTR,
    WORKING_DRAFT_STATUSES,
    WritingDraftRepository,
)
from modules.writing.schemas import (
    ChapterOrderHistoryItem,
    ChapterOrderHistoryResponse,
    ChapterOrderPreviewRequest,
    ChapterOrderPreviewResponse,
    ChapterOrderRestorePreviewResponse,
    ChapterOrderResultResponse,
    ChapterSummaryItem,
    DraftListItem,
    EditorialReadyRequest,
    VersionHistoryResponse,
    WritingDraftCheckpoint,
    WritingDraftCreate,
    WritingDraftResponse,
    WritingDraftUpdate,
    WritingPublishRequest,
    WritingRegenerationContext,
    project_writing_draft_state,
)
from modules.writing.semantic_review import _requires_confirmed_context
from modules.writing.service_support import (
    _adoption_replay_result,
    _as_utc_aware,
    _mark_knowledge_review_stale,
    _mark_knowledge_review_stale_in_place,
    _parse_uuid,
    _progress_confirmation_id,
    _result_confirmation_id,
    _sanitize_draft_create,
    _sanitize_draft_update,
    logger,
)
from modules.writing.source_hashing import has_substantive_change, hash_text


class WritingDraftService:
    """正文草稿业务服务"""

    def __init__(
        self,
        repo: WritingDraftRepository | None = None,
    ) -> None:
        self._repo = repo or WritingDraftRepository()

    async def build_book_export(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        fmt: str,
        chapter_index: int | None = None,
    ) -> dict[str, Any]:
        """按章序导出每章当前已采用（published）版本。

        chapter_index 指定时只导该章。组装完成后复核各章版本与内容哈希
        清单，变化则抛冲突，不交付半新半旧的文件。未采用章节在导出结果
        中列出，不静默跳过。
        """
        from modules.project.facade import get_project_context, require_active_project

        await require_active_project(db, novel_id)
        if fmt not in {"txt", "md", "md-zip"}:
            raise ValidationError("导出格式只支持 txt、md、md-zip")
        context = await get_project_context(db, novel_id)
        if context is None:
            raise NotFoundError("Project not found")
        book_title = (context.title or "未命名作品").strip() or "未命名作品"

        nid = _parse_uuid(novel_id, "novel_id")
        published = await self._repo.list_chapter_summaries(
            db, nid, statuses=("published",)
        )
        if chapter_index is not None:
            published = [
                item for item in published if item.chapter_index == chapter_index
            ]
            if not published:
                raise ValidationError(
                    f"第 {chapter_index} 章还没有已采用的版本，先采用后再导出。"
                )
        working = await self._repo.list_chapter_summaries(db, nid)
        if chapter_index is not None:
            working = [item for item in working if item.chapter_index == chapter_index]
        published_chapters = {item.chapter_index for item in published}
        pending_chapters = sorted(
            item.chapter_index
            for item in working
            if item.chapter_index not in published_chapters
        )
        if not published:
            raise ValidationError(
                "还没有已采用的章节，先在写作台采用至少一章后再导出全书。"
            )

        manifest = [
            {
                "chapter_index": item.chapter_index,
                "title": item.title or "",
                "version_number": int(item.version_number),
                "content_hash": item.content_hash,
            }
            for item in published
        ]

        recheck = await self._repo.list_chapter_summaries(
            db,
            nid,
            statuses=("published",),
            # 同一会话第二次查询默认复用 identity map 里的旧对象，
            # 必须强制刷新才能看到导出期间的并发改版
            populate_existing=True,
        )
        if chapter_index is not None:
            recheck = [item for item in recheck if item.chapter_index == chapter_index]
        recheck_manifest = [
            {
                "chapter_index": item.chapter_index,
                "title": item.title or "",
                "version_number": int(item.version_number),
                "content_hash": item.content_hash,
            }
            for item in recheck
        ]
        if manifest != recheck_manifest:
            raise ConflictError(
                "导出期间章节版本发生变化，请稍后重试，不会交付半新半旧的文件。"
            )

        exported_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        chapters = sorted(published, key=lambda item: item.chapter_index)

        def chapter_heading(item) -> str:
            label = f"第 {item.chapter_index} 章"
            if item.title:
                label += f" {item.title}"
            return label

        header_lines = [
            f"书名：{book_title}",
            f"导出时间：{exported_at}",
            "版本口径：每章当前已采用（published）版本",
            "章节版本："
            + "；".join(
                f"第{item.chapter_index}章 v{item.version_number}"
                f"（{item.content_hash[:12]}）"
                for item in chapters
            ),
        ]
        if pending_chapters:
            header_lines.append(
                "未采用章节（有工作稿但未采用，未包含在本次导出中）：第"
                + "、第".join(str(index) for index in pending_chapters)
                + "章"
            )

        if fmt == "txt":
            parts = ["\n".join(header_lines), ""]
            for item in chapters:
                parts.append(f"===== {chapter_heading(item)} =====")
                parts.append(item.content or "")
                parts.append("")
            body = "\n".join(parts)
            return {
                "content": body.encode("utf-8"),
                "media_type": "text/plain; charset=utf-8",
                "filename": f"{book_title}.txt",
                "pending_chapters": pending_chapters,
            }

        if fmt == "md":
            parts = [f"# {book_title}", ""]
            parts.extend(f"> {line}" for line in header_lines[1:])
            parts.append("")
            for item in chapters:
                parts.append(f"## {chapter_heading(item)}")
                parts.append("")
                parts.append(item.content or "")
                parts.append("")
            body = "\n".join(parts)
            return {
                "content": body.encode("utf-8"),
                "media_type": "text/markdown; charset=utf-8",
                "filename": f"{book_title}.md",
                "pending_chapters": pending_chapters,
            }

        import io
        import zipfile

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            manifest_md = [f"# {book_title}", ""]
            manifest_md.extend(f"- {line}" for line in header_lines[1:])
            archive.writestr("manifest.md", "\n".join(manifest_md) + "\n")
            for item in chapters:
                chapter_md = [f"# {chapter_heading(item)}", "", item.content or ""]
                safe_title = "".join(
                    char if char.isalnum() or char in " _-" else "_"
                    for char in (item.title or "")
                ).strip()
                name = f"chapters/{item.chapter_index:04d}"
                if safe_title:
                    name += f"-{safe_title[:40]}"
                archive.writestr(f"{name}.md", "\n".join(chapter_md) + "\n")
        return {
            "content": buffer.getvalue(),
            "media_type": "application/zip",
            "filename": f"{book_title}-分章.zip",
            "pending_chapters": pending_chapters,
        }

    async def regeneration_context(
        self, db: AsyncSession, draft_id: str, novel_id: str
    ) -> WritingRegenerationContext:
        from modules.evidence.facade import require_confirmation
        from modules.writing.semantic_review import _candidate_confirmation_id

        draft = await self.get_draft(db, draft_id, novel_id)
        if draft.status != "candidate":
            raise ValidationError("请先打开待处理正文建议")
        provenance = draft.provenance_json or {}
        confirmation_id = _candidate_confirmation_id(provenance)
        original = None
        if confirmation_id:
            try:
                # Only read the original selection. This never freshens or rebinds it.
                original = await require_confirmation(
                    db,
                    novel_id=novel_id,
                    action="writing.generate",
                    confirmation_id=confirmation_id,
                )
            except (NotFoundError, ValidationError, ValueError):
                pass
        options: dict[str, Any] = {
            "scope": "chapter",
            "chapter_index": draft.chapter_index,
            "reveal_mode": "author_safe",
            "include_pending_objects": False,
        }
        if original:
            options.update(deepcopy(original.compile_options))
            options.update(
                scope=original.scope,
                context_mode=original.context_mode,
                include_pending_objects=original.include_pending_objects,
                excluded_asset_ids=deepcopy(original.excluded_asset_ids),
                user_note=original.user_note,
            )
            for key in ("pinned_refs", "excluded_refs"):
                if key in original.selection_state:
                    options[key] = deepcopy(original.selection_state[key])
        # Identity and operation are always supplied by the current server-owned draft.
        options.update(
            novel_id=novel_id,
            action="writing.generate",
            chapter_index=draft.chapter_index,
        )
        message = (
            "沿用原参考资料选择与排除项，重新整理确认后生成新版；旧建议保持不变。"
            if original
            else "原资料记录缺失。请为本章重新选材生成新版；旧建议仍不能通过原审查。"
        )
        options["task"] = message
        return WritingRegenerationContext(
            original_scope_available=original is not None,
            reference_options=options,
            message=message,
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

    async def create_published_draft_contracts(
        self,
        db: AsyncSession,
        data_items: list[WritingDraftCreate],
    ) -> list[WritingDraftContract]:
        sanitized = [_sanitize_draft_create(item)[0] for item in data_items]
        drafts = await self._repo.create_many_with_status(
            db,
            sanitized,
            status="published",
        )
        return [
            self._to_contract(WritingDraftResponse.model_validate(draft))
            for draft in drafts
        ]

    async def publish_draft_result(
        self,
        db: AsyncSession,
        data: WritingPublishRequest,
    ) -> tuple[WritingDraftResponse, bool]:
        """发布当前工作版本，返回（版本，是否新发布）。"""
        sanitized_data, _summary = _sanitize_draft_create(data)
        nid = _parse_uuid(sanitized_data.novel_id, "novel")
        await self._repo.lock_version_chapters_for_revalidation(
            db,
            nid,
            [sanitized_data.chapter_index],
        )
        latest = await self._repo.get_latest_by_chapter(
            db,
            nid,
            sanitized_data.chapter_index,
        )
        current = latest
        if data.draft_id:
            current = await self._repo.get_for_update(
                db, _parse_uuid(data.draft_id, "draft")
            )
            if (
                current is None
                or current.novel_id != nid
                or current.chapter_index != sanitized_data.chapter_index
            ):
                raise NotFoundError(f"Draft {data.draft_id} not found")
            if data.restore_source_version is not None:
                if current.version_number != data.restore_source_version:
                    raise ConflictError("历史版本已变化，请重新选择。")
                if current.status not in WORKING_DRAFT_STATUSES:
                    raise ConflictError("待审核或已归档版本仅供预览。")
                self._ensure_expected_snapshot(latest, data)
                restored = await self.create_published_draft(
                    db,
                    sanitized_data.model_copy(
                        update={
                            "provenance_json": {
                                **(sanitized_data.provenance_json or {}),
                                "base_draft_id": str(current.id),
                                "version_origin": "manual",
                                "restored_from_version": current.version_number,
                            }
                        }
                    ),
                )
                return restored, True
            self._ensure_latest_and_expected(current, latest, data)
        else:
            # 未携带 draft_id 的旧调用方同样要接受最新快照校验，避免绕过多 Tab 冲突检测
            self._ensure_expected_snapshot(latest, data)

        if current is not None and current.status == "draft":
            base = await self._get_base_draft(db, current)
            provenance = dict(current.provenance_json or {})
            if (
                provenance.get("version_origin") != "manual"
                and base is not None
                and not has_substantive_change(base.content, sanitized_data.content)
            ):
                await self._discard_loaded_draft(
                    db, current, base, "publish_without_substantive_change"
                )
                if base.status == "draft":
                    promoted = await self._promote_loaded_draft(db, base)
                    return promoted, True
                return WritingDraftResponse.model_validate(base), False

            promoted = await self._promote_loaded_draft(
                db,
                current,
                title=sanitized_data.title,
                content=sanitized_data.content,
                replace_content=True,
            )
            return promoted, True

        if current is not None and not has_substantive_change(
            current.content, sanitized_data.content
        ):
            return WritingDraftResponse.model_validate(current), False

        published = await self.create_published_draft(db, sanitized_data)
        return published, True

    async def publish_draft(
        self,
        db: AsyncSession,
        data: WritingDraftCreate | WritingPublishRequest,
    ) -> WritingDraftResponse:
        """兼容返回单个 response 的服务调用方。"""
        publish_data = (
            data
            if isinstance(data, WritingPublishRequest)
            else WritingPublishRequest(**data.model_dump())
        )
        result, _created = await self.publish_draft_result(db, publish_data)
        return result

    async def get_draft(
        self,
        db: AsyncSession,
        draft_id: str,
        novel_id: str,
        *,
        published_only: bool = False,
    ) -> WritingDraftResponse:
        """获取草稿详情"""
        did = _parse_uuid(draft_id, "draft")
        nid = _parse_uuid(novel_id, "novel")
        draft = await self._repo.get(db, did)
        if (
            draft is None
            or str(draft.novel_id) != str(nid)
            or (published_only and draft.status != "published")
        ):
            raise NotFoundError(f"Draft {draft_id} not found")
        response = WritingDraftResponse.model_validate(draft)
        if draft.status == "candidate":
            from modules.writing.semantic_review import validate_candidate_upstream

            try:
                await validate_candidate_upstream(
                    db,
                    draft,
                    require_review=False,
                )
            except ConflictError:
                response.attention_reasons = list(
                    dict.fromkeys([*response.attention_reasons, "upstream_stale"])
                )
        return response

    async def mark_editorial_ready(
        self,
        db: AsyncSession,
        draft_id: str,
        novel_id: str,
        data: EditorialReadyRequest,
    ) -> WritingDraftResponse:
        """Freeze the author's explicit completion signal for one saved version."""
        did = _parse_uuid(draft_id, "draft")
        nid = _parse_uuid(novel_id, "novel")
        draft = await self._repo.get(db, did)
        if draft is None or draft.novel_id != nid:
            raise NotFoundError(f"Draft {draft_id} not found")
        await self._repo.lock_version_chapters_for_revalidation(
            db, nid, [draft.chapter_index]
        )
        draft = await self._repo.get_for_update(db, did)
        if draft is None or draft.novel_id != nid:
            raise NotFoundError(f"Draft {draft_id} not found")
        latest = await self._repo.get_latest_by_chapter(db, nid, draft.chapter_index)
        if (
            latest is None
            or draft.id != latest.id
            or draft.status != "draft"
            or not (draft.content or "").strip()
        ):
            raise ConflictError("请先保存当前章节工作稿，再交给编辑查看")
        if draft.content_hash != data.expected_content_hash:
            raise ConflictError("正文已有新版本，请先保存并刷新")
        if draft.editorial_ready_hash != draft.content_hash:
            draft.editorial_ready_at = datetime.now(UTC)
            draft.editorial_ready_hash = draft.content_hash
            await db.flush()
            # AO-5：assistant facade 经组合根 DI 键解析，不 import。
            await get(ASSISTANT_MARK_EDITORIAL_READY)(
                db, novel_id, draft.chapter_index, str(draft.id), draft.content_hash
            )
        return WritingDraftResponse.model_validate(draft)

    async def adopt_candidate_to_working(
        self,
        db: AsyncSession,
        draft_id: str,
        novel_id: str,
        *,
        adopted_by: str = "author",
        idempotency_key: str | None = None,
    ) -> WritingDraftResponse:
        """Adopt one AI suggestion into the ordinary working-draft lifecycle.

        可选 ``idempotency_key`` 把一次采用钉成可重放回执：候选已因本次采用废弃
        后，携带同一键的重放返回原采用结果而不报错；无键或键不一致维持原校验错误。
        """
        did = _parse_uuid(draft_id, "draft")
        nid = _parse_uuid(novel_id, "novel")
        replay_key = str(idempotency_key or "").strip() or None
        draft = await self._repo.get(db, did)
        if draft is None or draft.novel_id != nid:
            raise NotFoundError(f"Draft {draft_id} not found")
        await self._repo.lock_version_chapters_for_revalidation(
            db,
            draft.novel_id,
            [draft.chapter_index],
        )
        draft = await self._repo.get_for_update(db, did)
        if draft is None or draft.novel_id != nid:
            raise NotFoundError(f"Draft {draft_id} not found")
        if draft.status != "candidate":
            replayed = await _adoption_replay_result(
                self._repo,
                db,
                draft,
                replay_key,
            )
            if replayed is not None:
                return replayed
            raise ValidationError("Only a candidate writing suggestion can be adopted")

        from modules.writing.semantic_review import validate_candidate_upstream

        await validate_candidate_upstream(db, draft)

        from modules.evidence.contracts import require_knowledge_review_for_adoption

        require_knowledge_review_for_adoption(
            dict(draft.provenance_json or {}),
            label="该 AI 正文候选",
        )

        adopted_at = datetime.now(UTC).isoformat()
        adopted_provenance = {
            **(draft.provenance_json or {}),
            "adopted_from_candidate_id": str(draft.id),
            "adopted_at": adopted_at,
            "adopted_by": adopted_by,
        }
        # 带问题采用：阻断项在上方门禁已挡下，能走到这里的非阻断 finding
        # 属作者决定延后处理的欠账；钉住问题标识与当时的检查版本/输出，
        # 供发布提示与质量追溯，不建独立问题真相表。
        review = (draft.provenance_json or {}).get("independent_review")
        open_finding_ids = [
            str(item) for item in (review or {}).get("finding_ids") or [] if item
        ]
        if open_finding_ids:
            adopted_provenance["adopted_with_open_issues"] = {
                "check_version": review.get("check_version"),
                "review_output_hash": review.get("output_hash"),
                "open_finding_ids": open_finding_ids,
            }
        candidate_provenance = {
            **(draft.provenance_json or {}),
            "deprecated_from_status": "candidate",
            "adopted_at": adopted_at,
            "adopted_by": adopted_by,
        }
        if replay_key is not None:
            adopted_provenance["adoption_idempotency_key"] = replay_key
            candidate_provenance["adoption_idempotency_key"] = replay_key
        adopted = await self._repo.create(
            db,
            WritingDraftCreate(
                novel_id=str(draft.novel_id),
                chapter_index=draft.chapter_index,
                title=draft.title,
                content=draft.content,
                provenance_json=adopted_provenance,
            ),
        )
        candidate_provenance["adoption_result_draft_id"] = str(adopted.id)
        draft.provenance_json = candidate_provenance
        draft.status = "deprecated"
        db.add(draft)
        await db.flush()
        if confirmation_id := _result_confirmation_id(draft):
            from modules.evidence.facade import attach_result_ref

            await attach_result_ref(
                db,
                novel_id=str(draft.novel_id),
                confirmation_id=confirmation_id,
                result_type="writing_draft",
                result_id=str(adopted.id),
                status="adopted",
            )
        bridge_issue_ids = [
            str(value)
            for value in adopted_provenance.get("editorial_issue_ids") or []
            if value
        ]
        if bridge_issue_ids:
            # BR-4：审读意见桥接候选采用后，经组合根 DI 键按既有机制请求
            # 改后复核；复核无法成立（依据变化、用量未知等）只降级记录，
            # 不影响采用结果，也不绕过或改写任何采用门禁。
            try:
                await get(ASSISTANT_EDITORIAL_POST_ADOPTION_RECHECKS)(
                    db,
                    novel_id=str(draft.novel_id),
                    issue_ids=bridge_issue_ids,
                    adopted_draft_id=str(adopted.id),
                )
            except Exception as exc:
                logger.warning(
                    "Post-adoption editorial recheck failed for adopted draft %s: %s",
                    adopted.id,
                    redact_diagnostic(exc, limit=300),
                )
        return WritingDraftResponse.model_validate(adopted)

    async def adopt_candidate_to_working_contract(
        self,
        db: AsyncSession,
        draft_id: str,
        novel_id: str,
        *,
        adopted_by: str = "author",
        idempotency_key: str | None = None,
    ) -> WritingDraftContract:
        adopted = await self.adopt_candidate_to_working(
            db,
            draft_id,
            novel_id,
            adopted_by=adopted_by,
            idempotency_key=idempotency_key,
        )
        return self._to_contract(adopted)

    async def list_creation_progress(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        limit: int = 6,
    ) -> list[WorkspaceCreationProgressItem]:
        """只读作品进度投影（BR-1b）：最近候选与已采用成果。

        只读现有门禁结果与 provenance，不重复判断、不写回领域事实；
        来源新鲜度由知识复核 stale_after_edit 与确认失效信号拼出，
        不重编译上下文。任务类条目由组合根 adapter 另行并入。
        """
        from sqlalchemy import select

        nid = _parse_uuid(novel_id, "novel")
        limit = max(1, min(int(limit), 12))
        candidate_rows = (
            (
                await db.execute(
                    select(WritingDraft)
                    .where(
                        WritingDraft.novel_id == nid,
                        WritingDraft.status == "candidate",
                    )
                    .order_by(WritingDraft.updated_at.desc(), WritingDraft.id.desc())
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        adopted_pool = (
            (
                await db.execute(
                    select(WritingDraft)
                    .where(
                        WritingDraft.novel_id == nid,
                        WritingDraft.status.in_(["draft", "published"]),
                    )
                    .order_by(WritingDraft.updated_at.desc(), WritingDraft.id.desc())
                    .limit(limit * 4)
                )
            )
            .scalars()
            .all()
        )
        adopted_rows = [
            draft
            for draft in adopted_pool
            if (draft.provenance_json or {}).get("adopted_from_candidate_id")
        ][:limit]

        confirmation_ids: list[str] = []
        for draft in [*candidate_rows, *adopted_rows]:
            provenance = draft.provenance_json or {}
            confirmation_id = str(
                provenance.get("context_confirmation_id")
                or provenance.get("source_confirmation_id")
                or ""
            )
            if confirmation_id:
                confirmation_ids.append(confirmation_id)
        staleness = await get(EVIDENCE_CONFIRMATION_READS).get_staleness_map(
            db,
            novel_id=novel_id,
            confirmation_ids=list(dict.fromkeys(confirmation_ids)),
        )

        items: list[WorkspaceCreationProgressItem] = []
        for draft in candidate_rows:
            items.append(
                self._candidate_progress_item(
                    draft,
                    staleness.get(_progress_confirmation_id(draft), {}),
                )
            )
        for draft in adopted_rows:
            items.append(
                self._adopted_progress_item(
                    draft,
                    staleness.get(_progress_confirmation_id(draft), {}),
                )
            )
        return items

    @staticmethod
    def _candidate_progress_item(
        draft: WritingDraft,
        confirmation_staleness: dict,
    ) -> WorkspaceCreationProgressItem:
        provenance = draft.provenance_json or {}
        knowledge = provenance.get("knowledge_review") or {}
        review = provenance.get("independent_review") or {}
        knowledge_status = str(knowledge.get("status") or "") or None
        verdict = str(review.get("verdict") or "") or None
        blocking_count = int(review.get("blocking_count") or 0)
        review_status = knowledge_status or verdict
        knowledge_stale = bool(knowledge.get("stale_after_edit"))
        confirmation_stale = bool(confirmation_staleness.get("stale"))
        missing_confirmation = _requires_confirmed_context(provenance) and not bool(
            confirmation_staleness
        )
        source_freshness = (
            "stale"
            if knowledge_stale or confirmation_stale
            else "unknown"
            if missing_confirmation
            else "fresh"
        )

        if not knowledge_status:
            stop_reason = "缺少资料复核回执，暂不能采用"
            applicability = "blocked"
            actions = ("open_candidate", "reconfirm")
        elif knowledge_status in {"blocked", "legacy_unchecked", "not_checked"}:
            stop_reason = "资料复核未通过，暂不能采用"
            applicability = "blocked"
            actions = ("open_candidate", "reconfirm")
        elif knowledge_status == "unverifiable":
            stop_reason = "资料复核未完成，暂不能采用"
            applicability = "blocked"
            actions = ("open_candidate", "reconfirm")
        elif knowledge_status == "checking":
            stop_reason = "资料复核进行中"
            applicability = "blocked"
            actions = ("open_candidate",)
        elif missing_confirmation:
            stop_reason = "缺少原参考确认，需重新确认"
            applicability = "blocked"
            actions = ("open_candidate", "reconfirm")
        elif knowledge_stale or confirmation_stale:
            stop_reason = "正文或参考资料已变化，需重新确认"
            applicability = "stale"
            actions = ("open_candidate", "reconfirm")
        elif not review:
            stop_reason = "待独立语义审查"
            applicability = "applicable"
            actions = ("open_candidate", "continue_review")
        elif verdict == "needs_revision" or blocking_count > 0:
            stop_reason = f"独立审查发现 {blocking_count} 个必须先处理的问题"
            applicability = "blocked"
            actions = ("open_candidate", "continue_review")
        elif verdict == "incomplete":
            stop_reason = "独立审查部分完成，暂不能采用"
            applicability = "blocked"
            actions = ("open_candidate", "continue_review")
        else:
            stop_reason = "可审阅，待作者采用"
            applicability = "applicable"
            actions = ("open_candidate",)

        return WorkspaceCreationProgressItem(
            key=f"candidate:{draft.id}",
            kind="candidate",
            title=(f"第 {draft.chapter_index} 章 · " + (draft.title or "AI 正文建议")),
            execution_status="done",
            coverage=f"第 {draft.chapter_index} 章",
            source_freshness=source_freshness,
            applicability=applicability,
            review_status=review_status,
            adoption_status="candidate",
            stop_reason=stop_reason,
            actions=actions,
            draft_id=str(draft.id),
            chapter_index=int(draft.chapter_index),
            scene_id=(
                str(provenance.get("scene_id")) if provenance.get("scene_id") else None
            ),
            updated_at=draft.updated_at or draft.created_at,
        )

    @staticmethod
    def _adopted_progress_item(
        draft: WritingDraft,
        confirmation_staleness: dict,
    ) -> WorkspaceCreationProgressItem:
        provenance = draft.provenance_json or {}
        knowledge = provenance.get("knowledge_review") or {}
        open_issues = provenance.get("adopted_with_open_issues") or {}
        open_count = len(open_issues.get("open_finding_ids") or [])
        knowledge_stale = bool(knowledge.get("stale_after_edit"))
        source_freshness = (
            "stale"
            if knowledge_stale or bool(confirmation_staleness.get("stale"))
            else "fresh"
        )
        published = draft.status == "published"
        coverage = f"第 {draft.chapter_index} 章"
        if open_count:
            coverage += f" · 带 {open_count} 条未处理建议采用"

        return WorkspaceCreationProgressItem(
            key=f"adopted:{draft.id}",
            kind="adopted",
            title=(
                f"第 {draft.chapter_index} 章 · "
                + (draft.title or ("已发布正文" if published else "工作稿"))
            ),
            execution_status="done",
            coverage=coverage,
            source_freshness=source_freshness,
            applicability="stale" if source_freshness == "stale" else "applicable",
            review_status=str(knowledge.get("status") or "") or None,
            adoption_status="published" if published else "adopted",
            stop_reason="已发布" if published else "已采用，可继续写作或发布",
            actions=("open_candidate",),
            draft_id=str(draft.id),
            chapter_index=int(draft.chapter_index),
            updated_at=draft.updated_at or draft.created_at,
        )

    async def update_draft(
        self,
        db: AsyncSession,
        draft_id: str,
        data: WritingDraftUpdate,
        novel_id: str,
    ) -> WritingDraftResponse:
        """暂存草稿；published 版本首次编辑时 copy-on-write。"""
        did = _parse_uuid(draft_id, "draft")
        nid = _parse_uuid(novel_id, "novel")
        draft = await self._repo.get(db, did)
        if draft is None or str(draft.novel_id) != str(nid):
            raise NotFoundError(f"Draft {draft_id} not found")
        # 先序列化并发写者，再做最新快照校验；否则校验通过后仍可能被后写者原地覆盖
        await self._repo.lock_version_chapters_for_revalidation(
            db,
            draft.novel_id,
            [draft.chapter_index],
        )
        draft = await self._repo.get_for_update(db, did)
        if draft is None or str(draft.novel_id) != str(nid):
            raise NotFoundError(f"Draft {draft_id} not found")
        # 多 Tab 冲突检测：以章节最新版本为准
        latest = await self._repo.get_latest_by_chapter(
            db, draft.novel_id, draft.chapter_index
        )
        self._ensure_latest_and_expected(draft, latest, data)
        sanitized_data = _sanitize_draft_update(data)
        next_content = (
            sanitized_data.content
            if sanitized_data.content is not None
            else draft.content
        )
        content_changed = has_substantive_change(draft.content, next_content)
        if draft.status == "published":
            if not content_changed:
                return WritingDraftResponse.model_validate(draft)
            copied = WritingDraftCreate(
                novel_id=str(draft.novel_id),
                chapter_index=draft.chapter_index,
                title=(
                    sanitized_data.title
                    if sanitized_data.title is not None
                    else draft.title
                ),
                content=(
                    sanitized_data.content
                    if sanitized_data.content is not None
                    else draft.content
                ),
                provenance_json=_mark_knowledge_review_stale(
                    {
                        **(draft.provenance_json or {}),
                        "copied_from_published_draft_id": str(draft.id),
                        "base_draft_id": str(draft.id),
                        "version_origin": "auto",
                    },
                    changed=content_changed,
                ),
            )
            updated = await self._repo.create(db, copied)
            updated.conflict_check_snapshot_json = draft.conflict_check_snapshot_json
            await db.flush()
        elif (draft.provenance_json or {}).get("version_origin") == "manual":
            if not content_changed:
                return WritingDraftResponse.model_validate(draft)
            copied = WritingDraftCreate(
                novel_id=str(draft.novel_id),
                chapter_index=draft.chapter_index,
                title=(
                    sanitized_data.title
                    if sanitized_data.title is not None
                    else draft.title
                ),
                content=next_content,
                provenance_json=_mark_knowledge_review_stale(
                    {
                        **(draft.provenance_json or {}),
                        "base_draft_id": str(draft.id),
                        "version_origin": "auto",
                    },
                    changed=content_changed,
                ),
            )
            updated = await self._repo.create(db, copied)
        elif (draft.provenance_json or {}).get("version_origin") == "auto":
            base = await self._get_base_draft(db, draft)
            if base is not None and not has_substantive_change(
                base.content, next_content
            ):
                return await self._discard_loaded_draft(
                    db, draft, base, "automatic_revert"
                )
            updated = await self._repo.update(db, draft, sanitized_data)
            if updated is not None and content_changed:
                _mark_knowledge_review_stale_in_place(updated)
        else:
            updated = await self._repo.update(db, draft, sanitized_data)
            if updated is not None and content_changed:
                _mark_knowledge_review_stale_in_place(updated)
        if updated is None:
            raise NotFoundError(f"Draft {draft_id} not found")
        return WritingDraftResponse.model_validate(updated)

    async def checkpoint_draft(
        self,
        db: AsyncSession,
        draft_id: str,
        data: WritingDraftCheckpoint,
        novel_id: str,
    ) -> WritingDraftResponse:
        draft = await self._load_scoped_latest(db, draft_id, novel_id, data)
        sanitized = _sanitize_draft_update(data)
        content = sanitized.content if sanitized.content is not None else draft.content
        title = sanitized.title if sanitized.title is not None else draft.title
        provenance = dict(draft.provenance_json or {})
        if draft.status == "draft" and provenance.get("version_origin") == "auto":
            base = await self._get_base_draft(db, draft)
            if (
                not data.force
                and base is not None
                and not has_substantive_change(base.content, content)
            ):
                raise ValidationError("正文无实质变化；确认后可强制保存新版本")
            updated = await self._repo.update(
                db,
                draft,
                WritingDraftUpdate(title=title, content=content),
            )
            assert updated is not None
            updated.provenance_json = {**provenance, "version_origin": "manual"}
            db.add(updated)
            await db.flush()
            return WritingDraftResponse.model_validate(updated)

        if not data.force and not has_substantive_change(draft.content, content):
            raise ValidationError("正文无实质变化；确认后可强制保存新版本")

        checkpoint = await self._repo.create(
            db,
            WritingDraftCreate(
                novel_id=str(draft.novel_id),
                chapter_index=draft.chapter_index,
                title=title,
                content=content,
                provenance_json={
                    **provenance,
                    "base_draft_id": str(draft.id),
                    "version_origin": "manual",
                },
            ),
        )
        return WritingDraftResponse.model_validate(checkpoint)

    async def discard_draft(
        self,
        db: AsyncSession,
        draft_id: str,
        novel_id: str,
        *,
        expected_version: int | None = None,
        expected_updated_at: datetime | None = None,
    ) -> WritingDraftResponse:
        data = WritingDraftUpdate(
            expected_version=expected_version,
            expected_updated_at=expected_updated_at,
        )
        draft = await self._load_scoped_latest(db, draft_id, novel_id, data)
        if draft.status != "draft":
            raise ValidationError("只能放弃未发布的工作版本")
        base = await self._get_base_draft(db, draft)
        if base is None:
            raise ValidationError("当前工作版本没有可回退的基线版本")
        return await self._discard_loaded_draft(db, draft, base, "author_discard")

    async def _load_scoped_latest(
        self,
        db: AsyncSession,
        draft_id: str,
        novel_id: str,
        data: WritingDraftUpdate,
    ):
        draft = await self._repo.get(db, _parse_uuid(draft_id, "draft"))
        nid = _parse_uuid(novel_id, "novel")
        if draft is None or draft.novel_id != nid:
            raise NotFoundError(f"Draft {draft_id} not found")
        await self._repo.lock_version_chapters_for_revalidation(
            db,
            nid,
            [draft.chapter_index],
        )
        draft = await self._repo.get_for_update(db, _parse_uuid(draft_id, "draft"))
        if draft is None or draft.novel_id != nid:
            raise NotFoundError(f"Draft {draft_id} not found")
        latest = await self._repo.get_latest_by_chapter(db, nid, draft.chapter_index)
        self._ensure_latest_and_expected(draft, latest, data)
        return draft

    def _ensure_latest_and_expected(self, draft, latest, data) -> None:
        self._ensure_expected_snapshot(latest or draft, data)
        latest_version = latest.version_number if latest else draft.version_number
        if (
            draft.status not in WORKING_DRAFT_STATUSES
            or latest is None
            or latest.id != draft.id
        ):
            raise ConflictError(
                f"当前版本不是该章节最新版本 v{latest_version}，请刷新后重新编辑。"
            )

    def _ensure_expected_snapshot(self, latest, data) -> None:
        if latest is None:
            if data.expected_version is not None or data.expected_updated_at is not None:
                raise ConflictError("该章节最新版本已变化，请刷新后重新编辑。")
            return
        latest_version = latest.version_number
        latest_updated_at = latest.updated_at
        if data.expected_updated_at is not None and latest_updated_at is not None:
            if _as_utc_aware(latest_updated_at) > _as_utc_aware(data.expected_updated_at):
                raise ConflictError("该章节已被其他会话更新，请刷新后重新编辑。")
        if data.expected_version is not None and latest_version != data.expected_version:
            raise ConflictError(
                f"该章节已被其他会话更新（当前版本 v{latest_version}，"
                f"期望版本 v{data.expected_version}）。请刷新后重新编辑。"
            )

    async def _promote_loaded_draft(
        self,
        db: AsyncSession,
        draft,
        *,
        title: str | None = None,
        content: str | None = None,
        replace_content: bool = False,
    ) -> WritingDraftResponse:
        old_content = draft.content
        if replace_content:
            await self._repo.lock_version_chapters_for_revalidation(
                db,
                draft.novel_id,
                [draft.chapter_index],
            )
            draft.title = title
            draft.content = content
            draft.content_hash = hash_text(content)
        draft.status = "published"
        draft.provenance_json = {
            **(draft.provenance_json or {}),
            "published_from_draft": True,
        }
        db.add(draft)
        await db.flush()
        await self._repo._changed(db, draft, old_content=old_content)
        return WritingDraftResponse.model_validate(draft)

    async def _get_base_draft(self, db: AsyncSession, draft):
        base_id = (draft.provenance_json or {}).get("base_draft_id")
        if base_id:
            try:
                base = await self._repo.get(db, _parse_uuid(base_id, "base draft"))
            except ValidationError:
                base = None
            if (
                base is not None
                and base.novel_id == draft.novel_id
                and base.chapter_index == draft.chapter_index
                and base.status in WORKING_DRAFT_STATUSES
            ):
                return base
        return await self._repo.get_previous_working_version(db, draft)

    async def _discard_loaded_draft(self, db, draft, base, reason: str):
        previous_status = draft.status
        draft.provenance_json = {
            **(draft.provenance_json or {}),
            "deprecated_from_status": draft.status,
            "discard_reason": reason,
        }
        draft.status = "deprecated"
        db.add(draft)
        await db.flush()
        await self._repo._changed(
            db, draft, previous_status=previous_status, old_content=draft.content
        )
        return WritingDraftResponse.model_validate(base)

    async def delete_draft(
        self,
        db: AsyncSession,
        draft_id: str,
        novel_id: str,
    ) -> None:
        """软废弃单个版本（至少保留 1 个活跃版本）。"""
        did = _parse_uuid(draft_id, "draft")
        nid = _parse_uuid(novel_id, "novel")
        draft = await self._repo.get(db, did)
        if draft is None or str(draft.novel_id) != str(nid):
            raise NotFoundError(f"Draft {draft_id} not found")
        await self._repo.lock_version_chapters_for_revalidation(
            db,
            draft.novel_id,
            [draft.chapter_index],
        )
        draft = await self._repo.get_for_update(db, did)
        if draft is None or draft.novel_id != nid:
            raise NotFoundError(f"Draft {draft_id} not found")

        was_candidate = draft.status == "candidate"

        # 待处理建议不能充当章节工作稿。只有删除工作/已发布版本时，
        # 才需要保证仍有至少一个可用的章节来源。
        if draft.status in WORKING_DRAFT_STATUSES:
            working_version_count = await self._repo.count_working_versions(
                db,
                draft.novel_id,
                draft.chapter_index,
            )
            if working_version_count <= 1:
                raise ValidationError(
                    "Cannot delete the last working version of a chapter"
                )

        deleted = await self._repo.delete(db, did)
        if deleted is None:
            raise NotFoundError(f"Draft {draft_id} not found")
        if was_candidate:
            deleted.provenance_json = {
                **(deleted.provenance_json or {}),
                "rejected_at": datetime.now(UTC).isoformat(),
                "rejected_by": "author",
            }
            db.add(deleted)
            await db.flush()
            if confirmation_id := _result_confirmation_id(deleted):
                from modules.evidence.facade import attach_result_ref

                await attach_result_ref(
                    db,
                    novel_id=str(deleted.novel_id),
                    confirmation_id=confirmation_id,
                    result_type="writing_draft",
                    result_id=str(deleted.id),
                    status="rejected",
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
        *,
        published_only: bool = False,
    ) -> WritingDraftResponse:
        """获取章节最新草稿"""
        nid = _parse_uuid(novel_id, "novel")
        draft = await (
            self._repo.get_latest_published_by_chapter(db, nid, chapter_index)
            if published_only
            else self._repo.get_latest_by_chapter(db, nid, chapter_index)
        )
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
        *,
        published_only: bool = False,
    ) -> VersionHistoryResponse:
        """获取章节版本历史"""
        nid = _parse_uuid(novel_id, "novel")
        versions = await self._repo.get_version_history(db, nid, chapter_index)
        if published_only:
            versions = [version for version in versions if version.status == "published"]
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

    async def list_draft_contracts(
        self,
        db: AsyncSession,
        novel_id: str,
        draft_ids: list[str],
    ) -> list[WritingDraftContract]:
        """按 ID 批量获取草稿契约;隔离语义与 get_draft_contract 一致。"""
        nid = _parse_uuid(novel_id, "novel")
        parsed = [_parse_uuid(draft_id, "draft") for draft_id in draft_ids]
        if not parsed:
            return []
        drafts = await self._repo.list_by_ids(db, parsed, novel_id=nid)
        return [self._to_contract(draft) for draft in drafts]

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
        projection = project_writing_draft_state(
            getattr(draft, "status", "draft"),
            getattr(draft, "provenance_json", None),
        )
        return WritingDraftContract(
            id=str(draft.id) if getattr(draft, "id", None) is not None else None,
            novel_id=str(draft.novel_id),  # type: ignore[union-attr]
            chapter_index=draft.chapter_index,  # type: ignore[union-attr]
            title=draft.title,  # type: ignore[union-attr]
            content=draft.content,  # type: ignore[union-attr]
            content_hash=getattr(draft, "content_hash", ""),
            version_number=draft.version_number,  # type: ignore[union-attr]
            status=draft.status,  # type: ignore[union-attr]
            conflict_check_snapshot_json=draft.conflict_check_snapshot_json,  # type: ignore[union-attr]
            provenance_json=draft.provenance_json,  # type: ignore[union-attr]
            display_state=projection["display_state"],
            source=projection["source"],
            attention_reasons=projection["attention_reasons"],
            knowledge_review=projection.get("knowledge_review"),
            editorial_ready_at=getattr(draft, "editorial_ready_at", None),
            editorial_ready_hash=getattr(draft, "editorial_ready_hash", None),
            created_at=draft.created_at,  # type: ignore[union-attr]
            updated_at=draft.updated_at,  # type: ignore[union-attr]
            invalidation=getattr(draft, INVALIDATION_VIEW_ATTR, None),
        )

    @staticmethod
    def _projection_to_contract(row: object) -> WritingDraftContract:
        """将最新草稿投影结果转为契约对象。"""
        mapping = row._mapping if hasattr(row, "_mapping") else row  # noqa: SLF001
        projection = project_writing_draft_state(
            mapping["status"],  # type: ignore[index]
            mapping["provenance_json"],  # type: ignore[index]
        )
        return WritingDraftContract(
            id=str(mapping["id"]) if mapping["id"] is not None else None,  # type: ignore[index]
            novel_id=str(mapping["novel_id"]),  # type: ignore[index]
            chapter_index=mapping["chapter_index"],  # type: ignore[index]
            title=mapping["title"],  # type: ignore[index]
            content=mapping["content"],  # type: ignore[index]
            content_hash=mapping.get("content_hash", ""),  # type: ignore[union-attr]
            version_number=mapping["version_number"],  # type: ignore[index]
            status=mapping["status"],  # type: ignore[index]
            conflict_check_snapshot_json=mapping["conflict_check_snapshot_json"],  # type: ignore[index]
            provenance_json=mapping["provenance_json"],  # type: ignore[index]
            display_state=projection["display_state"],
            source=projection["source"],
            attention_reasons=projection["attention_reasons"],
            knowledge_review=projection.get("knowledge_review"),
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

    async def list_effective_chapter_indices(
        self,
        db: AsyncSession,
        novel_id: str,
    ) -> list[int]:
        """列出最新工作版本含实质正文的章节索引。"""
        nid = _parse_uuid(novel_id, "novel")
        return await self._repo.list_effective_chapter_indices(db, nid)

    async def get_latest_effective_chapter_index(
        self,
        db: AsyncSession,
        novel_id: str,
    ) -> int:
        """最新有实质正文的章节号；0 表示尚无正文。"""
        nid = _parse_uuid(novel_id, "novel")
        return await self._repo.get_latest_effective_chapter_index(db, nid)

    async def lock_chapter_versions_for_revalidation(
        self,
        db: AsyncSession,
        novel_id: str,
        chapter_indices: list[int],
    ) -> None:
        """Serialize selected chapter writes with an external finalizer."""
        nid = _parse_uuid(novel_id, "novel")
        await self._repo.lock_version_chapters_for_revalidation(
            db,
            nid,
            chapter_indices,
        )

    async def list_chapter_summaries(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        published_only: bool = False,
    ) -> list[ChapterSummaryItem]:
        """列出每章最新版本摘要。"""
        nid = _parse_uuid(novel_id, "novel")
        drafts = await self._repo.list_chapter_summaries(
            db,
            nid,
            statuses=("published",) if published_only else WORKING_DRAFT_STATUSES,
        )
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


class WritingChapterOrderService:
    """Preview, execute and safely restore a complete Writing chapter order."""

    def __init__(self, repo: WritingDraftRepository | None = None) -> None:
        self._repo = repo or WritingDraftRepository()

    async def preview(
        self,
        db: AsyncSession,
        novel_id: str,
        request: ChapterOrderPreviewRequest,
    ) -> ChapterOrderPreviewResponse:
        state = await self._load_state(db, novel_id)
        source_order = state["chapter_indices"]
        target_order = [int(index) for index in request.chapter_indices]
        if not source_order:
            raise ValidationError("当前没有可调整顺序的章节")
        if target_order != source_order and sorted(target_order) != source_order:
            raise ValidationError("请用当前章节完整顺序提交，不能漏章或重复")
        if target_order == source_order:
            raise ValidationError("章节顺序没有变化")

        chapter_map = self._chapter_map_for_orders(source_order, target_order)
        story = self._story_port()
        story_preview = await story.preview(
            db,
            novel_id,
            chapter_map,
            state["source_versions"],
        )
        operation_id = uuid.uuid4()
        moves = self._moves(state, chapter_map)
        writing_blockers = self._writing_blockers(state)
        story_impact = {
            **story_preview["impact"],
            "writing": {
                "draft_version_count": len(state["drafts"]),
                "comment_count": len(state["comments"]),
                "unlisted_version_chapter_count": len(state["unlisted_chapter_indices"]),
            },
            "blockers": [*story_preview["blockers"], *writing_blockers],
        }
        preview_value = {
            "receipt_id": str(operation_id),
            "source_order": source_order,
            "target_order": target_order,
            "moves": moves,
            "story_impact": story_impact,
            "blockers": story_impact["blockers"],
        }
        preview_hash = _chapter_order_hash(preview_value)
        operation = WritingChapterOrderOperation(
            id=operation_id,
            novel_id=_parse_uuid(novel_id, "novel_id"),
            status="previewed",
            source_order_json=source_order,
            target_order_json=target_order,
            before_fingerprint=state["fingerprint"],
            preview_hash=preview_hash,
            story_fingerprint=story_preview["fingerprint"],
            story_receipt_id=operation_id,
            impact_json=story_impact,
            preview_json=preview_value,
        )
        db.add(operation)
        await db.flush()
        return ChapterOrderPreviewResponse(
            **preview_value,
            preview_hash=preview_hash,
        )

    async def confirm(
        self,
        db: AsyncSession,
        novel_id: str,
        receipt_id: str,
        *,
        expected_preview_hash: str,
        confirmed: bool,
    ) -> ChapterOrderResultResponse:
        if confirmed is not True:
            raise ValidationError("需要作者明确确认章节顺序")
        operation = await self._get_operation(db, novel_id, receipt_id, for_update=True)
        if expected_preview_hash != operation.preview_hash:
            raise ConflictError("章节顺序预览已变化，请重新核对")
        if operation.status == "executed":
            return self._result(operation, "executed", replayed=True)
        if operation.status == "restored":
            raise ConflictError("这项章节顺序调整已经恢复，请重新预览")
        if (operation.impact_json or {}).get("blockers"):
            raise ConflictError("Story 来源尚有未解决冲突，不能执行章节重排")

        chapter_map = self._chapter_map(operation)
        await self._lock_chapters(db, novel_id, chapter_map)
        state = await self._load_state(db, novel_id, for_update=True)
        if state["fingerprint"] != operation.before_fingerprint:
            raise ConflictError("章节正文、版本或批注已变化，请重新预览")

        story_result = await self._story_port().apply(
            db,
            novel_id,
            str(operation.story_receipt_id),
            chapter_map,
            state["source_versions"],
            operation.story_fingerprint,
        )
        await self._move_writing_rows(db, state, chapter_map)
        await self._invalidate_standing_authorization(db, novel_id)
        await db.flush()

        after = await self._load_state(db, novel_id)
        operation.status = "executed"
        operation.after_fingerprint = after["fingerprint"]
        operation.executed_at = datetime.now(UTC)
        operation.result_ref_json = {
            "type": "writing_chapter_order",
            "id": str(operation.id),
        }
        operation.impact_json = {
            **(operation.impact_json or {}),
            "story": story_result.get("impact") or operation.impact_json,
        }
        await db.flush()
        return self._result(operation, "executed", replayed=False)

    async def preview_restore(
        self,
        db: AsyncSession,
        novel_id: str,
        receipt_id: str,
    ) -> ChapterOrderRestorePreviewResponse:
        operation = await self._get_operation(db, novel_id, receipt_id, for_update=True)
        if operation.status != "executed":
            raise ConflictError("只有尚未恢复的已执行重排可以预览恢复")
        state = await self._load_state(db, novel_id)
        story_preview = await self._story_port().preview_restore(
            db,
            novel_id,
            str(operation.story_receipt_id),
        )
        preview_value = self._restore_preview_value(operation, state, story_preview)
        preview_hash = _chapter_order_hash(preview_value)
        operation.restore_preview_hash = preview_hash
        operation.restore_preview_json = preview_value
        await db.flush()
        return ChapterOrderRestorePreviewResponse(
            receipt_id=operation.id,
            status="executed",
            can_restore=not preview_value["blockers"],
            restore_preview_hash=preview_hash,
            chapter_map=self._chapter_map(operation),
            story_impact=operation.impact_json or {},
            blockers=preview_value["blockers"],
        )

    async def restore(
        self,
        db: AsyncSession,
        novel_id: str,
        receipt_id: str,
        *,
        confirmed: bool,
        expected_preview_hash: str,
    ) -> ChapterOrderResultResponse:
        if confirmed is not True:
            raise ValidationError("需要作者明确确认恢复章节顺序")
        operation = await self._get_operation(db, novel_id, receipt_id, for_update=True)
        if operation.status == "restored":
            return self._result(operation, "restored", replayed=True)
        if operation.status != "executed" or not operation.after_fingerprint:
            raise ConflictError("这项章节顺序调整尚未执行，不能恢复")
        if (
            not operation.restore_preview_hash
            or expected_preview_hash != operation.restore_preview_hash
        ):
            raise ConflictError("恢复预览已变化，请重新核对")

        chapter_map = self._chapter_map(operation)
        await self._lock_chapters(db, novel_id, chapter_map)
        state = await self._load_state(db, novel_id, for_update=True)
        story_preview = await self._story_port().preview_restore(
            db,
            novel_id,
            str(operation.story_receipt_id),
        )
        preview_value = self._restore_preview_value(operation, state, story_preview)
        current_preview_hash = _chapter_order_hash(preview_value)
        if (
            preview_value["blockers"]
            or current_preview_hash != operation.restore_preview_hash
            or current_preview_hash != expected_preview_hash
        ):
            raise ConflictError(
                "重排后的正文、批注或 Story 来源已有变化；为保护新内容，请重新预览"
            )

        story_result = await self._story_port().restore(
            db,
            novel_id,
            str(operation.story_receipt_id),
        )
        inverse = {target: source for source, target in chapter_map.items()}
        await self._move_writing_rows(db, state, inverse)
        await self._invalidate_standing_authorization(db, novel_id)
        await db.flush()
        operation.status = "restored"
        operation.restored_at = datetime.now(UTC)
        operation.impact_json = {
            **(operation.impact_json or {}),
            "story": story_result.get("impact") or operation.impact_json,
        }
        await db.flush()
        return self._result(operation, "restored", replayed=False)

    @staticmethod
    def _restore_preview_value(
        operation: WritingChapterOrderOperation,
        state: dict[str, Any],
        story_preview: dict[str, Any],
    ) -> dict[str, Any]:
        blockers = []
        if state["fingerprint"] != operation.after_fingerprint:
            blockers.append(
                {
                    "kind": "writing_source_changed",
                    "message": "重排后正文、版本或批注已有新变化，不能覆盖恢复",
                }
            )
        for blocker in story_preview.get("blockers", []):
            kind = blocker.get("kind")
            blockers.append(
                {
                    "kind": kind or "story_source_changed",
                    "message": ("Story 绑定或派生来源已有新变化，不能覆盖恢复"),
                }
            )
        return {
            "receipt_id": str(operation.id),
            "writing_fingerprint": state["fingerprint"],
            "story_fingerprint": story_preview.get("story_fingerprint"),
            "expected_story_fingerprint": story_preview.get("expected_story_fingerprint"),
            "story_impact": operation.impact_json or {},
            "blockers": blockers,
        }

    async def list_history(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        limit: int = 20,
    ) -> ChapterOrderHistoryResponse:
        operations = (
            await db.scalars(
                select(WritingChapterOrderOperation)
                .where(
                    WritingChapterOrderOperation.novel_id
                    == _parse_uuid(novel_id, "novel_id")
                )
                .order_by(
                    WritingChapterOrderOperation.created_at.desc(),
                    WritingChapterOrderOperation.id.desc(),
                )
                .limit(max(1, min(int(limit), 100)))
            )
        ).all()
        return ChapterOrderHistoryResponse(
            items=[
                ChapterOrderHistoryItem(
                    receipt_id=operation.id,
                    status=operation.status,
                    source_order=operation.source_order_json or [],
                    target_order=operation.target_order_json or [],
                    preview_hash=operation.preview_hash,
                    story_impact=operation.impact_json or {},
                    can_restore=operation.status == "executed",
                    created_at=operation.created_at,
                    executed_at=operation.executed_at,
                    restored_at=operation.restored_at,
                )
                for operation in operations
            ]
        )

    async def _load_state(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        for_update: bool = False,
    ) -> dict[str, Any]:
        nid = _parse_uuid(novel_id, "novel_id")
        chapter_indices = await self._repo.list_chapter_indices(db, nid)
        if not chapter_indices:
            return {
                "chapter_indices": [],
                "unlisted_chapter_indices": [],
                "drafts": [],
                "comments": [],
                "source_versions": {},
                "fingerprint": _chapter_order_hash({"drafts": [], "comments": []}),
            }
        all_chapter_indices = await self._repo.list_all_chapter_indices(db, nid)
        unlisted_chapter_indices = sorted(set(all_chapter_indices) - set(chapter_indices))
        statement = (
            select(WritingDraft)
            .where(
                WritingDraft.novel_id == nid,
                WritingDraft.chapter_index.in_(chapter_indices),
            )
            .order_by(
                WritingDraft.chapter_index, WritingDraft.version_number, WritingDraft.id
            )
        )
        if for_update:
            statement = statement.with_for_update().execution_options(
                populate_existing=True
            )
        drafts = list((await db.scalars(statement)).all())
        draft_ids = [draft.id for draft in drafts]
        comments: list[WritingComment] = []
        if draft_ids:
            comment_statement = (
                select(WritingComment)
                .where(
                    WritingComment.novel_id == nid,
                    WritingComment.draft_id.in_(draft_ids),
                )
                .order_by(WritingComment.id)
            )
            if for_update:
                comment_statement = comment_statement.with_for_update().execution_options(
                    populate_existing=True
                )
            comments = list((await db.scalars(comment_statement)).all())
        source_versions: dict[int, list[dict[str, str]]] = {}
        for draft in drafts:
            source_versions.setdefault(int(draft.chapter_index), []).append(
                {"draft_id": str(draft.id), "content_hash": str(draft.content_hash)}
            )
        return {
            "chapter_indices": [int(index) for index in chapter_indices],
            "unlisted_chapter_indices": unlisted_chapter_indices,
            "drafts": drafts,
            "comments": comments,
            "source_versions": source_versions,
            "fingerprint": self._fingerprint(drafts, comments),
        }

    @staticmethod
    def _fingerprint(drafts: list[WritingDraft], comments: list[WritingComment]) -> str:
        payload = {
            "drafts": sorted(
                (
                    str(row.id),
                    int(row.chapter_index),
                    int(row.version_number),
                    str(row.status),
                    str(row.content_hash),
                    _text_hash(row.content),
                    _text_hash(row.title),
                    _dt_key(row.updated_at),
                )
                for row in drafts
            ),
            "comments": sorted(
                (
                    str(row.id),
                    str(row.draft_id),
                    int(row.chapter_index),
                    int(row.version_number),
                    str(row.source_hash),
                    row.range_hash,
                    row.start_offset,
                    row.end_offset,
                    _text_hash(row.excerpt),
                    _text_hash(row.body),
                    row.status,
                    row.origin,
                    row.severity,
                    str(row.review_task_id) if row.review_task_id else None,
                    row.finding_id,
                    str(row.last_run_task_id) if row.last_run_task_id else None,
                    _dt_key(row.updated_at),
                )
                for row in comments
            ),
        }
        return _chapter_order_hash(payload)

    @staticmethod
    def _moves(
        state: dict[str, Any], chapter_map: dict[int, int]
    ) -> list[dict[str, Any]]:
        counts: dict[int, int] = {}
        published: set[int] = set()
        titles: dict[int, tuple[int, str | None]] = {}
        for draft in state["drafts"]:
            chapter_index = int(draft.chapter_index)
            counts[chapter_index] = counts.get(chapter_index, 0) + 1
            if draft.status in {"published", "canonical"}:
                published.add(chapter_index)
            previous = titles.get(chapter_index)
            if previous is None or int(draft.version_number) > previous[0]:
                titles[chapter_index] = (int(draft.version_number), draft.title)
        return [
            {
                "from_chapter_index": source,
                "to_chapter_index": target,
                "title": titles.get(source, (0, None))[1],
                "version_count": counts.get(source, 0),
                "has_published_version": source in published,
            }
            for source, target in chapter_map.items()
            if source != target
        ]

    @staticmethod
    def _writing_blockers(state: dict[str, Any]) -> list[dict[str, Any]]:
        blockers: list[dict[str, Any]] = []
        unlisted = state["unlisted_chapter_indices"]
        if unlisted:
            blockers.append(
                {
                    "kind": "unlisted_chapter_versions",
                    "count": len(unlisted),
                    "message": (
                        "有未出现在当前章节列表中的历史或建议版本；"
                        "请先恢复或明确处理这些章节，再重排。"
                    ),
                    "examples": [{"chapter_index": index} for index in unlisted[:8]],
                }
            )

        hash_mismatches = [
            draft
            for draft in state["drafts"]
            if str(draft.content_hash or "") != hash_text(draft.content)
        ]
        if hash_mismatches:
            blockers.append(
                {
                    "kind": "writing_source_hash_mismatch",
                    "count": len(hash_mismatches),
                    "message": "部分正文来源指纹不匹配，请先修复这些版本。",
                    "examples": [
                        {
                            "chapter_index": int(draft.chapter_index),
                            "version_number": int(draft.version_number),
                        }
                        for draft in hash_mismatches[:8]
                    ],
                }
            )

        draft_by_id = {draft.id: draft for draft in state["drafts"]}
        misbound_comments = [
            comment
            for comment in state["comments"]
            if (draft := draft_by_id.get(comment.draft_id)) is not None
            and (
                int(comment.chapter_index) != int(draft.chapter_index)
                or int(comment.version_number) != int(draft.version_number)
            )
        ]
        if misbound_comments:
            blockers.append(
                {
                    "kind": "writing_comment_binding_mismatch",
                    "count": len(misbound_comments),
                    "message": "部分批注与其正文版本的章节记录不一致，请先核对这些批注。",
                    "examples": [
                        {
                            "chapter_index": int(comment.chapter_index),
                            "version_number": int(comment.version_number),
                        }
                        for comment in misbound_comments[:8]
                    ],
                }
            )
        return blockers

    async def _move_writing_rows(
        self,
        db: AsyncSession,
        state: dict[str, Any],
        chapter_map: dict[int, int],
    ) -> None:
        if not state["drafts"]:
            return
        all_indices = (
            await db.scalars(
                select(WritingDraft.chapter_index)
                .where(WritingDraft.novel_id == state["drafts"][0].novel_id)
                .distinct()
            )
        ).all()
        if any(int(index) < 1 for index in all_indices):
            raise ConflictError("作品中存在无效章节号，不能安全重排")
        temporary = {
            source: min([int(index) for index in all_indices] + [0]) - offset - 1
            for offset, source in enumerate(sorted(chapter_map))
        }
        original_by_draft = {row.id: int(row.chapter_index) for row in state["drafts"]}
        for row in state["drafts"]:
            row.chapter_index = temporary[original_by_draft[row.id]]
        await db.flush()
        for row in state["drafts"]:
            row.chapter_index = chapter_map[original_by_draft[row.id]]
        comment_source = {
            row.id: original_by_draft[row.draft_id]
            for row in state["comments"]
            if row.draft_id in original_by_draft
        }
        for row in state["comments"]:
            source = comment_source.get(row.id)
            if source in chapter_map:
                row.chapter_index = chapter_map[source]
        await db.flush()

    async def _lock_chapters(
        self,
        db: AsyncSession,
        novel_id: str,
        chapter_map: dict[int, int],
    ) -> None:
        nid = _parse_uuid(novel_id, "novel_id")
        await self._repo.lock_chapter_catalog_for_reorder(db, nid)
        await self._repo.lock_version_chapters_for_revalidation(
            db,
            nid,
            list(chapter_map),
        )

    async def _get_operation(
        self,
        db: AsyncSession,
        novel_id: str,
        receipt_id: str,
        *,
        for_update: bool = False,
    ) -> WritingChapterOrderOperation:
        statement = select(WritingChapterOrderOperation).where(
            WritingChapterOrderOperation.novel_id == _parse_uuid(novel_id, "novel_id"),
            WritingChapterOrderOperation.id == _parse_uuid(receipt_id, "receipt_id"),
        )
        if for_update:
            statement = statement.with_for_update().execution_options(
                populate_existing=True
            )
        operation = await db.scalar(statement)
        if operation is None:
            raise NotFoundError("章节顺序操作记录不存在")
        return operation

    def _chapter_map(self, operation: WritingChapterOrderOperation) -> dict[int, int]:
        source_order = [int(index) for index in operation.source_order_json]
        target_order = [int(index) for index in operation.target_order_json]
        target_slots = sorted(source_order)
        return {
            source: target_slots[position] for position, source in enumerate(target_order)
        }

    @staticmethod
    def _chapter_map_for_orders(
        source_order: list[int], target_order: list[int]
    ) -> dict[int, int]:
        target_slots = sorted(source_order)
        return {
            source: target_slots[position] for position, source in enumerate(target_order)
        }

    def _story_port(self) -> StoryChapterOrderPort:
        # Story is the owner of its binding rows; bootstrap registers the adapter.
        return get("story.chapter_order")

    async def _invalidate_standing_authorization(
        self,
        db: AsyncSession,
        novel_id: str,
    ) -> None:
        await get("story.invalidate_world_progression_for_reorder")(
            db,
            novel_id=novel_id,
        )

    @staticmethod
    def _result(
        operation: WritingChapterOrderOperation,
        status: str,
        *,
        replayed: bool,
    ) -> ChapterOrderResultResponse:
        return ChapterOrderResultResponse(
            receipt_id=operation.id,
            status=status,
            replayed=replayed,
            chapter_map=WritingChapterOrderService._chapter_map_for_orders(
                [int(index) for index in operation.source_order_json],
                [int(index) for index in operation.target_order_json],
            ),
            story_impact=operation.impact_json or {},
            result_ref=operation.result_ref_json
            or {"type": "writing_chapter_order", "id": str(operation.id)},
        )


def _chapter_order_hash(value: Any) -> str:
    encoded = json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _text_hash(value: str | None) -> str | None:
    if value is None:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _dt_key(value: datetime | None) -> str | None:
    if value is None:
        return None
    normalized = (
        value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    )
    return normalized.isoformat()
