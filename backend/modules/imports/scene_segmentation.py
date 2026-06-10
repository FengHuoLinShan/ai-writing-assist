"""SceneSegmentationService — Phase 1: 章节正文 → Scene 切分"""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.outline.models import Scene
from shared.utils import parse_uuid

logger = logging.getLogger(__name__)

BATCH_SIZE = 5
OVERLAP = 1
MAX_LLM_RETRIES = 3


class SceneSegmentationService:
    """Phase 1: 将章节正文按 5 章/批 + 1 章 Overlap 切分为 Scene"""

    async def segment_chapters(
        self,
        db: AsyncSession,
        novel_id: str,
        start_chapter: int,
        end_chapter: int,
    ) -> dict[str, Any]:
        """切分章节范围 → Scene，写入 scenes 表"""
        nid = parse_uuid(novel_id, "novel_id")

        chapters = await self._load_chapters(db, novel_id, start_chapter, end_chapter)
        if not chapters:
            return {"total_scenes": 0, "failed_batches": [], "degraded": False}

        batches = self._split_into_batches(chapters)
        total_batches = len(batches)
        logger.info(
            "Scene segmentation: %d chapters → %d batches (batch_size=%d, overlap=%d)",
            len(chapters),
            total_batches,
            BATCH_SIZE,
            OVERLAP,
        )

        next_scene_index = await self._get_next_scene_index(db, nid)
        added_count = 0
        failed_batches: list[int] = []
        degraded = False

        for batch_idx, batch in enumerate(batches):
            try:
                batch_scenes = await self._process_batch(db, batch, batch_idx)
                for s in batch_scenes:
                    scene = self._build_scene(db, nid, s, next_scene_index, batch)
                    db.add(scene)
                    next_scene_index += 1
                    added_count += 1
            except Exception as exc:
                logger.warning("Batch %d failed: %s", batch_idx, exc)
                degraded = True
                try:
                    fallback_scenes = await self._process_batch_single_chapter(
                        db,
                        batch,
                        batch_idx,
                    )
                    for s in fallback_scenes:
                        scene = self._build_scene(db, nid, s, next_scene_index, batch)
                        db.add(scene)
                        next_scene_index += 1
                        added_count += 1
                except Exception as fb_exc:
                    logger.error(
                        "Batch %d fallback also failed: %s",
                        batch_idx,
                        fb_exc,
                    )
                    failed_batches.append(batch_idx)
                    for ch in batch:
                        scene = Scene(
                            novel_id=nid,
                            scene_index=next_scene_index,
                            title=ch.get("title") or f"第{ch['chapter_index']}章",
                            narrative_tag="draft",
                            source="deep_import",
                            scene_chunks=[
                                {
                                    "chapter_index": ch["chapter_index"],
                                    "start_paragraph": 0,
                                }
                            ],
                            chapter_ids=[str(ch["chapter_index"])],
                            status="draft",
                        )
                        db.add(scene)
                        next_scene_index += 1
                        added_count += 1
                    logger.info(
                        "Batch %d: mechanical fallback, created %d scenes",
                        batch_idx,
                        len(batch),
                    )

        await db.flush()
        return {
            "total_scenes": added_count,
            "failed_batches": failed_batches,
            "degraded": degraded,
        }

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    async def _load_chapters(
        self,
        db: AsyncSession,
        novel_id: str,
        start: int,
        end: int,
    ) -> list[dict]:
        from modules.writing.facade import get_latest_draft_for_chapter

        chapters: list[dict] = []
        for idx in range(start, end + 1):
            draft = await get_latest_draft_for_chapter(db, novel_id, idx)
            if draft and draft.content:
                chapters.append(
                    {
                        "chapter_index": idx,
                        "title": draft.title or f"第{idx}章",
                        "content": draft.content,
                    }
                )
        return chapters

    def _split_into_batches(self, chapters: list[dict]) -> list[list[dict]]:
        batches: list[list[dict]] = []
        i = 0
        while i < len(chapters):
            batch = chapters[i : i + BATCH_SIZE]
            batches.append(batch)
            i += BATCH_SIZE - OVERLAP
        return batches

    async def _get_next_scene_index(self, db: AsyncSession, nid) -> int:
        stmt = select(func.coalesce(func.max(Scene.scene_index), -1)).where(
            Scene.novel_id == nid,
        )
        result = await db.execute(stmt)
        max_idx = result.scalar() or -1
        return max_idx + 1

    def _build_scene(
        self,
        db: AsyncSession,
        nid,
        scene_data: dict,
        scene_index: int,
        batch: list[dict],
    ) -> Scene:
        """将 LLM 输出的 scene 数据构建为 Scene ORM 对象"""
        scene_chunks = scene_data.get("scene_chunks", [])
        chapter_ids: list[str] = []
        for chunk in scene_chunks:
            ch_idx = chunk.get("chapter_index")
            if ch_idx is not None:
                chapter_ids.append(str(ch_idx))

        # If no chapter_ids from chunks, derive from batch
        if not chapter_ids:
            first_ch = batch[0] if batch else {}
            if first_ch:
                chapter_ids.append(str(first_ch.get("chapter_index", "")))

        return Scene(
            novel_id=nid,
            scene_index=scene_index,
            title=scene_data.get("title"),
            goal=scene_data.get("goal"),
            core_conflict=scene_data.get("core_conflict"),
            emotional_beat=scene_data.get("emotional_beat"),
            narrative_tag=scene_data.get("narrative_tag", "draft"),
            source="deep_import",
            scene_chunks=scene_chunks,
            chapter_ids=chapter_ids,
            status="draft",
        )

    async def _process_batch(
        self,
        db: AsyncSession,
        batch: list[dict],
        batch_idx: int,
    ) -> list[dict]:
        chapters_text = self._build_chapters_text(batch)
        system_prompt = self._load_prompt()

        from core.config import get_settings
        from infrastructure.llm.client import LLMClient
        from infrastructure.llm.schemas import LLMCallRequest, LLMMessage

        settings = get_settings()
        request = LLMCallRequest(
            model=settings.llm_model,
            messages=[
                LLMMessage(role="system", content=system_prompt),
                LLMMessage(
                    role="user",
                    content=f"请将以下章节正文切分为叙事 Scene。\n\n{chapters_text}",
                ),
            ],
            temperature=0.3,
            response_format={"type": "json_object"},
        )

        llm_client = LLMClient()
        last_error: Exception | None = None

        for attempt in range(MAX_LLM_RETRIES):
            try:
                raw = await llm_client.generate(request)
                parsed = json.loads(raw.content)
                scenes_data = parsed.get("scenes", [])
                if not scenes_data:
                    raise ValueError("LLM returned empty scenes list")
                return scenes_data
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "Batch %d LLM attempt %d/%d failed: %s",
                    batch_idx,
                    attempt + 1,
                    MAX_LLM_RETRIES,
                    exc,
                )

        raise last_error or RuntimeError("All LLM retries exhausted")

    async def _process_batch_single_chapter(
        self,
        db: AsyncSession,
        batch: list[dict],
        batch_idx: int,
    ) -> list[dict]:
        all_scenes: list[dict] = []
        for ch in batch:
            chapters_text = self._build_chapters_text([ch])
            system_prompt = self._load_prompt()

            from core.config import get_settings
            from infrastructure.llm.client import LLMClient
            from infrastructure.llm.schemas import LLMCallRequest, LLMMessage

            settings = get_settings()
            request = LLMCallRequest(
                model=settings.llm_model,
                messages=[
                    LLMMessage(role="system", content=system_prompt),
                    LLMMessage(
                        role="user",
                        content=f"请将以下章节正文切分为叙事 Scene。\n\n{chapters_text}",
                    ),
                ],
                temperature=0.3,
                response_format={"type": "json_object"},
            )

            llm_client = LLMClient()
            for attempt in range(MAX_LLM_RETRIES):
                try:
                    raw = await llm_client.generate(request)
                    parsed = json.loads(raw.content)
                    scenes = parsed.get("scenes", [])
                    if scenes:
                        all_scenes.extend(scenes)
                        break
                except Exception as exc:
                    logger.warning(
                        "Single-chapter batch %d ch %d attempt %d failed: %s",
                        batch_idx,
                        ch["chapter_index"],
                        attempt + 1,
                        exc,
                    )
            else:
                raise RuntimeError(
                    f"Single-chapter fallback failed for ch {ch['chapter_index']}"
                )
        return all_scenes

    @staticmethod
    def _build_chapters_text(chapters: list[dict]) -> str:
        parts: list[str] = []
        for ch in chapters:
            title = ch.get("title") or f"第{ch['chapter_index']}章"
            parts.append(
                f"## 第{ch['chapter_index']}章 {title}\n\n{ch.get('content', '')}"
            )
        return "\n\n".join(parts)

    @staticmethod
    def _load_prompt() -> str:
        from infrastructure.llm.prompt_loader import load_prompt

        return load_prompt("scene_segmentation")
