"""Integration coverage for both typed map-proposal persistence paths."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.imports.adoption_policy import build_authorization_snapshot
from modules.imports.entity_extraction.scene_entity_extraction import (
    SceneEntityExtractionService,
)
from modules.imports.entity_extraction.scene_entity_single_scene import (
    SingleSceneEntityExtractor,
)
from modules.imports.llm_schemas import (
    ExtractedCharacterLocationProposal,
    ExtractedEventLocationProposal,
    Phase2WorldExtractionOutput,
    SceneEntityExtractionOutput,
)
from modules.imports.phase2_world_extraction import (
    Phase2WorldExtractor,
    _WindowWorldResult,
)
from modules.imports.scene_planning import SceneWindowPlan
from modules.outline.facade import create_scene
from modules.project.models import Project
from modules.world.map_models import MapObservation


def _authorization(novel_id: str, *, end_chapter: int = 2) -> dict:
    return build_authorization_snapshot(
        novel_id=novel_id,
        start_chapter=1,
        end_chapter=end_chapter,
        adoption_policy="user_authorized_pipeline",
        authorization_confirmed=True,
    )


@pytest.mark.asyncio
async def test_single_scene_path_persists_typed_candidate_through_stable_facade(
    db_session: AsyncSession,
) -> None:
    novel_uuid = uuid.uuid4()
    novel_id = str(novel_uuid)
    db_session.add(Project(id=novel_uuid, title="single scene typed map proposal"))
    await db_session.flush()
    scene = await create_scene(
        db_session,
        novel_id,
        {"scene_index": 1, "title": "抵达青石镇", "status": "canonical"},
    )
    service = SceneEntityExtractionService()
    extraction = SceneEntityExtractionOutput(
        map_observation_proposals=[
            ExtractedCharacterLocationProposal(
                proposal_type="character_location",
                character_name="沈砚",
                location_name="青石镇",
                quote="沈砚走进青石镇。",
                confidence=0.91,
            )
        ]
    )

    with (
        patch.object(
            service,
            "_load_scene_chapters",
            autospec=True,
            return_value="沈砚走进青石镇。",
        ),
        patch.object(
            service,
            "_create_phase2_snapshot",
            autospec=True,
            return_value=SimpleNamespace(id=None),
        ),
        patch.object(
            service,
            "_call_llm_extraction",
            autospec=True,
            return_value=extraction,
        ),
        patch.object(
            service,
            "_persist_entities",
            autospec=True,
            return_value=0,
        ),
        patch.object(
            service,
            "_persist_relations",
            autospec=True,
            return_value=0,
        ),
        patch.object(
            service,
            "_record_deltas",
            autospec=True,
            return_value=0,
        ),
        patch.object(
            service,
            "_phase2_scene_llm_timeout_seconds",
            autospec=True,
            return_value=5.0,
        ),
        patch("modules.memory.facade.capture_snapshot", autospec=True),
    ):
        result = await SingleSceneEntityExtractor(service).process(
            db_session,
            novel_id,
            scene,
            0,
            "",
            [],
            set(),
            workflow_id="workflow-single-scene-map",
            authorization_snapshot=_authorization(novel_id),
        )

    observations = list(
        (
            await db_session.execute(
                select(MapObservation).where(MapObservation.novel_id == novel_uuid)
            )
        )
        .scalars()
        .all()
    )
    assert result["map_observation_candidates"] == {"created": 1, "reused": 0}
    assert len(observations) == 1
    assert str(observations[0].scene_id) == scene["id"]
    assert observations[0].value_json["proposal_type"] == "character_location"
    assert observations[0].source_ref["workflow_id"] == "workflow-single-scene-map"


@pytest.mark.asyncio
async def test_window_path_persists_proposal_only_against_owned_scene(
    db_session: AsyncSession,
) -> None:
    novel_uuid = uuid.uuid4()
    novel_id = str(novel_uuid)
    db_session.add(Project(id=novel_uuid, title="window typed map proposal"))
    await db_session.flush()
    overlap_scene = await create_scene(
        db_session,
        novel_id,
        {"scene_index": 1, "title": "重叠 Scene", "status": "canonical"},
    )
    owned_scene = await create_scene(
        db_session,
        novel_id,
        {"scene_index": 2, "title": "当前 Scene", "status": "canonical"},
    )
    window = SceneWindowPlan(
        window_index=1,
        window_id="phase2-window-1",
        covered_start=1,
        covered_end=2,
        owned_start=2,
        owned_end=2,
        chapter_indices=[1, 2],
        owned_chapter_indices=[2],
    )
    output = Phase2WorldExtractionOutput(
        map_observation_proposals=[
            ExtractedEventLocationProposal(
                proposal_type="event_location",
                event_name="旧信之约",
                location_name="石桥",
                quote="旧信之约发生在石桥。",
                confidence=0.88,
                supporting_scene_ids=[overlap_scene["id"], owned_scene["id"]],
            )
        ]
    )
    extractor = Phase2WorldExtractor(AsyncMock())
    result = _WindowWorldResult(
        window=window,
        output=output,
        final_status="success",
        owned_scene_ids=[owned_scene["id"]],
    )

    with patch.object(
        extractor._legacy,
        "_phase2_flush_with_timeout",
        autospec=True,
        return_value={"degraded": False},
    ):
        persisted = await extractor._persist_outputs(
            db_session,
            novel_id,
            [result],
            [overlap_scene, owned_scene],
            [
                {"chapter_index": 1, "content": "重叠 Scene 正文"},
                {"chapter_index": 2, "content": "当前 Scene 的精确正文"},
            ],
            workflow_id="workflow-window-map",
            authorization_snapshot=_authorization(novel_id),
        )

    observation = await db_session.scalar(
        select(MapObservation).where(MapObservation.novel_id == novel_uuid)
    )
    assert persisted["map_observation_candidates_created"] == 1
    assert persisted["map_observation_candidates_reused"] == 0
    assert observation is not None
    assert str(observation.scene_id) == owned_scene["id"]
    assert observation.source_chapter_index == 2
    assert observation.source_ref["scene_source_fingerprint"]
    assert observation.value_json["proposal_type"] == "event_location"
