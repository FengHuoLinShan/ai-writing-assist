"""Typed map proposal schema and deterministic imports mapping tests."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from pydantic import ValidationError

from modules.imports.llm_schemas import (
    ExtractedCharacterLocationProposal,
    Phase2WorldExtractionOutput,
    SceneEntityExtractionOutput,
)
from modules.imports.map_observation_candidates import (
    build_map_observation_candidates,
)
from modules.imports.phase2_world_extraction import (
    _primary_scene,
    _scene_source_fingerprint,
)


def test_scene_output_accepts_typed_map_proposal_and_rejects_unknown_type() -> None:
    output = SceneEntityExtractionOutput.model_validate(
        {
            "map_observation_proposals": [
                {
                    "proposal_type": "character_location",
                    "character_name": "沈砚",
                    "location_name": "青石镇",
                    "quote": "沈砚在薄雾里走进青石镇。",
                    "confidence": 0.91,
                }
            ]
        }
    )
    assert output.map_observation_proposals[0].proposal_type == "character_location"

    with pytest.raises(ValidationError):
        Phase2WorldExtractionOutput.model_validate(
            {
                "map_observation_proposals": [
                    {
                        "proposal_type": "free_form_map_delta",
                        "quote": "不可识别的地图变化。",
                    }
                ]
            }
        )


def test_mapping_keeps_source_identity_stable_and_payload_evidence_explicit() -> None:
    proposal = ExtractedCharacterLocationProposal(
        proposal_type="character_location",
        character_name="沈砚",
        location_name="青石镇",
        quote="沈砚在薄雾里走进青石镇。",
        confidence=0.91,
    )
    kwargs = {
        "novel_id": str(uuid.uuid4()),
        "workflow_id": "workflow-1",
        "scene_id": str(uuid.uuid4()),
        "scene_index": 4,
        "source_chapter_index": 2,
        "scene_source_fingerprint": "a" * 64,
        "context_snapshot_id": "snapshot-1",
    }
    kwargs["authorization_snapshot"] = {
        "adoption_policy": "user_authorized_pipeline",
        "authorization_confirmed": True,
        "authorized_at": "2026-07-15T00:00:00Z",
        "scope": {
            "novel_id": kwargs["novel_id"],
            "start_chapter": 1,
            "end_chapter": 10,
            "stage": None,
        },
    }

    first = build_map_observation_candidates([proposal], **kwargs)[0]
    second = build_map_observation_candidates([proposal], **kwargs)[0]

    assert first.source_item_key.startswith("map-proposal:v1:character_location:")
    assert first.source_item_key.endswith(":0")
    assert first == second
    assert first.evidence_text == proposal.quote
    assert first.evidence_anchor != proposal.quote
    assert first.proposal.proposal_type == "character_location"
    assert first.authorization.authorization_confirmed is True


def test_mapping_identity_survives_same_type_proposal_reordering() -> None:
    scene_id = str(uuid.uuid4())
    novel_id = str(uuid.uuid4())
    proposals = [
        ExtractedCharacterLocationProposal(
            proposal_type="character_location",
            character_name="沈砚",
            location_name="青石镇",
            quote="沈砚走进青石镇。",
            confidence=0.91,
        ),
        ExtractedCharacterLocationProposal(
            proposal_type="character_location",
            character_name="顾秋水",
            location_name="石桥",
            quote="顾秋水停在石桥上。",
            confidence=0.88,
        ),
    ]
    kwargs = {
        "novel_id": novel_id,
        "workflow_id": "workflow-1",
        "scene_id": scene_id,
        "scene_index": 4,
        "source_chapter_index": 2,
        "scene_source_fingerprint": "a" * 64,
        "authorization_snapshot": {
            "adoption_policy": "user_authorized_pipeline",
            "authorization_confirmed": True,
            "authorized_at": "2026-07-15T00:00:00Z",
            "scope": {
                "novel_id": novel_id,
                "start_chapter": 1,
                "end_chapter": 10,
                "stage": None,
            },
        },
    }

    first = build_map_observation_candidates(proposals, **kwargs)
    reordered = build_map_observation_candidates(list(reversed(proposals)), **kwargs)

    assert {item.source_item_key for item in first} == {
        item.source_item_key for item in reordered
    }


def test_mapping_identity_survives_same_quote_multi_target_reordering() -> None:
    scene_id = str(uuid.uuid4())
    novel_id = str(uuid.uuid4())
    proposals = [
        ExtractedCharacterLocationProposal(
            proposal_type="character_location",
            character_name=name,
            location_name="青石镇",
            quote="沈砚与顾秋水一同走进青石镇。",
            confidence=0.91,
        )
        for name in ("沈砚", "顾秋水")
    ]
    kwargs = {
        "novel_id": novel_id,
        "workflow_id": "workflow-1",
        "scene_id": scene_id,
        "scene_index": 4,
        "source_chapter_index": 2,
        "scene_source_fingerprint": "a" * 64,
        "authorization_snapshot": {
            "adoption_policy": "user_authorized_pipeline",
            "authorization_confirmed": True,
            "authorized_at": "2026-07-15T00:00:00Z",
            "scope": {
                "novel_id": novel_id,
                "start_chapter": 1,
                "end_chapter": 10,
                "stage": None,
            },
        },
    }

    first = build_map_observation_candidates(proposals, **kwargs)
    reordered = build_map_observation_candidates(list(reversed(proposals)), **kwargs)

    assert {item.target_name: item.source_item_key for item in first} == {
        item.target_name: item.source_item_key for item in reordered
    }


def test_map_proposal_schema_rejects_unknown_branch_fields() -> None:
    with pytest.raises(ValidationError):
        SceneEntityExtractionOutput.model_validate(
            {
                "map_observation_proposals": [
                    {
                        "proposal_type": "character_location",
                        "character_name": "沈砚",
                        "event_name": "不应出现",
                        "quote": "沈砚走进青石镇。",
                        "confidence": 0.91,
                    }
                ]
            }
        )


def test_window_proposal_provenance_uses_owned_scene_not_overlap_scene() -> None:
    overlap = {"id": "overlap", "scene_index": 1}
    owned = {"id": "owned", "scene_index": 2}

    selected = _primary_scene(
        ["overlap", "owned"],
        {"overlap": overlap, "owned": owned},
        allowed_scene_ids={"owned"},
    )

    assert selected == owned


def test_window_scene_fingerprint_changes_with_exact_consumed_text() -> None:
    scene = {
        "id": str(uuid.uuid4()),
        "scene_index": 2,
        "title": "过桥",
        "chapter_ids": [2],
    }
    before = _scene_source_fingerprint(
        scene,
        [{"chapter_index": 2, "content": "沈砚走上石桥。"}],
    )
    after = _scene_source_fingerprint(
        scene,
        [{"chapter_index": 2, "content": "沈砚离开石桥。"}],
    )

    assert before != after


def test_imports_map_candidate_path_uses_only_stable_world_seams() -> None:
    imports_root = Path(__file__).resolve().parents[1]
    sources = [
        (imports_root / "map_observation_candidates.py").read_text(),
        (imports_root / "entity_extraction" / "scene_entity_persistence.py").read_text(),
    ]
    combined = "\n".join(sources)
    assert "from modules.world.contracts import" in combined
    assert (
        "from modules.world.facade import create_map_observation_candidates" in combined
    )
    for forbidden in (
        "modules.world.map_models",
        "modules.world.map_repositories",
        "modules.world.map_schemas",
        "modules.world.services",
    ):
        assert forbidden not in combined
