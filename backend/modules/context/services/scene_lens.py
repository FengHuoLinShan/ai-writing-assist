"""Read-only, character-visible context for the writing Scene Lens."""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import NotFoundError, ValidationError
from infrastructure.llm.redaction import redact_diagnostic
from modules.context.contracts import CompileOptions, StructureContextBundle
from modules.context.services.loaders import CharactersLoader, WorldEntitiesLoader

logger = logging.getLogger(__name__)
_STATE_LABELS = {
    "entities": "人物与对象",
    "relations": "关系",
    "locations": "人物位置",
    "knowledge": "知识边界",
}


async def _get_scene(db: AsyncSession, novel_id: str, scene_id: str) -> Any:
    from modules.outline.facade import get_scene_contract

    return await get_scene_contract(db, novel_id, scene_id)


async def _get_checkpoints(db: AsyncSession, novel_id: str, scene_id: str) -> Any:
    from modules.memory.facade import get_scene_checkpoints

    return await get_scene_checkpoints(db, novel_id, scene_id)


class SceneLensService:
    """Load a minimal Scene view without retrieval, generation, or writes."""

    def __init__(
        self,
        *,
        get_scene_fn=_get_scene,
        world_loader: WorldEntitiesLoader | None = None,
        characters_loader: CharactersLoader | None = None,
        get_scene_checkpoints_fn=_get_checkpoints,
    ) -> None:
        self._get_scene = get_scene_fn
        self._world_loader = world_loader or WorldEntitiesLoader()
        self._characters_loader = characters_loader or CharactersLoader()
        self._get_checkpoints = get_scene_checkpoints_fn

    async def load(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        scene_id: str,
        chapter_index: int,
    ) -> dict[str, Any]:
        scene_contract = await self._get_scene(db, novel_id, scene_id)
        if scene_contract is None:
            raise NotFoundError("Scene not found", code="scene_not_found")
        scene = (
            scene_contract
            if isinstance(scene_contract, dict)
            else asdict(scene_contract)
        )
        if chapter_index not in self._scene_chapters(scene):
            raise ValidationError(
                "Scene 不属于当前章节",
                code="scene_chapter_mismatch",
                status_code=422,
            )

        viewpoint_id = scene.get("pov_character_id")
        options = CompileOptions(
            novel_id=novel_id,
            task="查看本场",
            scope="scene_lens",
            consumer_action="writing.scene_lens",
            scene_id=scene_id,
            chapter_index=chapter_index,
            visible_until_chapter=chapter_index,
            viewpoint_character_id=viewpoint_id,
            reveal_mode="character",
            include_pending_objects=False,
        )
        bundle = StructureContextBundle(
            novel_id=novel_id,
            task=options.task,
            scope=options.scope,
            chapter_index=chapter_index,
            scene=scene,
            reveal_mode=options.reveal_mode,
            viewpoint_character_id=viewpoint_id,
        )

        if not viewpoint_id:
            bundle.warnings.append("本场未设定 POV 人物，未加载角色可见知识")
        else:
            related_ids = self._related_entity_ids(scene)
            if related_ids:
                options.entity_ids = related_ids
                await self._world_loader.load(db, options, bundle)
            await self._characters_loader.load(db, options, bundle)

        return {
            "role_visible_knowledge": self._knowledge_items(bundle, viewpoint_id),
            "scene_world_state": await self._state_items(
                db,
                novel_id=novel_id,
                scene_id=scene_id,
                warnings=bundle.warnings,
            ),
            "warnings": list(dict.fromkeys(bundle.warnings)),
        }

    async def _state_items(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        scene_id: str,
        warnings: list[str],
    ) -> list[dict[str, Any]]:
        try:
            value = await self._get_checkpoints(db, novel_id, scene_id)
            data = value.model_dump() if hasattr(value, "model_dump") else value
        except Exception as exc:
            logger.warning(
                "Failed to read Scene Lens checkpoints: %s",
                redact_diagnostic(exc, limit=300),
            )
            warnings.append("Scene 时点状态暂时无法读取")
            data = {}

        raw_items = []
        if isinstance(data, dict):
            raw_items = data.get("items") or []
        by_dimension = {
            item.get("dimension"): item
            for item in raw_items
            if isinstance(item, dict)
        }
        return [
            self._state_item(dimension, by_dimension.get(dimension))
            for dimension in _STATE_LABELS
        ]

    @staticmethod
    def _state_item(dimension: str, item: dict[str, Any] | None) -> dict[str, Any]:
        available = bool(
            item
            and item.get("status") == "ready"
            and (
                item.get("source") == "system_generated"
                or item.get("confirmed") is True
            )
        )
        return {
            "label": _STATE_LABELS[dimension],
            "summary": (
                str(item.get("display_summary") or "已记录")
                if available
                else "暂无可靠记录"
            ),
            "availability": available,
        }

    @staticmethod
    def _knowledge_items(
        bundle: StructureContextBundle,
        viewpoint_id: str | None,
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for character in bundle.characters:
            if str(character.get("character_id") or "") != str(viewpoint_id or ""):
                continue
            summary = next(
                (
                    str(character.get(key))
                    for key in (
                        "current_state",
                        "current_goal",
                        "current_emotion",
                        "stance",
                        "role",
                    )
                    if character.get(key)
                ),
                "已设定为本场 POV",
            )
            items.append(
                {
                    "label": f"当前 POV：{character.get('name') or '未命名人物'}",
                    "summary": summary,
                    "availability": True,
                }
            )
        for entity in bundle.world_entities:
            label = str(entity.get("name") or entity.get("title") or "未命名资料")
            summary = str(
                entity.get("misconception")
                or entity.get("known_content")
                or entity.get("public_info")
                or entity.get("summary")
                or "已在角色可见范围内"
            )
            items.append(
                {"label": label, "summary": summary, "availability": True}
            )
        return items

    @staticmethod
    def _scene_chapters(scene: dict[str, Any]) -> set[int]:
        values = list(scene.get("chapter_ids") or [])
        values.extend(
            chunk.get("chapter_index", chunk.get("chapter_id"))
            for chunk in scene.get("scene_chunks") or []
            if isinstance(chunk, dict)
        )
        return {int(value) for value in values if str(value).isdigit()}

    @staticmethod
    def _related_entity_ids(scene: dict[str, Any]) -> list[str]:
        meta = scene.get("structure_meta")
        values = meta.get("related_entity_ids") if isinstance(meta, dict) else []
        return list(dict.fromkeys(str(value) for value in values or [] if value))
