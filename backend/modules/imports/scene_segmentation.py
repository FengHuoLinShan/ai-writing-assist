"""
SceneSegmentationService — Phase 1: 章节正文 → Scene 切分

注意: 本模块通过 outline.facade 操作 Scene, 不直接 import outline.models。
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from shared.utils import parse_llm_json

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
        on_batch_progress: Callable[[int, int], Awaitable[None]] | None = None,
    ) -> dict[str, Any]:
        """切分章节范围 → Scene，写入 scenes 表"""
        from modules.outline.facade import create_scene, get_next_scene_index

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

        next_scene_index = await get_next_scene_index(db, novel_id)
        added_count = 0
        failed_batches: list[int] = []
        degraded = False

        if on_batch_progress is not None:
            await on_batch_progress(0, total_batches)

        for batch_idx, batch in enumerate(batches):
            try:
                batch_scenes = await self._process_batch(db, batch, batch_idx)
                for s in batch_scenes:
                    scene_data = self._build_scene_data(s, next_scene_index, batch)
                    await create_scene(db, novel_id, scene_data)
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
                        scene_data = self._build_scene_data(
                            s, next_scene_index, batch
                        )
                        await create_scene(db, novel_id, scene_data)
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
                        mech_data = {
                            "scene_index": next_scene_index,
                            "title": ch.get("title")
                            or f"第{ch['chapter_index']}章",
                            "narrative_tag": "draft",
                            "source": "deep_import",
                            "scene_chunks": [
                                {
                                    "chapter_index": ch["chapter_index"],
                                    "start_paragraph": 0,
                                }
                            ],
                            "chapter_ids": [str(ch["chapter_index"])],
                            "status": "draft",
                        }
                        await create_scene(db, novel_id, mech_data)
                        next_scene_index += 1
                        added_count += 1
                    logger.info(
                        "Batch %d: mechanical fallback, created %d scenes",
                        batch_idx,
                        len(batch),
                    )

            if on_batch_progress is not None:
                await on_batch_progress(batch_idx + 1, total_batches)

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
        from modules.outline.facade import get_next_scene_index

        return await get_next_scene_index(db, str(nid))

    @staticmethod
    def _build_scene_data(
        scene_data: dict,
        scene_index: int,
        batch: list[dict],
    ) -> dict[str, Any]:
        """将 LLM 输出的 scene 数据构建为 Scene 创建参数字典"""
        scene_chunks = scene_data.get("scene_chunks", [])
        chapter_ids: list[str] = []
        for chunk in scene_chunks:
            ch_idx = chunk.get("chapter_index")
            if ch_idx is not None:
                chapter_ids.append(str(ch_idx))

        if not chapter_ids:
            first_ch = batch[0] if batch else {}
            if first_ch:
                chapter_ids.append(str(first_ch.get("chapter_index", "")))

        return {
            "scene_index": scene_index,
            "title": scene_data.get("title"),
            "goal": scene_data.get("goal"),
            "core_conflict": scene_data.get("core_conflict"),
            "emotional_beat": scene_data.get("emotional_beat"),
            "narrative_tag": scene_data.get("narrative_tag", "draft"),
            "source": "deep_import",
            "scene_chunks": scene_chunks,
            "chapter_ids": chapter_ids,
            "status": "draft",
        }

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
            max_tokens=16384,
            response_format={"type": "json_object"},
        )

        llm_client = LLMClient(timeout=180)
        last_error: Exception | None = None

        for attempt in range(MAX_LLM_RETRIES):
            try:
                raw = await llm_client.generate(request)
                parsed = parse_llm_json(raw.content, f"Batch {batch_idx} LLM response")
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
                max_tokens=4096,
            )

            llm_client = LLMClient(timeout=120)
            for attempt in range(MAX_LLM_RETRIES):
                try:
                    raw = await llm_client.generate(request)
                    parsed = parse_llm_json(
                        raw.content,
                        f"Single-ch {ch['chapter_index']}",
                    )
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
