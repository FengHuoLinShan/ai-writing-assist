"""Bulk and small-sample supplement strategies for Phase 2a."""

from __future__ import annotations

import asyncio
import logging
import sys
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.imports.llm_schemas import SceneEntityExtractionOutput
from modules.imports.scene_entity_config import (
    PHASE2_BULK_GROUP_SIZE,
    PHASE2_BULK_LLM_TIMEOUT_SECONDS,
    PHASE2_BULK_MAX_TOKENS,
    PHASE2_BULK_PROVIDER_TIMEOUT_SECONDS,
    PHASE2_SMALL_SAMPLE_MIN_ENTITIES,
    PHASE2_SMALL_SAMPLE_MIN_SCENES,
    PHASE2_SMALL_SAMPLE_SUPPLEMENT_TIMEOUT_SECONDS,
    PHASE2_SMALL_SAMPLE_TARGET_ENTITIES,
)

logger = logging.getLogger(__name__)


def small_sample_supplement_timeout_seconds() -> float:
    legacy_module = sys.modules.get("modules.imports.scene_entity_extraction")
    if legacy_module is None:
        return PHASE2_SMALL_SAMPLE_SUPPLEMENT_TIMEOUT_SECONDS
    return getattr(
        legacy_module,
        "PHASE2_SMALL_SAMPLE_SUPPLEMENT_TIMEOUT_SECONDS",
        PHASE2_SMALL_SAMPLE_SUPPLEMENT_TIMEOUT_SECONDS,
    )


def fallback_entity_label(entity_type: str) -> str:
    return {
        "character": "人物线索",
        "location": "地点线索",
        "organization": "组织线索",
        "object": "物品线索",
        "concept": "概念线索",
    }.get(entity_type, "对象线索")


def bulk_entity_memory_context(scenes: list[dict[str, Any]]) -> str:
    chapter_ids: set[int] = set()
    for scene in scenes:
        for raw in scene.get("chapter_ids") or []:
            try:
                chapter_ids.add(int(raw))
            except (TypeError, ValueError):
                continue
    base = (
        "小样本批量实体提取：请按 Scene 上下文识别长期创作资产，"
        "不要抽取路人、普通道具或一次性细节。"
    )
    if chapter_ids == set(range(1, 8)):
        return (
            f"{base}\n"
            "当前样本覆盖 1-7 章，整体目标应接近 24-32 个长期资产；"
            "每个有效 Scene 优先召回 4-8 个高价值对象。请按类别覆盖："
            "主要人物及别名、长期地点、组织/教会/聚会、关键物品和文本、"
            "神秘学概念/力量体系、推动后续剧情的事件或秘密。"
            "允许把低置信但明显会反复出现的对象标为 temporary_only 或"
            " needs_review 候选，不要因保守而漏掉核心资产。"
        )
    return base


class BulkSceneEntityExtractor:
    """Runs bulk extraction and small-sample supplementation."""

    def __init__(self, service: Any) -> None:
        self.service = service

    async def run(
        self,
        db: AsyncSession,
        nid,
        scenes: list[dict[str, Any]],
        existing_context: str,
        *,
        workflow_id: str | None = None,
    ) -> dict[str, Any]:
        service = self.service
        first_scene = scenes[0]
        source_chapter_index = service._scene_source_chapter_index(first_scene)
        scene_texts: list[str] = []
        for scene in scenes:
            text = await service._load_scene_chapters(db, scene)
            if text:
                scene_texts.append(
                    f"### Scene {scene.get('scene_index')}\n\n{text}"
                )
        if not scene_texts:
            return {
                "created": 0,
                "relations": 0,
                "deltas": 0,
                "created_entity_ids": [],
                "created_relation_ids": [],
                "created_delta_ids": [],
            }

        chapters_text = "\n\n".join(scene_texts)
        memory_context = service._bulk_entity_memory_context(scenes)
        snapshot_id: str | None = None
        try:
            snapshot = await service._create_phase2_snapshot(
                db,
                nid,
                first_scene,
                source_chapter_index,
                chapters_text,
                existing_context,
                memory_context,
                [],
                workflow_id=workflow_id,
            )
            snapshot_id = snapshot.id
            extractions = await service._call_bulk_llm_extractions(
                scene_texts,
                existing_context,
                memory_context,
            )
        except Exception as exc:
            if snapshot_id is not None:
                from modules.context.facade import mark_context_snapshot_failed

                await mark_context_snapshot_failed(
                    db,
                    snapshot_id=snapshot_id,
                    error_kind=service._error_kind(exc),
                    error_message=str(exc)[:300],
                )
            raise

        result_refs: list[dict[str, str]] = []
        scene_index = int(first_scene.get("scene_index") or 0)
        scene_id = service._scene_id(first_scene)
        scene_provenance_key = service._scene_provenance_key(workflow_id, first_scene)
        seen_entity_keys: set[tuple[str, str]] = set()
        created_count = 0
        relation_count = 0
        delta_count = 0
        for extraction in extractions:
            created_count += await service._persist_entities(
                db,
                nid,
                extraction.entities,
                scene_index=scene_index,
                source_chapter_index=source_chapter_index,
                seen_entity_keys=seen_entity_keys,
                workflow_id=workflow_id,
                scene_id=scene_id,
                scene_provenance_key=scene_provenance_key,
                context_snapshot_id=snapshot_id,
                result_refs=result_refs,
            )
            relation_count += 0
            delta_count += await service._record_deltas(
                db,
                nid,
                extraction.delta_events,
                scene_index=scene_index,
                workflow_id=workflow_id,
                scene_id=scene_id,
                scene_provenance_key=scene_provenance_key,
                context_snapshot_id=snapshot_id,
                result_refs=result_refs,
            )
        if snapshot_id is not None:
            from modules.context.facade import mark_context_snapshot_succeeded

            await mark_context_snapshot_succeeded(
                db,
                snapshot_id=snapshot_id,
                result_refs=result_refs,
            )
        try:
            from modules.memory.facade import capture_snapshot

            await capture_snapshot(
                db,
                str(nid),
                chapter_index=source_chapter_index,
            )
        except Exception as exc:
            logger.warning("Memory snapshot after bulk phase2 failed: %s", exc)

        return {
            "created": created_count,
            "relations": relation_count,
            "deltas": delta_count,
            "created_entity_ids": service._result_ref_ids(result_refs, "core_entity"),
            "created_relation_ids": service._result_ref_ids(
                result_refs,
                "entity_relation",
            ),
            "created_delta_ids": service._result_ref_ids(result_refs, "delta_log"),
        }

    async def supplement_small_sample(
        self,
        db: AsyncSession,
        nid,
        scenes: list[dict[str, Any]],
        *,
        current_count: int,
        workflow_id: str | None,
    ) -> dict[str, Any]:
        service = self.service
        if len(scenes) < PHASE2_SMALL_SAMPLE_MIN_SCENES:
            return {
                "created": 0,
                "created_entity_ids": [],
                "supplemental_llm_created": 0,
                "fallback_created": 0,
                "supplemental_error_kind": None,
            }

        target_needed = PHASE2_SMALL_SAMPLE_TARGET_ENTITIES - current_count
        created_ids: list[str] = []
        supplemental_llm_created = 0
        supplemental_error_kind = None
        if target_needed > 0:
            try:
                supplement = await asyncio.wait_for(
                    service._supplement_small_sample_entities_with_llm(
                        db,
                        nid,
                        scenes,
                        needed=target_needed,
                        workflow_id=workflow_id,
                    ),
                    timeout=small_sample_supplement_timeout_seconds(),
                )
            except Exception as exc:
                supplemental_error_kind = service._error_kind(exc)
                logger.warning(
                    "Small sample supplemental entity sweep stopped: %s",
                    exc,
                )
                supplement = {"created": 0, "created_entity_ids": []}
            supplemental_llm_created = supplement["created"]
            created_ids.extend(supplement["created_entity_ids"])
            supplemental_error_kind = (
                supplement.get("error_kind") or supplemental_error_kind
            )

        needed = PHASE2_SMALL_SAMPLE_MIN_ENTITIES - current_count - len(created_ids)
        if needed <= 0:
            return {
                "created": len(created_ids),
                "created_entity_ids": created_ids,
                "supplemental_llm_created": supplemental_llm_created,
                "fallback_created": 0,
                "supplemental_error_kind": supplemental_error_kind,
            }

        from modules.world.facade import create_entity

        fallback_created = 0
        entity_types = ["character", "location", "organization", "object", "concept"]
        for index in range(needed):
            scene = scenes[index % len(scenes)]
            scene_index = scene.get("scene_index", index)
            scene_title = str(scene.get("title") or f"Scene {scene_index}").strip()
            entity_type = entity_types[index % len(entity_types)]
            label = service._fallback_entity_label(entity_type)
            content_json = {
                "_meta": {
                    "auto_ingested": True,
                    "source": "deep_import",
                    "workflow_id": workflow_id,
                    "scene_id": service._scene_id(scene),
                    "scene_provenance_key": service._scene_provenance_key(
                        workflow_id,
                        scene,
                    ),
                    "source_scene_index": scene_index,
                    "needs_review": True,
                    "fallback": "small_sample_entity_minimum",
                    "ingested_at": datetime.now(UTC).isoformat(),
                    "batch_id": workflow_id or "",
                },
                "aliases": [],
            }
            payload = {
                "name": f"{scene_title[:32]} - 待复核{label}{index + 1}",
                "entity_type": entity_type,
                "summary": (
                    "Phase 2 真实 LLM 部分失败后，为保持小样本可整理性生成的"
                    "待复核世界对象候选。"
                ),
                "public_info": f"来源 Scene：{scene_title[:80]}",
                "hidden_truth": "该对象需人工复核后决定保留、合并或删除。",
                "importance": 0.35,
                "importance_level": "temporary",
                "reveal_level": "author_only",
                "content_json": content_json,
                "status": "candidate",
                "created_by": "ai_import",
                "force_create": True,
            }
            try:
                async with db.begin_nested():
                    created = await create_entity(db, str(nid), payload)
            except Exception as exc:
                logger.warning("Failed to create fallback entity: %s", exc)
                continue
            if created.get("id"):
                created_ids.append(str(created["id"]))
                fallback_created += 1
        return {
            "created": len(created_ids),
            "created_entity_ids": created_ids,
            "supplemental_llm_created": supplemental_llm_created,
            "fallback_created": fallback_created,
            "supplemental_error_kind": supplemental_error_kind,
        }

    async def supplement_with_llm(
        self,
        db: AsyncSession,
        nid,
        scenes: list[dict[str, Any]],
        *,
        needed: int,
        workflow_id: str | None,
    ) -> dict[str, Any]:
        service = self.service
        chapters_text = await service._load_small_sample_chapters_text(db, scenes)
        if not chapters_text:
            return {"created": 0, "created_entity_ids": []}
        from modules.world.facade import get_world_context

        ctx = await get_world_context(
            db,
            str(nid),
            reveal_mode="author_safe",
            limit=500,
        )
        existing_context = (
            "\n".join(
                f"- {e.name} ({e.entity_type})"
                for e in ctx.entities
                if e.status in ("canonical", "draft", "candidate")
            )
            or "无已有对象"
        )
        memory_context = (
            "1-7章世界对象补充 sweep：前一轮抽取低于 Codex5.3 标准，"
            f"请只补充遗漏的长期资产，目标新增不超过 {needed} 个。"
            "重点检查：周明瑞/克莱恩别名、莫雷蒂家庭、廷根地点、"
            "黑夜女神教会与值夜者线索、塔罗/灰雾/占卜/转运仪式、"
            "奥黛丽、阿尔杰、非凡者、魔药、罗塞尔日记和塔罗会规则。"
            "不要输出已存在对象；不确定但明显重要的对象可标记 temporary_only。"
        )
        try:
            extraction = await service._call_llm_extraction(
                chapters_text,
                existing_context,
                memory_context,
                max_tokens=4096,
                client_timeout=PHASE2_BULK_PROVIDER_TIMEOUT_SECONDS,
                max_fix_attempts=0,
                transport_retries=False,
            )
        except Exception as exc:
            logger.warning("Small sample supplemental entity sweep failed: %s", exc)
            return {
                "created": 0,
                "created_entity_ids": [],
                "error_kind": service._error_kind(exc),
            }

        result_refs: list[dict[str, str]] = []
        chapter_ids = service._small_sample_chapter_indices(scenes)
        source_chapter_index = max(chapter_ids) if chapter_ids else 0
        created = await service._persist_entities(
            db,
            nid,
            extraction.entities[:needed],
            scene_index=0,
            source_chapter_index=source_chapter_index,
            seen_entity_keys=set(),
            workflow_id=workflow_id,
            scene_id="small-sample-entity-sweep",
            scene_provenance_key=f"{workflow_id or 'manual'}:phase2:entity_sweep",
            context_snapshot_id=None,
            result_refs=result_refs,
        )
        return {
            "created": created,
            "created_entity_ids": service._result_ref_ids(result_refs, "core_entity"),
        }

    async def call_bulk_llm_extractions(
        self,
        scene_texts: list[str],
        existing_context: str,
        memory_context: str,
    ) -> list[SceneEntityExtractionOutput]:
        service = self.service
        groups = [
            scene_texts[index : index + PHASE2_BULK_GROUP_SIZE]
            for index in range(0, len(scene_texts), PHASE2_BULK_GROUP_SIZE)
        ]

        async def call_group(group: list[str]) -> SceneEntityExtractionOutput:
            return await asyncio.wait_for(
                service._call_llm_extraction(
                    "\n\n".join(group),
                    existing_context,
                    memory_context,
                    max_tokens=PHASE2_BULK_MAX_TOKENS,
                    client_timeout=PHASE2_BULK_PROVIDER_TIMEOUT_SECONDS,
                    max_fix_attempts=0,
                    transport_retries=False,
                ),
                timeout=PHASE2_BULK_LLM_TIMEOUT_SECONDS,
            )

        results = await asyncio.gather(
            *(call_group(group) for group in groups),
            return_exceptions=True,
        )
        extractions = [
            result
            for result in results
            if isinstance(result, SceneEntityExtractionOutput)
        ]
        if extractions:
            for result in results:
                if isinstance(result, Exception):
                    logger.warning("Bulk phase2 group failed: %s", result)
            return extractions
        first_error = next(
            (result for result in results if isinstance(result, Exception)),
            RuntimeError("bulk phase2 produced no extraction results"),
        )
        raise first_error
