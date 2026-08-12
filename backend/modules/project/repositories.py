"""
Project Repository
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, func, select, tuple_, update
from sqlalchemy.ext.asyncio import AsyncSession

from modules.project.models import Project, SmartDedupWorkbenchDecision
from modules.project.schemas import ProjectCreate, ProjectUpdate


class ProjectRepository:
    """项目数据访问层"""

    async def get(
        self,
        db: AsyncSession,
        project_id: uuid.UUID,
        owner_id: uuid.UUID | None = None,
        project_kind: str | None = "author",
    ) -> Project | None:
        conditions = [
            Project.id == project_id,
            Project.deleted_at.is_(None),
        ]
        if owner_id is not None:
            conditions.append(Project.owner_id == owner_id)
        if project_kind is not None:
            conditions.append(Project.project_kind == project_kind)
        stmt = select(Project).where(*conditions)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_active_for_share(
        self,
        db: AsyncSession,
        project_id: uuid.UUID,
        owner_id: uuid.UUID | None = None,
        project_kind: str | None = "author",
    ) -> Project | None:
        """Lock an active project against deletion for the caller transaction.

        PostgreSQL renders ``read=True`` as ``FOR SHARE``. Concurrent readers
        remain compatible, while updates to ``deleted_at`` wait until the
        guarded business transaction commits or rolls back.
        """
        conditions = [Project.id == project_id, Project.deleted_at.is_(None)]
        if owner_id is not None:
            conditions.append(Project.owner_id == owner_id)
        if project_kind is not None:
            conditions.append(Project.project_kind == project_kind)
        stmt = select(Project).where(*conditions).with_for_update(read=True)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_active_for_update(
        self,
        db: AsyncSession,
        project_id: uuid.UUID,
        owner_id: uuid.UUID | None = None,
        project_kind: str | None = "author",
    ) -> Project | None:
        """Exclusively lock one active project for a short finalizer.

        This is intentionally separate from the normal ``FOR SHARE`` guard:
        callers must not hold this lock across provider or other network I/O.
        """
        conditions = [Project.id == project_id, Project.deleted_at.is_(None)]
        if owner_id is not None:
            conditions.append(Project.owner_id == owner_id)
        if project_kind is not None:
            conditions.append(Project.project_kind == project_kind)
        stmt = select(Project).where(*conditions).with_for_update()
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def list(
        self,
        db: AsyncSession,
        skip: int = 0,
        limit: int = 20,
        owner_id: uuid.UUID | None = None,
        project_kind: str = "author",
    ) -> tuple[list[Project], int]:
        conditions = [Project.deleted_at.is_(None)]
        if owner_id is not None:
            conditions.append(Project.owner_id == owner_id)
        conditions.append(Project.project_kind == project_kind)
        count_stmt = select(func.count(Project.id)).where(*conditions)
        count_result = await db.execute(count_stmt)
        total = count_result.scalar() or 0
        stmt = (
            select(Project)
            .where(*conditions)
            .offset(skip)
            .limit(limit)
            .order_by(Project.created_at.desc(), Project.id.desc())
        )
        result = await db.execute(stmt)
        items = list(result.scalars().all())
        return items, total

    async def create(
        self,
        db: AsyncSession,
        data: ProjectCreate,
        owner_id: uuid.UUID | None = None,
        project_kind: str = "author",
    ) -> Project:
        values = dict(
            title=data.title,
            genre=data.genre,
            tone=data.tone,
            language=data.language or "zh",
            target_length=data.target_length,
            current_stage=data.current_stage,
            default_reveal_policy=data.default_reveal_policy or "author_safe",
            settings=data.settings or {},
            project_kind=project_kind,
        )
        if owner_id is not None:
            values["owner_id"] = owner_id
        project = Project(**values)
        db.add(project)
        await db.flush()
        return project

    async def update(
        self,
        db: AsyncSession,
        project_or_id: Project | uuid.UUID,
        data: ProjectUpdate,
        owner_id: uuid.UUID | None = None,
    ) -> Project | None:
        project = (
            (
                await self.get(db, project_or_id, owner_id)
                if owner_id is not None
                else await self.get(db, project_or_id)
            )
            if isinstance(project_or_id, uuid.UUID)
            else project_or_id
        )
        if project is None:
            return None
        update_values: dict[str, object] = {}
        for field in (
            "title",
            "genre",
            "tone",
            "language",
            "target_length",
            "current_stage",
            "default_reveal_policy",
            "settings",
        ):
            value = getattr(data, field, None)
            if value is not None:
                update_values[field] = value
        if update_values:
            for field, value in update_values.items():
                setattr(project, field, value)
            db.add(project)
            await db.flush()
        return project

    # ============================================================
    # 软删除
    # ============================================================

    async def get_deleted(
        self,
        db: AsyncSession,
        project_id: uuid.UUID,
        owner_id: uuid.UUID | None = None,
        project_kind: str = "author",
    ) -> Project | None:
        conditions = [
            Project.id == project_id,
            Project.deleted_at.isnot(None),
        ]
        if owner_id is not None:
            conditions.append(Project.owner_id == owner_id)
        conditions.append(Project.project_kind == project_kind)
        stmt = select(Project).where(*conditions)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def soft_delete(
        self,
        db: AsyncSession,
        project_id: uuid.UUID,
        owner_id: uuid.UUID | None = None,
        project_kind: str = "author",
    ) -> bool:
        """标记项目为软删除（设置 deleted_at）"""
        conditions = [Project.id == project_id, Project.deleted_at.is_(None)]
        if owner_id is not None:
            conditions.append(Project.owner_id == owner_id)
        conditions.append(Project.project_kind == project_kind)
        stmt = update(Project).where(*conditions).values(deleted_at=datetime.now(UTC))
        result = await db.execute(stmt)
        await db.flush()
        return result.rowcount > 0

    async def restore(
        self,
        db: AsyncSession,
        project_id: uuid.UUID,
        owner_id: uuid.UUID | None = None,
        project_kind: str = "author",
    ) -> bool:
        """恢复已删除项目（清除 deleted_at）"""
        conditions = [Project.id == project_id, Project.deleted_at.isnot(None)]
        if owner_id is not None:
            conditions.append(Project.owner_id == owner_id)
        conditions.append(Project.project_kind == project_kind)
        stmt = update(Project).where(*conditions).values(deleted_at=None)
        result = await db.execute(stmt)
        await db.flush()
        return result.rowcount > 0

    async def list_deleted(
        self,
        db: AsyncSession,
        skip: int = 0,
        limit: int = 20,
        owner_id: uuid.UUID | None = None,
        project_kind: str = "author",
    ) -> tuple[list[Project], int]:
        """列出回收站中的项目"""
        conditions = [Project.deleted_at.isnot(None)]
        if owner_id is not None:
            conditions.append(Project.owner_id == owner_id)
        conditions.append(Project.project_kind == project_kind)
        count_stmt = select(func.count(Project.id)).where(*conditions)
        total = (await db.execute(count_stmt)).scalar() or 0
        stmt = (
            select(Project)
            .where(*conditions)
            .offset(skip)
            .limit(limit)
            .order_by(Project.deleted_at.desc(), Project.id.desc())
        )
        result = await db.execute(stmt)
        return list(result.scalars().all()), total

    async def permanent_delete(
        self,
        db: AsyncSession,
        project_id: uuid.UUID,
        owner_id: uuid.UUID | None = None,
        project_kind: str = "author",
    ) -> bool:
        """永久删除项目（硬删除，数据库 CASCADE 处理关联数据）"""
        conditions = [Project.id == project_id, Project.deleted_at.isnot(None)]
        if owner_id is not None:
            conditions.append(Project.owner_id == owner_id)
        conditions.append(Project.project_kind == project_kind)
        stmt = delete(Project).where(*conditions)
        result = await db.execute(stmt)
        await db.flush()
        return result.rowcount > 0

    async def list_deleted_ids(
        self,
        db: AsyncSession,
        project_ids: list[uuid.UUID],
        owner_id: uuid.UUID | None = None,
        project_kind: str = "author",
    ) -> set[uuid.UUID]:
        """返回指定 ID 中当前确实在回收站的项目。"""
        if not project_ids:
            return set()
        conditions = [
            Project.id.in_(project_ids),
            Project.deleted_at.isnot(None),
        ]
        if owner_id is not None:
            conditions.append(Project.owner_id == owner_id)
        conditions.append(Project.project_kind == project_kind)
        stmt = select(Project.id).where(*conditions)
        result = await db.execute(stmt)
        return set(result.scalars().all())

    async def lock_deleted_ids_for_update(
        self,
        db: AsyncSession,
        project_ids: list[uuid.UUID],
        owner_id: uuid.UUID | None = None,
        project_kind: str = "author",
    ) -> set[uuid.UUID]:
        """Fence storage finalizers before hard deletion and global cleanup enqueue."""
        conditions = [
            Project.id.in_(project_ids),
            Project.deleted_at.isnot(None),
            Project.project_kind == project_kind,
        ]
        if owner_id is not None:
            conditions.append(Project.owner_id == owner_id)
        result = await db.execute(
            select(Project.id).where(*conditions).with_for_update()
        )
        return set(result.scalars().all())

    async def permanent_delete_many(
        self,
        db: AsyncSession,
        project_ids: list[uuid.UUID],
        owner_id: uuid.UUID | None = None,
        project_kind: str = "author",
    ) -> int:
        """批量硬删除回收站项目，由数据库 CASCADE 清理关联数据。"""
        if not project_ids:
            return 0
        conditions = [
            Project.id.in_(project_ids),
            Project.deleted_at.isnot(None),
        ]
        if owner_id is not None:
            conditions.append(Project.owner_id == owner_id)
        conditions.append(Project.project_kind == project_kind)
        stmt = delete(Project).where(*conditions)
        result = await db.execute(stmt)
        await db.flush()
        return result.rowcount or 0


class SmartDedupWorkbenchDecisionRepository:
    async def list_active(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        asset_types: set[str],
    ) -> list[SmartDedupWorkbenchDecision]:
        if not asset_types:
            return []
        result = await db.execute(
            select(SmartDedupWorkbenchDecision).where(
                SmartDedupWorkbenchDecision.novel_id == novel_id,
                SmartDedupWorkbenchDecision.asset_type.in_(asset_types),
                SmartDedupWorkbenchDecision.superseded_at.is_(None),
            )
        )
        return list(result.scalars().all())

    async def supersede_changed_pairs(
        self,
        db: AsyncSession,
        active: list[SmartDedupWorkbenchDecision],
        current_pairs: list[dict[str, str]],
    ) -> int:
        """Invalidate active decisions when the same pair has new semantics."""
        current = {
            (
                item["asset_type"],
                item["left_asset_id"],
                item["right_asset_id"],
            ): (
                item["left_semantic_fingerprint"],
                item["right_semantic_fingerprint"],
            )
            for item in current_pairs
        }
        changed = 0
        for decision in active:
            fingerprints = current.get(
                (
                    decision.asset_type,
                    decision.left_asset_id,
                    decision.right_asset_id,
                )
            )
            if fingerprints is None or fingerprints == (
                decision.left_semantic_fingerprint,
                decision.right_semantic_fingerprint,
            ):
                continue
            decision.superseded_at = datetime.now(UTC)
            changed += 1
        if changed:
            await db.flush()
        return changed

    async def keep_separate(
        self,
        db: AsyncSession,
        *,
        novel_id: uuid.UUID,
        asset_type: str,
        left_asset_id: str,
        right_asset_id: str,
        left_semantic_fingerprint: str,
        right_semantic_fingerprint: str,
        source_scan_task_id: str,
    ) -> SmartDedupWorkbenchDecision:
        decisions = await self.keep_separate_many(
            db,
            novel_id=novel_id,
            asset_type=asset_type,
            dispositions=[
                {
                    "left_asset_id": left_asset_id,
                    "right_asset_id": right_asset_id,
                    "left_semantic_fingerprint": left_semantic_fingerprint,
                    "right_semantic_fingerprint": right_semantic_fingerprint,
                }
            ],
            source_scan_task_id=source_scan_task_id,
        )
        return decisions[0]

    async def keep_separate_many(
        self,
        db: AsyncSession,
        *,
        novel_id: uuid.UUID,
        asset_type: str,
        dispositions: list[dict[str, str]],
        source_scan_task_id: str,
    ) -> list[SmartDedupWorkbenchDecision]:
        """Persist one group's pair dispositions with bounded database work."""
        if not dispositions:
            return []

        # Serialize pair-disposition changes per project so identical concurrent
        # submissions remain idempotent and new fingerprints cannot leave two
        # active decisions for the same pair.
        await db.execute(
            select(Project.id).where(Project.id == novel_id).with_for_update()
        )

        normalized: list[tuple[str, str, str, str]] = []
        fingerprints_by_pair: dict[tuple[str, str], tuple[str, str]] = {}
        for disposition in dispositions:
            supplied_left = disposition["left_asset_id"]
            supplied_right = disposition["right_asset_id"]
            left_id, right_id = sorted((supplied_left, supplied_right))
            left_fingerprint = disposition["left_semantic_fingerprint"]
            right_fingerprint = disposition["right_semantic_fingerprint"]
            if left_id != supplied_left:
                left_fingerprint, right_fingerprint = (
                    right_fingerprint,
                    left_fingerprint,
                )
            pair = (left_id, right_id)
            fingerprints = (left_fingerprint, right_fingerprint)
            previous = fingerprints_by_pair.setdefault(pair, fingerprints)
            if previous != fingerprints:
                raise ValueError("conflicting keep_separate pair fingerprints")
            normalized.append((*pair, *fingerprints))

        pairs = set(fingerprints_by_pair)
        result = await db.execute(
            select(SmartDedupWorkbenchDecision).where(
                SmartDedupWorkbenchDecision.novel_id == novel_id,
                SmartDedupWorkbenchDecision.asset_type == asset_type,
                SmartDedupWorkbenchDecision.superseded_at.is_(None),
                tuple_(
                    SmartDedupWorkbenchDecision.left_asset_id,
                    SmartDedupWorkbenchDecision.right_asset_id,
                ).in_(sorted(pairs)),
            )
        )
        active_by_pair: dict[tuple[str, str], list[SmartDedupWorkbenchDecision]] = {}
        for item in result.scalars().all():
            active_by_pair.setdefault(
                (item.left_asset_id, item.right_asset_id), []
            ).append(item)

        persisted_by_key: dict[
            tuple[str, str, str, str], SmartDedupWorkbenchDecision
        ] = {}
        now = datetime.now(UTC)
        for left_id, right_id, left_fingerprint, right_fingerprint in normalized:
            key = (left_id, right_id, left_fingerprint, right_fingerprint)
            if key in persisted_by_key:
                continue
            active = active_by_pair.get((left_id, right_id), [])
            matching = next(
                (
                    item
                    for item in active
                    if item.left_semantic_fingerprint == left_fingerprint
                    and item.right_semantic_fingerprint == right_fingerprint
                ),
                None,
            )
            if matching is not None:
                # Older deployments could contain more than one active row for
                # a pair because the partial unique index also includes the
                # fingerprints.  Reusing the matching row must still repair
                # that legacy state; otherwise the pair remains ambiguous.
                for item in active:
                    if item is not matching:
                        item.superseded_at = now
                active_by_pair[(left_id, right_id)] = [matching]
                persisted_by_key[key] = matching
                continue
            for item in active:
                item.superseded_at = now
            decision = SmartDedupWorkbenchDecision(
                novel_id=novel_id,
                asset_type=asset_type,
                left_asset_id=left_id,
                right_asset_id=right_id,
                left_semantic_fingerprint=left_fingerprint,
                right_semantic_fingerprint=right_fingerprint,
                decision="keep_separate",
                source_scan_task_id=source_scan_task_id,
            )
            db.add(decision)
            active_by_pair[(left_id, right_id)] = [decision]
            persisted_by_key[key] = decision
        await db.flush()
        return [persisted_by_key[item] for item in normalized]
