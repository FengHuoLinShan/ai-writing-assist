"""Read-only, character-visible context for the writing Scene Lens."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.llm.redaction import redact_diagnostic
from modules.context.contracts import CompileOptions, StructureContextBundle
from modules.context.services.loaders import (
    CharactersLoader,
    SceneLoader,
    WorldEntitiesLoader,
)
from modules.memory.contracts import SCENE_MEMORY_DIMENSIONS

SCENE_LENS_LOADER_PROFILE = (
    "scene",
    "world_entities",
    "characters",
    "scene_checkpoints",
)
logger = logging.getLogger(__name__)


async def _get_scene_checkpoints(
    db: AsyncSession,
    novel_id: str,
    scene_id: str,
) -> Any:
    from modules.memory.facade import get_scene_checkpoints

    return await get_scene_checkpoints(db, novel_id, scene_id)


class SceneLensService:
    """Load the smallest safe Scene view without retrieval or persistence."""

    def __init__(
        self,
        *,
        scene_loader: SceneLoader | None = None,
        world_loader: WorldEntitiesLoader | None = None,
        characters_loader: CharactersLoader | None = None,
        get_scene_checkpoints_fn=_get_scene_checkpoints,
    ) -> None:
        self._scene_loader = scene_loader or SceneLoader()
        self._world_loader = world_loader or WorldEntitiesLoader()
        self._characters_loader = characters_loader or CharactersLoader()
        self._loaders = {
            "scene": self._scene_loader,
            "world_entities": self._world_loader,
            "characters": self._characters_loader,
        }
        self._get_scene_checkpoints = get_scene_checkpoints_fn

    async def load(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        scene_id: str,
    ) -> dict[str, Any]:
        options = CompileOptions(
            novel_id=novel_id,
            task="查看本场",
            scope="scene_lens",
            consumer_action="writing.scene_lens",
            scene_id=scene_id,
            reveal_mode="character",
            include_pending_objects=False,
        )
        bundle = StructureContextBundle(
            novel_id=novel_id,
            task=options.task,
            scope=options.scope,
            reveal_mode=options.reveal_mode,
        )
        viewpoint_id = None
        chapter_index = None
        checkpoint_set: dict[str, Any] = {}
        for loader_name in SCENE_LENS_LOADER_PROFILE:
            if loader_name == "scene_checkpoints":
                checkpoint_set = await self._read_checkpoints(
                    db,
                    novel_id=novel_id,
                    scene_id=scene_id,
                    warnings=bundle.warnings,
                )
                continue
            if loader_name != "scene" and (
                viewpoint_id is None or chapter_index is None
            ):
                continue
            await self._loaders[loader_name].load(db, options, bundle)
            if loader_name == "scene":
                scene = bundle.scene or {}
                viewpoint_id = scene.get("pov_character_id")
                chapter_index = self._scene_chapter(scene)
                options.viewpoint_character_id = viewpoint_id
                options.chapter_index = chapter_index
                options.visible_until_chapter = chapter_index

        if not viewpoint_id:
            bundle.warnings.append("本场未设定 POV 人物，未加载角色可见知识")
        elif chapter_index is None:
            bundle.warnings.append("本场未关联章节，未加载角色可见知识")
        return {
            "role_visible_knowledge": {
                "characters": self._project_characters(
                    bundle.characters,
                    viewpoint_id=viewpoint_id,
                ),
                "world_entities": self._project_world_entities(bundle.world_entities),
            },
            "scene_world_state": checkpoint_set,
            "warnings": list(dict.fromkeys(bundle.warnings)),
        }

    async def _read_checkpoints(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        scene_id: str,
        warnings: list[str],
    ) -> dict[str, Any]:
        try:
            value = await self._get_scene_checkpoints(db, novel_id, scene_id)
            if hasattr(value, "model_dump"):
                value = value.model_dump()
            if isinstance(value, dict):
                return {
                    "coverage_status": value.get("coverage_status", "unavailable"),
                    "items": [
                        {
                            key: item[key]
                            for key in (
                                "dimension",
                                "dimension_label",
                                "display_summary",
                                "gap_reason",
                            )
                            if key in item
                        }
                        for item in value.get("items") or []
                        if isinstance(item, dict)
                    ],
                    "missing_dimensions": value.get("missing_dimensions") or [],
                }
        except Exception as exc:
            logger.warning(
                "Failed to read Scene Lens checkpoints: %s",
                redact_diagnostic(exc, limit=300),
            )
            warnings.append("Scene 时点状态暂时无法读取")
        return {
            "coverage_status": "unavailable",
            "items": [],
            "missing_dimensions": list(SCENE_MEMORY_DIMENSIONS),
        }

    @staticmethod
    def _scene_chapter(scene: dict[str, Any]) -> int | None:
        chapter_ids = scene.get("chapter_ids") or []
        chapters = [int(value) for value in chapter_ids if str(value).isdigit()]
        for chunk in scene.get("scene_chunks") or []:
            if not isinstance(chunk, dict):
                continue
            value = chunk.get("chapter_index", chunk.get("chapter_id"))
            if str(value).isdigit():
                chapters.append(int(value))
        return max(chapters) if chapters else None

    @staticmethod
    def _project_characters(
        characters: list[dict[str, Any]],
        *,
        viewpoint_id: str | None,
    ) -> list[dict[str, Any]]:
        fields = (
            "name",
            "role",
            "current_goal",
            "current_state",
            "current_emotion",
            "stance",
        )
        return [
            {key: item[key] for key in fields if item.get(key) is not None}
            for item in characters
            if str(item.get("character_id") or "") == str(viewpoint_id or "")
        ]

    @staticmethod
    def _project_world_entities(
        entities: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        fields = (
            "name",
            "title",
            "entity_type",
            "summary",
            "public_info",
            "known_content",
            "misconception",
            "knowledge_level",
        )
        return [
            {key: item[key] for key in fields if item.get(key) is not None}
            for item in entities
        ]
