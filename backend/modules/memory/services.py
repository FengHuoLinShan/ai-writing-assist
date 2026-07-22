"""
Memory 业务逻辑层

事件溯源 + 阶段性快照的协调逻辑。
"""

from __future__ import annotations

import json
import logging
import uuid
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ValidationError
from modules.memory.contracts import (
    MemoryContinuityEvidenceContract,
    MemoryDeltaEventIngest,
    MemoryDeltaIngestResult,
)
from modules.memory.models import DeltaLog
from modules.memory.repositories import (
    DeltaLogRepository,
    EventRepository,
    SceneCheckpointRepository,
    SceneSnapshotRepository,
    SnapshotRepository,
)
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
MEMORY_REPLAY_EVENT_BATCH_SIZE = 500
MEMORY_EVENT_LIST_BATCH_SIZE = 500
DELTA_ROLLBACK_BATCH_SIZE = 500
MAX_MEMORY_EVENTS_PER_CHAPTER = 500
MAX_MEMORY_EVENT_PAYLOAD_CHARS = 20000


class MemoryService:
    """记忆业务服务 — 事件溯源引擎"""

    def __init__(
        self,
        event_repo: EventRepository | None = None,
        snapshot_repo: SnapshotRepository | None = None,
        delta_log_repo: DeltaLogRepository | None = None,
        scene_checkpoint_repo: SceneCheckpointRepository | None = None,
        scene_snapshot_repo: SceneSnapshotRepository | None = None,
    ) -> None:
        self._event_repo = event_repo or EventRepository()
        self._snapshot_repo = snapshot_repo or SnapshotRepository()
        self._delta_log_repo = delta_log_repo or DeltaLogRepository()
        self._scene_checkpoint_repo = (
            scene_checkpoint_repo or SceneCheckpointRepository()
        )
        self._scene_snapshot_repo = scene_snapshot_repo or SceneSnapshotRepository()

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
        if len(events) > MAX_MEMORY_EVENTS_PER_CHAPTER:
            raise ValidationError(
                "Too many memory events for chapter: "
                f"count={len(events)}, max={MAX_MEMORY_EVENTS_PER_CHAPTER}"
            )
        for index, evt in enumerate(events, start=1):
            serialized = json.dumps(evt, ensure_ascii=False, default=str)
            if len(serialized) > MAX_MEMORY_EVENT_PAYLOAD_CHARS:
                raise ValidationError(
                    "Memory event payload exceeds limit: "
                    f"event_index={index}, max_chars={MAX_MEMORY_EVENT_PAYLOAD_CHARS}"
                )

        nid = parse_uuid(novel_id)
        rows = [
            {
                "novel_id": nid,
                "chapter_index": chapter_index,
                "sequence": seq,
                "event_type": evt["event_type"],
                "entity_id": parse_uuid(evt["entity_id"])
                if evt.get("entity_id")
                else None,
                "entity_type": evt.get("entity_type"),
                "snapshot_before": evt.get("snapshot_before"),
                "snapshot_after": evt.get("snapshot_after", evt.get("payload", {})),
                "source": evt.get("source", "ai_extraction"),
            }
            for seq, evt in enumerate(events, start=1)
        ]
        records = await self._event_repo.replace_chapter_events(
            db,
            novel_id=nid,
            chapter_index=chapter_index,
            rows=rows,
        )
        results = [MemoryEventResponse.model_validate(record) for record in records]

        await db.flush()
        return results

    async def record_scene_events(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        scene_id: str,
        scene_index: int,
        chapter_index: int,
        events: list[dict[str, Any]],
    ) -> list[MemoryEventResponse]:
        """Replace one Scene's event stream using Scene as the atomic stage."""
        from modules.outline.facade import get_scene_contract

        scene = await get_scene_contract(db, novel_id, scene_id)
        if scene is None:
            raise ValidationError("Scene not found")
        if scene.scene_index != scene_index:
            raise ValidationError("scene_index does not match Scene")
        if len(events) > MAX_MEMORY_EVENTS_PER_CHAPTER:
            raise ValidationError("Too many memory events for Scene")
        rows: list[dict[str, Any]] = []
        for sequence, event in enumerate(events, start=1):
            dimension = event.get("dimension") or self._event_dimension(event)
            if dimension not in {"entities", "relations", "locations", "knowledge"}:
                raise ValidationError("Unsupported memory event dimension")
            payload = event.get("snapshot_after", event.get("payload", {}))
            serialized = json.dumps(payload, ensure_ascii=False, default=str)
            if len(serialized) > MAX_MEMORY_EVENT_PAYLOAD_CHARS:
                raise ValidationError("Memory event payload exceeds limit")
            rows.append(
                {
                    "scene_sequence": sequence,
                    "dimension": dimension,
                    "event_type": event.get("event_type", "manual_correction"),
                    "entity_id": parse_uuid(event["entity_id"], "entity_id")
                    if event.get("entity_id")
                    else None,
                    "entity_type": event.get("entity_type"),
                    "snapshot_before": event.get("snapshot_before"),
                    "snapshot_after": payload,
                    "source": event.get("source", "ai_extraction"),
                }
            )
        records = await self._event_repo.replace_scene_events(
            db,
            novel_id=parse_uuid(novel_id, "novel_id"),
            scene_id=parse_uuid(scene_id, "scene_id"),
            scene_index=scene_index,
            chapter_index=chapter_index,
            rows=rows,
        )
        await self._scene_checkpoint_repo.supersede_system_from(
            db,
            parse_uuid(novel_id, "novel_id"),
            scene_index,
            ["entities", "relations", "locations", "knowledge"],
            include_start=True,
        )
        await self._scene_snapshot_repo.supersede_from(
            db,
            parse_uuid(novel_id, "novel_id"),
            scene_index,
            include_start=True,
        )
        return [MemoryEventResponse.model_validate(item) for item in records]

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
            state, _ = await self._apply_events_in_range(
                db,
                nid,
                start_chapter,
                chapter_index,
                state,
            )

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
        """物化事件重放结果；绝不把当前 World 注入历史章节。"""
        nid = parse_uuid(novel_id)
        full_state = await self.replay_state(db, novel_id, chapter_index)

        # 计算该快照覆盖的事件数，不加载完整事件流
        events_until = await self._event_repo.count_by_chapter_range(
            db, nid, 1, chapter_index
        )

        snapshot = await self._snapshot_repo.create(
            db,
            novel_id=nid,
            chapter_index=chapter_index,
            full_state=full_state,
            events_until=events_until,
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
        scene_groups: dict[tuple[str, int, int], list[dict[str, Any]]] = {}
        for event in events:
            if not event.scene_id or event.source_chapter_index is None:
                continue
            key = (event.scene_id, event.scene_index, event.source_chapter_index)
            scene_groups.setdefault(key, []).append(
                {
                    "event_type": "manual_correction",
                    "dimension": self._delta_dimension(event.category),
                    "entity_id": (event.meta or {}).get("entity_id"),
                    "snapshot_after": {
                        "category": event.category,
                        "field_path": event.field_path,
                        "old_value": event.old_value,
                        "new_value": event.new_value,
                        "meta": event.meta or {},
                    },
                    "source": event.source,
                }
            )
        for (scene_id, scene_index, chapter_index), scene_events in scene_groups.items():
            recorded = await self.record_scene_events(
                db,
                novel_id,
                scene_id=scene_id,
                scene_index=scene_index,
                chapter_index=chapter_index,
                events=scene_events,
            )
            if result_refs is not None:
                result_refs.extend(
                    {"type": "memory_event", "id": item.id} for item in recorded
                )
        return MemoryDeltaIngestResult(count=len(delta_logs), delta_logs=delta_logs)

    @staticmethod
    def _delta_value(value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=False)

    @staticmethod
    def _delta_dimension(category: str) -> str:
        normalized = str(category or "").lower()
        if "relation" in normalized:
            return "relations"
        if "location" in normalized or "move" in normalized:
            return "locations"
        if "knowledge" in normalized or "reveal" in normalized:
            return "knowledge"
        return "entities"

    @classmethod
    def _event_dimension(cls, event: dict[str, Any]) -> str:
        event_type = str(event.get("event_type") or "")
        if event_type.startswith("relation_"):
            return "relations"
        if event_type == "entity_moved":
            return "locations"
        if event_type == "knowledge_changed":
            return "knowledge"
        return cls._delta_dimension(str(event.get("category") or event_type))

    async def count_deep_import_delta_logs_by_workflow(
        self,
        db: AsyncSession,
        novel_id: str,
        workflow_id: str,
    ) -> int:
        """Count auto-ingested deep import DeltaLogs for cleanup reporting."""
        nid = parse_uuid(novel_id, "novel_id")
        return await self._delta_log_repo.count_active_by_workflow(
            db,
            nid,
            workflow_id,
        )

    async def rollback_deep_import_delta_logs_by_workflow(
        self,
        db: AsyncSession,
        novel_id: str,
        workflow_id: str,
    ) -> int:
        """Mark workflow-owned import deltas as rolled back without erasing audit data."""
        nid = parse_uuid(novel_id, "novel_id")
        rolled_back_at = datetime.now(UTC).isoformat()
        count = 0
        cursor: uuid.UUID | None = None
        while True:
            page = await self._delta_log_repo.get_active_by_workflow_page_after(
                db,
                nid,
                workflow_id,
                after_id=cursor,
                limit=DELTA_ROLLBACK_BATCH_SIZE,
                for_update=True,
            )
            if not page:
                break
            for item in page:
                meta = dict(item.meta or {})
                meta.update(
                    {
                        "rolled_back": True,
                        "rolled_back_at": rolled_back_at,
                        "rollback_reason": "workflow_abandoned",
                    }
                )
                item.meta = meta
                db.add(item)
                count += 1
            cursor = page[-1].id
            await db.flush()
            if len(page) < DELTA_ROLLBACK_BATCH_SIZE:
                break
        return count

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
        没有任何快照/事件时返回 stage0 空状态，禁止当前 World 泄漏到历史。
        """
        nid = parse_uuid(novel_id)
        nearest = await self._snapshot_repo.get_nearest(db, nid, chapter_index)

        if nearest:
            state = dict(nearest.full_state)
            start_chapter = nearest.chapter_index + 1
            if start_chapter <= chapter_index:
                state, _ = await self._apply_events_in_range(
                    db,
                    nid,
                    start_chapter,
                    chapter_index,
                    state,
                )
        else:
            # 没有任何快照 — 检查是否有事件可重放
            state, _ = await self._apply_events_in_range(
                db,
                nid,
                1,
                chapter_index,
                self._empty_replay_state(),
            )

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
            event_count = await self._event_repo.count_by_chapter_range(
                db, nid, 1, previous_chapter
            )
            if event_count == 0:
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
        total = await self._event_repo.count_by_chapter_range(
            db, nid, from_chapter, to_chapter
        )
        items: list[MemoryEventResponse] = []
        cursor: tuple[int, int, uuid.UUID] | None = None
        while len(items) < total:
            remaining = total - len(items)
            page = await self._event_repo.get_by_chapter_range_page_after(
                db,
                nid,
                from_chapter,
                to_chapter,
                after=cursor,
                limit=min(MEMORY_EVENT_LIST_BATCH_SIZE, remaining),
            )
            if not page:
                break
            items.extend(MemoryEventResponse.model_validate(event) for event in page)
            last = page[-1]
            cursor = (last.chapter_index, last.sequence, last.id)
            if len(page) < MEMORY_EVENT_LIST_BATCH_SIZE:
                break
        return EventListResponse(items=items, total=total)

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
        (
            snapshot_count,
            latest_chapter,
            latest_current,
            stale_from,
        ) = await self._snapshot_repo.get_status_summary(db, nid)

        return MemoryStatusResponse(
            novel_id=novel_id,
            latest_chapter=latest_chapter if snapshot_count else None,
            latest_snapshot_chapter=latest_current,
            has_stale=stale_from is not None,
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

        只从已有事件确定性重放并重建稀疏章节快照；不读取当前 World。
        """
        nid = parse_uuid(novel_id)
        # Preserve snapshot history: rebuilt current snapshots are superseded,
        # not hard-deleted.  Snapshots before the correction point remain valid.
        await self._snapshot_repo.mark_stale_from(db, nid, from_chapter)
        max_chapter = await self._event_repo.get_max_chapter_in_range(
            db, nid, from_chapter, 999999
        )
        # 重建快照（每 K 章一个，加上最新章）
        final_chapter = max_chapter or from_chapter

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

    @staticmethod
    def _empty_replay_state() -> dict[str, Any]:
        return {
            "entities": {},
            "relations": [],
            "character_locations": {},
            "character_knowledge": [],
        }

    async def _apply_events_in_range(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        from_chapter: int,
        to_chapter: int,
        state: dict[str, Any],
    ) -> tuple[dict[str, Any], int]:
        replay_state = self._normalize_replay_state(state)
        cursor: tuple[int, int, uuid.UUID] | None = None
        events_seen = 0

        while True:
            page = await self._event_repo.get_by_chapter_range_page_after(
                db,
                novel_id,
                from_chapter,
                to_chapter,
                after=cursor,
                limit=MEMORY_REPLAY_EVENT_BATCH_SIZE,
            )
            if not page:
                break
            for event in page:
                self._apply_event_to_replay_state(replay_state, event)
            events_seen += len(page)
            last = page[-1]
            cursor = (last.chapter_index, last.sequence, last.id)
            if len(page) < MEMORY_REPLAY_EVENT_BATCH_SIZE:
                break

        return self._finalize_replay_state(replay_state), events_seen

    def _apply_events(self, state: dict[str, Any], events: list[Any]) -> dict[str, Any]:
        """应用事件序列到状态上"""
        replay_state = self._normalize_replay_state(state)

        for event in events:
            self._apply_event_to_replay_state(replay_state, event)

        return self._finalize_replay_state(replay_state)

    def _normalize_replay_state(self, state: dict[str, Any]) -> dict[str, Any]:
        entities = state.get("entities", {})
        if isinstance(entities, dict):
            entity_map = deepcopy(entities)
        else:
            entity_map = {
                e["id"]: deepcopy(e)
                for e in entities
                if isinstance(e, dict) and e.get("id") is not None
            }
        return {
            "entities": entity_map,
            "relations": deepcopy(state.get("relations", [])),
            "character_locations": deepcopy(state.get("character_locations", {})),
            "character_knowledge": deepcopy(state.get("character_knowledge", [])),
        }

    def _apply_event_to_replay_state(
        self,
        state: dict[str, Any],
        event: Any,
    ) -> None:
        etype = event.event_type
        after = deepcopy(event.snapshot_after or {})
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
            state["relations"] = [r for r in state["relations"] if r.get("id") != rel_id]
        elif etype == EventType.knowledge_changed:
            state["character_knowledge"].append(after)

    @staticmethod
    def _finalize_replay_state(state: dict[str, Any]) -> dict[str, Any]:
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
