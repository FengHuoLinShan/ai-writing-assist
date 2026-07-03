from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.outline.models import Scene
from modules.outline.repositories import SceneRepository
from modules.outline.schemas import (
    SceneCreate,
    SceneFusionDraft,
    SceneFusionPreviewRequest,
    SceneFusionPreviewResponse,
    SceneFusionSaveRequest,
    SceneFusionSaveResponse,
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
        status: str | None = None,
        source: str | None = None,
        workflow_id: str | None = None,
        needs_review: bool | None = None,
        boundary_status: str | None = None,
        phase: str | None = None,
        phase1a_fallback: bool | None = None,
        skip: int = 0,
        limit: int | None = None,
    ) -> SceneWorkbenchResponse:
        nid = parse_uuid(novel_id, "novel_id")
        scenes = await self.repo.get_by_novel_ordered(
            db,
            nid,
            status=status,
            source=source,
            workflow_id=workflow_id,
            needs_review=needs_review,
            boundary_status=boundary_status,
            phase=phase,
            phase1a_fallback=phase1a_fallback,
            skip=skip,
            limit=limit,
        )
        all_matching_scenes = await self.repo.get_by_novel_ordered(
            db,
            nid,
            status=status,
            source=source,
            workflow_id=workflow_id,
            needs_review=needs_review,
            boundary_status=boundary_status,
            phase=phase,
            phase1a_fallback=phase1a_fallback,
            skip=0,
            limit=None,
        )
        chapter_indices = await list_chapter_indices(db, novel_id)
        unassigned_chapters = self._unassigned_chapters(
            chapter_indices,
            all_matching_scenes,
        )
        duplicate_chapter_ids = self._duplicate_scene_chapter_ids(all_matching_scenes)

        items = [
            SceneWorkbenchItem(
                scene=SceneResponse.model_validate(scene),
                health=self._scene_health(scene, duplicate_chapter_ids),
                chapter_range=self._chapter_range(scene.chapter_ids or []),
                summary=scene.goal or scene.core_conflict or scene.emotional_beat,
            )
            for scene in scenes
        ]

        counts = {key: 0 for key in HEALTH_DEFS}
        for scene in all_matching_scenes:
            for key in self._scene_health(scene, duplicate_chapter_ids):
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
        await self._validate_mapping_chapters(
            db,
            novel_id,
            data.chapter_ids,
            data.scene_chunks,
        )
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
            data.split_pos,
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
            data.split_pos,
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

    async def preview_llm_fusion(
        self,
        db: AsyncSession,
        novel_id: str,
        data: SceneFusionPreviewRequest,
    ) -> SceneFusionPreviewResponse:
        sources = await self._load_fusion_scenes(db, novel_id, data.source_scene_ids)
        fused_scene = await self._fusion_scene_payload(db, novel_id, sources)
        return SceneFusionPreviewResponse(
            source_scene_ids=[str(scene.id) for scene in sources],
            fused_scene=fused_scene,
            preview_scene=fused_scene,
            warnings=["当前为本地确定性融合预览，后续可替换为 LLM 结果。"],
        )

    async def save_llm_fusion(
        self,
        db: AsyncSession,
        novel_id: str,
        data: SceneFusionSaveRequest,
    ) -> SceneFusionSaveResponse:
        sources = await self._load_fusion_scenes(db, novel_id, data.source_scene_ids)
        source_ids = [str(scene.id) for scene in sources]
        if data.mode == "discard":
            return SceneFusionSaveResponse(
                status="discarded",
                source_scene_ids=source_ids,
                fused_scene=None,
                warnings=["融合结果已放弃，原 Scene 未修改。"],
            )

        overrides = data.fused_scene if data.mode != "discard" else None
        payload = await self._fusion_scene_payload(db, novel_id, sources, overrides)
        await self._validate_fusion_override_chapters(db, novel_id, overrides)
        created = await self.repo.create(
            db,
            parse_uuid(novel_id, "novel_id"),
            SceneCreate(**payload),
        )

        if data.mode == "deprecate_originals":
            for source in sources:
                source_meta = dict(source.structure_meta or {})
                source_meta["fused_into_scene_id"] = str(created.id)
                await self.repo.update(
                    db,
                    source.id,
                    SceneUpdate(status="deprecated", structure_meta=source_meta),
                )
        await db.flush()

        return SceneFusionSaveResponse(
            status="saved",
            source_scene_ids=source_ids,
            fused_scene=SceneResponse.model_validate(created),
        )

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

    async def _load_fusion_scenes(
        self,
        db: AsyncSession,
        novel_id: str,
        source_scene_ids: list[str],
    ) -> list[Scene]:
        if len(set(source_scene_ids)) != len(source_scene_ids):
            raise ValueError("source_scene_ids cannot contain duplicates")
        return [
            await self._get_scene_in_novel(db, novel_id, scene_id)
            for scene_id in source_scene_ids
        ]

    async def _fusion_scene_payload(
        self,
        db: AsyncSession,
        novel_id: str,
        sources: list[Scene],
        overrides: SceneFusionDraft | None = None,
    ) -> dict[str, Any]:
        if not sources:
            raise ValueError("source_scene_ids cannot be empty")
        source_ids = [str(scene.id) for scene in sources]
        payload: dict[str, Any] = {
            "scene_index": await self._next_scene_index(db, novel_id),
            "title": self._fusion_title(sources),
            "goal": self._join_unique_scene_text(sources, "goal"),
            "core_conflict": self._join_unique_scene_text(sources, "core_conflict"),
            "emotional_beat": self._join_unique_scene_text(sources, "emotional_beat"),
            "must_happen": self._join_unique_scene_text(sources, "must_happen"),
            "must_not_happen": self._join_unique_scene_text(sources, "must_not_happen"),
            "narrative_tag": sources[0].narrative_tag or "draft",
            "source": "manual_fusion",
            "scene_chunks": self._merge_chunks(
                *[source.scene_chunks or [] for source in sources]
            ),
            "chapter_ids": self._merge_chapter_ids(
                *[source.chapter_ids or [] for source in sources]
            ),
            "pov_character_id": self._first_non_empty(sources, "pov_character_id"),
            "structure_meta": {
                "fused_from_scene_ids": source_ids,
                "fusion_kind": "llm_scene_workbench",
                "fusion_strategy": "local_deterministic_preview",
                "needs_review": True,
            },
            "status": "draft",
        }
        if overrides is not None:
            override_values = overrides.model_dump(exclude_unset=True)
            override_meta = override_values.pop("structure_meta", None)
            for field, value in override_values.items():
                if value is not None:
                    payload[field] = value
            if override_meta is not None:
                meta = dict(payload["structure_meta"])
                meta.update(override_meta)
                payload["structure_meta"] = meta
        payload["status"] = "draft"
        payload["source"] = payload.get("source") or "manual_fusion"
        payload["structure_meta"] = {
            **dict(payload.get("structure_meta") or {}),
            "fused_from_scene_ids": source_ids,
        }
        return payload

    async def _validate_fusion_override_chapters(
        self,
        db: AsyncSession,
        novel_id: str,
        overrides: SceneFusionDraft | None,
    ) -> None:
        if overrides is None:
            return
        override_values = overrides.model_dump(exclude_unset=True)
        if "chapter_ids" not in override_values and "scene_chunks" not in override_values:
            return
        if not await list_chapter_indices(db, novel_id):
            return
        await self._validate_mapping_chapters(
            db,
            novel_id,
            override_values.get("chapter_ids"),
            override_values.get("scene_chunks"),
        )

    async def _next_scene_index(self, db: AsyncSession, novel_id: str) -> int:
        nid = parse_uuid(novel_id, "novel_id")
        scenes = await self.repo.get_by_novel_ordered(
            db,
            nid,
        )
        deprecated_scenes = await self.repo.get_by_novel_ordered(
            db,
            nid,
            status="deprecated",
        )
        all_scenes = [*scenes, *deprecated_scenes]
        if not all_scenes:
            return 0
        return max(scene.scene_index for scene in all_scenes) + 1

    def _fusion_title(self, sources: list[Scene]) -> str:
        titles = [scene.title for scene in sources if scene.title]
        if not titles:
            return "融合 Scene"
        joined = " / ".join(titles)
        return f"融合：{joined}"[:255]

    def _join_unique_scene_text(self, scenes: list[Scene], field: str) -> str | None:
        values: list[str] = []
        seen: set[str] = set()
        for scene in scenes:
            value = getattr(scene, field)
            if value and value not in seen:
                seen.add(value)
                values.append(value)
        if not values:
            return None
        return "\n\n".join(values)

    async def _validate_mapping_chapters(
        self,
        db: AsyncSession,
        novel_id: str,
        chapter_ids: list[str] | None,
        scene_chunks: list[dict] | None,
    ) -> None:
        if chapter_ids is None and scene_chunks is None:
            return
        known_chapters = set(await list_chapter_indices(db, novel_id))
        if chapter_ids is not None:
            for chapter_id in chapter_ids:
                chapter_index = self._coerce_chapter_index(chapter_id, "chapter_ids")
                if chapter_index not in known_chapters:
                    raise ValueError(f"Chapter {chapter_index} is not in this novel")
        if scene_chunks is not None:
            for chunk in scene_chunks:
                chapter_ref = chunk.get("chapter_index")
                if chapter_ref is None:
                    chapter_ref = chunk.get("chapter_id")
                chapter_index = self._coerce_chapter_index(
                    chapter_ref,
                    "scene_chunks",
                )
                if chapter_index not in known_chapters:
                    raise ValueError(
                        f"Chunk chapter {chapter_index} is not in this novel"
                    )
                if chunk.get("chapter_id") is not None:
                    chunk_id = self._coerce_chapter_index(
                        chunk.get("chapter_id"),
                        "scene_chunks.chapter_id",
                    )
                    if chunk_id != chapter_index:
                        raise ValueError(
                            "scene_chunks chapter_id and chapter_index mismatch"
                        )

    def _coerce_chapter_index(self, value: Any, field: str) -> int:
        if value is None or not str(value).isdigit():
            raise ValueError(f"{field} must use numeric chapter indexes")
        return int(value)

    def _duplicate_scene_chapter_ids(self, scenes: list[Scene]) -> set[str]:
        seen: set[str] = set()
        duplicates: set[str] = set()
        for scene in scenes:
            for chapter_id in {str(cid) for cid in scene.chapter_ids or []}:
                if chapter_id in seen:
                    duplicates.add(chapter_id)
                else:
                    seen.add(chapter_id)
        return duplicates

    def _scene_health(
        self,
        scene: Scene,
        duplicate_chapter_ids: set[str] | None = None,
    ) -> list[str]:
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
        if self._needs_organize(scene, duplicate_chapter_ids or set()):
            health.append("needs_organize")
        return health

    def _needs_organize(self, scene: Scene, duplicate_chapter_ids: set[str]) -> bool:
        meta = scene.structure_meta or {}
        if meta.get("needs_organize"):
            return True
        chapter_ids = scene.chapter_ids or []
        if len(chapter_ids) != len(set(chapter_ids)):
            return True
        if any(str(chapter_id) in duplicate_chapter_ids for chapter_id in chapter_ids):
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
        split_pos: int | None = None,
    ) -> tuple[list[str], list[str]]:
        keep: list[str] = []
        move: list[str] = []
        found_boundary = False
        for chapter_id in chapter_ids:
            if str(chapter_id).isdigit() and int(chapter_id) == split_chapter_index:
                found_boundary = True
                if split_pos is not None:
                    keep.append(str(chapter_id))
                move.append(str(chapter_id))
            elif str(chapter_id).isdigit() and int(chapter_id) > split_chapter_index:
                move.append(str(chapter_id))
            else:
                keep.append(str(chapter_id))
        if split_pos is not None and not found_boundary:
            raise ValueError(
                "split_chapter_index must exist in chapter_ids for split_pos"
            )
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
        boundary_split = False
        for chunk in chunks:
            copied = dict(chunk)
            chapter_index = self._chunk_chapter_index(copied)
            if chapter_index == split_chapter_index and split_pos is not None:
                start_pos = self._coerce_position(copied.get("start_pos", 0), "start_pos")
                end_pos = self._coerce_position(copied.get("end_pos"), "end_pos")
                if start_pos < split_pos < end_pos:
                    keep_part = dict(copied)
                    move_part = dict(copied)
                    keep_part["end_pos"] = split_pos
                    move_part["start_pos"] = split_pos
                    keep.append(keep_part)
                    move.append(move_part)
                    boundary_split = True
                elif end_pos <= split_pos:
                    keep.append(copied)
                elif start_pos >= split_pos:
                    move.append(copied)
                else:
                    raise ValueError("split_pos must be inside boundary chunk range")
            elif chapter_index is not None and chapter_index >= split_chapter_index:
                move.append(copied)
            else:
                keep.append(copied)
        if split_pos is not None and not boundary_split:
            raise ValueError("split_pos must be inside boundary chunk range")
        return keep, move

    def _chunk_chapter_index(self, chunk: dict) -> int | None:
        chapter_ref = chunk.get("chapter_index")
        if chapter_ref is None:
            chapter_ref = chunk.get("chapter_id")
        if chapter_ref is None or not str(chapter_ref).isdigit():
            return None
        return int(chapter_ref)

    def _coerce_position(self, value: Any, field: str) -> int:
        if value is None or not str(value).isdigit():
            raise ValueError(f"{field} must be numeric for split_pos")
        return int(value)

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
