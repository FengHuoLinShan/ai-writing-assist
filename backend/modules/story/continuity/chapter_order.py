"""Story-owned bindings and stale projections affected by Writing chapter order."""

from __future__ import annotations

import hashlib
import json
import uuid
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ConflictError, NotFoundError
from modules.story.continuity.models import (
    MemoryEvent,
    MemorySceneCheckpoint,
    MemorySceneSnapshot,
    MemorySnapshot,
    StoryChapterOrderReceipt,
)
from modules.story.outline_state.models import (
    ForeshadowingPlan,
    OutlineArc,
    PlotThread,
    RevealPlan,
    Scene,
    SceneChapterLink,
    SceneSpan,
    SceneSummaryCheckpoint,
)


class StoryChapterOrderService:
    """Remap exact Story chapter bindings and fence source-derived state."""

    async def preview(
        self,
        db: AsyncSession,
        novel_id: str,
        chapter_map: dict[int, int],
        source_versions: dict[int, list[dict[str, str]]],
    ) -> dict[str, Any]:
        state = await self._load_state(db, novel_id, chapter_map)
        return self._preview_from_state(chapter_map, source_versions, state)

    async def apply(
        self,
        db: AsyncSession,
        novel_id: str,
        receipt_id: str,
        chapter_map: dict[int, int],
        source_versions: dict[int, list[dict[str, str]]],
        expected_fingerprint: str,
    ) -> dict[str, Any]:
        nid = uuid.UUID(str(novel_id))
        operation_id = uuid.UUID(str(receipt_id))
        existing = await db.scalar(
            select(StoryChapterOrderReceipt).where(
                StoryChapterOrderReceipt.novel_id == nid,
                StoryChapterOrderReceipt.id == operation_id,
            )
        )
        if existing is not None:
            if existing.status == "applied":
                return {
                    "receipt_id": str(existing.id),
                    "status": "applied",
                    "replayed": True,
                    "story_fingerprint": existing.after_fingerprint,
                    "impact": existing.impact_json,
                }
            raise ConflictError("章节顺序预览已经恢复，不能再次执行")

        await self._lock(db, novel_id, chapter_map)
        state = await self._load_state(db, novel_id, chapter_map, for_update=True)
        preview = self._preview_from_state(chapter_map, source_versions, state)
        if preview["fingerprint"] != expected_fingerprint:
            raise ConflictError("Story 场景来源或绑定已变化，请重新预览")
        if preview["blockers"]:
            raise ConflictError("Story 存在无法可靠迁移的场景来源，请先处理预览中的冲突")

        manifest = self._capture_manifest(
            state, preview["impact"].get("plan_review_refs", [])
        )
        await self._remap_bindings(state, chapter_map, db)
        self._remap_plan_anchors(state, chapter_map)
        await self._invalidate_derived(state, db, novel_id, chapter_map)
        await db.flush()
        after = await self._load_state(db, novel_id, chapter_map)
        after_fingerprint = self._fingerprint(after)
        row = StoryChapterOrderReceipt(
            id=operation_id,
            novel_id=nid,
            status="applied",
            chapter_map_json={
                str(source): int(target) for source, target in chapter_map.items()
            },
            before_fingerprint=expected_fingerprint,
            after_fingerprint=after_fingerprint,
            impact_json=preview["impact"],
            manifest_json=manifest,
            created_at=datetime.now(UTC),
        )
        db.add(row)
        await db.flush()
        return {
            "receipt_id": str(operation_id),
            "status": "applied",
            "replayed": False,
            "story_fingerprint": after_fingerprint,
            "impact": preview["impact"],
        }

    async def restore(
        self,
        db: AsyncSession,
        novel_id: str,
        receipt_id: str,
    ) -> dict[str, Any]:
        nid = uuid.UUID(str(novel_id))
        operation_id = uuid.UUID(str(receipt_id))
        row = await db.scalar(
            select(StoryChapterOrderReceipt)
            .where(
                StoryChapterOrderReceipt.novel_id == nid,
                StoryChapterOrderReceipt.id == operation_id,
            )
            .with_for_update()
        )
        if row is None:
            raise NotFoundError("Story 章节顺序回执不存在")
        if row.status == "restored":
            return {
                "receipt_id": str(row.id),
                "status": "restored",
                "replayed": True,
                "story_fingerprint": row.after_fingerprint,
                "impact": row.impact_json,
            }

        chapter_map = {
            int(source): int(target) for source, target in row.chapter_map_json.items()
        }
        await self._lock(db, novel_id, chapter_map)
        state = await self._load_state(db, novel_id, chapter_map, for_update=True)
        current_fingerprint = self._fingerprint(state)
        if current_fingerprint != row.after_fingerprint:
            raise ConflictError(
                "Story 来源或计划在重排后已变化；为保护新内容，不能恢复旧绑定"
            )

        inverse = {target: source for source, target in chapter_map.items()}
        await self._remap_bindings(state, inverse, db)
        self._restore_manifest(state, row.manifest_json)
        await db.flush()
        restored_state = await self._load_state(db, novel_id, chapter_map)
        row.status = "restored"
        row.restored_at = datetime.now(UTC)
        row.after_fingerprint = self._fingerprint(restored_state)
        await db.flush()
        return {
            "receipt_id": str(row.id),
            "status": "restored",
            "replayed": False,
            "story_fingerprint": row.after_fingerprint,
            "impact": row.impact_json,
        }

    async def preview_restore(
        self,
        db: AsyncSession,
        novel_id: str,
        receipt_id: str,
    ) -> dict[str, Any]:
        nid = uuid.UUID(str(novel_id))
        operation_id = uuid.UUID(str(receipt_id))
        row = await db.scalar(
            select(StoryChapterOrderReceipt).where(
                StoryChapterOrderReceipt.novel_id == nid,
                StoryChapterOrderReceipt.id == operation_id,
            )
        )
        if row is None:
            raise NotFoundError("Story 章节顺序回执不存在")
        chapter_map = {
            int(source): int(target) for source, target in row.chapter_map_json.items()
        }
        state = await self._load_state(db, novel_id, chapter_map)
        current_fingerprint = self._fingerprint(state)
        blockers = []
        if row.status != "applied":
            blockers.append({"kind": "story_receipt_not_applied"})
        elif current_fingerprint != row.after_fingerprint:
            blockers.append({"kind": "story_source_changed"})
        return {
            "receipt_id": str(row.id),
            "status": row.status,
            "can_restore": not blockers,
            "story_fingerprint": current_fingerprint,
            "expected_story_fingerprint": row.after_fingerprint,
            "impact": row.impact_json or {},
            "blockers": blockers,
        }

    async def list_pending_plan_reviews(
        self, db: AsyncSession, novel_id: str
    ) -> list[dict[str, Any]]:
        nid = uuid.UUID(str(novel_id))
        receipts = await db.scalars(
            select(StoryChapterOrderReceipt)
            .where(
                StoryChapterOrderReceipt.novel_id == nid,
                StoryChapterOrderReceipt.status == "applied",
            )
            .order_by(StoryChapterOrderReceipt.created_at.desc())
        )
        pending: list[dict[str, Any]] = []
        for receipt in receipts:
            for ref in (receipt.impact_json or {}).get("plan_review_refs", []):
                if await self._plan_anchors_match(db, nid, ref):
                    pending.append(
                        {
                            "receipt_id": str(receipt.id),
                            "target_type": ref["target_type"],
                            "target_id": ref["target_id"],
                            "label": ref.get("label") or ref["target_type"],
                            "before": ref.get("before", {}),
                            "after": ref.get("after", {}),
                            "field_count": len(ref.get("after", {})),
                        }
                    )
        return pending

    async def _lock(
        self,
        db: AsyncSession,
        novel_id: str,
        chapter_map: dict[int, int],
    ) -> None:
        bind = db.get_bind()
        if bind is None or bind.dialect.name != "postgresql":
            return
        await db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"story_chapter_order:{novel_id}"},
        )
        for chapter_index in sorted(chapter_map):
            await db.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": f"memory_events:{novel_id}:{chapter_index}"},
            )

    async def _load_state(
        self,
        db: AsyncSession,
        novel_id: str,
        chapter_map: dict[int, int],
        *,
        for_update: bool = False,
    ) -> dict[str, Any]:
        nid = uuid.UUID(str(novel_id))
        changed = {
            int(key) for key, value in chapter_map.items() if int(key) != int(value)
        }
        minimum = min(changed) if changed else min(chapter_map, default=1)

        def locked(query):
            return query.with_for_update() if for_update else query

        scenes = list(
            (
                await db.scalars(
                    locked(
                        select(Scene)
                        .where(Scene.novel_id == nid)
                        .order_by(Scene.scene_index, Scene.id)
                    )
                )
            ).all()
        )
        preliminary_scene_ids = {
            scene.id for scene in scenes if self._scene_indices(scene) & changed
        }
        index_links = list(
            (
                await db.scalars(
                    locked(
                        select(SceneChapterLink).where(
                            SceneChapterLink.novel_id == nid,
                            SceneChapterLink.chapter_index.in_(changed or {-1}),
                        )
                    )
                )
            ).all()
        )
        index_spans = list(
            (
                await db.scalars(
                    locked(
                        select(SceneSpan).where(
                            SceneSpan.novel_id == nid,
                            SceneSpan.chapter_index.in_(changed or {-1}),
                        )
                    )
                )
            ).all()
        )
        scene_ids = (
            preliminary_scene_ids
            | {row.scene_id for row in index_links}
            | {row.scene_id for row in index_spans}
        )
        scene_by_id = {scene.id: scene for scene in scenes if scene.id in scene_ids}
        earliest_scene_index = min(
            (int(scene.scene_index) for scene in scene_by_id.values()),
            default=None,
        )
        timeline_scene_ids = set(scene_ids)
        if earliest_scene_index is not None:
            timeline_scene_ids.update(
                scene.id
                for scene in scenes
                if int(scene.scene_index) >= earliest_scene_index
            )
        links = list(index_links)
        spans = list(index_spans)
        if scene_ids:
            links.extend(
                row
                for row in (
                    await db.scalars(
                        locked(
                            select(SceneChapterLink).where(
                                SceneChapterLink.novel_id == nid,
                                SceneChapterLink.scene_id.in_(scene_ids),
                            )
                        )
                    )
                ).all()
                if row not in links
            )
            spans.extend(
                row
                for row in (
                    await db.scalars(
                        locked(
                            select(SceneSpan).where(
                                SceneSpan.novel_id == nid,
                                SceneSpan.scene_id.in_(scene_ids),
                            )
                        )
                    )
                ).all()
                if row not in spans
            )
        events_stmt = select(MemoryEvent).where(
            MemoryEvent.novel_id == nid,
            or_(
                MemoryEvent.chapter_index.in_(changed or {-1}),
                MemoryEvent.scene_id.in_(timeline_scene_ids or {uuid.UUID(int=0)}),
            ),
        )
        events = list((await db.scalars(locked(events_stmt))).all())
        memory_snapshots = list(
            (
                await db.scalars(
                    locked(
                        select(MemorySnapshot).where(
                            MemorySnapshot.novel_id == nid,
                            MemorySnapshot.chapter_index >= minimum,
                        )
                    )
                )
            ).all()
        )
        checkpoint_conditions = [
            MemorySceneCheckpoint.scene_id.in_(timeline_scene_ids or {uuid.UUID(int=0)})
        ]
        if earliest_scene_index is not None:
            checkpoint_conditions.append(
                MemorySceneCheckpoint.scene_index >= earliest_scene_index
            )
        checkpoints = list(
            (
                await db.scalars(
                    locked(
                        select(MemorySceneCheckpoint).where(
                            MemorySceneCheckpoint.novel_id == nid,
                            or_(*checkpoint_conditions),
                        )
                    )
                )
            ).all()
        )
        scene_snapshot_conditions = [MemorySceneSnapshot.is_latest.is_(True)]
        if earliest_scene_index is not None:
            scene_snapshot_conditions.append(
                MemorySceneSnapshot.scene_index >= earliest_scene_index
            )
        if timeline_scene_ids:
            scene_snapshot_conditions.append(
                MemorySceneSnapshot.scene_id.in_(timeline_scene_ids)
            )
        scene_snapshots = []
        if scene_snapshot_conditions:
            scene_snapshots = list(
                (
                    await db.scalars(
                        locked(
                            select(MemorySceneSnapshot).where(
                                MemorySceneSnapshot.novel_id == nid,
                                or_(*scene_snapshot_conditions),
                            )
                        )
                    )
                ).all()
            )
        summary_conditions = [SceneSummaryCheckpoint.through_chapter >= minimum]
        if timeline_scene_ids:
            summary_conditions.append(
                SceneSummaryCheckpoint.scene_id.in_(timeline_scene_ids)
            )
        summaries = list(
            (
                await db.scalars(
                    locked(
                        select(SceneSummaryCheckpoint).where(
                            SceneSummaryCheckpoint.novel_id == nid,
                            or_(*summary_conditions),
                        )
                    )
                )
            ).all()
        )
        threads = list(
            (
                await db.scalars(
                    locked(select(PlotThread).where(PlotThread.novel_id == nid))
                )
            ).all()
        )
        arcs = list(
            (
                await db.scalars(
                    locked(select(OutlineArc).where(OutlineArc.novel_id == nid))
                )
            ).all()
        )
        foreshadowing = list(
            (
                await db.scalars(
                    locked(
                        select(ForeshadowingPlan).where(ForeshadowingPlan.novel_id == nid)
                    )
                )
            ).all()
        )
        reveals = list(
            (
                await db.scalars(
                    locked(select(RevealPlan).where(RevealPlan.novel_id == nid))
                )
            ).all()
        )
        return {
            "scenes": list(scene_by_id.values()),
            "scene_links": links,
            "scene_spans": spans,
            "events": events,
            "memory_snapshots": memory_snapshots,
            "checkpoints": checkpoints,
            "scene_snapshots": scene_snapshots,
            "scene_summaries": summaries,
            "timeline_scene_ids": timeline_scene_ids,
            "threads": threads,
            "arcs": arcs,
            "foreshadowing": foreshadowing,
            "reveals": reveals,
            "changed_chapters": sorted(changed),
            "minimum_chapter": minimum,
        }

    def _preview_from_state(
        self,
        chapter_map: dict[int, int],
        source_versions: dict[int, list[dict[str, str]]],
        state: dict[str, Any],
    ) -> dict[str, Any]:
        conflicts: list[dict[str, Any]] = []
        source_pairs = {
            int(index): {
                (str(item.get("draft_id")), str(item.get("content_hash")))
                for item in versions
            }
            for index, versions in source_versions.items()
        }
        for span in state["scene_spans"]:
            if span.chapter_index not in chapter_map:
                continue
            if span.source_draft_id is not None or span.source_content_hash:
                pair = (
                    str(span.source_draft_id) if span.source_draft_id else "",
                    str(span.source_content_hash or ""),
                )
                if pair not in source_pairs.get(int(span.chapter_index), set()):
                    conflicts.append({"kind": "scene_span_source", "count": 1})
            elif span.mapping_status in {"exact", "reanchored"}:
                conflicts.append({"kind": "scene_span_source", "count": 1})

        for scene in state["scenes"]:
            chunks = scene.scene_chunks if isinstance(scene.scene_chunks, list) else []
            json_chapters: set[int] = set()
            for value in scene.chapter_ids or []:
                try:
                    json_chapters.add(int(value))
                except (TypeError, ValueError):
                    continue
            chunk_chapters = {
                index
                for chunk in chunks
                if isinstance(chunk, dict)
                if (index := self._chunk_chapter_index(chunk)) is not None
            }
            if chunk_chapters and json_chapters != chunk_chapters:
                conflicts.append(
                    {
                        "kind": "scene_chapter_projection_mismatch",
                        "scene_id": str(scene.id),
                        "title": scene.title or "未命名 Scene",
                        "chapter_ids": sorted(json_chapters),
                        "chunk_chapters": sorted(chunk_chapters),
                    }
                )
            linked_chapters = {
                int(row.chapter_index)
                for row in state["scene_links"]
                if row.scene_id == scene.id
            }
            expected_linked_chapters = json_chapters | chunk_chapters
            if linked_chapters != expected_linked_chapters:
                conflicts.append(
                    {
                        "kind": "scene_chapter_link_mismatch",
                        "scene_id": str(scene.id),
                        "title": scene.title or "未命名 Scene",
                        "stored_links": sorted(linked_chapters),
                        "scene_chapters": sorted(expected_linked_chapters),
                    }
                )
            for chunk in chunks:
                if not isinstance(chunk, dict):
                    continue
                raw_chapters = []
                for key in ("chapter_index", "chapter_id"):
                    if chunk.get(key) is not None:
                        try:
                            raw_chapters.append(int(chunk[key]))
                        except (TypeError, ValueError):
                            pass
                if len(set(raw_chapters)) > 1 and set(raw_chapters) & set(chapter_map):
                    conflicts.append({"kind": "scene_chunk_chapter_ref", "count": 1})
                chapter_index = self._chunk_chapter_index(chunk)
                draft_id = chunk.get("source_draft_id")
                content_hash = chunk.get("source_content_hash")
                precise = chunk.get("mapping_status") in {"exact", "reanchored"}
                if chapter_index not in chapter_map or not (
                    draft_id or content_hash or precise
                ):
                    continue
                pair = (str(draft_id or ""), str(content_hash or ""))
                if (
                    not draft_id
                    or not content_hash
                    or pair not in source_pairs.get(chapter_index, set())
                ):
                    conflicts.append({"kind": "scene_chunk_source", "count": 1})

        split_scenes = []
        for scene in state["scenes"]:
            sequences = self._scene_order_sequences(
                scene, state["scene_links"], state["scene_spans"]
            )
            for source_type, ordered in sequences:
                mapped = [chapter_map.get(index, index) for index in ordered]
                compact = [
                    value
                    for index, value in enumerate(mapped)
                    if index == 0 or value != mapped[index - 1]
                ]
                if source_type == "unordered_binding" and any(
                    index in chapter_map and chapter_map[index] != index
                    for index in ordered
                ):
                    conflicts.append(
                        {
                            "kind": "scene_multi_chapter_binding_order",
                            "scene_id": str(scene.id),
                            "title": scene.title or "未命名 Scene",
                            "before": ordered,
                            "after": compact,
                        }
                    )
                    continue
                if len(compact) > 1 and any(
                    left >= right for left, right in zip(compact, compact[1:])
                ):
                    split_scenes.append(
                        {
                            "kind": "scene_span_order"
                            if source_type == "scene_span"
                            else "scene_cross_chapter_order",
                            "scene_id": str(scene.id),
                            "title": scene.title or "未命名 Scene",
                            "before": ordered,
                            "after": compact,
                        }
                    )
        if split_scenes:
            conflicts.extend(split_scenes)

        plan_refs, plan_conflicts = self._plan_review_refs(
            state, chapter_map, source_versions
        )
        conflicts.extend(plan_conflicts)
        unanchored_events = sum(
            1
            for event in state["events"]
            if event.chapter_index in chapter_map and event.scene_id is None
        )
        impact = {
            "scene_count": len(state["scenes"]),
            "scene_binding_count": len(state["scene_links"]),
            "scene_span_count": len(state["scene_spans"]),
            "fact_event_count": len(state["events"]),
            "unanchored_fact_event_count": unanchored_events,
            "snapshot_count": len(state["memory_snapshots"]),
            "scene_checkpoint_count": len(state["checkpoints"]),
            "scene_snapshot_count": len(state["scene_snapshots"]),
            "scene_summary_count": len(state["scene_summaries"]),
            "plan_review_count": len(plan_refs),
            "plan_review_types": self._plan_review_type_counts(plan_refs),
            "plan_review_refs": plan_refs,
            "affected_scene_ids": sorted(
                str(value) for value in state["timeline_scene_ids"]
            ),
            "blockers": self._merge_blockers(conflicts),
        }
        return {
            "fingerprint": self._fingerprint(state),
            "impact": impact,
            "blockers": impact["blockers"],
        }

    @staticmethod
    def _merge_blockers(blockers: list[dict[str, Any]]) -> list[dict[str, Any]]:
        grouped: dict[str, dict[str, Any]] = {}
        for item in blockers:
            kind = str(item.get("kind") or "unknown")
            entry = grouped.setdefault(kind, {"count": 0, "examples": []})
            entry["count"] += int(item.get("count") or 1)
            if len(entry["examples"]) < 8:
                example = {
                    key: value
                    for key, value in item.items()
                    if key not in {"kind", "count"}
                }
                if example:
                    entry["examples"].append(example)
        labels = {
            "scene_span_source": "Scene 精确片段缺少匹配的正文版本来源",
            "scene_chunk_source": "Scene 章节片段来源与当前正文版本不一致",
            "scene_chunk_chapter_ref": "Scene 片段的章节锚点互相矛盾",
            "scene_chapter_projection_mismatch": "Scene 章节列表与正文片段指向不同章节",
            "scene_chapter_link_mismatch": "Scene 的章节查询索引与章节列表不一致",
            "scene_cross_chapter_order": "跨章 Scene 在新章节顺序中会倒置",
            "scene_span_order": "同一 Scene 的正文片段在新章节顺序中会倒置",
            "scene_multi_chapter_binding_order": "多章 Scene 缺少可确认的片段顺序",
            "plan_interval_inverted": "篇章或计划区间在新顺序中会倒置",
            "plan_interval_non_contiguous": "篇章或计划区间无法保持原有章节范围",
        }
        return [
            {
                "kind": kind,
                "count": entry["count"],
                "message": labels.get(kind, "来源需要先核对"),
                "examples": entry["examples"],
            }
            for kind, entry in sorted(grouped.items())
        ]

    @staticmethod
    def _scene_indices(scene: Scene) -> set[int]:
        found: set[int] = set()
        for value in scene.chapter_ids or []:
            try:
                found.add(int(value))
            except (TypeError, ValueError):
                continue
        for chunk in scene.scene_chunks or []:
            if isinstance(chunk, dict):
                value = StoryChapterOrderService._chunk_chapter_index(chunk)
                if value is not None:
                    found.add(value)
        return found

    @staticmethod
    def _chunk_chapter_index(chunk: dict[str, Any]) -> int | None:
        values = []
        for key in ("chapter_index", "chapter_id"):
            if chunk.get(key) is None:
                continue
            try:
                values.append(int(chunk[key]))
            except (TypeError, ValueError):
                continue
        if len(set(values)) > 1:
            return None
        return values[0] if values else None

    @staticmethod
    def _scene_order_sequences(
        scene: Scene,
        links: list[SceneChapterLink],
        spans: list[SceneSpan],
    ) -> list[tuple[str, list[int]]]:
        sequences: list[tuple[str, list[int]]] = []
        ordered_chunks: list[int] = []
        for chunk in scene.scene_chunks or []:
            if isinstance(chunk, dict):
                index = StoryChapterOrderService._chunk_chapter_index(chunk)
                if index is not None and (
                    not ordered_chunks or ordered_chunks[-1] != index
                ):
                    ordered_chunks.append(index)
        if ordered_chunks:
            sequences.append(("scene_chunk", ordered_chunks))

        ordered_chapters: list[int] = []
        for value in scene.chapter_ids or []:
            try:
                index = int(value)
            except (TypeError, ValueError):
                continue
            if not ordered_chapters or ordered_chapters[-1] != index:
                ordered_chapters.append(index)
        if ordered_chapters and not ordered_chunks:
            sequences.append(("scene_chapter_ids", ordered_chapters))

        spans_by_mode: dict[str, list[SceneSpan]] = {}
        for row in spans:
            if row.scene_id == scene.id:
                spans_by_mode.setdefault(str(row.content_mode), []).append(row)
        for rows in spans_by_mode.values():
            ordered_spans = []
            for row in sorted(rows, key=lambda item: (item.part_no, str(item.id))):
                index = int(row.chapter_index)
                if not ordered_spans or ordered_spans[-1] != index:
                    ordered_spans.append(index)
            if len(ordered_spans) > 1:
                sequences.append(("scene_span", ordered_spans))

        linked_chapters = sorted(
            {int(row.chapter_index) for row in links if row.scene_id == scene.id}
            | {int(row.chapter_index) for row in spans if row.scene_id == scene.id}
        )
        if (
            len(linked_chapters) > 1
            and not ordered_chunks
            and not ordered_chapters
            and not spans_by_mode
        ):
            sequences.append(("unordered_binding", linked_chapters))
        return sequences

    @staticmethod
    def _plan_review_refs(
        state: dict[str, Any],
        chapter_map: dict[int, int],
        source_versions: dict[int, list[dict[str, str]]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        refs: list[dict[str, Any]] = []
        conflicts: list[dict[str, Any]] = []

        def add_ref(kind: str, row: Any, label: str, before: dict[str, Any]):
            after = {
                field: _map_plan_anchor(field, value, chapter_map)
                for field, value in before.items()
            }
            if before != after or kind == "outline_arc":
                refs.append(
                    {
                        "target_type": kind,
                        "target_id": str(row.id),
                        "label": label,
                        "before": before,
                        "after": after,
                        "requires_revalidation": True,
                    }
                )

        for thread in state["threads"]:
            anchors = {
                key: getattr(thread, key)
                for key in ("start_chapter", "planned_payoff_chapter")
                if getattr(thread, key) is not None
                and int(getattr(thread, key)) in chapter_map
                and chapter_map[int(getattr(thread, key))] != int(getattr(thread, key))
            }
            if anchors:
                add_ref("plot_thread", thread, thread.name, anchors)
        for arc in state["arcs"]:
            start, end = arc.start_chapter, arc.end_chapter
            anchors = {
                key: getattr(arc, key)
                for key in ("start_chapter", "end_chapter")
                if getattr(arc, key) is not None
            }
            intersects = any(
                int(value) in chapter_map and chapter_map[int(value)] != int(value)
                for value in anchors.values()
            )
            if start is not None and end is not None and int(start) <= int(end):
                intersects = intersects or any(
                    int(source) in chapter_map
                    and int(start) <= int(source) <= int(end)
                    and int(source) != int(target)
                    for source, target in chapter_map.items()
                )
            if anchors:
                after = {
                    key: _map_plan_anchor(key, value, chapter_map)
                    for key, value in anchors.items()
                }
                if intersects:
                    refs.append(
                        {
                            "target_type": "outline_arc",
                            "target_id": str(arc.id),
                            "label": arc.title,
                            "before": anchors,
                            "after": after,
                            "requires_revalidation": True,
                        }
                    )
                    if start is not None and end is not None and int(start) <= int(end):
                        mapped_start = int(after["start_chapter"])
                        mapped_end = int(after["end_chapter"])
                        slots = sorted(int(index) for index in source_versions)
                        original_members = {
                            index for index in slots if int(start) <= index <= int(end)
                        }
                        mapped_members = {
                            chapter_map.get(index, index) for index in original_members
                        }
                        if mapped_start > mapped_end:
                            conflicts.append(
                                {
                                    "kind": "plan_interval_inverted",
                                    "target_type": "outline_arc",
                                    "target_id": str(arc.id),
                                    "label": arc.title,
                                    "before": {"start": int(start), "end": int(end)},
                                    "after": {"start": mapped_start, "end": mapped_end},
                                }
                            )
                        else:
                            actual_members = {
                                index
                                for index in slots
                                if mapped_start <= index <= mapped_end
                            }
                            if actual_members != mapped_members:
                                conflicts.append(
                                    {
                                        "kind": "plan_interval_non_contiguous",
                                        "target_type": "outline_arc",
                                        "target_id": str(arc.id),
                                        "label": arc.title,
                                        "before": {"start": int(start), "end": int(end)},
                                        "after": {
                                            "start": mapped_start,
                                            "end": mapped_end,
                                        },
                                    }
                                )
        for plan in state["foreshadowing"]:
            anchors: dict[str, Any] = {}
            for key in ("planned_seed_chapter", "planned_payoff_chapter"):
                value = getattr(plan, key)
                if (
                    value is not None
                    and int(value) in chapter_map
                    and chapter_map[int(value)] != int(value)
                ):
                    anchors[key] = value
            reinforce = deepcopy(plan.planned_reinforce_chapters or [])
            if any(
                _chapter_number(value) in chapter_map
                and chapter_map[_chapter_number(value)] != _chapter_number(value)
                for value in reinforce
            ):
                anchors["planned_reinforce_chapters"] = reinforce
            if anchors:
                add_ref("foreshadowing_plan", plan, plan.name, anchors)
        for plan in state["reveals"]:
            stages = deepcopy(plan.reveal_stages or [])
            if any(
                isinstance(stage, dict)
                and _chapter_number(stage.get("chapter_index")) in chapter_map
                and chapter_map[_chapter_number(stage.get("chapter_index"))]
                != _chapter_number(stage.get("chapter_index"))
                for stage in stages
            ):
                add_ref(
                    "reveal_plan",
                    plan,
                    str(plan.secret_summary)[:120],
                    {"reveal_stages": stages},
                )
        return refs, conflicts

    @staticmethod
    def _remap_plan_anchors(state: dict[str, Any], chapter_map: dict[int, int]) -> None:
        for thread in state["threads"]:
            for key in ("start_chapter", "planned_payoff_chapter"):
                value = getattr(thread, key)
                if value is not None:
                    setattr(thread, key, _map_plan_value(value, chapter_map))
        for arc in state["arcs"]:
            for key in ("start_chapter", "end_chapter"):
                value = getattr(arc, key)
                if value is not None:
                    setattr(arc, key, _map_plan_value(value, chapter_map))
        for plan in state["foreshadowing"]:
            for key in ("planned_seed_chapter", "planned_payoff_chapter"):
                value = getattr(plan, key)
                if value is not None:
                    setattr(plan, key, _map_plan_value(value, chapter_map))
            plan.planned_reinforce_chapters = [
                _map_plan_value(value, chapter_map)
                for value in (plan.planned_reinforce_chapters or [])
            ]
        for plan in state["reveals"]:
            stages = deepcopy(plan.reveal_stages or [])
            for stage in stages:
                if isinstance(stage, dict) and stage.get("chapter_index") is not None:
                    stage["chapter_index"] = _map_plan_value(
                        stage["chapter_index"], chapter_map
                    )
            plan.reveal_stages = stages

    @staticmethod
    def _plan_review_type_counts(refs: list[dict[str, Any]]) -> dict[str, int]:
        result: dict[str, int] = {}
        for ref in refs:
            kind = str(ref["target_type"])
            result[kind] = result.get(kind, 0) + 1
        return result

    def _fingerprint(self, state: dict[str, Any]) -> str:
        payload = {
            "scenes": sorted(
                (
                    str(scene.id),
                    int(scene.scene_index),
                    scene.title,
                    scene.status,
                    scene.narrative_tag,
                    scene.source,
                    scene.goal,
                    scene.core_conflict,
                    scene.emotional_beat,
                    scene.must_happen,
                    scene.must_not_happen,
                    scene.pov_character_id,
                    _digest_value(scene.structure_meta),
                    scene.chapter_ids or [],
                    scene.scene_chunks or [],
                    scene.updated_at.isoformat() if scene.updated_at else None,
                )
                for scene in state["scenes"]
            ),
            "links": sorted(
                (str(row.id), str(row.scene_id), int(row.chapter_index))
                for row in state["scene_links"]
            ),
            "spans": sorted(
                (
                    str(row.id),
                    str(row.scene_id),
                    int(row.chapter_index),
                    str(row.source_draft_id) if row.source_draft_id else None,
                    row.source_content_hash,
                    row.start_offset,
                    row.end_offset,
                    row.mapping_status,
                    row.status,
                )
                for row in state["scene_spans"]
            ),
            "events": sorted(
                (
                    str(row.id),
                    int(row.chapter_index),
                    str(row.scene_id) if row.scene_id else None,
                    row.scene_index,
                    row.scene_sequence,
                    int(row.sequence),
                    row.dimension,
                    row.event_type,
                    str(row.entity_id) if row.entity_id else None,
                    row.entity_type,
                    _digest_value(row.snapshot_before),
                    _digest_value(row.snapshot_after),
                    row.source,
                    bool(row.source_stale),
                    row.created_at.isoformat() if row.created_at else None,
                )
                for row in state["events"]
            ),
            "memory_snapshots": sorted(
                (
                    str(row.id),
                    int(row.chapter_index),
                    row.status,
                    row.events_until,
                    _digest_value(row.full_state),
                )
                for row in state["memory_snapshots"]
            ),
            "checkpoints": sorted(
                (
                    str(row.id),
                    str(row.scene_id),
                    int(row.scene_index),
                    int(row.stage_index),
                    row.dimension,
                    row.status,
                    row.source,
                    bool(row.confirmed),
                    bool(row.is_current),
                    row.gap_reason,
                    _digest_value(row.state_json),
                    _digest_value(row.evidence_refs),
                    row.display_summary,
                    row.source_hash,
                    _digest_value(row.basis_json),
                    int(row.retry_count),
                    row.decision_summary,
                    str(row.supersedes_id) if row.supersedes_id else None,
                )
                for row in state["checkpoints"]
            ),
            "scene_snapshots": sorted(
                (
                    str(row.id),
                    str(row.scene_id) if row.scene_id else None,
                    row.scene_index,
                    int(row.stage_index),
                    _digest_value(row.snapshot_reasons),
                    _digest_value(row.full_state),
                    row.source_hash,
                    bool(row.is_current),
                    bool(row.is_latest),
                )
                for row in state["scene_snapshots"]
            ),
            "scene_summaries": sorted(
                (
                    str(row.id),
                    row.status,
                    row.through_chapter,
                    row.through_offset,
                    row.content_mode,
                    row.based_on_hash,
                    _digest_value(row.source_refs),
                    hashlib.sha256((row.summary or "").encode("utf-8")).hexdigest(),
                    row.source,
                )
                for row in state["scene_summaries"]
            ),
            "plan_anchors": self._plan_anchor_fingerprint(state),
        }
        encoded = json.dumps(
            payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        )
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    @staticmethod
    def _capture_manifest(
        state: dict[str, Any], plan_review_refs: list[dict[str, Any]]
    ) -> dict[str, Any]:
        return {
            "memory_snapshots": [
                {"id": str(row.id), "status": row.status}
                for row in state["memory_snapshots"]
            ],
            "checkpoints": [
                {
                    "id": str(row.id),
                    "status": row.status,
                    "is_current": bool(row.is_current),
                    "gap_reason": row.gap_reason,
                }
                for row in state["checkpoints"]
            ],
            "scene_snapshots": [
                {
                    "id": str(row.id),
                    "is_current": bool(row.is_current),
                    "is_latest": bool(row.is_latest),
                }
                for row in state["scene_snapshots"]
            ],
            "scene_summaries": [
                {"id": str(row.id), "status": row.status}
                for row in state["scene_summaries"]
            ],
            "plan_anchors": [
                {
                    "target_type": ref["target_type"],
                    "target_id": ref["target_id"],
                    "fields": deepcopy(ref["before"]),
                }
                for ref in plan_review_refs
            ],
        }

    async def _remap_bindings(
        self,
        state: dict[str, Any],
        chapter_map: dict[int, int],
        db: AsyncSession,
    ) -> None:
        for scene in state["scenes"]:
            scene.chapter_ids = [
                _map_scalar(value, chapter_map) for value in (scene.chapter_ids or [])
            ]
            chunks = deepcopy(scene.scene_chunks or [])
            for chunk in chunks:
                if not isinstance(chunk, dict):
                    continue
                for key in ("chapter_index", "chapter_id"):
                    if key in chunk:
                        chunk[key] = _map_scalar(chunk[key], chapter_map)
            scene.scene_chunks = chunks

        # The link table is unique per (scene, chapter), so stage through
        # temporary negative values before applying a permutation.
        staged_links = []
        for row in state["scene_links"]:
            if row.chapter_index in chapter_map:
                if row.chapter_index < 1:
                    raise ConflictError("Story 章节链接中存在无效章节号，不能安全重排")
                row.chapter_index = -row.chapter_index
                staged_links.append(row)
        await db.flush()
        for row in staged_links:
            row.chapter_index = chapter_map[-row.chapter_index]
        for row in state["scene_spans"]:
            if row.chapter_index in chapter_map:
                row.chapter_index = chapter_map[row.chapter_index]
        await db.flush()

    async def _invalidate_derived(
        self,
        state: dict[str, Any],
        db: AsyncSession,
        novel_id: str,
        chapter_map: dict[int, int],
    ) -> None:
        if not state["changed_chapters"]:
            return
        for row in state["memory_snapshots"]:
            row.status = "stale"
        for row in state["checkpoints"]:
            if row.source == "system_generated" and not row.confirmed:
                row.is_current = False
                row.status = "superseded"
            else:
                row.status = "needs_revalidation"
                reason = "章节顺序变化，Scene 状态来源待重验"
                if reason not in (row.gap_reason or ""):
                    row.gap_reason = (
                        f"{row.gap_reason}；{reason}" if row.gap_reason else reason
                    )
        for row in state["scene_snapshots"]:
            row.is_current = False
            row.is_latest = False
        for row in state["scene_summaries"]:
            row.status = "needs_revalidation"
        await db.flush()

    @staticmethod
    def _restore_manifest(state: dict[str, Any], manifest: dict[str, Any]) -> None:
        snapshot_by_id = {str(row.id): row for row in state["memory_snapshots"]}
        for item in manifest.get("memory_snapshots", []):
            row = snapshot_by_id.get(str(item.get("id")))
            if row is not None:
                row.status = item["status"]
        checkpoint_by_id = {str(row.id): row for row in state["checkpoints"]}
        for item in manifest.get("checkpoints", []):
            row = checkpoint_by_id.get(str(item.get("id")))
            if row is not None:
                row.status = item["status"]
                row.is_current = bool(item["is_current"])
                row.gap_reason = item.get("gap_reason")
        scene_snapshot_by_id = {str(row.id): row for row in state["scene_snapshots"]}
        for item in manifest.get("scene_snapshots", []):
            row = scene_snapshot_by_id.get(str(item.get("id")))
            if row is not None:
                row.is_current = bool(item["is_current"])
                row.is_latest = bool(item["is_latest"])
        summary_by_id = {str(row.id): row for row in state["scene_summaries"]}
        for item in manifest.get("scene_summaries", []):
            row = summary_by_id.get(str(item.get("id")))
            if row is not None:
                row.status = item["status"]
        plan_rows = {
            "plot_thread": {str(row.id): row for row in state["threads"]},
            "outline_arc": {str(row.id): row for row in state["arcs"]},
            "foreshadowing_plan": {str(row.id): row for row in state["foreshadowing"]},
            "reveal_plan": {str(row.id): row for row in state["reveals"]},
        }
        for item in manifest.get("plan_anchors", []):
            row = plan_rows.get(item.get("target_type"), {}).get(
                str(item.get("target_id"))
            )
            if row is not None:
                for field, value in (item.get("fields") or {}).items():
                    setattr(row, field, deepcopy(value))

    async def _plan_anchors_match(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        ref: dict[str, Any],
    ) -> bool:
        models = {
            "plot_thread": PlotThread,
            "outline_arc": OutlineArc,
            "foreshadowing_plan": ForeshadowingPlan,
            "reveal_plan": RevealPlan,
        }
        model = models.get(ref.get("target_type"))
        if model is None:
            return False
        row = await db.scalar(
            select(model).where(
                model.novel_id == novel_id,
                model.id == uuid.UUID(str(ref["target_id"])),
            )
        )
        if row is None:
            return False
        return all(
            getattr(row, field, None) == value
            for field, value in (ref.get("after") or {}).items()
        )

    @staticmethod
    def _plan_anchor_fingerprint(state: dict[str, Any]) -> dict[str, list]:
        return {
            "plot_threads": sorted(
                (
                    str(row.id),
                    row.start_chapter,
                    row.planned_payoff_chapter,
                    row.updated_at.isoformat() if row.updated_at else None,
                )
                for row in state["threads"]
            ),
            "outline_arcs": sorted(
                (
                    str(row.id),
                    row.start_chapter,
                    row.end_chapter,
                    row.updated_at.isoformat() if row.updated_at else None,
                )
                for row in state["arcs"]
            ),
            "foreshadowing": sorted(
                (
                    str(row.id),
                    row.planned_seed_chapter,
                    row.planned_payoff_chapter,
                    _digest_value(row.planned_reinforce_chapters),
                    row.updated_at.isoformat() if row.updated_at else None,
                )
                for row in state["foreshadowing"]
            ),
            "reveals": sorted(
                (
                    str(row.id),
                    _digest_value(row.reveal_stages),
                    row.updated_at.isoformat() if row.updated_at else None,
                )
                for row in state["reveals"]
            ),
        }


def _chapter_number(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _map_plan_value(value: Any, chapter_map: dict[int, int]) -> Any:
    index = _chapter_number(value)
    if index is None or index not in chapter_map:
        return value
    target = chapter_map[index]
    return str(target) if isinstance(value, str) else target


def _map_plan_anchor(field: str, value: Any, chapter_map: dict[int, int]) -> Any:
    if field == "planned_reinforce_chapters" and isinstance(value, list):
        return [_map_plan_value(item, chapter_map) for item in value]
    if field == "reveal_stages" and isinstance(value, list):
        result = deepcopy(value)
        for stage in result:
            if isinstance(stage, dict) and stage.get("chapter_index") is not None:
                stage["chapter_index"] = _map_plan_value(
                    stage["chapter_index"], chapter_map
                )
        return result
    return _map_plan_value(value, chapter_map)


def _map_scalar(value: Any, chapter_map: dict[int, int]) -> Any:
    try:
        mapped = chapter_map.get(int(value))
    except (TypeError, ValueError):
        return value
    if mapped is None:
        return value
    return str(mapped) if isinstance(value, str) else mapped


def _digest_value(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


__all__ = ["StoryChapterOrderService"]
