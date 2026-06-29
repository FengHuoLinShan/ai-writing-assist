"""
Writing 数据访问层

封装 writing_drafts 表的所有数据库操作。
只处理 ORM ↔ DB 的基本 CRUD，不含业务逻辑。
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from modules.writing.conflict_evidence import snapshot_location
from modules.writing.models import WritingConflictCheck, WritingConflictItem, WritingDraft
from modules.writing.schemas import WritingDraftCreate, WritingDraftUpdate


class WritingDraftRepository:
    """正文草稿数据访问"""

    async def create(
        self,
        db: AsyncSession,
        data: WritingDraftCreate,
    ) -> WritingDraft:
        """创建新草稿版本

        SELECT MAX + 唯一约束兜底实现原子版本号递增。
        """
        novel_id = uuid.UUID(hex=data.novel_id)

        next_version = await self._next_version_number(
            db,
            novel_id,
            data.chapter_index,
        )

        draft = WritingDraft(
            novel_id=novel_id,
            chapter_index=data.chapter_index,
            title=data.title,
            content=data.content,
            conflict_check_snapshot_json=None,
            version_number=next_version,
            status="draft",
        )
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
        novel_id = uuid.UUID(hex=data.novel_id)
        next_version = await self._next_version_number(
            db,
            novel_id,
            data.chapter_index,
        )
        draft = WritingDraft(
            novel_id=novel_id,
            chapter_index=data.chapter_index,
            title=data.title,
            content=data.content,
            conflict_check_snapshot_json=None,
            version_number=next_version,
            status=status,
        )
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
            )
            .order_by(WritingDraft.version_number.desc())
            .limit(1)
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

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

    async def update(
        self,
        db: AsyncSession,
        draft_id: uuid.UUID,
        data: WritingDraftUpdate,
    ) -> WritingDraft | None:
        """暂存草稿（原地更新，不递增版本号）。返回更新后的对象。"""
        draft = await self.get(db, draft_id)
        if draft is None:
            return None

        update_values: dict[str, object] = {}
        for field in ("title", "content"):
            value = getattr(data, field, None)
            if value is not None:
                update_values[field] = value

        if update_values:
            stmt = (
                update(WritingDraft)
                .where(WritingDraft.id == draft_id)
                .values(**update_values)
            )
            await db.execute(stmt)
            await db.flush()
            draft = await self.get(db, draft_id)

        return draft

    async def delete(
        self,
        db: AsyncSession,
        draft_id: uuid.UUID,
    ) -> WritingDraft | None:
        """删除单个版本。返回被删除的 draft（用于后续重排版本号）。"""
        draft = await self.get(db, draft_id)
        if draft is None:
            return None

        # 删除该版本
        del_stmt = delete(WritingDraft).where(WritingDraft.id == draft_id)
        await db.execute(del_stmt)
        await db.flush()
        return draft

    async def renumber_versions_after_delete(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        chapter_index: int,
        deleted_version: int,
    ) -> None:
        """删除后重排高于被删版本的版本号（-1）。"""
        renumber_stmt = (
            update(WritingDraft)
            .where(
                WritingDraft.novel_id == novel_id,
                WritingDraft.chapter_index == chapter_index,
                WritingDraft.version_number > deleted_version,
            )
            .values(version_number=WritingDraft.version_number - 1)
        )
        await db.execute(renumber_stmt)
        await db.flush()

    async def count_versions(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        chapter_index: int,
    ) -> int:
        """返回某章版本总数"""
        stmt = select(func.count(WritingDraft.id)).where(
            WritingDraft.novel_id == novel_id,
            WritingDraft.chapter_index == chapter_index,
        )
        result = await db.execute(stmt)
        return result.scalar() or 0

    async def delete_all_versions(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        chapter_index: int,
    ) -> int:
        """删除某章全部版本。返回删除的版本数。"""
        stmt = delete(WritingDraft).where(
            WritingDraft.novel_id == novel_id,
            WritingDraft.chapter_index == chapter_index,
        )
        result = await db.execute(stmt)
        await db.flush()
        return result.rowcount or 0

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
            .where(WritingDraft.novel_id == novel_id)
            .distinct()
            .order_by(WritingDraft.chapter_index)
        )
        result = await db.execute(stmt)
        return [row[0] for row in result.all()]

    async def update_latest_content(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        chapter_index: int,
        *,
        title: str | None,
        content: str,
    ) -> WritingDraft:
        draft = await self.get_latest_by_chapter(db, novel_id, chapter_index)
        if draft is None:
            raise ValueError(f"No draft found for chapter {chapter_index}")
        draft.title = title
        draft.content = content
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

    async def shift_chapter_indices_from(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        start_index: int,
    ) -> None:
        stmt = (
            select(WritingDraft.chapter_index)
            .where(
                WritingDraft.novel_id == novel_id,
                WritingDraft.chapter_index >= start_index,
            )
            .distinct()
            .order_by(WritingDraft.chapter_index.desc())
        )
        result = await db.execute(stmt)
        indices = [row[0] for row in result.all()]
        for idx in indices:
            await db.execute(
                update(WritingDraft)
                .where(
                    WritingDraft.novel_id == novel_id,
                    WritingDraft.chapter_index == idx,
                )
                .values(chapter_index=idx + 1)
            )
        await db.flush()

    async def _next_version_number(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        chapter_index: int,
    ) -> int:
        """获取下一个版本号 = max(当前版本号) + 1"""
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
                suggestion_error=item.get("suggestion_error"),
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
            .order_by(WritingConflictCheck.created_at.desc())
            .limit(limit)
        )
        result = await db.execute(stmt)
        checks = result.scalars().all()
        pairs = []
        for check in checks:
            pairs.append((check, await self.list_items(db, check.id, novel_id)))
        return pairs, total

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
            .order_by(WritingConflictItem.severity, WritingConflictItem.created_at)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

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
                suggestion_error=item.get("suggestion_error"),
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
        check.ai_review_enabled = True
        check.ai_review_status = status
        check.ai_review_confirmation_id = confirmation_id
        check.ai_review_model = model
        check.ai_review_error = error
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
        item.suggestion_status = status
        item.suggestion_confirmation_id = confirmation_id
        item.ai_suggestion = ai_suggestion
        item.llm_rationale = llm_rationale
        item.suggestion_error = error
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
            "summary_json": check.summary_json,
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
