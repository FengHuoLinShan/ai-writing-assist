"""
Timeline 业务逻辑层

调用 repository 完成业务操作，包含时间线查询和冲突检查。
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException
from fastapi import status as http_status
from sqlalchemy.ext.asyncio import AsyncSession

from modules.timeline.repositories import TimelineEventRepository
from modules.timeline.schemas import (
    TimelineConflictWarning,
    TimelineEventContext,
    TimelineEventCreate,
    TimelineEventResponse,
    TimelineEventUpdate,
)
from shared.utils import parse_uuid

_DEFAULT_CONTEXT_LIMIT = 12


class TimelineService:
    """时间线业务服务"""

    def __init__(self) -> None:
        self._repo = TimelineEventRepository()

    # ============================================================
    # 时间线事件 CRUD
    # ============================================================

    async def create_event(
        self,
        db: AsyncSession,
        novel_id: str,
        data: TimelineEventCreate,
    ) -> TimelineEventResponse:
        """创建新的时间线事件"""
        nid = parse_uuid(novel_id)
        event = await self._repo.create(db, nid, data)
        return TimelineEventResponse.model_validate(event)

    async def get_event(
        self,
        db: AsyncSession,
        event_id: str,
        novel_id: str,
    ) -> TimelineEventResponse:
        """获取时间线事件详情"""
        eid = parse_uuid(event_id)
        nid = parse_uuid(novel_id)
        event = await self._repo.get(db, eid)
        if event is None or str(event.novel_id) != str(nid):
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Timeline event {event_id} not found",
            )
        return TimelineEventResponse.model_validate(event)

    async def list_events(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        skip: int = 0,
        limit: int = 20,
        status: str | None = None,
        event_type: str | None = None,
        before_chapter: int | None = None,
        character_id: str | None = None,
    ) -> tuple[list[TimelineEventResponse], int]:
        """获取时间线事件列表"""
        nid = parse_uuid(novel_id)
        items, total = await self._repo.get_multi(
            db,
            nid,
            skip=skip,
            limit=limit,
            status=status,
            event_type=event_type,
            before_chapter_index=before_chapter,
            character_id=character_id,
        )
        return [TimelineEventResponse.model_validate(e) for e in items], total

    async def update_event(
        self,
        db: AsyncSession,
        event_id: str,
        data: TimelineEventUpdate,
        novel_id: str,
    ) -> TimelineEventResponse:
        """更新时间线事件"""
        eid = parse_uuid(event_id)
        nid = parse_uuid(novel_id)
        event = await self._repo.get(db, eid)
        if event is None or str(event.novel_id) != str(nid):
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Timeline event {event_id} not found",
            )
        event = await self._repo.update(db, eid, data)
        return TimelineEventResponse.model_validate(event)

    async def delete_event(
        self,
        db: AsyncSession,
        event_id: str,
        novel_id: str,
    ) -> None:
        """删除时间线事件"""
        eid = parse_uuid(event_id)
        nid = parse_uuid(novel_id)
        event = await self._repo.get(db, eid)
        if event is None or str(event.novel_id) != str(nid):
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Timeline event {event_id} not found",
            )
        await self._repo.delete(db, eid)

    # ============================================================
    # Facade 支持方法
    # ============================================================

    async def get_relevant_timeline_context(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        chapter_index: int | None = None,
        related_entity_ids: list[str] | None = None,
        character_id: str | None = None,
        limit: int = _DEFAULT_CONTEXT_LIMIT,
    ) -> list[TimelineEventContext]:
        """获取相关时间线上下文

        Args:
            db: 数据库 session
            novel_id: 项目 ID
            chapter_index: 只返回该章节之前的事件
            related_entity_ids: 按关联实体过滤
            character_id: 按关联角色过滤
            limit: 最大返回条数

        Returns:
            list[TimelineEventContext]: 时间线事件上下文
        """
        nid = parse_uuid(novel_id)

        # 按实体+角色关联查询
        if related_entity_ids:
            cid = parse_uuid(character_id) if character_id else None
            items, _ = await self._repo.get_multi(
                db,
                nid,
                status="canonical",
                before_chapter_index=chapter_index,
                entity_ids=related_entity_ids,
                character_id=str(cid) if cid else None,
                limit=limit,
            )
            return [
                TimelineEventContext.model_validate(e) for e in items
            ]

        # 没有 entity_ids：按角色或章节过滤
        if character_id:
            items, _ = await self._repo.get_multi(
                db,
                nid,
                status="canonical",
                before_chapter_index=chapter_index,
                character_id=character_id,
                limit=limit,
            )
            return [
                TimelineEventContext.model_validate(e) for e in items
            ]

        # 最后：只按章节过滤
        items, _ = await self._repo.get_multi(
            db,
            nid,
            status="canonical",
            before_chapter_index=chapter_index,
            limit=limit,
        )
        return [TimelineEventContext.model_validate(e) for e in items]

    async def check_timeline_conflicts(
        self,
        db: AsyncSession,
        novel_id: str,
        structure_candidate: dict[str, Any],
    ) -> list[TimelineConflictWarning]:
        """检查候选结构事件是否与已有 timeline 冲突

        检查维度：
        1. 顺序矛盾 — 候选事件在已有事件之前/之后不合理
        2. 事件重复 — 候选事件与已有事件描述相同
        3. 角色冲突 — 角色同时在两地出现

        Args:
            db: 数据库 session
            novel_id: 项目 ID
            structure_candidate: 候选结构（含 events 列表）

        Returns:
            list[TimelineConflictWarning]: 冲突警告列表
        """
        nid = parse_uuid(novel_id)
        warnings: list[TimelineConflictWarning] = []

        # 获取正史事件
        existing_events = await self._repo.get_all_by_novel(
            db, nid, status="canonical"
        )

        candidate_events = structure_candidate.get("events", [])
        if not candidate_events:
            return warnings

        # 1. 顺序矛盾检查
        for i, candidate in enumerate(candidate_events):
            candidate_order = candidate.get("order_index", i)

            # 检查在已有事件之后但 chapter_index 却在前面
            if candidate.get("chapter_index") is not None:
                for existing in existing_events:
                    if (
                        existing.chapter_index is not None
                        and candidate["chapter_index"] < existing.chapter_index
                        and candidate_order > existing.order_index
                    ):
                        warnings.append(
                            TimelineConflictWarning(
                                type="order_conflict",
                                description=(
                                    f"候选事件「{candidate.get('title', '')}」"
                                    f"的顺序索引({candidate_order})在"
                                    f"「{existing.title}」({existing.order_index})之后，"
                                    f"但章节索引({candidate['chapter_index']})却在"
                                    f"「{existing.title}」({existing.chapter_index})之前"
                                ),
                                severity="warning",
                                source_event_ids=[str(existing.id)],
                                suggestion=(
                                    f"调整候选事件的 order_index 或 chapter_index "
                                    f"使其与「{existing.title}」的顺序一致"
                                ),
                            )
                        )

        # 2. 重复事件检查
        for candidate in candidate_events:
            c_title = candidate.get("title", "").strip()
            c_summary = candidate.get("summary", "").strip()

            # 简单文本相似检查：标题相同或摘要高度重叠
            for existing in existing_events:
                if not c_title or not existing.title:
                    continue

                # 标题完全相同
                if c_title == existing.title.strip():
                    warnings.append(
                        TimelineConflictWarning(
                            type="duplicate_event",
                            description=(
                                f"候选事件「{c_title}」"
                                f"与已有事件「{existing.title}」标题完全相同"
                            ),
                            severity="warning",
                            source_event_ids=[str(existing.id)],
                            suggestion="检查是否为同一事件，如是则复用已有事件 ID 而非创建新事件",
                        )
                    )
                    continue

                # 标题高度重叠（用于中文标题）
                if len(c_title) >= 4 and len(existing.title) >= 4:
                    shorter = min(c_title, existing.title, key=len)
                    longer = c_title if shorter == existing.title else existing.title
                    if shorter in longer:
                        warnings.append(
                            TimelineConflictWarning(
                                type="duplicate_event",
                                description=(
                                    f"候选事件「{c_title}」"
                                    f"与已有事件「{existing.title}」标题高度重叠"
                                ),
                                severity="info",
                                source_event_ids=[str(existing.id)],
                                suggestion="确认是否为同一事件的不同表述",
                            )
                        )

        # 3. 角色冲突检查（简单实现）
        # 收集每个角色在每章的事件 ID，用于比对位置
        character_chapter_events: dict[str, dict[int, list[str]]] = {}
        for existing in existing_events:
            for cid in (existing.related_character_ids or []):
                cid_str = str(cid)
                ch = existing.chapter_index or 0
                character_chapter_events.setdefault(cid_str, {}).setdefault(ch, []).append(
                    str(existing.id)
                )

        for candidate in candidate_events:
            cand_ch = candidate.get("chapter_index")
            if cand_ch is None:
                continue
            for cid in (candidate.get("related_character_ids") or []):
                existing_event_ids = character_chapter_events.get(cid, {}).get(cand_ch)
                if existing_event_ids:
                    candidate_loc_ids = candidate.get("related_location_ids", [])
                    # 简单检查：候选事件有位置信息且已有事件在同一章
                    if candidate_loc_ids:
                        warnings.append(
                            TimelineConflictWarning(
                                type="character_location_conflict",
                                description=(
                                    f"角色 {cid} 在同一章节(第{cand_ch}章)"
                                    f"出现在已有事件中，请确认位置是否一致"
                                ),
                                severity="info",
                                source_event_ids=existing_event_ids,
                                suggestion="确认角色是否可能在同一章节出现在多个位置",
                            )
                        )

        return warnings

    # ============================================================
    # 内部工具
    # ============================================================

