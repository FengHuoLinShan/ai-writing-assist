"""SceneEntityExtractionService -- Phase 2: 按 Scene 串行增量提取实体"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from shared.utils import parse_llm_json, parse_uuid

logger = logging.getLogger(__name__)

MAX_RETRIES = 3


class SceneEntityExtractionService:
    """Phase 2: 按 Scene 顺序串行提取实体，累积 Memory 上下文"""

    async def extract_by_scenes(
        self,
        db: AsyncSession,
        novel_id: str,
        on_scene_progress: Callable[[int, int], Awaitable[None]] | None = None,
    ) -> dict[str, Any]:
        nid = parse_uuid(novel_id, "novel_id")

        scenes = await self._get_scenes(db, nid)
        if not scenes:
            return {"total_created": 0, "total_deltas": 0}

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
        total_deltas = 0
        total_scenes = len(scenes)
        accumulated_memory: list[dict] = []

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
                )
                total_created += scene_result["created"]
                total_deltas += scene_result["deltas"]
                existing_context = scene_result["updated_context"]
                accumulated_memory = scene_result["updated_memory"]
            except Exception as exc:
                logger.warning(
                    "Scene %d (idx=%d) extraction failed after %d retries: %s",
                    scene_idx,
                    scene.get("scene_index"),
                    MAX_RETRIES,
                    exc,
                )
                continue

            if on_scene_progress is not None:
                await on_scene_progress(scene_idx + 1, total_scenes)

        await db.flush()
        return {
            "total_created": total_created,
            "total_deltas": total_deltas,
            "total_scenes": total_scenes,
        }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

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
    ) -> dict[str, Any]:
        scene_index = scene["scene_index"]
        chapters_text = await self._load_scene_chapters(db, scene)
        if not chapters_text:
            return {
                "created": 0,
                "deltas": 0,
                "updated_context": existing_context,
                "updated_memory": accumulated_memory,
            }

        memory_context = self._build_memory_context(accumulated_memory)
        entities, delta_events = await self._call_llm_extraction(
            chapters_text,
            existing_context,
            memory_context,
        )

        created_count = await self._persist_entities(
            db, nid, entities, scene_index
        )
        delta_count = await self._record_deltas(
            db, nid, delta_events, scene_index
        )

        new_names = [
            e.get("name", "")
            for e in entities
            if e.get("suggested_action") == "create_new"
        ]
        new_entities_text = "\n".join(
            f"- {n} ({e.get('entity_type', '?')})"
            for n, e in zip(new_names, entities)
            if e.get("suggested_action") == "create_new"
        )
        updated_context = (
            existing_context + "\n" + new_entities_text
            if new_entities_text
            else existing_context
        )

        updated_memory = accumulated_memory + [
            {"scene_index": scene_index, "entities": len(entities)},
        ]

        # Memory snapshot every 10 scenes
        if scene_idx > 0 and scene_idx % 10 == 0:
            try:
                from core.container import get as _get

                await _get("memory.capture_snapshot")(
                    db,
                    novel_id=str(nid),
                    chapter_index=scene_index,
                )
            except Exception as exc:
                logger.warning(
                    "Memory snapshot at scene %d failed: %s",
                    scene_idx,
                    exc,
                )

        return {
            "created": created_count,
            "deltas": delta_count,
            "updated_context": updated_context,
            "updated_memory": updated_memory,
        }

    async def _load_scene_chapters(
        self, db: AsyncSession, scene: dict[str, Any]
    ) -> str:
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
    ) -> tuple[list[dict], list[dict]]:
        from core.config import get_settings
        from infrastructure.llm.client import LLMClient
        from infrastructure.llm.prompt_loader import load_prompt
        from infrastructure.llm.schemas import LLMCallRequest, LLMMessage

        system_prompt = load_prompt(
            "structure_extraction",
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
        for attempt in range(MAX_RETRIES):
            try:
                raw = await llm_client.generate(request)
                parsed = parse_llm_json(raw.content, "Entity extraction")
                return (
                    parsed.get("entities", []),
                    parsed.get("delta_events", []),
                )
            except Exception as exc:
                logger.warning(
                    "LLM extraction attempt %d/%d failed: %s",
                    attempt + 1,
                    MAX_RETRIES,
                    exc,
                )

        return [], []

    async def _persist_entities(
        self,
        db: AsyncSession,
        nid,
        entities: list[dict],
        scene_index: int,
    ) -> int:
        from modules.world.facade import create_entity, find_similar_entities

        created = 0

        for ent in entities:
            action = ent.get("suggested_action", "ignore")
            if action in ("ignore", "temporary_only", "link_to_existing"):
                continue

            name = ent.get("name", "")
            if not name:
                continue

            similar = await find_similar_entities(db, str(nid), name)
            if similar and similar.get("score", 0) >= 0.88:
                continue

            try:
                await create_entity(
                    db,
                    str(nid),
                    {
                        "name": name,
                        "entity_type": ent.get("entity_type", "character"),
                        "summary": ent.get("summary"),
                        "public_info": ent.get("public_info"),
                        "hidden_truth": ent.get("hidden_truth"),
                        "importance": ent.get("importance", 0.5),
                        "status": "canonical",
                    },
                )
                created += 1
            except Exception as exc:
                logger.warning(
                    "Failed to create entity '%s': %s",
                    name,
                    exc,
                )

        return created

    async def _record_deltas(
        self,
        db: AsyncSession,
        nid,
        delta_events: list[dict],
        scene_index: int,
    ) -> int:
        from modules.memory.facade import create_delta_log

        count = 0
        for event in delta_events or []:
            await create_delta_log(
                db,
                str(nid),
                scene_index=scene_index,
                category=event.get("category", "ENTITY_UPDATED"),
                field_path=event.get("field"),
                old_value=json.dumps(event["old"]) if event.get("old") else None,
                new_value=json.dumps(event["new"]) if event.get("new") else None,
                source="ai_extraction",
                meta=event.get("meta", {}),
            )
            count += 1
        return count
