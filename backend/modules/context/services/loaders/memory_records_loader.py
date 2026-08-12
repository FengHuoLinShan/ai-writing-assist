"""长期记忆加载器 — 基于事件溯源全景"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.llm.redaction import redact_diagnostic
from modules.context.contracts import CompileOptions, StructureContextBundle
from modules.context.services.protocol import Loader

logger = logging.getLogger(__name__)

_GetMemoryPanoramaFn = Callable[[AsyncSession, str, int], Awaitable[Any]]
_EnsureSceneCheckpointsFn = Callable[[AsyncSession, str, str], Awaitable[Any]]


async def _default_get_memory_panorama(
    db: AsyncSession,
    novel_id: str,
    chapter_index: int,
) -> Any:
    from modules.memory.facade import get_memory_panorama

    return await get_memory_panorama(db, novel_id, chapter_index)


async def _default_ensure_scene_checkpoints(
    db: AsyncSession,
    novel_id: str,
    scene_id: str,
) -> Any:
    from modules.memory.facade import ensure_scene_checkpoints

    return await ensure_scene_checkpoints(db, novel_id, scene_id)


class MemoryRecordsLoader(Loader):
    """加载长期记忆（世界状态全景）"""

    def __init__(
        self,
        get_memory_panorama_fn: _GetMemoryPanoramaFn = _default_get_memory_panorama,
        ensure_scene_checkpoints_fn: _EnsureSceneCheckpointsFn = (
            _default_ensure_scene_checkpoints
        ),
    ) -> None:
        self._get_memory_panorama = get_memory_panorama_fn
        self._ensure_scene_checkpoints = ensure_scene_checkpoints_fn

    @property
    def name(self) -> str:
        return "memory_records"

    async def load(
        self,
        db: AsyncSession,
        options: CompileOptions,
        bundle: StructureContextBundle,
    ) -> None:
        chapter_index = options.chapter_index if options.chapter_index is not None else 1
        try:
            panorama = await self._get_memory_panorama(
                db,
                options.novel_id,
                chapter_index,
            )
            bundle.memory_records = self._normalize_panorama(
                panorama,
                include_hidden_truth=options.reveal_mode == "author_full",
            )
            bundle.budget_used["memory"] = len(bundle.memory_records)
        except Exception as exc:
            logger.warning(
                "Failed to load memory panorama: %s",
                redact_diagnostic(exc, limit=300),
            )
            bundle.memory_records = []
            bundle.budget_used["memory"] = 0

        if not (
            options.consumer_action == "writing.generate"
            and options.scene_id
            and options.reveal_mode == "character"
        ):
            return
        try:
            checkpoint_set = await self._ensure_scene_checkpoints(
                db,
                options.novel_id,
                options.scene_id,
            )
            bundle.scene_checkpoint_set = (
                checkpoint_set.model_dump()
                if hasattr(checkpoint_set, "model_dump")
                else dict(checkpoint_set)
            )
        except Exception as exc:
            logger.warning(
                "Failed to load Scene memory checkpoints: %s",
                redact_diagnostic(exc, limit=300),
            )
            bundle.scene_checkpoint_set = {
                "coverage_status": "unavailable",
                "items": [],
                "missing_dimensions": [
                    "entities",
                    "relations",
                    "locations",
                    "knowledge",
                    "map",
                ],
            }
            bundle.warnings.append("Scene 时点状态核对失败，本次未用当前世界状态回填过去")

    @staticmethod
    def _normalize_panorama(
        panorama: Any,
        *,
        include_hidden_truth: bool = False,
    ) -> list[dict[str, Any]]:
        data = panorama.model_dump() if hasattr(panorama, "model_dump") else panorama
        if not isinstance(data, dict):
            return []
        chapter_index = data.get("chapter_index")
        records: list[dict[str, Any]] = []

        for item in data.get("entities") or []:
            if not isinstance(item, dict):
                continue
            details = [item.get("summary"), item.get("public_info")]
            if include_hidden_truth:
                details.append(item.get("hidden_truth"))
            records.append(
                {
                    "id": item.get("id"),
                    "memory_type": "人物与对象",
                    "title": item.get("name") or "未命名对象",
                    "summary": "；".join(
                        dict.fromkeys(str(value) for value in details if value)
                    ),
                    "chapter_index": chapter_index,
                }
            )
        for item in data.get("relations") or []:
            if not isinstance(item, dict):
                continue
            records.append(
                {
                    "id": item.get("id"),
                    "memory_type": "关系",
                    "title": item.get("relation_type") or "关系记录",
                    "summary": item.get("description") or "已记录关系状态",
                    "chapter_index": chapter_index,
                }
            )
        for item in (data.get("character_locations") or {}).values():
            if not isinstance(item, dict):
                continue
            item_chapter = item.get("chapter_index")
            records.append(
                {
                    "memory_type": "人物位置",
                    "title": "位置状态",
                    "summary": item.get("text_state") or "已记录位置",
                    "chapter_index": (
                        item_chapter if item_chapter is not None else chapter_index
                    ),
                }
            )
        for item in data.get("character_knowledge") or []:
            if not isinstance(item, dict):
                continue
            source_chapter = item.get("source_chapter_index")
            records.append(
                {
                    "id": item.get("id"),
                    "memory_type": "人物认知",
                    "title": "认知状态",
                    "summary": item.get("known_content") or "已记录认知边界",
                    "chapter_index": (
                        source_chapter if source_chapter is not None else chapter_index
                    ),
                }
            )
        return records
