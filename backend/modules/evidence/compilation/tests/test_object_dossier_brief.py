"""Three-layer object briefs preserve cutoff, source and POV boundaries."""

from __future__ import annotations

from uuid import uuid4

import pytest

from modules.evidence.compilation.contracts import CompileOptions
from modules.evidence.compilation.object_dossier_schemas import (
    ObjectDossierBriefRequest,
    ObjectDossierBriefResponse,
)
from modules.evidence.compilation.services.object_dossier_brief import (
    ObjectDossierBriefService,
)

NOVEL_ID = str(uuid4())
SCENE_ID = str(uuid4())
ENTITY_ID = str(uuid4())
POV_ID = str(uuid4())
CHECKPOINT_ID = str(uuid4())


def _story_view(*, character: bool = False) -> dict:
    facts = [
        {
            "subject_id": ENTITY_ID,
            "subject_label": "北门",
            "field": "state",
            "value": "北门关闭",
            "layer": "fact",
            "occurred_at": {"scene_index": 2},
            "source": {
                "checkpoint_id": CHECKPOINT_ID,
                "provenance": {
                    "field": "state",
                    "event_id": str(uuid4()),
                    "status": "exact",
                    "source_refs": [
                        {
                            "draft_id": str(uuid4()),
                            "chapter_index": 1,
                            "version_number": 2,
                            "content_mode": "canonical",
                            "start_offset": 3,
                            "end_offset": 7,
                            "source_hash": "a" * 64,
                            "range_hash": "b" * 64,
                        }
                    ],
                },
            },
            "confidence": "confirmed",
            "possibly_false": False,
        },
        {
            "subject_id": ENTITY_ID,
            "subject_label": "北门守卫",
            "field": "knows:gate",
            "value": "北门关闭",
            "layer": "belief",
            "occurred_at": None,
            "source": {"checkpoint_id": CHECKPOINT_ID},
            "confidence": "confirmed",
            "possibly_false": True,
        },
        {
            "subject_id": ENTITY_ID,
            "subject_label": "未锚定观察",
            "field": "observation",
            "value": {"modality": "character_statement", "text": "北门关闭"},
            "layer": "observation",
            "occurred_at": None,
            "source": {"checkpoint_id": CHECKPOINT_ID},
            "confidence": "derived",
            "possibly_false": False,
        },
    ]
    return {
        "novel_id": NOVEL_ID,
        "scene_id": SCENE_ID,
        "scene_index": 2,
        "viewpoint": (
            {"kind": "character", "target_id": POV_ID}
            if character
            else {"kind": "author"}
        ),
        "state_fingerprint": "story-fingerprint",
        "omissions": [],
        "dimensions": [
            {
                "dimension": "entities",
                "label": "人物与对象",
                "status": "ok",
                "facts": facts,
            },
            {
                "dimension": "relations",
                "label": "关系",
                "status": "missing",
                "gap_reason": "没有时点关系记录",
                "facts": [],
            },
        ],
    }


def _world_dossier() -> dict:
    return {
        "entity_id": ENTITY_ID,
        "entity_type": "location",
        "as_of_scene_id": SCENE_ID,
        "entries": [
            {
                "id": str(uuid4()),
                "entry_group_id": str(uuid4()),
                "revision_number": 2,
                "facing": {"kind": "core", "key": "history"},
                "facing_label": "长期历史",
                "legacy_field_key": None,
                "content": "北门关闭",
                "tags": ["access"],
                "evidence": [
                    {
                        "scene_id": SCENE_ID,
                        "chapter_id": None,
                        "source_hash": "c" * 64,
                        "start_offset": 3,
                        "end_offset": 7,
                        "quote": "北门关闭",
                    }
                ],
                "legacy_value": None,
                "source_metadata": {},
                "quote_text": "raw quote must not be projected",
                "source": "manual",
                "visibility": "public",
                "status": "active",
                "validity": {"start": None, "end": None},
                "anchor_problem": None,
                "effective_at_cutoff": True,
            },
            {
                "id": str(uuid4()),
                "entry_group_id": str(uuid4()),
                "revision_number": 1,
                "facing": {"kind": "core", "key": "secret"},
                "facing_label": "秘密",
                "content": "北门地下有密道",
                "evidence": [],
                "visibility": "secret",
                "source": "manual",
                "tags": [],
                "effective_at_cutoff": True,
            },
        ],
        "legacy_profile_fields": [
            {
                "profile_id": str(uuid4()),
                "profile_type": "location",
                "profile_status": "active",
                "template_id": str(uuid4()),
                "template_version_number": 3,
                "field_key": "origin_place",
                "label": "所在区域",
                "facing": {"kind": "core", "key": "geography"},
                "value": "北门关闭",
                "mapped": True,
                "source_metadata": {"profile_source": "author"},
            },
            {
                "profile_id": str(uuid4()),
                "profile_type": "location",
                "profile_status": "active",
                "template_id": None,
                "template_version_number": None,
                "field_key": "unknown_legacy_key",
                "label": "未知字段",
                "facing": None,
                "value": "must remain unmapped",
                "mapped": False,
                "source_metadata": {},
            },
        ],
        "total_count": 2,
        "omitted_count": 0,
        "dossier_fingerprint": "world-fingerprint",
        "unknown": False,
    }


def _pattern() -> dict:
    return {
        "entry_id": str(uuid4()),
        "revision_id": str(uuid4()),
        "revision": 4,
        "entity_ids": [ENTITY_ID],
        "category": "conditional_behavior",
        "statement": "守卫听见钟声后会检查北门。",
        "conditions": ["听见钟声"],
        "modality": "hypothesis",
        "confidence": 0.8,
        "competing_explanations": ["当日加强巡查"],
        "review_verdict": "supported",
        "author_decision": "keep",
        "evidence_refs": [
            {
                "observation_id": "obs-1",
                "scene_id": SCENE_ID,
                "scene_index": 2,
                "modality": "character_statement",
                "role": "support",
                "source": {
                    "draft_id": "draft-1",
                    "content_hash": "d" * 64,
                    "start_offset": 5,
                    "end_offset": 14,
                    "source_visibility": "canonical",
                },
            }
        ],
        "interpretation_only": True,
    }


def _options(*, reveal_mode: str = "author_safe") -> CompileOptions:
    return CompileOptions(
        novel_id=NOVEL_ID,
        task="object brief test",
        scope="scene",
        scene_id=SCENE_ID,
        reveal_mode=reveal_mode,
        viewpoint_character_id=POV_ID if reveal_mode == "character" else None,
        content_mode="canonical",
    )


@pytest.fixture
def facade_reads(monkeypatch):
    calls = {"checkpoints": 0}

    async def active_project(_db, _novel_id):
        return None

    async def scene_state(_db, novel_id, scene_id, *, viewpoint):
        assert novel_id == NOVEL_ID
        assert scene_id == SCENE_ID
        return _story_view(character=viewpoint["kind"] == "character")

    async def checkpoints(_db, novel_id, scene_id):
        calls["checkpoints"] += 1
        return {
            "novel_id": novel_id,
            "scene_id": scene_id,
            "scene_index": 2,
            "items": [
                {
                    "id": CHECKPOINT_ID,
                    "dimension": "entities",
                    "source_hash": "e" * 64,
                    "status": "ready",
                    "stage_index": 1,
                    "is_current": True,
                }
            ],
        }

    async def dossier(_db, novel_id, entity_id, *, as_of_scene_id, limit, offset):
        assert novel_id == NOVEL_ID
        assert entity_id == ENTITY_ID
        assert as_of_scene_id == SCENE_ID
        assert (limit, offset) == (250, 0)
        return _world_dossier()

    monkeypatch.setattr("modules.project.facade.require_active_project", active_project)
    monkeypatch.setattr("modules.story.facade.get_scene_state_view", scene_state)
    monkeypatch.setattr("modules.story.facade.get_scene_checkpoints", checkpoints)
    monkeypatch.setattr("modules.world.facade.read_world_object_dossier", dossier)
    return calls


async def test_author_brief_aggregates_three_layers_and_keeps_only_reference_ids(
    facade_reads,
):
    async def read_patterns(_db, **kwargs):
        assert kwargs == {
            "novel_id": NOVEL_ID,
            "scene_id": SCENE_ID,
            "entity_ids": [ENTITY_ID],
            "only_adopted": False,
        }
        return {
            "novel_id": NOVEL_ID,
            "scene_id": SCENE_ID,
            "scene_index": 2,
            "items": [_pattern()],
            "omitted_count": 0,
            "omissions": [],
            "coverage": "complete",
            "ledger_fingerprint": "ledger-fingerprint",
        }

    result = await ObjectDossierBriefService(read_patterns).load(
        None,
        _options(),
        entity_ids=[ENTITY_ID],
        include_patterns=True,
    )

    response = ObjectDossierBriefResponse.model_validate(result)
    assert facade_reads["checkpoints"] == 1
    assert response.layers == ["world", "continuity", "evolution"]
    assert response.world_fingerprint
    assert response.continuity_fingerprint
    assert response.pattern_fingerprint == "ledger-fingerprint"
    assert len(response.world_items) == 3
    assert sum(item.kind == "world_dossier" for item in response.world_items) == 2
    assert sum(item.kind == "legacy_profile_field" for item in response.world_items) == 1
    assert response.continuity_items[0].layer == "fact"
    assert response.continuity_items[1].layer == "belief"
    assert response.continuity_items[1].possibly_false is True
    assert response.continuity_items[2].layer == "observation"
    assert response.pattern_items[0].modality == "hypothesis"
    assert response.pattern_items[0].evidence_refs[0]["modality"] == "character_statement"
    dossier_entry = next(
        item
        for item in response.world_items
        if item.kind == "world_dossier" and item.source_refs
    )
    assert "quote" not in dossier_entry.source_refs[0]
    assert "raw quote must not be projected" not in str(response.model_dump())
    assert "unknown_legacy_key" not in str(response.model_dump())
    assert "1 个旧档案字段未绑定模板面向" in " ".join(response.omissions)


async def test_character_brief_fails_closed_on_secret_and_evolution_patterns(
    facade_reads,
):
    async def forbidden_patterns(*_args, **_kwargs):
        raise AssertionError("POV projection must not call Evolution")

    result = await ObjectDossierBriefService(forbidden_patterns).load(
        None,
        _options(reveal_mode="character"),
        entity_ids=[ENTITY_ID],
        include_patterns=True,
    )

    response = ObjectDossierBriefResponse.model_validate(result)
    assert facade_reads["checkpoints"] == 0
    assert [
        item.content for item in response.world_items if item.kind == "world_dossier"
    ] == ["北门关闭"]
    assert all(
        item.visibility == "public"
        for item in response.world_items
        if item.kind == "world_dossier"
    )
    visible_entry = next(
        item for item in response.world_items if item.kind == "world_dossier"
    )
    assert visible_entry.facing is None
    assert visible_entry.facing_label is None
    assert visible_entry.source_refs == []
    assert visible_entry.dossier_fingerprint is None
    assert response.checkpoint_refs == []
    assert response.world_dossier_fingerprints[0]["fingerprint"] != "world-fingerprint"
    assert response.pattern_items == []
    assert all(item.layer != "observation" for item in response.continuity_items)
    assert "secret" not in str(response.model_dump())
    assert "人物倾向" in " ".join(response.omissions)


def test_brief_request_contract_requires_a_cutoff_and_explicit_pattern_opt_in():
    request = ObjectDossierBriefRequest(
        novel_id=NOVEL_ID,
        scene_id=SCENE_ID,
        entity_ids=[ENTITY_ID],
    )
    assert request.include_patterns is False
    assert request.only_adopted_patterns is False
    with pytest.raises(ValueError, match="viewpoint_character_id"):
        ObjectDossierBriefRequest(
            novel_id=NOVEL_ID,
            scene_id=SCENE_ID,
            entity_ids=[ENTITY_ID],
            reveal_mode="character",
        )
    with pytest.raises(ValueError, match="requires include_patterns"):
        ObjectDossierBriefRequest(
            novel_id=NOVEL_ID,
            scene_id=SCENE_ID,
            entity_ids=[ENTITY_ID],
            only_adopted_patterns=True,
        )


def test_object_brief_api_is_registered_without_importing_evolution_service_key():
    from modules.evidence.compilation.api import router

    route = next(
        item for item in router.routes if item.path.endswith("/object-dossier-brief")
    )
    assert route.methods == {"POST"}
    assert route.response_model is ObjectDossierBriefResponse
