from __future__ import annotations

import pytest

from modules.story.world_progression_schemas import (
    ProgressionKnowledgeUpdate,
    ProgressionStepResolution,
)
from modules.story.world_progression_tasks import _apply_candidate_updates

SOURCE = "00000000-0000-0000-0000-000000000001"
RECEIVER = "00000000-0000-0000-0000-000000000002"
EVENT = "event-claim-1"


def _resolution() -> ProgressionStepResolution:
    return ProgressionStepResolution(
        story_time_text="约一周",
        narrative_summary="有人声称港口已封锁。",
        outcomes={},
        knowledge_updates=[
            ProgressionKnowledgeUpdate(
                receiver_id=RECEIVER,
                subject_key="port_closed",
                statement="港口已封锁",
                modality="reported_claim",
                source_actor_id=SOURCE,
                source_event_id=EVENT,
            )
        ],
    )


def test_reported_claim_must_come_from_a_visible_successful_speech_event() -> None:
    state = {
        "candidate_status": {},
        "candidate_attitudes": {},
        "candidate_knowledge": {},
        "candidate_resources": {},
    }
    event = {
        EVENT: {
            "event": {
                "actor_id": SOURCE,
                "truth": "spoken_claim",
                "outcome": "succeeded",
            },
            "observers": {f"object:{RECEIVER}"},
        }
    }
    result = _apply_candidate_updates(
        state,
        _resolution(),
        participants={SOURCE, RECEIVER},
        source_ids=set(),
        event_visibility=event,
        route_ids=set(),
        resource_keys=set(),
        targets={},
        entity_ids=set(),
    )
    claim = result["candidate_knowledge"][f"{RECEIVER}:port_closed"]
    assert claim["modality"] == "reported_claim"
    assert claim["source_actor_id"] == SOURCE


@pytest.mark.parametrize(
    "event",
    [
        None,
        {
            "event": {
                "actor_id": SOURCE,
                "truth": "spoken_claim",
                "outcome": "failed",
            },
            "observers": {f"object:{RECEIVER}"},
        },
        {
            "event": {
                "actor_id": RECEIVER,
                "truth": "spoken_claim",
                "outcome": "succeeded",
            },
            "observers": {f"object:{RECEIVER}"},
        },
        {
            "event": {
                "actor_id": SOURCE,
                "truth": "spoken_claim",
                "outcome": "succeeded",
            },
            "observers": {f"object:{SOURCE}"},
        },
    ],
)
def test_reported_claim_rejects_missing_or_nonrecipient_speech(event) -> None:
    event_visibility = {EVENT: event} if event else {}
    with pytest.raises(ValueError, match="传闻必须来自接收者可见"):
        _apply_candidate_updates(
            {
                "candidate_status": {},
                "candidate_attitudes": {},
                "candidate_knowledge": {},
                "candidate_resources": {},
            },
            _resolution(),
            participants={SOURCE, RECEIVER},
            source_ids=set(),
            event_visibility=event_visibility,
            route_ids=set(),
            resource_keys=set(),
            targets={},
            entity_ids=set(),
        )


def test_reported_claim_contract_requires_both_speaker_and_event() -> None:
    with pytest.raises(ValueError, match="说法来源人物与当前可见事件"):
        ProgressionKnowledgeUpdate(
            receiver_id=RECEIVER,
            subject_key="port_closed",
            statement="港口已封锁",
            modality="reported_claim",
            source_actor_id=SOURCE,
        )
