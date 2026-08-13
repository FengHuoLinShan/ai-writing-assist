"""Scene-anchored deterministic memory projections and manual repair workflow."""

from __future__ import annotations

import hashlib
import json
import uuid
from copy import deepcopy
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ConflictError, NotFoundError, ValidationError
from modules.memory.contracts import SCENE_MEMORY_DIMENSIONS
from modules.memory.models import MemorySceneCheckpoint
from modules.memory.repositories import (
    EventRepository,
    SceneCheckpointRepository,
    SceneSnapshotRepository,
)
from modules.memory.schemas import (
    SceneCheckpointRepairRequest,
    SceneCheckpointRepairResponse,
    SceneCheckpointResponse,
    SceneCheckpointSetResponse,
)
from shared.utils import parse_uuid

_AUTO_RETRY_LIMIT = 2
_SPARSE_SNAPSHOT_INTERVAL = 10


class _CoverageGapError(Exception):
    def __init__(self, message: str, *, coverage: dict[str, int]) -> None:
        super().__init__(message)
        self.coverage = coverage


class SceneMemoryProjectionService:
    """Own the Scene timeline; never reads today's World as a historical fallback."""

    def __init__(
        self,
        event_repo: EventRepository | None = None,
        checkpoint_repo: SceneCheckpointRepository | None = None,
        snapshot_repo: SceneSnapshotRepository | None = None,
    ) -> None:
        self._events = event_repo or EventRepository()
        self._checkpoints = checkpoint_repo or SceneCheckpointRepository()
        self._snapshots = snapshot_repo or SceneSnapshotRepository()

    async def ensure_scene(
        self,
        db: AsyncSession,
        novel_id: str,
        scene_id: str,
    ) -> SceneCheckpointSetResponse:
        nid = parse_uuid(novel_id, "novel_id")
        scenes = await self._ordered_scenes(db, novel_id)
        target = next((item for item in scenes if str(item["id"]) == scene_id), None)
        if target is None:
            raise NotFoundError("Scene not found", code="scene_not_found")
        await self._reconcile_event_order(db, nid, scenes)
        allowed_scene_ids = self._scene_ids(scenes)
        await self._snapshots.ensure_stage0(
            db,
            nid,
            self._empty_full_state(),
            self._hash(self._empty_full_state()),
        )
        for position, scene in enumerate(scenes):
            if int(scene["scene_index"]) > int(target["scene_index"]):
                break
            previous_scene = scenes[position - 1] if position > 0 else None
            for dimension in SCENE_MEMORY_DIMENSIONS:
                checkpoint = await self._build_dimension(
                    db,
                    novel_id,
                    scene,
                    dimension,
                    previous_scene=previous_scene,
                    allowed_scene_ids=allowed_scene_ids,
                )
                retries = 0
                while (
                    checkpoint.status == "retry_pending" and retries < _AUTO_RETRY_LIMIT
                ):
                    checkpoint = await self._build_dimension(
                        db,
                        novel_id,
                        scene,
                        dimension,
                        previous_scene=previous_scene,
                        allowed_scene_ids=allowed_scene_ids,
                    )
                    retries += 1
            await self._capture_sparse_if_needed(db, nid, scenes, scene)
        return await self.get_scene(db, novel_id, scene_id, scenes=scenes)

    async def rebuild_from_scene(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        from_scene_id: str | None,
        dimensions: list[str],
    ) -> dict[str, Any]:
        nid = parse_uuid(novel_id, "novel_id")
        scenes = await self._ordered_scenes(db, novel_id)
        await self._reconcile_event_order(db, nid, scenes)
        allowed_scene_ids = self._scene_ids(scenes)
        start_index = 0
        if from_scene_id:
            source = next(
                (item for item in scenes if str(item["id"]) == from_scene_id), None
            )
            if source is None:
                raise NotFoundError("Scene not found", code="scene_not_found")
            start_index = int(source["scene_index"])
        await self._checkpoints.supersede_system_from(
            db,
            nid,
            start_index,
            dimensions,
            include_start=True,
        )
        await self._snapshots.supersede_from(
            db,
            nid,
            start_index,
            include_start=True,
        )
        rebuilt = 0
        for position, scene in enumerate(scenes):
            if int(scene["scene_index"]) < start_index:
                continue
            previous_scene = scenes[position - 1] if position > 0 else None
            for dimension in dimensions:
                await self._build_dimension(
                    db,
                    novel_id,
                    scene,
                    dimension,
                    previous_scene=previous_scene,
                    allowed_scene_ids=allowed_scene_ids,
                )
            await self._capture_sparse_if_needed(db, nid, scenes, scene)
            rebuilt += 1
        return {
            "from_scene_id": from_scene_id,
            "dimensions": dimensions,
            "rebuilt_scene_count": rebuilt,
        }

    async def get_scene(
        self,
        db: AsyncSession,
        novel_id: str,
        scene_id: str,
        *,
        scenes: list[dict[str, Any]] | None = None,
    ) -> SceneCheckpointSetResponse:
        nid = parse_uuid(novel_id, "novel_id")
        ordered = scenes or await self._ordered_scenes(db, novel_id)
        scene = next((item for item in ordered if str(item["id"]) == scene_id), None)
        if scene is None:
            raise NotFoundError("Scene not found", code="scene_not_found")
        rows = await self._checkpoints.list_current_for_scene(
            db, nid, parse_uuid(scene_id, "scene_id")
        )
        by_dimension = {item.dimension: item for item in rows}
        missing = [item for item in SCENE_MEMORY_DIMENSIONS if item not in by_dimension]
        statuses = {item.status for item in rows}
        if missing:
            coverage_status = "missing"
        elif "manual_required" in statuses:
            coverage_status = "manual_required"
        elif "retry_pending" in statuses:
            coverage_status = "retry_pending"
        elif statuses == {"ready"}:
            coverage_status = "ready"
        else:
            coverage_status = "gap"
        return SceneCheckpointSetResponse(
            novel_id=novel_id,
            scene_id=scene_id,
            scene_index=int(scene["scene_index"]),
            stage_index=int(scene["scene_index"]) + 1,
            scene_title=scene.get("title"),
            coverage_status=coverage_status,
            items=[SceneCheckpointResponse.model_validate(item) for item in rows],
            missing_dimensions=missing,
        )

    async def repair(
        self,
        db: AsyncSession,
        novel_id: str,
        request: SceneCheckpointRepairRequest,
    ) -> SceneCheckpointRepairResponse:
        nid = parse_uuid(novel_id, "novel_id")
        sid = parse_uuid(request.scene_id, "scene_id")
        scenes = await self._ordered_scenes(db, novel_id)
        await self._reconcile_event_order(db, nid, scenes)
        allowed_scene_ids = self._scene_ids(scenes)
        scene = next(
            (item for item in scenes if str(item["id"]) == request.scene_id), None
        )
        if scene is None:
            raise NotFoundError("Scene not found", code="scene_not_found")
        current = await self._checkpoints.lock_current(
            db,
            nid,
            sid,
            request.dimension,
        )
        if current is None:
            raise NotFoundError("Checkpoint not found", code="checkpoint_not_found")
        if str(current.id) != request.expected_checkpoint_id:
            raise ConflictError(
                "Checkpoint changed; reload the latest facts before deciding",
                code="checkpoint_version_conflict",
            )
        if current.source != "system_generated" or current.confirmed:
            raise ConflictError(
                "Manual or confirmed checkpoint is preserved",
                code="checkpoint_protected",
            )
        state = self._manual_state(current, request)
        summary = self._manual_display_summary(request, state)
        repaired = await self._checkpoints.create_manual_repair(
            db,
            current=current,
            state_json=state,
            evidence_refs=list(current.evidence_refs or []),
            display_summary=summary,
            source_hash=self._hash(
                {
                    "state": state,
                    "decision": request.decision,
                    "decision_summary": request.decision_summary,
                }
            ),
            decision_summary=request.decision_summary,
        )
        await self._checkpoints.supersede_system_from(
            db,
            nid,
            int(scene["scene_index"]),
            [request.dimension],
            include_start=False,
        )
        await self._snapshots.supersede_from(
            db,
            nid,
            int(scene["scene_index"]),
            include_start=True,
        )
        await self._capture_sparse_if_needed(db, nid, scenes, scene)
        rebuilt = 0
        for position, downstream in enumerate(scenes):
            if int(downstream["scene_index"]) <= int(scene["scene_index"]):
                continue
            await self._build_dimension(
                db,
                novel_id,
                downstream,
                request.dimension,
                previous_scene=scenes[position - 1] if position > 0 else None,
                allowed_scene_ids=allowed_scene_ids,
            )
            await self._capture_sparse_if_needed(db, nid, scenes, downstream)
            rebuilt += 1
        return SceneCheckpointRepairResponse(
            scene_id=request.scene_id,
            dimension=request.dimension,
            rebuilt_scene_count=rebuilt,
            checkpoint=SceneCheckpointResponse.model_validate(repaired),
        )

    async def _build_dimension(
        self,
        db: AsyncSession,
        novel_id: str,
        scene: dict[str, Any],
        dimension: str,
        *,
        previous_scene: dict[str, Any] | None,
        allowed_scene_ids: list[uuid.UUID],
    ) -> MemorySceneCheckpoint:
        nid = parse_uuid(novel_id, "novel_id")
        sid = parse_uuid(str(scene["id"]), "scene_id")
        scene_index = int(scene["scene_index"])
        current = await self._checkpoints.get_current(db, nid, sid, dimension)
        if current is not None and (
            current.source != "system_generated" or current.confirmed
        ):
            # Stage coordinates are derived from the live outline ordering.  Keep
            # the protected author decision, but do not let stale coordinates
            # make it appear before a Scene that now precedes it.
            if current.scene_index != scene_index:
                current.scene_index = scene_index
                current.stage_index = scene_index + 1
                await db.flush()
            return current
        previous = None
        previous_scene_index = None
        if previous_scene is not None:
            previous_scene_index = int(previous_scene["scene_index"])
            candidate = await self._checkpoints.get_current(
                db,
                nid,
                parse_uuid(str(previous_scene["id"]), "scene_id"),
                dimension,
            )
            if candidate is not None and candidate.status == "ready":
                previous = candidate
        try:
            state, refs = await self._project_dimension(
                db,
                novel_id,
                scene,
                dimension,
                previous,
                previous_scene_index=previous_scene_index,
                allowed_scene_ids=allowed_scene_ids,
            )
            source_hash = self._hash(
                {
                    "previous": previous.source_hash if previous else "stage0",
                    "state": state,
                    "refs": refs,
                }
            )
            if (
                current is not None
                and current.status == "ready"
                and current.scene_index == scene_index
                and current.source_hash == source_hash
            ):
                return current
            return await self._checkpoints.replace_system(
                db,
                novel_id=nid,
                scene_id=sid,
                scene_index=scene_index,
                dimension=dimension,
                values={
                    "status": "ready",
                    "confirmed": False,
                    "is_current": True,
                    "state_json": state,
                    "evidence_refs": refs,
                    "display_summary": self._display_summary(dimension, state),
                    "source_hash": source_hash,
                    "retry_count": 0,
                },
            )
        except _CoverageGapError as exc:
            retry_count = int(current.retry_count if current else 0) + 1
            status = (
                "manual_required" if retry_count > _AUTO_RETRY_LIMIT else "retry_pending"
            )
            base_state = deepcopy(
                previous.state_json if previous else self._empty_dimension(dimension)
            )
            base_state.setdefault("_coverage", {}).update(exc.coverage)
            return await self._checkpoints.replace_system(
                db,
                novel_id=nid,
                scene_id=sid,
                scene_index=scene_index,
                dimension=dimension,
                values={
                    "status": status,
                    "confirmed": False,
                    "is_current": True,
                    "state_json": base_state,
                    "evidence_refs": list(previous.evidence_refs or [])
                    if previous
                    else [],
                    "display_summary": self._display_summary(dimension, base_state),
                    "source_hash": self._hash(
                        {"gap": str(exc), "retry_count": retry_count}
                    ),
                    "gap_reason": str(exc),
                    "retry_count": retry_count,
                },
            )

    async def _project_dimension(
        self,
        db: AsyncSession,
        novel_id: str,
        scene: dict[str, Any],
        dimension: str,
        previous: MemorySceneCheckpoint | None,
        *,
        previous_scene_index: int | None,
        allowed_scene_ids: list[uuid.UUID],
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        scene_index = int(scene["scene_index"])
        after_scene_index = previous_scene_index if previous else None
        state = deepcopy(
            previous.state_json if previous else self._empty_dimension(dimension)
        )
        refs: list[dict[str, Any]] = []
        max_chapter = max(self._chapter_indices(scene) or [0])
        unanchored = await self._events.count_unanchored_through_chapter(
            db, parse_uuid(novel_id, "novel_id"), max_chapter
        )
        confirmed_coverage = (
            previous.state_json.get("_coverage_confirmed") or {} if previous else {}
        )
        covered_unanchored = int(
            confirmed_coverage.get("unanchored_memory_event_count", 0)
        )
        if unanchored > covered_unanchored:
            missing_count = unanchored - covered_unanchored
            raise _CoverageGapError(
                f"{missing_count} 条记忆事件只有章节锚点，无法确定所属 Scene",
                coverage={"unanchored_memory_event_count": unanchored},
            )
        events = await self._events.get_through_scene(
            db,
            parse_uuid(novel_id, "novel_id"),
            scene_index,
            dimension=dimension,
            after_scene_index=after_scene_index,
            allowed_scene_ids=allowed_scene_ids,
        )
        for event in events:
            self._apply_event(state, dimension, event)
            refs.append(
                {
                    "type": "memory_event",
                    "id": str(event.id),
                    "label": self._event_label(event),
                }
            )
        return state, refs

    async def _capture_sparse_if_needed(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        scenes: list[dict[str, Any]],
        scene: dict[str, Any],
    ) -> None:
        scene_index = int(scene["scene_index"])
        reasons: list[str] = []
        if (scene_index + 1) % _SPARSE_SNAPSHOT_INTERVAL == 0:
            reasons.append("periodic")
        position = next(i for i, item in enumerate(scenes) if item["id"] == scene["id"])
        next_scene = scenes[position + 1] if position + 1 < len(scenes) else None
        current_chapters = self._chapter_indices(scene)
        next_chapters = self._chapter_indices(next_scene) if next_scene else []
        if current_chapters and (
            not next_chapters or max(current_chapters) < min(next_chapters)
        ):
            reasons.append("chapter_end")
        is_latest = position == len(scenes) - 1
        if is_latest:
            reasons.append("latest")
        if not reasons:
            return
        rows = await self._checkpoints.list_current_for_scene(
            db, novel_id, parse_uuid(str(scene["id"]), "scene_id")
        )
        by_dimension = {item.dimension: item for item in rows}
        if any(
            dimension not in by_dimension or by_dimension[dimension].status != "ready"
            for dimension in SCENE_MEMORY_DIMENSIONS
        ):
            return
        full_state = {
            dimension: deepcopy(by_dimension[dimension].state_json)
            for dimension in SCENE_MEMORY_DIMENSIONS
        }
        await self._snapshots.replace_for_scene(
            db,
            novel_id=novel_id,
            scene_id=parse_uuid(str(scene["id"]), "scene_id"),
            scene_index=scene_index,
            reasons=list(dict.fromkeys(reasons)),
            full_state=full_state,
            source_hash=self._hash(full_state),
            is_latest=is_latest,
        )

    @staticmethod
    def _apply_event(state: dict[str, Any], dimension: str, event: Any) -> None:
        after = deepcopy(event.snapshot_after or {})
        entity_id = str(event.entity_id) if event.entity_id else None
        event_type = str(event.event_type)
        if dimension == "entities":
            entities = state.setdefault("entities", {})
            if event_type == "entity_removed" and entity_id:
                entities.pop(entity_id, None)
            elif event_type in {"entity_created", "entity_updated"} and entity_id:
                entities.setdefault(entity_id, {}).update(after)
            else:
                state.setdefault("changes", []).append(after)
        elif dimension == "relations":
            relations = state.setdefault("relations", [])
            if event_type == "relation_ended":
                relation_id = after.get("relation_id") or after.get("id")
                state["relations"] = [
                    item for item in relations if item.get("id") != relation_id
                ]
            elif event_type == "relation_established":
                relations.append(after)
            else:
                state.setdefault("changes", []).append(after)
        elif dimension == "locations":
            if event_type == "entity_moved" and entity_id:
                state.setdefault("character_locations", {})[entity_id] = after
            else:
                state.setdefault("changes", []).append(after)
        elif dimension == "knowledge":
            knowledge = state.setdefault("character_knowledge", [])
            knowledge_id = after.get("id")
            if knowledge_id:
                knowledge[:] = [
                    item for item in knowledge if item.get("id") != knowledge_id
                ]
            knowledge.append(after)

    @staticmethod
    def _manual_state(
        current: MemorySceneCheckpoint,
        request: SceneCheckpointRepairRequest,
    ) -> dict[str, Any]:
        current_state = deepcopy(current.state_json or {})
        confirmed_coverage = dict(current_state.get("_coverage_confirmed") or {})
        for key, value in (current_state.get("_coverage") or {}).items():
            confirmed_coverage[key] = max(
                int(confirmed_coverage.get(key, 0) or 0),
                int(value or 0),
            )
        if request.decision == "keep_current":
            state = current_state
            if confirmed_coverage:
                state["_coverage_confirmed"] = confirmed_coverage
            return state
        if request.decision == "confirm_empty":
            state = SceneMemoryProjectionService._empty_dimension(current.dimension)
            if confirmed_coverage:
                state["_coverage_confirmed"] = confirmed_coverage
            return state
        if not (request.replacement_summary or "").strip():
            raise ValidationError("请填写正确内容", code="replacement_summary_required")
        state = SceneMemoryProjectionService._empty_dimension(current.dimension)
        if confirmed_coverage:
            state["_coverage_confirmed"] = confirmed_coverage
        state["manual_summary"] = request.replacement_summary.strip()
        return state

    @staticmethod
    def _manual_display_summary(
        request: SceneCheckpointRepairRequest, state: dict[str, Any]
    ) -> str:
        if request.decision == "keep_current":
            return "已人工确认保留当前事实"
        if request.decision == "confirm_empty":
            return "已人工确认此阶段没有该维度事实"
        return (
            request.replacement_summary
            or SceneMemoryProjectionService._display_summary(request.dimension, state)
        )

    @staticmethod
    def _display_summary(dimension: str, state: dict[str, Any]) -> str:
        if state.get("manual_summary"):
            return str(state["manual_summary"])
        key = {
            "entities": "entities",
            "relations": "relations",
            "locations": "character_locations",
            "knowledge": "character_knowledge",
        }[dimension]
        count = len(state.get(key) or {})
        changes = len(state.get("changes") or [])
        labels = {
            "entities": "人物与对象",
            "relations": "关系",
            "locations": "人物位置",
            "knowledge": "知识边界",
        }
        suffix = f"，另有 {changes} 条变更" if changes else ""
        return f"{labels[dimension]} {count} 条{suffix}"

    @staticmethod
    def _event_label(event: Any) -> str:
        after = event.snapshot_after or {}
        return str(
            after.get("summary")
            or after.get("new_value")
            or after.get("field_path")
            or event.event_type
        )[:240]

    @staticmethod
    def _chapter_indices(scene: dict[str, Any] | None) -> list[int]:
        if not scene:
            return []
        values: set[int] = set()
        for raw in scene.get("chapter_ids") or []:
            try:
                values.add(int(raw))
            except (TypeError, ValueError):
                continue
        for chunk in scene.get("scene_chunks") or []:
            if not isinstance(chunk, dict):
                continue
            raw = chunk.get("chapter_index") or chunk.get("chapter_id")
            try:
                values.add(int(raw))
            except (TypeError, ValueError):
                continue
        return sorted(values)

    @staticmethod
    async def _ordered_scenes(db: AsyncSession, novel_id: str) -> list[dict[str, Any]]:
        from modules.outline.facade import get_scenes_by_novel

        scenes = await get_scenes_by_novel(
            db,
            novel_id,
            status_filter=["canonical", "draft"],
        )
        return sorted(
            scenes, key=lambda item: (int(item["scene_index"]), str(item["id"]))
        )

    @staticmethod
    def _scene_ids(scenes: list[dict[str, Any]]) -> list[uuid.UUID]:
        return [parse_uuid(str(scene["id"]), "scene_id") for scene in scenes]

    async def _reconcile_event_order(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        scenes: list[dict[str, Any]],
    ) -> None:
        positions = {
            parse_uuid(str(scene["id"]), "scene_id"): int(scene["scene_index"])
            for scene in scenes
        }
        earliest = await self._events.align_scene_indices(db, novel_id, positions)
        if earliest is None:
            return
        await self._checkpoints.supersede_system_from(
            db,
            novel_id,
            earliest,
            ["entities", "relations", "locations", "knowledge"],
            include_start=True,
        )
        await self._snapshots.supersede_from(
            db,
            novel_id,
            earliest,
            include_start=True,
        )

    @staticmethod
    def _empty_dimension(dimension: str) -> dict[str, Any]:
        return {
            "entities": {"entities": {}, "changes": []},
            "relations": {"relations": [], "changes": []},
            "locations": {"character_locations": {}, "changes": []},
            "knowledge": {"character_knowledge": [], "changes": []},
        }[dimension]

    @staticmethod
    def _empty_full_state() -> dict[str, Any]:
        return {
            dimension: SceneMemoryProjectionService._empty_dimension(dimension)
            for dimension in SCENE_MEMORY_DIMENSIONS
        }

    @staticmethod
    def _hash(value: Any) -> str:
        payload = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
