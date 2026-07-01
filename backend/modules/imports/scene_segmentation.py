"""
SceneSegmentationService — Phase 1: 章节正文 → Scene 切分

注意: 本模块通过 outline.facade 操作 Scene, 不直接 import outline.models。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.llm.errors import (
    LLMConnectionError,
    LLMRateLimitError,
    LLMTimeoutError,
)
from modules.imports.llm_schemas import SceneSegmentationOutput
from shared.utils import parse_llm_json

logger = logging.getLogger(__name__)

BATCH_SIZE = 5
OVERLAP = 1
MAX_BATCH_CHARS = 12_000
LLM_CALL_TIMEOUT_SECONDS = 60


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
            "Scene segmentation: %d chapters → %d batches "
            "(batch_size=%d, overlap=%d, max_batch_chars=%d)",
            len(chapters),
            total_batches,
            BATCH_SIZE,
            OVERLAP,
            MAX_BATCH_CHARS,
        )

        next_scene_index = await get_next_scene_index(db, novel_id)
        added_count = 0
        failed_batches: list[int] = []
        degraded = False

        if on_batch_progress is not None:
            await on_batch_progress(0, total_batches)

        for batch_idx, batch in enumerate(batches):
            output_chapters = self._output_chapters_for_batch(batch, batch_idx)
            overlap_chapter_indices = self._overlap_chapter_indices(batch, batch_idx)
            try:
                batch_scenes = await self._process_batch(db, batch, batch_idx)
                for s in batch_scenes:
                    scene_data = self._build_scene_data(
                        s,
                        next_scene_index,
                        batch,
                        output_chapters=output_chapters,
                        overlap_chapter_indices=overlap_chapter_indices,
                    )
                    if scene_data is None:
                        continue
                    await create_scene(db, novel_id, scene_data)
                    next_scene_index += 1
                    added_count += 1
            except Exception as exc:
                logger.warning("Batch %d failed: %s", batch_idx, exc)
                degraded = True
                if batch_idx not in failed_batches:
                    failed_batches.append(batch_idx)
                if self._should_skip_llm_fallback(exc):
                    next_scene_index, created = await self._create_mechanical_scenes(
                        db,
                        create_scene,
                        novel_id,
                        output_chapters,
                        next_scene_index,
                    )
                    added_count += created
                    logger.info(
                        "Batch %d: transport failure, "
                        "mechanical fallback created %d scenes",
                        batch_idx,
                        created,
                    )
                else:
                    try:
                        fallback_scenes = await self._process_batch_single_chapter(
                            db,
                            batch,
                            batch_idx,
                        )
                        for s in fallback_scenes:
                            scene_data = self._build_scene_data(
                                s,
                                next_scene_index,
                                batch,
                                output_chapters=output_chapters,
                                overlap_chapter_indices=overlap_chapter_indices,
                            )
                            if scene_data is None:
                                continue
                            await create_scene(db, novel_id, scene_data)
                            next_scene_index += 1
                            added_count += 1
                    except Exception as fb_exc:
                        logger.error(
                            "Batch %d fallback also failed: %s",
                            batch_idx,
                            fb_exc,
                        )
                        next_scene_index, created = await self._create_mechanical_scenes(
                            db,
                            create_scene,
                            novel_id,
                            output_chapters,
                            next_scene_index,
                        )
                        added_count += created
                        logger.info(
                            "Batch %d: mechanical fallback, created %d scenes",
                            batch_idx,
                            created,
                        )

            if on_batch_progress is not None:
                await on_batch_progress(batch_idx + 1, total_batches)

        return {
            "total_scenes": added_count,
            "failed_batches": failed_batches,
            "degraded": degraded,
        }

    @staticmethod
    def _should_skip_llm_fallback(exc: Exception) -> bool:
        return isinstance(exc, (LLMConnectionError, LLMTimeoutError, LLMRateLimitError))

    @staticmethod
    async def _create_mechanical_scenes(
        db: AsyncSession,
        create_scene: Any,
        novel_id: str,
        output_chapters: list[dict],
        next_scene_index: int,
    ) -> tuple[int, int]:
        created = 0
        for ch in output_chapters:
            mech_data = {
                "scene_index": next_scene_index,
                "title": ch.get("title") or f"第{ch['chapter_index']}章",
                "goal": "",
                "core_conflict": "",
                "emotional_beat": "",
                "must_happen": "",
                "must_not_happen": "",
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
            created += 1
        return next_scene_index, created

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
            batch: list[dict] = []
            batch_chars = 0
            j = i
            while j < len(chapters) and len(batch) < BATCH_SIZE:
                chapter = chapters[j]
                chapter_chars = len(chapter.get("content") or "")
                would_exceed = (
                    MAX_BATCH_CHARS > 0
                    and bool(batch)
                    and batch_chars + chapter_chars > MAX_BATCH_CHARS
                )
                if would_exceed:
                    break
                batch.append(chapter)
                batch_chars += chapter_chars
                j += 1

            if not batch:
                batch = [chapters[i]]
            batches.append(batch)
            if i + len(batch) >= len(chapters):
                break
            advance = len(batch) - OVERLAP
            i += max(1, advance)
        return batches

    @staticmethod
    def _output_chapters_for_batch(batch: list[dict], batch_idx: int) -> list[dict]:
        if batch_idx == 0 or OVERLAP <= 0:
            return batch
        return batch[OVERLAP:] or batch

    @staticmethod
    def _overlap_chapter_indices(batch: list[dict], batch_idx: int) -> set[int]:
        if batch_idx == 0 or OVERLAP <= 0:
            return set()
        return {
            int(ch["chapter_index"])
            for ch in batch[:OVERLAP]
            if ch.get("chapter_index") is not None
        }

    async def _get_next_scene_index(self, db: AsyncSession, nid) -> int:
        from modules.outline.facade import get_next_scene_index

        return await get_next_scene_index(db, str(nid))

    @staticmethod
    def _build_scene_data(
        scene_data: dict,
        scene_index: int,
        batch: list[dict],
        *,
        output_chapters: list[dict] | None = None,
        overlap_chapter_indices: set[int] | None = None,
    ) -> dict[str, Any] | None:
        """将 LLM 输出的 scene 数据构建为 Scene 创建参数字典"""
        batch_chapter_indices = {
            int(ch["chapter_index"])
            for ch in batch
            if ch.get("chapter_index") is not None
        }
        output_chapters = output_chapters if output_chapters is not None else batch
        output_chapter_indices = {
            int(ch["chapter_index"])
            for ch in output_chapters
            if ch.get("chapter_index") is not None
        }
        overlap_chapter_indices = overlap_chapter_indices or set()

        scene_chunks = []
        chapter_ids: list[str] = []
        for chunk in scene_data.get("scene_chunks", []) or []:
            ch_idx = chunk.get("chapter_index")
            try:
                normalized_idx = int(ch_idx)
            except (TypeError, ValueError):
                continue
            if normalized_idx not in batch_chapter_indices:
                continue
            scene_chunks.append({**chunk, "chapter_index": normalized_idx})
            chapter_ids.append(str(normalized_idx))

        if not chapter_ids:
            first_ch = output_chapters[0] if output_chapters else {}
            if first_ch:
                chapter_ids.append(str(first_ch.get("chapter_index", "")))
                scene_chunks = [
                    {
                        "chapter_index": first_ch.get("chapter_index"),
                        "start_paragraph": 0,
                    }
                ]

        unique_chapter_ids = list(dict.fromkeys(chapter_ids))
        try:
            referenced_indices = {int(ch_id) for ch_id in unique_chapter_ids}
        except ValueError:
            referenced_indices = set()
        if (
            referenced_indices
            and referenced_indices.issubset(overlap_chapter_indices)
            and not referenced_indices.intersection(output_chapter_indices)
        ):
            logger.info(
                "Skipping overlap-only scene from later batch: %s",
                scene_data.get("title"),
            )
            return None

        return {
            "scene_index": scene_index,
            "title": scene_data.get("title"),
            "goal": scene_data.get("goal"),
            "core_conflict": scene_data.get("core_conflict"),
            "emotional_beat": scene_data.get("emotional_beat"),
            "narrative_tag": scene_data.get("narrative_tag", "draft"),
            "source": "deep_import",
            "scene_chunks": scene_chunks,
            "chapter_ids": unique_chapter_ids,
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
            max_tokens=4096,
            response_format={"type": "json_object"},
        )

        llm_client = LLMClient(timeout=settings.llm_timeout)
        raw = await self._generate_with_timeout(
            llm_client,
            request,
            timeout_seconds=LLM_CALL_TIMEOUT_SECONDS,
        )
        parsed = parse_llm_json(raw.content, f"Batch {batch_idx} LLM response")
        output = SceneSegmentationOutput.model_validate(parsed)
        scenes_data = [s.model_dump() for s in output.scenes]
        if not scenes_data:
            raise ValueError("LLM returned empty scenes list")
        return scenes_data

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

            llm_client = LLMClient(timeout=settings.llm_timeout)
            try:
                raw = await self._generate_with_timeout(
                    llm_client,
                    request,
                    timeout_seconds=LLM_CALL_TIMEOUT_SECONDS,
                )
                parsed = parse_llm_json(
                    raw.content,
                    f"Single-ch {ch['chapter_index']}",
                )
                output = SceneSegmentationOutput.model_validate(parsed)
                scenes = [s.model_dump() for s in output.scenes]
                if scenes:
                    all_scenes.extend(scenes)
                    continue
            except Exception as exc:
                logger.warning(
                    "Single-chapter fallback batch %d ch %d failed: %s",
                    batch_idx,
                    ch["chapter_index"],
                    exc,
                )
                raise RuntimeError(
                    f"Single-chapter fallback failed for ch {ch['chapter_index']}"
                )
            raise RuntimeError(
                f"Single-chapter fallback returned no scenes for ch {ch['chapter_index']}"
            )
        return all_scenes

    @staticmethod
    async def _generate_with_timeout(
        llm_client: Any,
        request: Any,
        *,
        timeout_seconds: float,
    ) -> Any:
        try:
            return await asyncio.wait_for(
                llm_client.generate(request),
                timeout=timeout_seconds,
            )
        except TimeoutError as exc:
            provider = getattr(llm_client, "provider", "")
            raise LLMTimeoutError(
                "Scene segmentation LLM call timed out",
                provider=provider,
                model=getattr(request, "model", ""),
                timeout=int(timeout_seconds),
            ) from exc

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
