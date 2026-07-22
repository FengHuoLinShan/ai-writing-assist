"""Bulk and small-sample supplement strategies for Phase 2a."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.llm.redaction import redact_diagnostic
from modules.imports.entity_extraction.scene_entity_config import (
    PHASE2_BULK_GROUP_SIZE,
    PHASE2_BULK_LLM_TIMEOUT_SECONDS,
    PHASE2_BULK_MAX_TOKENS,
    PHASE2_BULK_PROVIDER_TIMEOUT_SECONDS,
    PHASE2_SMALL_SAMPLE_MIN_ENTITIES,
    PHASE2_SMALL_SAMPLE_MIN_SCENES,
    PHASE2_SMALL_SAMPLE_SUPPLEMENT_TIMEOUT_SECONDS,
    PHASE2_SMALL_SAMPLE_TARGET_ENTITIES,
)
from modules.imports.entity_extraction.scene_entity_text import (
    scene_chapter_indices,
    scene_text_from_drafts,
)
from modules.imports.llm_schemas import SceneEntityExtractionOutput

logger = logging.getLogger(__name__)


def small_sample_supplement_timeout_seconds() -> float:
    default_timeout = PHASE2_SMALL_SAMPLE_SUPPLEMENT_TIMEOUT_SECONDS
    import modules.imports.entity_extraction as public_module

    timeout = getattr(
        public_module,
        "PHASE2_SMALL_SAMPLE_SUPPLEMENT_TIMEOUT_SECONDS",
        default_timeout,
    )
    if timeout != default_timeout:
        return timeout
    return default_timeout


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


class BulkSceneEntityExtractionMixin:
    """Internal bulk and small-sample Phase 2a implementation."""

    async def _process_scenes_bulk(
        self,
        db: AsyncSession,
        nid,
        scenes: list[dict[str, Any]],
        existing_context: str,
        *,
        workflow_id: str | None = None,
        authorization_snapshot: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        service = self
        first_scene = scenes[0]
        source_chapter_index = service._scene_source_chapter_index(first_scene)
        from modules.writing.facade import list_latest_drafts_for_chapters

        scene_chapter_payloads: list[
            tuple[dict[str, Any], list[int], dict[int, list[dict[str, Any]]]]
        ] = []
        all_chapter_indices: set[int] = set()
        for scene in scenes:
            chunk_by_chapter = service._scene_chunks_by_chapter(scene)
            chapter_ids = service._scene_chapter_ids(scene, chunk_by_chapter)
            chapter_indices = scene_chapter_indices(chapter_ids)
            scene_chapter_payloads.append((scene, chapter_indices, chunk_by_chapter))
            all_chapter_indices.update(chapter_indices)
        drafts = await list_latest_drafts_for_chapters(
            db,
            first_scene["novel_id"],
            sorted(all_chapter_indices),
        )
        draft_by_chapter = {draft.chapter_index: draft for draft in drafts}
        scene_texts: list[str] = []
        text_scenes: list[dict[str, Any]] = []
        input_fingerprints: dict[str, str] = {}
        for scene, chapter_indices, chunk_by_chapter in scene_chapter_payloads:
            text = scene_text_from_drafts(
                service,
                scene,
                chapter_indices,
                chunk_by_chapter,
                draft_by_chapter,
            )
            input_fingerprints[service._scene_id(scene)] = (
                service._scene_input_fingerprint(scene, text)
            )
            if text:
                text_scenes.append(scene)
                scene_texts.append(f"### Scene {scene.get('scene_index')}\n\n{text}")
        if not scene_texts:
            return {
                "created": 0,
                "relations": 0,
                "deltas": 0,
                "created_entity_ids": [],
                "created_relation_ids": [],
                "created_delta_ids": [],
                "input_fingerprints": input_fingerprints,
            }

        chapters_text = "\n\n".join(scene_texts)
        memory_context = service._bulk_entity_memory_context(scenes)
        snapshot_id: str | None = None
        format_diagnostics: list[dict[str, Any]] = []
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
            indexed_extractions = await service._call_bulk_llm_extractions(
                scene_texts,
                existing_context,
                memory_context,
                diagnostics=format_diagnostics,
                with_source_indexes=True,
            )
        except Exception as exc:
            if snapshot_id is not None:
                from modules.context.facade import fail_context_snapshot

                await fail_context_snapshot(
                    db,
                    novel_id=str(nid),
                    snapshot_id=snapshot_id,
                    error_kind=service._error_kind(exc),
                    error_message=redact_diagnostic(exc, limit=300),
                )
            raise

        result_refs: list[dict[str, str]] = []
        seen_entity_keys: set[tuple[str, str]] = set()
        created_count = 0
        relation_count = 0
        delta_count = 0
        map_candidate_counts = {"created": 0, "reused": 0}
        if indexed_extractions and not isinstance(indexed_extractions[0], tuple):
            indexed_extractions = list(enumerate(indexed_extractions))
        for source_index, extraction in indexed_extractions:
            scene = text_scenes[int(source_index)]
            scene_index = int(scene.get("scene_index") or 0)
            scene_id = service._scene_id(scene)
            source_chapter_index = service._scene_source_chapter_index(scene)
            scene_provenance_key = service._scene_provenance_key(workflow_id, scene)
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
            relation_count += await service._persist_relations(
                db,
                nid,
                extraction.relations,
                scene_index=scene_index,
                source_chapter_index=source_chapter_index,
                workflow_id=workflow_id,
                scene_id=scene_id,
                context_snapshot_id=snapshot_id,
                result_refs=result_refs,
            )
            delta_count += await service._record_deltas(
                db,
                nid,
                extraction.delta_events,
                scene_index=scene_index,
                source_chapter_index=source_chapter_index,
                workflow_id=workflow_id,
                scene_id=scene_id,
                scene_provenance_key=scene_provenance_key,
                context_snapshot_id=snapshot_id,
                result_refs=result_refs,
            )
            proposals = getattr(extraction, "map_observation_proposals", None)
            if isinstance(proposals, list) and proposals:
                counts = await service._record_map_observation_proposals(
                    db,
                    nid,
                    proposals,
                    scene_index=scene_index,
                    source_chapter_index=source_chapter_index,
                    workflow_id=workflow_id,
                    scene_id=scene_id,
                    scene_source_fingerprint=input_fingerprints.get(scene_id),
                    authorization_snapshot=authorization_snapshot,
                    context_snapshot_id=snapshot_id,
                    result_refs=result_refs,
                )
                map_candidate_counts["created"] += counts["created"]
                map_candidate_counts["reused"] += counts["reused"]
        if snapshot_id is not None:
            from modules.context.facade import succeed_context_snapshot

            await succeed_context_snapshot(
                db,
                novel_id=str(nid),
                snapshot_id=snapshot_id,
                result_refs=result_refs,
            )
        try:
            from modules.memory.facade import ensure_scene_checkpoints

            for scene in text_scenes:
                await ensure_scene_checkpoints(db, str(nid), service._scene_id(scene))
        except Exception as exc:
            logger.warning(
                "Scene memory checkpoints after bulk phase2 failed: %s",
                redact_diagnostic(exc, limit=300),
            )

        return {
            "created": created_count,
            "relations": relation_count,
            "deltas": delta_count,
            "map_observation_candidates": map_candidate_counts,
            "created_entity_ids": service._result_ref_ids(result_refs, "core_entity"),
            "created_relation_ids": service._result_ref_ids(
                result_refs,
                "entity_relation",
            ),
            "created_delta_ids": service._result_ref_ids(result_refs, "delta_log"),
            "structured_format_diagnostics": format_diagnostics[:20],
            "input_fingerprints": input_fingerprints,
        }

    async def _supplement_small_sample_entities(
        self,
        db: AsyncSession,
        nid,
        scenes: list[dict[str, Any]],
        *,
        current_count: int,
        workflow_id: str | None,
    ) -> dict[str, Any]:
        service = self
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
                    redact_diagnostic(exc, limit=300),
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
                logger.warning(
                    "Failed to create fallback entity: %s",
                    redact_diagnostic(exc, limit=300),
                )
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

    async def _supplement_small_sample_entities_with_llm(
        self,
        db: AsyncSession,
        nid,
        scenes: list[dict[str, Any]],
        *,
        needed: int,
        workflow_id: str | None,
    ) -> dict[str, Any]:
        service = self
        chapters_text = await service._load_small_sample_chapters_text(db, scenes)
        if not chapters_text:
            return {"created": 0, "created_entity_ids": []}
        from modules.world.facade import get_world_context

        ctx = await get_world_context(
            db,
            str(nid),
            reveal_mode="author_safe",
            limit=500,
            include_review=True,
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
                max_tokens=PHASE2_BULK_MAX_TOKENS,
                client_timeout=PHASE2_BULK_PROVIDER_TIMEOUT_SECONDS,
                max_fix_attempts=0,
                transport_retries=False,
            )
        except Exception as exc:
            logger.warning(
                "Small sample supplemental entity sweep failed: %s",
                redact_diagnostic(exc, limit=300),
            )
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

    async def _call_bulk_llm_extractions(
        self,
        scene_texts: list[str],
        existing_context: str,
        memory_context: str,
        *,
        diagnostics: list[dict[str, Any]] | None = None,
        with_source_indexes: bool = False,
    ) -> (
        list[SceneEntityExtractionOutput] | list[tuple[int, SceneEntityExtractionOutput]]
    ):
        service = self
        groups = [
            scene_texts[index : index + PHASE2_BULK_GROUP_SIZE]
            for index in range(0, len(scene_texts), PHASE2_BULK_GROUP_SIZE)
        ]

        async def call_group(group: list[str]) -> SceneEntityExtractionOutput:
            group_diagnostics: list[dict[str, Any]] = []
            result = await asyncio.wait_for(
                service._call_llm_extraction(
                    "\n\n".join(group),
                    existing_context,
                    memory_context,
                    max_tokens=PHASE2_BULK_MAX_TOKENS,
                    client_timeout=PHASE2_BULK_PROVIDER_TIMEOUT_SECONDS,
                    max_fix_attempts=0,
                    transport_retries=False,
                    diagnostics=group_diagnostics,
                ),
                timeout=PHASE2_BULK_LLM_TIMEOUT_SECONDS,
            )
            if diagnostics is not None:
                diagnostics.extend(group_diagnostics)
            return result

        results = await asyncio.gather(
            *(call_group(group) for group in groups),
            return_exceptions=True,
        )
        indexed_extractions = [
            (index * PHASE2_BULK_GROUP_SIZE, result)
            for index, result in enumerate(results)
            if isinstance(result, SceneEntityExtractionOutput)
        ]
        extractions = [result for _, result in indexed_extractions]
        if extractions:
            for result in results:
                if isinstance(result, Exception):
                    logger.warning(
                        "Bulk phase2 group failed: %s",
                        redact_diagnostic(result, limit=300),
                    )
            return indexed_extractions if with_source_indexes else extractions
        first_error = next(
            (result for result in results if isinstance(result, Exception)),
            RuntimeError("bulk phase2 produced no extraction results"),
        )
        raise first_error


class BulkSceneEntityExtractor(BulkSceneEntityExtractionMixin):
    """Compatibility adapter for the former helper class."""

    def __init__(self, service) -> None:
        self.service = service

    def __getattr__(self, name):
        return getattr(self.service, name)

    async def run(self, *args, **kwargs):
        return await BulkSceneEntityExtractionMixin._process_scenes_bulk(
            self.service,
            *args,
            **kwargs,
        )

    async def supplement_small_sample(self, *args, **kwargs):
        return await BulkSceneEntityExtractionMixin._supplement_small_sample_entities(
            self.service,
            *args,
            **kwargs,
        )

    async def supplement_with_llm(self, *args, **kwargs):
        return await (
            BulkSceneEntityExtractionMixin._supplement_small_sample_entities_with_llm(
                self.service,
                *args,
                **kwargs,
            )
        )

    async def call_bulk_llm_extractions(self, *args, **kwargs):
        return await BulkSceneEntityExtractionMixin._call_bulk_llm_extractions(
            self.service,
            *args,
            **kwargs,
        )
