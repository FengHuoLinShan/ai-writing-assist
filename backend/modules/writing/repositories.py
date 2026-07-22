"""
Writing 数据访问层

封装 writing_drafts 表的所有数据库操作。
只处理 ORM ↔ DB 的基本 CRUD，不含业务逻辑。
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import and_, func, select, text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.llm.redaction import redact_diagnostic
from modules.writing.conflict_evidence import snapshot_location
from modules.writing.models import WritingConflictCheck, WritingConflictItem, WritingDraft
from modules.writing.schemas import WritingDraftCreate, WritingDraftUpdate
from modules.writing.source_hashing import hash_text, substantive_text

WORKING_DRAFT_STATUSES = ("draft", "published", "canonical")
AI_REVIEW_TASK_OWNER_KEY = "_ai_review_task_id"


def public_conflict_summary(summary: dict | None) -> dict:
    """Hide task fencing metadata from stable API/snapshot projections."""
    projected = dict(summary or {})
    projected.pop(AI_REVIEW_TASK_OWNER_KEY, None)
    return projected


class WritingDraftRepository:
    """正文草稿数据访问"""

    async def _build_draft(
        self,
        db: AsyncSession,
        data: WritingDraftCreate,
        *,
        status: str,
    ) -> WritingDraft:
        novel_id = uuid.UUID(hex=data.novel_id)
        return WritingDraft(
            novel_id=novel_id,
            chapter_index=data.chapter_index,
            title=data.title,
            content=data.content,
            content_hash=hash_text(data.content),
            conflict_check_snapshot_json=None,
            provenance_json=data.provenance_json,
            version_number=await self._next_version_number(
                db,
                novel_id,
                data.chapter_index,
            ),
            status=status,
        )

    async def create(
        self,
        db: AsyncSession,
        data: WritingDraftCreate,
    ) -> WritingDraft:
        """创建新草稿版本

        SELECT MAX + 唯一约束兜底实现原子版本号递增。
        """
        draft = await self._build_draft(db, data, status="draft")
        db.add(draft)
        await db.flush()
        return draft

    async def create_with_status(
        self,
        db: AsyncSession,
        data: WritingDraftCreate,
        *,
        status: str,
    ) -> WritingDraft:
        """创建指定状态的新草稿版本。"""
        draft = await self._build_draft(db, data, status=status)
        db.add(draft)
        await db.flush()
        return draft

    async def get(
        self,
        db: AsyncSession,
        draft_id: uuid.UUID,
    ) -> WritingDraft | None:
        """根据 ID 获取草稿"""
        stmt = select(WritingDraft).where(WritingDraft.id == draft_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_for_update(
        self,
        db: AsyncSession,
        draft_id: uuid.UUID,
    ) -> WritingDraft | None:
        """Lock one draft while an adoption transition is decided.

        PostgreSQL serializes concurrent adopters on this row. SQLite ignores
        ``FOR UPDATE`` in tests while preserving the same repository interface.
        """
        stmt = (
            select(WritingDraft)
            .where(WritingDraft.id == draft_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_latest_by_chapter(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        chapter_index: int,
    ) -> WritingDraft | None:
        """获取指定章节的最新草稿（版本号最大）"""
        stmt = (
            select(WritingDraft)
            .where(
                WritingDraft.novel_id == novel_id,
                WritingDraft.chapter_index == chapter_index,
                WritingDraft.status.in_(WORKING_DRAFT_STATUSES),
            )
            .order_by(WritingDraft.version_number.desc())
            .limit(1)
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_latest_published_by_chapter(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        chapter_index: int,
    ) -> WritingDraft | None:
        stmt = (
            select(WritingDraft)
            .where(
                WritingDraft.novel_id == novel_id,
                WritingDraft.chapter_index == chapter_index,
                WritingDraft.status == "published",
            )
            .order_by(WritingDraft.version_number.desc())
            .limit(1)
        )
        return (await db.execute(stmt)).scalar_one_or_none()

    async def get_version_history(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        chapter_index: int,
    ) -> Sequence[WritingDraft]:
        """获取指定章节的所有版本（按版本号降序）"""
        stmt = (
            select(WritingDraft)
            .where(
                WritingDraft.novel_id == novel_id,
                WritingDraft.chapter_index == chapter_index,
            )
            .order_by(WritingDraft.version_number.desc())
        )
        result = await db.execute(stmt)
        return result.scalars().all()

    async def get_previous_working_version(
        self,
        db: AsyncSession,
        draft: WritingDraft,
    ) -> WritingDraft | None:
        stmt = (
            select(WritingDraft)
            .where(
                WritingDraft.novel_id == draft.novel_id,
                WritingDraft.chapter_index == draft.chapter_index,
                WritingDraft.version_number < draft.version_number,
                WritingDraft.status.in_(WORKING_DRAFT_STATUSES),
            )
            .order_by(WritingDraft.version_number.desc())
            .limit(1)
        )
        return (await db.execute(stmt)).scalar_one_or_none()

    async def update(
        self,
        db: AsyncSession,
        draft_or_id: WritingDraft | uuid.UUID,
        data: WritingDraftUpdate,
    ) -> WritingDraft | None:
        """暂存草稿（原地更新，不递增版本号）。返回更新后的对象。"""
        draft = (
            await self.get(db, draft_or_id)
            if isinstance(draft_or_id, uuid.UUID)
            else draft_or_id
        )
        if draft is None:
            return None
        if draft.status == "published":
            raise ValueError("published drafts cannot be updated in place")

        update_values: dict[str, object] = {}
        for field in ("title", "content"):
            value = getattr(data, field, None)
            if value is not None:
                update_values[field] = value

        if update_values:
            if "content" in update_values:
                await self.lock_version_chapters_for_revalidation(
                    db,
                    draft.novel_id,
                    [draft.chapter_index],
                )
            for field, value in update_values.items():
                setattr(draft, field, value)
            if "content" in update_values:
                draft.content_hash = hash_text(draft.content)
            db.add(draft)
            await db.flush()

        return draft

    async def delete(
        self,
        db: AsyncSession,
        draft_id: uuid.UUID,
    ) -> WritingDraft | None:
        """软废弃单个版本，保留稳定来源引用。"""
        draft = await self.get(db, draft_id)
        if draft is None:
            return None

        previous_status = draft.status
        provenance = dict(draft.provenance_json or {})
        provenance.setdefault("deprecated_from_status", previous_status)
        draft.provenance_json = provenance
        draft.status = "deprecated"
        db.add(draft)
        await db.flush()
        return draft

    async def count_versions(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        chapter_index: int,
    ) -> int:
        """返回某章未废弃版本数"""
        stmt = select(func.count(WritingDraft.id)).where(
            WritingDraft.novel_id == novel_id,
            WritingDraft.chapter_index == chapter_index,
            WritingDraft.status != "deprecated",
        )
        result = await db.execute(stmt)
        return result.scalar() or 0

    async def count_working_versions(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        chapter_index: int,
    ) -> int:
        """Return versions that can act as the chapter's editable/published source."""
        stmt = select(func.count(WritingDraft.id)).where(
            WritingDraft.novel_id == novel_id,
            WritingDraft.chapter_index == chapter_index,
            WritingDraft.status.in_(WORKING_DRAFT_STATUSES),
        )
        result = await db.execute(stmt)
        return result.scalar() or 0

    async def delete_all_versions(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        chapter_index: int,
    ) -> int:
        """软废弃某章全部活跃版本。"""
        stmt = select(WritingDraft).where(
            WritingDraft.novel_id == novel_id,
            WritingDraft.chapter_index == chapter_index,
            WritingDraft.status != "deprecated",
        )
        drafts = list((await db.execute(stmt)).scalars().all())
        for draft in drafts:
            draft.provenance_json = {
                **(draft.provenance_json or {}),
                "deprecated_from_status": draft.status,
            }
            draft.status = "deprecated"
        if drafts:
            db.add_all(drafts)
        await db.flush()
        return len(drafts)

    # ============================================================
    # 内部方法
    # ============================================================

    async def list_chapter_indices(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
    ) -> list[int]:
        """列出该小说所有有草稿的章节索引（去重、升序）"""
        stmt = (
            select(WritingDraft.chapter_index)
            .where(
                WritingDraft.novel_id == novel_id,
                WritingDraft.status.in_(WORKING_DRAFT_STATUSES),
            )
            .distinct()
            .order_by(WritingDraft.chapter_index)
        )
        result = await db.execute(stmt)
        return [row[0] for row in result.all()]

    async def list_effective_chapter_indices(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
    ) -> list[int]:
        """List latest working chapters whose body contains substantive text."""
        latest = (
            select(
                WritingDraft.chapter_index.label("chapter_index"),
                func.max(WritingDraft.version_number).label("version_number"),
            )
            .where(
                WritingDraft.novel_id == novel_id,
                WritingDraft.status.in_(WORKING_DRAFT_STATUSES),
            )
            .group_by(WritingDraft.chapter_index)
            .subquery()
        )
        stmt = (
            select(WritingDraft.chapter_index, WritingDraft.content)
            .join(
                latest,
                and_(
                    WritingDraft.chapter_index == latest.c.chapter_index,
                    WritingDraft.version_number == latest.c.version_number,
                ),
            )
            .where(
                WritingDraft.novel_id == novel_id,
                WritingDraft.status.in_(WORKING_DRAFT_STATUSES),
                WritingDraft.content.is_not(None),
                func.length(WritingDraft.content) > 0,
            )
            .order_by(WritingDraft.chapter_index)
        )
        rows = (await db.execute(stmt)).all()
        return [
            chapter_index
            for chapter_index, content in rows
            if substantive_text(content)
        ]

    async def list_chapter_summaries(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
    ) -> Sequence[WritingDraft]:
        """列出每章最新版本草稿，用于章节列表摘要。"""
        latest_versions = (
            select(
                WritingDraft.chapter_index.label("chapter_index"),
                func.max(WritingDraft.version_number).label("version_number"),
            )
            .where(
                WritingDraft.novel_id == novel_id,
                WritingDraft.status.in_(WORKING_DRAFT_STATUSES),
            )
            .group_by(WritingDraft.chapter_index)
            .subquery()
        )
        stmt = (
            select(WritingDraft)
            .join(
                latest_versions,
                (WritingDraft.chapter_index == latest_versions.c.chapter_index)
                & (WritingDraft.version_number == latest_versions.c.version_number),
            )
            .where(
                WritingDraft.novel_id == novel_id,
                WritingDraft.status.in_(WORKING_DRAFT_STATUSES),
            )
            .order_by(WritingDraft.chapter_index, WritingDraft.id)
        )
        result = await db.execute(stmt)
        return result.scalars().all()

    async def list_latest_by_chapters(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        chapter_indices: list[int],
        *,
        content_limit: int | None = None,
    ) -> Sequence[WritingDraft] | Sequence[RowMapping]:
        """按章节集合列出最新版本草稿。"""
        requested = sorted({idx for idx in chapter_indices if idx >= 1})
        if not requested:
            return []
        latest_versions = (
            select(
                WritingDraft.chapter_index.label("chapter_index"),
                func.max(WritingDraft.version_number).label("version_number"),
            )
            .where(
                WritingDraft.novel_id == novel_id,
                WritingDraft.chapter_index.in_(requested),
                WritingDraft.status.in_(WORKING_DRAFT_STATUSES),
            )
            .group_by(WritingDraft.chapter_index)
            .subquery()
        )
        if content_limit is not None:
            stmt = (
                select(
                    WritingDraft.id.label("id"),
                    WritingDraft.novel_id.label("novel_id"),
                    WritingDraft.chapter_index.label("chapter_index"),
                    WritingDraft.title.label("title"),
                    func.substr(WritingDraft.content, 1, content_limit).label("content"),
                    WritingDraft.content_hash.label("content_hash"),
                    WritingDraft.version_number.label("version_number"),
                    WritingDraft.status.label("status"),
                    WritingDraft.conflict_check_snapshot_json.label(
                        "conflict_check_snapshot_json"
                    ),
                    WritingDraft.provenance_json.label("provenance_json"),
                    WritingDraft.created_at.label("created_at"),
                    WritingDraft.updated_at.label("updated_at"),
                )
                .join(
                    latest_versions,
                    (WritingDraft.chapter_index == latest_versions.c.chapter_index)
                    & (WritingDraft.version_number == latest_versions.c.version_number),
                )
                .where(
                    WritingDraft.novel_id == novel_id,
                    WritingDraft.status.in_(WORKING_DRAFT_STATUSES),
                )
                .order_by(WritingDraft.chapter_index)
            )
            result = await db.execute(stmt)
            return result.mappings().all()

        stmt = (
            select(WritingDraft)
            .join(
                latest_versions,
                (WritingDraft.chapter_index == latest_versions.c.chapter_index)
                & (WritingDraft.version_number == latest_versions.c.version_number),
            )
            .where(
                WritingDraft.novel_id == novel_id,
                WritingDraft.status.in_(WORKING_DRAFT_STATUSES),
            )
            .order_by(WritingDraft.chapter_index)
        )
        result = await db.execute(stmt)
        return result.scalars().all()

    async def list_latest_by_mode(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        chapter_indices: list[int],
        *,
        content_mode: str,
    ) -> Sequence[WritingDraft]:
        """Return one concrete source version per requested chapter."""
        requested = sorted({idx for idx in chapter_indices if idx >= 1})
        if not requested:
            return []
        conditions = [
            WritingDraft.novel_id == novel_id,
            WritingDraft.chapter_index.in_(requested),
        ]
        if content_mode == "canonical":
            conditions.append(WritingDraft.status == "published")
        elif content_mode == "working":
            conditions.append(WritingDraft.status.in_(WORKING_DRAFT_STATUSES))
        else:
            raise ValueError("content_mode must be canonical or working")
        latest_versions = (
            select(
                WritingDraft.chapter_index.label("chapter_index"),
                func.max(WritingDraft.version_number).label("version_number"),
            )
            .where(*conditions)
            .group_by(WritingDraft.chapter_index)
            .subquery()
        )
        stmt = (
            select(WritingDraft)
            .join(
                latest_versions,
                (WritingDraft.chapter_index == latest_versions.c.chapter_index)
                & (WritingDraft.version_number == latest_versions.c.version_number),
            )
            .where(WritingDraft.novel_id == novel_id, *conditions[2:])
            .order_by(WritingDraft.chapter_index)
        )
        return (await db.execute(stmt)).scalars().all()

    async def project_stats(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
    ) -> tuple[int, int]:
        """统计该小说每章最新版本的章节数和正文长度。"""
        latest_versions = (
            select(
                WritingDraft.chapter_index.label("chapter_index"),
                func.max(WritingDraft.version_number).label("version_number"),
            )
            .where(
                WritingDraft.novel_id == novel_id,
                WritingDraft.status.in_(WORKING_DRAFT_STATUSES),
            )
            .group_by(WritingDraft.chapter_index)
            .subquery()
        )
        stmt = (
            select(
                func.count(WritingDraft.id),
                func.coalesce(
                    func.sum(func.length(func.coalesce(WritingDraft.content, ""))),
                    0,
                ),
            )
            .join(
                latest_versions,
                (WritingDraft.chapter_index == latest_versions.c.chapter_index)
                & (WritingDraft.version_number == latest_versions.c.version_number),
            )
            .where(WritingDraft.novel_id == novel_id)
        )
        result = await db.execute(stmt)
        chapter_count, word_count = result.one()
        return int(chapter_count or 0), int(word_count or 0)

    async def project_stats_many(
        self,
        db: AsyncSession,
        novel_ids: list[uuid.UUID],
    ) -> dict[uuid.UUID, tuple[int, int]]:
        """批量统计多个小说项目的最新版本章节数和字数。"""
        requested = list(dict.fromkeys(novel_ids))
        if not requested:
            return {}
        latest_versions = (
            select(
                WritingDraft.novel_id.label("novel_id"),
                WritingDraft.chapter_index.label("chapter_index"),
                func.max(WritingDraft.version_number).label("version_number"),
            )
            .where(
                WritingDraft.novel_id.in_(requested),
                WritingDraft.status.in_(WORKING_DRAFT_STATUSES),
            )
            .group_by(WritingDraft.novel_id, WritingDraft.chapter_index)
            .subquery()
        )
        stmt = (
            select(
                WritingDraft.novel_id,
                func.count(WritingDraft.id),
                func.coalesce(
                    func.sum(func.length(func.coalesce(WritingDraft.content, ""))),
                    0,
                ),
            )
            .join(
                latest_versions,
                (WritingDraft.novel_id == latest_versions.c.novel_id)
                & (WritingDraft.chapter_index == latest_versions.c.chapter_index)
                & (WritingDraft.version_number == latest_versions.c.version_number),
            )
            .where(WritingDraft.novel_id.in_(requested))
            .group_by(WritingDraft.novel_id)
        )
        result = await db.execute(stmt)
        stats = {
            novel_id: (int(chapter_count or 0), int(word_count or 0))
            for novel_id, chapter_count, word_count in result.all()
        }
        return {novel_id: stats.get(novel_id, (0, 0)) for novel_id in requested}

    async def update_latest_content(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        chapter_index: int,
        *,
        title: str | None,
        content: str,
    ) -> WritingDraft:
        await self.lock_version_chapters_for_revalidation(
            db,
            novel_id,
            [chapter_index],
        )
        draft = await self.get_latest_by_chapter(db, novel_id, chapter_index)
        if draft is None:
            raise ValueError(f"No draft found for chapter {chapter_index}")
        if draft.status == "published":
            raise ValueError("published drafts cannot be updated in place")
        draft.title = title
        draft.content = content
        draft.content_hash = hash_text(content)
        db.add(draft)
        await db.flush()
        return draft

    async def set_conflict_check_snapshot(
        self,
        db: AsyncSession,
        draft_id: uuid.UUID,
        snapshot: dict,
    ) -> WritingDraft | None:
        draft = await self.get(db, draft_id)
        if draft is None:
            return None
        draft.conflict_check_snapshot_json = snapshot
        db.add(draft)
        await db.flush()
        return draft

    async def _next_version_number(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        chapter_index: int,
    ) -> int:
        """获取下一个版本号 = max(当前版本号) + 1"""
        await self.lock_version_chapters_for_revalidation(
            db,
            novel_id,
            [chapter_index],
        )
        stmt = (
            select(WritingDraft.version_number)
            .where(
                WritingDraft.novel_id == novel_id,
                WritingDraft.chapter_index == chapter_index,
            )
            .order_by(WritingDraft.version_number.desc())
            .limit(1)
            .with_for_update()
        )
        result = await db.execute(stmt)
        max_ver = result.scalar_one_or_none() or 0
        return int(max_ver) + 1

    async def lock_version_chapters_for_revalidation(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        chapter_indices: Sequence[int],
    ) -> None:
        """Serialize version/content writes with task final revalidation."""
        get_bind = getattr(db, "get_bind", None)
        if get_bind is None:
            return
        bind = get_bind()
        if bind is None or bind.dialect.name != "postgresql":
            return
        for chapter_index in sorted(
            {int(index) for index in chapter_indices if int(index) >= 1}
        ):
            await db.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": f"writing_versions:{novel_id}:{chapter_index}"},
            )


class WritingConflictCheckRepository:
    """Writing conflict-check persistence."""

    async def create_check(
        self,
        db: AsyncSession,
        *,
        novel_id: uuid.UUID,
        chapter_index: int,
        scene_id: uuid.UUID | None,
        draft_id: uuid.UUID | None,
        version_number: int | None,
        scope: dict,
        include_candidates: bool,
        status: str,
        summary_json: dict,
        items: list[dict],
    ) -> tuple[WritingConflictCheck, list[WritingConflictItem]]:
        check = WritingConflictCheck(
            novel_id=novel_id,
            chapter_index=chapter_index,
            scene_id=scene_id,
            draft_id=draft_id,
            version_number=version_number,
            scope=scope,
            include_candidates=include_candidates,
            status=status,
            summary_json=summary_json,
        )
        db.add(check)
        await db.flush()

        created_items: list[WritingConflictItem] = []
        for item in items:
            conflict_item = WritingConflictItem(
                check_id=check.id,
                novel_id=novel_id,
                kind=item["kind"],
                severity=item["severity"],
                source_module=item["source_module"],
                source_type=item.get("source_type"),
                source_id=item.get("source_id"),
                evidence_summary=item["evidence_summary"],
                location_json=item.get("location_json"),
                is_ai_judgment=item.get("is_ai_judgment", False),
                needs_review=item.get("needs_review", False),
                confidence=item.get("confidence"),
                source_confirmation_id=item.get("source_confirmation_id"),
                llm_rationale=item.get("llm_rationale"),
                suggestion_status=item.get("suggestion_status", "not_requested"),
                suggestion_confirmation_id=item.get("suggestion_confirmation_id"),
                status=item.get("status", "open"),
                ai_suggestion=item.get("ai_suggestion"),
                suggestion_error=(
                    redact_diagnostic(item["suggestion_error"], limit=500)
                    if item.get("suggestion_error") is not None
                    else None
                ),
            )
            db.add(conflict_item)
            created_items.append(conflict_item)
        await db.flush()
        return check, created_items

    async def get_check(
        self,
        db: AsyncSession,
        check_id: uuid.UUID,
        novel_id: uuid.UUID,
    ) -> tuple[WritingConflictCheck, list[WritingConflictItem]] | None:
        stmt = select(WritingConflictCheck).where(
            WritingConflictCheck.id == check_id,
            WritingConflictCheck.novel_id == novel_id,
        )
        result = await db.execute(stmt)
        check = result.scalar_one_or_none()
        if check is None:
            return None
        return check, await self.list_items(db, check.id, novel_id)

    async def get_check_for_ai_review_update(
        self,
        db: AsyncSession,
        check_id: uuid.UUID,
        novel_id: uuid.UUID,
    ) -> tuple[WritingConflictCheck, list[WritingConflictItem]] | None:
        """Lock one check and its current items for a serialized AI review update."""
        stmt = (
            select(WritingConflictCheck)
            .where(
                WritingConflictCheck.id == check_id,
                WritingConflictCheck.novel_id == novel_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        check = (await db.execute(stmt)).scalar_one_or_none()
        if check is None:
            return None
        items_stmt = (
            select(WritingConflictItem)
            .where(
                WritingConflictItem.check_id == check_id,
                WritingConflictItem.novel_id == novel_id,
            )
            .order_by(
                WritingConflictItem.severity,
                WritingConflictItem.created_at,
                WritingConflictItem.id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        items = list((await db.execute(items_stmt)).scalars().all())
        return check, items

    async def list_checks(
        self,
        db: AsyncSession,
        *,
        novel_id: uuid.UUID,
        chapter_index: int,
        scene_id: uuid.UUID | None,
        limit: int,
        exact_scene_scope: bool = False,
    ) -> tuple[list[tuple[WritingConflictCheck, list[WritingConflictItem]]], int]:
        conditions = [
            WritingConflictCheck.novel_id == novel_id,
            WritingConflictCheck.chapter_index == chapter_index,
        ]
        if scene_id is not None:
            conditions.append(WritingConflictCheck.scene_id == scene_id)
        elif exact_scene_scope:
            conditions.append(WritingConflictCheck.scene_id.is_(None))

        count_stmt = select(func.count(WritingConflictCheck.id)).where(*conditions)
        total = (await db.execute(count_stmt)).scalar() or 0
        stmt = (
            select(WritingConflictCheck)
            .where(*conditions)
            .order_by(
                WritingConflictCheck.created_at.desc(),
                WritingConflictCheck.id.desc(),
            )
            .limit(limit)
        )
        result = await db.execute(stmt)
        checks = result.scalars().all()
        items_by_check_id = await self._list_items_for_checks(
            db,
            [check.id for check in checks],
            novel_id,
        )
        return [(check, items_by_check_id.get(check.id, [])) for check in checks], total

    async def latest_check(
        self,
        db: AsyncSession,
        *,
        novel_id: uuid.UUID,
        chapter_index: int,
        scene_id: uuid.UUID | None,
        exact_scene_scope: bool = False,
    ) -> tuple[WritingConflictCheck, list[WritingConflictItem]] | None:
        checks, _ = await self.list_checks(
            db,
            novel_id=novel_id,
            chapter_index=chapter_index,
            scene_id=scene_id,
            limit=1,
            exact_scene_scope=exact_scene_scope,
        )
        return checks[0] if checks else None

    async def list_items(
        self,
        db: AsyncSession,
        check_id: uuid.UUID,
        novel_id: uuid.UUID,
    ) -> list[WritingConflictItem]:
        stmt = (
            select(WritingConflictItem)
            .where(
                WritingConflictItem.check_id == check_id,
                WritingConflictItem.novel_id == novel_id,
            )
            .order_by(
                WritingConflictItem.severity,
                WritingConflictItem.created_at,
                WritingConflictItem.id,
            )
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def _list_items_for_checks(
        self,
        db: AsyncSession,
        check_ids: list[uuid.UUID],
        novel_id: uuid.UUID,
    ) -> dict[uuid.UUID, list[WritingConflictItem]]:
        if not check_ids:
            return {}
        stmt = (
            select(WritingConflictItem)
            .where(
                WritingConflictItem.check_id.in_(check_ids),
                WritingConflictItem.novel_id == novel_id,
            )
            .order_by(
                WritingConflictItem.check_id,
                WritingConflictItem.severity,
                WritingConflictItem.created_at,
                WritingConflictItem.id,
            )
        )
        result = await db.execute(stmt)
        items_by_check_id: dict[uuid.UUID, list[WritingConflictItem]] = {
            check_id: [] for check_id in check_ids
        }
        for item in result.scalars().all():
            items_by_check_id.setdefault(item.check_id, []).append(item)
        return items_by_check_id

    async def get_item(
        self,
        db: AsyncSession,
        item_id: uuid.UUID,
        novel_id: uuid.UUID,
    ) -> WritingConflictItem | None:
        stmt = select(WritingConflictItem).where(
            WritingConflictItem.id == item_id,
            WritingConflictItem.novel_id == novel_id,
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def update_item_status(
        self,
        db: AsyncSession,
        *,
        item_id: uuid.UUID,
        novel_id: uuid.UUID,
        status: str,
    ) -> WritingConflictItem | None:
        item = await self.get_item(db, item_id, novel_id)
        if item is None:
            return None
        item.status = status
        db.add(item)
        await db.flush()
        return item

    async def append_items(
        self,
        db: AsyncSession,
        *,
        check_id: uuid.UUID,
        novel_id: uuid.UUID,
        items: list[dict],
    ) -> list[WritingConflictItem]:
        created_items: list[WritingConflictItem] = []
        for item in items:
            conflict_item = WritingConflictItem(
                check_id=check_id,
                novel_id=novel_id,
                kind=item["kind"],
                severity=item["severity"],
                source_module=item["source_module"],
                source_type=item.get("source_type"),
                source_id=item.get("source_id"),
                evidence_summary=item["evidence_summary"],
                location_json=item.get("location_json"),
                is_ai_judgment=item.get("is_ai_judgment", False),
                needs_review=item.get("needs_review", False),
                confidence=item.get("confidence"),
                source_confirmation_id=item.get("source_confirmation_id"),
                llm_rationale=item.get("llm_rationale"),
                status=item.get("status", "open"),
                suggestion_status=item.get("suggestion_status", "not_requested"),
                suggestion_confirmation_id=item.get("suggestion_confirmation_id"),
                ai_suggestion=item.get("ai_suggestion"),
                suggestion_error=(
                    redact_diagnostic(item["suggestion_error"], limit=500)
                    if item.get("suggestion_error") is not None
                    else None
                ),
            )
            db.add(conflict_item)
            created_items.append(conflict_item)
        await db.flush()
        return created_items

    async def update_ai_review(
        self,
        db: AsyncSession,
        *,
        check_id: uuid.UUID,
        novel_id: uuid.UUID,
        status: str,
        summary_json: dict | None = None,
        confirmation_id: uuid.UUID | None = None,
        model: str | None = None,
        error: str | None = None,
    ) -> WritingConflictCheck | None:
        stmt = select(WritingConflictCheck).where(
            WritingConflictCheck.id == check_id,
            WritingConflictCheck.novel_id == novel_id,
        )
        result = await db.execute(stmt)
        check = result.scalar_one_or_none()
        if check is None:
            return None
        return await self.update_loaded_ai_review(
            db,
            check,
            status=status,
            summary_json=summary_json,
            confirmation_id=confirmation_id,
            model=model,
            error=error,
        )

    async def update_loaded_ai_review(
        self,
        db: AsyncSession,
        check: WritingConflictCheck,
        *,
        status: str,
        summary_json: dict | None = None,
        confirmation_id: uuid.UUID | None = None,
        model: str | None = None,
        error: str | None = None,
    ) -> WritingConflictCheck:
        """Update an already loaded/locked check without re-querying it."""
        check.ai_review_enabled = True
        check.ai_review_status = status
        check.ai_review_confirmation_id = confirmation_id
        check.ai_review_model = model
        check.ai_review_error = (
            redact_diagnostic(error, limit=500) if error is not None else None
        )
        if summary_json is not None:
            check.summary_json = summary_json
        db.add(check)
        await db.flush()
        return check

    async def update_item_suggestion(
        self,
        db: AsyncSession,
        *,
        item_id: uuid.UUID,
        novel_id: uuid.UUID,
        status: str,
        confirmation_id: uuid.UUID | None = None,
        ai_suggestion: str | None = None,
        llm_rationale: str | None = None,
        error: str | None = None,
    ) -> WritingConflictItem | None:
        item = await self.get_item(db, item_id, novel_id)
        if item is None:
            return None
        return await self.update_loaded_item_suggestion(
            db,
            item,
            status=status,
            confirmation_id=confirmation_id,
            ai_suggestion=ai_suggestion,
            llm_rationale=llm_rationale,
            error=error,
        )

    async def update_loaded_item_suggestion(
        self,
        db: AsyncSession,
        item: WritingConflictItem,
        *,
        status: str,
        confirmation_id: uuid.UUID | None = None,
        ai_suggestion: str | None = None,
        llm_rationale: str | None = None,
        error: str | None = None,
    ) -> WritingConflictItem:
        item.suggestion_status = status
        item.suggestion_confirmation_id = confirmation_id
        item.ai_suggestion = ai_suggestion
        item.llm_rationale = llm_rationale
        item.suggestion_error = (
            redact_diagnostic(error, limit=500) if error is not None else None
        )
        db.add(item)
        await db.flush()
        return item

    async def build_latest_snapshot(
        self,
        db: AsyncSession,
        *,
        novel_id: uuid.UUID,
        chapter_index: int,
        scene_id: uuid.UUID | None,
    ) -> dict | None:
        latest = await self.latest_check(
            db,
            novel_id=novel_id,
            chapter_index=chapter_index,
            scene_id=scene_id,
            exact_scene_scope=True,
        )
        if latest is None:
            return None
        check, items = latest
        open_items = [item for item in items if item.status == "open"]
        high_items = [item for item in open_items if item.severity == "high"]
        ai_items = [item for item in items if item.is_ai_judgment]
        suggestion_items = [item for item in items if item.ai_suggestion]
        return {
            "check_id": str(check.id),
            "checked_at": check.created_at.isoformat() if check.created_at else None,
            "status": check.status,
            "summary_json": public_conflict_summary(check.summary_json),
            "open_count": len(open_items),
            "open_high_count": len(high_items),
            "ai_review_status": check.ai_review_status,
            "ai_judgment_count": len(ai_items),
            "suggestion_count": len(suggestion_items),
            "items": [
                {
                    "id": str(item.id),
                    "kind": item.kind,
                    "severity": item.severity,
                    "status": item.status,
                    "source_module": item.source_module,
                    "evidence_summary": item.evidence_summary,
                    "location_json": snapshot_location(item.location_json),
                    "is_ai_judgment": item.is_ai_judgment,
                    "needs_review": item.needs_review,
                    "suggestion_status": item.suggestion_status,
                    "has_ai_suggestion": bool(item.ai_suggestion),
                }
                for item in items
            ],
        }
