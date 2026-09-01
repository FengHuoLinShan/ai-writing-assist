from __future__ import annotations

import pytest

from modules.imports.llm_schemas import SceneChunk
from modules.imports.scene_fusion import FinalSceneCandidate
from modules.imports.scene_fusion_phase1c import Phase1cSceneFusionService


def _candidate(
    candidate_id: str,
    *,
    chapter: int,
    start: int,
    end: int,
) -> FinalSceneCandidate:
    return FinalSceneCandidate(
        candidate_id=candidate_id,
        phase="phase1b_enrichment",
        title=candidate_id,
        goal=f"goal-{candidate_id}",
        core_conflict=f"conflict-{candidate_id}",
        core_conflict_status="present",
        phase1a_confidence=0.84 if candidate_id == "left" else 0.78,
        boundary_basis=f"basis-{candidate_id}",
        scene_chunks=[
            SceneChunk(
                chapter_index=chapter,
                start_offset=start,
                end_offset=end,
                source_draft_id=f"draft-{chapter}",
                source_content_hash=str(chapter) * 64,
            )
        ],
        source_candidate_ids=[candidate_id],
        source_chapter_indices=[chapter],
        needs_review=False,
    )


def _chapter(chapter: int, content: str) -> dict:
    return {
        "chapter_index": chapter,
        "content": content,
        "source_draft_id": f"draft-{chapter}",
        "source_content_hash": str(chapter) * 64,
    }


def _boundary_result(
    payload: dict,
    *,
    relation: str,
    confidence: float,
    basis: str,
    fusion_intent: str | None = None,
) -> dict:
    return {
        "boundaries": [
            {
                **boundary,
                "relation": relation,
                "fusion_intent": fusion_intent,
                "basis": basis,
                "uncertainties": [],
                "confidence": confidence,
            }
            for boundary in payload["owned_boundaries"]
        ],
        "candidate_concerns": [],
    }


def _synthesis_result(**overrides) -> dict:
    return {
        "title": "融合 Scene",
        "goal": "完成连续行动",
        "core_conflict": "在阻力中完成行动",
        "core_conflict_status": "present",
        "emotional_beat": "压力升高",
        "must_happen": "保留关键决定",
        "must_not_happen": None,
        "narrative_tag": "rising_action",
        "narrative_function": "把连续行动整合为一个因果单元",
        "basis": "完整正文显示这些片段属于同一连续因果单元。",
        "field_evidence": {
            "emotional_beat": ["x"],
            "must_happen": ["x"],
        },
        "uncertain_fields": [],
        "confidence": 0.96,
        **overrides,
    }


@pytest.mark.asyncio
async def test_phase1c_auto_merges_only_high_confidence_exact_pair() -> None:
    async def decide(payload):
        if payload["task"] == "phase1c_scene_synthesis_v2":
            return _synthesis_result(confidence=0.95)
        return _boundary_result(
            payload,
            relation="same_scene",
            fusion_intent="integrate_both",
            confidence=0.95,
            basis="same major narrative objective",
        )

    result = await Phase1cSceneFusionService(decide).run(
        [
            _candidate("left", chapter=1, start=0, end=20),
            _candidate("right", chapter=1, start=20, end=40),
        ],
        [_chapter(1, "x" * 50)],
    )

    assert len(result.candidates) == 1
    assert result.candidates[0].phase == "phase1c_fusion"
    assert [
        (chunk.start_offset, chunk.end_offset)
        for chunk in result.candidates[0].scene_chunks
    ] == [(0, 40)]
    assert result.suggestions == []
    assert result.quality_stats["auto_merged"] == 1
    assert result.candidates[0].core_conflict_status == "present"
    assert result.candidates[0].phase1a_confidence == 0.78
    assert result.candidates[0].boundary_basis == (
        "basis-left basis-right same major narrative objective"
    )


@pytest.mark.asyncio
async def test_phase1c_merge_preserves_nullable_phase1b_metadata() -> None:
    async def decide(payload):
        if payload["task"] == "phase1c_scene_synthesis_v2":
            return _synthesis_result(
                core_conflict=None,
                core_conflict_status="not_applicable",
                must_not_happen=None,
            )
        return _boundary_result(
            payload,
            relation="same_scene",
            fusion_intent="integrate_both",
            confidence=0.96,
            basis="one continuous causal unit",
        )

    left = _candidate("left", chapter=1, start=0, end=20).model_copy(
        update={
            "emotional_beat": None,
            "must_happen": "保留左侧决定",
            "must_not_happen": None,
            "narrative_tag": "rising_action",
            "narrative_function": "建立行动方向",
            "phase1b_basis": "左侧正文依据",
            "phase1b_field_evidence": {"must_happen": ["x"]},
            "phase1b_field_statuses": {
                "emotional_beat": "not_applicable",
                "must_happen": "present",
                "must_not_happen": "not_applicable",
                "narrative_tag": "present",
            },
            "phase1b_confidence": 0.82,
            "phase1b_context_fingerprint": "a" * 64,
            "phase1b_source_fingerprint": "c" * 64,
        }
    )
    right = _candidate("right", chapter=1, start=20, end=40).model_copy(
        update={
            "emotional_beat": "压力升高",
            "must_happen": None,
            "must_not_happen": None,
            "narrative_tag": "draft",
            "narrative_function": "延续行动后果",
            "phase1b_basis": "右侧正文依据",
            "phase1b_field_evidence": {"emotional_beat": ["x"]},
            "phase1b_field_statuses": {
                "emotional_beat": "present",
                "must_happen": "not_applicable",
                "must_not_happen": "uncertain",
                "narrative_tag": "not_applicable",
            },
            "phase1b_uncertain_fields": ["must_not_happen"],
            "phase1b_confidence": 0.71,
            "phase1b_context_fingerprint": "b" * 64,
            "phase1b_source_fingerprint": "d" * 64,
        }
    )

    result = await Phase1cSceneFusionService(decide).run(
        [left, right],
        [_chapter(1, "x" * 50)],
    )

    merged = result.candidates[0]
    assert merged.emotional_beat == "压力升高"
    assert merged.must_happen == "保留关键决定"
    assert merged.must_not_happen is None
    assert merged.narrative_function == "把连续行动整合为一个因果单元"
    assert merged.phase1b_basis == "完整正文显示这些片段属于同一连续因果单元。"
    assert merged.core_conflict is None or merged.core_conflict == ""
    assert merged.phase1b_field_statuses["core_conflict"] == "not_applicable"
    assert merged.phase1b_field_statuses["must_not_happen"] == "not_applicable"
    assert merged.phase1b_uncertain_fields == []
    assert merged.phase1b_confidence == 0.96
    assert len(merged.phase1b_context_fingerprint) == 64
    assert len(merged.phase1b_source_fingerprint) == 64
    assert merged.phase1b_source_fingerprint not in {"c" * 64, "d" * 64}


@pytest.mark.asyncio
async def test_phase1c_keeps_same_chapter_independent_scenes() -> None:
    async def decide(payload):
        return _boundary_result(
            payload,
            relation="separate",
            confidence=0.98,
            basis="independent major objectives",
        )

    result = await Phase1cSceneFusionService(decide).run(
        [
            _candidate("left", chapter=1, start=0, end=20),
            _candidate("right", chapter=1, start=20, end=40),
        ],
        [_chapter(1, "x" * 50)],
    )

    assert [item.candidate_id for item in result.candidates] == ["left", "right"]
    assert len(result.suggestions) == 1
    assert result.suggestions[0].initial_status == "dismissed"


@pytest.mark.asyncio
async def test_phase1c_low_confidence_action_becomes_durable_suggestion_input() -> None:
    async def decide(payload):
        return _boundary_result(
            payload,
            relation="same_scene",
            fusion_intent="right_is_fragment",
            confidence=0.81,
            basis="right side looks transitional but confidence is insufficient",
        )

    result = await Phase1cSceneFusionService(decide).run(
        [
            _candidate("left", chapter=1, start=0, end=20),
            _candidate("right", chapter=2, start=0, end=20),
        ],
        [
            _chapter(1, "x" * 30),
            _chapter(2, "y" * 30),
        ],
    )

    assert len(result.candidates) == 2
    assert len(result.suggestions) == 1
    assert result.suggestions[0].suggestion_kind == "cross_chapter"
    assert result.suggestions[0].source_candidate_ids == ["left", "right"]


@pytest.mark.asyncio
async def test_phase1c_provider_failure_does_not_flood_author_suggestions() -> None:
    async def fail(_payload):
        raise ValueError("invalid provider contract")

    result = await Phase1cSceneFusionService(fail).run(
        [
            _candidate("one", chapter=1, start=0, end=20),
            _candidate("two", chapter=2, start=0, end=20),
            _candidate("three", chapter=3, start=0, end=20),
        ],
        [
            _chapter(1, "x" * 30),
            _chapter(2, "y" * 30),
            _chapter(3, "z" * 30),
        ],
    )

    assert [item.candidate_id for item in result.candidates] == [
        "one",
        "two",
        "three",
    ]
    assert result.suggestions == []
    assert result.degraded is True
    assert result.quality_stats["failed_calls"] == 1
    assert result.diagnostics[-1]["boundary_pairs"] == [
        {"left_candidate_id": "one", "right_candidate_id": "two"},
        {"left_candidate_id": "two", "right_candidate_id": "three"},
    ]


@pytest.mark.asyncio
async def test_phase1c_can_form_one_scene_across_more_than_two_chapters() -> None:
    async def decide(payload):
        if payload["task"] == "phase1c_scene_synthesis_v2":
            quote = payload["members"][0]["scene_source"][0]["text"][:1]
            return _synthesis_result(
                field_evidence={
                    "emotional_beat": [quote],
                    "must_happen": [quote],
                }
            )
        return _boundary_result(
            payload,
            relation="same_scene",
            fusion_intent="integrate_both",
            confidence=0.96,
            basis="one continuous major objective",
        )

    result = await Phase1cSceneFusionService(decide).run(
        [
            _candidate("one", chapter=1, start=0, end=20),
            _candidate("two", chapter=2, start=0, end=20),
            _candidate("three", chapter=3, start=0, end=20),
        ],
        [
            _chapter(1, "x" * 30),
            _chapter(2, "y" * 30),
            _chapter(3, "z" * 30),
        ],
    )

    assert len(result.candidates) == 1
    assert result.candidates[0].source_chapter_indices == [1, 2, 3]
    assert result.quality_stats["auto_merged"] == 2


@pytest.mark.asyncio
async def test_phase1c_remaps_pending_boundary_after_later_candidate_merges() -> None:
    async def decide(payload):
        if payload["task"] == "phase1c_scene_synthesis_v2":
            quote = payload["members"][0]["scene_source"][0]["text"][:1]
            return _synthesis_result(
                field_evidence={
                    "emotional_beat": [quote],
                    "must_happen": [quote],
                }
            )
        boundaries = []
        for index, boundary in enumerate(payload["owned_boundaries"]):
            boundaries.append(
                {
                    **boundary,
                    "relation": "same_scene",
                    "fusion_intent": "integrate_both",
                    "basis": (
                        "first boundary needs review"
                        if index == 0
                        else "second and third belong together"
                    ),
                    "uncertainties": [],
                    "confidence": 0.80 if index == 0 else 0.96,
                }
            )
        return {"boundaries": boundaries, "candidate_concerns": []}

    result = await Phase1cSceneFusionService(decide).run(
        [
            _candidate("one", chapter=1, start=0, end=20),
            _candidate("two", chapter=2, start=0, end=20),
            _candidate("three", chapter=3, start=0, end=20),
        ],
        [
            _chapter(1, "x" * 30),
            _chapter(2, "y" * 30),
            _chapter(3, "z" * 30),
        ],
    )

    assert len(result.candidates) == 2
    merged_id = result.candidates[1].candidate_id
    assert result.suggestions[0].source_candidate_ids == ["one", merged_id]
    assert result.suggestions[0].chapter_span == [1, 2, 3]


@pytest.mark.asyncio
async def test_phase1c_does_not_auto_merge_stale_source_binding() -> None:
    async def decide(payload):
        return _boundary_result(
            payload,
            relation="same_scene",
            fusion_intent="integrate_both",
            confidence=0.99,
            basis="same objective",
        )

    stale = _candidate("left", chapter=1, start=0, end=20)
    stale.scene_chunks[0].source_content_hash = "f" * 64
    result = await Phase1cSceneFusionService(decide).run(
        [stale, _candidate("right", chapter=1, start=20, end=40)],
        [_chapter(1, "x" * 50)],
    )

    assert [item.candidate_id for item in result.candidates] == ["left", "right"]
    assert len(result.suggestions) == 1
    assert result.diagnostics[0]["exact_provenance"] is False
