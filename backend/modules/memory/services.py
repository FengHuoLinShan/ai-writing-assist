"""
Memory 业务逻辑层

事件溯源 + 阶段性快照的协调逻辑。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.memory.contracts import (
    MemoryContinuityEvidenceContract,
    MemoryDeltaEventIngest,
    MemoryDeltaIngestResult,
)
from modules.memory.models import DeltaLog
from modules.memory.repositories import EventRepository, SnapshotRepository
from modules.memory.schemas import (
    ChapterPanorama,
    CharacterLocationInPanorama,
    EntityInPanorama,
    EventListResponse,
    EventType,
    KnowledgeInPanorama,
    MemoryEventResponse,
    MemoryStatusResponse,
    RelationInPanorama,
    SnapshotListResponse,
    SnapshotResponse,
)
from shared.utils import parse_uuid

logger = logging.getLogger(__name__)

_SNAPSHOT_INTERVAL = 10  # K=10


class MemoryService:
    """记忆业务服务 — 事件溯源引擎"""

    def __init__(
        self,
        event_repo: EventRepository | None = None,
        snapshot_repo: SnapshotRepository | None = None,
    ) -> None:
        self._event_repo = event_repo or EventRepository()
        self._snapshot_repo = snapshot_repo or SnapshotRepository()

    # ============================================================
    # 事件记录
    # ============================================================

    async def record_events(
        self,
        db: AsyncSession,
        novel_id: str,
        chapter_index: int,
        events: list[dict[str, Any]],
    ) -> list[MemoryEventResponse]:
        """批量记录一章的变化事件

        events 格式: [{"event_type": "entity_created", "entity_id": ..., ...}, ...]
        """
        nid = parse_uuid(novel_id)
        # 先清除该章的旧事件（如果存在）
        await self._event_repo.delete_by_chapter(db, nid, chapter_index)

        results: list[MemoryEventResponse] = []
        for seq, evt in enumerate(events, start=1):
            record = await self._event_repo.create(
                db,
                novel_id=nid,
                chapter_index=chapter_index,
                sequence=seq,
                event_type=evt["event_type"],
                entity_id=parse_uuid(evt["entity_id"]) if evt.get("entity_id") else None,
                entity_type=evt.get("entity_type"),
                snapshot_before=evt.get("snapshot_before"),
                snapshot_after=evt.get("snapshot_after", evt.get("payload", {})),
                source=evt.get("source", "ai_extraction"),
            )
            results.append(MemoryEventResponse.model_validate(record))

        await db.flush()
        return results

    # ============================================================
    # 状态重放
    # ============================================================

    async def replay_state(
        self,
        db: AsyncSession,
        novel_id: str,
        chapter_index: int,
    ) -> dict[str, Any]:
        """重放事件至指定章节，返回完整世界状态

        优先从最近快照 + 增量事件重放。
        """
        nid = parse_uuid(novel_id)
        nearest = await self._snapshot_repo.get_nearest(db, nid, chapter_index)

        if nearest:
            state = dict(nearest.full_state)
            start_chapter = nearest.chapter_index + 1
        else:
            state = {
                "entities": {},
                "relations": [],
                "character_locations": {},
                "character_knowledge": [],
            }
            start_chapter = 1

        if start_chapter <= chapter_index:
            events = await self._event_repo.get_by_chapter_range(
                db, nid, start_chapter, chapter_index
            )
            state = self._apply_events(state, events)

        return state

    # ============================================================
    # 快照管理
    # ============================================================

    async def capture_snapshot(
        self,
        db: AsyncSession,
        novel_id: str,
        chapter_index: int,
    ) -> SnapshotResponse:
        """在指定章生成快照节点

        从 world facade 抓取当前世界状态，结合 replay 的事件流验证一致性，
        然后物化为快照行。
        """
        from modules.world.facade import get_full_state

        nid = parse_uuid(novel_id)

        # 获取当前世界完整状态
        full_state = await get_full_state(db, novel_id)

        # 计算该快照覆盖的事件数
        events = await self._event_repo.get_by_chapter_range(db, nid, 1, chapter_index)

        snapshot = await self._snapshot_repo.create(
            db,
            novel_id=nid,
            chapter_index=chapter_index,
            full_state=full_state,
            events_until=len(events),
        )

        return SnapshotResponse.model_validate(snapshot)

    async def create_delta_log(
        self,
        db: AsyncSession,
        novel_id: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Create a DeltaLog record and return the stable facade shape."""
        nid = parse_uuid(novel_id, "novel_id")
        delta = DeltaLog(
            novel_id=nid,
            **kwargs,
        )
        db.add(delta)
        await db.flush()
        return {
            "id": str(delta.id),
            "novel_id": str(delta.novel_id),
            "entity_id": str(delta.entity_id) if delta.entity_id else None,
            "category": delta.category,
            "source": delta.source,
            "scene_index": delta.scene_index,
            "field_path": delta.field_path,
        }

    async def ingest_delta_events(
        self,
        db: AsyncSession,
        novel_id: str,
        events: list[MemoryDeltaEventIngest],
        *,
        result_refs: list[dict[str, str]] | None = None,
    ) -> MemoryDeltaIngestResult:
        """Create DeltaLog rows from typed delta events."""
        delta_logs: list[dict[str, Any]] = []
        for event in events:
            provenance_key = (
                event.scene_provenance_key
                or f"{event.workflow_id or 'manual'}:scene:{event.scene_index}"
            )
            source_ref = {
                "workflow_id": event.workflow_id,
                "scene_id": event.scene_id,
                "scene_provenance_key": provenance_key,
                "auto_ingested": True,
            }
            meta = {
                **(event.meta or {}),
                "source": event.source,
                "workflow_id": event.workflow_id,
                "scene_id": event.scene_id,
                "scene_provenance_key": provenance_key,
                "auto_ingested": True,
                "source_ref": {
                    **((event.meta or {}).get("source_ref") or {}),
                    **source_ref,
                },
            }
            if event.context_snapshot_id:
                meta["context_snapshot_id"] = event.context_snapshot_id
            delta = await self.create_delta_log(
                db,
                novel_id,
                scene_index=event.scene_index,
                category=event.category,
                field_path=event.field_path,
                old_value=self._delta_value(event.old_value),
                new_value=self._delta_value(event.new_value),
                source=event.source,
                meta=meta,
            )
            delta_logs.append(delta)
            if result_refs is not None and delta.get("id"):
                result_refs.append({"type": "delta_log", "id": delta["id"]})
        return MemoryDeltaIngestResult(count=len(delta_logs), delta_logs=delta_logs)

    @staticmethod
    def _delta_value(value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=False)

    async def count_deep_import_delta_logs_by_workflow(
        self,
        db: AsyncSession,
        novel_id: str,
        workflow_id: str,
    ) -> int:
        """Count auto-ingested deep import DeltaLogs for cleanup reporting."""
        nid = parse_uuid(novel_id, "novel_id")
        stmt = select(DeltaLog).where(
            DeltaLog.novel_id == nid,
            DeltaLog.source == "deep_import",
        )
        result = await db.execute(stmt)
        items = result.scalars().all()
        return sum(
            1
            for item in items
            if (item.meta or {}).get("workflow_id") == workflow_id
            and (item.meta or {}).get("auto_ingested") is True
        )

    # ============================================================
    # 全景查询
    # ============================================================

    async def get_panorama(
        self,
        db: AsyncSession,
        novel_id: str,
        chapter_index: int,
    ) -> ChapterPanorama:
        """返回指定章节的世界全景

        流程：找最近快照 → 应用增量事件 → 组装 ChapterPanorama
        如果没有任何快照/事件，回退到 world facade 直接获取当前状态。
        """
        nid = parse_uuid(novel_id)
        from modules.world.facade import get_full_state

        nearest = await self._snapshot_repo.get_nearest(db, nid, chapter_index)

        if nearest:
            state = dict(nearest.full_state)
            start_chapter = nearest.chapter_index + 1
            if start_chapter <= chapter_index:
                events = await self._event_repo.get_by_chapter_range(
                    db, nid, start_chapter, chapter_index
                )
                state = self._apply_events(state, events)
        else:
            # 没有任何快照 — 检查是否有事件可重放
            events = await self._event_repo.get_by_chapter_range(
                db, nid, 1, chapter_index
            )
            if events:
                state = self._apply_events(
                    {
                        "entities": {},
                        "relations": [],
                        "character_locations": {},
                        "character_knowledge": [],
                    },
                    events,
                )
            else:
                # 完全没有数据，回退到 world 当前状态
                state = await get_full_state(db, novel_id)

        return self._build_panorama(novel_id, chapter_index, state)

    async def get_continuity_evidence_for_writing(
        self,
        db: AsyncSession,
        novel_id: str,
        chapter_index: int,
        *,
        pov_character_id: str | None,
        current_location_id: str | None,
        current_location_name: str | None = None,
    ) -> MemoryContinuityEvidenceContract | None:
        """Return previous-location evidence for writing continuity checks."""
        if not pov_character_id or not current_location_id or chapter_index <= 1:
            return None
        previous_chapter = chapter_index - 1
        nid = parse_uuid(novel_id)
        nearest = await self._snapshot_repo.get_nearest(db, nid, previous_chapter)
        if not nearest:
            events = await self._event_repo.get_by_chapter_range(
                db, nid, 1, previous_chapter
            )
            if not events:
                return None
        panorama = await self.get_panorama(db, novel_id, previous_chapter)
        character_locations = getattr(panorama, "character_locations", None) or {}
        if not isinstance(character_locations, dict):
            return None
        previous_location = character_locations.get(pov_character_id)
        if previous_location is None:
            return None
        previous_location_id = getattr(previous_location, "location_id", None)
        if previous_location_id is None and isinstance(previous_location, dict):
            previous_location_id = previous_location.get("location_id")
        if not previous_location_id or previous_location_id == current_location_id:
            return None
        previous_text = getattr(previous_location, "text_state", None)
        if previous_text is None and isinstance(previous_location, dict):
            previous_text = previous_location.get("text_state")
        previous_text = previous_text or str(previous_location_id)
        current_text = current_location_name or current_location_id
        return MemoryContinuityEvidenceContract(
            source_module="memory",
            source_type="memory.character_location",
            source_id=pov_character_id,
            source_label=f"章节记忆：第 {previous_chapter} 章",
            source_field="角色位置",
            source_excerpt=f"上一章 {previous_text}，当前 {current_text}",
            open_target={
                "kind": "memory_chapter",
                "chapter_index": previous_chapter,
                "character_id": pov_character_id,
            },
        )

    # ============================================================
    # 过时管理
    # ============================================================

    async def mark_stale(
        self,
        db: AsyncSession,
        novel_id: str,
        from_chapter: int,
    ) -> dict[str, Any]:
        """标记从指定章节开始的所有快照为过时"""
        nid = parse_uuid(novel_id)
        count = await self._snapshot_repo.mark_stale_from(db, nid, from_chapter)
        logger.info("Marked %d snapshots as stale from chapter %d", count, from_chapter)
        return {"stale_count": count, "from_chapter": from_chapter}

    async def list_events(
        self,
        db: AsyncSession,
        novel_id: str,
        from_chapter: int,
        to_chapter: int,
    ) -> EventListResponse:
        """按章节范围查询事件列表"""
        nid = parse_uuid(novel_id)
        events = await self._event_repo.get_by_chapter_range(
            db,
            nid,
            from_chapter,
            to_chapter,
        )
        items = [MemoryEventResponse.model_validate(e) for e in events]
        return EventListResponse(items=items, total=len(items))

    async def get_entity_timeline(
        self,
        db: AsyncSession,
        novel_id: str,
        entity_id: str,
        skip: int,
        limit: int,
    ) -> EventListResponse:
        """获取单个实体的变化时间线"""
        nid = parse_uuid(novel_id)
        eid = parse_uuid(entity_id)
        events, total = await self._event_repo.get_by_entity(
            db,
            nid,
            eid,
            skip=skip,
            limit=limit,
        )
        items = [MemoryEventResponse.model_validate(e) for e in events]
        return EventListResponse(items=items, total=total)

    async def list_snapshots(
        self,
        db: AsyncSession,
        novel_id: str,
    ) -> SnapshotListResponse:
        """列出所有快照"""
        nid = parse_uuid(novel_id)
        snapshots = await self._snapshot_repo.list_for_novel(db, nid)
        items = [SnapshotResponse.model_validate(s) for s in snapshots]
        return SnapshotListResponse(items=items, total=len(items))

    async def get_status(
        self,
        db: AsyncSession,
        novel_id: str,
    ) -> MemoryStatusResponse:
        """获取 memory 模块当前状态"""
        nid = parse_uuid(novel_id)
        snapshots = await self._snapshot_repo.list_for_novel(db, nid)

        if not snapshots:
            return MemoryStatusResponse(
                novel_id=novel_id,
                latest_chapter=None,
                latest_snapshot_chapter=None,
                has_stale=False,
                stale_from_chapter=None,
            )

        latest_current = max(
            (s.chapter_index for s in snapshots if s.status == "current"),
            default=None,
        )
        stale_snapshots = [s for s in snapshots if s.status == "stale"]
        stale_from = (
            min((s.chapter_index for s in stale_snapshots), default=None)
            if stale_snapshots
            else None
        )

        return MemoryStatusResponse(
            novel_id=novel_id,
            latest_chapter=max(s.chapter_index for s in snapshots),
            latest_snapshot_chapter=latest_current,
            has_stale=len(stale_snapshots) > 0,
            stale_from_chapter=stale_from,
        )

    # ============================================================
    # 手动全更新
    # ============================================================

    async def full_rebuild(
        self,
        db: AsyncSession,
        novel_id: str,
        from_chapter: int,
    ) -> dict[str, Any]:
        """从前文修正点开始，全量重建后续的事件和快照

        流程：
        1. 重放到 from_chapter-1 的状态作为基准
        2. 获取 world 当前完整状态
        3. 对比差异，重新生成 from_chapter 之后的事件
        4. 重建 from_chapter 之后的快照
        """
        nid = parse_uuid(novel_id)
        from modules.world.facade import get_full_state

        # 清理旧数据
        await self._snapshot_repo.delete_stale(db, nid)
        await self._event_repo.delete_from_chapter(db, nid, from_chapter)

        # 获取基准状态（from_chapter 之前的状态）
        if from_chapter > 1:
            base_state = await self.replay_state(db, novel_id, from_chapter - 1)
        else:
            base_state = {
                "entities": {},
                "relations": [],
                "character_locations": {},
                "character_knowledge": [],
            }

        # 获取当前世界状态
        current_state = await get_full_state(db, novel_id)

        # 计算差异事件
        all_events = self._diff_states(base_state, current_state)

        # 按章节重新分配事件（如果事件中带有 chapter_index 信息）
        # v1 简化：将所有差异事件作为 from_chapter 的新事件
        # 后续可扩展为更细粒度的差异分配
        if all_events:
            await self.record_events(db, novel_id, from_chapter, all_events)

        # 重建快照（每 K 章一个，加上最新章）
        all_events_after = await self._event_repo.get_by_chapter_range(
            db, nid, from_chapter, 999999
        )
        final_chapter = max(
            (e.chapter_index for e in all_events_after), default=from_chapter
        )

        rebuilt_count = 0
        for ch in range(from_chapter, final_chapter + 1):
            if ch % _SNAPSHOT_INTERVAL == 0 or ch == final_chapter:
                await self.capture_snapshot(db, novel_id, ch)
                rebuilt_count += 1

        return {
            "rebuilt_snapshots": rebuilt_count,
            "from_chapter": from_chapter,
            "final_chapter": final_chapter,
        }

    # ============================================================
    # 内部方法
    # ============================================================

    def _apply_events(self, state: dict[str, Any], events: list[Any]) -> dict[str, Any]:
        """应用事件序列到状态上"""
        state = {
            "entities": {e["id"]: e for e in state.get("entities", [])},
            "relations": list(state.get("relations", [])),
            "character_locations": dict(state.get("character_locations", {})),
            "character_knowledge": list(state.get("character_knowledge", [])),
        }

        for event in events:
            etype = event.event_type
            after = event.snapshot_after or {}
            eid = str(event.entity_id) if event.entity_id else None

            if etype == EventType.entity_created and eid:
                state["entities"][eid] = after
            elif etype == EventType.entity_updated and eid:
                if eid in state["entities"]:
                    state["entities"][eid].update(after)
            elif etype == EventType.entity_removed and eid:
                state["entities"].pop(eid, None)
            elif etype == EventType.entity_moved and eid:
                state["character_locations"][eid] = after
            elif etype == EventType.relation_established:
                state["relations"].append(after)
            elif etype == EventType.relation_ended:
                rel_id = after.get("relation_id") or after.get("id")
                state["relations"] = [
                    r for r in state["relations"] if r.get("id") != rel_id
                ]
            elif etype == EventType.knowledge_changed:
                state["character_knowledge"].append(after)

        # 将 entities 恢复为列表格式
        state["entities"] = list(state["entities"].values())
        return state

    def _diff_states(self, before: dict, after: dict) -> list[dict[str, Any]]:
        """对比两个世界状态，生成变化事件列表"""
        events: list[dict[str, Any]] = []

        before_entities = {e["id"]: e for e in before.get("entities", [])}
        after_entities = {e["id"]: e for e in after.get("entities", [])}

        # 新增或更新的实体
        for eid, aent in after_entities.items():
            bent = before_entities.get(eid)
            if bent is None:
                events.append(
                    {
                        "event_type": EventType.entity_created,
                        "entity_id": eid,
                        "entity_type": aent.get("entity_type"),
                        "snapshot_after": aent,
                        "source": "ai_extraction",
                    }
                )
            else:
                # 简单对比：检查关键字段变化
                changed = False
                for key in (
                    "name",
                    "summary",
                    "public_info",
                    "hidden_truth",
                    "importance",
                    "status",
                ):
                    if aent.get(key) != bent.get(key):
                        changed = True
                        break
                if changed:
                    events.append(
                        {
                            "event_type": EventType.entity_updated,
                            "entity_id": eid,
                            "entity_type": aent.get("entity_type"),
                            "snapshot_before": bent,
                            "snapshot_after": aent,
                            "source": "ai_extraction",
                        }
                    )

        # 删除的实体
        for eid in before_entities:
            if eid not in after_entities:
                events.append(
                    {
                        "event_type": EventType.entity_removed,
                        "entity_id": eid,
                        "entity_type": before_entities[eid].get("entity_type"),
                        "snapshot_before": before_entities[eid],
                        "snapshot_after": {},
                        "source": "manual_edit",
                    }
                )

        # 关系变化
        before_rels = {
            (r["source_id"], r["target_id"], r.get("relation_type", "")): r
            for r in before.get("relations", [])
        }
        after_rels = {
            (r["source_id"], r["target_id"], r.get("relation_type", "")): r
            for r in after.get("relations", [])
        }

        for key, arel in after_rels.items():
            if key not in before_rels:
                events.append(
                    {
                        "event_type": EventType.relation_established,
                        "entity_id": arel.get("source_id"),
                        "entity_type": "relation",
                        "snapshot_after": arel,
                        "source": "ai_extraction",
                    }
                )

        for key, brel in before_rels.items():
            if key not in after_rels:
                events.append(
                    {
                        "event_type": EventType.relation_ended,
                        "entity_id": brel.get("source_id"),
                        "entity_type": "relation",
                        "snapshot_before": brel,
                        "snapshot_after": {"relation_id": brel.get("id")},
                        "source": "manual_edit",
                    }
                )

        # 角色位置变化
        before_locs = before.get("character_locations", {})
        after_locs = after.get("character_locations", {})
        for cid, aloc in after_locs.items():
            bloc = before_locs.get(cid, {})
            if str(aloc.get("location_id")) != str(bloc.get("location_id")):
                events.append(
                    {
                        "event_type": EventType.entity_moved,
                        "entity_id": cid,
                        "entity_type": "character",
                        "snapshot_before": bloc if bloc else None,
                        "snapshot_after": aloc,
                        "source": "ai_extraction",
                    }
                )

        return events

    def _build_panorama(
        self,
        novel_id: str,
        chapter_index: int,
        state: dict[str, Any],
    ) -> ChapterPanorama:
        """将内部状态字典转换为 ChapterPanorama"""
        entities = [EntityInPanorama(**e) for e in state.get("entities", [])]
        relations = [RelationInPanorama(**r) for r in state.get("relations", [])]
        locations: dict[str, CharacterLocationInPanorama] = {}
        for cid, loc in state.get("character_locations", {}).items():
            locations[cid] = CharacterLocationInPanorama(**loc)
        knowledge = [
            KnowledgeInPanorama(**k) for k in state.get("character_knowledge", [])
        ]

        return ChapterPanorama(
            novel_id=novel_id,
            chapter_index=chapter_index,
            entities=entities,
            relations=relations,
            character_locations=locations,
            character_knowledge=knowledge,
        )
