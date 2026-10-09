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

    async def state_view(db, novel_id, scene_id, *, viewpoint=None):
        calls.append(
            ("state_view", novel_id, scene_id, (viewpoint or {}).get("kind", "author"))
        )
        return SimpleNamespace(
            model_dump=lambda: {
                "subject_labels": {
                    "entity-1": "铜钥匙",
                    "character-2": "阿乙",
                },
                "dimensions": [
                    {
                        "dimension": "entities",
                        "status": "ok",
                        "facts": [
                            {
                                "subject_id": "entity-1",
                                "subject_label": "铜钥匙",
                                "field": "custody_holder",
                                "value": "character-2",
                                "layer": "fact",
                                "confidence": "derived",
                                "possibly_false": False,
                            },
                            {
                                "subject_id": "character-2",
                                "subject_label": "阿乙",
                                "field": "custody_holder",
                                "value": "character-2",
                                "layer": "fact",
                                "confidence": "derived",
                                "possibly_false": False,
                            },
                        ],
                    },
                    {
                        "dimension": "knowledge",
                        "status": "ok",
                        "facts": [
                            {
                                "subject_id": "character-1",
                                "subject_label": "阿乙误信钥匙已归还",
                                "field": "knows:entity-1",
                                "value": "阿乙误信钥匙已归还",
                                "layer": "belief",
                                "confidence": "derived",
                                "possibly_false": True,
                            }
                        ],
                    },
                ],
            }
        )

    result = await SceneLensService(
        get_scene_fn=get_scene,
        characters_loader=_Loader(characters),
        get_scene_checkpoints_fn=checkpoints,
        get_state_view_fn=state_view,
    ).load(object(), novel_id="novel-1", scene_id="scene-1", chapter_index=2)

    assert calls == [
        ("scene", "novel-1", "scene-1"),
        # M4：状态视图单次读取，先于 checkpoint 读（维度新鲜度共用同一份）
        ("state_view", "novel-1", "scene-1", "author"),
        ("state_view", "novel-1", "scene-1", "character"),
        ("checkpoints", "novel-1", "scene-1"),
    ]
    assert set(result) == {
        "state_fingerprint",
        "subject_choices",
        "role_visible_knowledge",
        "scene_world_state",
        "object_states",
        "warnings",
    }
    for item in result["role_visible_knowledge"]:
        assert set(item) == {"label", "summary", "availability", "stale"}
    assert "目击者" not in str(result["role_visible_knowledge"])
    assert "可能误信" in str(result["role_visible_knowledge"])
    for item in result["scene_world_state"]:
        # M4：维度区新增 stale（视图基线比对 degraded 时作者侧可见待核对）
        assert set(item) == {"label", "summary", "availability", "stale"}
    assert [item["label"] for item in result["scene_world_state"]] == [
        "人物与对象",
        "关系",
        "空间与位置",
        "知识边界",
        "时间顺序",
        "因果与前提",
    ]
    # 对象状态区：仅本 Scene 关联对象；UUID 渲染成名字；误信带标记。
    objects = result["object_states"]
    assert len(objects) == 2
    unknown = next(item for item in objects if item["subject_id"] == "character-1")
    assert unknown["unknowns"]
    key_state = next(item for item in objects if item["label"] == "铜钥匙")
    assert key_state["fields"][0]["display"] == "阿乙"
    assert key_state["knowledge"][0]["possibly_false"] is True
    serialized = str(result)
    for internal in (
        "coverage_status",
        "missing_dimensions",
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
                "stale": False,
            }
        ],
        "scene_world_state": [],
        "object_states": [],
        "state_fingerprint": None,
        "subject_choices": {},
        "warnings": [],
    }


@pytest.mark.asyncio
async def test_scene_lens_object_sources_carry_field_provenance() -> None:
    """P2-A：fact 级 provenance 聚进 Lens source；三态明示，坏形态不冒充依据。"""

    def fact(field: str, status: str, refs, event_id="event-1"):
        return {
            "subject_id": "entity-1",
            "subject_label": "铜钥匙",
            "field": field,
            "value": "character-2",
            "layer": "fact",
            "confidence": "derived",
            "possibly_false": False,
            "source": {
                "checkpoint_id": "checkpoint-1",
                "dimension": "entities",
                "confirmed": False,
                "provenance": {
                    "field": field,
                    "event_id": event_id,
                    "source_refs": refs,
                    "status": status,
                },
            },
        }

    exact_ref = {
        "draft_id": "draft-1",
        "chapter_index": 2,
        "version_number": 1,
        "content_mode": "working",
        "start_offset": 10,
        "end_offset": 24,
        "source_hash": "a" * 64,
        "range_hash": "b" * 64,
    }

    async def state_view(db, novel_id, scene_id, *, viewpoint=None):
        return SimpleNamespace(
            model_dump=lambda: {
                "subject_labels": {"entity-1": "铜钥匙"},
                "dimensions": [
                    {
                        "dimension": "entities",
                        "status": "ok",
                        "evidence_refs": [{"type": "memory_event", "id": "event-1"}],
                        "facts": [
                            fact("custody_holder", "exact", [exact_ref]),
                            fact("custody_owner", "unverified", [], event_id=None),
                            fact("opening_passphrase", "conflict", [exact_ref]),
                            # 区间不完整的 exact 降级为来源待核实，不制造精确性。
                            fact(
                                "opening_key_id",
                                "exact",
                                [{**exact_ref, "start_offset": "x"}],
                            ),
                            # 非法 status / 非 dict 的 provenance 整条丢弃。
                            {
                                **fact("opening_moon_phase", "exact", [exact_ref]),
                                "source": {
                                    "checkpoint_id": "checkpoint-1",
                                    "provenance": {
                                        "field": "opening_moon_phase",
                                        "status": "maybe",
                                        "source_refs": [exact_ref],
                                    },
                                },
                            },
                            {
                                **fact("entity_type", "exact", [exact_ref]),
                                "source": {
                                    "checkpoint_id": "checkpoint-1",
                                    "provenance": "corrupted",
                                },
                            },
                        ],
                    }
                ],
            }
        )

    result = await SceneLensService(
        get_scene_fn=lambda *_args: _async_value(_scene()),
        get_scene_checkpoints_fn=lambda *_args: _async_value({"items": []}),
        get_state_view_fn=state_view,
    ).load(object(), novel_id="novel-1", scene_id="scene-1", chapter_index=2)

    sources = {
        item["field"]: item["source"]
        for obj in result["object_states"]
        for item in obj["fields"]
    }
    exact = sources["custody_holder"]["provenance"]
    assert exact == {
        "field": "custody_holder",
        "status": "exact",
        "event_id": "event-1",
        "source_refs": [exact_ref],
    }
    assert sources["custody_holder"]["evidence_refs"] == [
        {"type": "memory_event", "id": "event-1"}
    ]
    unverified = sources["custody_owner"]["provenance"]
    assert unverified["status"] == "unverified"
    assert unverified["source_refs"] == []
    assert unverified["event_id"] is None
    assert sources["opening_passphrase"]["provenance"]["status"] == "conflict"
    downgraded = sources["opening_key_id"]["provenance"]
    assert downgraded["status"] == "unverified"
    assert downgraded["source_refs"] == []
    assert "provenance" not in sources["opening_moon_phase"]
    assert "provenance" not in sources["entity_type"]


@pytest.mark.asyncio
async def test_scene_lens_provenance_survives_response_schema() -> None:
    """provenance 必须能穿过 SceneLensResponse 的响应模型到达前端。"""
    from modules.evidence.compilation.schemas import SceneLensResponse

    exact_ref = {
        "draft_id": "draft-1",
        "chapter_index": 2,
        "version_number": 1,
        "content_mode": "working",
        "start_offset": 10,
        "end_offset": 24,
    }

    async def state_view(db, novel_id, scene_id, *, viewpoint=None):
        return SimpleNamespace(
            model_dump=lambda: {
                "subject_labels": {"entity-1": "铜钥匙"},
                "dimensions": [
                    {
                        "dimension": "entities",
                        "status": "ok",
                        "facts": [
                            {
                                "subject_id": "entity-1",
                                "subject_label": "铜钥匙",
                                "field": "custody_holder",
                                "value": "character-2",
                                "layer": "fact",
                                "confidence": "derived",
                                "possibly_false": False,
                                "source": {
                                    "checkpoint_id": "checkpoint-1",
                                    "provenance": {
                                        "field": "custody_holder",
                                        "event_id": "event-1",
                                        "source_refs": [exact_ref],
                                        "status": "exact",
                                    },
                                },
                            }
                        ],
                    }
                ],
            }
        )

    result = await SceneLensService(
        get_scene_fn=lambda *_args: _async_value(_scene()),
        get_scene_checkpoints_fn=lambda *_args: _async_value({"items": []}),
        get_state_view_fn=state_view,
    ).load(object(), novel_id="novel-1", scene_id="scene-1", chapter_index=2)

    response = SceneLensResponse(**result)
    field = next(obj for obj in response.object_states if obj.fields).fields[0]
    assert field.source.provenance is not None
    assert field.source.provenance.status == "exact"
    assert field.source.provenance.source_refs[0].draft_id == "draft-1"


async def _async_value(value):
    return value
