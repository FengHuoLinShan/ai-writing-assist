"""SceneEntityExtractionService -- Phase 2: 按 Scene 串行增量提取实体、关系与 Delta。"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.llm.errors import (
    LLMConnectionError,
    LLMRateLimitError,
    LLMTimeoutError,
)
from modules.imports.llm_schemas import (
    DeltaEvent,
    ExtractedEntity,
    ExtractedRelation,
    SceneEntityExtractionOutput,
)
from shared.utils import parse_llm_json, parse_uuid

logger = logging.getLogger(__name__)

class SceneEntityExtractionService:
    """Phase 2: 按 Scene 顺序串行提取实体，累积 Memory 上下文。"""

    async def extract_by_scenes(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        workflow_id: str | None = None,
        on_scene_progress: Callable[[int, int], Awaitable[None]] | None = None,
    ) -> dict[str, Any]:
        nid = parse_uuid(novel_id, "novel_id")

        scenes = await self._get_scenes(db, nid)
        if not scenes:
            return {
                "total_created": 0,
                "total_relations": 0,
                "total_deltas": 0,
                "total_scenes": 0,
                "degraded": False,
                "error_kind": None,
                "error_message": None,
                "failed_scene_indices": [],
                "completed_scenes": 0,
                "skipped_scenes": 0,
                "stopped_early": False,
            }

        from modules.world.facade import get_world_context

        ctx = await get_world_context(
            db,
            novel_id,
            reveal_mode="author_safe",
            limit=500,
        )
        existing_context = (
            "\n".join(
                f"- {e.name} ({e.entity_type})"
                for e in ctx.entities
                if e.status in ("canonical", "draft")
            )
            or "无已有对象"
        )

        total_created = 0
        total_relations = 0
        total_deltas = 0
        total_scenes = len(scenes)
        accumulated_memory: list[dict] = []
        seen_entity_keys: set[tuple[str, str]] = set()
        failed_scene_indices: list[int] = []
        completed_scenes = 0
        skipped_scenes = 0
        stopped_early = False
        error_kind: str | None = None
        error_message: str | None = None

        if on_scene_progress is not None:
            await on_scene_progress(0, total_scenes)

        for scene_idx, scene in enumerate(scenes):
            try:
                scene_result = await self._process_scene(
                    db,
                    nid,
                    scene,
                    scene_idx,
                    existing_context,
                    accumulated_memory,
                    seen_entity_keys,
                    workflow_id=workflow_id,
                )
                total_created += scene_result["created"]
                total_relations += scene_result["relations"]
                total_deltas += scene_result["deltas"]
                existing_context = scene_result["updated_context"]
                accumulated_memory = scene_result["updated_memory"]
                completed_scenes += 1
            except Exception as exc:
                scene_index_value = (
                    scene.get("scene_index")
                    if isinstance(scene, dict)
                    else getattr(scene, "scene_index", scene_idx)
                )
                failed_scene_indices.append(scene_index_value)
                error_kind = self._error_kind(exc)
                error_message = str(exc)[:300]
                logger.warning(
                    "Scene idx=%d scene_index=%r extraction failed: %s",
                    scene_idx,
                    scene_index_value,
                    exc,
                )
                if self._is_transport_failure(exc):
                    logger.warning(
                        "Stopping scene entity extraction after transport failure; "
                        "remaining scenes will be skipped."
                    )
                    stopped_early = True
                    skipped_scenes = total_scenes - scene_idx - 1
                    break
                continue

            if on_scene_progress is not None:
                await on_scene_progress(scene_idx + 1, total_scenes)

        await db.flush()
        return {
            "total_created": total_created,
            "total_relations": total_relations,
            "total_deltas": total_deltas,
            "total_scenes": total_scenes,
            "degraded": bool(failed_scene_indices or stopped_early),
            "error_kind": error_kind,
            "error_message": error_message,
            "failed_scene_indices": failed_scene_indices,
            "completed_scenes": completed_scenes,
            "skipped_scenes": skipped_scenes,
            "stopped_early": stopped_early,
        }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _is_transport_failure(exc: Exception) -> bool:
        return isinstance(exc, (LLMConnectionError, LLMTimeoutError, LLMRateLimitError))

    @staticmethod
    def _error_kind(exc: Exception) -> str:
        if isinstance(exc, LLMConnectionError):
            return "connection_error"
        if isinstance(exc, LLMTimeoutError):
            return "timeout"
        if isinstance(exc, LLMRateLimitError):
            return "rate_limit"
        return exc.__class__.__name__

    async def _get_scenes(self, db: AsyncSession, nid) -> list[dict[str, Any]]:
        from modules.outline.facade import get_scenes_by_novel

        return await get_scenes_by_novel(
            db,
            str(nid),
            status_filter=["draft", "canonical"],
            exclude_narrative_tags=["valley", "transition"],
        )

    async def _process_scene(
        self,
        db: AsyncSession,
        nid,
        scene: dict[str, Any],
        scene_idx: int,
        existing_context: str,
        accumulated_memory: list[dict],
        seen_entity_keys: set[tuple[str, str]],
        workflow_id: str | None = None,
    ) -> dict[str, Any]:
        scene_index = scene["scene_index"]
        source_chapter_index = self._scene_source_chapter_index(scene)
        chapters_text = await self._load_scene_chapters(db, scene)
        if not chapters_text:
            return {
                "created": 0,
                "relations": 0,
                "deltas": 0,
                "updated_context": existing_context,
                "updated_memory": accumulated_memory,
            }

        memory_context = self._build_memory_context(accumulated_memory)
        extraction = await self._call_llm_extraction(
            chapters_text,
            existing_context,
            memory_context,
        )

        created_count = await self._persist_entities(
            db,
            nid,
            extraction.entities,
            scene_index=scene_index,
            source_chapter_index=source_chapter_index,
            seen_entity_keys=seen_entity_keys,
            workflow_id=workflow_id,
        )
        relation_count = await self._persist_relations(
            db,
            nid,
            extraction.relations,
            scene_index=scene_index,
            workflow_id=workflow_id,
        )
        delta_count = await self._record_deltas(
            db,
            nid,
            extraction.delta_events,
            scene_index=scene_index,
        )

        new_names = [
            e.name for e in extraction.entities if e.suggested_action == "create_new"
        ]
        new_entities_text = "\n".join(
            f"- {n} ({e.entity_type})"
            for n, e in zip(new_names, extraction.entities)
            if e.suggested_action == "create_new"
        )
        updated_context = (
            existing_context + "\n" + new_entities_text
            if new_entities_text
            else existing_context
        )

        updated_memory = accumulated_memory + [
            {"scene_index": scene_index, "entities": len(extraction.entities)},
        ]

        # 每个 Scene 完成后更新记忆快照
        try:
            from modules.memory.facade import capture_snapshot

            await capture_snapshot(
                db,
                str(nid),
                chapter_index=source_chapter_index,
            )
        except Exception as exc:
            logger.warning(
                "Memory snapshot after scene %d failed: %s",
                scene_index,
                exc,
            )

        return {
            "created": created_count,
            "relations": relation_count,
            "deltas": delta_count,
            "updated_context": updated_context,
            "updated_memory": updated_memory,
        }

    @staticmethod
    def _scene_source_chapter_index(scene: dict[str, Any]) -> int:
        """取 Scene 关联的最大章节号作为来源章节；没有则回退到 scene_index。"""
        chapter_ids = scene.get("chapter_ids") or []
        indices: list[int] = []
        for raw in chapter_ids:
            try:
                indices.append(int(raw))
            except (ValueError, TypeError):
                continue
        return max(indices) if indices else scene.get("scene_index", 0)

    async def _load_scene_chapters(self, db: AsyncSession, scene: dict[str, Any]) -> str:
        from modules.writing.facade import get_latest_draft_for_chapter

        parts: list[str] = []
        for ch_id_str in scene.get("chapter_ids") or []:
            try:
                ch_idx = int(ch_id_str)
            except (ValueError, TypeError):
                continue
            draft = await get_latest_draft_for_chapter(
                db,
                scene["novel_id"],
                ch_idx,
            )
            if draft and draft.content:
                parts.append(f"## 第{ch_idx}章\n\n{draft.content}")
        return "\n\n".join(parts)

    @staticmethod
    def _build_memory_context(memory: list[dict]) -> str:
        if not memory:
            return "无前序 Scene 上下文"
        recent = memory[-5:]
        lines = ["## 前序 Scene 摘要"]
        for m in recent:
            lines.append(f"- Scene {m['scene_index']}: 包含 {m['entities']} 个实体")
        return "\n".join(lines)

    async def _call_llm_extraction(
        self,
        chapters_text: str,
        existing_context: str,
        memory_context: str,
    ) -> SceneEntityExtractionOutput:
        from core.config import get_settings
        from infrastructure.llm.client import LLMClient
        from infrastructure.llm.prompt_loader import load_prompt
        from infrastructure.llm.schemas import LLMCallRequest, LLMMessage

        system_prompt = load_prompt(
            "scene_entity_extraction",
            existing_entities_context=existing_context,
        )
        system_prompt += f"\n\n## 前序上下文\n\n{memory_context}"

        settings = get_settings()
        request = LLMCallRequest(
            model=settings.llm_model,
            messages=[
                LLMMessage(role="system", content=system_prompt),
                LLMMessage(
                    role="user",
                    content=f"请从以下正文中提取世界对象。\n\n{chapters_text}",
                ),
            ],
            temperature=0.3,
            max_tokens=16384,
            response_format={"type": "json_object"},
        )

        llm_client = LLMClient(timeout=180)
        raw = await llm_client.generate(request)
        parsed = parse_llm_json(raw.content, "Entity extraction")
        return SceneEntityExtractionOutput.model_validate(parsed)

    async def _persist_entities(
        self,
        db: AsyncSession,
        nid,
        entities: list[ExtractedEntity],
        scene_index: int,
        source_chapter_index: int,
        seen_entity_keys: set[tuple[str, str]] | None = None,
        workflow_id: str | None = None,
    ) -> int:
        from modules.world.facade import create_entity, find_similar_entities

        created = 0
        seen_entity_keys = seen_entity_keys if seen_entity_keys is not None else set()

        for ent in entities:
            action = ent.suggested_action
            if action == "ignore":
                continue

            if not ent.name:
                continue

            entity_key = self._entity_key(ent.entity_type, ent.name)
            if entity_key in seen_entity_keys:
                continue

            if action == "create_new":
                similar = await find_similar_entities(db, str(nid), ent.name)
                if similar and similar.get("score", 0) >= 0.88:
                    seen_entity_keys.add(entity_key)
                    continue

            content_json: dict[str, Any] = {
                "_meta": {
                    "auto_ingested": True,
                    "source_scene_index": scene_index,
                    "source_chapter_index": source_chapter_index,
                    "ingested_at": datetime.now(UTC).isoformat(),
                    "batch_id": workflow_id or "",
                    "suggested_action": action,
                    "suggested_existing_entity_name": (
                        ent.suggested_existing_entity_name
                    ),
                    "candidate_reason": ent.candidate_reason,
                    "confidence": ent.confidence,
                },
                "aliases": ent.aliases or [],
            }
            if action == "temporary_only":
                content_json["_meta"]["temporary"] = True
            entity_payload = {
                "name": ent.name,
                "entity_type": ent.entity_type,
                "summary": ent.summary or None,
                "public_info": ent.public_info or None,
                "hidden_truth": ent.hidden_truth or None,
                "importance": ent.importance,
                "content_json": content_json,
                "status": "candidate",
                "created_by": "ai_import",
            }
            try:
                async with db.begin_nested():
                    await create_entity(db, str(nid), entity_payload)
                created += 1
                seen_entity_keys.add(entity_key)
            except Exception as exc:
                logger.warning(
                    "Failed to create entity '%s': %s",
                    ent.name,
                    exc,
                )

        return created

    @staticmethod
    def _entity_key(entity_type: str, name: str) -> tuple[str, str]:
        return (entity_type.strip().lower(), " ".join(name.strip().lower().split()))

    async def _persist_relations(
        self,
        db: AsyncSession,
        nid,
        relations: list[ExtractedRelation],
        scene_index: int,
        workflow_id: str | None = None,
    ) -> int:
        from modules.world.facade import create_relation, find_entity_id_by_name

        created = 0
        for rel in relations:
            source_id = await find_entity_id_by_name(db, str(nid), rel.source_name)
            target_id = await find_entity_id_by_name(db, str(nid), rel.target_name)
            if not source_id or not target_id:
                logger.debug(
                    "Skipping relation %s -> %s: entity not found",
                    rel.source_name,
                    rel.target_name,
                )
                continue
            try:
                await create_relation(
                    db,
                    str(nid),
                    {
                        "source_id": source_id,
                        "target_id": target_id,
                        "relation_type": rel.relation_type,
                        "description": rel.description,
                        "quote": rel.quote,
                        "strength": rel.strength,
                        "status": "candidate",
                    },
                )
                created += 1
            except Exception as exc:
                logger.warning(
                    "Failed to create relation %s -> %s: %s",
                    rel.source_name,
                    rel.target_name,
                    exc,
                )
        return created

    async def _record_deltas(
        self,
        db: AsyncSession,
        nid,
        delta_events: list[DeltaEvent],
        scene_index: int,
    ) -> int:
        from modules.memory.facade import create_delta_log

        count = 0
        for event in delta_events or []:
            await create_delta_log(
                db,
                str(nid),
                scene_index=scene_index,
                category=event.category,
                field_path=event.field,
                old_value=json.dumps(event.old) if event.old is not None else None,
                new_value=json.dumps(event.new) if event.new is not None else None,
                source="ai_extraction",
                meta=event.meta,
            )
            count += 1
        return count
