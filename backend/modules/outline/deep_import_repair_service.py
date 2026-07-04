from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.outline.models import ForeshadowingPlan, OutlineArc, PlotThread, RevealPlan
from modules.outline.repositories import SceneRepository
from modules.outline.schemas import (
    ForeshadowingPlanCreate,
    OutlineArcCreate,
    PlotThreadCreate,
    RevealPlanCreate,
)
from modules.outline.services import (
    ForeshadowingPlanService,
    OutlineArcService,
    PlotThreadService,
    RevealPlanService,
    SceneService,
)
from modules.world.facade import list_entities as default_list_entities
from shared.utils import parse_uuid

SMALL_SAMPLE_STRUCTURE_TARGET_COUNT = 4

ServiceResolver = Callable[[str], Any]
ListEntities = Callable[..., Awaitable[list[dict[str, Any]]]]


def minimum_structure_category_targets(
    chapter_count: int,
    *,
    small_sample_target_count: int = SMALL_SAMPLE_STRUCTURE_TARGET_COUNT,
) -> dict[str, int]:
    if chapter_count <= 7:
        return {
            "threads": small_sample_target_count,
            "arcs": small_sample_target_count,
            "foreshadowing": small_sample_target_count,
            "reveals": small_sample_target_count,
        }
    return {
        "threads": max(3, chapter_count // 20),
        "arcs": max(4, (chapter_count + 14) // 15),
        "foreshadowing": max(3, chapter_count // 20),
        "reveals": max(3, chapter_count // 20),
    }


def structure_category_counts(result: dict[str, Any]) -> dict[str, int]:
    extra_sections = result.get("extra_sections") or {}
    return {
        "threads": int(result.get("total_threads", 0) or 0),
        "arcs": int(result.get("total_arcs", 0) or 0),
        "foreshadowing": len(extra_sections.get("foreshadowing_plans") or []),
        "reveals": len(extra_sections.get("reveal_plans") or []),
    }


def structure_output_count(result: dict[str, Any]) -> int:
    return sum(structure_category_counts(result).values())


def fallback_thread_type(index: int) -> str:
    types = ["main", "secondary", "hidden", "foreshadowing"]
    return types[(index - 1) % len(types)]


class OutlineDeepImportRepairService:
    """Outline-owned repair logic used by deep-import display repair."""

    def __init__(
        self,
        *,
        service_resolver: ServiceResolver | None = None,
        list_entities: ListEntities | None = None,
    ) -> None:
        self._service_resolver = service_resolver
        self._list_entities = list_entities or default_list_entities

    async def reindex_scenes(self, db: AsyncSession, novel_id: str) -> int:
        nid = parse_uuid(novel_id, "novel_id")
        repo = SceneRepository()
        scenes = await SceneService().get_ordered_models(db, novel_id)
        ordered = sorted(
            scenes,
            key=lambda scene: (
                self._scene_chapter_sort_key(scene),
                scene.created_at,
                str(scene.id),
            ),
        )
        current_order = [scene.id for scene in scenes]
        desired_order = [scene.id for scene in ordered]
        already_indexed = all(
            scene.scene_index == index for index, scene in enumerate(ordered)
        )
        if current_order == desired_order and already_indexed:
            return 0
        updated = await repo.reorder(db, nid, desired_order)
        await repo.backfill_chapter_links(db, nid)
        return updated

    async def structure_counts(
        self,
        db: AsyncSession,
        novel_id: str,
    ) -> dict[str, int]:
        nid = parse_uuid(novel_id, "novel_id")

        async def count(model) -> int:
            result = await db.execute(
                select(func.count(model.id)).where(model.novel_id == nid)
            )
            return int(result.scalar() or 0)

        return {
            "threads": await count(PlotThread),
            "arcs": await count(OutlineArc),
            "foreshadowing": await count(ForeshadowingPlan),
            "reveals": await count(RevealPlan),
        }

    async def structure_payload(
        self,
        db: AsyncSession,
        novel_id: str,
    ) -> dict[str, Any]:
        nid = parse_uuid(novel_id, "novel_id")
        threads = (
            await db.execute(select(PlotThread).where(PlotThread.novel_id == nid))
        ).scalars().all()
        arcs = (
            await db.execute(select(OutlineArc).where(OutlineArc.novel_id == nid))
        ).scalars().all()
        foreshadowing = (
            await db.execute(
                select(ForeshadowingPlan).where(ForeshadowingPlan.novel_id == nid)
            )
        ).scalars().all()
        reveals = (
            await db.execute(select(RevealPlan).where(RevealPlan.novel_id == nid))
        ).scalars().all()
        return {
            "total_threads": len(threads),
            "total_arcs": len(arcs),
            "threads": [{"id": str(item.id), "name": item.name} for item in threads],
            "arcs": [
                {"id": str(item.id), "title": item.title, "arc_index": item.arc_index}
                for item in arcs
            ],
            "extra_sections": {
                "foreshadowing_plans": [
                    {"id": str(item.id), "name": item.name} for item in foreshadowing
                ],
                "reveal_plans": [
                    {"id": str(item.id), "target_id": str(item.target_id)}
                    for item in reveals
                ],
            },
        }

    async def ensure_minimum_structure_outputs(
        self,
        db: AsyncSession,
        novel_id: str,
        start_chapter: int,
        end_chapter: int,
        result: dict[str, Any],
        *,
        workflow_id: str | None,
        small_sample_target_count: int = SMALL_SAMPLE_STRUCTURE_TARGET_COUNT,
    ) -> dict[str, Any]:
        chapter_count = end_chapter - start_chapter + 1
        counts = structure_category_counts(result)
        targets = minimum_structure_category_targets(
            chapter_count,
            small_sample_target_count=small_sample_target_count,
        )
        if all(counts[key] >= target for key, target in targets.items()):
            return result

        created_assets: list[dict[str, Any]] = []
        try:
            arc_service = self._get_service("outline.arc_service")
            thread_service = self._get_service("outline.thread_service")
            foreshadowing_service = self._get_service("outline.foreshadowing_service")
            reveal_service = self._get_service("outline.reveal_service")
            provenance_meta = {
                "source": "deep_import",
                "workflow_id": workflow_id,
                "auto_ingested": True,
                "needs_review": True,
                "phase": "structure_analysis",
                "fallback": "category_minimum_structure_outputs",
            }

            thread_payloads = [
                PlotThreadCreate(
                    name=f"第 {start_chapter}-{end_chapter} 章补强剧情线 {index}",
                    thread_type=fallback_thread_type(index),
                    summary="根据已导入 Scene 和世界对象补齐的待复核剧情线。",
                    visible_goal="把章节范围内的关键行动转化为可追踪结构资产。",
                    hidden_truth="该项由深度导入小样本结构保底生成，需要人工复核。",
                    start_chapter=start_chapter,
                    planned_payoff_chapter=end_chapter,
                    current_stage="draft",
                    provenance_meta=dict(provenance_meta),
                    status="draft",
                )
                for index in range(counts["threads"] + 1, targets["threads"] + 1)
            ]
            created_threads = []
            if thread_payloads:
                created_threads = await thread_service.create_batch(
                    db,
                    novel_id,
                    thread_payloads,
                )
            for created in created_threads:
                thread_summary = {
                    "id": str(created.id),
                    "name": created.name,
                    "thread_type": created.thread_type,
                }
                result.setdefault("threads", []).append(thread_summary)
                result["total_threads"] = int(result.get("total_threads", 0) or 0) + 1
                created_assets.append(
                    {
                        "type": "plot_thread",
                        "id": thread_summary["id"],
                        "reason": "category_minimum_structure_outputs",
                    }
                )

            arc_payloads = [
                OutlineArcCreate(
                    title=f"第 {start_chapter}-{end_chapter} 章补强篇章纲 {index}",
                    arc_index=index,
                    start_chapter=start_chapter,
                    end_chapter=end_chapter,
                    arc_goal="把已生成 Scene 的阶段性推进整理为可复核篇章结构。",
                    core_conflict=(
                        "关键 Scene 已存在，但结构分析输出不足以覆盖所有转折。"
                    ),
                    entry_hook="从导入 Scene 中回收章节开端的触发事件。",
                    midpoint_turn="以章节中段的认知变化或关系变化作为转折锚点。",
                    climax="以章节范围内最强冲突或信息揭示作为高潮锚点。",
                    result="生成待复核篇章纲候选，供用户整理、合并或删除。",
                    next_hook="用后续章节校验该篇章纲是否应保留。",
                    provenance_meta=dict(provenance_meta),
                    status="draft",
                )
                for index in range(counts["arcs"] + 1, targets["arcs"] + 1)
            ]
            created_arcs = []
            if arc_payloads:
                created_arcs = await arc_service.create_batch(
                    db,
                    novel_id,
                    arc_payloads,
                )
            for created in created_arcs:
                arc_summary = {
                    "id": str(created.id),
                    "title": created.title,
                    "arc_index": created.arc_index,
                }
                result.setdefault("arcs", []).append(arc_summary)
                result["total_arcs"] = int(result.get("total_arcs", 0) or 0) + 1
                created_assets.append(
                    {
                        "type": "outline_arc",
                        "id": arc_summary["id"],
                        "reason": "category_minimum_structure_outputs",
                    }
                )

            extra_sections = result.setdefault("extra_sections", {})
            foreshadowing_items = extra_sections.setdefault("foreshadowing_plans", [])
            foreshadowing_payloads = [
                ForeshadowingPlanCreate(
                    name=f"第 {start_chapter}-{end_chapter} 章补强伏笔 {index}",
                    summary="根据已导入 Scene 补齐的待复核伏笔计划。",
                    surface_meaning="章节内已经出现但尚未整理为结构资产的线索。",
                    hidden_meaning="该线索可能指向后续身份、组织或非凡规则揭示。",
                    planned_seed_chapter=start_chapter,
                    planned_payoff_chapter=end_chapter,
                    provenance_meta=dict(provenance_meta),
                    status="draft",
                )
                for index in range(
                    counts["foreshadowing"] + 1,
                    targets["foreshadowing"] + 1,
                )
            ]
            created_foreshadowing = []
            if foreshadowing_payloads:
                created_foreshadowing = await foreshadowing_service.create_batch(
                    db,
                    novel_id,
                    foreshadowing_payloads,
                )
            for created in created_foreshadowing:
                item = {"id": str(created.id), "name": created.name}
                foreshadowing_items.append(item)
                created_assets.append(
                    {
                        "type": "foreshadowing_plan",
                        "id": item["id"],
                        "reason": "category_minimum_structure_outputs",
                    }
                )

            reveal_items = extra_sections.setdefault("reveal_plans", [])
            if counts["reveals"] >= targets["reveals"]:
                reveal_target = None
            else:
                reveal_target = await self.select_fallback_reveal_target(db, novel_id)
            if reveal_target is None and counts["reveals"] < targets["reveals"]:
                result.setdefault("warnings", []).append(
                    "揭示计划不足，但没有可关联世界对象，无法补强 reveal。"
                )
            elif reveal_target is not None:
                reveal_payloads = [
                    RevealPlanCreate(
                        target_type="world_entity",
                        target_id=reveal_target["id"],
                        secret_summary=(
                            f"{reveal_target['name']} 在第 "
                            f"{start_chapter}-{end_chapter} 章范围内存在待复核"
                            "的信息层级或隐藏背景。"
                        ),
                        reveal_stages=[
                            {
                                "stage_index": 0,
                                "chapter_index": start_chapter,
                                "reveal_content": "读者获得初步表层线索。",
                                "trigger": "Scene 导入后的结构补强。",
                                "effect": "形成后续人工整理的揭示计划草稿。",
                            }
                        ],
                        provenance_meta=dict(provenance_meta),
                        status="draft",
                    )
                    for _index in range(
                        counts["reveals"] + 1,
                        targets["reveals"] + 1,
                    )
                ]
                created_reveals = await reveal_service.create_batch(
                    db,
                    novel_id,
                    reveal_payloads,
                )
                for created in created_reveals:
                    item = {"id": str(created.id), "target_name": reveal_target["name"]}
                    reveal_items.append(item)
                    created_assets.append(
                        {
                            "type": "reveal_plan",
                            "id": item["id"],
                            "reason": "category_minimum_structure_outputs",
                        }
                    )
        except Exception as exc:
            warnings = result.setdefault("warnings", [])
            warnings.append(f"category_minimum_structure_outputs fallback failed: {exc}")
            return result

        if created_assets:
            extra_sections = result.setdefault("extra_sections", {})
            extra_sections.setdefault("fallback_structure_assets", []).extend(
                created_assets
            )
            result.setdefault("warnings", []).append(
                "结构类别输出不足，已补充待复核结构候选。"
            )
        return result

    async def ensure_structure_minimum_counts(
        self,
        db: AsyncSession,
        novel_id: str,
        start_chapter: int,
        end_chapter: int,
        *,
        workflow_id: str | None,
    ) -> dict[str, int]:
        payload = await self.structure_payload(db, novel_id)
        await self.ensure_minimum_structure_outputs(
            db,
            novel_id,
            start_chapter,
            end_chapter,
            payload,
            workflow_id=workflow_id,
        )
        return await self.structure_counts(db, novel_id)

    async def select_fallback_reveal_target(
        self,
        db: AsyncSession,
        novel_id: str,
    ) -> dict[str, Any] | None:
        entities = await self._list_entities(db, novel_id, limit=20)
        for entity in entities:
            entity_id = entity.get("id")
            name = entity.get("name")
            if entity_id and name:
                return {"id": entity_id, "name": name}
        return None

    def _get_service(self, name: str) -> Any:
        if self._service_resolver is not None:
            return self._service_resolver(name)
        defaults = {
            "outline.thread_service": PlotThreadService(),
            "outline.arc_service": OutlineArcService(),
            "outline.foreshadowing_service": ForeshadowingPlanService(),
            "outline.reveal_service": RevealPlanService(),
        }
        return defaults[name]

    def _scene_chapter_sort_key(self, scene) -> int:
        chunks = scene.scene_chunks or []
        chapter_indices: list[int] = []
        for chunk in chunks:
            if isinstance(chunk, dict) and chunk.get("chapter_index") is not None:
                chapter_indices.append(int(chunk["chapter_index"]))
        if chapter_indices:
            return min(chapter_indices)
        for chapter_id in scene.chapter_ids or []:
            try:
                return int(chapter_id)
            except (TypeError, ValueError):
                continue
        return int(scene.scene_index or 0)
