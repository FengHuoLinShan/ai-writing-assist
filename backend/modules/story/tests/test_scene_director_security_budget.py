from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from infrastructure.llm.schemas import (
    AIChargeState,
    AIRequestOutcome,
    AIStepAttemptV1,
)
from infrastructure.llm.workflow_budget import AIRunEnvelope, new_ai_run_envelope
from modules.story.director_budget import budget_stop_reason, preview_director_budget
from modules.story.director_consistency import (
    build_consistency,
    validate_candidate_events,
    validate_intents,
    validate_material_references,
)
from modules.story.director_context import _story_card_status
from modules.story.director_schemas import (
    DirectorAngle,
    DirectorCandidateEvent,
    DirectorMaterial,
    DirectorPerformance,
    DirectorPerformanceBasis,
)
from modules.story.director_tasks import (
    _apply_angle_material_availability,
    _fit_packet,
    _rewrite_one_character,
    _validate_performance_basis,
    _visible_typed_references,
)
from modules.story.simulation_v3 import SimulationIntentDraft, SimulationReference


def _base_envelope(*, request_limit: int = 10, seconds: int = 100) -> AIRunEnvelope:
    now = datetime.now(UTC)
    return new_ai_run_envelope(
        operation_id=str(uuid4()),
        run_id=str(uuid4()),
        root_capability_id="story.scene_director",
        novel_id=str(uuid4()),
        request_limit=request_limit,
        budget_mode="bounded",
        token_limit=10_000,
        started_at=now,
        deadline_at=now + timedelta(seconds=seconds),
    )


def _performance(*basis: DirectorPerformanceBasis) -> DirectorPerformance:
    return DirectorPerformance(
        character_id=str(uuid4()),
        action="抬手挡住门口",
        expression="眉间收紧",
        body_language="侧身守住门框",
        voice_and_dialogue="压低声音说：先别进来。",
        subtext="不愿让对方看见屋内",
        motive_and_emotion="担心秘密暴露",
        trigger_and_defense="听见脚步后转为防御",
        attention="门外脚步",
        ignored="桌上散落的纸",
        change_from_previous="从回避转为阻拦",
        basis=list(basis),
    )


def test_budget_preview_returns_explicit_ranges_and_default_round():
    source = {
        "source_hash": "a" * 64,
        "author_brief": {"omissions": []},
        "scene_id": str(uuid4()),
        "scene_context": {},
        "role_briefs": {
            str(uuid4()): {
                "brief": {
                    "world_items": [],
                    "continuity_items": [],
                    "pattern_items": [],
                    "fingerprint": "b" * 64,
                },
                "style_anchors": [],
                "known_participant_ids": [],
            }
        },
    }
    request = SimpleNamespace(
        scene_id=source["scene_id"],
        character_ids=[str(uuid4())],
        related_object_ids=[],
        primary_character_ids=[],
        rounds=1,
        instructions="",
        intervention="",
        public_stimulus="",
    )
    actor_id = str(uuid4())
    request.character_ids = [actor_id]
    source["role_briefs"] = {
        actor_id: {
            "brief": {
                "world_items": [],
                "continuity_items": [],
                "pattern_items": [],
                "fingerprint": "b" * 64,
            },
            "style_anchors": [],
            "known_participant_ids": [],
        }
    }
    preview = preview_director_budget(request, source)
    assert len(preview["preview_hash"]) == 64
    assert preview["rounds"] == 1
    assert preview["request_count"]["minimum"] <= preview["request_count"]["maximum"]
    assert preview["token_count"]["minimum"] <= preview["token_count"]["maximum"]
    assert preview["time_seconds"]["maximum"] > 0
    assert "金额" in preview["possible_charge"]


@pytest.mark.asyncio
async def test_rewrite_checkpoint_failure_stops_before_any_provider_call(monkeypatch):
    actor = str(uuid4())
    card = _performance(
        DirectorPerformanceBasis(source_kind="director_inference", note="合成候选")
    )
    card.character_id = actor
    checkpoint = AsyncMock(side_effect=RuntimeError("checkpoint unavailable"))
    provider = AsyncMock(side_effect=AssertionError("provider must stay offline"))
    monkeypatch.setattr(
        "modules.story.director_tasks.checkpoint_handler_session", checkpoint
    )
    monkeypatch.setattr(
        "modules.story.director_tasks.open_project_snapshot_llm_client", provider
    )
    with pytest.raises(RuntimeError, match="checkpoint unavailable"):
        await _rewrite_one_character(
            object(),
            object(),
            SimpleNamespace(novel_id=uuid4()),
            SimpleNamespace(request_json={"public_stimulus": ""}),
            SimpleNamespace(rewrite_character_id=actor, intervention="", instructions=""),
            SimpleNamespace(
                output_json={"performances": [card.model_dump(mode="json")]},
                state_json={},
                round_number=1,
                parent_round_id=None,
                id=uuid4(),
            ),
            {
                "role_briefs": {
                    actor: {
                        "brief": {
                            "world_items": [],
                            "continuity_items": [],
                            "pattern_items": [],
                        },
                        "style_anchors": [],
                        "known_participant_ids": [],
                    }
                }
            },
            source_changed=False,
            input_limit=4000,
            acknowledged_unknown=0,
            baseline_requests_started=0,
            baseline_attempts_overflow=0,
            envelope=_base_envelope(),
        )
    checkpoint.assert_awaited_once()
    provider.assert_not_awaited()


def test_budget_stops_at_eighty_percent_and_uses_per_continuation_unknown_baseline():
    envelope = _base_envelope(request_limit=5)
    envelope._envelope.requests_started = 4
    assert budget_stop_reason(envelope) == "request_budget_80_percent"

    envelope = _base_envelope(request_limit=10)
    original = envelope.snapshot()
    old_attempt = AIStepAttemptV1(
        step_name="scene-director.intent",
        step_capability_id="story.scene_director",
        call_kind="structured",
        purpose="primary",
        request_index=1,
        started_at=original.started_at,
        outcome=AIRequestOutcome.unknown,
        charge_state=AIChargeState.possible,
    )
    envelope._envelope.requests_started = 1
    envelope._envelope.requests_unknown = 1
    envelope._envelope.usage_complete = False
    envelope._envelope.charge_state = AIChargeState.possible
    envelope._envelope.recent_attempts = [old_attempt]
    # The author acknowledged the old request before starting this branch.
    assert (
        budget_stop_reason(
            envelope,
            acknowledged_unknown=1,
            baseline_requests_started=1,
            baseline_recent_attempts_overflow=0,
        )
        is None
    )

    new_attempt = old_attempt.model_copy(
        update={"request_index": 2, "outcome": AIRequestOutcome.unknown}
    )
    envelope._envelope.requests_started = 2
    envelope._envelope.requests_unknown = 2
    envelope._envelope.recent_attempts.append(new_attempt)
    assert (
        budget_stop_reason(
            envelope,
            acknowledged_unknown=1,
            baseline_requests_started=1,
            baseline_recent_attempts_overflow=0,
        )
        == "provider_result_unknown"
    )


def test_budget_stops_when_new_attempt_history_overflows_or_deadline_is_near():
    envelope = _base_envelope(request_limit=20)
    envelope._envelope.recent_attempts_overflow = 2
    assert (
        budget_stop_reason(
            envelope,
            acknowledged_unknown=0,
            baseline_requests_started=0,
            baseline_recent_attempts_overflow=1,
        )
        == "usage_incomplete"
    )

    envelope = _base_envelope(request_limit=20, seconds=100)
    envelope._envelope.started_at = datetime.now(UTC) - timedelta(seconds=85)
    envelope._envelope.deadline_at = envelope._envelope.started_at + timedelta(
        seconds=100
    )
    assert budget_stop_reason(envelope) == "time_budget_80_percent"


def test_intent_cannot_reference_globally_known_but_role_private_object():
    actor_id, secret_object_id = str(uuid4()), str(uuid4())
    intent = SimulationIntentDraft(
        kind="inspect",
        action="查看密室中的盒子",
        resource=SimulationReference(kind="object", id=secret_object_id),
    ).bind(
        intent_id="round:actor",
        actor=SimulationReference(kind="object", id=actor_id),
    )
    with pytest.raises(ValueError, match="当前可知资料"):
        validate_intents(
            [intent],
            participant_ids={actor_id},
            known_participant_ids={actor_id: set()},
            role_visible_object_ids={actor_id: {actor_id}},
            role_visible_map_node_ids={actor_id: set()},
            existing_object_ids={actor_id, secret_object_id},
            existing_map_node_ids=set(),
        )


def test_typed_role_references_match_the_capacity_fitted_packet():
    actor_id, object_id = str(uuid4()), str(uuid4())
    source = {
        "role_briefs": {
            actor_id: {
                "known_participant_ids": [],
                "style_anchors": [],
                "brief": {
                    "world_items": [
                        {
                            "entity_id": object_id,
                            "revision_id": "role-visible-object",
                            "content": "一段角色可知资料。" * 40,
                        }
                    ],
                    "continuity_items": [],
                    "pattern_items": [],
                },
            }
        }
    }
    state = {"locations": {}, "resource_holders": {}, "observations": {}}
    visible_without_stimulus, _ = _visible_typed_references(
        source,
        actor_id,
        state,
        public_stimulus="",
        input_limit=1_000,
        known_object_ids={actor_id, object_id},
        known_map_node_ids=set(),
    )
    visible_with_stimulus, _ = _visible_typed_references(
        source,
        actor_id,
        state,
        public_stimulus="公共刺激" * 900,
        input_limit=1_000,
        known_object_ids={actor_id, object_id},
        known_map_node_ids=set(),
    )

    assert object_id in visible_without_stimulus
    assert object_id not in visible_with_stimulus
    assert (
        source["role_briefs"][actor_id]["brief"]["world_items"][0]["entity_id"]
        == object_id
    )


def test_performance_basis_rejects_author_only_source_and_binds_visible_fingerprint():
    secret_id = "author-only-checkpoint"
    visible_id = "role-checkpoint"
    card = _performance(
        DirectorPerformanceBasis(
            source_kind="continuity", source_id=secret_id, note="来自台账"
        ),
        DirectorPerformanceBasis(
            source_kind="continuity", source_id=visible_id, note="角色已知"
        ),
    )
    result = _validate_performance_basis(
        card,
        allowed_sources={
            visible_id: {"kind": "continuity", "fingerprint": "b" * 64},
        },
        allowed_events={},
        role_fingerprint="c" * 64,
    )
    assert result.basis[0].source_kind == "director_inference"
    assert result.basis[0].source_id is None
    assert result.basis[1].source_kind == "continuity"
    assert result.basis[1].source_fingerprint
    assert result.basis[1].source_fingerprint != "b" * 64


def test_material_perception_is_derived_from_role_sources_not_model_claims():
    actor_id = str(uuid4())
    material = DirectorMaterial(
        material_id="hidden-note",
        category="object",
        content="桌下藏着一封信",
        source_kind="continuity",
        source_ids=["author-only-source"],
        perceiver_ids=[actor_id],
    )
    result = validate_material_references(
        [material],
        participant_ids={actor_id},
        known_event_ids=set(),
        known_event_index={},
        event_observers={},
        known_source_index={
            "author-only-source": {"kind": "continuity", "fingerprint": "d" * 64}
        },
        role_source_indexes={actor_id: {}},
        existing_object_ids=set(),
        existing_map_node_ids=set(),
    )[0]
    assert result.perceiver_ids == []
    assert result.disabled_for_character_ids == [actor_id]
    assert result.perception_status == "impossible"


def test_character_angle_greys_every_material_the_pov_cannot_perceive():
    actor_id, other_id = str(uuid4()), str(uuid4())
    angle = DirectorAngle(
        angle_id="pov",
        label="贴近人物",
        viewpoint_kind="character",
        viewpoint_character_id=actor_id,
        narrative_distance="close",
        focus="人物反应",
        detail_and_pacing="详写观察",
    )
    materials = [
        DirectorMaterial(
            material_id="hidden-inner",
            category="mood",
            content="另一人的恐惧",
            source_kind="continuity",
            internal_character_id=other_id,
            senses=["inner"],
            disabled_for_character_ids=[actor_id],
        ),
        DirectorMaterial(
            material_id="visible-sound",
            category="environment",
            content="钟声",
            source_kind="observed_event",
            senses=["sound"],
            perceiver_ids=[actor_id],
        ),
    ]

    _apply_angle_material_availability([angle], materials, {actor_id, other_id})

    assert angle.disabled_material_ids == ["hidden-inner"]


def test_event_observer_receipts_allow_only_observers_to_perceive():
    actor_id, bystander_id, event_id = str(uuid4()), str(uuid4()), "event-1"
    material = DirectorMaterial(
        material_id="heard-line",
        category="environment",
        content="门外传来一句话",
        source_kind="observed_event",
        source_ids=[event_id],
        perceiver_ids=[actor_id, bystander_id],
        senses=["sound"],
    )
    result = validate_material_references(
        [material],
        participant_ids={actor_id, bystander_id},
        known_event_ids={event_id},
        known_event_index={event_id: {"fingerprint": "e" * 64}},
        event_observers={event_id: {f"object:{actor_id}"}},
        known_source_index={},
        role_source_indexes={actor_id: {}, bystander_id: {}},
        existing_object_ids=set(),
        existing_map_node_ids=set(),
    )[0]
    assert result.perceiver_ids == [actor_id]
    assert result.disabled_for_character_ids == [bystander_id]
    assert result.perception_status == "known"


def test_unproven_story_card_stays_out_of_character_packet():
    actor_id = str(uuid4())
    scene_id = str(uuid4())
    revision_id = str(uuid4())
    status = _story_card_status(
        {
            "character_cards": [
                {
                    "character_id": actor_id,
                    "scene_id": scene_id,
                    "status": "active",
                    "stale": False,
                    "revision": {
                        "id": revision_id,
                        "scene_id": scene_id,
                        "character_id": actor_id,
                        "is_current": True,
                        "status": "accepted",
                        "content_hash": "f" * 64,
                        "content": {
                            "version": "character_card.v1",
                            "knowledge": ["他知道地下室藏着尸体"],
                            "author_notes": "未来剧情秘密",
                        },
                    },
                }
            ]
        },
        actor_id,
        scene_id,
    )
    assert status["available"] is True
    assert status["omitted"] is True
    assert "knowledge" not in status
    assert "author_notes" not in status


def test_author_examples_are_only_added_to_director_authored_performance_steps():
    actor_id = str(uuid4())
    source = {
        "author_examples": {"positive_example": "作者示例中的潜在剧情细节"},
        "role_briefs": {
            actor_id: {
                "brief": {
                    "world_items": [],
                    "continuity_items": [],
                    "pattern_items": [],
                },
                "style_anchors": [],
                "known_participant_ids": [],
            }
        },
    }

    actor_packet, _ = _fit_packet(source, actor_id, "", 10_000)
    performance_packet, _ = _fit_packet(
        source,
        actor_id,
        "",
        10_000,
        include_author_examples=True,
    )

    assert "潜在剧情细节" not in actor_packet
    assert "潜在剧情细节" in performance_packet


def test_candidate_event_cannot_write_simulation_state_or_claim_unknown_identity():
    event = DirectorCandidateEvent(
        candidate_id="arrival",
        label="陌生人到来",
        description="一名尚未建立身份的陌生人走进屋里。",
        references=[
            SimulationReference(
                kind="candidate", id="stranger", label="陌生人"
            ).model_dump(mode="json")
        ],
    )
    result = validate_candidate_events(
        [event],
        existing_object_ids=set(),
        existing_map_node_ids=set(),
        known_source_index={},
        known_event_index={},
    )
    assert result[0].candidate_only is True
    assert result[0].applied_to_state is False
    with pytest.raises(ValidationError):
        DirectorCandidateEvent(
            candidate_id="arrival",
            label="陌生人到来",
            description="加入场景人物列表。",
            candidate_only=False,
        )


def test_consistency_reports_exact_scene_and_world_validity_conflicts():
    actor_id = str(uuid4())
    continuity_items = [
        {
            "entity_id": actor_id,
            "dimension": "entities",
            "field": "life_state",
            "value": value,
            "checkpoint_id": checkpoint_id,
            "provenance": {"status": "exact"},
        }
        for value, checkpoint_id in (("alive", "checkpoint-a"), ("dead", "checkpoint-b"))
    ]

    consistency = build_consistency(
        source={
            "author_brief": {
                "continuity_items": continuity_items,
                "omissions": [],
                "coverage": "partial",
            },
            "object_validity_notices": [
                {
                    "notice_key": "world.object_validity:dossier:entry-1",
                    "basis_fingerprint": "a" * 64,
                    "validity_decision": "author_priority",
                    "target": {"entity_id": actor_id, "entry_id": "entry-1"},
                },
                {
                    "notice_key": "world.object_validity:map:node-1:feature:feature-1",
                    "basis_fingerprint": "b" * 64,
                    "validity_decision": "gap",
                    "target": {"node_id": "node-1"},
                },
            ],
        },
        intents=[],
        candidates={},
        materials=[],
        candidate_events=[],
        object_ids={actor_id},
        map_node_ids=set(),
    )

    conflicts = [item for item in consistency.findings if item.severity == "conflict"]
    assert {item.field for item in conflicts} == {
        "entities:life_state",
        "author_validity",
    }
    fact_conflict = next(
        item for item in conflicts if item.field == "entities:life_state"
    )
    assert {item["id"] for item in fact_conflict.source_refs} == {
        "checkpoint-a",
        "checkpoint-b",
    }
    assert "当前精确来源字段：entities:life_state" in consistency.checked_facts
    assert consistency.coverage == "partial"
    assert "当前精确来源字段：world:author_validity" in consistency.checked_facts
    assert any("地图声明作者有效期" in item for item in consistency.unavailable_checks)
    assert any(
        item.field == "author_validity" and item.severity == "unknown"
        for item in consistency.findings
    )
