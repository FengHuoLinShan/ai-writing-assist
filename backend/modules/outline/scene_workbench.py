from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.outline.models import Scene
from modules.outline.repositories import SceneRepository
from modules.outline.schemas import (
    SceneCreate,
    SceneHealthSummary,
    SceneImpactPreview,
    SceneMappingUpdate,
    SceneMergeRequest,
    SceneResponse,
    SceneSplitRequest,
    SceneUpdate,
    SceneWorkbenchItem,
    SceneWorkbenchResponse,
)
from modules.writing.facade import list_chapter_indices
from shared.utils import parse_uuid

HEALTH_DEFS = {
    "unreviewed": "未复核",
    "unassigned": "未关联章节",
    "missing_setup": "缺设定",
    "needs_organize": "待整理",
}


class SceneWorkbenchService:
    def __init__(self) -> None:
        self.repo = SceneRepository()

    async def get_workbench(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        selected_scene_id: str | None = None,
    ) -> SceneWorkbenchResponse:
        nid = parse_uuid(novel_id, "novel_id")
        scenes = await self.repo.get_by_novel_ordered(db, nid)
        chapter_indices = await list_chapter_indices(db, novel_id)
        unassigned_chapters = self._unassigned_chapters(chapter_indices, scenes)

        items = [
            SceneWorkbenchItem(
                scene=SceneResponse.model_validate(scene),
                health=self._scene_health(scene),
                chapter_range=self._chapter_range(scene.chapter_ids or []),
                summary=scene.goal or scene.core_conflict or scene.emotional_beat,
            )
            for scene in scenes
        ]

        counts = {key: 0 for key in HEALTH_DEFS}
        for item in items:
            for key in item.health:
                counts[key] += 1
        counts["unassigned"] += len(unassigned_chapters)

        return SceneWorkbenchResponse(
            health={
                key: SceneHealthSummary(key=key, label=label, count=counts[key])
                for key, label in HEALTH_DEFS.items()
            },
            items=items,
            unassigned_chapters=unassigned_chapters,
            selected_scene_id=selected_scene_id,
        )

    async def update_mapping(
        self,
        db: AsyncSession,
        novel_id: str,
        scene_id: str,
        data: SceneMappingUpdate,
    ) -> SceneResponse:
        scene = await self._get_scene_in_novel(db, novel_id, scene_id)
        meta = dict(scene.structure_meta or {})
        if data.structure_meta is not None:
            meta.update(data.structure_meta)
        update_payload: dict[str, Any] = {"structure_meta": meta}
        if data.chapter_ids is not None:
            update_payload["chapter_ids"] = data.chapter_ids
        if data.scene_chunks is not None:
            update_payload["scene_chunks"] = data.scene_chunks
        if data.status is not None:
            update_payload["status"] = data.status
        updated = await self.repo.update(
            db,
            scene.id,
            SceneUpdate(**update_payload),
        )
        if updated is None:
            raise LookupError("Scene not found")
        return SceneResponse.model_validate(updated)

    async def preview_merge(
        self,
        db: AsyncSession,
        novel_id: str,
        data: SceneMergeRequest,
    ) -> SceneImpactPreview:
        target, sources = await self._load_merge_scenes(db, novel_id, data)
        merged_chapters = self._merge_chapter_ids(
            target.chapter_ids or [],
            *[source.chapter_ids or [] for source in sources],
        )
        field_changes = self._merge_field_changes(target, sources)
        before = {
            str(target.id): target.chapter_ids or [],
            **{str(source.id): source.chapter_ids or [] for source in sources},
        }
        after = {
            str(target.id): merged_chapters,
            **{str(source.id): [] for source in sources},
        }
        start, end = self._range_from_chapters(merged_chapters)
        return SceneImpactPreview(
            operation="merge",
            chapter_mapping_change={"before": before, "after": after},
            field_changes=field_changes,
            related_threads=await self._related_thread_summary(db, novel_id, start, end),
            related_foreshadowing=await self._related_foreshadowing_summary(
                db, novel_id, start, end
            ),
            related_reveals=await self._related_reveal_summary(db, novel_id, start, end),
            map_summary_impact={
                "message": (
                    "目标 Scene 将承接来源 Scene 的章节映射；"
                    "地图摘要将在写作页重新读取。"
                )
            },
            warnings=["关联资产仅提示，不会自动阻断合并。"],
            scene=SceneResponse.model_validate(target),
        )

    async def merge(
        self,
        db: AsyncSession,
        novel_id: str,
        data: SceneMergeRequest,
    ) -> SceneWorkbenchItem:
        if not data.confirmed:
            raise PermissionError("merge requires confirmed=true")
        target, sources = await self._load_merge_scenes(db, novel_id, data)
        merged_chapters = self._merge_chapter_ids(
            target.chapter_ids or [],
            *[source.chapter_ids or [] for source in sources],
        )
        merged_chunks = self._merge_chunks(
            target.scene_chunks or [],
            *[source.scene_chunks or [] for source in sources],
        )
        field_payload = {
            field: getattr(target, field) or self._first_non_empty(sources, field)
            for field in (
                "goal",
                "core_conflict",
                "emotional_beat",
                "must_happen",
                "must_not_happen",
                "pov_character_id",
            )
        }
        target_meta = dict(target.structure_meta or {})
        target_meta["merged_from_scene_ids"] = [str(source.id) for source in sources]
        updated_target = await self.repo.update(
            db,
            target.id,
            SceneUpdate(
                chapter_ids=merged_chapters,
                scene_chunks=merged_chunks,
                structure_meta=target_meta,
                **field_payload,
            ),
        )
        if updated_target is None:
            raise LookupError("Target Scene not found")

        for source in sources:
            source_meta = dict(source.structure_meta or {})
            source_meta["merged_into_scene_id"] = str(target.id)
            await self.repo.update(
                db,
                source.id,
                SceneUpdate(
                    chapter_ids=[],
                    scene_chunks=[],
                    status="deprecated",
                    structure_meta=source_meta,
                ),
            )
        await db.flush()

        return SceneWorkbenchItem(
            scene=SceneResponse.model_validate(updated_target),
            health=self._scene_health(updated_target),
            chapter_range=self._chapter_range(updated_target.chapter_ids or []),
            summary=updated_target.goal
            or updated_target.core_conflict
            or updated_target.emotional_beat,
        )

    async def preview_split(
        self,
        db: AsyncSession,
        novel_id: str,
        data: SceneSplitRequest,
    ) -> SceneImpactPreview:
        source = await self._get_scene_in_novel(db, novel_id, data.source_scene_id)
        keep, move = self._split_chapter_ids(
            source.chapter_ids or [],
            data.split_chapter_index,
        )
        keep_chunks, move_chunks = self._split_chunks(
            source.scene_chunks or [],
            data.split_chapter_index,
            data.split_pos,
        )
        new_scene = self._new_split_scene_payload(source, data, move, move_chunks)
        start, end = self._range_from_chapters(source.chapter_ids or [])
        return SceneImpactPreview(
            operation="split",
            chapter_mapping_change={
                "before": {str(source.id): source.chapter_ids or []},
                "after": {str(source.id): keep},
            },
            field_changes={
                "source_scene": {
                    "chapter_ids": {
                        "before": source.chapter_ids or [],
                        "after": keep,
                    }
                },
                "new_scene": {"chapter_ids": move, "status": new_scene["status"]},
            },
            related_threads=await self._related_thread_summary(db, novel_id, start, end),
            related_foreshadowing=await self._related_foreshadowing_summary(
                db, novel_id, start, end
            ),
            related_reveals=await self._related_reveal_summary(db, novel_id, start, end),
            map_summary_impact={
                "message": "拆分后两个 Scene 的地图摘要将在写作页按新映射重新读取。"
            },
            warnings=["拆分不会修改正文内容。"],
            scene=SceneResponse.model_validate(source),
            new_scene=new_scene,
        )

    async def split(
        self,
        db: AsyncSession,
        novel_id: str,
        data: SceneSplitRequest,
    ) -> SceneWorkbenchItem:
        if not data.confirmed:
            raise PermissionError("split requires confirmed=true")
        source = await self._get_scene_in_novel(db, novel_id, data.source_scene_id)
        keep, move = self._split_chapter_ids(
            source.chapter_ids or [],
            data.split_chapter_index,
        )
        keep_chunks, move_chunks = self._split_chunks(
            source.scene_chunks or [],
            data.split_chapter_index,
            data.split_pos,
        )
        source_meta = dict(source.structure_meta or {})
        source_meta["split_at_chapter_index"] = data.split_chapter_index
        updated_source = await self.repo.update(
            db,
            source.id,
            SceneUpdate(
                chapter_ids=keep,
                scene_chunks=keep_chunks,
                structure_meta=source_meta,
            ),
        )
        if updated_source is None:
            raise LookupError("Source Scene not found")

        new_payload = self._new_split_scene_payload(source, data, move, move_chunks)
        new_scene = await self.repo.create(
            db,
            parse_uuid(novel_id, "novel_id"),
            SceneCreate(**new_payload),
        )
        await self._shift_later_scenes(db, new_scene)
        await db.flush()

        response = SceneResponse.model_validate(updated_source)
        item = SceneWorkbenchItem(
            scene=response,
            new_scene=SceneResponse.model_validate(new_scene),
            health=self._scene_health(updated_source),
            chapter_range=self._chapter_range(updated_source.chapter_ids or []),
            summary=updated_source.goal
            or updated_source.core_conflict
            or updated_source.emotional_beat,
        )
        return item

    async def _get_scene_in_novel(
        self,
        db: AsyncSession,
        novel_id: str,
        scene_id: str,
    ) -> Scene:
        sid = parse_uuid(scene_id, "scene_id")
        nid = parse_uuid(novel_id, "novel_id")
        scene = await self.repo.get(db, sid)
        if scene is None or scene.novel_id != nid:
            raise LookupError("Scene not found")
        return scene

    async def _load_merge_scenes(
        self,
        db: AsyncSession,
        novel_id: str,
        data: SceneMergeRequest,
    ) -> tuple[Scene, list[Scene]]:
        target = await self._get_scene_in_novel(db, novel_id, data.target_scene_id)
        sources = [
            await self._get_scene_in_novel(db, novel_id, sid)
            for sid in data.source_scene_ids
        ]
        if any(source.id == target.id for source in sources):
            raise ValueError("source_scene_ids cannot include target_scene_id")
        return target, sources

    def _scene_health(self, scene: Scene) -> list[str]:
        health: list[str] = []
        meta = scene.structure_meta or {}
        if (
            scene.source in {"deep_import", "ai_generated"}
            and scene.status in {"draft", "candidate"}
            and not meta.get("reviewed_at")
        ):
            health.append("unreviewed")
        chapter_ids = scene.chapter_ids or []
        if not chapter_ids:
            health.append("unassigned")
        if any(
            not getattr(scene, field)
            for field in ("goal", "core_conflict", "must_happen", "must_not_happen")
        ):
            health.append("missing_setup")
        if self._needs_organize(scene):
            health.append("needs_organize")
        return health

    def _needs_organize(self, scene: Scene) -> bool:
        meta = scene.structure_meta or {}
        if meta.get("needs_organize"):
            return True
        chapter_ids = scene.chapter_ids or []
        if len(chapter_ids) != len(set(chapter_ids)):
            return True
        chunk_chapters = {
            str(chunk.get("chapter_id") or chunk.get("chapter_index"))
            for chunk in scene.scene_chunks or []
            if chunk.get("chapter_id") is not None
            or chunk.get("chapter_index") is not None
        }
        return bool(chunk_chapters and set(chapter_ids) != chunk_chapters)

    def _unassigned_chapters(
        self,
        chapter_indices: list[int],
        scenes: list[Scene],
    ) -> list[int]:
        assigned = {
            int(chapter_id)
            for scene in scenes
            for chapter_id in scene.chapter_ids or []
            if str(chapter_id).isdigit()
        }
        return [idx for idx in chapter_indices if idx not in assigned]

    def _chapter_range(self, chapter_ids: list[str]) -> str:
        nums = sorted(int(cid) for cid in chapter_ids if str(cid).isdigit())
        if not nums:
            return "未关联章节"
        if len(nums) == 1:
            return f"第 {nums[0]} 章"
        return f"第 {nums[0]}-{nums[-1]} 章"

    def _merge_chapter_ids(self, *chapter_groups: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for group in chapter_groups:
            for chapter_id in group:
                cid = str(chapter_id)
                if cid not in seen:
                    seen.add(cid)
                    result.append(cid)
        return sorted(result, key=self._chapter_sort_key)

    def _merge_chunks(self, *chunk_groups: list[dict]) -> list[dict]:
        chunks = [dict(chunk) for group in chunk_groups for chunk in group]
        return sorted(
            chunks,
            key=lambda chunk: self._chapter_sort_key(
                str(chunk.get("chapter_index") or chunk.get("chapter_id") or "0")
            ),
        )

    def _chapter_sort_key(self, value: str) -> tuple[int, str]:
        return (int(value), value) if str(value).isdigit() else (0, str(value))

    def _merge_field_changes(
        self,
        target: Scene,
        sources: list[Scene],
    ) -> dict[str, dict[str, Any]]:
        changes: dict[str, dict[str, Any]] = {}
        for field in (
            "goal",
            "core_conflict",
            "emotional_beat",
            "must_happen",
            "must_not_happen",
            "pov_character_id",
        ):
            before = getattr(target, field)
            inherited = before or self._first_non_empty(sources, field)
            if inherited != before:
                changes[field] = {"before": before, "after": inherited}
        return changes

    def _first_non_empty(self, scenes: list[Scene], field: str) -> Any:
        for scene in scenes:
            value = getattr(scene, field)
            if value:
                return value
        return None

    def _split_chapter_ids(
        self,
        chapter_ids: list[str],
        split_chapter_index: int,
    ) -> tuple[list[str], list[str]]:
        keep: list[str] = []
        move: list[str] = []
        for chapter_id in chapter_ids:
            if str(chapter_id).isdigit() and int(chapter_id) >= split_chapter_index:
                move.append(str(chapter_id))
            else:
                keep.append(str(chapter_id))
        if not keep or not move:
            raise ValueError("split_chapter_index must split existing chapter_ids")
        return keep, move

    def _split_chunks(
        self,
        chunks: list[dict],
        split_chapter_index: int,
        split_pos: int | None,
    ) -> tuple[list[dict], list[dict]]:
        if not chunks:
            return [], []
        keep: list[dict] = []
        move: list[dict] = []
        for chunk in chunks:
            copied = dict(chunk)
            chapter_index = copied.get("chapter_index") or copied.get("chapter_id")
            if str(chapter_index).isdigit() and int(chapter_index) >= split_chapter_index:
                move.append(copied)
            else:
                keep.append(copied)
        if split_pos is not None and move:
            first = move[0]
            if first.get("chapter_index") == split_chapter_index:
                first["start_pos"] = split_pos
        return keep, move

    def _new_split_scene_payload(
        self,
        source: Scene,
        data: SceneSplitRequest,
        chapter_ids: list[str],
        chunks: list[dict],
    ) -> dict[str, Any]:
        return {
            "scene_index": source.scene_index + 1,
            "title": data.new_scene_title or f"{source.title or 'Scene'}（拆分）",
            "narrative_tag": source.narrative_tag or "draft",
            "source": "manual",
            "chapter_ids": chapter_ids,
            "scene_chunks": chunks,
            "pov_character_id": source.pov_character_id,
            "status": data.new_scene_status or "draft",
            "structure_meta": {
                "split_from_scene_id": str(source.id),
                "split_at_chapter_index": data.split_chapter_index,
                "needs_organize": True,
            },
        }

    async def _shift_later_scenes(self, db: AsyncSession, new_scene: Scene) -> None:
        scenes = await self.repo.get_by_novel_ordered(db, new_scene.novel_id)
        for scene in scenes:
            if scene.id != new_scene.id and scene.scene_index >= new_scene.scene_index:
                scene.scene_index += 1
                db.add(scene)

    def _range_from_chapters(self, chapter_ids: list[str]) -> tuple[int, int]:
        nums = sorted(int(cid) for cid in chapter_ids if str(cid).isdigit())
        if not nums:
            return (0, 0)
        return nums[0], nums[-1]

    async def _related_thread_summary(
        self,
        db: AsyncSession,
        novel_id: str,
        start: int,
        end: int,
    ) -> dict[str, Any]:
        if start <= 0 or end <= 0:
            return {"count": 0}
        from modules.outline.services import PlotThreadService

        count = await PlotThreadService().count_by_novel_and_range(
            db, parse_uuid(novel_id, "novel_id"), start, end
        )
        return {"count": count}

    async def _related_foreshadowing_summary(
        self,
        db: AsyncSession,
        novel_id: str,
        start: int,
        end: int,
    ) -> dict[str, Any]:
        if start <= 0 or end <= 0:
            return {"count": 0}
        from modules.outline.foreshadowing_repository import ForeshadowingPlanRepository

        count = await ForeshadowingPlanRepository().count_by_novel_and_range(
            db, parse_uuid(novel_id, "novel_id"), start, end
        )
        return {"count": count}

    async def _related_reveal_summary(
        self,
        db: AsyncSession,
        novel_id: str,
        start: int,
        end: int,
    ) -> dict[str, Any]:
        if start <= 0 or end <= 0:
            return {"count": 0}
        from sqlalchemy import select

        from modules.outline.models import RevealPlan

        nid = parse_uuid(novel_id, "novel_id")
        result = await db.execute(select(RevealPlan).where(RevealPlan.novel_id == nid))
        count = 0
        for plan in result.scalars().all():
            stages = plan.reveal_stages or []
            if any(
                start <= int(stage.get("chapter_index", 0)) <= end
                for stage in stages
            ):
                count += 1
        return {"count": count}
