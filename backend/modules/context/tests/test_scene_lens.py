from __future__ import annotations

from types import SimpleNamespace

import pytest

from modules.context.schemas import SceneLensRequest
from modules.context.services.scene_lens import (
    SCENE_LENS_LOADER_PROFILE,
    SceneLensService,
)


class _Loader:
    def __init__(self, callback):
        self._callback = callback

    async def load(self, db, options, bundle):
        await self._callback(options, bundle)


@pytest.mark.asyncio
async def test_scene_lens_derives_pov_and_only_reads_existing_checkpoints() -> None:
    calls = []

    async def scene(options, bundle):
        calls.append("scene")
        bundle.scene = {
            "id": options.scene_id,
            "pov_character_id": "character-1",
            "chapter_ids": ["2"],
        }

    async def world(options, bundle):
        calls.append(
            ("world_entities", options.viewpoint_character_id, options.chapter_index)
        )
        bundle.world_entities = [{"name": "钟楼", "summary": "POV 已知"}]

    async def characters(options, bundle):
        calls.append(("characters", options.reveal_mode))
        bundle.characters = [
            {"character_id": "character-1", "name": "阿青", "current_state": "目击者"},
            {"character_id": "character-2", "name": "不应暴露"},
        ]

    async def checkpoints(db, novel_id, scene_id):
        calls.append(("get_checkpoints", novel_id, scene_id))
        return SimpleNamespace(
            model_dump=lambda: {
                "coverage_status": "complete",
                "items": [{"dimension": "locations", "display_summary": "位于钟楼"}],
                "missing_dimensions": [],
            }
        )

    result = await SceneLensService(
        scene_loader=_Loader(scene),
        world_loader=_Loader(world),
        characters_loader=_Loader(characters),
        get_scene_checkpoints_fn=checkpoints,
    ).load(object(), novel_id="novel-1", scene_id="scene-1")

    assert SCENE_LENS_LOADER_PROFILE == (
        "scene",
        "world_entities",
        "characters",
        "scene_checkpoints",
    )
    assert calls == [
        "scene",
        ("world_entities", "character-1", 2),
        ("characters", "character"),
        ("get_checkpoints", "novel-1", "scene-1"),
    ]
    assert set(result) == {"role_visible_knowledge", "scene_world_state", "warnings"}
    assert result["role_visible_knowledge"]["characters"][0]["name"] == "阿青"


@pytest.mark.asyncio
async def test_scene_lens_without_pov_fails_closed_but_keeps_static_state() -> None:
    async def scene(options, bundle):
        bundle.scene = {"id": options.scene_id, "chapter_ids": ["1"]}

    async def forbidden(*_args):
        raise AssertionError(
            "knowledge loaders must not run without a server-derived POV"
        )

    result = await SceneLensService(
        scene_loader=_Loader(scene),
        world_loader=_Loader(forbidden),
        characters_loader=_Loader(forbidden),
        get_scene_checkpoints_fn=lambda *_args: forbidden(),
    ).load(object(), novel_id="novel-1", scene_id="scene-1")

    assert result["role_visible_knowledge"] == {"characters": [], "world_entities": []}
    assert any("POV" in warning for warning in result["warnings"])


@pytest.mark.asyncio
async def test_scene_lens_api_applies_project_owner_gate(monkeypatch) -> None:
    from modules.context import api

    calls = []

    async def require_project(db, novel_id):
        calls.append(("gate", novel_id))

    async def load_lens(db, *, novel_id, scene_id):
        calls.append(("load", novel_id, scene_id))
        return {
            "role_visible_knowledge": {},
            "scene_world_state": {},
            "warnings": [],
        }

    monkeypatch.setattr(api, "require_active_project", require_project)
    monkeypatch.setattr(api, "_load_scene_lens", load_lens)
    response = await api.scene_lens(
        db=object(),
        request=SceneLensRequest(novel_id="novel-1", scene_id="scene-1"),
    )

    assert calls == [("gate", "novel-1"), ("load", "novel-1", "scene-1")]
    assert response.warnings == []
