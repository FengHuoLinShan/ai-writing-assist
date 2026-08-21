from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.errors import NotFoundError, ValidationError
from modules.evidence.compilation.schemas import SceneLensRequest
from modules.evidence.compilation.services.scene_lens import SceneLensService


class _Loader:
    def __init__(self, callback):
        self._callback = callback

    async def load(self, db, options, bundle):
        await self._callback(options, bundle)


def _scene(**overrides):
    return {
        "id": "scene-1",
        "novel_id": "novel-1",
        "pov_character_id": "character-1",
        "chapter_ids": ["2", "3"],
        "structure_meta": {"related_entity_ids": ["entity-1"]},
        **overrides,
    }


@pytest.mark.asyncio
async def test_scene_lens_uses_requested_chapter_as_cross_chapter_cutoff() -> None:
    calls = []

    async def get_scene(db, novel_id, scene_id):
        calls.append(("scene", novel_id, scene_id))
        return _scene()

    async def world(options, bundle):
        calls.append(
            (
                "world",
                options.chapter_index,
                options.visible_until_chapter,
                options.entity_ids,
            )
        )
        bundle.world_entities = [{"name": "钟楼", "summary": "POV 已知"}]

    async def characters(options, bundle):
        calls.append(("characters", options.viewpoint_character_id))
        bundle.characters = [
            {
                "character_id": "character-1",
                "name": "阿青",
                "current_state": "目击者",
                "secret": "不得暴露",
            }
        ]

    async def checkpoints(db, novel_id, scene_id):
        calls.append(("checkpoints", novel_id, scene_id))
        return SimpleNamespace(
            model_dump=lambda: {
                "coverage_status": "complete",
                "missing_dimensions": ["knowledge"],
                "items": [
                    {
                        "dimension": "locations",
                        "status": "ready",
                        "source": "system_generated",
                        "display_summary": "位于钟楼",
                        "gap_reason": "internal",
                    }
                ],
            }
        )

    result = await SceneLensService(
        get_scene_fn=get_scene,
        world_loader=_Loader(world),
        characters_loader=_Loader(characters),
        get_scene_checkpoints_fn=checkpoints,
    ).load(object(), novel_id="novel-1", scene_id="scene-1", chapter_index=2)

    assert calls == [
        ("scene", "novel-1", "scene-1"),
        ("world", 2, 2, ["entity-1"]),
        ("characters", "character-1"),
        ("checkpoints", "novel-1", "scene-1"),
    ]
    assert set(result) == {"role_visible_knowledge", "scene_world_state", "warnings"}
    for item in [
        *result["role_visible_knowledge"],
        *result["scene_world_state"],
    ]:
        assert set(item) == {"label", "summary", "availability"}
    serialized = str(result)
    for internal in (
        "coverage_status",
        "missing_dimensions",
        "dimension",
        "gap_reason",
        "entity_type",
        "knowledge_level",
        "secret",
    ):
        assert internal not in serialized


@pytest.mark.asyncio
async def test_scene_lens_rejects_missing_or_wrong_chapter_scene() -> None:
    missing = SceneLensService(get_scene_fn=lambda *_args: _async_value(None))
    with pytest.raises(NotFoundError):
        await missing.load(
            object(), novel_id="novel-1", scene_id="other-scene", chapter_index=2
        )

    wrong_chapter = SceneLensService(
        get_scene_fn=lambda *_args: _async_value(_scene(chapter_ids=["3"]))
    )
    with pytest.raises(ValidationError) as exc_info:
        await wrong_chapter.load(
            object(), novel_id="novel-1", scene_id="scene-1", chapter_index=2
        )
    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_scene_lens_skips_global_world_fallback_without_related_ids() -> None:
    async def forbidden(*_args):
        raise AssertionError("world loader must not run without related_entity_ids")

    result = await SceneLensService(
        get_scene_fn=lambda *_args: _async_value(
            _scene(structure_meta={}, pov_character_id=None)
        ),
        world_loader=_Loader(forbidden),
        characters_loader=_Loader(forbidden),
        get_scene_checkpoints_fn=lambda *_args: _async_value({"items": []}),
    ).load(object(), novel_id="novel-1", scene_id="scene-1", chapter_index=2)

    assert result["role_visible_knowledge"] == []
    assert any("POV" in warning for warning in result["warnings"])


@pytest.mark.asyncio
async def test_scene_lens_api_applies_project_owner_gate(monkeypatch) -> None:
    from modules.evidence.compilation import api

    calls = []

    async def require_project(db, novel_id):
        calls.append(("gate", novel_id))

    async def load_lens(db, *, novel_id, scene_id, chapter_index):
        calls.append(("load", novel_id, scene_id, chapter_index))
        return {
            "role_visible_knowledge": [
                {
                    "label": "当前 POV：阿青",
                    "summary": "只知道铜铃",
                    "availability": True,
                    "knowledge_level": "internal",
                }
            ],
            "scene_world_state": [],
            "warnings": [],
            "coverage_status": "internal",
        }

    monkeypatch.setattr(api, "require_active_project", require_project)
    monkeypatch.setattr(api, "_load_scene_lens", load_lens)
    response = await api.scene_lens(
        db=object(),
        request=SceneLensRequest(
            novel_id="novel-1",
            scene_id="scene-1",
            chapter_index=2,
        ),
    )

    assert calls == [
        ("gate", "novel-1"),
        ("load", "novel-1", "scene-1", 2),
    ]
    assert response.model_dump() == {
        "role_visible_knowledge": [
            {
                "label": "当前 POV：阿青",
                "summary": "只知道铜铃",
                "availability": True,
            }
        ],
        "scene_world_state": [],
        "warnings": [],
    }


async def _async_value(value):
    return value
