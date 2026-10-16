from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from core.errors import ConflictError
from infrastructure.llm.workflow_budget import new_ai_run_envelope
from modules.story.world_progression_continuous import _lineage_goal_step
from modules.story.world_progression_engine import derive_progression_metrics
from modules.story.world_progression_hooks_api import _find_adopted_operation
from modules.story.world_progression_schemas import (
    ProgressionBudgetPreviewRequest,
    ProgressionKnowledgeUpdate,
    ProgressionStatusUpdate,
    ProgressionStepResolution,
    ProgressionTargetOutcome,
    ProgressionTargetPath,
)
from modules.story.world_progression_tasks import (
    _actor_view_packet,
    _apply_candidate_updates,
    _budget_stop,
    _goals_reached,
    _monotonic_envelope,
    _rolling_summary,
)

SOURCE = "00000000-0000-0000-0000-000000000001"
RECEIVER = "00000000-0000-0000-0000-000000000002"
EVENT = "event-claim-1"
TARGET = "00000000-0000-0000-0000-000000000003"


def test_actor_packet_excludes_author_summary_and_other_actor_observations() -> None:
    packet = _actor_view_packet(
        {"viewpoint": {"kind": "character"}, "brief": {"safe": "own"}},
        {
            "rolling_summary": {"latest_resolution": "author-only future goal"},
            "observations": {
                f"object:{SOURCE}": [{"action": "own visible action"}],
                f"object:{RECEIVER}": [{"action": "other private action"}],
            },
            "locations": {f"object:{SOURCE}": "object:place"},
            "resource_holders": {},
            "candidate_knowledge": {
                f"{SOURCE}:promise": {
                    "statement": "own promise",
                    "modality": "direct_observation",
                },
                f"{SOURCE}:guess": {
                    "statement": "author-only uncertain future",
                    "modality": "uncertain",
                },
                f"{RECEIVER}:secret": {
                    "statement": "other secret",
                    "modality": "reported_claim",
                },
            },
        },
        SOURCE,
        "auto",
    )
    assert packet["own_observations"] == [{"action": "own visible action"}]
    assert "rolling_summary" not in packet
    assert "author-only future goal" not in str(packet)
    assert "other private action" not in str(packet)
    assert "own promise" in str(packet)
    assert "author-only uncertain future" not in str(packet)
    assert "other secret" not in str(packet)


def test_step_narrative_and_rolling_author_summary_stay_separate() -> None:
    result = _rolling_summary(
        {"revision": 3},
        ProgressionStepResolution(
            story_time_text="约一天",
            narrative_summary="本步相遇。",
            rolling_summary="前情仍在，今天相遇。",
            outcomes={},
        ),
        [],
    )
    assert result["cumulative_summary"] == "前情仍在，今天相遇。"
    assert "本步相遇。" not in str(result)


def test_resume_acknowledges_only_prior_unknown_and_preserves_long_run_budget() -> None:
    now = datetime.now(UTC)
    envelope = new_ai_run_envelope(
        operation_id=str(uuid4()),
        run_id=str(uuid4()),
        root_capability_id="story.world_progression",
        novel_id=str(uuid4()),
        request_limit=1000,
        token_limit=1000000,
        budget_mode="bounded",
        started_at=now,
        deadline_at=now + timedelta(hours=8),
    )
    envelope._envelope.requests_started = 65
    envelope._envelope.requests_settled = 64
    envelope._envelope.requests_unknown = 1
    envelope._envelope.usage_complete = False
    envelope._envelope.recent_attempts_overflow = 1
    assert _budget_stop(envelope) == "provider_result_unknown"
    assert (
        _budget_stop(envelope, acknowledged_unknown=1, baseline_requests_started=65)
        is None
    )
    envelope._envelope.requests_started += 1
    envelope._envelope.requests_unknown += 1
    assert (
        _budget_stop(envelope, acknowledged_unknown=1, baseline_requests_started=65)
        == "provider_result_unknown"
    )


def test_resume_rejects_root_identity_or_deadline_rewrite() -> None:
    now = datetime.now(UTC).isoformat()
    prior = {"run_id": "root", "started_at": now, "requests_started": 4}
    with pytest.raises(ValueError, match="根身份或时限"):
        _monotonic_envelope(
            prior,
            {**prior, "started_at": (datetime.now(UTC) + timedelta(days=1)).isoformat()},
        )
    with pytest.raises(ValueError, match="旧预算快照"):
        _monotonic_envelope(prior, {**prior, "requests_started": 3})


def _resolution() -> ProgressionStepResolution:
    return ProgressionStepResolution(
        story_time_text="约一周",
        narrative_summary="有人声称港口已封锁。",
        rolling_summary="港口封锁仍是传闻。",
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
        current_event_ids={EVENT},
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
            current_event_ids={EVENT},
            targets={},
            entity_ids=set(),
        )


def test_candidate_state_change_needs_a_current_simulated_event() -> None:
    resolution = ProgressionStepResolution(
        story_time_text="约一天",
        narrative_summary="有人尝试改变计划。",
        rolling_summary="计划仍未确定。",
        outcomes={},
        status_updates=[
            ProgressionStatusUpdate(
                actor_id=SOURCE,
                field="goal",
                value="改变计划",
                basis_ids=["source-from-dossier"],
            )
        ],
    )
    with pytest.raises(ValueError, match="必须引用本步成功的模拟事件"):
        _apply_candidate_updates(
            {},
            resolution,
            participants={SOURCE},
            source_ids={"source-from-dossier"},
            event_visibility={},
            route_ids=set(),
            resource_keys=set(),
            current_event_ids={EVENT},
            targets={},
            entity_ids=set(),
        )


def test_failed_simulated_event_cannot_change_candidate_status() -> None:
    resolution = ProgressionStepResolution(
        story_time_text="约一天",
        narrative_summary="尝试失败。",
        rolling_summary="尝试失败，目标未变。",
        outcomes={},
        status_updates=[
            ProgressionStatusUpdate(
                actor_id=SOURCE,
                field="goal",
                value="目标已达成",
                basis_ids=[EVENT],
            )
        ],
    )
    with pytest.raises(ValueError, match="必须引用本步成功的模拟事件"):
        _apply_candidate_updates(
            {},
            resolution,
            participants={SOURCE},
            source_ids=set(),
            event_visibility={
                EVENT: {"event": {"outcome": "failed"}, "observers": {f"object:{SOURCE}"}}
            },
            route_ids=set(),
            resource_keys=set(),
            current_event_ids={EVENT},
            targets={},
            entity_ids=set(),
        )


def test_private_event_cannot_change_unaware_actors_role_state() -> None:
    resolution = ProgressionStepResolution(
        story_time_text="约一天",
        narrative_summary="有人私下改变计划。",
        rolling_summary="另一人仍不知道这项计划。",
        outcomes={},
        status_updates=[
            ProgressionStatusUpdate(
                actor_id=RECEIVER,
                field="goal",
                value="已知对方的秘密计划",
                basis_ids=[EVENT],
            )
        ],
    )
    with pytest.raises(ValueError, match="必须引用本步成功的模拟事件"):
        _apply_candidate_updates(
            {},
            resolution,
            participants={SOURCE, RECEIVER},
            source_ids=set(),
            event_visibility={
                EVENT: {
                    "event": {"actor_id": SOURCE, "outcome": "succeeded"},
                    "observers": {f"object:{SOURCE}"},
                }
            },
            route_ids=set(),
            resource_keys=set(),
            current_event_ids={EVENT},
            targets={},
            entity_ids=set(),
        )


def test_goal_completion_requires_successful_event_and_counts_only_transition() -> None:
    resolution = ProgressionStepResolution(
        story_time_text="约一天",
        narrative_summary="目标达成。",
        rolling_summary="目标达成且仍有效。",
        outcomes={},
        goal_outcomes=[
            ProgressionTargetOutcome(
                target_id=TARGET, status="completed", reason="已达成"
            )
        ],
        target_paths=[
            ProgressionTargetPath(
                target_id=TARGET,
                actor_ids=[SOURCE],
                basis_ids=[EVENT],
                rationale="行动达成目标",
            )
        ],
    )
    visibility = {
        EVENT: {
            "event": {"actor_id": SOURCE, "outcome": "failed"},
            "observers": {f"object:{SOURCE}"},
        }
    }
    params = dict(
        participants={SOURCE},
        source_ids=set(),
        event_visibility=visibility,
        route_ids=set(),
        resource_keys=set(),
        current_event_ids={EVENT},
        targets={TARGET: True},
        entity_ids=set(),
    )
    with pytest.raises(ValueError, match="目标完成必须由本步成功事件"):
        _apply_candidate_updates({}, resolution, **params)
    visibility[EVENT]["event"]["outcome"] = "succeeded"
    _apply_candidate_updates({}, resolution, **params)
    previous = {
        "rolling_summary": {
            "candidate_goal_statuses": [{"target_id": TARGET, "status": "completed"}]
        }
    }
    metrics = derive_progression_metrics(
        before_state=previous,
        after_state=previous,
        resolution=resolution.model_dump(mode="json"),
        intersections={"items": []},
    )
    assert metrics["goals_completed"] == 0


def test_explicit_step_count_does_not_implicitly_stop_at_partial_goal() -> None:
    request = ProgressionBudgetPreviewRequest(
        novel_id=SOURCE,
        request_limit=20,
        token_limit=20000,
        time_budget_seconds=3600,
        participants=[{"id": SOURCE}],
        run_policy="n_steps",
        steps=3,
    )
    assert request.stop_at_goal is False
    assert not _goals_reached(
        {"goal_outcomes": [{"target_id": TARGET, "status": "completed"}]},
        {
            "targets": [
                {"id": TARGET, "must_reach": True},
                {"id": RECEIVER, "must_reach": True},
            ]
        },
    )


@pytest.mark.asyncio
async def test_planned_scene_hook_adoption_receipt_is_idempotent() -> None:
    project_id, scene_id, operation_id = (str(uuid4()) for _ in range(3))
    row = SimpleNamespace(
        id=scene_id,
        structure_meta={
            "provenance": {
                "world_progression_operation_id": operation_id,
                "world_progression_preview_hash": "a" * 64,
            }
        },
    )

    class Session:
        def __init__(self):
            self.reads = 0

        async def scalars(self, _query):
            self.reads += 1
            return SimpleNamespace(all=lambda: [row] if self.reads == 3 else [])

    receipt = await _find_adopted_operation(
        Session(), project_id, "planned_scene", operation_id, "a" * 64
    )
    assert receipt == {"asset_type": "scene", "asset_id": scene_id, "status": "adopted"}
    with pytest.raises(ConflictError, match="另一钩子或草稿"):
        await _find_adopted_operation(
            Session(), project_id, "planned_scene", operation_id, "b" * 64
        )


@pytest.mark.asyncio
async def test_continuous_goal_reads_its_own_parent_lineage() -> None:
    project_id, root_id = uuid4(), uuid4()
    author_branch_id, light_branch_id, sibling_branch_id = (uuid4() for _ in range(3))
    own_goal = SimpleNamespace(
        id=uuid4(), branch_id=author_branch_id, parent_step_id=None
    )
    light = SimpleNamespace(
        id=uuid4(), branch_id=light_branch_id, parent_step_id=own_goal.id
    )
    sibling_goal = SimpleNamespace(
        id=uuid4(), branch_id=sibling_branch_id, parent_step_id=None
    )
    branches = [
        SimpleNamespace(id=author_branch_id, branch_kind="start"),
        SimpleNamespace(id=light_branch_id, branch_kind="continuous_light_step"),
        SimpleNamespace(id=sibling_branch_id, branch_kind="continue"),
    ]

    class Session:
        def __init__(self):
            self.reads = 0

        async def scalars(self, _query):
            self.reads += 1
            return SimpleNamespace(
                all=lambda: (
                    [own_goal, light, sibling_goal] if self.reads == 1 else branches
                )
            )

    selected = await _lineage_goal_step(
        Session(), SimpleNamespace(id=root_id, novel_id=project_id), light
    )
    assert selected.id == own_goal.id


def test_reported_claim_contract_requires_both_speaker_and_event() -> None:
    with pytest.raises(ValueError, match="说法来源人物与当前可见事件"):
        ProgressionKnowledgeUpdate(
            receiver_id=RECEIVER,
            subject_key="port_closed",
            statement="港口已封锁",
            modality="reported_claim",
            source_actor_id=SOURCE,
        )
